from pathlib import Path

import pytest

from ltm_reader import parse_docx
from ltm_reader.structure import extract_sections, extract_tables

REAL_D03 = Path("/Users/bpark/bamoe-appian/03_Workflow_and_Process_Models.docx")


@pytest.mark.skipif(not REAL_D03.exists(), reason="LTM originals not present")
class TestSections:
    def test_process_sections_found(self):
        doc = parse_docx(REAL_D03)
        sections = extract_sections(doc)
        titles = [s.title for s in sections]
        assert "Process Model: NSSOL Register Project" in titles
        assert "Process Model: NSSOL Allocations" in titles
        assert "Process Model: NSSOL Update Language Toggle" in titles

    def test_register_project_variables_table(self):
        doc = parse_docx(REAL_D03)
        sections = extract_sections(doc)
        rp = next(s for s in sections
                  if s.title == "Process Model: NSSOL Register Project")
        var_table = next(t for s in sections for t in s.tables
                         if t.rows and t.rows[0] and t.rows[0][0] == "`cancel`")
        names = [r[0].strip("`") for r in var_table.rows]
        assert names == ["cancel", "isUpdate", "projectRegistration"]
        types = [r[1] for r in var_table.rows]
        assert types[0] == "Boolean"
        assert "NSSOL Projects record" in types[2]

    def test_table_anchor_points_at_header_paragraph(self):
        doc = parse_docx(REAL_D03)
        sections = extract_sections(doc)
        rp = next(s for s in sections
                  if s.title == "Process Model: NSSOL Register Project")
        t = rp.tables[0]
        assert doc.paragraphs[t.start_index].text.startswith("| Attribute")
