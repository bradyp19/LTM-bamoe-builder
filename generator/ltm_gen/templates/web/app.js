// Generated user webpage. Everything process-specific comes from application.json,
// which the builder writes from the specs; this script holds no process names.
"use strict";

let APP = null;
const TERMINAL = ["COMPLETED", "ABORTED", "ERROR"];
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "onclick" || k === "onchange") e[k] = v;
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
const pretty = (v) => el("pre", {}, JSON.stringify(v, null, 2));

function identity() {
  const q = new URLSearchParams();
  q.set("user", $("#user").value.trim() || APP.user);
  for (const g of $("#groups").value.split(",").map((s) => s.trim()).filter(Boolean)) q.append("group", g);
  return q.toString();
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method, headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${path} -> HTTP ${r.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

// ---- data-audit (what the running service recorded for an instance) ----

// Without pagination the audit queries return only the newest 10 rows.
const ALL_ROWS = "pagination: { limit: 100000, offset: 0 }";

async function audit(id) {
  const q = `{ nodes: GetAllProcessInstancesNodeByProcessInstanceId(processInstanceId: "${id}", ${ALL_ROWS}) { eventId eventType nodeType nodeName eventDate }
    variables: GetAllProcessInstancesVariableByProcessInstanceId(processInstanceId: "${id}", ${ALL_ROWS}) { variableName variableValue eventDate }
    history: GetAllProcessInstancesVariableHistoryByProcessInstanceId(processInstanceId: "${id}", ${ALL_ROWS}) { variableName logs { variableValue eventDate } }
    states: GetProcessInstancesStateHistory(processInstanceId: "${id}", ${ALL_ROWS}) { eventType eventDate }
    tasks: GetAllUserTaskInstanceState(${ALL_ROWS}) { processInstanceId userTaskInstanceId name state eventType eventDate } }`;
  const r = await api("POST", "/data-audit/q", { query: q });
  if (r.errors) throw new Error("data-audit: " + JSON.stringify(r.errors));
  const d = r.data;
  const variables = {};
  for (const v of d.variables) variables[v.variableName] = v.variableValue;
  return {
    nodes: [...d.nodes].reverse(),
    variables, history: d.history,
    // an instance that started and ended in one unit of work has both events at the same time
    status: (d.states.find((s) => TERMINAL.includes(s.eventType)) || d.states[0] || {}).eventType || null,
    tasks: d.tasks.filter((t) => t.processInstanceId === id),
  };
}

// The audit records java.time values as arrays: LocalDate 2027-01-31 -> [2027,1,31].
function temporalParts(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?)?$/.exec(text);
  if (!m) return null;
  const nanos = m[7] ? Number(m[7].padEnd(9, "0")) : 0;
  return [m[1], m[2], m[3], m[4], m[5], m[6]].map((x) => Number(x || 0)).concat(nanos);
}

// Sent values are partial (unset fields are not sent); recorded records carry every field.
function sameValue(sent, recorded) {
  if (sent === null || sent === undefined) return recorded === null || recorded === undefined;
  if (typeof sent === "string" && Array.isArray(recorded) && temporalParts(sent)) {
    const want = temporalParts(sent);
    return recorded.length <= 7 && want.every((x, i) => x === Number(recorded[i] || 0));
  }
  if (Array.isArray(sent)) {
    return Array.isArray(recorded) && sent.length === recorded.length &&
      sent.every((s, i) => sameValue(s, recorded[i]));
  }
  if (typeof sent === "object") {
    return recorded !== null && typeof recorded === "object" &&
      Object.keys(sent).every((k) => sameValue(sent[k], recorded[k]));
  }
  if (typeof sent === "number" || typeof recorded === "number") return Number(sent) === Number(recorded);
  return sent === recorded;
}

// After every action: read the record back and compare it with what was sent.
async function checkStep(proc, id, action, nodeName, sent, before) {
  // Events of one step can be stored in more than one write; wait (up to ~5 s)
  // until the step's node has been left before judging the record.
  const seen = new Set(before.nodes.map((n) => n.eventId));
  // Started over REST, BAMOE 9.6 records only ENTER for the start node; a task must be left (EXIT).
  const wanted = action === "start" ? ["ENTER", "EXIT"] : ["EXIT"];
  const exited = (nodes) => nodes.some((n) => !seen.has(n.eventId) && wanted.includes(n.eventType) && n.nodeName === nodeName);
  let after = null;
  for (let i = 0; i < 17; i++) {
    after = await audit(id);
    if (exited(after.nodes)) break;
    await new Promise((res) => setTimeout(res, 300));
  }
  const added = after.nodes.filter((n) => !seen.has(n.eventId));
  const problems = [];
  if (!added.length) problems.push("nothing was recorded for this step");
  if (!exited(after.nodes)) {
    problems.push(`node history has no ${action === "start" ? "record" : "exit"} of '${nodeName}'`);
  }
  for (const [k, v] of Object.entries(sent)) {
    if (!(k in after.variables)) problems.push(`variable '${k}' was sent but nothing was recorded`);
    else if (!sameValue(v, after.variables[k])) {
      problems.push(`variable '${k}' was sent as ${JSON.stringify(v)} but recorded as ${JSON.stringify(after.variables[k])}`);
    }
  }
  const check = {
    at: new Date().toISOString(), process: proc.id, instance: id, action, node: nodeName, sent,
    variablesBefore: before.variables, variablesAfter: after.variables,
    nodeEvents: added.map((n) => `${n.eventType} ${n.nodeType} '${n.nodeName}'`),
    taskStates: after.tasks, status: after.status, problems,
  };
  const all = JSON.parse(localStorage.getItem("stepChecks") || "{}");
  (all[id] = all[id] || []).push(check);
  localStorage.setItem("stepChecks", JSON.stringify(all));
  showCheck(check);
  return check;
}

function showCheck(c) {
  const box = $("#last-check");
  box.replaceChildren(el("div", { class: "card check" + (c.problems.length ? " bad" : ""), id: "step-check" },
    el("h3", {}, "Step check: ", el("span", { class: c.problems.length ? "fail" : "ok", id: "step-check-result" },
      c.problems.length ? "MISMATCH" : "OK")),
    el("p", {}, `${c.action} on instance ${c.instance} (${c.process}); recorded status ${c.status}`),
    c.problems.length ? el("ul", {}, c.problems.map((p) => el("li", { class: "fail" }, p))) : "",
    el("p", {}, "Node events recorded for this step: " + (c.nodeEvents.join(", ") || "none")),
    el("details", {}, el("summary", {}, "Sent / variables before / after"),
      el("h4", {}, "Sent"), pretty(c.sent), el("h4", {}, "Before"), pretty(c.variablesBefore),
      el("h4", {}, "After"), pretty(c.variablesAfter))));
  box.scrollIntoView({ behavior: "smooth" });
}

// ---- forms built from the spec ----

const SCALAR = { "java.lang.Boolean": "bool", Boolean: "bool", "java.lang.Integer": "int", Integer: "int",
  "java.lang.String": "text", String: "text", "java.math.BigDecimal": "decimal", "java.time.LocalDate": "date" };

function scalarInput(name, type, id) {
  const kind = SCALAR[type] || "text";
  if (kind === "bool") {
    return el("select", { id, "data-kind": kind, name },
      el("option", { value: "" }, "(not set)"), el("option", { value: "true" }, "true"), el("option", { value: "false" }, "false"));
  }
  return el("input", { id, name, "data-kind": kind,
    type: kind === "int" || kind === "decimal" ? "number" : kind === "date" ? "date" : "text",
    step: kind === "decimal" ? "any" : null });
}

function readScalar(input) {
  const v = input.value;
  if (v === "") return undefined;
  switch (input.dataset.kind) {
    case "bool": return v === "true";
    case "int": return parseInt(v, 10);
    case "decimal": return Number(v);
    default: return v;
  }
}
function writeScalar(input, v) { input.value = v === null || v === undefined ? "" : String(v); }

function modelFields(model, prefix) {
  return APP.models[model].map((f) => el("label", { class: "field" }, `${f.name} (${f.type.split(".").pop()})`,
    scalarInput(f.name, f.type, `${prefix}-${f.name}`)));
}

// One widget per process variable: flag, scalar, record (fieldset) or list of records (rows).
function variableWidget(v, prefix) {
  const id = `${prefix}-${v.name}`;
  if (v.kind === "model") {
    return el("fieldset", { id, "data-var": v.name, "data-kind": "model", "data-model": v.model },
      el("legend", {}, `${v.name} (${v.model})`), modelFields(v.model, id));
  }
  if (v.kind === "list") {
    const rows = el("tbody");
    const box = el("fieldset", { id, "data-var": v.name, "data-kind": "list", "data-model": v.model },
      el("legend", {}, `${v.name} (list of ${v.model})`),
      el("table", {}, el("thead", {}, el("tr", {}, APP.models[v.model].map((f) => el("th", {}, f.name)), el("th"))), rows),
      el("button", { type: "button", class: "add-row", onclick: () => addRow(box) }, `Add ${v.model}`),
      el("label", { class: "field" }, "send", el("select", { class: "list-mode" },
        el("option", { value: "omit" }, "(not set)"), el("option", { value: "send" }, "the rows above"))));
    return box;
  }
  return el("label", { class: "field", "data-var": v.name, "data-kind": "scalar" }, `${v.name} (${v.type.split(".").pop()})`,
    scalarInput(v.name, v.type, id));
}

function addRow(box, values = {}) {
  const tbody = box.querySelector("tbody");
  const n = tbody.children.length;
  const tr = el("tr", {}, APP.models[box.dataset.model].map((f) => {
    const input = scalarInput(f.name, f.type, `${box.id}-${n}-${f.name}`);
    writeScalar(input, values[f.name]);
    return el("td", {}, input);
  }), el("td", {}, el("button", { type: "button", onclick: () => tr.remove() }, "remove")));
  tbody.append(tr);
  box.querySelector(".list-mode").value = "send";
}

function readRecord(container) {
  const out = {};
  for (const input of container.querySelectorAll("input, select")) {
    if (input.classList.contains("list-mode")) continue;
    const v = readScalar(input);
    if (v !== undefined) out[input.name] = v;
  }
  return out;
}

function readVariables(form) {
  const out = {};
  for (const w of form.querySelectorAll("[data-var]")) {
    const kind = w.dataset.kind;
    if (kind === "scalar") {
      const v = readScalar(w.querySelector("input, select"));
      if (v !== undefined) out[w.dataset.var] = v;
    } else if (kind === "model") {
      const rec = readRecord(w);
      if (Object.keys(rec).length) out[w.dataset.var] = rec;
    } else if (w.querySelector(".list-mode").value === "send") {
      out[w.dataset.var] = [...w.querySelectorAll("tbody tr")].map(readRecord);
    }
  }
  return out;
}

function fillVariables(form, values) {
  for (const w of form.querySelectorAll("[data-var]")) {
    const v = values[w.dataset.var];
    if (w.dataset.kind === "scalar") writeScalar(w.querySelector("input, select"), v);
    else if (w.dataset.kind === "model") {
      for (const input of w.querySelectorAll("input, select")) writeScalar(input, v ? v[input.name] : undefined);
    } else {
      w.querySelector("tbody").replaceChildren();
      w.querySelector(".list-mode").value = "omit";
      if (Array.isArray(v)) {
        v.forEach((row) => addRow(w, row));
        w.querySelector(".list-mode").value = "send";
      }
    }
  }
}

function scenarioPicker(options, form) {
  if (!options.length) return "";
  const sel = el("select", { class: "scenario" }, el("option", { value: "" }, "(fill from a spec scenario)"),
    options.map((o, i) => el("option", { value: String(i) }, o.label)));
  sel.onchange = () => { if (sel.value !== "") fillVariables(form, options[Number(sel.value)].values); };
  return el("label", { class: "field" }, "Scenario", sel);
}

// ---- tabs ----

function renderStart() {
  const tab = $("#tab-start");
  tab.replaceChildren();
  for (const p of APP.processes) {
    const vars = p.variables.filter((v) => p.startVariables.includes(v.name));
    const form = el("form", { id: `start-${p.id}` }, vars.map((v) => variableWidget(v, `start-${p.id}`)));
    const options = p.scenarios.map((s) => ({ label: s.name, values: s.start }));
    const button = el("button", { class: "primary", type: "submit" }, `Start ${p.name}`);
    form.append(el("div", {}, button));
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      const sent = readVariables(form);
      try {
        const r = await api("POST", p.endpoint, sent);
        await checkStep(p, r.id, "start", p.startNode, sent, { nodes: [], variables: {} });
      } catch (e) { alert(e.message); }
    };
    tab.append(el("div", { class: "card", id: `process-${p.id}` },
      el("h2", {}, p.name), el("p", { class: "evidence" }, `Process id ${p.id}. Evidence: ${p.evidence}`),
      el("p", {}, "Start variables: ", p.startVariables.join(", ") || "none", " (", p.startSource, ")"),
      scenarioPicker(options, form), form));
  }
}

