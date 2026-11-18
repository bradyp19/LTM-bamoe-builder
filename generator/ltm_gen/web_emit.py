"""The user webpage: static HTML/JS served by the generated service itself.

The page is fixed code (templates/web); everything process-specific is in
application.json, written here from the specs: one start form per process,
one form per user task (its inputs shown, its outputs editable) and the spec's
test scenarios as optional prefills. Endpoints are the generated Kogito REST
resources (/<processId>, /<processId>/<id>/tasks, /<processId>/<id>/<Task_Name>/<taskId>)
and the data-audit GraphQL endpoint (/data-audit/q), as served by BAMOE 9.6.
"""

from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).parent / "templates" / "web"
STATIC = ["index.html", "app.js", "app.css"]


def task_path(name: str) -> str:
    """REST path segment Kogito generates for a task: spaces become underscores."""
    return name.replace(" ", "_")


def _variable(v: dict) -> dict:
    out = {"name": v["name"], "type": v["type"], "evidence": v.get("evidence", "")}
    if v["type"] == "java.util.List":
        out.update(kind="list", model=v["elementType"].split(".")[-1])
    elif ".model." in v["type"]:
        out.update(kind="model", model=v["type"].split(".")[-1])
    else:
        out["kind"] = "scalar"
    return out


def start_variables(spec: dict) -> tuple[list[str], str]:
    """The process's start contract: declared in the spec, else the variables its
    test scenarios start with."""
    declared = spec["process"].get("startVariables")
    if declared is not None:
        return list(declared), "declared in the spec"
    used = {k for t in spec["tests"] for k in t.get("start", {})}
    return [v["name"] for v in spec["variables"] if v["name"] in used], \
        "set by the spec's test scenarios"


def _scenario(t: dict, form_id: str | None) -> dict:
    if "steps" in t:
        steps = t["steps"]
    else:  # single-task scenario: the start record is sent back with the flags
        model_var = next((k for k, v in t["start"].items() if isinstance(v, dict)), None)
        complete = dict(t.get("complete", {}))
        if model_var:
            complete[model_var] = t["start"][model_var]
        steps = [{"task": form_id, "complete": complete}]
    return {"name": t["name"], "start": t.get("start", {}), "steps": steps, "expect": t["expect"]}


def application_config(app: dict, specs: list[dict], models: dict[str, dict]) -> dict:
    processes = []
    for s in specs:
        p = s["process"]
        tasks = [n for n in s["nodes"] if n["type"] == "userTask"]
        start, source = start_variables(s)
        processes.append({
            "id": p["id"], "name": p["name"], "evidence": p["evidence"], "endpoint": f"/{p['id']}",
            "startNode": next(n["name"] for n in s["nodes"] if n["type"] == "start"),
            "startVariables": start, "startSource": source,
            "variables": [_variable(v) for v in s["variables"]],
            "userTasks": [{"id": n["id"], "name": n["name"], "path": task_path(n["name"]),
                           "inputs": n.get("inputs", []), "outputs": n.get("outputs", []),
                           "groups": n.get("candidateGroups", []), "doc": n.get("doc", "")}
                          for n in tasks],
            "scenarios": [_scenario(t, tasks[0]["id"] if tasks else None) for t in s["tests"]],
        })
    groups = sorted({g for s in specs for n in s["nodes"] for g in n.get("candidateGroups", [])})
    return {
        "application": {"name": app["name"], "evidence": app.get("evidence", "")},
        "user": "tester", "groups": groups,
        "models": {name: [{"name": f["name"], "type": f["type"]} for f in m["fields"]]
                   for name, m in models.items()},
        "processes": processes,
    }


def emit_web(app: dict, specs: list[dict], models: dict[str, dict]) -> dict[str, str]:
    """Files of the webpage, relative to META-INF/resources/ui/."""
    files = {name: (WEB / name).read_text(encoding="utf-8") for name in STATIC}
    files["application.json"] = json.dumps(application_config(app, specs, models),
                                           indent=2, ensure_ascii=False) + "\n"
    return files
