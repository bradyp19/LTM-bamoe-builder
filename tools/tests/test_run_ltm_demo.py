import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_ltm_demo as runner  # noqa: E402
from ltm_extract import Diagnostic  # noqa: E402
from ltm_gen import emit_application  # noqa: E402

ROOT = Path(__file__).parents[2]
NAMES = ["allocations", "register_project", "update_language_toggle"]


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "01_Overview.docx").write_bytes(b"one")
    (d / "02_Rules.docx").write_bytes(b"two")
    (d / "notes.docx").write_bytes(b"not a source")
    return d


def _args(docs, out, *extra):
    return ["--docs", str(docs), "--out", str(out), "--skip-maven", *extra]


class TestArguments:
    def test_valid(self, docs, tmp_path):
        args = runner.parse_args(_args(docs, tmp_path / "out"))
        assert args.skip_maven and args.supplements == runner.SUPPLEMENTS

    def test_out_must_be_fresh(self, docs, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "old.txt").write_text("hand edited")
        with pytest.raises(runner.UsageError, match="not empty"):
            runner.parse_args(_args(docs, out))

    def test_empty_out_is_accepted(self, docs, tmp_path):
        (tmp_path / "out").mkdir()
        runner.parse_args(_args(docs, tmp_path / "out"))

    def test_docs_must_hold_sources(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(runner.UsageError, match="no NN_\\*.docx"):
            runner.parse_args(_args(tmp_path / "empty", tmp_path / "out"))

    def test_every_problem_reported(self, tmp_path):
        with pytest.raises(runner.UsageError) as e:
            runner.parse_args(["--docs", str(tmp_path / "nope"), "--out", str(tmp_path / "o"),
                               "--supplements", str(tmp_path), "--mvn", "no-such-mvn"])
        assert all(s in str(e.value) for s in ("not a folder", "no supplement JSON", "not found"))

    def test_main_returns_usage_code(self, tmp_path, capsys):
        assert runner.main(["--docs", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 2
        assert "run_ltm_demo:" in capsys.readouterr().err


def test_sources_are_hashed_by_name(docs):
    hashes = runner.sha256(docs)
    assert list(hashes) == ["01_Overview.docx", "02_Rules.docx"]
    assert all(len(h) == 64 for h in hashes.values())


SUREFIRE = """<?xml version="1.0"?>
<testsuite name="nssol.{cls}" tests="{n}" failures="{f}" errors="0" skipped="0">
  <testcase name="a"/>{fail}
</testsuite>"""


class TestManifest:
    @pytest.fixture
    def setup(self, tmp_path):
        specs = [json.loads((ROOT / "generator/specs" / f"{n}.json").read_text()) for n in NAMES]
        for s in specs:
            s.setdefault("application", {"name": "NSSOL POC", "evidence": "D01 ¶1"})
        out = tmp_path / "out"
        project = out / "projects" / "nssol-poc"
        emit_application(specs, ROOT / "register-project", project)
        reports = project / "target" / "surefire-reports"
        reports.mkdir(parents=True)
        for cls, n, f in [("AllocationsProcessTest", 3, 0), ("RegisterProjectProcessTest", 3, 1),
                          ("UpdateLanguageToggleProcessTest", 2, 0)]:
            fail = '<testcase name="b"><failure message="step broke"/></testcase>' if f else ""
            (reports / f"TEST-nssol.{cls}.xml").write_text(SUREFIRE.format(cls=cls, n=n, f=f, fail=fail))
        (project / "logs").mkdir()
        (project / "logs" / "allocations-audit.json").write_text("{}")
        sups = [ROOT / "extractor/supplements" / f"{n}.json" for n in NAMES]
        return specs, sups, project, out, runner.surefire_results(reports)

    def test_application_entry_and_one_entry_per_process(self, setup):
        specs, sups, project, out, results = setup
        diags = [[Diagnostic("D1", "note")], [], []]
        m = runner.build_manifest(specs=specs, supplements=sups, diagnostics=diags, project=project,
                                  out=out, build={"status": "fail", "command": "mvn"}, results=results,
                                  before={"01_A.docx": "x"}, after={"01_A.docx": "x"})
        app = m["application"]
        assert app["artifactId"] == "nssol-poc" and app["project"] == "projects/nssol-poc"
        assert app["build"]["tests"] == {"tests": 8, "failures": 1, "errors": 0, "skipped": 0}
        assert app["build"]["expectedTests"] == 8
        assert [p["id"] for p in m["processes"]] == ["allocations", "registerProject", "updateLanguageToggle"]
        alloc, reg, _ = m["processes"]
        assert alloc["bpmn"] == "projects/nssol-poc/src/main/resources/allocations.bpmn"
        assert alloc["audit"] == "projects/nssol-poc/logs/allocations-audit.json"
        assert alloc["diagnostics"] == [{"code": "D1", "message": "note"}]
        assert alloc["supplement"] == "extractor/supplements/allocations.json"
        assert reg["tests"]["failed"] == [{"test": "b", "kind": "failure", "message": "step broke"}]
        assert reg["audit"] is None
        assert m["sourcesUnchanged"] is True

    def test_changed_source_is_visible(self, setup):
        specs, sups, project, out, _ = setup
        m = runner.build_manifest(specs=specs, supplements=sups, diagnostics=[[], [], []],
                                  project=project, out=out, build={"status": "not-run", "command": "mvn"},
                                  results={}, before={"01_A.docx": "x"}, after={"01_A.docx": "y"})
        assert m["sourcesUnchanged"] is False
        assert m["application"]["build"]["tests"] is None
        assert m["processes"][0]["tests"] == {"status": "not-run"}
