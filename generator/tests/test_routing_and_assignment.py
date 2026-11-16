"""Optional spec features: gateway default flow, flow priority, task candidate groups.

None of them is used by the committed specs, so the committed output is unchanged;
these tests build variants of the allocations spec.
"""

import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from ltm_gen.bpmn_emit import emit_bpmn
from ltm_gen.java_emit import emit_process_test

SPEC = json.loads((Path(__file__).parents[1] / "specs" / "allocations.json").read_text())
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
DROOLS = "{http://www.jboss.org/drools}"
GATEWAY = "allocationMainScreenGateway"


def _flow(spec, source, target):
    return next(f for f in spec["flows"] if f["from"] == source and f["to"] == target)


def _parse(spec):
    return ET.fromstring(emit_bpmn(spec))


def _element(root, tag, element_id):
    return next(e for e in root.iter(f"{BPMN}{tag}") if e.get("id") == element_id)


class TestDefaultFlow:
    def test_gateway_names_its_default_flow_and_that_flow_has_no_condition(self):
        spec = copy.deepcopy(SPEC)
        flow = _flow(spec, GATEWAY, "end1")
        del flow["condition"]
        flow["default"] = True
        root = _parse(spec)
        flow_id = f"_sf_{GATEWAY}_end1"
        assert _element(root, "exclusiveGateway", GATEWAY).get("default") == flow_id
        assert _element(root, "sequenceFlow", flow_id).find(f"{BPMN}conditionExpression") is None

    def test_no_default_attribute_without_a_default_flow(self):
        root = _parse(SPEC)
        for gateway in root.iter(f"{BPMN}exclusiveGateway"):
            assert gateway.get("default") is None


class TestFlowPriority:
    def test_priority_is_emitted_as_a_drools_attribute(self):
        spec = copy.deepcopy(SPEC)
        _flow(spec, GATEWAY, "allocationConfirmation")["priority"] = 1
        root = _parse(spec)
        flow = _element(root, "sequenceFlow", f"_sf_{GATEWAY}_allocationConfirmation")
        assert flow.get(f"{DROOLS}priority") == "1"

    def test_no_priority_attribute_by_default(self):
        root = _parse(SPEC)
        assert all(f.get(f"{DROOLS}priority") is None for f in root.iter(f"{BPMN}sequenceFlow"))

    def test_layout_with_default_flow_and_priority_maintains_di_integrity(self):
        spec = copy.deepcopy(SPEC)
        f_end = _flow(spec, GATEWAY, "end1")
        del f_end["condition"]
        f_end["default"] = True
        _flow(spec, GATEWAY, "allocationConfirmation")["priority"] = 1
        root = _parse(spec)
        shapes = [s for s in root.iter("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNShape")]
        edges = [e for e in root.iter("{http://www.omg.org/spec/BPMN/20100524/DI}BPMNEdge")]
        assert len(shapes) == len(spec["nodes"])
        assert len(edges) == len(spec["flows"])


class TestCandidateGroups:
    def _spec(self, groups):
        spec = copy.deepcopy(SPEC)
        next(n for n in spec["nodes"] if n["id"] == "allocationMainScreen")["candidateGroups"] = groups
        return spec

    def test_group_id_input_carries_the_comma_joined_groups(self):
        root = _parse(self._spec(["NP Users", "NP Administrators"]))
        task = _element(root, "userTask", "allocationMainScreen")
        inputs = {d.get("id"): d for d in task.iter(f"{BPMN}dataInput")}
        group = inputs["_allocationMainScreen_GroupId"]
        assert group.get("name") == "GroupId"
        refs = [r.text for r in task.find(f"{BPMN}ioSpecification").find(f"{BPMN}inputSet")]
        assert "_allocationMainScreen_GroupId" in refs
        assignment = next(a for a in task.iter(f"{BPMN}dataInputAssociation")
                          if a.find(f"{BPMN}targetRef").text == "_allocationMainScreen_GroupId")
        assert assignment.find(f"{BPMN}assignment").find(f"{BPMN}from").text == "NP Users,NP Administrators"
        item = group.get("itemSubjectRef")
        assert next(i for i in root.iter(f"{BPMN}itemDefinition")
                    if i.get("id") == item).get("structureRef") == "java.lang.String"

    def test_other_tasks_and_ids_stay_unique(self):
        root = _parse(self._spec(["NP Users"]))
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))
        task = _element(root, "userTask", "employeeSearchScreen")
        assert all(d.get("name") != "GroupId" for d in task.iter(f"{BPMN}dataInput"))

    def test_group_id_variable_keeps_its_own_type_and_unique_id(self):
        spec = self._spec(["NP Users"])
        spec["variables"].append({"name": "groupId", "type": "java.lang.Integer"})
        root = _parse(spec)
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))
        variable = _element(root, "property", "groupId")
        variable_type = _element(root, "itemDefinition", variable.get("itemSubjectRef"))
        assert variable_type.get("structureRef") == "java.lang.Integer"
        for group in root.iter(f"{BPMN}dataInput"):
            if group.get("name") == "GroupId":
                group_type = _element(root, "itemDefinition", group.get("itemSubjectRef"))
                assert group_type.get("structureRef") == "java.lang.String"
                assert group_type is not variable_type

    def test_group_item_fallback_avoids_variable_and_node_ids(self):
        spec = self._spec(["NP Users"])
        spec["variables"] += [
            {"name": "groupId", "type": "java.lang.Integer"},
            {"name": "_groupIdItem_2", "type": "java.lang.Integer"}]
        spec["nodes"].append({"id": "_groupIdItem_3", "type": "end", "name": "Extra End"})
        root = _parse(spec)
        ids = [e.get("id") for e in root.iter() if e.get("id")]
        assert len(ids) == len(set(ids))

    def test_no_group_input_by_default(self):
        root = _parse(SPEC)
        assert all(d.get("name") != "GroupId" for d in root.iter(f"{BPMN}dataInput"))

    def test_generated_test_identity_belongs_to_the_groups(self):
        java = emit_process_test(self._spec(["NP Users", "NP Administrators"]))
        assert ('new StaticIdentityProvider("tester", '
                'java.util.List.of("NP Administrators", "NP Users"))') in java

    def test_generated_test_identity_is_unchanged_without_groups(self):
        java = emit_process_test(SPEC)
        assert 'new StaticIdentityProvider("tester")' in java


class TestDescriptionTemplate:
    def test_template_is_emitted_as_the_custom_description_metadata(self):
        spec = copy.deepcopy(SPEC)
        spec["process"]["descriptionTemplate"] = "NSSOL Allocations - #{projectInfo.projectName} & more"
        root = _parse(spec)
        process = root.find(f"{BPMN}process")
        meta = next(m for m in process.iter(f"{DROOLS}metaData") if m.get("name") == "customDescription")
        assert meta.find(f"{DROOLS}metaValue").text == "NSSOL Allocations - #{projectInfo.projectName} & more"
        children = [c.tag for c in process]
        assert children.index(f"{BPMN}documentation") < children.index(f"{BPMN}extensionElements")

    def test_no_metadata_by_default(self):
        assert "customDescription" not in emit_bpmn(SPEC)
