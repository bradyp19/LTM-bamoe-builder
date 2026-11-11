"""Text flow diagrams -> nodes and edges.

LTM draws flows inside a code fence with box-drawing rails:

    START
      │
      ▼
    [User Task: Name]
      │   Interface: SOME_INTERFACE
      ├──[flag = true]──▶ END
      └──[other = true]──▶
            ▼
         [Next Node]

Only what is drawn is returned. A node's type comes from its declared prefix
or stays None; a branch target that cannot be matched is reported, never
guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ltm_reader import Paragraph

RAIL_CHARS = " \t│"
ARROW = "▼"
BRANCH_RE = re.compile(r"^[├└]─+\[(.+?)\]─+▶\s*(.*)$")
BRACKET_RE = re.compile(r"^\[(.+)\]$")
INTERFACE_RE = re.compile(r"^Interface:\s*(\S+)$")
BACK_TO = "back to "
DECLARED_KINDS = {"User Task": "userTask", "Service Task": "serviceTask"}


@dataclass
class Annotation:
    text: str
    paragraph_index: int


@dataclass
class FlowNode:
    key: str
    kind: str | None  # start | end | userTask | serviceTask | None (not declared)
    name: str
    start_index: int
    end_index: int
    declared_type: str | None = None
    interface: str | None = None
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class FlowEdge:
    source: str
    target: str
    label: str | None
    paragraph_index: int
    note: str | None = None


@dataclass
class FlowDiagnostic:
    code: str
    message: str
    paragraph_index: int


@dataclass
class FlowGraph:
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    diagnostics: list[FlowDiagnostic] = field(default_factory=list)


def camel_case(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "node"
    return words[0][0].lower() + words[0][1:] + "".join(w[0].upper() + w[1:] for w in words[1:])


@dataclass
class _Pending:
    owner: FlowNode
    label: str
    paragraph_index: int


class _Parser:
    def __init__(self):
        self.graph = FlowGraph()
        self.groups: list[tuple[int, FlowNode]] = []  # (branch column, owning node)
        self.prev: FlowNode | None = None  # source of the next sequence edge
        self.last: FlowNode | None = None  # node that annotations attach to
        self.pending: _Pending | None = None
        self.arrow_seen = False
        self.end_count = 0

    def diag(self, code: str, message: str, index: int) -> None:
        self.graph.diagnostics.append(FlowDiagnostic(code, message, index))

    def add_node(self, kind, name, index, declared_type=None, base_key=None) -> FlowNode:
        keys = {n.key for n in self.graph.nodes}
        base = base_key or camel_case(name)
        key, n = base, 1
        while key in keys:
            n += 1
            key = f"{base}{n}"
        node = FlowNode(key=key, kind=kind, name=name, start_index=index, end_index=index,
                        declared_type=declared_type)
        self.graph.nodes.append(node)
        return node

    def add_end(self, index: int) -> FlowNode:
        self.end_count += 1
        return self.add_node("end", "End", index, base_key=f"end{self.end_count}")

    def flush_pending(self) -> None:
        if self.pending:
            self.diag("flow-dangling-branch",
                      f"branch [{self.pending.label}] has no target", self.pending.paragraph_index)
            self.pending = None

    def on_branch(self, column: int, label: str, target: str, index: int) -> None:
        self.flush_pending()
        while self.groups and self.groups[-1][0] > column:
            self.groups.pop()
        if self.groups and self.groups[-1][0] == column:
            owner = self.groups[-1][1]
        elif self.prev is not None:
            owner = self.prev
            self.groups.append((column, owner))
        else:
            self.diag("flow-orphan-branch", f"branch [{label}] has no source node", index)
            return
        self.prev = None
        if not target:
            self.pending = _Pending(owner, label, index)
            return
        if target == "END":
            self.graph.edges.append(FlowEdge(owner.key, self.add_end(index).key, label, index))
            return
        reference = target[len(BACK_TO):] if target.startswith(BACK_TO) else target
        matches = [n for n in self.graph.nodes
                   if n.kind not in ("start", "end")
                   and (reference == n.name or reference.startswith(n.name + " "))]
        if not matches:
            self.diag("flow-unresolved-target",
                      f"branch [{label}] points at '{target}', which names no node drawn "
                      "above it", index)
            return
        node = max(matches, key=lambda n: len(n.name))
        note = reference[len(node.name):].strip() or None
        self.graph.edges.append(FlowEdge(owner.key, node.key, label, index, note))

    def on_node(self, content: str, index: int) -> None:
        if content == "START":
            node = self.add_node("start", "Start", index, base_key="start")
        elif content == "END":
            node = self.add_end(index)
        else:
            inner = BRACKET_RE.match(content).group(1).strip()
            declared, sep, name = inner.partition(":")
            if sep:
                declared, name = declared.strip(), name.strip()
                node = self.add_node(DECLARED_KINDS.get(declared), name, index,
                                     declared_type=declared)
            else:
                node = self.add_node(None, inner, index)

        if self.pending:
            self.graph.edges.append(FlowEdge(self.pending.owner.key, node.key,
                                             self.pending.label, self.pending.paragraph_index))
            self.pending = None
        elif self.prev is not None:
            if not self.arrow_seen:
                self.diag("flow-implicit-sequence",
                          f"'{node.name}' follows '{self.prev.name}' with no arrow between them",
                          index)
            self.graph.edges.append(FlowEdge(self.prev.key, node.key, None, index))
        elif self.graph.nodes[0] is not node:
            self.diag("flow-disconnected-node", f"'{node.name}' has no incoming flow", index)
        self.prev = self.last = node
        self.arrow_seen = False

    def on_annotation(self, content: str, index: int) -> None:
        if self.last is None:
            return
        self.last.annotations.append(Annotation(content, index))
        self.last.end_index = index
        m = INTERFACE_RE.match(content)
        if m and self.last.interface is None:
            self.last.interface = m.group(1)

    def parse(self, lines: list[Paragraph]) -> FlowGraph:
        for p in lines:
            stripped = p.text.lstrip(RAIL_CHARS)
            column = len(p.text) - len(stripped)
            content = stripped.rstrip()
            if not content:
                continue
            if content.startswith(ARROW):
                self.arrow_seen = True
                continue
            branch = BRANCH_RE.match(content)
            if branch:
                self.on_branch(column, branch.group(1).strip(), branch.group(2).strip(), p.index)
            elif content in ("START", "END") or BRACKET_RE.match(content):
                self.on_node(content, p.index)
            else:
                self.on_annotation(content, p.index)
        self.flush_pending()
        if self.end_count == 1:
            for n in self.graph.nodes:
                if n.kind == "end":
                    for e in self.graph.edges:
                        if e.target == n.key:
                            e.target = "end"
                    n.key = "end"
        return self.graph


def parse_text_flow(lines: list[Paragraph]) -> FlowGraph:
    """Parse the paragraphs between the fences of a text flow diagram."""
    return _Parser().parse(lines)
