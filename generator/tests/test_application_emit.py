"""One project for every process of an application (emit_application)."""

import copy
import json
from pathlib import Path

import pytest

from ltm_gen import ApplicationError, emit_application
from ltm_gen.web_emit import task_path

SPECS = Path(__file__).parents[1] / "specs"
SKELETON = Path(__file__).parents[2] / "register-project"
NAMES = ["register_project", "allocations", "update_language_toggle"]


APPLICATION = {"name": "NSSOL POC", "evidence": "test fixture"}


def _specs():
    specs = [json.loads((SPECS / f"{n}.json").read_text()) for n in NAMES]
    for s in specs:
        s.setdefault("application", dict(APPLICATION))
    return specs


def _problems(specs, tmp_path):
    with pytest.raises(ApplicationError) as e:
        emit_application(specs, SKELETON, tmp_path / "out")
    assert not (tmp_path / "out").exists(), "nothing is written when the specs conflict"
    return e.value.problems


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    out = tmp_path_factory.mktemp("app") / "nssol-poc"
    emit_application(_specs(), SKELETON, out)
    return out


class TestOneProject:
    def test_one_bpmn_per_process(self, project):
        assert sorted(p.name for p in (project / "src/main/resources").glob("*.bpmn")) == \
            ["allocations.bpmn", "registerProject.bpmn", "updateLanguageToggle.bpmn"]

    def test_one_test_class_per_process_plus_the_audit_helper(self, project):
        assert sorted(p.name for p in (project / "src/test/java/nssol").glob("*.java")) == [
            "AllocationsProcessTest.java", "RegisterProjectProcessTest.java", "StepAudit.java",
            "UpdateLanguageToggleProcessTest.java"]

    def test_artifact_and_name_come_from_the_application(self, project):
        pom = (project / "pom.xml").read_text()
        assert "<artifactId>nssol-poc</artifactId>" in pom
        assert "<name>NSSOL POC</name>" in pom
        assert "your-bamoe-business-service" not in pom

    def test_flat_classpath_added_once(self, project):
        props = (project / "src/main/resources/application.properties").read_text()
        assert props.count("quarkus.test.flat-class-path=true") == 1

    def test_dev_pool_keeps_idle_h2_connections(self, project):
        props = (project / "src/main/resources/application.properties").read_text()
        assert "%dev.quarkus.datasource.jdbc.idle-removal-interval=0S" in props

    def test_audit_queries_request_all_rows(self, project):
        res = project / "src/main/resources/META-INF/resources/ui/app.js"
        audit = next(project.rglob("StepAudit.java")).read_text()
        for text in (res.read_text(), audit):
            assert "pagination: { limit: 100000, offset: 0 }" in text
            assert "GetAllUserTaskInstanceState {" not in text

    def test_webpage_denied_outside_dev(self, project):
        props = (project / "src/main/resources/application.properties").read_text()
        assert "%prod.quarkus.http.auth.permission.webpage.policy=deny" in props

    def test_each_test_clears_only_its_own_stores(self, project):
        tests = project / "src/test/java/nssol"
        reg = (tests / "RegisterProjectProcessTest.java").read_text()
        alloc = (tests / "AllocationsProcessTest.java").read_text()
        assert "ProjectStore.clear();" in reg and "MapEmployeeStore" not in reg
        assert "MapEmployeeStore.clear();" in alloc and "ProjectStore.clear();" not in alloc

    def test_every_service_once(self, project):
        assert sorted(p.stem for p in (project / "src/main/java/nssol/service").glob("*.java")) == [
            "LanguageToggleStore", "MapEmployeeStore", "MapSubcontractorStore", "ProjectStore"]


class TestModelMerge:
    def test_shared_model_emitted_once_with_evidence_from_every_spec(self, project):
        src = (project / "src/main/java/nssol/model/ProjectRegistration.java").read_text()
        assert "registerProject" in src and "allocations" in src
        specs = _specs()
        fields = [f["name"] for f in specs[1]["models"]["ProjectRegistration"]["fields"]]
        positions = [src.index(f"private {t} {n};") for n, t in
                     ((f["name"], f["type"]) for f in specs[1]["models"]["ProjectRegistration"]["fields"])]
        assert positions == sorted(positions) and len(positions) == len(fields)

    def test_different_type_stops_with_both_definitions(self, tmp_path):
        specs = _specs()
        specs[1]["models"]["ProjectRegistration"]["fields"][0]["type"] = "String"
        problems = _problems(specs, tmp_path)
        assert len(problems) == 1
        assert "ProjectRegistration" in problems[0] and "'registerProject'" in problems[0] \
            and "'allocations'" in problems[0] and "projectId" in problems[0]
        assert specs[0]["models"]["ProjectRegistration"]["evidence"] in problems[0]

    def test_missing_field_stops(self, tmp_path):
        specs = _specs()
        specs[1]["models"]["ProjectRegistration"]["fields"].pop()
        assert "absent" in _problems(specs, tmp_path)[0]

    def test_different_order_stops(self, tmp_path):
        specs = _specs()
        specs[0]["models"]["ProjectRegistration"]["fields"].reverse()
        assert "different order" in _problems(specs, tmp_path)[0]


