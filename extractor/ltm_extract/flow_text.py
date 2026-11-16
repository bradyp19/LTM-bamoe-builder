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
BRANCH_RE = re.compile(r"^([├└])─+(?:\[(.+?)\]─+)?▶\s*(.*)$")
BRANCH_CHARS = "├└"
BRANCH_ARROW = "▶"
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
    label: str | None
    paragraph_index: int


@dataclass
class _Group:
    """The branches drawn off one node's rail. `closed` once └ has been seen."""

    column: int
    owner: FlowNode
    closed: bool = False


def _shown(label: str | None) -> str:
    return f"[{label}]" if label else "(unlabelled)"


class _Parser:
    def __init__(self):
        self.graph = FlowGraph()
        self.groups: list[_Group] = []
        self.prev: FlowNode | None = None  # source of the next sequence edge
        self.last: FlowNode | None = None  # node that annotations attach to
        self.pending: _Pending | None = None
        self.arrow_column: int | None = None  # column of the ▼ since the last node/branch
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
                      f"branch {_shown(self.pending.label)} has no target",
                      self.pending.paragraph_index)
            self.pending = None

    def on_branch(self, column: int, last: bool, label: str | None, target: str,
                  index: int) -> None:
        self.flush_pending()
        while self.groups and self.groups[-1].column > column:
            self.groups.pop()
        if self.groups and self.groups[-1].column == column:
            group = self.groups[-1]
            if group.closed:
                self.diag("flow-branch-after-last",
                          f"branch {_shown(label)} follows the last branch (└) of "
                          f"'{group.owner.name}' at the same indentation", index)
                return
        elif self.prev is not None:
            group = _Group(column, self.prev)
            self.groups.append(group)
        else:
            self.diag("flow-orphan-branch", f"branch {_shown(label)} has no source node", index)
            return
        group.closed = last
        owner = group.owner
        self.prev = None
        self.arrow_column = None
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
                      f"branch {_shown(label)} points at '{target}', which names no node drawn "
                      "above it", index)
            return
        longest = max(len(n.name) for n in matches)
        best = [n for n in matches if len(n.name) == longest]
        if len(best) > 1:
            self.diag("flow-ambiguous-target",
                      f"branch {_shown(label)} points at '{target}', which names "
                      f"{len(best)} nodes", index)
            return
        node = best[0]
        note = reference[len(node.name):].strip() or None
        self.graph.edges.append(FlowEdge(owner.key, node.key, label, index, note))

    def on_node(self, content: str, column: int, index: int) -> None:
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

        # A node drawn at or left of a branch group's rail ends that group. If
        # the group is still open and the arrow is on its rail, the owner's
        # main line continues into this node.
        mainline = None
        while self.groups and self.groups[-1].column >= column:
            group = self.groups.pop()
            if not group.closed and self.arrow_column == group.column:
                mainline = group.owner

        if self.pending:
            self.graph.edges.append(FlowEdge(self.pending.owner.key, node.key,
                                             self.pending.label, self.pending.paragraph_index))
            self.pending = None
        elif mainline is not None:
            self.graph.edges.append(FlowEdge(mainline.key, node.key, None, index))
        elif self.prev is not None:
            if self.arrow_column is None:
                self.diag("flow-implicit-sequence",
                          f"'{node.name}' follows '{self.prev.name}' with no arrow between them",
                          index)
            self.graph.edges.append(FlowEdge(self.prev.key, node.key, None, index))
        elif self.graph.nodes[0] is not node:
            self.diag("flow-disconnected-node", f"'{node.name}' has no incoming flow", index)
        self.prev = self.last = node
        self.arrow_column = None

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
                self.arrow_column = column
                continue
            branch = BRANCH_RE.match(content)
            if branch:
                label = branch.group(2).strip() if branch.group(2) else None
                self.on_branch(column, branch.group(1) == "└", label,
                               branch.group(3).strip(), p.index)
            elif content[0] in BRANCH_CHARS or BRANCH_ARROW in content:
                self.diag("flow-unparsed-line",
                          f"'{content}' looks like a flow line but is not one this parser "
                          "understands; nothing was taken from it", p.index)
            elif content in ("START", "END") or BRACKET_RE.match(content):
                self.on_node(content, column, p.index)
            else:
                self.on_annotation(content, p.index)
        self.flush_pending()
        if self.end_count == 1 and all(n.key != "end" for n in self.graph.nodes):
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
