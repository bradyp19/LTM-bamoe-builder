"""Deterministic LTM DOCX intake.

LTM documents store literal Markdown inside Word paragraphs: headings, pipe
tables, bullets, code fences, and text diagrams with leading whitespace and
Unicode box-drawing characters. This module reads the raw OOXML and produces
an ordered paragraph list with stable anchors (paragraph index + style) and
diagnostics. It never writes to or modifies the source file.
"""

from __future__ import annotations

import re
import warnings as py_warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
R_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

DOCUMENT_XML = "word/document.xml"
RELS_XML = "word/_rels/document.xml.rels"

FENCE_RE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class Paragraph:
    """One <w:p>, in document order. `index` is the stable source anchor."""

    index: int
    style: str | None
    text: str
    image_targets: tuple[str, ...] = ()
    alt_texts: tuple[str, ...] = ()


@dataclass
class Diagnostic:
    """A disclosed anomaly. Diagnostics are reported, never repaired here."""

    code: str
    message: str
    paragraph_index: int | None = None


@dataclass
class DocumentResult:
    source: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def text_paragraphs(self) -> list[Paragraph]:
        return [p for p in self.paragraphs if p.text.strip()]

    @property
    def images(self) -> list[tuple[int, str]]:
        return [(p.index, t) for p in self.paragraphs for t in p.image_targets]


def _load_rels(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map relationship IDs (rId5) to media targets (media/image1.png)."""
    try:
        root = ET.fromstring(zf.read(RELS_XML))
    except KeyError:
        return {}
    return {
        el.get("Id"): el.get("Target")
        for el in root
        if el.get("Id") and el.get("Target")
    }


def _paragraph_text(p: ET.Element) -> str:
    """Join split text runs into one string, preserving order and whitespace."""
    return "".join(t.text or "" for t in p.iter(f"{W}t"))


def _paragraph_style(p: ET.Element) -> str | None:
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return None
    style = ppr.find(f"{W}pStyle")
    return style.get(f"{W}val") if style is not None else None


def _paragraph_images(p: ET.Element, rels: dict[str, str]) -> tuple[list[str], list[str]]:
    targets, alts = [], []
    for blip in p.iter(f"{A}blip"):
        rid = blip.get(R_EMBED)
        if rid and rid in rels:
            targets.append(rels[rid])
    for docpr in p.iter():
        if docpr.tag.endswith("}docPr") and docpr.get("descr"):
            alts.append(docpr.get("descr"))
    return targets, alts


def parse_docx(path: str | Path) -> DocumentResult:
    """Parse an LTM DOCX into ordered paragraphs + diagnostics. Read-only."""
    path = Path(path)
    result = DocumentResult(source=str(path))

    with zipfile.ZipFile(path) as zf:
        rels = _load_rels(zf)
        root = ET.fromstring(zf.read(DOCUMENT_XML))

    body = root.find(f"{W}body")
    for i, p in enumerate(body.iter(f"{W}p")):
        targets, alts = _paragraph_images(p, rels)
        result.paragraphs.append(
            Paragraph(
                index=i,
                style=_paragraph_style(p),
                text=_paragraph_text(p),
                image_targets=tuple(targets),
                alt_texts=tuple(alts),
            )
        )

    _diagnose(result)
    return result


def _diagnose(result: DocumentResult) -> None:
    """Report anomalies without modifying content."""

    # Unbalanced code fences: count of ``` lines must be even.
    fence_pars = [p for p in result.paragraphs if FENCE_RE.match(p.text)]
    if len(fence_pars) % 2:
        result.diagnostics.append(
            Diagnostic(
                code="unbalanced-fence",
                message=f"{len(fence_pars)} fence lines found (odd); "
                f"first at paragraph {fence_pars[0].index}, "
                f"last at paragraph {fence_pars[-1].index}",
                paragraph_index=fence_pars[-1].index,
            )
        )

    # Image-only content: flag every image, and separately flag images
    # with no alt text (the content they carry can't be extracted as text).
    for p in result.paragraphs:
        for target in p.image_targets:
            result.diagnostics.append(
                Diagnostic(
                    code="image-content",
                    message=f"Embedded image '{target}' at paragraph {p.index}; "
                    "content is image-only and needs visual review",
                    paragraph_index=p.index,
                )
            )
            if not p.alt_texts:
                result.diagnostics.append(
                    Diagnostic(
                        code="image-no-alt-text",
                        message=f"Image '{target}' at paragraph {p.index} "
                        "has no descriptive alt text",
                        paragraph_index=p.index,
                    )
                )


def warn_unless(condition: bool, message: str) -> None:
    if not condition:
        py_warnings.warn(message, stacklevel=2)
