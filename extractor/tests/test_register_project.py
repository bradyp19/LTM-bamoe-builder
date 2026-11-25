"""Acceptance: documents + supplement -> generator/specs/register_project.json.

The target spec is hand-written. Everything the documents support is derived
(variables, types, model fields, evidence anchors, conditions); the flow is
image-only, so its transcription and all target-design choices come from
extractor/supplements/register_project.json.
"""

import copy
import json

import pytest

from conftest import SPECS, SUPPLEMENTS
from ltm_extract import ExtractionError, build_spec, load_supplement
from ltm_gen.bpmn_emit import emit_bpmn
from ltm_gen.java_emit import emit_process_test

TARGET = json.loads((SPECS / "register_project.json").read_text(encoding="utf-8"))
SUPPLEMENT = SUPPLEMENTS / "register_project.json"


def fields_by_name(spec):
    """Model field order is not part of the contract (see TestModelFields)."""
    spec = copy.deepcopy(spec)
    for model in spec["models"].values():
        model["fields"] = sorted(model["fields"], key=lambda f: f["name"])
    return spec


@pytest.fixture(scope="module")
def result(real_docset):
    return build_spec(real_docset, load_supplement(SUPPLEMENT))


@pytest.fixture
def supplement():
    return load_supplement(SUPPLEMENT)


class TestTarget:
    @pytest.mark.parametrize("section", ["process", "variables", "nodes", "flows",
                                         "tests", "assumptions"])
    def test_section_matches_target(self, result, section):
        assert result.spec[section] == TARGET[section]

    def test_whole_spec_matches_target(self, result):
        assert fields_by_name(result.spec) == fields_by_name(TARGET)

    def test_bpmn_is_byte_identical_to_the_target_specs(self, result):
        assert emit_bpmn(result.spec) == emit_bpmn(TARGET)

    def test_generated_process_test_is_identical(self, result):
        assert emit_process_test(result.spec) == emit_process_test(TARGET)


class TestModelFields:
    def test_same_fields_and_types_as_target(self, result):
        got = {f["name"]: f["type"] for f in result.spec["models"]["ProjectRegistration"]["fields"]}
        want = {f["name"]: f["type"] for f in TARGET["models"]["ProjectRegistration"]["fields"]}
        assert got == want

    def test_fields_are_emitted_in_document_order(self, result):
        names = [f["name"] for f in result.spec["models"]["ProjectRegistration"]["fields"]]
        assert names[:3] == ["projectId", "projectName", "startDate"]  # D05 ¶50–52
        assert names[-1] == "isActive"  # D05 ¶76

    def test_model_evidence_is_the_fields_table(self, result):
        assert result.spec["models"]["ProjectRegistration"]["evidence"] == "D05 ¶48–76"


class TestDerivedNotTyped:
    """Source facts must come from the documents, never from the supplement."""

    def test_supplement_carries_no_source_facts(self, supplement):
        assert set(supplement) <= {"application", "process", "figureTranscriptions", "design",
                                   "assumptions", "tests"}
        raw = SUPPLEMENT.read_text(encoding="utf-8")
        for derived in ["java.lang.Boolean", "orderAmountMillionYen", "D05 ¶48–76",
                        "D03 ¶24–28", "D04 ¶24–79", "return cancel"]:
            assert derived not in raw

    def test_unknown_top_level_key_rejected(self, real_docset, supplement):
        supplement["variables"] = [{"name": "extra", "type": "java.lang.String"}]
        with pytest.raises(ExtractionError, match="variables"):
            build_spec(real_docset, supplement)

    def test_image_only_flow_is_disclosed(self, result):
        codes = [d.code for d in result.diagnostics]
        assert "flow-from-image-transcription" in codes


class TestRefusesToInvent:
    def test_image_only_flow_without_transcription(self, real_docset, supplement):
        supplement["figureTranscriptions"] = []
        with pytest.raises(ExtractionError, match="image-only") as exc:
            build_spec(real_docset, supplement)
        assert "D03 ¶31" in str(exc.value)

    def test_transcription_of_a_different_image(self, real_docset, supplement):
        supplement["figureTranscriptions"][0]["sha256"] = "0" * 64
        with pytest.raises(ExtractionError, match="sha256"):
            build_spec(real_docset, supplement)

    def test_transcription_using_an_undeclared_variable(self, real_docset, supplement):
        form = supplement["figureTranscriptions"][0]["nodes"][1]
        form["inputs"] = ["isUpdate", "projectRegistrationX"]
        with pytest.raises(ExtractionError, match="projectRegistrationX"):
            build_spec(real_docset, supplement)

    def test_design_cannot_override_the_transcription(self, real_docset, supplement):
        supplement["design"]["nodes"]["form"]["inputs"] = ["cancel"]
        with pytest.raises(ExtractionError, match="form"):
            build_spec(real_docset, supplement)

    def test_design_for_unknown_node(self, real_docset, supplement):
        supplement["design"]["nodes"]["approve"] = {"notes": "not in the figure"}
        with pytest.raises(ExtractionError, match="approve"):
            build_spec(real_docset, supplement)

    def test_gateway_flow_without_a_translatable_condition(self, real_docset, supplement):
        supplement["figureTranscriptions"][0]["flows"][2]["label"] = "Yes"
        with pytest.raises(ExtractionError, match="condition"):
            build_spec(real_docset, supplement)

    def test_unknown_process(self, real_docset, supplement):
        supplement["process"] = "NSSOL Register Projekt"
        with pytest.raises(ExtractionError, match="NSSOL Register Projekt"):
            build_spec(real_docset, supplement)

    def test_service_task_without_binding(self, real_docset, supplement):
        del supplement["design"]["nodes"]["saveRecord"]["service"]
        with pytest.raises(ExtractionError, match="saveRecord"):
            build_spec(real_docset, supplement)


class TestCitations:
    def test_citation_to_missing_paragraph(self, real_docset, supplement):
        supplement["assumptions"][0]["text"] += " See D03 ¶999."
        with pytest.raises(ExtractionError, match="D03 ¶999"):
            build_spec(real_docset, supplement)

    def test_citation_to_missing_document(self, real_docset, supplement):
        supplement["assumptions"][0]["text"] += " See D09 ¶3."
        with pytest.raises(ExtractionError, match="D09"):
            build_spec(real_docset, supplement)

    def test_citation_to_blank_paragraph(self, real_docset, supplement):
        supplement["assumptions"][0]["text"] += " See D03 ¶29."
        with pytest.raises(ExtractionError, match="D03 ¶29"):
            build_spec(real_docset, supplement)

    def test_support_quote_must_be_in_the_cited_paragraphs(self, real_docset, supplement):
        supplement["assumptions"][0]["support"] = [
            {"cite": "D03 ¶38", "quote": "assigned to the NP Users group"}]
        with pytest.raises(ExtractionError, match="D03 ¶38"):
            build_spec(real_docset, supplement)

    def test_every_assumption_with_citations_has_verified_support(self, supplement):
        for a in supplement["assumptions"]:
            if "¶" in a["text"]:
                assert a.get("support"), a["id"]
