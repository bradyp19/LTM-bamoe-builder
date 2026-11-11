"""Source facts + analyst supplement -> generator spec.

What the documents state is derived here and cannot be overridden: process
name, variables, types, model fields, evidence anchors, text-diagram nodes and
flows, and `<flag> = true|false` conditions. The supplement supplies only what
the documents cannot: a transcription of an image-only flow (pinned to the
image's hash), target-design choices, assumptions and test scenarios. Anything
still missing is an ExtractionError, never a default.

Transformations applied to a text diagram, each disclosed in the spec's
assumptions as T-n:
- a node with several outgoing branches gets an exclusive gateway, because the
  spec carries conditions on gateway flows;
- branches from one node to the same target become one flow;
- a task reached by several flows gets a converging exclusive gateway in front of it.
A null flag is treated as not true on both sides of a condition.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .docset import DocSet, ExtractionError, cite
from .facts import ProcessFacts, interfaces, process_models, record_types
from .flow_text import camel_case, parse_text_flow

SUPPLEMENT_KEYS = {"process", "figureTranscriptions", "design", "assumptions", "tests"}
DESIGN_KEYS = {"process", "models", "typeMap", "nodes", "conditions"}
NODE_DESIGN_KEYS = {"type", "service", "inputs", "outputs", "notes", "support"}
NODE_TYPES = {"start", "end", "userTask", "serviceTask", "xor"}
TASK_TYPES = {"userTask", "serviceTask"}

# Document type -> Java type, as verified by the register-project reference.
FIELD_TYPES = {
    "Integer": "Integer",
    "Text": "String",
    "Boolean": "Boolean",
    "Date": "java.time.LocalDate",
    "Decimal": "java.math.BigDecimal",
}
QUALIFIED = {"Integer": "java.lang.Integer", "String": "java.lang.String",
             "Boolean": "java.lang.Boolean"}

PROCESS_ID_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")
NODE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CONDITION_RE = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*(true|false)\b")


@dataclass
class Diagnostic:
    code: str
    message: str


@dataclass
class SpecResult:
    spec: dict
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class _Node:
    id: str
    type: str | None
    name: str
    interface: str | None = None
    inputs: list[str] | None = None
    source_cite: str | None = None
    declared: str | None = None
    fixed_doc: str | None = None
    transcribed: bool = False


@dataclass
class _Edge:
    source: str
    target: str
    labels: list[str | None]
    paragraphs: list[int] = field(default_factory=list)

    @property
    def label(self) -> str | None:
        return " / ".join(l for l in self.labels if l) or None


def load_supplement(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _split_prefix(name: str) -> tuple[str | None, str]:
    """'NSSOL Register Project' -> ('NSSOL', 'Register Project')."""
    tokens = name.split()
    if len(tokens) > 1 and tokens[0].isupper():
        return tokens[0], " ".join(tokens[1:])
    return None, name


def _pascal_case(text: str) -> str:
    camel = camel_case(text)
    return camel[0].upper() + camel[1:]


def _java_condition(label: str | None, boolean_vars: set[str]) -> str | None:
    matches = [m for m in CONDITION_RE.finditer(label or "") if m.group(1) in boolean_vars]
    if len(matches) != 1:
        return None
    var, value = matches[0].groups()
    return f"return {var} != null && {var};" if value == "true" else f"return {var} == null || !{var};"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _supports(value):
    if isinstance(value, dict):
        for s in value.get("support", []) if isinstance(value.get("support"), list) else []:
            yield s
        for v in value.values():
            yield from _supports(v)
    elif isinstance(value, list):
        for v in value:
            yield from _supports(v)


class _Builder:
    def __init__(self, docset: DocSet, supplement: dict):
        self.docset = docset
        self.supplement = supplement
        self.design = supplement.get("design", {}) if isinstance(supplement.get("design", {}), dict) else {}
        self.node_design: dict[str, dict] = self.design.get("nodes", {})
        self.problems: list[str] = []
        self.diagnostics: list[Diagnostic] = []
        self.transformations: dict[str, list[str]] = {"gateway": [], "merge": [], "join": []}

    def problem(self, message: str) -> None:
        if message not in self.problems:
            self.problems.append(message)

    def note(self, code: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, message))

    def fail_if_problems(self) -> None:
        if self.problems:
            raise ExtractionError(self.problems)

    # -- supplement checks -------------------------------------------------

    def check_supplement_shape(self) -> None:
        for key in sorted(set(self.supplement) - SUPPLEMENT_KEYS):
            self.problem(f"supplement key '{key}' is not allowed: source facts are derived from "
                         f"the documents (allowed: {', '.join(sorted(SUPPLEMENT_KEYS))})")
        if not isinstance(self.supplement.get("process"), str):
            self.problem("supplement needs 'process': the documented process model name")
        for key in sorted(set(self.design) - DESIGN_KEYS):
            self.problem(f"design key '{key}' is not allowed (allowed: {', '.join(sorted(DESIGN_KEYS))})")
        for node_id, d in self.node_design.items():
            for key in sorted(set(d) - NODE_DESIGN_KEYS):
                self.problem(f"design.nodes.{node_id}.{key} is not allowed "
                             f"(allowed: {', '.join(sorted(NODE_DESIGN_KEYS))})")

    def check_citations(self) -> None:
        for text in _strings(self.supplement):
            for doc, start, end in self.docset.find_citations(text):
                why = self.docset.check_citation(doc, start, end)
                if why:
                    self.problem(f"citation does not resolve: {why}")
        for support in _supports(self.supplement):
            refs = self.docset.find_citations(support.get("cite", ""))
            quote = support.get("quote")
            if len(refs) != 1 or not quote:
                self.problem(f"support entry needs one 'cite' and a 'quote': {support!r}")
                continue
            doc, start, end = refs[0]
            if self.docset.check_citation(doc, start, end):
                continue  # already reported above
            if quote not in self.docset.text(doc, start, end):
                self.problem(f"{cite(doc, start, end)} does not contain the quoted support {quote!r}")

    # -- flow --------------------------------------------------------------

    def transcribed_flow(self, pf: ProcessFacts):
        flow = pf.flow
        ref = flow.anchor.cite()
        entries = [t for t in self.supplement.get("figureTranscriptions", [])
                   if t.get("cite") == ref]
        if not entries:
            self.problem(f"{pf.name}: the flow is image-only ({ref}, {flow.image}); a figure "
                         "transcription is required and nothing was inferred")
            return None
        t = entries[0]
        actual = self.docset.image_sha256(flow.anchor.doc, flow.image)
        if t.get("image") != flow.image:
            self.problem(f"{ref}: transcription is of '{t.get('image')}', the document embeds "
                         f"'{flow.image}'")
        if t.get("sha256") != actual:
            self.problem(f"{ref}: transcription sha256 {t.get('sha256')} does not match "
                         f"{flow.image} in the document ({actual}); re-inspect the figure")
        if not t.get("inspected"):
            self.problem(f"{ref}: transcription needs an 'inspected' date")

        nodes = []
        for n in t.get("nodes", []):
            if not {"id", "type", "name"} <= set(n) or n["type"] not in NODE_TYPES:
                self.problem(f"{ref}: transcribed node needs id, name and a type in "
                             f"{sorted(NODE_TYPES)}: {n!r}")
                continue
            nodes.append(_Node(id=n["id"], type=n["type"], name=n["name"],
                               interface=n.get("interface"), inputs=n.get("inputs"),
                               transcribed=True))
        edges = [_Edge(f.get("from"), f.get("to"), [f.get("label")]) for f in t.get("flows", [])]
        self.note("flow-from-image-transcription",
                  f"{pf.name}: flow taken from the transcription of {flow.image} ({ref}), "
                  f"inspected {t.get('inspected')}; the image itself is not machine-read")
        figure = flow.figure or "figure"
        return nodes, edges, f"{flow.anchor.doc} {figure} (image-inspected {t.get('inspected')})"

    def text_flow(self, pf: ProcessFacts):
        doc = pf.flow.anchor.doc
        graph = parse_text_flow(pf.flow.lines)
        for d in graph.diagnostics:
            where = cite(doc, d.paragraph_index)
            if d.code == "flow-implicit-sequence":
                self.note(d.code, f"{where}: {d.message}")
            else:
                self.problem(f"{where}: {d.message}")

        nodes = [_Node(id=n.key, type=n.kind, name=n.name, interface=n.interface,
                       source_cite=cite(doc, n.start_index, n.end_index),
                       declared=n.declared_type) for n in graph.nodes]
        by_id = {n.id: n for n in nodes}

        merged: list[_Edge] = []
        index: dict[tuple[str, str], _Edge] = {}
        for e in graph.edges:
            key = (e.source, e.target)
            if key in index:
                index[key].labels.append(e.label)
                index[key].paragraphs.append(e.paragraph_index)
            else:
                index[key] = _Edge(e.source, e.target, [e.label], [e.paragraph_index])
                merged.append(index[key])
        for e in merged:
            if len(e.labels) > 1:
                labels = " and ".join(f"'{l}'" for l in e.labels)
                text = (f"Branches {labels} ({cite(doc, min(e.paragraphs), max(e.paragraphs))}) "
                        f"both lead from '{by_id[e.source].name}' to '{by_id[e.target].name}'; "
                        "emitted as one flow with no condition.")
                self.transformations["merge"].append(text)
                self.note("branches-merged", text)

        outgoing: dict[str, list[_Edge]] = {}
        for e in merged:
            outgoing.setdefault(e.source, []).append(e)
        out_nodes: list[_Node] = []
        gateways: dict[str, _Node] = {}
        for n in nodes:
            out_nodes.append(n)
            outs = outgoing.get(n.id, [])
            if len(outs) < 2:
                continue
            paragraphs = [p for e in outs for p in e.paragraphs]
            span = cite(doc, min(paragraphs), max(paragraphs))
            gateway = _Node(
                id=f"{n.id}Gateway", type="xor", name=f"After {n.name}",
                fixed_doc=(f"SYNTHESIZED: not a documented node. The branches at {span} leave "
                           f"'{n.name}' directly; this exclusive gateway carries their "
                           "conditions."))
            gateways[n.id] = gateway
            out_nodes.append(gateway)
            text = (f"Gateway '{gateway.name}' is synthesized: the branches at {span} leave "
                    f"'{n.name}' directly and no gateway is documented.")
            self.transformations["gateway"].append(text)
            self.note("gateway-synthesized", text)

        out_edges: list[_Edge] = []
        linked: set[str] = set()
        for e in merged:
            gateway = gateways.get(e.source)
            if gateway is None:
                out_edges.append(e)
                continue
            if e.source not in linked:
                linked.add(e.source)
                out_edges.append(_Edge(e.source, gateway.id, [None]))
            out_edges.append(_Edge(gateway.id, e.target, e.labels, e.paragraphs))

        return out_nodes, out_edges, pf.flow.anchor.cite()

    def add_merge_gateways(self, nodes: list[_Node], edges: list[_Edge]) -> None:
        """BAMOE rejects a task with several incoming flows, so they enter through
        a converging exclusive gateway placed just before it. Mutates both lists."""
        by_id = {n.id: n for n in nodes}
        for n in list(nodes):
            if n.type in ("start", "end", "xor"):
                continue
            entering = [e for e in edges if e.target == n.id]
            if len(entering) < 2:
                continue
            merge = _Node(
                id=f"{n.id}Merge", type="xor", name=f"Before {n.name}",
                fixed_doc=(f"SYNTHESIZED: not a documented node. {len(entering)} flows reach "
                           f"'{n.name}'; this converging exclusive gateway merges them."))
            nodes.insert(nodes.index(n), merge)
            for e in entering:
                e.target = merge.id
            edges.append(_Edge(merge.id, n.id, [None]))
            sources = ", ".join(f"'{by_id[e.source].name}'" for e in entering)
            text = (f"Merge gateway '{merge.name}' is synthesized: {len(entering)} flows "
                    f"(from {sources}) reach '{n.name}' and no merge gateway is documented; "
                    "BAMOE does not accept several incoming flows on a task.")
            self.transformations["join"].append(text)
            self.note("merge-gateway-synthesized", text)

    def check_structure(self, nodes: list[_Node], edges: list[_Edge]) -> None:
        ids = [n.id for n in nodes]
        for i in sorted({i for i in ids if ids.count(i) > 1}):
            self.problem(f"node id '{i}' is used more than once")
        for i in ids:
            if not NODE_ID_RE.match(i):
                self.problem(f"node id '{i}' is not a valid identifier")
        known = set(ids)
        pairs = set()
        for e in edges:
            for end in (e.source, e.target):
                if end not in known:
                    self.problem(f"flow {e.source}->{e.target} refers to unknown node '{end}'")
            if (e.source, e.target) in pairs:
                self.problem(f"more than one flow {e.source}->{e.target}")
            pairs.add((e.source, e.target))
        for node_id in sorted(set(self.node_design) - known):
            self.problem(f"design.nodes.{node_id}: the flow has no node '{node_id}' "
                         f"(nodes: {', '.join(ids)})")
        if [n.type for n in nodes].count("start") != 1:
            self.problem("the flow needs exactly one start node")
        incoming = {i: [e.source for e in edges if e.target == i] for i in ids}
        outgoing = {i: [e for e in edges if e.source == i] for i in ids}
        for n in nodes:
            if n.type == "start" and incoming[n.id]:
                self.problem(f"start node '{n.id}' has an incoming flow")
            if n.type != "start" and not incoming[n.id]:
                self.problem(f"node '{n.id}' has no incoming flow")
            if n.type == "end" and outgoing[n.id]:
                self.problem(f"end node '{n.id}' has an outgoing flow")
            if n.type != "end" and not outgoing[n.id]:
                self.problem(f"node '{n.id}' has no outgoing flow")
            if n.type != "xor" and len(outgoing[n.id]) > 1:
                self.problem(f"node '{n.id}' branches but is not a gateway")

    # -- build -------------------------------------------------------------

    def build(self) -> SpecResult:
        self.check_supplement_shape()
        self.fail_if_problems()
        self.check_citations()

        name = self.supplement["process"]
        processes = process_models(self.docset)
        if name not in processes:
            self.problem(f"no process model '{name}' in the documents "
                         f"(found: {', '.join(processes) or 'none'})")
            self.fail_if_problems()
        pf = processes[name]
        records = record_types(self.docset)
        ifaces = interfaces(self.docset)

        prefix, rest = _split_prefix(name)
        process_design = self.design.get("process", {})
        process_id = process_design.get("id") or camel_case(rest)
        package = process_design.get("packageName") or (prefix.lower() if prefix else None)
        if not PROCESS_ID_RE.match(process_id):
            self.problem(f"process id '{process_id}' must be camelCase letters and digits")
        if not package:
            self.problem(f"'{name}' has no application prefix to derive a package from; "
                         "set design.process.packageName")

        # types, variables, models
        type_map = {**FIELD_TYPES, **self.design.get("typeMap", {})}
        model_names: dict[str, str] = self.design.get("models", {})
        for record in sorted(set(model_names) - set(records)):
            self.problem(f"design.models: no record type '{record}' in the documents")

        def model_class(record: str) -> str:
            return model_names.get(record) or _pascal_case(_split_prefix(record)[1])

        if not pf.variables:
            self.problem(f"{name}: no process variables table found")
        variables, used_records, boolean_vars = [], [], set()
        for v in pf.variables:
            entry = {"name": v.name}
            record, is_list = None, False
            for suffix, listy in ((" record", False), (" list", True)):
                if v.type.endswith(suffix) and v.type[:-len(suffix)] in records:
                    record, is_list = v.type[:-len(suffix)], listy
            if record is None and v.type in records:
                record = v.type
            if record:
                if record not in used_records:
                    used_records.append(record)
                qualified = f"{package}.model.{model_class(record)}"
                if is_list:
                    entry["type"] = "java.util.List"
                    entry["elementType"] = qualified
                else:
                    entry["type"] = qualified
            elif v.type in type_map:
                entry["type"] = QUALIFIED.get(type_map[v.type], type_map[v.type])
                if v.type == "Boolean":
                    boolean_vars.add(v.name)
            else:
                self.problem(f"variable '{v.name}': type '{v.type}' ({v.anchor.cite()}) is neither "
                             "a documented record type nor in the type map")
                continue
            if v.required:
                entry["required"] = True
            entry["evidence"] = v.anchor.cite()
            variables.append(entry)
        var_names = {v.name for v in pf.variables}

        models = {}
        unmapped: set[str] = set()
        for record in used_records:
            facts = records[record]
            if not facts.fields:
                self.problem(f"record type '{record}' ({facts.anchor.cite()}) has no fields table")
                continue
            fields = []
            for f in facts.fields:
                if f.data_type in type_map:
                    fields.append({"name": f.name, "type": type_map[f.data_type]})
                elif f.data_type not in unmapped:
                    unmapped.add(f.data_type)
                    self.problem(f"type '{f.data_type}' (first at {f.anchor.cite()}, "
                                 f"{record}.{f.name}) is not in the type map; "
                                 f"rule on it in design.typeMap")
            models[model_class(record)] = {"fields": fields,
                                           "evidence": facts.fields_anchor.cite()}

        # flow
        if pf.flow.kind == "text":
            flow = self.text_flow(pf)
        elif pf.flow.kind == "image":
            flow = self.transcribed_flow(pf)
        else:
            self.problem(f"{name} ({pf.anchor.cite()}): no process flow is documented")
            flow = None
        if flow is None:
            self.fail_if_problems()
        nodes, edges, flow_cite = flow

        # node typing
        for n in nodes:
            d = self.node_design.get(n.id, {})
            if "type" not in d:
                if n.type is None:
                    shown = f"'{n.declared}'" if n.declared else "no task type"
                    self.problem(f"{n.id} ({n.source_cite}): the diagram declares {shown}; "
                                 f"design.nodes.{n.id}.type must rule on it")
            elif n.type is not None:
                self.problem(f"design.nodes.{n.id}.type: '{n.id}' is already "
                             f"{n.type} in the {'figure' if n.transcribed else 'diagram'}")
            elif d["type"] not in TASK_TYPES:
                self.problem(f"design.nodes.{n.id}.type must be one of {sorted(TASK_TYPES)}")
            else:
                n.type = d["type"]
        self.add_merge_gateways(nodes, edges)
        before = len(self.problems)
        self.check_structure(nodes, edges)
        if len(self.problems) > before:
            self.fail_if_problems()

        # nodes
        def check_vars(node_id: str, names: list[str]) -> None:
            for v in names:
                if v not in var_names:
                    self.problem(f"{node_id}: '{v}' is not a declared process variable "
                                 f"({pf.variables_anchor.cite()})")

        spec_nodes, interface_cites = [], []
        for n in nodes:
            d = self.node_design.get(n.id, {})
            out = {"id": n.id, "type": n.type, "name": n.name}
            parts = []
            inputs = outputs = None

            if n.type not in TASK_TYPES:
                for key in ("service", "inputs", "outputs"):
                    if key in d:
                        self.problem(f"design.nodes.{n.id}.{key}: '{n.id}' is a {n.type} node")
            if n.type == "userTask":
                iface = ifaces.get(n.interface) if n.interface else None
                if n.interface and iface:
                    parts.append(f"Interface: {n.interface} ({iface.anchor.cite()}).")
                    if iface.anchor.cite() not in interface_cites:
                        interface_cites.append(iface.anchor.cite())
                elif n.interface:
                    parts.append(f"Interface: {n.interface}.")
                    self.note("interface-not-found",
                              f"{n.id}: interface '{n.interface}' is not documented")
                if n.source_cite:
                    parts.append(f"Flow: {n.source_cite}.")
                derived = n.inputs is None and iface is not None and bool(iface.rule_inputs)
                if derived:
                    inputs = [r.name for r in iface.rule_inputs if r.name in var_names]
                    for r in iface.rule_inputs:
                        if r.name not in var_names:
                            self.note("rule-input-not-a-variable",
                                      f"{n.id}: rule input '{r.name}' ({r.anchor.cite()}) is not "
                                      "a process variable and is not a task input")
                    parts.append(f"Inputs: rule inputs at {iface.rule_inputs_anchor.cite()}.")
                elif n.inputs is not None:
                    inputs = list(n.inputs)
                if "inputs" in d:
                    if inputs is not None:
                        origin = "rule inputs" if derived else "figure transcription"
                        self.problem(f"design.nodes.{n.id}.inputs: the inputs of '{n.id}' come "
                                     f"from the {origin} and cannot be overridden")
                    else:
                        inputs = list(d["inputs"])
                if inputs is None:
                    inputs = []
                if "outputs" not in d:
                    self.problem(f"design.nodes.{n.id}.outputs: the outputs of user task "
                                 f"'{n.name}' are not documented and need a ruling")
                outputs = list(d.get("outputs", []))
                if "service" in d:
                    self.problem(f"design.nodes.{n.id}.service: '{n.id}' is a user task")
            elif n.type == "serviceTask":
                if n.source_cite:
                    parts.append(f"Flow: {n.source_cite}.")
                missing = [k for k in ("service", "inputs", "outputs") if not d.get(k)]
                service = d.get("service", {})
                if "service" not in missing and not {"class", "operation"} <= set(service):
                    missing.append("service.class/operation")
                if missing:
                    self.problem(f"design.nodes.{n.id}: service task '{n.name}' needs a ruling "
                                 f"on {', '.join(missing)}")
                inputs, outputs = list(d.get("inputs", [])), list(d.get("outputs", []))
                out_service = {"class": service.get("class"), "operation": service.get("operation")}
            elif n.fixed_doc:
                parts.append(n.fixed_doc)
            elif n.source_cite:
                parts.append(f"Flow: {n.source_cite}.")

            if d.get("notes"):
                parts.append(d["notes"])
            if parts:
                out["doc"] = " ".join(parts)
            if n.type == "serviceTask":
                out["service"] = out_service
            if n.type in TASK_TYPES:
                check_vars(n.id, inputs + outputs)
                out["inputs"], out["outputs"] = inputs, outputs
            spec_nodes.append(out)

        # flows
        by_id = {n.id: n for n in nodes}
        out_degree = {n.id: sum(1 for e in edges if e.source == n.id) for n in nodes}
        conditions: dict[str, str] = dict(self.design.get("conditions", {}))
        spec_flows = []
        for e in edges:
            flow_out = {"from": e.source, "to": e.target}
            if e.label:
                flow_out["name"] = e.label
            key = f"{e.source}->{e.target}"
            ruled = conditions.pop(key, None)
            if by_id[e.source].type == "xor" and out_degree[e.source] > 1:
                condition = ruled or _java_condition(e.label, boolean_vars)
                if condition:
                    flow_out["condition"] = condition
                else:
                    self.problem(f"flow {key}: no condition can be derived from the label "
                                 f"{e.label!r} (needs one '<Boolean variable> = true|false'); "
                                 f"rule on it in design.conditions['{key}']")
            elif ruled:
                self.problem(f"design.conditions['{key}']: that flow does not leave a "
                             "branching gateway")
            spec_flows.append(flow_out)
        for key in conditions:
            self.problem(f"design.conditions['{key}']: the flow has no such sequence flow")

        # tests
        tests = self.supplement.get("tests", [])
        record_vars = {v["name"]: v["type"].split(".")[-1] for v in variables
                       if ".model." in v["type"]}
        list_vars = {v["name"]: v["elementType"].split(".")[-1] for v in variables
                     if v["type"] == "java.util.List"}
        user_tasks = {n["id"] for n in spec_nodes if n["type"] == "userTask"}

        def check_values(label: str, values: dict) -> None:
            for var, value in values.items():
                if var not in var_names:
                    self.problem(f"test {label}: '{var}' is not a declared process variable")
                    continue
                if var in record_vars and isinstance(value, dict):
                    records = [(record_vars[var], value)]
                elif var in list_vars and isinstance(value, list):
                    records = [(list_vars[var], item) for item in value]
                else:
                    continue
                for model, item in records:
                    fields = {f["name"] for f in models.get(model, {}).get("fields", [])}
                    for name_ in sorted(set(item) - fields):
                        self.problem(f"test {label}: {model} has no field '{name_}'")

        for t in tests:
            label = t.get("name", "?")
            for phase in ("start", "complete"):
                check_values(label, t.get(phase, {}))
            for i, step in enumerate(t.get("steps", []), 1):
                if step.get("task") not in user_tasks:
                    self.problem(f"test {label} step {i}: '{step.get('task')}' is not a user task "
                                 f"(user tasks: {', '.join(sorted(user_tasks))})")
                check_values(f"{label} step {i}", step.get("complete", {}))

        # assumptions: authored first, then the disclosed transformations
        assumptions = [{"id": a["id"], "text": a["text"]}
                       for a in self.supplement.get("assumptions", [])]
        generated = (self.transformations["gateway"] + self.transformations["merge"]
                     + self.transformations["join"])
        assumptions += [{"id": f"T-{i}", "text": text} for i, text in enumerate(generated, 1)]

        self.fail_if_problems()
        evidence = [flow_cite]
        if pf.variables_anchor:
            evidence.append(pf.variables_anchor.cite())
        spec = {
            "process": {"id": process_id, "name": name, "packageName": package,
                        "evidence": ", ".join(evidence + interface_cites)},
            "models": models,
            "variables": variables,
            "nodes": spec_nodes,
            "flows": spec_flows,
            "tests": tests,
            "assumptions": assumptions,
        }
        return SpecResult(spec=spec, diagnostics=self.diagnostics)


def build_spec(docset: DocSet, supplement: dict) -> SpecResult:
    """Build the generator spec for the process the supplement names.

    Raises ExtractionError listing every problem if anything would have to be
    invented."""
    return _Builder(docset, supplement).build()
