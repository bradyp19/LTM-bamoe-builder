"""Structural extraction: literal-Markdown headings and pipe tables.

Turns the ordered paragraph stream into sections keyed by heading text, and
parses pipe tables into header + row cells. Everything carries the paragraph
index of its source line so downstream claims keep their anchors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .docx_extract import DocumentResult, Paragraph

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


@dataclass(frozen=True)
class TableCell:
    text: str
    paragraph_index: int


@dataclass
class PipeTable:
    header: list[str]
    rows: list[list[str]]
    start_index: int  # paragraph index of the header row


@dataclass
class Section:
    level: int
    title: str
    paragraph_index: int  # heading line index
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[PipeTable] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


def _is_table_line(text: str) -> bool:
    s = text.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_row(text: str) -> list[str]:
    s = text.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def extract_tables(paragraphs: list[Paragraph]) -> list[PipeTable]:
    tables = []
    i = 0
    while i < len(paragraphs):
        if _is_table_line(paragraphs[i].text) and i + 1 < len(paragraphs) \
                and TABLE_SEP_RE.match(paragraphs[i + 1].text):
            header = _split_row(paragraphs[i].text)
            rows = []
            j = i + 2
            while j < len(paragraphs) and _is_table_line(paragraphs[j].text):
                rows.append(_split_row(paragraphs[j].text))
                j += 1
            tables.append(PipeTable(header=header, rows=rows, start_index=paragraphs[i].index))
            i = j
        else:
            i += 1
    return tables


def extract_sections(doc: DocumentResult) -> list[Section]:
    """Split the document into sections at literal-Markdown headings."""
    sections: list[Section] = []
    current: Section | None = None
    for p in doc.paragraphs:
        m = HEADING_RE.match(p.text)
        if m:
            current = Section(level=len(m.group(1)), title=m.group(2),
                              paragraph_index=p.index)
            sections.append(current)
        elif current is not None:
            current.paragraphs.append(p)
    for s in sections:
        s.tables = extract_tables(s.paragraphs)
    return sections
