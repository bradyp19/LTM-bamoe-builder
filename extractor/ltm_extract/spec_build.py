"""Source facts + analyst supplement -> generator spec.

What the documents state is derived here and cannot be overridden: process
name, variables, types, model fields, evidence anchors, text-diagram nodes and
flows, rule inputs, and conditions whose label is exactly
`<Boolean variable> = true|false`. The supplement supplies only what the
documents cannot: a transcription of an image-only flow (pinned to the image's
hash), target-design rulings, assumptions and test scenarios. Anything still
missing is an ExtractionError, never a default.

Checks run in stages and each stage lists all of its problems: supplement
shape and citations; process, types and flow; flow structure; rulings.

Transformations applied to a text diagram are disclosed in the spec's
assumptions as T-n (see README). A transcribed flow gets no T-n items; what was
done to it is reported as diagnostics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .docset import DocSet, ExtractionError, cite, cite_all
from .facts import ProcessFacts, interfaces, process_models, record_types
from .flow_text import camel_case, parse_text_flow
from .supplement import (CLASS_NAME_RE, PROCESS_ID_RE, TASK_TYPES, is_identifier, is_package,
                         load_supplement, shape_problems)

__all__ = ["Diagnostic", "SpecResult", "build_spec", "load_supplement"]

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

CONDITION_RE = re.compile(
    r"^(?:(?:yes|no)\s*/\s*)?(?:pv!)?([A-Za-z_]\w*)\s*=\s*(true|false)$", re.IGNORECASE)
UNVERIFIABLE_REF_RE = re.compile(r"\bFigure\s+\d+|§\s*\d+")
NULL_HANDLING = ("Conditions read a null flag as not true, so '= false' also matches null; "
                 "the documents do not say how a null flag is routed.")


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
    def merged(self) -> bool:
        return len(self.labels) > 1

    @property
    def label(self) -> str | None:
        return " / ".join(l for l in self.labels if l) or None


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
    """Java for a label that is exactly `<Boolean variable> = true|false`
    (optionally `Yes / ` or `No / ` first); None for anything else."""
    m = CONDITION_RE.match((label or "").strip())
    if not m or m.group(1) not in boolean_vars:
        return None
    var = m.group(1)
    if m.group(2).lower() == "true":
        return f"return {var} != null && {var};"
    return f"return {var} == null || !{var};"


def _literal_problem(java_type: str, value) -> str | None:
    """Why a scenario value cannot be written as a Java literal of that type."""
    simple = java_type.rsplit(".", 1)[-1] if java_type.startswith("java.lang.") else java_type
    expected = {"Boolean": bool, "Integer": int, "String": str}.get(simple)
    if expected is None:
        return f"is a {java_type}; scenarios can only set Boolean, Integer and String values"
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        return f"must be a {simple} value, not {value!r}"
    return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _quoted(labels: list[str | None]) -> str:
    return " and ".join(f"'{l}'" if l else "an unlabelled branch" for l in labels)


class _Builder:
    def __init__(self, docset: DocSet, supplement):
        self.docset = docset
        self.supplement = supplement
        self.problems: list[str] = []
        self.diagnostics: list[Diagnostic] = []
        # generated T-n items, in this order
        self.disclosures: dict[str, list[str]] = {
            k: [] for k in ("gateway", "merge", "join", "guard", "ruling", "null")}

    def problem(self, message: str) -> None:
        if message not in self.problems:
            self.problems.append(message)

    def note(self, code: str, message: str) -> None:
        if not any(d.code == code and d.message == message for d in self.diagnostics):
            self.diagnostics.append(Diagnostic(code, message))

    def disclose(self, kind: str, code: str, text: str) -> None:
        if (self.text_flow_used or kind == "join") and text not in self.disclosures[kind]:
            self.disclosures[kind].append(text)
        self.note(code, text)

    def fail_if_problems(self) -> None:
        if self.problems:
            raise ExtractionError(self.problems)

    def check_defined_once(self, kind: str, facts) -> None:
        if facts.other_definitions:
            where = " and ".join(a.cite() for a in [facts.anchor] + facts.other_definitions)
            self.problem(f"{kind} '{facts.name}' is documented more than once ({where}); "
                         "nothing was picked")

    # -- citations ---------------------------------------------------------

    def _resolved(self, text: str) -> list[tuple[str, int, int]]:
        """The citations in the text that resolve; the others become problems."""
        out = []
        for ref in self.docset.find_citations(text):
            why = self.docset.check_citation(*ref)
            if why:
                self.problem(f"citation does not resolve: {why}")
            else:
                out.append(ref)
        return out

    def check_claim(self, label: str, text, support) -> None:
        """Every paragraph a statement cites needs a quote from that paragraph."""
        cited = self._resolved(text) if isinstance(text, str) else []
        quoted = []
        for entry in support if isinstance(support, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("cite"), str) \
                    or not isinstance(entry.get("quote"), str):
                continue  # reported by the shape check
            refs = self.docset.find_citations(entry["cite"])
            if len(refs) != 1:
                self.problem(f"{label}: support cite {entry['cite']!r} must be one citation")
                continue
            if self.docset.check_citation(*refs[0]):
                self._resolved(entry["cite"])
                continue
            doc, start, end = refs[0]
            if entry["quote"] not in self.docset.text(doc, start, end):
                self.problem(f"{label}: {cite(doc, start, end)} does not contain the quoted "
                             f"support {entry['quote']!r}")
            else:
                quoted.append(refs[0])
        for doc, start, end in cited:
            if not any(d == doc and s <= end and start <= e for d, s, e in quoted):
                self.problem(f"{label}: {cite(doc, start, end)} is cited without a supporting "
                             "quote from it")

    def check_citations(self) -> None:
        supplement = self.supplement
        claims = []
        for a in supplement.get("assumptions", []) if isinstance(supplement.get("assumptions"), list) else []:
            if isinstance(a, dict):
                claims.append((f"assumption {a.get('id')}", a.get("text"), a.get("support")))
        design = supplement.get("design") if isinstance(supplement.get("design"), dict) else {}
        nodes = design.get("nodes") if isinstance(design.get("nodes"), dict) else {}
        for node_id, d in nodes.items():
            if isinstance(d, dict):
                claims.append((f"design.nodes.{node_id}", d.get("notes"), d.get("support")))
        for label, text, support in claims:
            self.check_claim(label, text, support)
        for text in _strings(supplement):
            self._resolved(text)
            for m in UNVERIFIABLE_REF_RE.finditer(text):
                self.note("unverifiable-reference",
                          f"'{m.group(0)}' in the supplement is not a paragraph citation and "
                          "was not checked")

    # -- flow --------------------------------------------------------------

    def transcribed_flow(self, pf: ProcessFacts, ifaces: dict):
        flow = pf.flow
        ref = flow.anchor.cite()
        transcriptions = self.supplement.get("figureTranscriptions", [])
        for t in transcriptions:
            if t.get("cite") != ref:
                self.problem(f"figureTranscriptions: {t.get('cite')} is not the flow figure of "
                             f"'{pf.name}' ({ref})")
        entries = [t for t in transcriptions if t.get("cite") == ref]
        if not entries:
            self.problem(f"{pf.name}: the flow is image-only ({ref}, {flow.image}); a figure "
                         "transcription is required and nothing was inferred")
            return None
        if len(entries) > 1:
            self.problem(f"{ref}: {len(entries)} transcriptions of the same figure; "
                         "nothing was picked")
            return None
        t = entries[0]
        actual = self.docset.image_sha256(flow.anchor.doc, flow.image)
        if t.get("image") != flow.image:
            self.problem(f"{ref}: transcription is of '{t.get('image')}', the document embeds "
                         f"'{flow.image}'")
        if t.get("sha256") != actual:
            self.problem(f"{ref}: transcription sha256 {t.get('sha256')} does not match "
                         f"{flow.image} in the document ({actual}); re-inspect the figure")

        nodes = []
        for n in t.get("nodes", []):
            if n.get("interface") and n["interface"] not in ifaces:
                self.problem(f"{ref}: transcribed node '{n['id']}' names interface "
                             f"'{n['interface']}', which the documents do not define")
            nodes.append(_Node(id=n["id"], type=n["type"], name=n["name"],
                               interface=n.get("interface"), inputs=n.get("inputs"),
                               transcribed=True))
        edges = [_Edge(f["from"], f["to"], [f.get("label")]) for f in t.get("flows", [])]
        self.note("flow-from-image-transcription",
                  f"{pf.name}: flow taken from the transcription of {flow.image} ({ref}), "
                  f"inspected {t.get('inspected')}; the image itself is not machine-read")
        figure = flow.figure or "figure"
        return nodes, edges, f"{flow.anchor.doc} {figure} (image-inspected {t.get('inspected')})"

    def text_flow(self, pf: ProcessFacts):
        doc = pf.flow.anchor.doc
        if self.supplement.get("figureTranscriptions"):
            self.problem(f"figureTranscriptions: the flow of '{pf.name}' is a text diagram "
                         f"({pf.flow.anchor.cite()}); a transcription is not used")
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
            self.disclose("gateway", "gateway-synthesized",
                          f"Gateway '{gateway.name}' is synthesized: the branches at {span} "
                          f"leave '{n.name}' directly and no gateway is documented.")

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
        """Keep BAMOE's single-incoming-task requirement without losing loopbacks."""
        by_id = {n.id: n for n in nodes}
        for n in list(nodes):
            if n.type not in TASK_TYPES:
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
            self.disclose(
                "join", "merge-gateway-synthesized",
                f"Merge gateway '{merge.name}' is synthesized: {len(entering)} flows "
                f"(from {sources}) reach '{n.name}' and no merge gateway is documented; "
                "BAMOE does not accept several incoming flows on a task.")

    def check_structure(self, nodes: list[_Node], edges: list[_Edge], var_names: set[str]) -> None:
        ids = [n.id for n in nodes]
        for i in sorted({i for i in ids if ids.count(i) > 1}):
            self.problem(f"node id '{i}' is used more than once")
        for i in ids:
            if not is_identifier(i):
                self.problem(f"node id '{i}' is not a valid identifier")
            elif i in var_names:
                self.problem(f"node id '{i}' is also a process variable name; the generated "
                             "BPMN ids would collide")
        known = set(ids)
        if self.process_id in known or self.process_id in var_names:
            self.problem(f"process id '{self.process_id}' is also a node or variable id; "
                         "rule on it in design.process.id")
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
        starts = [n.id for n in nodes if n.type == "start"]
        if len(starts) != 1:
            self.problem("the flow needs exactly one start node")
        if not any(n.type == "end" for n in nodes):
            self.problem("the flow has no end node")

        incoming = {i: [e.source for e in edges if e.target == i] for i in ids}
        outgoing = {i: [e.target for e in edges if e.source == i] for i in ids}
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
            if n.type == "xor" and len(outgoing[n.id]) < 2 and len(incoming[n.id]) < 2:
                self.problem(f"gateway '{n.id}' has fewer than two outgoing flows "
                             "and is not a converging gateway")

        def reach(seeds: list[str], step: dict[str, list[str]]) -> set[str]:
            seen, todo = set(seeds), list(seeds)
            while todo:
                for nxt in step.get(todo.pop(), []):
                    if nxt in known and nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            return seen

        if len(starts) == 1:
            for i in sorted(known - reach(starts, outgoing), key=ids.index):
                self.problem(f"node '{i}' cannot be reached from the start")
        ends = [n.id for n in nodes if n.type == "end"]
        if ends:
            for i in sorted(known - reach(ends, incoming), key=ids.index):
                self.problem(f"node '{i}' can never reach an end")

    # -- build -------------------------------------------------------------

    def build(self) -> SpecResult:
        self.problems += shape_problems(self.supplement, set(FIELD_TYPES))
        if isinstance(self.supplement, dict):
            self.check_citations()
        self.fail_if_problems()

        supplement = self.supplement
        self.design = supplement.get("design", {})
        self.node_design: dict[str, dict] = self.design.get("nodes", {})
        name = supplement["process"]
        processes = process_models(self.docset)
        if name not in processes:
            self.problem(f"no process model '{name}' in the documents "
                         f"(found: {', '.join(processes) or 'none'})")
            for doc in self.docset.documents:
                for section in self.docset.sections(doc):
                    if name.casefold() in section.title.casefold():
                        self.problem(
                            f"{cite(doc, section.paragraph_index)} has a heading "
                            f"'{section.title}' that mentions '{name}' but is not shaped "
                            "'Process Model: <name>'")
            self.fail_if_problems()
        pf = processes[name]
        self.text_flow_used = pf.flow.kind == "text"
        self.check_defined_once("process model", pf)
        records = record_types(self.docset)
        ifaces = interfaces(self.docset)

        prefix, rest = _split_prefix(name)
        process_design = self.design.get("process", {})
        process_id = process_design.get("id") or camel_case(rest)
        self.process_id = process_id
        package = process_design.get("packageName") or (prefix.lower() if prefix else None)
        template = process_design.get("descriptionTemplate")
        if not PROCESS_ID_RE.match(process_id):
            self.problem(f"process id '{process_id}' derived from '{name}' is not camelCase "
                         "letters and digits; set design.process.id")
        if not package or not is_package(package):
            self.problem(f"no Java package can be derived from '{name}' "
                         f"(got {package!r}); set design.process.packageName")

        # types, variables, models
        type_map = {**FIELD_TYPES, **self.design.get("typeMap", {})}
        model_names: dict[str, str] = self.design.get("models", {})
        for record in sorted(set(model_names) - set(records)):
            self.problem(f"design.models: no record type '{record}' in the documents")

        def model_class(record: str) -> str:
            return model_names.get(record) or _pascal_case(_split_prefix(record)[1])

        if not pf.variables:
            self.problem(f"{name} ({pf.anchor.cite()}): no process variables table found")
        variables, used_records, boolean_vars = [], [], set()
        seen_names: set[str] = set()
        for v in pf.variables:
            if not is_identifier(v.name):
                self.problem(f"variable '{v.name}' ({v.anchor.cite()}) is not a valid Java "
                             "identifier")
                continue
            if v.name in seen_names:
                self.problem(f"variable '{v.name}' is declared more than once "
                             f"({v.anchor.cite()})")
                continue
            seen_names.add(v.name)
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
        var_names = seen_names
        variables_cite = cite_all(pf.variables_anchors) or "no variables table"
        for ref in sorted(set(re.findall(r"#\{\s*([A-Za-z_]\w*)", template or ""))):
            if ref not in var_names:
                self.problem(f"design.process.descriptionTemplate: '{ref}' is not a declared "
                             f"process variable ({variables_cite})")

        models = {}
        unmapped: set[str] = set()
        class_of: dict[str, str] = {}
        for record in used_records:
            facts = records[record]
            self.check_defined_once("record type", facts)
            cls = model_class(record)
            if not CLASS_NAME_RE.match(cls):
                self.problem(f"record type '{record}' gives class name '{cls}', which is not a "
                             f"Java class name; rule on it in design.models")
                continue
            if cls in class_of:
                self.problem(f"record types '{class_of[cls]}' and '{record}' both map to model "
                             f"class '{cls}'; rule on it in design.models")
                continue
            class_of[cls] = record
            if not facts.fields:
                self.problem(f"record type '{record}' ({facts.anchor.cite()}) has no documented "
                             "fields")
                continue
            fields = []
            field_names: set[str] = set()
            for f in facts.fields:
                if f.name in field_names:
                    self.problem(f"{record}.{f.name} is declared more than once "
                                 f"({f.anchor.cite()})")
                    continue
                field_names.add(f.name)
                if not is_identifier(f.name):
                    self.problem(f"{record}.{f.name} ({f.anchor.cite()}) is not a valid Java "
                                 "identifier")
                elif f.data_type in type_map:
                    fields.append({"name": f.name, "type": type_map[f.data_type]})
                elif f.data_type not in unmapped:
                    unmapped.add(f.data_type)
                    self.problem(f"type '{f.data_type}' (first at {f.anchor.cite()}, "
                                 f"{record}.{f.name}) is not in the type map; "
                                 f"rule on it in design.typeMap")
            models[cls] = {"fields": fields, "evidence": cite_all(facts.fields_anchors)}

        # flow
        if pf.flow.kind == "text":
            flow = self.text_flow(pf)
        elif pf.flow.kind == "image":
            flow = self.transcribed_flow(pf, ifaces)
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
            else:
                n.type = d["type"]
        before = len(self.problems)
        self.check_structure(nodes, edges, var_names)
        if len(self.problems) > before:
            self.fail_if_problems()
        self.add_merge_gateways(nodes, edges)
        # Check the synthesized identifiers as well as the source identifiers.
        self.check_structure(nodes, edges, var_names)

        # nodes
        def check_vars(node_id: str, names: list[str]) -> None:
            for v in names:
                if v not in var_names:
                    self.problem(f"{node_id}: '{v}' is not a declared process variable "
                                 f"({variables_cite})")

        spec_nodes, interface_cites = [], []
        for n in nodes:
            d = self.node_design.get(n.id, {})
            if n.type is None:
                continue  # already reported: needs a type ruling
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
                    self.check_defined_once("interface", iface)
                    parts.append(f"Interface: {n.interface} ({iface.anchor.cite()}).")
                    if iface.anchor.cite() not in interface_cites:
                        interface_cites.append(iface.anchor.cite())
                elif n.interface:
                    parts.append(f"Interface: {n.interface}.")
                    self.problem(f"{n.id}: interface '{n.interface}' is not documented; "
                                 "task inputs cannot be derived")
                if n.source_cite:
                    parts.append(f"Flow: {n.source_cite}.")
                rule_inputs = [r.name for r in iface.rule_inputs if r.name in var_names] \
                    if iface else []
                derived = n.inputs is None and bool(iface and iface.rule_inputs)
                if derived:
                    inputs = rule_inputs
                    for r in iface.rule_inputs:
                        if r.name not in var_names:
                            self.note("rule-input-not-a-variable",
                                      f"{n.id}: rule input '{r.name}' ({r.anchor.cite()}) is not "
                                      "a process variable and is not a task input")
                    parts.append(f"Inputs: rule inputs at {cite_all(iface.rule_inputs_anchors)}.")
                elif n.inputs is not None:
                    inputs = list(n.inputs)
                    if iface and iface.rule_inputs and sorted(inputs) != sorted(rule_inputs):
                        self.note("inputs-differ-from-rule-inputs",
                                  f"{n.id}: the figure gives inputs {', '.join(inputs) or 'none'}; "
                                  f"the rule inputs at {cite_all(iface.rule_inputs_anchors)} are "
                                  f"{', '.join(rule_inputs) or 'none'}. The figure was followed.")
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
                missing = [k for k in ("service", "inputs", "outputs") if k not in d]
                if missing:
                    self.problem(f"design.nodes.{n.id}: service task '{n.name}' needs a ruling "
                                 f"on {', '.join(missing)}")
                inputs, outputs = list(d.get("inputs", [])), list(d.get("outputs", []))
                if not missing and (len(inputs) != 1 or len(outputs) != 1):
                    self.problem(f"design.nodes.{n.id}: a service task takes exactly one input "
                                 "and one output (the generator binds one Parameter and one "
                                 "Result)")
                service = d.get("service", {})
            elif n.fixed_doc:
                parts.append(n.fixed_doc)
            elif n.source_cite:
                parts.append(f"Flow: {n.source_cite}.")

            if d.get("notes"):
                parts.append(d["notes"])
            if parts:
                out["doc"] = " ".join(parts)
            if n.type == "serviceTask":
                out["service"] = {"class": service.get("class"),
                                  "operation": service.get("operation")}
            if n.type in TASK_TYPES:
                check_vars(n.id, inputs + outputs)
                out["inputs"], out["outputs"] = inputs, outputs
            if "candidateGroups" in d:
                if n.type == "userTask":
                    out["candidateGroups"] = list(d["candidateGroups"])
                else:
                    self.problem(f"design.nodes.{n.id}.candidateGroups: '{n.id}' is not a user task")
            spec_nodes.append(out)

        # flows
        by_id = {n.id: n for n in nodes}
        out_degree = {n.id: sum(1 for e in edges if e.source == n.id) for n in nodes}
        conditions: dict[str, str] = dict(self.design.get("conditions", {}))
        flow_rules: dict[str, dict] = dict(self.design.get("flowRules", {}))
        defaults: dict[str, int] = {}
        spec_flows = []
        used_conditions: dict[str, dict[str, str]] = {}
        derived_any = False
        for e in edges:
            flow_out = {"from": e.source, "to": e.target}
            if e.label:
                flow_out["name"] = e.label
            key = f"{e.source}->{e.target}"
            ruled = conditions.pop(key, None)
            rule = flow_rules.pop(key, {})
            where = f" ({cite(pf.flow.anchor.doc, min(e.paragraphs), max(e.paragraphs))})" \
                if e.paragraphs else ""
            on_gateway = by_id[e.source].type == "xor" and out_degree[e.source] > 1
            if rule and not on_gateway:
                self.problem(f"design.flowRules['{key}']: that flow does not leave a "
                             "branching gateway")
            if rule.get("default"):
                defaults[e.source] = defaults.get(e.source, 0) + 1
                flow_out["default"] = True
                if ruled:
                    self.problem(f"design.conditions['{key}']: the default flow cannot "
                                 "also have a condition")
                self.disclose("ruling", "default-flow-from-design",
                              f"Flow {key} is the default by design ruling; "
                              f"its label {e.label!r} is not enforced.")
            if "priority" in rule:
                flow_out["priority"] = rule["priority"]
            if on_gateway and rule.get("default"):
                pass
            elif on_gateway:
                derived = None if e.merged else _java_condition(e.label, boolean_vars)
                if derived and ruled:
                    self.problem(f"design.conditions['{key}']: the condition comes from the "
                                 f"label {e.label!r} and cannot be overridden")
                elif derived:
                    flow_out["condition"] = derived
                    derived_any = True
                    var = CONDITION_RE.match(e.label.strip()).group(1)
                    if not any(var in n.get("outputs", []) for n in spec_nodes):
                        self.note("condition-variable-never-set",
                                  f"flow {key} tests '{var}', which no task outputs; it can "
                                  "only be set when the process starts")
                elif ruled:
                    flow_out["condition"] = ruled
                    self.disclose("ruling", "condition-from-design",
                                  f"The condition on flow {key}{where} is a design ruling; it is "
                                  f"not derived from the label {e.label!r}.")
                else:
                    why = ("it merges the branches " + _quoted(e.labels)) if e.merged else \
                        f"the label {e.label!r} is not exactly '<Boolean variable> = true|false'"
                    self.problem(f"flow {key}{where}: no condition can be derived because {why}; "
                                 f"rule on it in design.conditions['{key}']")
                if "condition" in flow_out:
                    earlier = used_conditions.setdefault(e.source, {})
                    if flow_out["condition"] in earlier:
                        self.problem(f"flows {earlier[flow_out['condition']]} and {key} leave "
                                     f"gateway '{e.source}' with the same condition")
                    earlier[flow_out["condition"]] = key
            else:
                if ruled:
                    self.problem(f"design.conditions['{key}']: that flow does not leave a "
                                 "gateway")
                if e.merged:
                    self.disclose("merge", "branches-merged",
                                  f"Branches {_quoted(e.labels)}{where} both lead from "
                                  f"'{by_id[e.source].name}' to '{by_id[e.target].name}'; "
                                  "emitted as one flow with no condition.")
                elif e.label and out_degree[e.source] == 1:
                    self.disclose("guard", "guard-not-enforced",
                                  f"The only flow leaving '{by_id[e.source].name}' is labelled "
                                  f"{e.label!r}{where}; no other route is documented, so the "
                                  "guard is not enforced.")
            if on_gateway and e.merged and "condition" in flow_out:
                self.disclose("merge", "branches-merged",
                              f"Branches {_quoted(e.labels)}{where} both lead from "
                              f"'{by_id[e.source].name}' to '{by_id[e.target].name}'; emitted as "
                              "one flow whose condition is a design ruling.")
            spec_flows.append(flow_out)
        for key in conditions:
            self.problem(f"design.conditions['{key}']: the flow has no such sequence flow")
        for key in flow_rules:
            self.problem(f"design.flowRules['{key}']: the flow has no such sequence flow")
        for source, count in defaults.items():
            if count > 1:
                self.problem(f"gateway '{source}' has more than one default flow")
        for source in {f["from"] for f in spec_flows if "priority" in f}:
            unranked = [f["to"] for f in spec_flows
                        if f["from"] == source and "priority" not in f and not f.get("default")]
            if unranked:
                self.problem(f"gateway '{source}': priorities must be given for every branch "
                             f"except the default flow (missing: {', '.join(unranked)})")
        if derived_any:
            self.disclose("null", "null-handling", NULL_HANDLING)

        # tests
        tests = supplement.get("tests", [])
        var_types = {v["name"]: v["type"] for v in variables}
        variable_defs = {v["name"]: v for v in variables}
        user_tasks = {n["id"] for n in spec_nodes if n["type"] == "userTask"}
        stores = {n["service"]["class"].split(".")[-1]: n for n in spec_nodes
                  if n["type"] == "serviceTask" and n["service"].get("class")}
        for n in stores.values():
            if len(n["inputs"]) == len(n["outputs"]) == 1:
                vin, vout = (variable_defs.get(names[0], {})
                             for names in (n["inputs"], n["outputs"]))
                if (vin.get("type"), vin.get("elementType")) != (
                        vout.get("type"), vout.get("elementType")):
                    self.problem(f"service task '{n['id']}': the generated test double "
                                 "returns its input, so input and output types must match")

        def check_record(where: str, cls: str, value) -> None:
            if not isinstance(value, dict):
                self.problem(f"{where} must be an object of {cls} fields")
                return
            field_types = {f["name"]: f["type"] for f in models.get(cls, {}).get("fields", [])}
            for field_name, field_value in value.items():
                if field_name not in field_types:
                    self.problem(f"test {test_name}: {cls} has no field '{field_name}'")
                    continue
                why = _literal_problem(field_types[field_name], field_value)
                if why:
                    self.problem(f"{where}.{field_name} {why}")

        for t in tests:
            test_name = t["name"]
            phases = [(phase, t.get(phase, {})) for phase in ("start", "complete")]
            for i, step in enumerate(t.get("steps", []), 1):
                if step["task"] not in user_tasks:
                    self.problem(f"test {test_name} step {i}: '{step['task']}' is not a user task "
                                 f"(user tasks: {', '.join(sorted(user_tasks))})")
                phases.append((f"step {i}", step["complete"]))
            if "steps" not in t:
                record_var = next((v["name"] for v in variables if ".model." in v["type"]), None)
                if len(user_tasks) != 1 or len(stores) != 1 or record_var is None:
                    self.problem(f"test {test_name}: use steps for a process other than one "
                                 "user task, one store and a record variable")
                elif record_var not in t["start"]:
                    self.problem(f"test {test_name}: start must include record variable "
                                 f"'{record_var}' for the single-task template")
            for phase, values in phases:
                if len(values) > 10:
                    self.problem(f"test {test_name}: {phase} exceeds the generator's "
                                 "10-entry Map.of limit")
                for var, value in values.items():
                    where = f"test {test_name}: {phase}.{var}"
                    if var not in var_types:
                        if var not in var_names:
                            self.problem(f"test {test_name}: '{var}' is not a declared process "
                                         "variable")
                        continue
                    if var_types[var] == "java.util.List":
                        if not isinstance(value, list):
                            self.problem(f"{where} must be a list of record objects")
                            continue
                        cls = variable_defs[var]["elementType"].split(".")[-1]
                        for i, item in enumerate(value):
                            check_record(f"{where}[{i}]", cls, item)
                    elif ".model." not in var_types[var]:
                        why = _literal_problem(var_types[var], value)
                        if why:
                            self.problem(f"{where} {why}")
                    else:
                        check_record(where, var_types[var].split(".")[-1], value)
            if "steps" in t:
                for key in ("saves", "savedLists", "savedValues"):
                    for store, expected in t["expect"].get(key, {}).items():
                        if store not in stores:
                            self.problem(f"test {test_name}: {key} names unknown store '{store}'")
                            continue
                        inputs = stores[store]["inputs"]
                        var = variable_defs.get(inputs[0], {}) if inputs else {}
                        if key == "savedLists" and var.get("type") != "java.util.List":
                            self.problem(f"test {test_name}: savedLists requires a list store "
                                         f"('{store}' is not one)")
                        if key == "savedValues":
                            why = _literal_problem(var.get("type", ""), expected)
                            if why:
                                self.problem(f"test {test_name}: savedValues.{store} {why}")
                        if key != "saves" and t["expect"]["saves"].get(store, 0) < 1:
                            self.problem(f"test {test_name}: {key}.{store} needs at least one "
                                         "expected save")
        if not tests:
            self.note("no-test-scenarios",
                      f"{name}: the supplement has no test scenarios, so the generated process "
                      "test will be empty")

        # what the documents state that the spec does not carry
        if pf.attributes:
            anchors = [a for _, a in pf.attributes.values()]
            self.note("not-carried",
                      f"process attributes ({', '.join(pf.attributes)}) at "
                      f"{cite(anchors[0].doc, anchors[0].start, anchors[-1].end)} are not carried "
                      "into the spec")
        columns = ["Parameter"] if any(v.parameter for v in pf.variables) else []
        columns += [c for c in dict.fromkeys(k for v in pf.variables for k in v.extra)]
        if columns:
            self.note("not-carried",
                      f"variable columns {', '.join(columns)} ({variables_cite}) are not carried "
                      "into the spec")

        # assumptions: authored first, then the generated disclosures
        assumptions = [{"id": a["id"], "text": a["text"]}
                       for a in supplement.get("assumptions", [])]
        generated = [text for kind in self.disclosures for text in self.disclosures[kind]]
        assumptions += [{"id": f"T-{i}", "text": text} for i, text in enumerate(generated, 1)]

        self.fail_if_problems()
        evidence = [flow_cite] + [a.cite() for a in pf.variables_anchors]
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
        if template:
            spec["process"]["descriptionTemplate"] = template
        return SpecResult(spec=spec, diagnostics=self.diagnostics)


def build_spec(docset: DocSet, supplement: dict) -> SpecResult:
    """Build the generator spec for the process the supplement names.

    Raises ExtractionError listing the problems if anything would have to be
    invented."""
    return _Builder(docset, supplement).build()
