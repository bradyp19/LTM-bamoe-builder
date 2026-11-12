import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from ltm_gen.bpmn_emit import emit_bpmn

SPEC = json.loads((Path(__file__).parents[1] / "specs" / "register_project.json").read_text())
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


@pytest.fixture(scope="module")
def xml():
    out = emit_bpmn(SPEC)
    return ET.fromstring(out), out


class TestStructure:
    def test_well_formed_and_process_id(self, xml):
        root, _ = xml
        proc = root.find(f"{BPMN}process")
        assert proc.get("id") == "registerProject"
        assert proc.get("isExecutable") == "true"

    def test_process_id_camel_case_no_hyphens(self, xml):
        root, _ = xml
        pid = root.find(f"{BPMN}process").get("id")
        assert re.fullmatch(r"[a-z][A-Za-z0-9]*", pid)

    def test_documented_nodes_present(self, xml):
        root, _ = xml
        names = {e.get("name") for e in root.iter() if e.get("name")}
        for n in ["Start", "Fill Project Registration Form", "Cancel?",
                  "Write / Save NSSOL Projects Record",
                  "Cancelled — no data written", "Completed"]:
            assert n in names

    def test_variables_with_types(self, xml):
        root, _ = xml
        props = {p.get("id") for p in root.iter(f"{BPMN}property")}
        assert props == {"cancel", "isUpdate", "projectRegistration"}
        items = {i.get("id"): i.get("structureRef")
                 for i in root.iter(f"{BPMN}itemDefinition")}
        assert items["_cancelItem"] == "java.lang.Boolean"
        assert items["_projectRegistrationItem"] == "nssol.model.ProjectRegistration"

    def test_gateway_conditions_java_and_escaped(self, xml):
        root, raw = xml
        conds = [c.text for c in root.iter(f"{BPMN}conditionExpression")]
        assert "return cancel != null && cancel;" in conds
        assert "return cancel == null || !cancel;" in conds
        assert "&amp;&amp;" in raw  # escaped in XML

    def test_service_task_java_binding_conventions(self, xml):
        root, _ = xml
        st = next(e for e in root.iter(f"{BPMN}serviceTask"))
        assert st.get("implementation") == "##Java"
        in_names = [d.get("name") for d in st.iter(f"{BPMN}dataInput")]
        out_names = [d.get("name") for d in st.iter(f"{BPMN}dataOutput")]
        assert in_names == ["Parameter"]
        assert out_names == ["Result"]
        iface = next(e for e in root.iter(f"{BPMN}interface"))
        assert iface.get("implementationRef") == "nssol.service.ProjectStore"

    def test_no_undocumented_nodes(self, xml):
        root, _ = xml
        tasks = [e.get("name") for e in root.iter() if e.tag.endswith("Task")]
        assert tasks == ["Fill Project Registration Form",
                         "Write / Save NSSOL Projects Record"]

    def test_documentation_carries_conflicts(self, xml):
        _, raw = xml
        assert "C1 CONFLICT" in raw
        assert "SR-3" in raw


ALLOC = json.loads((Path(__file__).parents[1] / "specs" / "allocations.json").read_text())
TOGGLE = json.loads((Path(__file__).parents[1] / "specs" / "update_language_toggle.json").read_text())


@pytest.fixture(scope="module")
def alloc():
    return ET.fromstring(emit_bpmn(ALLOC))


@pytest.fixture(scope="module")
def toggle():
    return ET.fromstring(emit_bpmn(TOGGLE))


BPMNDI = "{http://www.omg.org/spec/BPMN/20100524/DI}"
DC = "{http://www.omg.org/spec/DD/20100524/DC}"
DI = "{http://www.omg.org/spec/DD/20100524/DI}"


def _get_shape_bounds(root: ET.Element) -> dict[str, tuple[int, int, int, int]]:
    """Extract {node_id: (x, y, w, h)} from BPMNShape definitions."""
    shapes = {}
    for shape in root.iter(f"{BPMNDI}BPMNShape"):
        eid = shape.get("bpmnElement")
        bounds = shape.find(f"{DC}Bounds")
        assert bounds is not None, f"Missing Bounds for shape {eid}"
        x = int(bounds.get("x"))
        y = int(bounds.get("y"))
        w = int(bounds.get("width"))
        h = int(bounds.get("height"))
        shapes[eid] = (x, y, w, h)
    return shapes


