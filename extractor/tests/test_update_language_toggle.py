"""Update Language Toggle: text flow diagram with no user task (D03 ¶179–190) -> spec JSON.

Nodes, flow and the variable are parsed from the documents. The task type of
the single node, its service binding and the scenarios are proposals in
extractor/supplements/update_language_toggle.json.
"""

import json
import re
from xml.etree import ElementTree as ET

import pytest

from conftest import SPECS, SUPPLEMENTS
from ltm_extract import ExtractionError, build_spec, load_supplement
from ltm_gen.bpmn_emit import emit_bpmn

SUPPLEMENT = SUPPLEMENTS / "update_language_toggle.json"
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


@pytest.fixture(scope="module")
def result(real_docset):
    return build_spec(real_docset, load_supplement(SUPPLEMENT))


@pytest.fixture(scope="module")
def spec(result):
    return result.spec


@pytest.fixture
def supplement():
    return load_supplement(SUPPLEMENT)


def node(spec, node_id):
    return next(n for n in spec["nodes"] if n["id"] == node_id)


class TestProcess:
    def test_identity_derived_from_the_process_name(self, spec):
        assert spec["process"]["id"] == "updateLanguageToggle"
        assert spec["process"]["name"] == "NSSOL Update Language Toggle"
        assert spec["process"]["packageName"] == "nssol"

    def test_evidence_is_computed_from_anchors(self, spec):
        assert spec["process"]["evidence"] == "D03 ¶179–190, D03 ¶173–175"

    def test_no_record_types_are_involved(self, spec):
        assert spec["models"] == {}


class TestVariables:
    def test_only_toggle_value_as_documented(self, spec):
        assert spec["variables"] == [
            {"name": "toggleValue", "type": "java.lang.Boolean", "evidence": "D03 ¶175"}]


class TestNodesAndFlows:
    def test_start_service_task_end_without_gateways(self, spec):
        assert [(n["id"], n["type"]) for n in spec["nodes"]] == [
            ("start", "start"), ("updateConstant", "serviceTask"), ("end", "end")]
        assert spec["flows"] == [{"from": "start", "to": "updateConstant"},
                                 {"from": "updateConstant", "to": "end"}]

    def test_name_is_the_documented_name(self, spec):
        assert node(spec, "updateConstant")["name"] == "Update Constant"

    def test_service_binding_is_the_supplement_proposal(self, spec):
        n = node(spec, "updateConstant")
        assert n["service"] == {"class": "nssol.service.LanguageToggleStore",
                                "operation": "update"}
        assert n["inputs"] == ["toggleValue"] and n["outputs"] == ["toggleValue"]
        assert "D03 ¶184–186" in n["doc"]

    def test_there_are_no_user_tasks(self, spec):
        assert not [n for n in spec["nodes"] if n["type"] == "userTask"]

    def test_untyped_node_needs_a_design_ruling(self, real_docset, supplement):
        del supplement["design"]["nodes"]["updateConstant"]["type"]
        with pytest.raises(ExtractionError, match="updateConstant.*Script Task / Service Task"):
            build_spec(real_docset, supplement)


class TestAssumptions:
    def test_no_transformation_is_needed(self, spec, result):
        assert not [a for a in spec["assumptions"] if a["id"].startswith("T-")]
        assert {d.code for d in result.diagnostics} == {"not-carried"}

    def test_conflicts_are_recorded_not_resolved(self, supplement):
        ids = [a["id"] for a in supplement["assumptions"]]
        assert any(i.startswith("TL-C") for i in ids)
        assert all(a["text"].startswith("CONFLICT") for a in supplement["assumptions"]
                   if a["id"].startswith("TL-C"))

    def test_every_assumption_with_citations_has_verified_support(self, supplement):
        for a in supplement["assumptions"]:
            if "¶" in a["text"]:
                assert a.get("support"), a["id"]

    def test_ids_are_unique_and_numbered(self, supplement):
        ids = [a["id"] for a in supplement["assumptions"]]
        assert len(ids) == len(set(ids))


class TestScenarios:
    def test_scenarios_have_no_steps_because_there_is_no_user_task(self, spec):
        assert spec["tests"]
        for t in spec["tests"]:
            assert t["steps"] == []
            assert t["expect"]["status"] == "COMPLETED"

    def test_both_toggle_directions_are_covered(self, spec):
        written = {t["start"]["toggleValue"]: t["expect"]["savedValues"]["LanguageToggleStore"]
                   for t in spec["tests"]}
        assert written == {True: True, False: False}

    def test_scenario_value_for_an_undeclared_variable_is_an_error(self, real_docset, supplement):
        supplement["tests"][0]["start"]["bogus"] = True
        with pytest.raises(ExtractionError, match="'bogus' is not a declared process variable"):
            build_spec(real_docset, supplement)


class TestGeneratorCompatibility:
    def test_bpmn_is_well_formed_with_unique_ids(self, spec):
        root = ET.fromstring(emit_bpmn(spec))
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))
        proc = root.find(f"{BPMN}process")
        assert re.fullmatch(r"[a-z][A-Za-z0-9]*", proc.get("id"))
        assert len(list(root.iter(f"{BPMN}userTask"))) == 0
        assert len(list(root.iter(f"{BPMN}serviceTask"))) == 1
        assert len(list(root.iter(f"{BPMN}sequenceFlow"))) == 2

    def test_spec_file_on_disk_is_the_current_extraction(self, spec):
        on_disk = json.loads((SPECS / "update_language_toggle.json").read_text(encoding="utf-8"))
        assert on_disk == spec
