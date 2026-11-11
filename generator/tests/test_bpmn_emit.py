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