// Overlapping refreshes (tab click + Refresh) must not append to the same table.
let inboxRun = 0;
let instancesRun = 0;

async function renderInbox() {
  const run = ++inboxRun;
  const body = document.createElement("tbody");
  for (const p of APP.processes) {
    if (!p.userTasks.length) continue;
    const instances = await api("GET", p.endpoint);
    for (const inst of instances) {
      const tasks = await api("GET", `${p.endpoint}/${inst.id}/tasks?${identity()}`);
      for (const t of tasks) {
        const spec = p.userTasks.find((u) => u.name === t.name);
        if (!spec) continue; // work items of service tasks are not user tasks
        body.append(el("tr", { "data-task": t.id },
          el("td", {}, p.name), el("td", {}, inst.id), el("td", {}, t.name), el("td", {}, t.phaseStatus || t.phase || ""),
          el("td", {}, el("button", { onclick: () => openTask(p, inst.id, spec, t) }, "Open"))));
      }
    }
  }
  if (!body.children.length) body.append(el("tr", {}, el("td", { colspan: 5 }, "No open user tasks.")));
  if (run === inboxRun) $("#inbox tbody").replaceChildren(...body.children);
}

function openTask(p, instanceId, spec, task) {
  const outputs = p.variables.filter((v) => spec.outputs.includes(v.name));
  const form = el("form", { id: `task-${spec.id}` }, outputs.map((v) => variableWidget(v, `task-${spec.id}`)));
  form.append(el("div", {}, el("button", { class: "primary", type: "submit" }, `Complete ${spec.name}`)));
  const options = p.scenarios.flatMap((s) => s.steps.map((st, i) => ({ s, st, i })))
    .filter((x) => x.st.task === spec.id).map((x) => ({ label: `${x.s.name} step ${x.i + 1}`, values: x.st.complete }));
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const sent = readVariables(form);
    try {
      const before = await audit(instanceId);
      await api("POST", `${p.endpoint}/${instanceId}/${spec.path}/${task.id}?${identity()}`, sent);
      await checkStep(p, instanceId, `complete ${spec.id}`, spec.name, sent, before);
      $("#task").replaceChildren();
      await renderInbox();
    } catch (e) { alert(e.message); }
  };
  const inputs = {};
  for (const name of spec.inputs) inputs[name] = task.parameters ? task.parameters[name] : undefined;
  $("#task").replaceChildren(el("div", { class: "card", id: "open-task" },
    el("h3", {}, `${spec.name} (${p.name})`), el("p", {}, `Instance ${instanceId}, task ${task.id}`),
    el("p", { class: "evidence" }, spec.doc || ""),
    el("h4", {}, "Task inputs (read from the instance)"), pretty(inputs),
    el("h4", {}, "Task outputs"), outputs.length ? "" : el("p", {}, "This task has no outputs."),
    scenarioPicker(options, form), form));
}

