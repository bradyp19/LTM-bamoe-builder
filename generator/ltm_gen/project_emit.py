"""Assemble a generated BAMOE project from a spec + skeleton template.

Copies the pinned accelerator skeleton (pom.xml, application.properties,
README) and emits generated sources on top. The skeleton is authoritative
for build config; only generated artifacts come from the spec.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .bpmn_emit import emit_bpmn
from .java_emit import emit_pojo, emit_process_test, emit_store


def emit_project(spec: dict, skeleton_dir: Path, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    written = []

    # skeleton: build config only
    skel = Path(skeleton_dir)
    for rel in ["pom.xml", "src/main/resources/application.properties", "README.md"]:
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skel / rel, dst)
        written.append(dst)

    pkg = spec["process"]["packageName"]
    java_root = out_dir / "src/main/java" / Path(*pkg.split("."))
    test_root = out_dir / "src/test/java" / Path(*pkg.split("."))
    res_root = out_dir / "src/main/resources"

    # List variables are Java-serialized with their items; under Quarkus' split test
    # classloader the item classes then cannot be resolved when an instance is reloaded.
    if any(v.get("elementType") for v in spec["variables"]):
        props = out_dir / "src/main/resources/application.properties"
        props.write_text(props.read_text().rstrip("\n") + "\n\n"
                         "# Generated: process variables hold lists of model classes, which are Java-serialized;\n"
                         "# a flat test classpath lets deserialization find them.\n"
                         "quarkus.test.flat-class-path=true\n")

    # BPMN
    bpmn_file = res_root / f"{spec['process']['id']}.bpmn"
    bpmn_file.write_text(emit_bpmn(spec))
    written.append(bpmn_file)

    # POJOs
    for name, m in spec["models"].items():
        f = java_root / "model" / f"{name}.java"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(emit_pojo(pkg, name, m["fields"], m["evidence"]))
        written.append(f)

    # service stubs (test doubles) for service tasks; each saves the type of
    # the task's first input variable
    variables = {v["name"]: v for v in spec["variables"]}
    for n in spec["nodes"]:
        if n["type"] == "serviceTask":
            svc = n["service"]
            cls = svc["class"].split(".")[-1]
            var = variables[n["inputs"][0]]
            is_list = var["type"] == "java.util.List"
            model = (var["elementType"] if is_list else var["type"]).split(".")[-1]
            f = java_root / "service" / f"{cls}.java"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(emit_store(pkg, cls, model, svc["operation"],
                                    "Write semantics unspecified; records calls for tests.",
                                    param=var["name"], is_list=is_list))
            written.append(f)

    # process test
    t = test_root / f"{spec['process']['id'][0].upper() + spec['process']['id'][1:]}ProcessTest.java"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(emit_process_test(spec))
    written.append(t)

    return written
