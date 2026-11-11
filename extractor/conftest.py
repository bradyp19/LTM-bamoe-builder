"""Shared test setup for the extraction layer.

The reader, generator and extractor are sibling source folders rather than
installed packages, so put all three on sys.path.
"""

import os
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _sub in ("reader", "generator", "extractor"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

DOCS_DIR = Path(os.environ.get("LTM_DOCS_DIR", ROOT.parent))
SUPPLEMENTS = ROOT / "extractor" / "supplements"
SPECS = ROOT / "generator" / "specs"

IMAGE = object()  # sentinel line: an image-only paragraph

_DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<w:body>{body}</w:body></w:document>"""

_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId5" Type="http://x/image" Target="media/image1.png"/>
</Relationships>"""

_IMAGE_RUN = (
    '<w:r><w:drawing><wp:inline><wp:docPr id="1" name="img"/>'
    '<a:graphic><a:blip r:embed="rId5"/></a:graphic></wp:inline>'
    "</w:drawing></w:r>"
)


def _para(line):
    if line is IMAGE:
        return f"<w:p>{_IMAGE_RUN}</w:p>"
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'


@pytest.fixture
def make_docx(tmp_path):
    """Write a minimal LTM-style DOCX: one paragraph per line."""

    def _make(name, lines, image_bytes=b"\x89PNG-fixture"):
        f = tmp_path / name
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml",
                       _DOC_XML.format(body="".join(_para(l) for l in lines)))
            z.writestr("word/_rels/document.xml.rels", _RELS_XML)
            z.writestr("word/media/image1.png", image_bytes)
        return f

    return _make


@pytest.fixture(scope="session")
def real_docset():
    if not (DOCS_DIR / "03_Workflow_and_Process_Models.docx").exists():
        pytest.skip("LTM originals not present (set LTM_DOCS_DIR)")
    from ltm_extract import DocSet

    return DocSet.load(DOCS_DIR)
