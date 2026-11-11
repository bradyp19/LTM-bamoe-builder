"""Allocations: text flow diagram (D03 ¶75–134) -> spec JSON.

Nodes, flows and conditions are parsed from the documents. Class names,
service bindings and task outputs are proposals in
extractor/supplements/allocations.json.
"""

import json
import re
from xml.etree import ElementTree as ET

import pytest

from conftest import SPECS, SUPPLEMENTS
from ltm_extract import ExtractionError, build_spec, load_supplement
from ltm_gen.bpmn_emit import emit_bpmn

SUPPLEMENT = SUPPLEMENTS / "allocations.json"
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
GATEWAY = "allocationMainScreenGateway"


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
        assert spec["process"]["id"] == "allocations"
        assert spec["process"]["name"] == "NSSOL Allocations"
        assert spec["process"]["packageName"] == "nssol"

    def test_evidence_is_computed_from_anchors(self, spec):
        assert spec["process"]["evidence"] == (
            "D03 ¶75–134, D03 ¶59–71, D04 ¶168–237, D04 ¶241–251, "
            "D04 ¶255–265, D04 ¶83–97")


class TestVariables:
    def test_all_eleven_in_document_order(self, spec):
        assert [v["name"] for v in spec["variables"]] == [
            "projectInfo", "selectedEmployees", "selectedSubcontractors",
            "assignedEmployees", "assignedSubcontractors", "isAddEmployee",
            "isAddSubcontractor", "isAssign", "allocationCancel", "empCancel",
            "SubconCancel"]

    def test_record_boolean_and_list_types(self, spec):
        v = {x["name"]: x for x in spec["variables"]}
        assert v["projectInfo"] == {
            "name": "projectInfo", "type": "nssol.model.ProjectRegistration",
            "required": True, "evidence": "D03 ¶61"}
        assert v["isAssign"] == {
            "name": "isAssign", "type": "java.lang.Boolean", "evidence": "D03 ¶68"}
        assert v["assignedEmployees"] == {
            "name": "assignedEmployees", "type": "java.util.List",
            "elementType": "nssol.model.MapEmployee", "evidence": "D03 ¶64"}

    def test_only_documented_required_variables_are_marked(self, spec):
        assert [v["name"] for v in spec["variables"] if v.get("required")] == ["projectInfo"]


class TestModels:
    def test_models_for_every_referenced_record_type(self, spec):
        assert list(spec["models"]) == ["ProjectRegistration", "Employee", "Subcontractor",
                                        "MapEmployee", "MapSubcontractor"]

    def test_evidence_and_field_counts(self, spec):
        m = spec["models"]
        assert m["ProjectRegistration"]["evidence"] == "D05 ¶48–76"
        assert m["Employee"]["evidence"] == "D05 ¶101–119"
        assert m["Subcontractor"]["evidence"] == "D05 ¶136–158"
        assert m["MapEmployee"]["evidence"] == "D05 ¶177–207"
        assert m["MapSubcontractor"]["evidence"] == "D05 ¶232–262"
        assert [len(m[k]["fields"]) for k in m] == [27, 17, 21, 29, 29]

    def test_datetime_uses_the_supplement_type_map(self, spec):
        created = next(f for f in spec["models"]["MapEmployee"]["fields"]
                       if f["name"] == "createdOn")
        assert created["type"] == "java.time.LocalDateTime"

    def test_unmapped_document_type_is_an_error_not_a_guess(self, real_docset, supplement):
        del supplement["design"]["typeMap"]["DateTime"]
        with pytest.raises(ExtractionError, match="DateTime"):
            build_spec(real_docset, supplement)


class TestNodes:
    def test_nodes_in_document_order_with_one_synthesized_gateway(self, spec):
        assert [(n["id"], n["type"]) for n in spec["nodes"]] == [
            ("start", "start"),
            ("allocationMainScreen", "userTask"),
            (GATEWAY, "xor"),
            ("end1", "end"),
            ("employeeSearchScreen", "userTask"),
            ("subcontractorSearchScreen", "userTask"),
            ("allocationConfirmation", "userTask"),
            ("writeMapEmployeeRecords", "serviceTask"),
            ("writeMapSubcontractorRecords", "serviceTask"),
            ("end2", "end"),
        ]

    def test_names_are_the_documented_names(self, spec):
        assert node(spec, "allocationMainScreen")["name"] == "Allocation Main Screen"
        assert node(spec, "writeMapEmployeeRecords")["name"] == "Write Map Employee Records"
        assert node(spec, "end1")["name"] == "End"

    def test_synthesized_gateway_is_labelled_as_such(self, spec):
        doc = node(spec, GATEWAY)["doc"]
        assert doc.startswith("SYNTHESIZED")
        assert "D03 ¶93–115" in doc

    def test_user_task_doc_cites_interface_and_flow_lines(self, spec):
        doc = node(spec, "allocationMainScreen")["doc"]
        assert "Interface: NSSOL_SEC_Allocation (D04 ¶168–237)." in doc
        assert "D03 ¶80–91" in doc

    def test_main_screen_inputs_come_from_rule_inputs(self, spec):
        n = node(spec, "allocationMainScreen")
        assert n["inputs"] == [
            "projectInfo", "selectedEmployees", "selectedSubcontractors",
            "assignedEmployees", "assignedSubcontractors", "isAddEmployee",
            "isAddSubcontractor", "isAssign", "allocationCancel"]
        assert "D04 ¶174–184" in n["doc"]

    def test_confirmation_inputs_come_from_rule_inputs(self, spec):
        assert node(spec, "allocationConfirmation")["inputs"] == ["projectInfo"]

    def test_search_screen_has_no_documented_rule_inputs(self, spec):
        assert node(spec, "employeeSearchScreen")["inputs"] == []

    def test_untyped_write_nodes_need_a_design_ruling(self, real_docset, supplement):
        del supplement["design"]["nodes"]["writeMapEmployeeRecords"]["type"]
        with pytest.raises(ExtractionError, match="writeMapEmployeeRecords"):
            build_spec(real_docset, supplement)

    def test_design_cannot_retype_a_declared_user_task(self, real_docset, supplement):
        supplement["design"]["nodes"]["allocationConfirmation"]["type"] = "serviceTask"
        with pytest.raises(ExtractionError, match="allocationConfirmation"):
            build_spec(real_docset, supplement)


