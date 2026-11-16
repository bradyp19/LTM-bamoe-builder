"""Source facts: what the documents state, each with its paragraph anchor.

Nothing here interprets or fills gaps. Process models, record types and
interfaces are found by their heading shapes in whichever document holds them.
A name defined more than once keeps its first definition and records where the
others are, so that a caller can refuse to pick one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ltm_reader import Paragraph
from ltm_reader.structure import PipeTable, Section

from .docset import Anchor, DocSet, has_content

PROCESS_HEADING_RE = re.compile(r"^Process Model:\s*(.+)$")
RECORD_HEADING_RE = re.compile(r"^Record Type:\s*(.+?)(?:\s*\([^)]*\))?$")
INTERFACE_HEADING_RE = re.compile(r"^\d+\.\s+([A-Za-z_]\w*)$")  # after backticks are removed
INTERFACE_SCOPE = "interface"  # an enclosing heading must mention it
INLINE_FIELDS_RE = re.compile(r"^\*\*Fields:\*\*\s*(.+)$")
INLINE_FIELD_RE = re.compile(r"`(\w+)`\s*\(([^)]*)\)")
FENCE_RE = re.compile(r"^\s*```")
FIGURE_RE = re.compile(r"^(Figure\s+\d+)\b")
PRIMARY_KEY_RE = re.compile(r"\*\*Primary Key:\*\*\s*`([^`]+)`")


@dataclass
class VariableFact:
    name: str
    type: str
    parameter: str
    required: bool
    extra: dict[str, str]
    anchor: Anchor


@dataclass
class FlowSource:
    """Where the process flow is documented: a text diagram, an image, or nowhere."""

    kind: str  # "text" | "image" | "missing"
    anchor: Anchor | None = None
    lines: list[Paragraph] = field(default_factory=list)
    image: str | None = None
    figure: str | None = None


@dataclass
class ProcessFacts:
    name: str
    anchor: Anchor
    attributes: dict[str, tuple[str, Anchor]]
    variables: list[VariableFact]
    variables_anchors: list[Anchor]
    flow: FlowSource
    other_definitions: list[Anchor] = field(default_factory=list)


@dataclass
class FieldFact:
    name: str
    data_type: str
    nullable: bool | None  # None: not stated
    description: str
    anchor: Anchor


@dataclass
class RecordTypeFacts:
    name: str
    anchor: Anchor
    primary_key: str | None
    fields: list[FieldFact]
    fields_anchors: list[Anchor]
    other_definitions: list[Anchor] = field(default_factory=list)


@dataclass
class RuleInputFact:
    name: str
    type: str
    anchor: Anchor


@dataclass
class FormFieldFact:
    label: str
    type: str
    constraints: str
    required: bool
    anchor: Anchor


@dataclass
class InterfaceFacts:
    name: str
    anchor: Anchor
    rule_inputs: list[RuleInputFact]
    rule_inputs_anchors: list[Anchor]
    form_fields: list[FormFieldFact]
    other_definitions: list[Anchor] = field(default_factory=list)


def _clean(cell: str) -> str:
    return cell.strip().strip("*").strip("`").strip()


def _rows(table: PipeTable, doc: str):
    """(cells keyed by header, anchor) per row. Rows directly follow the
    header and separator lines, so their paragraph indexes are contiguous."""
    for i, cells in enumerate(table.rows):
        row = {h: (cells[j] if j < len(cells) else "") for j, h in enumerate(table.header)}
        index = table.start_index + 2 + i
        yield row, Anchor(doc, index, index)


def _table_anchor(table: PipeTable, doc: str) -> Anchor:
    return Anchor(doc, table.start_index, table.start_index + 1 + len(table.rows))


def _content_anchor(doc: str, span: list[Paragraph]) -> Anchor:
    last = next(p for p in reversed(span) if has_content(p))
    return Anchor(doc, span[0].index, last.index)


def _tables(sections: list[Section], *first_column: str) -> list[PipeTable]:
    """Every table in these sections whose first column has one of the names."""
    return [t for s in sections for t in s.tables if t.header and t.header[0] in first_column]


def _flow_source(doc: str, own: Section, children: list[Section],
                 span: list[Paragraph]) -> FlowSource:
    for s in children:
        if s.title != "Process Flow":
            continue
        fences = [p for p in s.paragraphs if FENCE_RE.match(p.text)]
        if len(fences) >= 2:
            opening, closing = fences[0], fences[1]
            return FlowSource(
                kind="text", anchor=Anchor(doc, opening.index, closing.index),
                lines=[p for p in s.paragraphs if opening.index < p.index < closing.index])
    for i, p in enumerate(span):
        if not p.image_targets:
            continue
        figure = None
        for following in span[i + 1:]:
            if following.text.strip():
                m = FIGURE_RE.match(following.text.strip())
                figure = m.group(1) if m else None
                break
        return FlowSource(kind="image", anchor=Anchor(doc, p.index, p.index),
                          image=p.image_targets[0], figure=figure)
    return FlowSource(kind="missing")


def process_models(docset: DocSet) -> dict[str, ProcessFacts]:
    out: dict[str, ProcessFacts] = {}
    for doc in docset.documents:
        for i, section in enumerate(docset.sections(doc)):
            m = PROCESS_HEADING_RE.match(section.title)
            if not m:
                continue
            children = docset.children(doc, i)
            span = docset.span(doc, i)

            name = m.group(1).strip()
            anchor_ = _content_anchor(doc, span)
            if name in out:
                out[name].other_definitions.append(anchor_)
                continue

            attributes = {}
            for attr_table in _tables([section], "Attribute"):
                for row, anchor in _rows(attr_table, doc):
                    attributes[_clean(row["Attribute"])] = (row.get("Value", "").strip(), anchor)

            variables, variables_anchors = [], []
            known = {"Variable", "Type", "Parameter", "Required"}
            for var_table in _tables(
                    [s for s in children if s.title == "Process Variables"], "Variable"):
                variables_anchors.append(_table_anchor(var_table, doc))
                for row, anchor in _rows(var_table, doc):
                    variables.append(VariableFact(
                        name=_clean(row["Variable"]),
                        type=row.get("Type", "").strip(),
                        parameter=row.get("Parameter", "").strip(),
                        required=_clean(row.get("Required", "")).lower() == "yes",
                        extra={h: v.strip() for h, v in row.items() if h not in known},
                        anchor=anchor))

            out[name] = ProcessFacts(
                name=name,
                anchor=anchor_,
                attributes=attributes,
                variables=variables,
                variables_anchors=variables_anchors,
                flow=_flow_source(doc, section, children, span))
    return out


def record_types(docset: DocSet) -> dict[str, RecordTypeFacts]:
    out: dict[str, RecordTypeFacts] = {}
    for doc in docset.documents:
        for i, section in enumerate(docset.sections(doc)):
            m = RECORD_HEADING_RE.match(section.title)
            if not m:
                continue
            span = docset.span(doc, i)
            name = m.group(1).strip()
            anchor_ = _content_anchor(doc, span)
            if name in out:
                out[name].other_definitions.append(anchor_)
                continue
            pk = next((k.group(1) for p in span
                       if (k := PRIMARY_KEY_RE.search(p.text))), None)
            fields, fields_anchors = [], []
            for table in _tables(docset.children(doc, i), "Field Name"):
                fields_anchors.append(_table_anchor(table, doc))
                for row, anchor in _rows(table, doc):
                    fields.append(FieldFact(
                        name=_clean(row["Field Name"]),
                        data_type=row.get("Data Type", "").strip(),
                        nullable=_clean(row.get("Nullable", "")).lower() == "yes",
                        description=row.get("Description", "").strip(),
                        anchor=anchor))
            if not fields:
                # "**Fields:** `id` (Integer, PK), `textValue` (Text)"
                for p in span:
                    inline = INLINE_FIELDS_RE.match(p.text.strip())
                    if not inline:
                        continue
                    anchor = Anchor(doc, p.index, p.index)
                    fields_anchors.append(anchor)
                    for f in INLINE_FIELD_RE.finditer(inline.group(1)):
                        parts = [x.strip() for x in f.group(2).split(",")]
                        fields.append(FieldFact(name=f.group(1), data_type=parts[0],
                                                nullable=None, description="", anchor=anchor))
                        if pk is None and "PK" in parts[1:]:
                            pk = f.group(1)
            out[name] = RecordTypeFacts(
                name=name, anchor=anchor_, primary_key=pk, fields=fields,
                fields_anchors=fields_anchors)
    return out


def interfaces(docset: DocSet) -> dict[str, InterfaceFacts]:
    out: dict[str, InterfaceFacts] = {}
    for doc in docset.documents:
        for i, section in enumerate(docset.sections(doc)):
            m = INTERFACE_HEADING_RE.match(section.title.replace("`", ""))
            if not m or not any(INTERFACE_SCOPE in a.title.lower()
                                for a in docset.ancestors(doc, i)):
                continue
            anchor_ = _content_anchor(doc, docset.span(doc, i))
            if m.group(1) in out:
                out[m.group(1)].other_definitions.append(anchor_)
                continue
            children = docset.children(doc, i)

            rule_inputs, rule_inputs_anchors = [], []
            for table in _tables([s for s in children if s.title.startswith("Rule Inputs")],
                                 "Input", "Parameter"):
                rule_inputs_anchors.append(_table_anchor(table, doc))
                for row, anchor in _rows(table, doc):
                    name = _clean(row[table.header[0]])
                    rule_inputs.append(RuleInputFact(
                        name=name[3:] if name.startswith("ri!") else name,
                        type=row.get("Type", "").strip(), anchor=anchor))

            form_fields = []
            for s in children:
                for t in s.tables:
                    if t.header[:2] != ["Field", "Type"]:
                        continue
                    for row, anchor in _rows(t, doc):
                        constraints = row.get("Constraints", "").strip()
                        form_fields.append(FormFieldFact(
                            label=row["Field"].strip(), type=row["Type"].strip(),
                            constraints=constraints,
                            required=constraints == "Required", anchor=anchor))

            out[m.group(1)] = InterfaceFacts(
                name=m.group(1), anchor=anchor_,
                rule_inputs=rule_inputs, rule_inputs_anchors=rule_inputs_anchors,
                form_fields=form_fields)
    return out
