"""Assemble one generated BAMOE project for an application from its process specs.

Copies the pinned accelerator skeleton (pom.xml, application.properties) once
and emits every process's BPMN, the union of models and service test doubles,
one process test per process and the user webpage on top. The skeleton is
authoritative for build config; only generated artifacts come from the specs.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .bpmn_emit import emit_bpmn
from .java_emit import emit_audit_support, emit_pojo, emit_process_test, emit_store, test_class_name
from .web_emit import emit_web

SKELETON_FILES = ["pom.xml", "src/main/resources/application.properties"]
SKELETON_ARTIFACT = "your-bamoe-business-service"


class ApplicationError(ValueError):
    """The specs cannot be combined into one project. Lists every problem."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def artifact_id(name: str) -> str:
    """'NSSOL POC' -> 'nssol-poc'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ApplicationError([f"application name {name!r} gives no Maven artifactId"])
    return slug


def _application(specs: list[dict], problems: list[str]) -> dict | None:
    apps = {}
    for s in specs:
        app = s.get("application")
        if not isinstance(app, dict) or not app.get("name"):
            problems.append(f"process '{s['process']['id']}': the spec names no application "
                            "(application.name, from the application overview)")
            continue
        apps.setdefault(app["name"], []).append(s["process"]["id"])
    if len(apps) > 1:
        problems.append("the specs belong to different applications: " + "; ".join(
            f"{name} ({', '.join(ids)})" for name, ids in apps.items()))
    if len(apps) != 1:
        return None
    return next(s["application"] for s in specs if s.get("application"))


def _check_processes(specs: list[dict], problems: list[str]) -> str | None:
    ids: dict[str, str] = {}
    classes: dict[str, str] = {}
    packages: dict[str, list[str]] = {}
    for s in specs:
        p = s["process"]
        if p["id"] in ids:
            problems.append(f"process id '{p['id']}' is used by both '{ids[p['id']]}' and "
                            f"'{p['name']}'")
        ids.setdefault(p["id"], p["name"])
        cls = test_class_name(p["id"])
        if cls in classes and classes[cls] != p["id"]:
            problems.append(f"processes '{classes[cls]}' and '{p['id']}' both give test class {cls}")
        classes.setdefault(cls, p["id"])
        packages.setdefault(p["packageName"], []).append(p["id"])
    if len(packages) > 1:
        problems.append("all processes must share one packageName: " + "; ".join(
            f"{pkg} ({', '.join(pids)})" for pkg, pids in packages.items()))
    return next(iter(packages)) if len(packages) == 1 else None


def _fields(model: dict) -> list[tuple[str, str]]:
    return [(f["name"], f["type"]) for f in model["fields"]]


def merge_models(specs: list[dict], problems: list[str]) -> dict[str, dict]:
    """Union of the specs' models. A class defined in several specs must have the same
    fields with the same types in the same (document) order; its evidence lists every spec."""
    merged: dict[str, dict] = {}
    for s in specs:
        pid = s["process"]["id"]
        for name, m in s["models"].items():
            if name not in merged:
                merged[name] = {"fields": m["fields"], "evidence": [(m["evidence"], [pid])],
                                "first": pid}
                continue
            seen = merged[name]
            if _fields(m) != _fields(seen):
                a, b = dict(_fields(seen)), dict(_fields(m))
                if a == b:
                    why = "the same fields in a different order"
                else:
                    diff = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
                    why = "different fields or types (" + ", ".join(
                        f"{k}: {a.get(k, 'absent')} vs {b.get(k, 'absent')}" for k in diff) + ")"
                problems.append(
                    f"model {name} is defined differently by '{seen['first']}' "
                    f"({seen['evidence'][0][0]}) and '{pid}' ({m['evidence']}): {why}")
                continue
            for ev, users in seen["evidence"]:
                if ev == m["evidence"]:
                    users.append(pid)
                    break
            else:
                seen["evidence"].append((m["evidence"], [pid]))
    return {name: {"fields": m["fields"],
                   "evidence": "; ".join(f"{ev} (used by {', '.join(users)})"
                                         for ev, users in m["evidence"])}
            for name, m in merged.items()}


def _service_signature(spec: dict, node: dict) -> dict:
    """The test double a service task needs; it saves the type of the task's first input."""
    variables = {v["name"]: v for v in spec["variables"]}
    var = variables[node["inputs"][0]]
    is_list = var["type"] == "java.util.List"
    qualified = var["elementType"] if is_list else var["type"]
    scalar = ".model." not in qualified  # e.g. java.lang.Boolean: no generated model
    return {"class": node["service"]["class"].split(".")[-1],
            "operation": node["service"]["operation"],
            "model": qualified if scalar else qualified.split(".")[-1],
            "param": var["name"], "is_list": is_list, "scalar": scalar}


def merge_services(specs: list[dict], problems: list[str]) -> dict[str, dict]:
    services: dict[str, tuple[dict, str]] = {}
    for s in specs:
        for n in s["nodes"]:
            if n["type"] != "serviceTask":
                continue
            sig = _service_signature(s, n)
            where = f"{s['process']['id']}.{n['id']}"
            if sig["class"] in services:
                seen, seen_where = services[sig["class"]]
                if seen != sig:
                    diff = ", ".join(f"{k} {seen[k]!r} vs {sig[k]!r}"
                                     for k in sig if seen[k] != sig[k])
                    problems.append(f"service class {sig['class']} has different signatures in "
                                    f"{seen_where} and {where}: {diff}")
                continue
            services[sig["class"]] = (sig, where)
    return {cls: sig for cls, (sig, _) in services.items()}