class TestCollisions:
    def test_duplicate_process_id(self, tmp_path):
        specs = _specs()
        specs[2]["process"]["id"] = "allocations"
        assert any("process id 'allocations'" in p for p in _problems(specs, tmp_path))

    def test_package_mismatch(self, tmp_path):
        specs = _specs()
        specs[2]["process"]["packageName"] = "other"
        assert any("share one packageName" in p for p in _problems(specs, tmp_path))

    def test_service_signature_clash(self, tmp_path):
        specs = _specs()
        node = next(n for n in specs[2]["nodes"] if n["type"] == "serviceTask")
        node["service"]["class"] = "nssol.service.ProjectStore"
        problems = _problems(specs, tmp_path)
        assert any("service class ProjectStore has different signatures" in p for p in problems)

    def test_different_applications(self, tmp_path):
        specs = _specs()
        specs[2]["application"] = dict(specs[2]["application"], name="Other App")
        assert any("different applications" in p for p in _problems(specs, tmp_path))

    def test_application_is_required(self, tmp_path):
        specs = _specs()
        del specs[0]["application"]
        assert any("names no application" in p for p in _problems(specs, tmp_path))

    def test_all_problems_reported_together(self, tmp_path):
        specs = _specs()
        specs[2]["process"]["packageName"] = "other"
        specs[1]["models"]["ProjectRegistration"]["fields"][0]["type"] = "String"
        assert len(_problems(specs, tmp_path)) == 2


class TestStepAudit:
    def test_every_step_is_checked_against_the_audit_record(self, project):
        src = (project / "src/test/java/nssol/AllocationsProcessTest.java").read_text()
        for spec in _specs()[1:2]:
            for t in spec["tests"]:
                assert src.count('audit.step("start"') == len(spec["tests"])
                for step in t["steps"]:
                    assert f'audit.step("{step["task"]}"' in src
        assert "UnitOfWorkExecutor.executeInUnitOfWork" in src
        assert 'StepAudit.write("allocations")' in src

    def test_service_tasks_that_must_or_must_not_run(self, project):
        src = (project / "src/test/java/nssol/RegisterProjectProcessTest.java").read_text()
        assert 'audit.finish(instance.id(), "COMPLETED", List.of("Write / Save NSSOL Projects Record"), List.of());' in src
        assert 'audit.finish(instance.id(), "COMPLETED", List.of(), List.of("Write / Save NSSOL Projects Record"));' in src


@pytest.fixture(scope="module")
def config(project):
    return json.loads((project / "src/main/resources/META-INF/resources/ui/application.json").read_text())


class TestWebpage:
    def test_static_files(self, project):
        ui = project / "src/main/resources/META-INF/resources/ui"
        assert sorted(p.name for p in ui.iterdir()) == ["app.css", "app.js", "application.json", "index.html"]

    def test_every_process_with_its_start_variables(self, config):
        by_id = {p["id"]: p for p in config["processes"]}
        assert list(by_id) == ["registerProject", "allocations", "updateLanguageToggle"]
        assert by_id["updateLanguageToggle"]["startVariables"] == ["toggleValue"]
        assert by_id["allocations"]["startVariables"] == ["projectInfo"]
        assert set(by_id["registerProject"]["startVariables"]) >= {"isUpdate", "projectRegistration"}

    def test_every_user_task_with_its_inputs_and_outputs(self, config):
        for spec, proc in zip(_specs(), config["processes"]):
            tasks = [n for n in spec["nodes"] if n["type"] == "userTask"]
            assert [(t["id"], t["name"], t["inputs"], t["outputs"]) for t in proc["userTasks"]] == \
                [(n["id"], n["name"], n.get("inputs", []), n.get("outputs", [])) for n in tasks]
            names = {v["name"] for v in proc["variables"]}
            assert all(set(t["inputs"]) | set(t["outputs"]) <= names for t in proc["userTasks"])

    def test_list_and_record_variables_carry_their_model_fields(self, config):
        alloc = next(p for p in config["processes"] if p["id"] == "allocations")
        kinds = {v["name"]: (v["kind"], v.get("model")) for v in alloc["variables"]}
        assert kinds["assignedEmployees"] == ("list", "MapEmployee")
        assert kinds["projectInfo"] == ("model", "ProjectRegistration")
        assert kinds["isAssign"] == ("scalar", None)
        assert [f["name"] for f in config["models"]["MapEmployee"]][:2] == ["employeeMappedId", "projectId"]

    def test_all_eight_scenarios_are_offered(self, config):
        assert sum(len(p["scenarios"]) for p in config["processes"]) == 8

    def test_task_paths_match_the_generated_rest_resources(self):
        assert task_path("Fill Project Registration Form") == "Fill_Project_Registration_Form"
        assert task_path("Write / Save NSSOL Projects Record") == "Write_/_Save_NSSOL_Projects_Record"

    def test_script_holds_no_process_names(self, project):
        js = (project / "src/main/resources/META-INF/resources/ui/app.js").read_text()
        for spec in _specs():
            assert spec["process"]["id"] not in js and spec["process"]["name"] not in js
