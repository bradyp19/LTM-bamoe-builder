"""Java emitters: POJO model, service test-double, process test class."""

from __future__ import annotations

import json


def _getter_name(field: str, jtype: str) -> str:
    cap = field[0].upper() + field[1:]
    return f"is{cap}" if field.startswith("is") else f"get{cap}"


def _setter_name(field: str) -> str:
    return f"set{field[0].upper() + field[1:]}"


def emit_pojo(package: str, class_name: str, fields: list[dict], evidence: str) -> str:
    lines = [
        f"package {package}.model;",
        "",
        f"// Generated. Evidence: {evidence}",
        # Items of list variables are Java-serialized when a process instance is marshalled
        f"public class {class_name} implements java.io.Serializable {{",
        "",
        "    private static final long serialVersionUID = 1L;",
        "",
    ]
    for f in fields:
        lines.append(f"    private {f['type']} {f['name']};")
    lines.append("")
    for f in fields:
        lines.append(f"    public {f['type']} {_getter_name(f['name'], f['type'])}() "
                     f"{{ return {f['name']}; }}")
        lines.append(f"    public void {_setter_name(f['name'])}({f['type']} {f['name']}) "
                     f"{{ this.{f['name']} = {f['name']}; }}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def emit_store(package: str, class_name: str, model_class: str, operation: str,
               assumption: str, param: str | None = None, is_list: bool = False) -> str:
    """Test-double service. `param` names the saved argument (default: the
    model class in lowerCamel); `is_list` makes it a List of the model."""
    param = param or model_class[0].lower() + model_class[1:]
    payload = f"List<{model_class}>" if is_list else model_class
    field = "records" if is_list else "registration"
    return f'''package {package}.service;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import jakarta.enterprise.context.ApplicationScoped;
import {package}.model.{model_class};

/**
 * TEST DOUBLE — generated. {assumption}
 */
@ApplicationScoped
public class {class_name} {{

    public record SaveCall({payload} {field}) {{}}

    private static final List<SaveCall> SAVES = new CopyOnWriteArrayList<>();

    public {payload} {operation}({payload} {param}) {{
        SAVES.add(new SaveCall({param}));
        return {param};
    }}

    public static List<SaveCall> saves() {{
        return List.copyOf(SAVES);
    }}

    public static void clear() {{
        SAVES.clear();
    }}
}}
'''