def _pom(text: str, app: dict) -> str:
    artifact = artifact_id(app["name"])
    if f"<artifactId>{SKELETON_ARTIFACT}</artifactId>" not in text:
        raise ApplicationError([f"skeleton pom.xml has no <artifactId>{SKELETON_ARTIFACT}</artifactId>"])
    text = re.sub(r"\s*<!-- TODO: CHANGE THIS -->", "", text, count=2)
    return text.replace(f"<artifactId>{SKELETON_ARTIFACT}</artifactId>",
                        f"<artifactId>{artifact}</artifactId>\n  <name>{app['name']}</name>", 1)


def _readme(app: dict, specs: list[dict]) -> str:
    rows = "\n".join(f"| {s['process']['name']} | `{s['process']['id']}` | "
                     f"`src/main/resources/{s['process']['id']}.bpmn` | "
                     f"`{test_class_name(s['process']['id'])}` |" for s in specs)
    return f"""# {app['name']} (generated)

Generated by the LTM -> BAMOE builder from the application's process specs.
Application evidence: {app.get('evidence', 'not recorded')}. Do not edit by hand; regenerate.

| Process | Id | BPMN | Test |
|---|---|---|---|
{rows}

Services in `service/` are **test doubles**, not production persistence.

- Build and test: `mvn -Pdevelopment -Dquarkus.test.profile=dev clean package`
  (each test writes its step audit to `logs/<processId>-audit.json`)
- Run with the user webpage at http://localhost:8080/ui/ (dev profile, packaged app):
  `mvn -Pdevelopment -Dquarkus.profile=dev -DskipTests clean package`, then
  `java -Dquarkus.profile=dev -Dquarkus.http.host=127.0.0.1 -jar target/quarkus-app/quarkus-run.jar`.
  Not `quarkus:dev` when a process has list variables: in dev mode Kogito cannot
  deserialize the list elements (ClassNotFoundException for the model class).

The webpage is served only in the `%dev` profile, where authentication is off.
"""


def emit_application(specs: list[dict], skeleton_dir: Path, out_dir: Path) -> list[Path]:
    """Write one project holding every process of the application into a fresh out_dir.

    Raises ApplicationError listing every problem before anything is written."""
    specs = list(specs)
    problems: list[str] = []
    if not specs:
        raise ApplicationError(["no process specs given"])
    app = _application(specs, problems)
    pkg = _check_processes(specs, problems)
    models = merge_models(specs, problems)
    services = merge_services(specs, problems)
    if problems:
        raise ApplicationError(problems)

    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    written: list[Path] = []

    def write(rel: str | Path, text: str) -> None:
        f = out_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        written.append(f)

    skel = Path(skeleton_dir)
    write("pom.xml", _pom((skel / "pom.xml").read_text(encoding="utf-8"), app))
    props = (skel / SKELETON_FILES[1]).read_text(encoding="utf-8").rstrip("\n") + "\n"
    # List variables are Java-serialized with their items; under Quarkus' split test
    # classloader the item classes then cannot be resolved when an instance is reloaded.
    if any(v.get("elementType") for s in specs for v in s["variables"]):
        props += ("\n# Generated: process variables hold lists of model classes, which are "
                  "Java-serialized;\n# a flat test classpath lets deserialization find them.\n"
                  "quarkus.test.flat-class-path=true\n")
    props += ("\n# Generated: the user webpage (META-INF/resources/ui) calls the unauthenticated\n"
              "# %dev endpoints; it is denied outside %dev until it supports OIDC.\n"
              "%prod.quarkus.http.auth.permission.webpage.paths=/ui,/ui/*\n"
              "%prod.quarkus.http.auth.permission.webpage.policy=deny\n")
    write(SKELETON_FILES[1], props)
    write("README.md", _readme(app, specs))

    pkg_path = Path(*pkg.split("."))
    java_root = Path("src/main/java") / pkg_path
    test_root = Path("src/test/java") / pkg_path
    res_root = Path("src/main/resources")

    for s in specs:
        write(res_root / f"{s['process']['id']}.bpmn", emit_bpmn(s))
    for name, m in models.items():
        write(java_root / "model" / f"{name}.java", emit_pojo(pkg, name, m["fields"], m["evidence"]))
    for cls, sig in services.items():
        write(java_root / "service" / f"{cls}.java",
              emit_store(pkg, cls, sig["model"], sig["operation"],
                         "Write semantics unspecified; records calls for tests.",
                         param=sig["param"], is_list=sig["is_list"], scalar=sig["scalar"]))
    for rel, text in emit_audit_support(pkg).items():
        write(test_root / rel, text)
    for s in specs:
        write(test_root / f"{test_class_name(s['process']['id'])}.java", emit_process_test(s))
    for rel, text in emit_web(app, specs, models).items():
        write(res_root / "META-INF/resources/ui" / rel, text)
    return written
