# NSSOL Allocations: decisions needed

Source of the open items: `assumptions` in [`extractor/supplements/allocations.json`](../extractor/supplements/allocations.json).
Every quote below was checked against the source paragraph (D03 = process model document, D04 = interface document, D07 = site/security document).

**Nothing in the supplement has been changed.** Each section ends with the exact edit I would make once you decide.
Reply with the item and letter, e.g. `AL-C1: a, AL-2: c`. "Recommended" is a recommendation only.

## Summary

| Item | Question | Options | Recommended | Supported today |
|---|---|---|---|---|
| AL-C1 | 3 forms (table) or 4 (diagram)? | a keep 4 / b drop Allocation Confirmation | **a** | yes (no change) |
| AL-C2 | Back button on Allocation Confirmation | a no back flow / b add back flow / c UI only | **a** | a, c yes; b no |
| AL-1 | Who is assigned the 4 user tasks? | a unassigned / b NP Users / c NP Administrators | **b** | yes (`candidateGroups`) |
| AL-2 | Which branch wins, and what if none is true? | a as is / b priority only / c default = cancel + priority | **c** | yes (`flowRules`) |
| AL-3 | Reset of `isAddEmployee` / `isAddSubcontractor` on loop-back | a accept / b form resets the flags / c new reset step | **b** | a, b yes; c no |
| AL-4 | Write nodes modelled as service tasks | a accept / b change task type | **a** | yes (no change) |
| AL-5 | Dynamic process name | a static name / b `descriptionTemplate` | **b** | yes (`descriptionTemplate`) |
| AL-6 | `projectId = 3` default | a drop / b keep as test default only / c carry into spec | **a** | yes (no change) |
| AL-7 | Target-design proposals (class names, types, outputs) | a approve / b change | **a** | yes (no change) |
| AL-8 | Search-screen cancel is not enforced | a accept / b enforce with a condition | **a** | a yes; b no |

---

## AL-C1: Form count, 3 vs 4

**Evidence**
- D03 ¶220: `| Forms Involved | 1 (registration) | 3 (allocation + 2 search) | 0 |`
- D03 ¶118–119: `[User Task: Allocation Confirmation]` with `Interface: NSSOL_FRM_Allocation_Confirmation`.
- D04 ¶84–97 documents that interface in full: "Final confirmation screen before writing allocation records".

The diagram and the interface document agree. Only the summary table disagrees, and it is the only place that gives a count.

**Options**
- **a. Keep 4 user tasks (current).** Treat the table as out of date.
- **b. Drop Allocation Confirmation.** `isAssign` goes straight to the two writes.

**Consequence.** With a, nothing changes: `allocationConfirmation` stays a user task and the `assign_savesEmployeesAndSubcontractors` test keeps its second step. With b, one task, its generated form hooks and one test step go away, and the user no longer confirms before records are written.

**Recommended: a.** Two sources describe the screen; one summary cell contradicts them.

**Supplement edit (a):** reword the `AL-C1` text to "RESOLVED: …table at D03 ¶220 is out of date; model follows the diagram and D04 ¶84–97". No structural edit.
**Supported today:** yes.

---

## AL-C2: Back button on Allocation Confirmation

**Evidence**
- D04 ¶97: `**Back** button: returns to allocation screen`
- D03 ¶118–124: Allocation Confirmation → Write Map Employee Records. No path back.

**Options**
- **a. No back flow (current).** Follow the diagram.
- **b. Add a flow from Allocation Confirmation back to the main-screen merge.** This needs an exclusive gateway after the task and a new output flag (for example `confirmBack`).
- **c. Treat Back as a UI behaviour.** The form offers Back without completing the task, so the process never sees it.

**Consequence.** With a or c the process model is unchanged. With b the model gains a gateway, a variable and a new test.

**Recommended: a** (and implement c in the form if needed). In a BPMN user task, "back" that does not complete the task is not a sequence flow.

**Supplement edit (a):** reword `AL-C2` as resolved, stating that Back is a form behaviour that leaves the task open.
**Supported today:** a and c, yes. b, **no**: the extractor takes flows only from the document diagram or the transcription, and there is no way to add one from the supplement. It needs a new mechanism (for example `design.extraFlows` plus a new gateway node). Say so if you choose b and I will scope it.

