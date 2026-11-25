"""Demo runner: LTM documents -> one BAMOE application project -> one Maven run.

    python tools/run_ltm_demo.py --docs DIR --out DIR [--out-of-scope D04,D07]
        [--skip-maven] [--mvn mvn]

Every supplement in extractor/supplements/ is extracted against the documents,
the specs are generated into one project (projects/<artifactId>/), Maven is run
once and the results are written to manifest.json: one application-level
build/test result and one entry per process with its spec, BPMN, test results,
audit report and extractor diagnostics. The source DOCX files are hashed
before and after; any change fails the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("reader", "extractor", "generator"):
    sys.path.insert(0, str(ROOT / pkg))

from ltm_extract import DocSet, ExtractionError, build_spec, load_supplement  # noqa: E402
from ltm_gen import ApplicationError, emit_application  # noqa: E402
from ltm_gen.java_emit import test_class_name  # noqa: E402
from ltm_gen.project_emit import artifact_id  # noqa: E402

MAVEN_ARGS = ["-Pdevelopment", "-Dquarkus.test.profile=dev", "clean", "package"]
SKELETON = ROOT / "register-project"
SUPPLEMENTS = ROOT / "extractor" / "supplements"


class UsageError(Exception):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_ltm_demo", description=__doc__.splitlines()[0])
    parser.add_argument("--docs", required=True, type=Path, help="folder holding the NN_*.docx originals")
    parser.add_argument("--out", required=True, type=Path, help="new or empty output folder")
    parser.add_argument("--supplements", type=Path, default=SUPPLEMENTS,
                        help="folder of analyst supplements, one per process")
    parser.add_argument("--skeleton", type=Path, default=SKELETON, help="BAMOE build skeleton")
    parser.add_argument("--mvn", default="mvn", help="Maven executable")
    parser.add_argument("--skip-maven", action="store_true", help="generate only; build not run")
    parser.add_argument("--out-of-scope", default="", metavar="D04,D07",
                        help="documents this run does not need; if one is not supplied, "
                             "citations into it are reported instead of checked")
    args = parser.parse_args(argv)
    problems = []
    args.out_of_scope = [d.strip() for d in args.out_of_scope.split(",") if d.strip()]
    bad = [d for d in args.out_of_scope if not re.fullmatch(r"D\d\d", d)]
    if bad:
        problems.append(f"--out-of-scope {', '.join(bad)}: name documents as D01, D02, ...")
    if not args.docs.is_dir():
        problems.append(f"--docs {args.docs} is not a folder")
    elif not source_files(args.docs):
        problems.append(f"--docs {args.docs} holds no NN_*.docx documents")
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        problems.append(f"--out {args.out} exists and is not empty; the runner only writes a fresh folder")
    if not args.supplements.is_dir() or not sorted(args.supplements.glob("*.json")):
        problems.append(f"--supplements {args.supplements} holds no supplement JSON")
    if not (args.skeleton / "pom.xml").is_file():
        problems.append(f"--skeleton {args.skeleton} has no pom.xml")
    if not args.skip_maven and shutil.which(args.mvn) is None:
        problems.append(f"Maven executable {args.mvn!r} not found (use --skip-maven to generate only)")
    if problems:
        raise UsageError("; ".join(problems))
    return args


def source_files(docs: Path) -> list[Path]:
    return sorted(p for p in docs.glob("*.docx") if p.name[:2].isdigit() and p.name[2] == "_")


def sha256(docs: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files(docs)}


def surefire_results(reports: Path) -> dict[str, dict]:
    """Per test class: counts and the failing test names with their messages."""
    results = {}
    for xml in sorted(reports.glob("TEST-*.xml")):
        suite = ET.parse(xml).getroot()
        name = suite.get("name", "").split(".")[-1]
        failed = []
        for case in suite.iter("testcase"):
            for kind in ("failure", "error"):
                for f in case.iter(kind):
                    failed.append({"test": case.get("name"), "kind": kind,
                                   "message": (f.get("message") or "").strip()})
        results[name] = {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
        results[name]["failed"] = failed
    return results


def _total(results: dict[str, dict]) -> dict:
    return {k: sum(r[k] for r in results.values()) for k in ("tests", "failures", "errors", "skipped")}


def build_manifest(*, specs: list[dict], supplements: list[Path], diagnostics: list[list],
                   project: Path, out: Path, build: dict, results: dict[str, dict],
                   before: dict[str, str], after: dict[str, str],
                   out_of_scope: list[str] = ()) -> dict:
    app = specs[0]["application"]
    processes = []
    for spec, supplement, diags in zip(specs, supplements, diagnostics):
        pid = spec["process"]["id"]
        cls = test_class_name(pid)
        audit = project / "logs" / f"{pid}-audit.json"
        processes.append({
            "id": pid, "name": spec["process"]["name"], "evidence": spec["process"]["evidence"],
            "supplement": str(supplement.relative_to(ROOT) if supplement.is_relative_to(ROOT) else supplement),
            "spec": f"specs/{supplement.stem}.json",
            "bpmn": str((project / "src/main/resources" / f"{pid}.bpmn").relative_to(out)),
            "testClass": cls,
            "scenarios": [t["name"] for t in spec["tests"]],
            "tests": results.get(cls, {"status": build["status"]}),
            "audit": str(audit.relative_to(out)) if audit.is_file() else None,
            "openAssumptions": len(spec.get("assumptions", [])),
            "diagnostics": [{"code": d.code, "message": d.message} for d in diags],
        })
    expected = sum(len(s["tests"]) for s in specs)
    tests = _total(results) if results else None
    return {
        "application": {
            "name": app["name"], "evidence": app.get("evidence", ""),
            "artifactId": artifact_id(app["name"]),
            "project": str(project.relative_to(out)),
            "build": dict(build, tests=tests, expectedTests=expected),
        },
        "processes": processes,
        "sources": [{"file": f, "sha256": h} for f, h in before.items()],
        "outOfScope": list(out_of_scope),
        "sourcesUnchanged": before == after,
    }


def run(args: argparse.Namespace) -> int:
    out: Path = args.out
    before = sha256(args.docs)
    docset = DocSet.load(args.docs)
    supplements = sorted(args.supplements.glob("*.json"))
    specs, diagnostics, problems = [], [], []
    for sup in supplements:
        try:
            result = build_spec(docset, load_supplement(sup), args.out_of_scope)
        except ExtractionError as e:
            problems += [f"{sup.name}: {p}" for p in e.problems]
            continue
        specs.append(result.spec)
        diagnostics.append(result.diagnostics)
        for d in result.diagnostics:
            print(f"{sup.stem} [{d.code}] {d.message}", file=sys.stderr)
    if problems:
        print("No project written; the extractor refused:", *problems, sep="\n  - ", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    (out / "specs").mkdir()
    for sup, spec in zip(supplements, specs):
        (out / "specs" / f"{sup.stem}.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        name = artifact_id(specs[0].get("application", {}).get("name", ""))
        project = out / "projects" / name
        emit_application(specs, args.skeleton, project)
    except ApplicationError as e:
        print("No project written; the specs do not form one application:", *e.problems,
              sep="\n  - ", file=sys.stderr)
        return 1

    command = [args.mvn, *MAVEN_ARGS]
    build = {"command": " ".join(command), "log": None}
    results = {}
    if args.skip_maven:
        build["status"] = "not-run"
    else:
        (out / "logs").mkdir()
        log = out / "logs" / "maven.log"
        with log.open("w", encoding="utf-8") as f:
            code = subprocess.run(command, cwd=project, stdout=f, stderr=subprocess.STDOUT).returncode
        build.update(status="pass" if code == 0 else "fail", exitCode=code, log=str(log.relative_to(out)))
        results = surefire_results(project / "target" / "surefire-reports")

    manifest = build_manifest(specs=specs, supplements=supplements, diagnostics=diagnostics,
                              project=project, out=out, build=build, results=results,
                              before=before, after=sha256(args.docs),
                              out_of_scope=args.out_of_scope)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    tests = manifest["application"]["build"]["tests"]
    print(f"{manifest['application']['name']}: {len(specs)} processes in {project}; build {build['status']}"
          + (f", {tests['tests']} tests, {tests['failures'] + tests['errors']} failed" if tests else ""))
    if not manifest["sourcesUnchanged"]:
        print("Source documents changed during the run", file=sys.stderr)
        return 1
    return 0 if build["status"] in ("pass", "not-run") else 1


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except UsageError as e:
        print(f"run_ltm_demo: {e}", file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