async function renderInstances() {
  const run = ++instancesRun;
  const body = document.createElement("tbody");
  for (const p of APP.processes) {
    const q = `{ GetAllProcessInstancesStateByProcessId(processId: "${p.id}", ${ALL_ROWS}) { processInstanceId eventType eventDate } }`;
    const r = await api("POST", "/data-audit/q", { query: q });
    // This query keeps one row per instance, and BAMOE can store an ACTIVE event 1 ms after
    // COMPLETED, so the row may say ACTIVE for a finished instance: resolve the status from
    // each instance's state history, where a terminal event wins (as in the detail view).
    const ids = [...new Set(r.data.GetAllProcessInstancesStateByProcessId.map((s) => s.processInstanceId))];
    const latest = new Map();
    if (ids.length) {
      const hq = "{ " + ids.map((id, i) =>
        `i${i}: GetProcessInstancesStateHistory(processInstanceId: "${id}", ${ALL_ROWS}) { eventType eventDate }`).join(" ") + " }";
      const h = await api("POST", "/data-audit/q", { query: hq });
      ids.forEach((id, i) => {
        const states = h.data[`i${i}`] || [];
        const newest = states.reduce((a, b) => (!a || b.eventDate > a.eventDate ? b : a), null);
        const s = states.find((e) => TERMINAL.includes(e.eventType)) || newest;
        if (s) latest.set(id, { processInstanceId: id, eventType: s.eventType, eventDate: s.eventDate });
      });
    }
    for (const s of latest.values()) {
      body.append(el("tr", { "data-instance": s.processInstanceId },
        el("td", {}, p.name), el("td", {}, s.processInstanceId), el("td", {}, s.eventType), el("td", {}, s.eventDate),
        el("td", {}, el("button", { onclick: () => showInstance(p, s.processInstanceId) }, "View"))));
    }
  }
  if (run === instancesRun) $("#instances tbody").replaceChildren(...body.children);
}

