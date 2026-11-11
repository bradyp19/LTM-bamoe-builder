"""Source facts read from the real LTM documents, each with its ¶ anchor."""

from ltm_extract import cite
from ltm_extract.facts import interfaces, process_models, record_types

RP = "NSSOL Register Project"
ALLOC = "NSSOL Allocations"


def test_cite_format():
    assert cite("D03", 26) == "D03 ¶26"
    assert cite("D03", 26, 26) == "D03 ¶26"
    assert cite("D03", 24, 28) == "D03 ¶24–28"


class TestDocSet:
    def test_documents_keyed_by_number(self, real_docset):
        assert list(real_docset.documents) == [f"D0{i}" for i in range(1, 8)]


class TestProcessModels:
    def test_all_three_found(self, real_docset):
        assert list(process_models(real_docset)) == [
            RP, ALLOC, "NSSOL Update Language Toggle"]

    def test_register_project_variables(self, real_docset):
        p = process_models(real_docset)[RP]
        assert [(v.name, v.type, v.required, v.anchor.cite()) for v in p.variables] == [
            ("cancel", "Boolean", False, "D03 ¶26"),
            ("isUpdate", "Boolean", False, "D03 ¶27"),
            ("projectRegistration", "NSSOL Projects record", False, "D03 ¶28"),
        ]
        assert p.variables_anchor.cite() == "D03 ¶24–28"

    def test_register_project_flow_is_image_only(self, real_docset):
        flow = process_models(real_docset)[RP].flow
        assert flow.kind == "image"
        assert flow.image == "media/image1.png"
        assert flow.anchor.cite() == "D03 ¶31"
        assert flow.figure == "Figure 1"
        assert flow.lines == []

    def test_allocations_flow_is_text(self, real_docset):
        flow = process_models(real_docset)[ALLOC].flow
        assert flow.kind == "text"
        assert flow.anchor.cite() == "D03 ¶75–134"  # fence to fence
        assert flow.lines[0].index == 76 and flow.lines[0].text == "START"
        assert flow.lines[-1].index == 133

    def test_allocations_variables(self, real_docset):
        p = process_models(real_docset)[ALLOC]
        assert [v.name for v in p.variables] == [
            "projectInfo", "selectedEmployees", "selectedSubcontractors",
            "assignedEmployees", "assignedSubcontractors", "isAddEmployee",
            "isAddSubcontractor", "isAssign", "allocationCancel", "empCancel",
            "SubconCancel"]
        by_name = {v.name: v for v in p.variables}
        assert by_name["projectInfo"].required is True
        assert by_name["selectedEmployees"].required is False
        assert by_name["assignedEmployees"].type == "NSSOL Map Employees list"
        assert by_name["empCancel"].parameter == "No (internal)"
        assert by_name["projectInfo"].extra == {"Default": "projectId = 3 (default for dev)"}
        assert p.variables_anchor.cite() == "D03 ¶59–71"

    def test_attributes_and_anchor(self, real_docset):
        p = process_models(real_docset)[ALLOC]
        assert p.anchor.start == 43
        value, anchor = p.attributes["Process Name Template"]
        assert value == '`"NSSOL Allocations - " & pv!projectInfo[projectName]`'
        assert anchor.cite() == "D03 ¶49"


class TestRecordTypes:
    def test_names_normalised(self, real_docset):
        names = list(record_types(real_docset))
        assert names[:5] == ["NSSOL Projects", "NSSOL Employees", "NSSOL Subcontractors",
                             "NSSOL Map Employees", "NSSOL Map Subcontractors"]

    def test_projects_fields(self, real_docset):
        r = record_types(real_docset)["NSSOL Projects"]
        assert r.primary_key == "projectId"
        assert len(r.fields) == 27
        assert r.fields_anchor.cite() == "D05 ¶48–76"
        first, status, last = r.fields[0], r.fields[9], r.fields[-1]
        assert (first.name, first.data_type, first.nullable, first.anchor.cite()) == (
            "projectId", "Integer", False, "D05 ¶50")
        assert (status.name, status.data_type, status.nullable, status.anchor.cite()) == (
            "status", "Text", True, "D05 ¶59")
        assert (last.name, last.data_type, last.nullable) == ("isActive", "Boolean", False)

    def test_map_employees_fields(self, real_docset):
        r = record_types(real_docset)["NSSOL Map Employees"]
        assert r.fields_anchor.cite() == "D05 ¶177–207"
        assert {f.data_type for f in r.fields} == {"Integer", "Text", "Decimal",
                                                   "DateTime", "Boolean"}


class TestInterfaces:
    def test_registration_form(self, real_docset):
        i = interfaces(real_docset)["NSSOL_FRM_ProjectRegistration"]
        assert i.anchor.cite() == "D04 ¶24–79"
        assert [r.name for r in i.rule_inputs] == ["isUpdate", "projectRegistration", "cancel"]
        assert len(i.form_fields) == 25
        assert [f.label for f in i.form_fields if f.required] == [
            "Project Name", "Order Amount (Million Yen)", "Expected Order Amount"]
        status = next(f for f in i.form_fields if f.label == "Status")
        assert status.anchor.cite() == "D04 ¶48" and status.required is False

    def test_allocation_screen(self, real_docset):
        i = interfaces(real_docset)["NSSOL_SEC_Allocation"]
        assert i.anchor.cite() == "D04 ¶168–237"
        assert i.rule_inputs_anchor.cite() == "D04 ¶174–184"
        assert [r.name for r in i.rule_inputs] == [
            "projectInfo", "selectedEmployees", "selectedSubcontractors",
            "assignedEmployees", "assignedSubcontractors", "isAddEmployee",
            "isAddSubcontractor", "isAssign", "allocationCancel"]

    def test_interface_without_rule_inputs(self, real_docset):
        i = interfaces(real_docset)["NSSOL_GRID_Employee_Search_Screen"]
        assert i.anchor.cite() == "D04 ¶241–251"
        assert i.rule_inputs == [] and i.rule_inputs_anchor is None

    def test_sixteen_interfaces(self, real_docset):
        assert len(interfaces(real_docset)) == 16
