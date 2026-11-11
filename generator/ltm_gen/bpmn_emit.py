"""Deterministic spec -> BPMN 2.0 emitter for BAMOE 9.6 (Kogito) targets.

Conventions verified on 9.6.0 (see register-project/README.md):
- Java service tasks bind input "Parameter", output "Result"; implementation
  class must be a CDI bean.
- Gateway conditions: language="http://www.java.com/java", `return` statements.
- dataInput/dataOutput carry itemSubjectRef type bindings.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

NODE_SIZE = {
    "start": (36, 36),
    "end": (36, 36),
    "userTask": (180, 110),
    "serviceTask": (200, 100),
    "xor": (50, 50),
}
TASK_TAGS = {"userTask": "userTask", "serviceTask": "serviceTask"}
EVENT_TAGS = {"start": "startEvent", "end": "endEvent"}
GATEWAY_TAG = {"xor": "exclusiveGateway"}


def _tag(node_type: str) -> str:
    if node_type in TASK_TAGS:
        return TASK_TAGS[node_type]
    if node_type in EVENT_TAGS:
        return EVENT_TAGS[node_type]
    return GATEWAY_TAG[node_type]


def _item_id(var: str) -> str:
    return f"_{var}Item"


def emit_bpmn(spec: dict) -> str:
    p = spec["process"]
    nodes = {n["id"]: n for n in spec["nodes"]}
    var_types = {v["name"]: v["type"] for v in spec["variables"]}

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bpmn2:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"',
        '  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
        '  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"',
        '  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"',
        '  xmlns:drools="http://www.jboss.org/drools"',
        '  xmlns:java="http://www.java.com/javaTypes"',
        '  xmlns:tns="http://www.jboss.org/drools"',
        f'  id="_{p["id"]}" name={quoteattr(p["name"])}',
        '  targetNamespace="http://www.jboss.org/drools">',
        "",
        f"  <!-- Generated from spec evidence: {escape(p['evidence'])} -->",
        "",
    ]

    # item definitions + service interfaces/messages
    for v in spec["variables"]:
        parts.append(f'  <bpmn2:itemDefinition id="{_item_id(v["name"])}" '
                     f'structureRef="{v["type"]}"/>')
    for n in spec["nodes"]:
        if n["type"] == "serviceTask":
            svc = n["service"]
            parts += [
                f'  <bpmn2:message id="_{n["id"]}InMessage" itemRef="{_item_id(n["inputs"][0])}"/>',
                f'  <bpmn2:message id="_{n["id"]}OutMessage" itemRef="{_item_id(n["outputs"][0])}"/>',
                f'  <bpmn2:interface id="_{n["id"]}Interface" name="{svc["class"].split(".")[-1]}" '
                f'implementationRef="{svc["class"]}">',
                f'    <bpmn2:operation id="_{n["id"]}Operation" name="{svc["operation"]}" '
                f'implementationRef="{svc["operation"]}">',
                f'      <bpmn2:inMessageRef>_{n["id"]}InMessage</bpmn2:inMessageRef>',
                f'      <bpmn2:outMessageRef>_{n["id"]}OutMessage</bpmn2:outMessageRef>',
                '    </bpmn2:operation>',
                '  </bpmn2:interface>',
            ]
    parts.append("")

    # flows by target/source for wiring
    incoming = {}
    outgoing = {}
    for f in spec["flows"]:
        outgoing.setdefault(f["from"], []).append(f)
        incoming.setdefault(f["to"], []).append(f)

    parts.append(f'  <bpmn2:process id="{p["id"]}" tns:packageName="{p["packageName"]}" '
                 f'name={quoteattr(p["name"])} isExecutable="true" processType="Public">')
    if spec.get("assumptions"):
        doc = " / ".join(f'{a["id"]}: {a["text"]}' for a in spec["assumptions"])
        parts.append(f'    <bpmn2:documentation>Open items and assumptions — {escape(doc)}</bpmn2:documentation>')
    for v in spec["variables"]:
        parts.append(f'    <bpmn2:property id="{v["name"]}" itemSubjectRef="{_item_id(v["name"])}"/>')
    parts.append("")

    flow_ids = {}
    for i, f in enumerate(spec["flows"]):
        flow_ids[id(f)] = f"_sf_{f['from']}_{f['to']}"

    for n in spec["nodes"]:
        tag = _tag(n["type"])
        inc = "".join(f"\n      <bpmn2:incoming>{flow_ids[id(f)]}</bpmn2:incoming>"
                      for f in incoming.get(n["id"], []))
        out = "".join(f"\n      <bpmn2:outgoing>{flow_ids[id(f)]}</bpmn2:outgoing>"
                      for f in outgoing.get(n["id"], []))
        doc = f'\n      <bpmn2:documentation>{escape(n["doc"])}</bpmn2:documentation>' if n.get("doc") else ""

        if n["type"] in TASK_TAGS:
            svc_attr = ""
            if n["type"] == "serviceTask":
                svc_attr = (f' implementation="##Java" '
                            f'operationRef="_{n["id"]}Operation"')
            parts.append(f'    <bpmn2:{tag} id="{n["id"]}" name={quoteattr(n["name"])}{svc_attr}>{doc}{inc}{out}')
            parts.append('      <bpmn2:ioSpecification>')
            for i, var in enumerate(n.get("inputs", [])):
                pname = "Parameter" if n["type"] == "serviceTask" and i == 0 else var
                parts.append(f'        <bpmn2:dataInput id="_{n["id"]}_in_{i}" name="{pname}" '
                             f'itemSubjectRef="{_item_id(var)}"/>')
            for i, var in enumerate(n.get("outputs", [])):
                pname = "Result" if n["type"] == "serviceTask" else var
                parts.append(f'        <bpmn2:dataOutput id="_{n["id"]}_out_{i}" name="{pname}" '
                             f'itemSubjectRef="{_item_id(var)}"/>')
            parts.append('        <bpmn2:inputSet>')
            for i in range(len(n.get("inputs", []))):
                parts.append(f'          <bpmn2:dataInputRefs>_{n["id"]}_in_{i}</bpmn2:dataInputRefs>')
            parts.append('        </bpmn2:inputSet>')
            parts.append('        <bpmn2:outputSet>')
            for i in range(len(n.get("outputs", []))):
                parts.append(f'          <bpmn2:dataOutputRefs>_{n["id"]}_out_{i}</bpmn2:dataOutputRefs>')
            parts.append('        </bpmn2:outputSet>')
            parts.append('      </bpmn2:ioSpecification>')
            for i, var in enumerate(n.get("inputs", [])):
                parts.append('      <bpmn2:dataInputAssociation>')
                parts.append(f'        <bpmn2:sourceRef>{var}</bpmn2:sourceRef>')
                parts.append(f'        <bpmn2:targetRef>_{n["id"]}_in_{i}</bpmn2:targetRef>')
                parts.append('      </bpmn2:dataInputAssociation>')
            for i, var in enumerate(n.get("outputs", [])):
                parts.append('      <bpmn2:dataOutputAssociation>')
                parts.append(f'        <bpmn2:sourceRef>_{n["id"]}_out_{i}</bpmn2:sourceRef>')
                parts.append(f'        <bpmn2:targetRef>{var}</bpmn2:targetRef>')
                parts.append('      </bpmn2:dataOutputAssociation>')
            parts.append(f'    </bpmn2:{tag}>')
        elif n["type"] == "xor":
            parts.append(f'    <bpmn2:{tag} id="{n["id"]}" name={quoteattr(n["name"])} '
                         f'gatewayDirection="Diverging">{doc}{inc}{out}')
            parts.append(f'    </bpmn2:{tag}>')
        else:
            parts.append(f'    <bpmn2:{tag} id="{n["id"]}" name={quoteattr(n["name"])}>{doc}{inc}{out}')
            parts.append(f'    </bpmn2:{tag}>')
        parts.append("")

    for f in spec["flows"]:
        name_attr = f' name={quoteattr(f["name"])}' if f.get("name") else ""
        cond = ""
        if f.get("condition"):
            cond = (f'\n      <bpmn2:conditionExpression xsi:type="bpmn2:tFormalExpression" '
                    f'language="http://www.java.com/java">{escape(f["condition"])}'
                    f'</bpmn2:conditionExpression>')
        parts.append(f'    <bpmn2:sequenceFlow id="{flow_ids[id(f)]}" sourceRef="{f["from"]}" '
                     f'targetRef="{f["to"]}"{name_attr}>{cond}')
        parts.append('    </bpmn2:sequenceFlow>')

    parts.append('  </bpmn2:process>')
    parts.append("")
    parts.append(_emit_di(spec, flow_ids))
    parts.append('</bpmn2:definitions>')
    return "\n".join(parts)


def _emit_di(spec: dict, flow_ids: dict) -> str:
    """Naive left-to-right layout; editors can re-layout. Diverging targets
    after a gateway fan vertically by outgoing order."""
    pos = {}
    x = 60
    for i, n in enumerate(spec["nodes"]):
        w, h = NODE_SIZE[n["type"]]
        pos[n["id"]] = (x, 300 if n["type"] != "end" else 300 + (i % 2) * 160 - 80, w, h)
        x += 200
    out = ['  <bpmndi:BPMNDiagram>',
           f'    <bpmndi:BPMNPlane bpmnElement="{spec["process"]["id"]}">']
    for n in spec["nodes"]:
        x, y, w, h = pos[n["id"]]
        out.append(f'      <bpmndi:BPMNShape id="shape_{n["id"]}" bpmnElement="{n["id"]}">')
        out.append(f'        <dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}"/>')
        out.append('      </bpmndi:BPMNShape>')
    for f in spec["flows"]:
        sx, sy, sw, sh = pos[f["from"]]
        tx, ty, tw, th = pos[f["to"]]
        out.append(f'      <bpmndi:BPMNEdge id="edge_{flow_ids[id(f)]}" bpmnElement="{flow_ids[id(f)]}">')
        out.append(f'        <di:waypoint x="{sx + sw}" y="{sy + sh // 2}"/>')
        out.append(f'        <di:waypoint x="{tx}" y="{ty + th // 2}"/>')
        out.append('      </bpmndi:BPMNEdge>')
    out += ['    </bpmndi:BPMNPlane>', '  </bpmndi:BPMNDiagram>']
    return "\n".join(out)
