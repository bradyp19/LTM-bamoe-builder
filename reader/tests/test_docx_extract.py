"""Test-first fixtures for the LTM DOCX reader.

Covers the verified input findings: split text runs, literal Markdown tables,
leading whitespace / Unicode diagrams, embedded images, unbalanced fences —
and the invariant that the source file is never modified.
"""

import hashlib
import zipfile
from pathlib import Path

import pytest

from ltm_reader import parse_docx

REAL_D03 = Path("/Users/bpark/bamoe-appian/03_Workflow_and_Process_Models.docx")

DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<w:body>{body}</w:body></w:document>"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://x/image" Target="media/image1.png"/>
</Relationships>"""


def para(runs, style=None, image=False):
    """Build a <w:p>. runs = list of text fragments (split runs)."""
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    img_xml = (
        '<w:r><w:drawing><wp:inline><wp:docPr id="1" name="img"/>'
        '<a:graphic><a:blip r:embed="rId5"/></a:graphic></wp:inline>'
        "</w:drawing></w:r>"
        if image else ""
    )
    run_xml = "".join(
        f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>' for t in runs
    )
    return f"<w:p>{style_xml}{run_xml}{img_xml}</w:p>"


@pytest.fixture
def make_docx(tmp_path):
    def _make(body, name="fixture.docx"):
        f = tmp_path / name
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", DOC_XML.format(body=body))
            z.writestr("word/_rels/document.xml.rels", RELS_XML)
            z.writestr("word/media/image1.png", b"\x89PNG")
        return f
    return _make


class TestSplitRuns:
    def test_split_runs_reconstruct_paragraph(self, make_docx):
        f = make_docx(para(["| Variable ", "| Ty", "pe |"]))
        doc = parse_docx(f)
        assert doc.paragraphs[0].text == "| Variable | Type |"

    def test_paragraph_order_preserved(self, make_docx):
        f = make_docx(para(["first"]) + para(["second"]) + para(["third"]))
        doc = parse_docx(f)
        assert [p.text for p in doc.paragraphs] == ["first", "second", "third"]
        assert [p.index for p in doc.paragraphs] == [0, 1, 2]


class TestMarkdownPreservation:
    def test_markdown_table_rows_preserved_verbatim(self, make_docx):
        f = make_docx(
            para(["| Variable | Type |"])
            + para(["|---|---|"])
            + para(["| `cancel` | Boolean |"])
        )
        doc = parse_docx(f)
        assert doc.paragraphs[2].text == "| `cancel` | Boolean |"

    def test_leading_whitespace_and_box_drawing_preserved(self, make_docx):
        diagram = "  │\n  ├──[cancel = true]──▶ END"
        f = make_docx(para(["START"]), )
        f = make_docx(para(["  │"]) + para(["  ├──[cancel = true]──▶ END"]))
        doc = parse_docx(f)
        assert doc.paragraphs[0].text == "  │"
        assert "──▶ END" in doc.paragraphs[1].text
        assert doc.paragraphs[1].text.startswith("  ├")


class TestImages:
    def test_image_paragraph_disclosed_not_omitted(self, make_docx):
        f = make_docx(para(["before"]) + para([""], image=True) + para(["after"]))
        doc = parse_docx(f)
        p = doc.paragraphs[1]
        assert p.image_targets == ("media/image1.png",)
        codes = [d.code for d in doc.diagnostics]
        assert "image-content" in codes
        assert "image-no-alt-text" in codes
        assert len(doc.paragraphs) == 3


class TestFences:
    def test_balanced_fences_no_diagnostic(self, make_docx):
        f = make_docx(para(["```"]) + para(["code"]) + para(["```"]))
        doc = parse_docx(f)
        assert not any(d.code == "unbalanced-fence" for d in doc.diagnostics)

    def test_unbalanced_fences_diagnosed_not_repaired(self, make_docx):
        f = make_docx(para(["```"]) + para(["code"]))
        doc = parse_docx(f)
        diags = [d for d in doc.diagnostics if d.code == "unbalanced-fence"]
        assert len(diags) == 1
        # content is not repaired
        assert doc.paragraphs[0].text == "```"


class TestImmutability:
    def test_source_file_unmodified(self, make_docx):
        f = make_docx(para(["data"]))
        before = hashlib.sha256(f.read_bytes()).hexdigest()
        parse_docx(f)
        assert hashlib.sha256(f.read_bytes()).hexdigest() == before


@pytest.mark.skipif(not REAL_D03.exists(), reason="LTM originals not present")
class TestRealD03:
    """Integration assertions against the verified D03 findings."""

    def test_paragraph_counts(self):
        doc = parse_docx(REAL_D03)
        assert len(doc.paragraphs) == 258
        assert len(doc.text_paragraphs) == 214

    def test_embedded_image_found(self):
        doc = parse_docx(REAL_D03)
        assert ("media/image1.png" in t for _, t in doc.images)
        image_par = doc.paragraphs[31]
        assert image_par.image_targets == ("media/image1.png",)
        assert any(d.code == "image-no-alt-text" for d in doc.diagnostics)

    def test_variables_table_intact(self):
        doc = parse_docx(REAL_D03)
        texts = [p.text for p in doc.paragraphs]
        assert "| `cancel` | Boolean | Yes | No | Flag set to true when user cancels the form |" in texts
        assert "| `isUpdate` | Boolean | Yes | No | Distinguishes create (false) from update (true) mode |" in texts

    def test_unbalanced_fences_flagged(self):
        doc = parse_docx(REAL_D03)
        diags = [d for d in doc.diagnostics if d.code == "unbalanced-fence"]
        assert len(diags) == 1
        assert "9 fence lines" in diags[0].message

    def test_allocations_text_diagram_preserved(self):
        doc = parse_docx(REAL_D03)
        flow = [p.text for p in doc.paragraphs if "Allocation Main Screen" in p.text]
        assert flow
        assert any(p.text.startswith("  │") for p in doc.paragraphs)

    def test_heading_style_detected(self):
        doc = parse_docx(REAL_D03)
        heading = doc.paragraphs[30]
        assert heading.text == "Process Flow"
        assert heading.style is not None and "Heading" in heading.style
