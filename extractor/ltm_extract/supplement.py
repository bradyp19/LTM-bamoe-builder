"""Shape of the analyst supplement.

The supplement carries only what the documents cannot supply: a transcription
of an image-only flow, target-design rulings, assumptions and test scenarios.
`shape_problems` checks every value's type and every key before anything is
built, so a malformed file is reported in full rather than crashing later.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .docset import ExtractionError

SUPPLEMENT_KEYS = {"process", "figureTranscriptions", "design", "assumptions", "tests"}
TRANSCRIPTION_KEYS = {"cite", "image", "sha256", "inspected", "nodes", "flows"}
TRANSCRIBED_NODE_KEYS = {"id", "type", "name", "interface", "inputs"}
TRANSCRIBED_FLOW_KEYS = {"from", "to", "label"}
DESIGN_KEYS = {"process", "models", "typeMap", "nodes", "conditions", "flowRules"}
PROCESS_DESIGN_KEYS = {"id", "packageName", "descriptionTemplate"}
NODE_DESIGN_KEYS = {"type", "service", "inputs", "outputs", "notes", "support", "candidateGroups"}
SERVICE_KEYS = {"class", "operation"}
ASSUMPTION_KEYS = {"id", "text", "support"}
TEST_KEYS = {"name", "start", "complete", "expect", "steps"}
EXPECT_KEYS = {"status", "saves", "savedFields", "savedLists", "savedValues"}
SUPPORT_KEYS = {"cite", "quote"}

NODE_TYPES = {"start", "end", "userTask", "serviceTask", "xor"}
TASK_TYPES = {"userTask", "serviceTask"}
# org.kie.kogito.process.ProcessInstance.STATE_*
INSTANCE_STATES = {"PENDING", "ACTIVE", "COMPLETED", "ABORTED", "SUSPENDED", "ERROR"}
MIN_QUOTE_LENGTH = 8

JAVA_KEYWORDS = frozenset("""abstract assert boolean break byte case catch char class const
continue default do double else enum extends final finally float for goto if implements import
instanceof int interface long native new package private protected public return short static
strictfp super switch synchronized this throw throws transient try void volatile while true
false null""".split())

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROCESS_ID_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")
CLASS_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
PACKAGE_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
TYPE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
GENERATED_ASSUMPTION_ID_RE = re.compile(r"^T-\d+$")


def is_identifier(value) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER_RE.match(value)) \
        and value not in JAVA_KEYWORDS


def is_package(value) -> bool:
    return isinstance(value, str) and bool(PACKAGE_RE.match(value)) \
        and not any(part in JAVA_KEYWORDS for part in value.split("."))


def is_type_name(value) -> bool:
    return isinstance(value, str) and bool(TYPE_NAME_RE.match(value)) \
        and not any(part in JAVA_KEYWORDS for part in value.split("."))


def _one_of(value, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def load_supplement(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ExtractionError([f"supplement {path} cannot be read: {e.strerror or e}"]) from e
    except ValueError as e:
        raise ExtractionError([f"supplement {path} is not valid JSON: {e}"]) from e


class _Shape:
    def __init__(self):
        self.problems: list[str] = []

    def bad(self, path: str, message: str) -> None:
        self.problems.append(f"{path}: {message}")

    def obj(self, value, path: str, allowed: set[str] | None = None,
            required: tuple[str, ...] = ()) -> dict:
        """The value if it is an object (else {} and a problem), with its keys checked."""
        if not isinstance(value, dict):
            self.bad(path, "must be an object")
            return {}
        if allowed is not None:
            for key in sorted(set(value) - allowed):
                self.bad(f"{path}.{key}", f"is not allowed (allowed: {', '.join(sorted(allowed))})")
        for key in required:
            if key not in value:
                self.bad(f"{path}.{key}", "is required")
        return value

    def array(self, value, path: str) -> list:
        if not isinstance(value, list):
            self.bad(path, "must be a list")
            return []
        return value

    def text(self, value, path: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            self.bad(path, "must be a non-empty string")
            return False
        return True

    def names(self, value, path: str) -> None:
        for i, item in enumerate(self.array(value, path)):
            if not isinstance(item, str) or not item:
                self.bad(f"{path}[{i}]", "must be a variable name")

    def support(self, value, path: str) -> None:
        for i, entry in enumerate(self.array(value, path)):
            entry = self.obj(entry, f"{path}[{i}]", SUPPORT_KEYS, ("cite", "quote"))
            if "cite" in entry:
                self.text(entry["cite"], f"{path}[{i}].cite")
            if "quote" in entry and self.text(entry["quote"], f"{path}[{i}].quote") \
                    and len(entry["quote"].strip()) < MIN_QUOTE_LENGTH:
                self.bad(f"{path}[{i}].quote",
                         f"is too short to support anything (under {MIN_QUOTE_LENGTH} characters)")


def shape_problems(supplement, builtin_types: set[str]) -> list[str]:
    s = _Shape()
    if not isinstance(supplement, dict):
        return ["supplement: must be a JSON object"]
    for key in sorted(set(supplement) - SUPPLEMENT_KEYS):
        s.bad(f"supplement key '{key}'",
              "is not allowed: source facts are derived from the documents "
              f"(allowed: {', '.join(sorted(SUPPLEMENT_KEYS))})")
    if "process" not in supplement:
        s.bad("process", "is required: the documented process model name")
    else:
        s.text(supplement["process"], "process")

    for i, t in enumerate(s.array(supplement.get("figureTranscriptions", []),
                                  "figureTranscriptions")):
        path = f"figureTranscriptions[{i}]"
        t = s.obj(t, path, TRANSCRIPTION_KEYS, tuple(sorted(TRANSCRIPTION_KEYS)))
        for key in ("cite", "image", "sha256", "inspected"):
            if key in t:
                s.text(t[key], f"{path}.{key}")
        for j, n in enumerate(s.array(t.get("nodes", []), f"{path}.nodes")):
            npath = f"{path}.nodes[{j}]"
            n = s.obj(n, npath, TRANSCRIBED_NODE_KEYS, ("id", "type", "name"))
            for key in ("id", "name", "interface"):
                if key in n:
                    s.text(n[key], f"{npath}.{key}")
            if "type" in n and not _one_of(n["type"], NODE_TYPES):
                s.bad(f"{npath}.type", f"must be one of {sorted(NODE_TYPES)}")
            if "inputs" in n:
                s.names(n["inputs"], f"{npath}.inputs")
        for j, f in enumerate(s.array(t.get("flows", []), f"{path}.flows")):
            fpath = f"{path}.flows[{j}]"
            f = s.obj(f, fpath, TRANSCRIBED_FLOW_KEYS, ("from", "to"))
            for key in ("from", "to", "label"):
                if key in f:
                    s.text(f[key], f"{fpath}.{key}")

    design = s.obj(supplement.get("design", {}), "design", DESIGN_KEYS)
    process = s.obj(design.get("process", {}), "design.process", PROCESS_DESIGN_KEYS)
    if "id" in process and not (isinstance(process["id"], str)
                                and PROCESS_ID_RE.match(process["id"])):
        s.bad("design.process.id", "must be camelCase letters and digits")
    if "packageName" in process and not is_package(process["packageName"]):
        s.bad("design.process.packageName", "must be a Java package name")
    if "descriptionTemplate" in process and not isinstance(process["descriptionTemplate"], str):
        s.bad("design.process.descriptionTemplate must be a string", "non-string supplied")
    for record, cls in s.obj(design.get("models", {}), "design.models").items():
        if not (isinstance(cls, str) and CLASS_NAME_RE.match(cls)):
            s.bad(f"design.models['{record}']", "must be a Java class name")
    for doc_type, java_type in s.obj(design.get("typeMap", {}), "design.typeMap").items():
        if doc_type in builtin_types:
            s.bad(f"design.typeMap['{doc_type}']",
                  "is a built-in mapping and cannot be overridden")
        elif not is_type_name(java_type):
            s.bad(f"design.typeMap['{doc_type}']", "must be a Java type name")
    for node_id, d in s.obj(design.get("nodes", {}), "design.nodes").items():
        path = f"design.nodes.{node_id}"
        d = s.obj(d, path, NODE_DESIGN_KEYS)
        if "type" in d and not _one_of(d["type"], TASK_TYPES):
            s.bad(f"{path}.type", f"must be one of {sorted(TASK_TYPES)}")
        if "service" in d:
            service = s.obj(d["service"], f"{path}.service", SERVICE_KEYS, ("class", "operation"))
            if "class" in service and not (is_type_name(service["class"])
                                           and "." in service["class"]):
                s.bad(f"{path}.service.class", "must be a fully qualified Java class name")
            if "operation" in service and not is_identifier(service["operation"]):
                s.bad(f"{path}.service.operation", "must be a Java method name")
        for key in ("inputs", "outputs"):
            if key in d:
                s.names(d[key], f"{path}.{key}")
        if "notes" in d:
            s.text(d["notes"], f"{path}.notes")
        if "support" in d:
            s.support(d["support"], f"{path}.support")
        groups = d.get("candidateGroups")
        if "candidateGroups" in d and not (
                isinstance(groups, list) and groups
                and all(isinstance(g, str) and g.strip() and "," not in g for g in groups)):
            s.bad(f"{path}.candidateGroups must be a non-empty list",
                  "use group names without commas")
    for key, condition in s.obj(design.get("conditions", {}), "design.conditions").items():
        s.text(condition, f"design.conditions['{key}']")
    for key, rule in s.obj(design.get("flowRules", {}), "design.flowRules").items():
        path = f"design.flowRules['{key}']"
        rule = s.obj(rule, path, {"default", "priority"})
        if "default" in rule and rule["default"] is not True:
            s.bad(f"{path}.default must be true", "non-true value supplied")
        priority = rule.get("priority")
        if "priority" in rule and (type(priority) is not int or priority <= 0):
            s.bad(f"{path}.priority must be a positive integer", "invalid priority")

    seen: set[str] = set()
    for i, a in enumerate(s.array(supplement.get("assumptions", []), "assumptions")):
        path = f"assumptions[{i}]"
        a = s.obj(a, path, ASSUMPTION_KEYS, ("id", "text"))
        if "id" in a and s.text(a["id"], f"{path}.id"):
            if GENERATED_ASSUMPTION_ID_RE.match(a["id"]):
                s.bad(f"{path}.id", f"'{a['id']}' is reserved for generated items (T-n)")
            if a["id"] in seen:
                s.bad(f"{path}.id", f"'{a['id']}' is used more than once")
            seen.add(a["id"])
        if "text" in a:
            s.text(a["text"], f"{path}.text")
        if "support" in a:
            s.support(a["support"], f"{path}.support")

    seen = set()
    for i, t in enumerate(s.array(supplement.get("tests", []), "tests")):
        path = f"tests[{i}]"
        t = s.obj(t, path, TEST_KEYS, ("name", "start", "expect"))
        if "steps" in t:
            if "complete" in t:
                s.bad(path, "use steps or complete, not both")
            for j, step in enumerate(s.array(t["steps"], f"{path}.steps")):
                spath = f"{path}.steps[{j}]"
                step = s.obj(step, spath, {"task", "complete"}, ("task", "complete"))
                if "task" in step:
                    s.text(step["task"], f"{spath}.task")
                if "complete" in step:
                    s.obj(step["complete"], f"{spath}.complete")
        elif "complete" not in t:
            s.bad(f"{path}.complete", "is required for a single-task scenario")
        if "name" in t:
            if not is_identifier(t["name"]):
                s.bad(f"{path}.name", "must be a Java method name")
            elif t["name"] in seen:
                s.bad(f"{path}.name", f"'{t['name']}' is used more than once")
            else:
                seen.add(t["name"])
        for key in ("start", "complete"):
            if key in t:
                s.obj(t[key], f"{path}.{key}")
        if "expect" in t:
            expect = s.obj(t["expect"], f"{path}.expect", EXPECT_KEYS, ("status", "saves"))
            if "status" in expect and not _one_of(expect["status"], INSTANCE_STATES):
                s.bad(f"{path}.expect.status", f"must be one of {sorted(INSTANCE_STATES)}")
            saves = expect.get("saves", 0)
            if "steps" in t:
                counts = s.obj(saves, f"{path}.expect.saves")
                counts = {**counts, **s.obj(expect.get("savedLists", {}),
                                           f"{path}.expect.savedLists")}
                for store, count in counts.items():
                    if type(count) is not int or count < 0:
                        s.bad(f"{path}.expect.{store}", "must be a count")
                s.obj(expect.get("savedValues", {}), f"{path}.expect.savedValues")
            elif type(saves) is not int or saves < 0:
                s.bad(f"{path}.expect.saves", "must be a count")
            for name, value in s.obj(expect.get("savedFields", {}),
                                     f"{path}.expect.savedFields").items():
                if not isinstance(value, str):
                    s.bad(f"{path}.expect.savedFields.{name}", "must be a Java expression string")
    return s.problems
