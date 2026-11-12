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


class TestGeneratedProjectCompilesAndRunsOnBamoe:
    """Facts verified by running `mvn test` on the generated allocations project."""

    def test_models_are_serializable(self, allocations):
        src = (allocations / "src/main/java/nssol/model/MapEmployee.java").read_text()
        assert "implements java.io.Serializable" in src
        assert "serialVersionUID" in src

    def test_flat_classpath_only_when_a_variable_is_a_list(self, allocations, register):
        assert "quarkus.test.flat-class-path=true" in \
            (allocations / "src/main/resources/application.properties").read_text()
        assert "flat-class-path" not in \
            (register / "src/main/resources/application.properties").read_text()

    def test_scenario_tests_use_one_work_item_per_step(self, allocations):
        src = (allocations / "src/test/java/nssol/AllocationsProcessTest.java").read_text()
        assert src.count("@Test") == 3
        assert 'getName()).isEqualTo("Allocation Confirmation")' in src
        assert "step1_assignedEmployees0" in src and "step2_assignedEmployees0" in src
        assert "new ArrayList<>(List.of(" in src
        assert "import java.util.ArrayList;" in src
        assert "MapEmployeeStore.clear();" in src and "MapSubcontractorStore.clear();" in src


@pytest.fixture(scope="module")
def toggle(tmp_path_factory):
    out = tmp_path_factory.mktemp("toggle")
    emit_project(_load("update_language_toggle"), SKELETON, out)
    return out


class TestScalarServiceStub:
    """A service task may save a plain value (here a Boolean), not only a model."""

    def test_store_saves_the_scalar_type_without_a_model_import(self, toggle):
        src = _service(toggle, "LanguageToggleStore")
        assert "import nssol.model" not in src
        assert "record SaveCall(java.lang.Boolean value)" in src
        assert "public java.lang.Boolean update(java.lang.Boolean toggleValue)" in src

    def test_no_model_classes_and_no_flat_classpath(self, toggle):
        assert not (toggle / "src/main/java/nssol/model").exists()
        assert "flat-class-path" not in \
            (toggle / "src/main/resources/application.properties").read_text()


class TestProcessWithoutUserTasks:
    def test_scenarios_start_the_instance_and_check_the_saved_value(self, toggle):
        src = (toggle / "src/test/java/nssol/UpdateLanguageToggleProcessTest.java").read_text()
        assert src.count("@Test") == 2
        assert "workItems" not in src
        assert 'model.update(Map.of("toggleValue", true));' in src
        assert "assertThat(LanguageToggleStore.saves()).hasSize(1);" in src
        assert "assertThat(LanguageToggleStore.saves().get(0).value()).isEqualTo(false);" in src
        assert "import nssol.model" not in src
