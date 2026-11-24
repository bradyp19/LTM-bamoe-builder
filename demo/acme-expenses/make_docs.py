"""Build the made-up ACME Expenses documents as NN_*.docx in the LTM layout.

    python demo/acme-expenses/make_docs.py OUT_DIR

Each Markdown line becomes one DOCX paragraph, which is how the LTM originals
are laid out (literal-Markdown headings, pipe tables and fenced diagrams).
"""

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

DOC_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>{body}</w:body></w:document>")

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 "</Types>")
PACKAGE_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/officeDocument" Target="word/document.xml"/></Relationships>')


def para(line: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for src in sorted((Path(__file__).parent / "docs").glob("*.md")):
        lines = src.read_text(encoding="utf-8").split("\n")
        with zipfile.ZipFile(out / f"{src.stem}.docx", "w") as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", PACKAGE_RELS)
            z.writestr("word/document.xml", DOC_XML.format(body="".join(map(para, lines))))
        print(out / f"{src.stem}.docx")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
