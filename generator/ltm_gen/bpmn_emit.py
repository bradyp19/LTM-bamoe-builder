"""Deterministic spec -> BPMN 2.0 emitter for BAMOE 9.6 (Kogito) targets.

Conventions verified on 9.6.0 (see register-project/README.md):
- Java service tasks bind input "Parameter", output "Result"; implementation
  class must be a CDI bean.
- Gateway conditions: language="http://www.java.com/java", `return` statements.
- dataInput/dataOutput carry itemSubjectRef type bindings.
"""

from __future__ import annotations

from collections import deque
from xml.sax.saxutils import escape, quoteattr

NODE_SIZE = {
    "start": (36, 36),
    "end": (36, 36),
    "userTask": (160, 80),
    "serviceTask": (160, 80),
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


# Node documentation is persisted in a VARCHAR(255) column (definitions_nodes_metadata).
NODE_DOC_LIMIT = 255
OVERFLOW_MARK = " … (full text in process documentation)"


def _node_doc(node_id: str, doc: str, overflow: list[str]) -> str:
    """The node's documentation, cut to the column limit; the full text then goes to
    `overflow` for the process-level documentation so nothing is lost."""
    if len(doc) <= NODE_DOC_LIMIT:
        return doc
    overflow.append(f"[{node_id}] {doc}")
    return doc[:NODE_DOC_LIMIT - len(OVERFLOW_MARK)].rstrip() + OVERFLOW_MARK


def _item_id(var: str) -> str:
    return f"_{var}Item"


def _raw_item_id(var: str) -> str:
    """Item definition without generics, for Java method arguments (service tasks)."""
    return f"_{var}RawItem"


def _method_item(var: str, var_types: dict) -> str:
    return _raw_item_id(var) if var_types[var].get("elementType") else _item_id(var)


def emit_bpmn(spec: dict) -> str:
    p = spec["process"]
    nodes = {n["id"]: n for n in spec["nodes"]}
    var_types = {v["name"]: v for v in spec["variables"]}

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
        # Kogito reads a collection's element type from the generic in structureRef
        ref = f'{v["type"]}<{v["elementType"]}>' if v.get("elementType") else v["type"]
        parts.append(f'  <bpmn2:itemDefinition id="{_item_id(v["name"])}" '
                     f'structureRef={quoteattr(ref)}/>')
        if v.get("elementType"):
            parts.append(f'  <bpmn2:itemDefinition id="{_raw_item_id(v["name"])}" '
                         f'structureRef="{v["type"]}"/>')
    for n in spec["nodes"]:
        if n["type"] == "serviceTask":
            svc = n["service"]
            parts += [
                f'  <bpmn2:message id="_{n["id"]}InMessage" itemRef="{_method_item(n["inputs"][0], var_types)}"/>',
                f'  <bpmn2:message id="_{n["id"]}OutMessage" itemRef="{_method_item(n["outputs"][0], var_types)}"/>',
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
    overflow: list[str] = []
    node_docs = {n["id"]: _node_doc(n["id"], n["doc"], overflow) for n in spec["nodes"] if n.get("doc")}
    doc_items = ([f'{a["id"]}: {a["text"]}' for a in spec.get("assumptions", [])]
                 + [f"Node documentation {o}" for o in overflow])
    if doc_items:
        label = "Open items and assumptions" if spec.get("assumptions") else "Node documentation"
        parts.append(f'    <bpmn2:documentation>{label} — {escape(" / ".join(doc_items))}</bpmn2:documentation>')
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
        doc = (f'\n      <bpmn2:documentation>{escape(node_docs[n["id"]])}</bpmn2:documentation>'
               if n["id"] in node_docs else "")

        if n["type"] in TASK_TAGS:
            svc_attr = ""
            if n["type"] == "serviceTask":
                svc_attr = (f' implementation="##Java" '
                            f'operationRef="_{n["id"]}Operation"')
            parts.append(f'    <bpmn2:{tag} id="{n["id"]}" name={quoteattr(n["name"])}{svc_attr}>{doc}{inc}{out}')
            parts.append('      <bpmn2:ioSpecification>')
            for i, var in enumerate(n.get("inputs", [])):
                pname = "Parameter" if n["type"] == "serviceTask" and i == 0 else var
                item = _method_item(var, var_types) if n["type"] == "serviceTask" else _item_id(var)
                parts.append(f'        <bpmn2:dataInput id="_{n["id"]}_in_{i}" name="{pname}" '
                             f'itemSubjectRef="{item}"/>')
            for i, var in enumerate(n.get("outputs", [])):
                pname = "Result" if n["type"] == "serviceTask" else var
                item = _method_item(var, var_types) if n["type"] == "serviceTask" else _item_id(var)
                parts.append(f'        <bpmn2:dataOutput id="_{n["id"]}_out_{i}" name="{pname}" '
                             f'itemSubjectRef="{item}"/>')
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
            converging = len(incoming.get(n["id"], [])) > 1 and len(outgoing.get(n["id"], [])) == 1
            direction = "Converging" if converging else "Diverging"
            parts.append(f'    <bpmn2:{tag} id="{n["id"]}" name={quoteattr(n["name"])} '
                         f'gatewayDirection="{direction}">{doc}{inc}{out}')
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
    """Deterministic layered (left-to-right) BPMN diagram layout.

    - Layers/ranks nodes by longest path from start in the forward DAG (ignoring back edges).
    - Gateway branches are placed on separate rows; primary forward continuation stays on center row.
    - Loop-back branches route above the main row to converging merge gateways.
    - Sequence flow waypoints use orthogonal routing that avoids passing through shapes.
    - Conditional and named flows carry BPMNLabel annotations.
    """
    nodes = {n["id"]: n for n in spec["nodes"]}
    flows = spec["flows"]

    outgoing: dict[str, list[dict]] = {n["id"]: [] for n in spec["nodes"]}
    incoming: dict[str, list[dict]] = {n["id"]: [] for n in spec["nodes"]}
    for f in flows:
        outgoing[f["from"]].append(f)
        incoming[f["to"]].append(f)

    # 1. Identify start node(s)
    start_nodes = [n["id"] for n in spec["nodes"] if n["type"] == "start"]
    if not start_nodes:
        start_nodes = [n["id"] for n in spec["nodes"] if not incoming[n["id"]]]
    if not start_nodes and spec["nodes"]:
        start_nodes = [spec["nodes"][0]["id"]]

    # 2. Detect back edges via deterministic DFS
    UNVISITED, VISITING, VISITED = 0, 1, 2
    state = {n["id"]: UNVISITED for n in spec["nodes"]}
    back_edges: set[int] = set()

    def dfs(u: str):
        state[u] = VISITING
        for f in outgoing[u]:
            v = f["to"]
            if state[v] == VISITING:
                back_edges.add(id(f))
            elif state[v] == UNVISITED:
                dfs(v)
        state[u] = VISITED

    for s in start_nodes:
        if state[s] == UNVISITED:
            dfs(s)
    for n in spec["nodes"]:
        if state[n["id"]] == UNVISITED:
            dfs(n["id"])

    # 3. Layering / Ranking by longest path from start in the DAG (ignoring back edges)
    in_deg = {n["id"]: 0 for n in spec["nodes"]}
    for f in flows:
        if id(f) not in back_edges:
            in_deg[f["to"]] += 1

    queue = [s for s in start_nodes if in_deg[s] == 0]
    if not queue:
        queue = [n["id"] for n in spec["nodes"] if in_deg[n["id"]] == 0]

    ranks = {n["id"]: 0 for n in spec["nodes"]}
    topo_order = []
    q = deque(queue)
    visited_topo = set(queue)

    while q:
        u = q.popleft()
        topo_order.append(u)
        for f in outgoing[u]:
            if id(f) in back_edges:
                continue
            v = f["to"]
            ranks[v] = max(ranks[v], ranks[u] + 1)
            in_deg[v] -= 1
            if in_deg[v] == 0:
                q.append(v)
                visited_topo.add(v)

    for n in spec["nodes"]:
        if n["id"] not in visited_topo:
            topo_order.append(n["id"])

    # Compute max reachable rank along forward edges to identify main continuation path
    max_future_rank = {n["id"]: ranks[n["id"]] for n in spec["nodes"]}
    for u in reversed(topo_order):
        for f in outgoing[u]:
            if id(f) not in back_edges:
                v = f["to"]
                max_future_rank[u] = max(max_future_rank[u], max_future_rank[v])

    # 4. Row assignment
    def is_loop_back_node(nid: str) -> bool:
        outs = outgoing.get(nid, [])
        return len(outs) > 0 and all(id(f) in back_edges for f in outs)

    rows: dict[str, int] = {}
    for s in start_nodes:
        if s not in rows:
            rows[s] = 0

    for u in topo_order:
        u_row = rows.get(u, 0)
        fwd_outs = [f for f in outgoing[u] if id(f) not in back_edges]
        if not fwd_outs:
            continue
        if len(fwd_outs) == 1:
            v = fwd_outs[0]["to"]
            if v not in rows:
                rows[v] = u_row
        else:
            # Multi-branch gateway: place loop branches above, primary on same row, others below
            loop_branches = []
            other_branches = []

            non_loop = [f for f in fwd_outs if not is_loop_back_node(f["to"])]
            if non_loop:
                primary_flow = max(non_loop, key=lambda f: (max_future_rank[f["to"]], -fwd_outs.index(f)))
                primary_target = primary_flow["to"]
            else:
                primary_target = fwd_outs[0]["to"]

            for f in fwd_outs:
                v = f["to"]
                if is_loop_back_node(v):
                    loop_branches.append(v)
                elif v == primary_target:
                    pass
                else:
                    other_branches.append(v)

            for i, v in enumerate(loop_branches):
                if v not in rows:
                    rows[v] = u_row - (len(loop_branches) - i)

            if primary_target not in rows:
                rows[primary_target] = u_row

            for i, v in enumerate(other_branches):
                if v not in rows:
                    rows[v] = u_row + 1 + i

    for n in spec["nodes"]:
        if n["id"] not in rows:
            rows[n["id"]] = 0

    # Conflict resolution: ensure no two nodes in the same column share the same row
    col_nodes: dict[int, list[str]] = {}
    for n in spec["nodes"]:
        nid = n["id"]
        col_nodes.setdefault(ranks[nid], []).append(nid)

    for c in sorted(col_nodes.keys()):
        used_rows: set[int] = set()
        for nid in col_nodes[c]:
            r = rows[nid]
            if r in used_rows:
                offset = 1
                while True:
                    if r + offset not in used_rows:
                        r = r + offset
                        break
                    if r - offset not in used_rows:
                        r = r - offset
                        break
                    offset += 1
                rows[nid] = r
            used_rows.add(r)

    # 5. Compute absolute coordinates
    COLUMN_GAP = 90
    ROW_HEIGHT = 80
    ROW_GAP = 70
    X_START = 60
    Y_START = 60

    all_cols = sorted(col_nodes.keys())
    col_width = {c: max(NODE_SIZE.get(nodes[nid]["type"], (160, 80))[0] for nid in col_nodes[c]) for c in all_cols}

    col_center: dict[int, int] = {}
    cur_x = X_START
    for c in all_cols:
        col_center[c] = cur_x + col_width[c] // 2
        cur_x += col_width[c] + COLUMN_GAP

    min_row = min(rows.values()) if rows else 0
    row_center = {r: Y_START + (r - min_row) * (ROW_HEIGHT + ROW_GAP) + ROW_HEIGHT // 2
                  for r in set(rows.values())}

    pos: dict[str, tuple[int, int, int, int]] = {}
    for n in spec["nodes"]:
        nid = n["id"]
        w, h = NODE_SIZE.get(n["type"], (160, 80))
        cx = col_center[ranks[nid]]
        cy = row_center[rows[nid]]
        pos[nid] = (cx - w // 2, cy - h // 2, w, h)

    # 6. Waypoints and edge routing
    out = [
        '  <bpmndi:BPMNDiagram>',
        f'    <bpmndi:BPMNPlane bpmnElement="{spec["process"]["id"]}">'
    ]

    for n in spec["nodes"]:
        x, y, w, h = pos[n["id"]]
        out.append(f'      <bpmndi:BPMNShape id="shape_{n["id"]}" bpmnElement="{n["id"]}">' )
        out.append(f'        <dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}"/>')
        out.append('      </bpmndi:BPMNShape>')

    for f in flows:
        fid = flow_ids[id(f)]
        fn = f["from"]
        tn = f["to"]
        sx, sy, sw, sh = pos[fn]
        tx, ty, tw, th = pos[tn]
        scx, scy = sx + sw // 2, sy + sh // 2
        tcx, tcy = tx + tw // 2, ty + th // 2
        cs, rs = ranks[fn], rows[fn]
        ct, rt = ranks[tn], rows[tn]

        is_back = id(f) in back_edges or ct <= cs

        if not is_back:
            if rs == rt:
                waypoints = [(sx + sw, scy), (tx, tcy)]
            else:
                mid_x = sx + sw + (tx - (sx + sw)) // 2
                waypoints = [(sx + sw, scy), (mid_x, scy), (mid_x, tcy), (tx, tcy)]
        else:
            if rs < rt:
                waypoints = [(sx, scy), (tcx, scy), (tcx, ty)]
            elif rs > rt:
                waypoints = [(sx, scy), (tcx, scy), (tcx, ty + th)]
            else:
                corridor_y = sy - 40
                waypoints = [(scx, sy), (scx, corridor_y), (tcx, corridor_y), (tcx, ty)]

        out.append(f'      <bpmndi:BPMNEdge id="edge_{fid}" bpmnElement="{fid}">')
        for wx, wy in waypoints:
            out.append(f'        <di:waypoint x="{wx}" y="{wy}"/>')

        if f.get("name"):
            name = f["name"]
            label_w = min(max(len(name) * 7, 50), 160)
            label_h = 14
            if len(waypoints) >= 2:
                p0, p1 = waypoints[0], waypoints[1]
                lx = (p0[0] + p1[0]) // 2 - label_w // 2
                if is_back or rs <= rt:
                    ly = p0[1] - label_h - 4
                else:
                    ly = p0[1] + 6
            else:
                lx = sx + sw + 5
                ly = scy - label_h - 4
            out.append('        <bpmndi:BPMNLabel>')
            out.append(f'          <dc:Bounds x="{lx}" y="{ly}" width="{label_w}" height="{label_h}"/>')
            out.append('        </bpmndi:BPMNLabel>')

        out.append('      </bpmndi:BPMNEdge>')

    out += ['    </bpmndi:BPMNPlane>', '  </bpmndi:BPMNDiagram>']
    return "\n".join(out)