def _literal(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def _pojo_init(model: str, values: dict, var: str) -> list[str]:
    lines = [f"        {model} {var} = new {model}();"]
    for k, v in values.items():
        lit = _literal(v)
        lines.append(f"        {var}.set{k[0].upper() + k[1:]}({lit});")
    return lines


MAP_OF_MAX_PAIRS = 10


def _simple(type_name: str) -> str:
    return type_name.split(".")[-1]


def _java_value(name: str, value, var: dict, setup: list[str], models: set[str]) -> str:
    """Java expression for a process-variable value; POJO setup lines go to `setup`.
    Record variables take a dict of fields, record-list variables a list of dicts."""
    if var["type"] == "java.util.List" and isinstance(value, list):
        element = _simple(var["elementType"])
        names = []
        for i, item in enumerate(value):
            models.add(element)
            names.append(f"{name}{i}")
            setup += _pojo_init(element, item, f"{name}{i}")
        return f"new ArrayList<>(List.of({', '.join(names)}))"
    if ".model." in var["type"] and isinstance(value, dict):
        models.add(_simple(var["type"]))
        setup += _pojo_init(_simple(var["type"]), value, name)
        return name
    return _literal(value)


def _java_map(values: dict, variables: dict, setup: list[str], models: set[str], where: str,
              scope: str) -> str:
    if len(values) > MAP_OF_MAX_PAIRS:
        raise ValueError(f"{where}: Map.of takes at most {MAP_OF_MAX_PAIRS} entries, got {len(values)}")
    unknown = sorted(set(values) - set(variables))
    if unknown:
        raise ValueError(f"{where}: not process variables: {', '.join(unknown)}")
    return "Map.of(" + ", ".join(
        f'"{k}", {_java_value(f"{scope}_{k}", v, variables[k], setup, models)}'
        for k, v in values.items()) + ")"


def _scenario_test(t: dict, variables: dict, task_names: dict, stores: dict,
                   models: set[str]) -> str:
    """A scenario with `steps`: start values, then each user task completed in order.
    expect.saves maps store class -> number of save calls; expect.savedLists maps
    store class -> size of the list saved by its first call."""
    setup, lines = [], []
    start = _java_map(t.get("start", {}), variables, setup, models, f"test {t['name']} start", "start")
    lines.append("        var model = process.createModel();")
    if t.get("start"):
        lines += setup
        lines.append(f"        model.update({start});")
    lines += ["        var instance = process.createInstance(model);",
              "        instance.start();"]
    for i, step in enumerate(t["steps"], 1):
        if step["task"] not in task_names:
            raise ValueError(f"test {t['name']}: no user task '{step['task']}'")
        setup = []
        done = _java_map(step.get("complete", {}), variables, setup, models,
                         f"test {t['name']} step {i}", f"step{i}")
        lines += [
            "        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);",
            f"        var items{i} = instance.workItems(USER);",
            f"        assertThat(items{i}).hasSize(1);",
            f'        assertThat(items{i}.get(0).getName()).isEqualTo("{task_names[step["task"]]}");',
            *setup,
            f"        instance.completeWorkItem(items{i}.get(0).getId(), {done}, USER);",
        ]
    expect = t["expect"]
    lines.append(f"        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_{expect['status']});")
    for store in stores:
        lines.append(f"        assertThat({store}.saves()).hasSize({expect.get('saves', {}).get(store, 0)});")
    for store, size in expect.get("savedLists", {}).items():
        lines.append(f"        assertThat({store}.saves().get(0).records()).hasSize({size});")
    return f"""
    @Test
    void {t["name"]}() {{
{chr(10).join(lines)}
    }}"""


def _imports(pkg: str, models: set[str], stores: dict, tests: list[str]) -> dict:
    java = "import java.util.Map;"
    if any("List.of(" in t for t in tests):
        java = "import java.util.ArrayList;\nimport java.util.List;\n" + java
    project = "\n".join([f"import {pkg}.model.{m};" for m in sorted(models)]
                        + [f"import {pkg}.service.{c};" for c in stores])
    return {"java": java, "project": project}


def emit_process_test(spec: dict) -> str:
    p = spec["process"]
    pkg = p["packageName"]
    variables = {v["name"]: v for v in spec["variables"]}
    stores = {n["service"]["class"].split(".")[-1]: n for n in spec["nodes"]
              if n["type"] == "serviceTask"}
    task_names = {n["id"]: n["name"] for n in spec["nodes"] if n["type"] == "userTask"}
    scenario_models: set[str] = set()
    groups = sorted({g for n in spec["nodes"] for g in n.get("candidateGroups", [])})
    identity = ('new StaticIdentityProvider("tester", java.util.List.of('
                + ", ".join(f'"{g}"' for g in groups) + "))") if groups else 'new StaticIdentityProvider("tester")'

    # Single-task scenarios (no `steps`): one record variable, one store, one form.
    legacy = [t for t in spec["tests"] if "steps" not in t]
    if legacy:
        model_var, model_type = next(
            (v["name"], v["type"].split(".")[-1])
            for v in spec["variables"] if ".model." in v["type"])
        store = next(iter(stores))
        form_node = next(n for n in spec["nodes"] if n["type"] == "userTask")
        scenario_models.add(model_type)

    tests = []
    for t in spec["tests"]:
        if "steps" in t:
            tests.append(_scenario_test(t, variables, task_names, stores, scenario_models))
            continue
        init = [f'        var model = process.createModel();']
        init += _pojo_init(model_type, t["start"][model_var], "p")
        start_vars = {k: v for k, v in t["start"].items() if k != model_var}
        map_entries = ", ".join(f'"{k}", {_literal(v)}' for k, v in start_vars.items())
        if map_entries:
            map_entries += ", "
        map_entries += f'"{model_var}", p'
        init.append(f'        model.update(Map.of({map_entries}));')
        init.append(f'        var instance = process.createInstance(model);')
        init.append('        instance.start();')
        complete_vars = dict(t["complete"])
        complete_vars[model_var] = "p"
        cmap = ", ".join(
            f'"{k}", {v if isinstance(v, str) and v == "p" else _literal(v)}'
            for k, v in complete_vars.items())
        saved_asserts = "".join(
            f'\n        assertThat({store}.saves().get(0).registration()'
            f'.{_getter_name(fname, "")}()).isEqualTo({expected});'
            for fname, expected in t["expect"].get("savedFields", {}).items())
        body = f'''
    @Test
    void {t["name"]}() {{
{chr(10).join(init)}
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);
        var items = instance.workItems(USER);
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getName()).isEqualTo("{form_node["name"]}");
        instance.completeWorkItem(items.get(0).getId(), Map.of({cmap}), USER);
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_{t["expect"]["status"]});
        assertThat({store}.saves()).hasSize({t["expect"]["saves"]});{saved_asserts}
    }}'''
        tests.append(body)

    imports = _imports(pkg, scenario_models, stores, tests)
    clears = "\n".join(f"        {c}.clear();" for c in stores)

    return f'''package {pkg};

import static org.assertj.core.api.Assertions.assertThat;

{imports["java"]}

import jakarta.inject.Inject;
import jakarta.inject.Named;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.kie.kogito.Model;
import org.kie.kogito.auth.SecurityPolicy;
import org.kie.kogito.process.Process;
import org.kie.kogito.process.ProcessInstance;
import org.kie.kogito.services.identity.StaticIdentityProvider;

import io.quarkus.test.junit.QuarkusTest;
{imports["project"]}

// Generated process test. Scenarios from spec evidence: {p["evidence"]}
@QuarkusTest
class {p["id"][0].upper() + p["id"][1:]}ProcessTest {{

    private static final SecurityPolicy USER =
            SecurityPolicy.of({identity});

    @Inject
    @Named("{p["id"]}")
    Process<? extends Model> process;

    @BeforeEach
    void clearStore() {{
{clears}
    }}
{"".join(tests)}
}}
'''
