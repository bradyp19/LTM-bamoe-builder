"""Text flow diagrams (box-drawing, inside a code fence) -> nodes and edges.

The diagrams below are verbatim copies of D03 ¶76–133 (Allocations) and
D03 ¶180–189 (Language Toggle); paragraph indexes are kept so anchors can be
asserted.
"""

from ltm_reader.docx_extract import Paragraph

from ltm_extract.flow_text import parse_text_flow

ALLOCATIONS = """START
  │   Receives: projectInfo (required)
  │
  ▼
[User Task: Allocation Main Screen]
  │   Interface: NSSOL_SEC_Allocation
  │   Displays:
  │     - Project information panel (NSSOL_Project_Info)
  │     - Existing employee allocations grid (from NSSOL Map Employees)
  │     - Existing subcontractor allocations grid (from NSSOL Map Subcontractors)
  │     - Employee headcount totals (Jan–Dec)
  │     - Subcontractor headcount totals (Jan–Dec)
  │     - "Add Employees" button → sets isAddEmployee=true
  │     - "Add Subcontractors" button → sets isAddSubcontractor=true
  │     - "Assign" button → sets isAssign=true
  │     - "Cancel" button → sets allocationCancel=true
  │
  ├──[allocationCancel = true]──▶ END
  │
  ├──[isAddEmployee = true]──▶
  │     │
  │     ▼
  │   [User Task: Employee Search Screen]
  │     Interface: NSSOL_GRID_Employee_Search_Screen
  │     User searches, filters, and multi-selects employees
  │     Selected employees stored in pv!selectedEmployees
  │     ├──[empCancel = true]──▶ back to Allocation Main Screen
  │     └──[confirm]──▶ back to Allocation Main Screen with selectedEmployees populated
  │
  ├──[isAddSubcontractor = true]──▶
  │     │
  │     ▼
  │   [User Task: Subcontractor Search Screen]
  │     Interface: NSSOL_GRID_Subcontractor_Search_Screen
  │     User searches, filters, and multi-selects subcontractors
  │     Selected subcontractors stored in pv!selectedSubcontractors
  │     ├──[SubconCancel = true]──▶ back to Allocation Main Screen
  │     └──[confirm]──▶ back to Allocation Main Screen with selectedSubcontractors populated
  │
  └──[isAssign = true]──▶
        │
        ▼
     [User Task: Allocation Confirmation]
        │   Interface: NSSOL_FRM_Allocation_Confirmation
        │   Shows project name and confirmation message
        │   User clicks Submit to confirm
        │
        ▼
     [Write Map Employee Records]
        │   Saves pv!assignedEmployees to NSSOL Map Employees record type
        │   Each record includes: employee data, projectId, createdBy, createdOn, updatedBy, updatedOn, isActive=true
        │
        ▼
     [Write Map Subcontractor Records]
        │   Saves pv!assignedSubcontractors to NSSOL Map Subcontractors record type
        │
        ▼
       END"""

TOGGLE = """START
  │   Receives: toggleValue (boolean)
  │
  ▼
[Script Task / Service Task: Update Constant]
  │   Updates NSSOL_BOOL_LANGUAGE_TOGGLE constant
  │   Sets constant value = pv!toggleValue
  │
  ▼
END"""


def paras(text, start=0):
    return [Paragraph(index=start + i, style="PlainText", text=line)
            for i, line in enumerate(text.split("\n"))]


def edges(graph):
    return [(e.source, e.target, e.label) for e in graph.edges]