def _get_edge_waypoints(root: ET.Element) -> dict[str, list[tuple[int, int]]]:
    """Extract {flow_id: [(x, y), ...]} from BPMNEdge definitions."""
    edges = {}
    for edge in root.iter(f"{BPMNDI}BPMNEdge"):
        eid = edge.get("bpmnElement")
        wps = []
        for wp in edge.findall(f"{DI}waypoint"):
            wps.append((int(wp.get("x")), int(wp.get("y"))))
        edges[eid] = wps
    return edges


def _get_edge_labels(root: ET.Element) -> dict[str, tuple[int, int, int, int]]:
    """Extract {flow_id: (x, y, w, h)} for edges with BPMNLabel."""
    labels = {}
    for edge in root.iter(f"{BPMNDI}BPMNEdge"):
        eid = edge.get("bpmnElement")
        label = edge.find(f"{BPMNDI}BPMNLabel")
        if label is not None:
            bounds = label.find(f"{DC}Bounds")
            if bounds is not None:
                labels[eid] = (int(bounds.get("x")), int(bounds.get("y")),
                               int(bounds.get("width")), int(bounds.get("height")))
    return labels


class TestBpmnLayout:
    @pytest.mark.parametrize("spec_data", [SPEC, ALLOC, TOGGLE])
    def test_no_two_shapes_overlap(self, spec_data):
        root = ET.fromstring(emit_bpmn(spec_data))
        shapes = _get_shape_bounds(root)
        shape_list = list(shapes.items())
        for i in range(len(shape_list)):
            id1, (x1, y1, w1, h1) = shape_list[i]
            for j in range(i + 1, len(shape_list)):
                id2, (x2, y2, w2, h2) = shape_list[j]
                # Check bounding box collision
                overlap_x = (x1 < x2 + w2) and (x1 + w1 > x2)
                overlap_y = (y1 < y2 + h2) and (y1 + h1 > y2)
                assert not (overlap_x and overlap_y), (
                    f"Shapes overlap: {id1} ({x1},{y1},{w1},{h1}) and {id2} ({x2},{y2},{w2},{h2})"
                )

    @pytest.mark.parametrize("spec_data", [SPEC, ALLOC, TOGGLE])
    def test_all_nodes_and_flows_have_di_elements(self, spec_data):
        root = ET.fromstring(emit_bpmn(spec_data))
        shapes = _get_shape_bounds(root)
        edges = _get_edge_waypoints(root)
        for n in spec_data["nodes"]:
            assert n["id"] in shapes, f"Missing shape for node {n['id']}"
            x, y, w, h = shapes[n["id"]]
            assert x >= 0 and y >= 0 and w > 0 and h > 0

        for f in spec_data["flows"]:
            flow_id = f"_sf_{f['from']}_{f['to']}"
            assert flow_id in edges, f"Missing edge for flow {flow_id}"
            assert len(edges[flow_id]) >= 2, f"Edge {flow_id} has fewer than 2 waypoints"

    @pytest.mark.parametrize("spec_data", [SPEC, ALLOC, TOGGLE])
    def test_edge_waypoints_connect_to_source_and_target_bounds(self, spec_data):
        root = ET.fromstring(emit_bpmn(spec_data))
        shapes = _get_shape_bounds(root)
        edges = _get_edge_waypoints(root)
        for f in spec_data["flows"]:
            flow_id = f"_sf_{f['from']}_{f['to']}"
            wps = edges[flow_id]
            sx, sy, sw, sh = shapes[f["from"]]
            tx, ty, tw, th = shapes[f["to"]]

            # Start point should touch source perimeter
            start_x, start_y = wps[0]
            assert sx <= start_x <= sx + sw, f"Edge {flow_id} start x={start_x} outside source [{sx}, {sx+sw}]"
            assert sy <= start_y <= sy + sh, f"Edge {flow_id} start y={start_y} outside source [{sy}, {sy+sh}]"

            # End point should touch target perimeter
            end_x, end_y = wps[-1]
            assert tx <= end_x <= tx + tw, f"Edge {flow_id} end x={end_x} outside target [{tx}, {tx+tw}]"
            assert ty <= end_y <= ty + th, f"Edge {flow_id} end y={end_y} outside target [{ty}, {ty+th}]"

    def test_allocations_gateway_branches_on_separate_rows(self, alloc):
        shapes = _get_shape_bounds(alloc)
        branch_targets = ["end1", "employeeSearchScreen", "subcontractorSearchScreen", "allocationConfirmation"]
        y_coords = [shapes[tid][1] for tid in branch_targets]
        assert len(set(y_coords)) == len(branch_targets), f"Branches share Y coords: {dict(zip(branch_targets, y_coords))}"

    def test_allocations_back_edges_routed_cleanly(self, alloc):
        shapes = _get_shape_bounds(alloc)
        edges = _get_edge_waypoints(alloc)
        # Check employeeSearchScreen -> allocationMainScreenMerge
        f_emp = "_sf_employeeSearchScreen_allocationMainScreenMerge"
        wps_emp = edges[f_emp]
        merge_y = shapes["allocationMainScreenMerge"][1]
        # Back edge waypoints should stay at or above the merge node Y
        for wp_x, wp_y in wps_emp[:-1]:
            assert wp_y <= merge_y + shapes["allocationMainScreenMerge"][3], f"Waypoint {wp_x},{wp_y} drops below merge"

    def test_conditional_flows_have_labels(self):
        root = ET.fromstring(emit_bpmn(ALLOC))
        labels = _get_edge_labels(root)
        for f in ALLOC["flows"]:
            flow_id = f"_sf_{f['from']}_{f['to']}"
            if f.get("name"):
                assert flow_id in labels, f"Flow {flow_id} with name {f['name']} should have BPMNLabel"

    @pytest.mark.parametrize("spec_data", [SPEC, ALLOC, TOGGLE])
    def test_deterministic_output(self, spec_data):
        out1 = emit_bpmn(spec_data)
        out2 = emit_bpmn(spec_data)
        assert out1 == out2

    @pytest.mark.parametrize("spec_data", [SPEC, ALLOC, TOGGLE])
    def test_standard_shape_sizes(self, spec_data):
        root = ET.fromstring(emit_bpmn(spec_data))
        shapes = _get_shape_bounds(root)
        for n in spec_data["nodes"]:
            _, _, w, h = shapes[n["id"]]
            if n["type"] in ("start", "end"):
                assert (w, h) == (36, 36)
            elif n["type"] == "xor":
                assert (w, h) == (50, 50)
            elif n["type"] in ("userTask", "serviceTask"):
                assert w >= 140 and h >= 60

    def test_allocations_merge_gateway_precedes_main_screen(self, alloc):
        shapes = _get_shape_bounds(alloc)
        merge_x = shapes["allocationMainScreenMerge"][0]
        main_x = shapes["allocationMainScreen"][0]
        assert merge_x < main_x, "Merge gateway should be to the left of Allocation Main Screen"