async function showInstance(p, id) {
  const a = await audit(id);
  const checks = (JSON.parse(localStorage.getItem("stepChecks") || "{}")[id]) || [];
  $("#instance").replaceChildren(el("div", { class: "card", id: "instance-view" },
    el("h3", {}, `${p.name}: ${id}`), el("p", {}, "Status: ", el("strong", { id: "instance-status" }, a.status || "unknown")),
    el("h4", {}, "Node history (oldest first)"),
    el("table", { id: "node-history" }, el("tr", {}, el("th", {}, "Event"), el("th", {}, "Type"), el("th", {}, "Node"), el("th", {}, "At")),
      a.nodes.map((n) => el("tr", {}, el("td", {}, n.eventType), el("td", {}, n.nodeType), el("td", {}, n.nodeName), el("td", {}, n.eventDate)))),
    el("h4", {}, "User task states"),
    el("table", {}, el("tr", {}, el("th", {}, "Task"), el("th", {}, "State"), el("th", {}, "At")),
      a.tasks.map((t) => el("tr", {}, el("td", {}, t.name), el("td", {}, t.state), el("td", {}, t.eventDate)))),
    el("h4", {}, "Current variables"), pretty(a.variables),
    el("h4", {}, "Step checks made from this page"),
    checks.length ? el("table", { id: "step-checks" }, el("tr", {}, el("th", {}, "Action"), el("th", {}, "Result"), el("th", {}, "Details")),
      checks.map((c) => el("tr", {}, el("td", {}, c.action),
        el("td", { class: c.problems.length ? "fail" : "ok" }, c.problems.length ? "MISMATCH" : "OK"),
        el("td", {}, c.problems.join("; ") || c.nodeEvents.join(", "))))) : el("p", {}, "None."),
    el("details", {}, el("summary", {}, "Variable history"), pretty(a.history))));
}

function showTab(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const s of ["start", "inbox", "instances"]) $(`#tab-${s}`).hidden = s !== name;
  const load = { inbox: renderInbox, instances: renderInstances }[name];
  if (load) load().catch((e) => alert(e.message));
}

async function init() {
  APP = await api("GET", "application.json");
  document.title = APP.application.name;
  $("#app-name").textContent = APP.application.name;
  $("#user").value = APP.user;
  $("#groups").value = APP.groups.join(",");
  for (const b of document.querySelectorAll("nav button")) b.onclick = () => showTab(b.dataset.tab);
  $("#refresh-inbox").onclick = () => renderInbox().catch((e) => alert(e.message));
  $("#refresh-instances").onclick = () => renderInstances().catch((e) => alert(e.message));
  renderStart();
}

init().catch((e) => { document.body.prepend(el("p", { class: "fail" }, e.message)); });