---

## AL-1: Task assignees

**Evidence**
- D03 ¶239–242: "All 3 process models share the same role map: `ADMIN_OWNER`: NP Administrators group; `VIEWER`: NP Users group; No explicit INITIATOR or MANAGER group assignments (open to all authenticated users)".
- D07 ¶58–59: NP Administrators = `site_administrator`; NP Users = `site_viewer`.
- No document names an assignee for any of the four user tasks.

**Options**
- **a. Leave unassigned (current).** Any user can claim the task.
- **b. `candidateGroups: ["NP Users"]`** on all four tasks. This matches "open to all authenticated users" in D03 ¶242 and the viewer role.
- **c. `candidateGroups: ["NP Administrators"]`** on all four tasks.

**Consequence.** a and b both produce tasks that are visible to everyone who is authenticated, but b makes the intent explicit in the BPMN (`potentialOwner`). c would lock regular users out of allocation, which no document says.

**Recommended: b.** This is an analyst choice, not a documented fact.

**Supplement edit (b):** add `"candidateGroups": ["NP Users"]` to `allocationMainScreen`, `employeeSearchScreen`, `subcontractorSearchScreen` and `allocationConfirmation` in `design.nodes`. Update `AL-1` to say the group is chosen, not documented.
**Supported today:** yes. `candidateGroups` is a list of group names without commas, valid only on user tasks.

---

## AL-2: Branch precedence and no-match

**Evidence**
- D03 ¶93, 95, 105, 115: four conditions, `allocationCancel`, `isAddEmployee`, `isAddSubcontractor`, `isAssign`. All four are independent booleans.
- Nothing says which wins if two are true, or what happens if none is.
- The gateway `allocationMainScreenGateway` has the four conditional flows and no default.

**Options**
- **a. As is.** Conditions in document order; if none is true the engine finds no outgoing flow.
- **b. Priority only.** `flowRules` gives cancel 1, addEmployee 2, addSubcontractor 3, assign 4. Cancel always wins, but no match is still an error.
- **c. Default + priority.** The cancel flow becomes the default (it ends without writing), and the other three get priorities 1 to 3.

**Consequence.** With c, a task completed with no flag set ends the process without writing anything instead of failing. Trade-off: a default flow carries no condition, so `allocationCancel` is no longer tested. Cancel is now "everything else", and if `allocationCancel` and `isAssign` are both true, assign wins. The buttons set one flag each (D03 ¶88–91), so this only matters if the form sets several.

**Recommended: c.** It removes the stuck-instance case and writes nothing by default.

**Supplement edit (c):** add to `design`:
```json
"flowRules": {
  "allocationMainScreenGateway->end1": {"default": true},
  "allocationMainScreenGateway->employeeSearchScreen": {"priority": 1},
  "allocationMainScreenGateway->subcontractorSearchScreen": {"priority": 2},
  "allocationMainScreenGateway->allocationConfirmation": {"priority": 3}
}
```
Update `AL-2` to say the rule was chosen, not documented. The `cancel_writesNothing` test still passes because cancel is the default.
**Supported today:** yes. The default flow emits the gateway's `default=` attribute; priority is emitted as `drools:priority`; if any branch has a priority, every non-default branch must have one.

---

## AL-3: Flag reset on loop-back

**Evidence**
- D03 ¶102–103: both the cancel and confirm paths go "back to Allocation Main Screen".
- D03 ¶112–113: same for subcontractors.
- Nothing clears `isAddEmployee` / `isAddSubcontractor`, so after the loop-back the same flag is still true.

**Options**
- **a. Accept and document.** The main-screen form is expected to reset flags when it opens.
- **b. Make it the form's contract.** The main-screen task always returns all four flags, so each completion overwrites the previous values. The three existing tests already do this by only setting the one that matters.
- **c. New reset step** (script task before the merge) that sets the flags to false.

**Consequence.** a and b leave the BPMN unchanged. c adds a node and a new generator capability.

