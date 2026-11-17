"""Citation parsing and checking."""

import pytest

from ltm_extract import DocSet

LINES = ["# Title", "", "First fact.", "Second fact.", "---", "Third fact."]


@pytest.fixture
def docset(make_docx):
    f = make_docx("03_Workflow.docx", LINES)
    return DocSet.load(f.parent)


def problems(docset, text):
    return [why for ref in docset.find_citations(text)
            if (why := docset.check_citation(*ref))]


class TestFindCitations:
    def test_forms(self, docset):
        assert docset.find_citations("D03 ¶2") == [("D03", 2, 2)]
        assert docset.find_citations("D03 ¶2–3") == [("D03", 2, 3)]
        assert docset.find_citations("D03 ¶2-3") == [("D03", 2, 3)]
        assert docset.find_citations("D03 ¶2, ¶5; D04 ¶7") == [
            ("D03", 2, 2), ("D03", 5, 5), ("D04", 7, 7)]

    @pytest.mark.parametrize("text", ["D03 ¶2 – 3", "D03 ¶2—3", "D03 ¶ 2–3", "D03 ¶2 - 3"])
    def test_spacing_and_dash_variants_are_whole_references(self, docset, text):
        assert docset.find_citations(text) == [("D03", 2, 3)]

    def test_prose_dash_is_not_a_range(self, docset):
        assert docset.find_citations("D03 ¶2 — unresolved") == [("D03", 2, 2)]


class TestCheckCitation:
    def test_resolving_references(self, docset):
        assert problems(docset, "D03 ¶2–3 and D03 ¶5") == []

    @pytest.mark.parametrize("text, expected", [
        ("D03 ¶99", "D03 ¶99"),
        ("D03 ¶2 – 99", "D03 ¶2–99"),
        ("D03 ¶2—99", "D03 ¶2–99"),
        ("D03 ¶ 99", "D03 ¶99"),
        ("D03 ¶3–2", "D03 ¶3–2"),
        ("D07 ¶2", "D07"),
        ("¶2", "names no document"),
        ("D03 ¶1", "blank"),
        ("D03 ¶2–4", "blank"),
        ("D03 ¶ two", "paragraph number"),
        ("see D03 ¶", "paragraph number"),
    ])
    def test_references_that_do_not_resolve(self, docset, text, expected):
        found = problems(docset, text)
        assert len(found) == 1 and expected in found[0], found
