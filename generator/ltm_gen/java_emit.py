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
        f"public class {class_name} {{",
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


def emit_process_test(spec: dict) -> str:
    p = spec["process"]
    pkg = p["packageName"]
    model_var, model_type = next(
        (v["name"], v["type"].split(".")[-1])
        for v in spec["variables"] if ".model." in v["type"])
    svc_node = next(n for n in spec["nodes"] if n["type"] == "serviceTask")
    store = svc_node["service"]["class"].split(".")[-1]
    form_node = next(n for n in spec["nodes"] if n["type"] == "userTask")

    tests = []
    for t in spec["tests"]:
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

    return f'''package {pkg};

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;

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
import {pkg}.model.{model_type};
import {pkg}.service.{store};

// Generated process test. Scenarios from spec evidence: {p["evidence"]}
@QuarkusTest
class {p["id"][0].upper() + p["id"][1:]}ProcessTest {{

    private static final SecurityPolicy USER =
            SecurityPolicy.of(new StaticIdentityProvider("tester"));

    @Inject
    @Named("{p["id"]}")
    Process<? extends Model> process;

    @BeforeEach
    void clearStore() {{
        {store}.clear();
    }}
{"".join(tests)}
}}
'''