class TestAllocationsBpmn:
    def test_merge_gateway_converges_and_decision_gateway_diverges(self, alloc):
        gateways = {g.get("id"): g.get("gatewayDirection")
                    for g in alloc.iter(f"{BPMN}exclusiveGateway")}
        assert gateways == {"allocationMainScreenMerge": "Converging",
                            "allocationMainScreenGateway": "Diverging"}

    def test_no_task_has_several_incoming_flows(self, alloc):
        for tag in ("userTask", "serviceTask", "endEvent"):
            for e in alloc.iter(f"{BPMN}{tag}"):
                assert len(e.findall(f"{BPMN}incoming")) <= 1, e.get("id")

    def test_list_variable_item_carries_generic_but_service_item_does_not(self, alloc):
        items = {i.get("id"): i.get("structureRef") for i in alloc.iter(f"{BPMN}itemDefinition")}
        assert items["_assignedEmployeesItem"] == "java.util.List<nssol.model.MapEmployee>"
        assert items["_assignedEmployeesRawItem"] == "java.util.List"
        refs = {d.get("itemSubjectRef") for st in alloc.iter(f"{BPMN}serviceTask")
                for d in st.iter(f"{BPMN}dataInput")}
        assert refs == {"_assignedEmployeesRawItem", "_assignedSubcontractorsRawItem"}

    def test_node_documentation_fits_the_metadata_column(self, alloc):
        for n in alloc.find(f"{BPMN}process"):
            doc = n.find(f"{BPMN}documentation")
            if n.tag != f"{BPMN}documentation" and doc is not None:
                assert len(doc.text) <= 255, n.get("id")

    def test_truncated_node_documentation_is_kept_in_full_on_the_process(self, alloc):
        process_doc = alloc.find(f"{BPMN}process").find(f"{BPMN}documentation").text
        assert "[allocationMainScreen] Interface: NSSOL_SEC_Allocation (D04 ¶168–237)." in process_doc