class TestAllocationsDiagram:
    def setup_method(self):
        self.g = parse_text_flow(paras(ALLOCATIONS, start=76))

    def test_no_diagnostics(self):
        assert self.g.diagnostics == []

    def test_nodes_in_document_order(self):
        assert [n.key for n in self.g.nodes] == [
            "start", "allocationMainScreen", "end1", "employeeSearchScreen",
            "subcontractorSearchScreen", "allocationConfirmation",
            "writeMapEmployeeRecords", "writeMapSubcontractorRecords", "end2"]

    def test_node_kinds_come_only_from_the_declared_prefix(self):
        kinds = {n.key: n.kind for n in self.g.nodes}
        assert kinds["start"] == "start"
        assert kinds["end1"] == kinds["end2"] == "end"
        assert kinds["allocationMainScreen"] == "userTask"
        assert kinds["allocationConfirmation"] == "userTask"
        # "[Write Map Employee Records]" declares no task type: never guessed.
        assert kinds["writeMapEmployeeRecords"] is None
        assert kinds["writeMapSubcontractorRecords"] is None

    def test_names_and_interfaces(self):
        nodes = {n.key: n for n in self.g.nodes}
        assert nodes["allocationMainScreen"].name == "Allocation Main Screen"
        assert nodes["allocationMainScreen"].interface == "NSSOL_SEC_Allocation"
        assert nodes["employeeSearchScreen"].interface == "NSSOL_GRID_Employee_Search_Screen"
        assert nodes["allocationConfirmation"].interface == "NSSOL_FRM_Allocation_Confirmation"
        assert nodes["writeMapEmployeeRecords"].interface is None

    def test_edges(self):
        assert edges(self.g) == [
            ("start", "allocationMainScreen", None),
            ("allocationMainScreen", "end1", "allocationCancel = true"),
            ("allocationMainScreen", "employeeSearchScreen", "isAddEmployee = true"),
            ("employeeSearchScreen", "allocationMainScreen", "empCancel = true"),
            ("employeeSearchScreen", "allocationMainScreen", "confirm"),
            ("allocationMainScreen", "subcontractorSearchScreen", "isAddSubcontractor = true"),
            ("subcontractorSearchScreen", "allocationMainScreen", "SubconCancel = true"),
            ("subcontractorSearchScreen", "allocationMainScreen", "confirm"),
            ("allocationMainScreen", "allocationConfirmation", "isAssign = true"),
            ("allocationConfirmation", "writeMapEmployeeRecords", None),
            ("writeMapEmployeeRecords", "writeMapSubcontractorRecords", None),
            ("writeMapSubcontractorRecords", "end2", None),
        ]

    def test_anchors_are_source_paragraphs(self):
        nodes = {n.key: n for n in self.g.nodes}
        main = nodes["allocationMainScreen"]
        assert (main.start_index, main.end_index) == (80, 91)
        assert (nodes["start"].start_index, nodes["start"].end_index) == (76, 77)
        assert nodes["end1"].start_index == 93
        assert nodes["end2"].start_index == 133
        by_label = {e.label: e for e in self.g.edges if e.label}
        assert by_label["allocationCancel = true"].paragraph_index == 93
        assert by_label["isAssign = true"].paragraph_index == 115

    def test_annotations_kept_verbatim(self):
        nodes = {n.key: n for n in self.g.nodes}
        texts = [a.text for a in nodes["writeMapEmployeeRecords"].annotations]
        assert texts[0] == "Saves pv!assignedEmployees to NSSOL Map Employees record type"
        assert nodes["start"].annotations[0].text == "Receives: projectInfo (required)"

    def test_back_reference_remainder_kept_as_note(self):
        e = next(e for e in self.g.edges
                 if e.source == "employeeSearchScreen" and e.label == "confirm")
        assert e.note == "with selectedEmployees populated"


class TestToggleDiagram:
    def test_linear_flow(self):
        g = parse_text_flow(paras(TOGGLE, start=180))
        assert [n.key for n in g.nodes] == ["start", "updateConstant", "end"]
        assert edges(g) == [("start", "updateConstant", None),
                            ("updateConstant", "end", None)]
        assert g.diagnostics == []

    def test_ambiguous_declared_type_is_not_resolved(self):
        g = parse_text_flow(paras(TOGGLE, start=180))
        node = g.nodes[1]
        assert node.name == "Update Constant"
        assert node.declared_type == "Script Task / Service Task"
        assert node.kind is None


class TestDiagnostics:
    def codes(self, text):
        return [d.code for d in parse_text_flow(paras(text)).diagnostics]

    def test_unresolvable_back_reference_is_reported_not_guessed(self):
        text = ("START\n  │\n  ▼\n[User Task: Review]\n"
                "  ├──[redo = true]──▶ back to Some Other Screen\n"
                "  └──[done = true]──▶ END")
        g = parse_text_flow(paras(text))
        assert [d.code for d in g.diagnostics] == ["flow-unresolved-target"]
        assert g.diagnostics[0].paragraph_index == 4
        assert ("review", "end", "done = true") in edges(g)
        assert all(e.label != "redo = true" for e in g.edges)

    def test_sequence_without_arrow_is_flagged(self):
        assert self.codes("START\n[User Task: Review]\n  ▼\nEND") == ["flow-implicit-sequence"]

    def test_branch_without_target_is_flagged(self):
        text = "START\n  ▼\n[User Task: Review]\n  ├──[a = true]──▶\n  └──[b = true]──▶ END"
        assert self.codes(text) == ["flow-dangling-branch"]

    def test_branch_before_any_node_is_flagged(self):
        assert "flow-orphan-branch" in self.codes("  ├──[a = true]──▶ END")

    def test_unrecognised_inline_target_is_flagged(self):
        text = "START\n  ▼\n[User Task: Review]\n  └──[a = true]──▶ somewhere else"
        assert self.codes(text) == ["flow-unresolved-target"]

    def test_duplicate_node_names_get_distinct_keys(self):
        text = "START\n  ▼\n[User Task: Review]\n  ▼\n[User Task: Review]\n  ▼\nEND"
        g = parse_text_flow(paras(text))
        assert [n.key for n in g.nodes] == ["start", "review", "review2", "end"]
