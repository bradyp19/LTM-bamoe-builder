import json
from pathlib import Path

import pytest

from ltm_gen.project_emit import emit_project

SPECS = Path(__file__).parents[1] / "specs"
SKELETON = Path(__file__).parents[2] / "register-project"


def _load(name):
    return json.loads((SPECS / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def allocations(tmp_path_factory):
    out = tmp_path_factory.mktemp("alloc")
    emit_project(_load("allocations"), SKELETON, out)
    return out


@pytest.fixture(scope="module")
def register(tmp_path_factory):
    out = tmp_path_factory.mktemp("reg")
    emit_project(_load("register_project"), SKELETON, out)
    return out


def _service(project: Path, cls: str) -> str:
    return (project / "src/main/java/nssol/service" / f"{cls}.java").read_text()


class TestServiceStubTypes:
    def test_employee_store_uses_its_own_model_as_list(self, allocations):
        src = _service(allocations, "MapEmployeeStore")
        assert "import nssol.model.MapEmployee;" in src
        assert "ProjectRegistration" not in src
        assert "List<MapEmployee> save(List<MapEmployee>" in src

    def test_subcontractor_store_uses_its_own_model_as_list(self, allocations):
        src = _service(allocations, "MapSubcontractorStore")
        assert "import nssol.model.MapSubcontractor;" in src
        assert "MapEmployee" not in src
        assert "List<MapSubcontractor> save(List<MapSubcontractor>" in src

    def test_single_record_store_unchanged(self, register):
        src = _service(register, "ProjectStore")
        assert "public ProjectRegistration save(ProjectRegistration projectRegistration)" in src
        assert "record SaveCall(ProjectRegistration registration)" in src

    def test_register_project_store_matches_reference(self, register):
        reference = Path(__file__).parents[2] / "register-project-generated" / \
            "src/main/java/nssol/service/ProjectStore.java"
        assert _service(register, "ProjectStore") == reference.read_text()