**Recommended: b.** It needs no generator change and matches what `allocationMainScreen.outputs` already lists.

**Supplement edit (b):** reword `AL-3` to state the contract: "the main-screen task returns all four flags on every completion".
**Supported today:** a and b, yes. c, **no**: there is no mechanism for a node the document does not describe, other than the synthesized gateways.

---

## AL-4: Write nodes as service tasks

**Evidence**
- D03 ¶124 and ¶129 give no task type.
- D03 ¶125: `Saves pv!assignedEmployees to NSSOL Map Employees record type`; ¶130 likewise for subcontractors.
- The current model uses `nssol.service.MapEmployeeStore.save` and `MapSubcontractorStore.save`, which are test doubles.

**Options**
- **a. Accept service tasks (current).**
- **b. Use another task type** (for example script task). Say which.

**Recommended: a.** "Saves … to a record type" is a service call. The real write semantics (insert vs upsert) remain open, as for SR-4.

**Supplement edit:** none, or reword `AL-4` as accepted.
**Supported today:** yes.

---

## AL-5: Dynamic process name

**Evidence**
- D03 ¶49: `Process Name Template | "NSSOL Allocations - " & pv!projectInfo[projectName]`.
- `projectInfo` is a `ProjectRegistration`, which has `projectName`.

**Options**
- **a. Static BPMN name (current).**
- **b. `descriptionTemplate`**, emitted as `customDescription` metadata.

**Consequence.** With b, each instance gets a readable name such as "NSSOL Allocations - Test Tower Construction". The `#{var}` reference is checked against the process variables at extraction time.

**Recommended: b.**

**Supplement edit (b):** add to `design`:
```json
"process": {"descriptionTemplate": "NSSOL Allocations - #{projectInfo.projectName}"}
```
and mark `AL-5` resolved.
**Supported today:** yes.

---

## AL-6: Default `projectId = 3`

**Evidence**
- D03 ¶61: `projectInfo | NSSOL Projects record | Yes | Yes | projectId = 3 (default for dev)`. The columns are Parameter, Required, Default (D03 ¶59).
- D07 ¶215: "Default project ID = 3 in Allocations process PV | Medium | Replace hardcoded default with contextual project ID".

**Options**
- **a. Do not carry the default (current).** `projectInfo` is `required: true`, so the caller must pass it.
- **b. Keep it in tests only.** Already true: every test starts with `projectId: 3`.
- **c. Carry it into the spec as a default.**

**Recommended: a** (with b as it stands). D07 flags the hardcoded value as a risk to replace.

**Supplement edit:** none. Reword `AL-6` as resolved, citing D07 ¶215.
**Supported today:** yes.

---

## AL-7: Target-design proposals

**What is proposed:** class names (`ProjectRegistration` reused for NSSOL Projects; `Employee`, `Subcontractor`, `MapEmployee`, `MapSubcontractor`), `DateTime` as `java.time.LocalDateTime`, lists as `java.util.List`, and the outputs of every user task (flags and lists).

**Options**
- **a. Approve as written.**
- **b. Change some of them.** Tell me which.

**Recommended: a.** The outputs are cited in the `support` entries of each node.

**Supplement edit (a):** reword `AL-7` as approved.
**Supported today:** yes.

---

## AL-8: Search-screen cancel is not enforced

**Evidence**
- D04 ¶251: `Cancel → returns without selection (sets empCancel=true)`.
- The return flow from each search screen to the merge has no condition.

**Options**
- **a. Accept.** The search form must leave `selectedEmployees` empty when it sets `empCancel`. The process does not check it.
- **b. Enforce in the process.** A gateway after each search screen that clears the selection on cancel.

**Recommended: a.** Same limit as AL-3; b needs a new node and a way to clear variables.

**Supplement edit (a):** reword `AL-8` as accepted, noting that the form carries the rule.
**Supported today:** a yes, b **no**.

---

## After you decide

1. I apply the edits above to `extractor/supplements/allocations.json`, regenerate `generator/specs/allocations.json`, and run extractor, generator and reader tests plus Maven on the Allocations project.
2. Items marked **no** under "Supported today" need new generator or extractor work first. I will scope that before starting.
