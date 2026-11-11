"""The LTM document set, keyed D01..Dnn, plus citation helpers.

A citation is `Dnn ¶a` or `Dnn ¶a–b`: document number and paragraph index in
the original DOCX, as produced by the reader. Documents are opened read-only.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ltm_reader import DocumentResult, Paragraph, parse_docx
from ltm_reader.structure import Section, extract_sections

DOC_FILE_RE = re.compile(r"^(\d\d)_.*\.docx$")
CITE_TOKEN_RE = re.compile(r"\b(D\d\d)\b|¶(\d+)(?:[–-](\d+))?")
NON_CONTENT = {"", "---"}


class ExtractionError(Exception):
    """The spec cannot be built without inventing something. Lists every problem."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def cite(doc: str, start: int, end: int | None = None) -> str:
    if end is None or end == start:
        return f"{doc} ¶{start}"
    return f"{doc} ¶{start}–{end}"


@dataclass(frozen=True)
class Anchor:
    doc: str
    start: int
    end: int

    def cite(self) -> str:
        return cite(self.doc, self.start, self.end)


def has_content(p: Paragraph) -> bool:
    return p.text.strip() not in NON_CONTENT or bool(p.image_targets)


class DocSet:
    def __init__(self, documents: dict[str, DocumentResult]):
        self.documents = dict(sorted(documents.items()))
        self._sections: dict[str, list[Section]] = {}

    @classmethod
    def load(cls, docs_dir: str | Path) -> "DocSet":
        docs_dir = Path(docs_dir)
        files = sorted(docs_dir.glob("*.docx")) if docs_dir.is_dir() else []
        documents = {}
        for f in files:
            m = DOC_FILE_RE.match(f.name)
            if m:
                documents[f"D{m.group(1)}"] = parse_docx(f)
        if not documents:
            raise ExtractionError([f"no LTM documents (NN_*.docx) found in {docs_dir}"])
        return cls(documents)

    def sections(self, key: str) -> list[Section]:
        if key not in self._sections:
            self._sections[key] = extract_sections(self.documents[key])
        return self._sections[key]

    def span(self, key: str, section_index: int) -> list[Paragraph]:
        """Heading paragraph through the last paragraph before the next
        heading of the same or a higher level."""
        sections = self.sections(key)
        own = sections[section_index]
        paragraphs = self.documents[key].paragraphs
        end = len(paragraphs)
        for later in sections[section_index + 1:]:
            if later.level <= own.level:
                end = later.paragraph_index
                break
        return paragraphs[own.paragraph_index:end]

    def children(self, key: str, section_index: int) -> list[Section]:
        sections = self.sections(key)
        own = sections[section_index]
        out = []
        for later in sections[section_index + 1:]:
            if later.level <= own.level:
                break
            out.append(later)
        return out

    def image_sha256(self, key: str, target: str) -> str | None:
        """Hash of an embedded image, read straight from the DOCX package."""
        try:
            with zipfile.ZipFile(self.documents[key].source) as zf:
                return hashlib.sha256(zf.read(f"word/{target}")).hexdigest()
        except (OSError, KeyError, zipfile.BadZipFile):
            return None

    def find_citations(self, text: str) -> list[tuple[str | None, int, int]]:
        """(doc, start, end) for every ¶ reference; a bare ¶ inherits the
        document named before it in the same string."""
        found, doc = [], None
        for m in CITE_TOKEN_RE.finditer(text):
            if m.group(1):
                doc = m.group(1)
            else:
                start = int(m.group(2))
                found.append((doc, start, int(m.group(3)) if m.group(3) else start))
        return found

    def check_citation(self, doc: str | None, start: int, end: int) -> str | None:
        """None if the reference resolves to content paragraphs, else why not."""
        if doc is None:
            return f"¶{start} names no document"
        ref = cite(doc, start, end)
        if doc not in self.documents:
            return f"{ref}: no document {doc} in the set"
        paragraphs = self.documents[doc].paragraphs
        if start > end or end >= len(paragraphs):
            return f"{ref}: {doc} has paragraphs 0–{len(paragraphs) - 1}"
        for i in (start, end):
            if not has_content(paragraphs[i]):
                return f"{cite(doc, i)} (in {ref}) is blank"
        return None

    def text(self, doc: str, start: int, end: int) -> str:
        return "\n".join(p.text for p in self.documents[doc].paragraphs[start:end + 1])