class TestFlows:
    def test_flows(self, spec):
        cond = "return {0} != null && {0};".format
        assert spec["flows"] == [
            {"from": "start", "to": "allocationMainScreen"},
            {"from": "allocationMainScreen", "to": GATEWAY},
            {"from": GATEWAY, "to": "end1", "name": "allocationCancel = true",
             "condition": cond("allocationCancel")},
            {"from": GATEWAY, "to": "employeeSearchScreen", "name": "isAddEmployee = true",
             "condition": cond("isAddEmployee")},
            {"from": "employeeSearchScreen", "to": "allocationMainScreen",
             "name": "empCancel = true / confirm"},
            {"from": GATEWAY, "to": "subcontractorSearchScreen",
             "name": "isAddSubcontractor = true", "condition": cond("isAddSubcontractor")},
            {"from": "subcontractorSearchScreen", "to": "allocationMainScreen",
             "name": "SubconCancel = true / confirm"},
            {"from": GATEWAY, "to": "allocationConfirmation", "name": "isAssign = true",
             "condition": cond("isAssign")},
            {"from": "allocationConfirmation", "to": "writeMapEmployeeRecords"},
            {"from": "writeMapEmployeeRecords", "to": "writeMapSubcontractorRecords"},
            {"from": "writeMapSubcontractorRecords", "to": "end2"},
        ]

    def test_flow_ids_will_be_unique_in_the_generator(self, spec):
        pairs = [(f["from"], f["to"]) for f in spec["flows"]]
        assert len(pairs) == len(set(pairs))


class TestTransformationsAreDisclosed:
    def test_generated_assumptions_follow_the_supplement_ones(self, spec, supplement):
        ids = [a["id"] for a in spec["assumptions"]]
        authored = [a["id"] for a in supplement["assumptions"]]
        assert ids[:len(authored)] == authored
        assert ids[len(authored):] == ["T-1", "T-2", "T-3", "T-4"]

    def test_each_transformation_is_explained_with_anchors(self, spec):
        t = {a["id"]: a["text"] for a in spec["assumptions"] if a["id"].startswith("T-")}
        assert "synthesized" in t["T-1"] and "D03 ¶93–115" in t["T-1"]
        assert "empCancel = true" in t["T-2"] and "D03 ¶102–103" in t["T-2"]
        assert "SubconCancel = true" in t["T-3"] and "D03 ¶112–113" in t["T-3"]
        assert "3 incoming flows" in t["T-4"] and "Allocation Main Screen" in t["T-4"]

    def test_diagnostics_report_the_same_transformations(self, result):
        codes = [d.code for d in result.diagnostics]
        assert codes.count("gateway-synthesized") == 1
        assert codes.count("branches-merged") == 2
        assert codes.count("implicit-join") == 1

    def test_every_assumption_with_citations_has_verified_support(self, supplement):
        for a in supplement["assumptions"]:
            if "¶" in a["text"]:
                assert a.get("support"), a["id"]


class TestGeneratorCompatibility:
    def test_bpmn_is_well_formed_with_unique_ids(self, spec):
        root = ET.fromstring(emit_bpmn(spec))
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))
        proc = root.find(f"{BPMN}process")
        assert re.fullmatch(r"[a-z][A-Za-z0-9]*", proc.get("id"))
        assert len(list(root.iter(f"{BPMN}userTask"))) == 4
        assert len(list(root.iter(f"{BPMN}serviceTask"))) == 2
        assert len(list(root.iter(f"{BPMN}exclusiveGateway"))) == 1
        assert len(list(root.iter(f"{BPMN}sequenceFlow"))) == 11

    def test_spec_file_on_disk_is_the_current_extraction(self, spec):
        on_disk = json.loads((SPECS / "allocations.json").read_text(encoding="utf-8"))
        assert on_disk == spec
