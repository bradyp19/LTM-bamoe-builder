"""One test per refusal: what the extractor will not accept or invent.

Runs on a made-up application, so it needs no LTM originals.
"""

import copy
import hashlib
import json

import pytest

from ltm_extract import DocSet, ExtractionError, build_spec
from ltm_extract.__main__ import main
from test_synthetic import (DATA, IMAGE_BYTES, INTERFACES, WORKFLOW, approve_supplement,
                            ship_supplement)

SHA = hashlib.sha256(IMAGE_BYTES).hexdigest()
NULL_NOTE = "Conditions read a null flag as not true"


@pytest.fixture
def docset(make_docx):
    make_docx("03_Workflow.docx", WORKFLOW, image_bytes=IMAGE_BYTES)
    make_docx("04_Interfaces.docx", INTERFACES)
    f = make_docx("05_Data.docx", DATA)
    return DocSet.load(f.parent)


def problems(docset, supplement):
    with pytest.raises(ExtractionError) as exc:
        build_spec(docset, supplement)
    return exc.value.problems


def refused(docset, supplement, expected):
    found = problems(docset, supplement)
    assert any(expected in p for p in found), found
    return found


def flow_docset(make_docx, flow, workflow=WORKFLOW, data=DATA):
    """The ACME documents with Approve Order's diagram replaced."""
    lines = list(workflow[:18]) + flow.split("\n") + list(workflow[33:])
    make_docx("03_Workflow.docx", lines, image_bytes=IMAGE_BYTES)
    make_docx("04_Interfaces.docx", INTERFACES)
    f = make_docx("05_Data.docx", data)
    return DocSet.load(f.parent)


def renamed(name):
    return [l.replace("ACME Approve Order", name) if isinstance(l, str) else l for l in WORKFLOW]


def two_way(first, second):
    return ("START\n  ▼\n[User Task: Check]\n"
            f"  ├──[{first}]──▶ END\n  └──[{second}]──▶ END")


def check_supplement(**design):
    return {"process": "ACME Approve Order",
            "design": {"typeMap": {"DateTime": "java.time.OffsetDateTime"},
                       "nodes": {"check": {"outputs": ["approved"]}}, **design}}


def set_path(supplement, path, value):
    target = supplement
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return supplement


SHAPE_CASES = [
    (("variables",), [], "supplement key 'variables': is not allowed"),
    (("process",), 7, "process: must be a non-empty string"),
    (("design",), [], "design: must be an object"),
    (("design", "junk"), 1, "design.junk: is not allowed"),
    (("design", "nodes"), [], "design.nodes: must be an object"),
    (("design", "nodes", "reviewOrder"), None, "design.nodes.reviewOrder: must be an object"),
    (("design", "nodes", "reviewOrder", "assignee"), "x",
     "design.nodes.reviewOrder.assignee: is not allowed"),
    (("design", "nodes", "reviewOrder", "type"), "xor", "design.nodes.reviewOrder.type: must be"),
    (("design", "nodes", "reviewOrder", "outputs"), "approved",
     "design.nodes.reviewOrder.outputs: must be a list"),
    (("design", "nodes", "reviewOrder", "outputs"), [3],
     "design.nodes.reviewOrder.outputs[0]: must be a variable name"),
    (("design", "nodes", "reviewOrder", "notes"), 5, "notes: must be a non-empty string"),
    (("design", "nodes", "reviewOrder", "support"), "D03 ¶12", "support: must be a list"),
    (("design", "nodes", "reviewOrder", "support"), ["D03 ¶12"], "support[0]: must be an object"),
    (("design", "nodes", "reviewOrder", "support"), [{"cite": "D03 ¶12", "quote": "e"}],
     "is too short to support anything"),
    (("design", "nodes", "saveOrder", "service"), "acme.service.OrderStore",
     "service: must be an object"),
    (("design", "nodes", "saveOrder", "service", "class"), "OrderStore",
     "service.class: must be a fully qualified Java class name"),
    (("design", "nodes", "saveOrder", "service", "operation"), "do it",
     "service.operation: must be a Java method name"),
    (("design", "nodes", "saveOrder", "service", "extra"), 1, "service.extra: is not allowed"),
    (("design", "process"), "approve", "design.process: must be an object"),
    (("design", "process"), {"name": "x"}, "design.process.name: is not allowed"),
    (("design", "process"), {"id": "approve-order"}, "design.process.id: must be camelCase"),
    (("design", "process"), {"packageName": "Not A Package"},
     "design.process.packageName: must be a Java package name"),
    (("design", "models"), {"ACME Orders": "not a class"}, "must be a Java class name"),
    (("design", "typeMap"), {"Boolean": "String"}, "is a built-in mapping"),
    (("design", "typeMap"), {"DateTime": 5}, "must be a Java type name"),
    (("design", "conditions"), [], "design.conditions: must be an object"),
    (("design", "conditions"), {"a->b": 5}, "design.conditions['a->b']: must be a non-empty"),
    (("assumptions",), "none", "assumptions: must be a list"),
    (("assumptions",), [{"text": "x"}], "assumptions[0].id: is required"),
    (("assumptions",), [{"id": "T-1", "text": "x"}], "is reserved for generated items"),
    (("assumptions",), [{"id": "A", "text": "x"}, {"id": "A", "text": "y"}],
     "'A' is used more than once"),
    (("tests",), "none", "tests: must be a list"),
    (("tests",), ["x"], "tests[0]: must be an object"),
    (("tests",), [{"name": "ok"}], "tests[0].start: is required"),
    (("tests",), [{"name": "not a name!", "start": {}, "complete": {},
                   "expect": {"status": "COMPLETED", "saves": 0}}], "must be a Java method name"),
    (("tests",), [{"name": "a", "start": {}, "complete": {},
                   "expect": {"status": "WHATEVER", "saves": 0}}], "expect.status: must be one of"),
    (("tests",), [{"name": "a", "start": {}, "complete": {},
                   "expect": {"status": "COMPLETED", "saves": -1}}], "expect.saves: must be a count"),
    (("figureTranscriptions",), {}, "figureTranscriptions: must be a list"),
    (("figureTranscriptions",), [{"cite": "D03 ¶47"}], "figureTranscriptions[0].nodes: is required"),
]


class TestSupplementShape:
    @pytest.mark.parametrize("path, value, expected", SHAPE_CASES,
                             ids=[c[2] for c in SHAPE_CASES])
    def test_malformed_supplement_is_reported_not_crashed_on(self, docset, path, value, expected):
        refused(docset, set_path(approve_supplement(), path, value), expected)

    @pytest.mark.parametrize("supplement", [None, [], "x", 3])
    def test_supplement_must_be_an_object(self, docset, supplement):
        assert problems(docset, supplement) == ["supplement: must be a JSON object"]

    def test_missing_process(self, docset):
        refused(docset, {"design": {}}, "process: is required")

    def test_shape_and_citation_problems_are_reported_together(self, docset):
        supplement = set_path(approve_supplement(), ("junk",), 1)
        supplement["assumptions"] = [{"id": "A", "text": "See D09 ¶3."}]
        found = problems(docset, supplement)
        assert any("junk" in p for p in found) and any("D09" in p for p in found)

    @pytest.mark.parametrize("key, value, expected", [
        ("extra", 1, "figureTranscriptions[0].extra: is not allowed"),
        ("nodes", [{"id": "start", "type": "begin", "name": "Start"}], "nodes[0].type: must be"),
        ("nodes", [{"id": 4, "type": "start", "name": None}], "nodes[0].id: must be a non-empty"),
        ("nodes", [{"id": "s", "type": "start", "name": "S", "outputs": []}],
         "nodes[0].outputs: is not allowed"),
        ("flows", ["start->ship"], "flows[0]: must be an object"),
        ("flows", [{"from": "start", "to": "ship", "condition": "x"}],
         "flows[0].condition: is not allowed"),
    ])
    def test_transcription_shape(self, docset, key, value, expected):
        supplement = ship_supplement(SHA)
        supplement["figureTranscriptions"][0][key] = value
        refused(docset, supplement, expected)


class TestProcessAndTypes:
    def test_unknown_process(self, docset):
        refused(docset, set_path(approve_supplement(), ("process",), "ACME Nothing"),
                "no process model 'ACME Nothing' in the documents (found: ACME Approve Order")

    @pytest.mark.parametrize("name, expected", [
        ("ACME 3D Print", "process id '3DPrint' derived from"),
        ("Approve order", "no Java package can be derived"),
        ("X-RAY Review", "no Java package can be derived"),
    ])
    def test_names_that_do_not_give_java_identifiers(self, make_docx, name, expected):
        workflow = renamed(name)
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"), workflow)
        refused(docs, {**check_supplement(), "process": name}, expected)

    def test_design_can_rule_on_id_and_package(self, make_docx):
        workflow = renamed("X-RAY 3D Review")
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"), workflow)
        supplement = check_supplement(process={"id": "review3d", "packageName": "xray"})
        spec = build_spec(docs, {**supplement, "process": "X-RAY 3D Review"}).spec
        assert (spec["process"]["id"], spec["process"]["packageName"]) == ("review3d", "xray")
        assert spec["variables"][1]["type"] == "xray.model.Orders"

    def test_design_model_for_unknown_record(self, docset):
        refused(docset, set_path(approve_supplement(), ("design", "models"), {"ACME Items": "Item"}),
                "design.models: no record type 'ACME Items'")

    def test_no_variables_table(self, make_docx):
        workflow = list(WORKFLOW[:10]) + [""] * 4 + list(WORKFLOW[14:])
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"), workflow)
        found = refused(docs, check_supplement(), "no process variables table found")
        assert any("'approved' is not a declared process variable (no variables table)" in p
                   for p in found)

    @pytest.mark.parametrize("row, expected", [
        ("| `approved` | Boolean | Yes | No | again |", "'approved' is declared more than once"),
        ("| `order id` | Text | Yes | No | x |", "'order id' (D03 ¶14) is not a valid Java"),
        ("| `class` | Text | Yes | No | x |", "'class' (D03 ¶14) is not a valid Java"),
        ("| `when` | Timestamp | Yes | No | x |", "type 'Timestamp' (D03 ¶14) is neither"),
    ])
    def test_variable_rows(self, make_docx, row, expected):
        workflow = list(WORKFLOW[:14]) + [row] + list(WORKFLOW[15:])
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"), workflow)
        refused(docs, check_supplement(), expected)

    def test_two_records_mapped_to_one_class(self, make_docx):
        data = DATA + ["", "## Record Type: ACME Items", "", "### Fields", "",
                       "| Field Name | Data Type | Nullable | Description |", "|---|---|---|---|",
                       "| `itemId` | Integer | No | Key |"]
        workflow = list(WORKFLOW[:14]) + ["| `item` | ACME Items record | Yes | No | x |"] \
            + list(WORKFLOW[15:])
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"),
                           workflow, data)
        refused(docs, check_supplement(models={"ACME Items": "Orders"}),
                "record types 'ACME Orders' and 'ACME Items' both map to model class 'Orders'")

    def test_record_without_fields(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"),
                           data=DATA[:6])
        refused(docs, check_supplement(), "record type 'ACME Orders' (D05 ¶2–4) has no documented")


def approve_with(path, value):
    return set_path(approve_supplement(), ("design", "nodes") + path, value)


class TestNodeRulings:
    def test_retyping_a_declared_node(self, docset):
        supplement = approve_with(("reviewOrder",), {
            "type": "serviceTask", "inputs": ["order"], "outputs": ["order"],
            "service": {"class": "acme.service.X", "operation": "run"}})
        refused(docset, supplement, "'reviewOrder' is already userTask in the diagram")

    def test_untyped_node_needs_one_ruling_not_four_messages(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[Save Order]\n  ▼\nEND")
        supplement = check_supplement()
        supplement["design"]["nodes"] = {"saveOrder": {
            "service": {"class": "acme.service.OrderStore", "operation": "save"},
            "inputs": ["order"], "outputs": ["order"]}}
        found = problems(docs, supplement)
        assert len(found) == 1 and "design.nodes.saveOrder.type must rule on it" in found[0]

    def test_ambiguous_declared_type_needs_a_ruling(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[Script Task / Service Task: Save]\n  ▼\nEND")
        refused(docs, {"process": "ACME Approve Order"},
                "the diagram declares 'Script Task / Service Task'")

    def test_design_for_a_node_that_is_not_in_the_flow(self, docset):
        refused(docset, approve_with(("approve",), {"notes": "extra"}),
                "design.nodes.approve: the flow has no node 'approve'")

    def test_rulings_on_a_node_that_is_not_a_task(self, docset):
        refused(docset, approve_with(("start",), {"outputs": ["order"]}),
                "design.nodes.start.outputs: 'start' is a start node")

    def test_user_task_outputs_need_a_ruling(self, docset):
        supplement = approve_supplement()
        del supplement["design"]["nodes"]["reviewOrder"]
        refused(docset, supplement, "design.nodes.reviewOrder.outputs: the outputs of user task")

    def test_service_on_a_user_task(self, docset):
        refused(docset, approve_with(("reviewOrder", "service"),
                                     {"class": "acme.service.X", "operation": "run"}),
                "design.nodes.reviewOrder.service: 'reviewOrder' is a user task")

    def test_service_task_without_binding(self, docset):
        supplement = approve_supplement()
        del supplement["design"]["nodes"]["saveOrder"]["service"]
        refused(docset, supplement, "service task 'Save Order' needs a ruling on service")

    def test_service_task_takes_one_input_and_one_output(self, docset):
        refused(docset, approve_with(("saveOrder", "inputs"), ["order", "approved"]),
                "a service task takes exactly one input and one output")

    def test_rule_inputs_cannot_be_overridden(self, docset):
        refused(docset, approve_with(("reviewOrder", "inputs"), ["approved"]),
                "come from the rule inputs and cannot be overridden")

    def test_undeclared_variable(self, docset):
        refused(docset, approve_with(("reviewOrder", "outputs"), ["aproved"]),
                "reviewOrder: 'aproved' is not a declared process variable (D03 ¶10–13)")

    def test_node_named_like_a_variable(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[User Task: Approved]\n  ▼\nEND")
        refused(docs, {"process": "ACME Approve Order",
                       "design": {"nodes": {"approved": {"outputs": []}}}},
                "node id 'approved' is also a process variable name")

    def test_parser_diagnostics_stop_the_build(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[User Task: Check]\n"
                                      "  ├──[approved = true]──▶ back to Nowhere\n"
                                      "  └──[approved = false]──▶ END")
        refused(docs, check_supplement(), "D03 ¶21: branch [approved = true] points at")

    def test_unlabelled_branch_is_kept_and_needs_a_condition(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[User Task: Check]\n"
                                      "  ├──▶ END\n  └──[approved = true]──▶ END")
        refused(docs, check_supplement(),
                "flow checkGateway->end1 (D03 ¶21): no condition can be derived")


class TestConditions:
    def spec(self, make_docx, first, second, **design):
        return build_spec(flow_docset(make_docx, two_way(first, second)),
                          check_supplement(**design)).spec

    def test_exact_labels_are_derived(self, make_docx):
        spec = self.spec(make_docx, "pv!approved = true", "No / approved=false")
        assert [f.get("condition") for f in spec["flows"][2:]] == [
            "return approved != null && approved;", "return approved == null || !approved;"]
        assert NULL_NOTE in spec["assumptions"][-1]["text"]

    @pytest.mark.parametrize("label", [
        "NOT approved = true", "unless approved = true", "order.approved = true",
        "approved = true and order.total > 1000", "confirm", "order = true"])
    def test_anything_else_needs_a_ruling(self, make_docx, label):
        docs = flow_docset(make_docx, two_way(label, "approved = false"))
        refused(docs, check_supplement(),
                f"the label {label!r} is not exactly '<Boolean variable> = true|false'")

    def test_ruling_is_used_and_disclosed(self, make_docx):
        spec = self.spec(make_docx, "confirm", "approved = false",
                         conditions={"checkGateway->end1": "return approved != null && approved;"})
        assert spec["flows"][2]["condition"] == "return approved != null && approved;"
        texts = [a["text"] for a in spec["assumptions"]]
        assert any("flow checkGateway->end1 (D03 ¶21) is a design ruling" in t for t in texts)

    def test_ruling_cannot_replace_a_documented_condition(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"))
        refused(docs, check_supplement(conditions={"checkGateway->end1": "return true;"}),
                "comes from the label 'approved = true' and cannot be overridden")

    def test_ruling_on_a_flow_that_does_not_leave_a_gateway(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"))
        refused(docs, check_supplement(conditions={"start->check": "return true;"}),
                "design.conditions['start->check']: that flow does not leave a gateway")

    def test_ruling_on_a_flow_that_does_not_exist(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"))
        refused(docs, check_supplement(conditions={"a->b": "return true;"}),
                "design.conditions['a->b']: the flow has no such sequence flow")

    def test_two_flows_with_the_same_condition(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = true"))
        refused(docs, check_supplement(), "leave gateway 'checkGateway' with the same condition")

    def test_merged_branches_on_a_gateway_need_a_ruling(self, make_docx):
        flow = ("START\n  ▼\n[User Task: Check]\n  ▼\n[User Task: Fix]\n"
                "  ├──[approved = true]──▶ back to Check\n  ├──[retry]──▶ back to Check\n"
                "  └──[approved = false]──▶ END")
        supplement = check_supplement()
        supplement["design"]["nodes"]["fix"] = {"outputs": ["approved"]}
        docs = flow_docset(make_docx, flow)
        refused(docs, supplement, "it merges the branches 'approved = true' and 'retry'")
        supplement["design"]["conditions"] = {
            "fixGateway->checkMerge": "return approved != null && approved;"}
        texts = [a["text"] for a in build_spec(docs, supplement).spec["assumptions"]]
        assert any("emitted as one flow whose condition is a design ruling" in t for t in texts)
        assert not any("with no condition" in t for t in texts)

    def test_guard_on_an_only_branch_is_disclosed(self, make_docx):
        docs = flow_docset(make_docx, "START\n  ▼\n[User Task: Check]\n"
                                      "  └──[approved = true]──▶ END")
        result = build_spec(docs, check_supplement())
        assert result.spec["flows"][1] == {"from": "check", "to": "end", "name": "approved = true"}
        assert "the guard is not enforced" in result.spec["assumptions"][0]["text"]
        assert "guard-not-enforced" in [d.code for d in result.diagnostics]

    def test_condition_on_a_variable_no_task_sets_is_reported(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"))
        supplement = check_supplement()
        supplement["design"]["nodes"]["check"]["outputs"] = []
        codes = [d.code for d in build_spec(docs, supplement).diagnostics]
        assert codes.count("condition-variable-never-set") == 2


def ship(nodes=None, flows=None, **design_nodes):
    supplement = ship_supplement(SHA)
    t = supplement["figureTranscriptions"][0]
    t["nodes"] = t["nodes"] + (nodes or [])
    if flows is not None:
        t["flows"] = flows
    supplement["design"]["nodes"].update(design_nodes)
    return supplement


def node(node_id, node_type="userTask"):
    return {"id": node_id, "type": node_type, "name": node_id.title()}


def flow(source, target, label=None):
    return {"from": source, "to": target, **({"label": label} if label else {})}


BASE = [flow("start", "ship"), flow("ship", "done")]

STRUCTURE_CASES = [
    ([], BASE + [flow("ship", "nowhere")], "flow ship->nowhere refers to unknown node 'nowhere'"),
    ([], BASE + [flow("start", "ship")], "more than one flow start->ship"),
    ([node("s2", "start")], BASE + [flow("s2", "ship")], "the flow needs exactly one start node"),
    ([], BASE + [flow("ship", "start")], "start node 'start' has an incoming flow"),
    ([node("x")], BASE + [flow("x", "done")], "node 'x' has no incoming flow"),
    ([], BASE + [flow("done", "ship")], "end node 'done' has an outgoing flow"),
    ([node("x")], BASE + [flow("ship", "x")], "node 'x' has no outgoing flow"),
    ([node("d2", "end")], BASE + [flow("ship", "d2")], "node 'ship' branches but is not a gateway"),
    ([node("g", "xor")], [flow("start", "g"), flow("g", "ship"), flow("ship", "done")],
     "gateway 'g' has fewer than two outgoing flows"),
    ([node("a"), node("b")], BASE + [flow("a", "b"), flow("b", "a")],
     "node 'a' cannot be reached from the start"),
    ([node("g", "xor"), node("loop")],
     [flow("start", "g"), flow("g", "ship"), flow("g", "loop"), flow("loop", "loop"),
      flow("ship", "done")], "node 'loop' can never reach an end"),
    ([node("ship", "end")], BASE, "node id 'ship' is used more than once"),
    ([node("bad id")], BASE + [flow("ship", "bad id")], "node id 'bad id' is not a valid identifier"),
]


class TestTranscribedFlow:
    @pytest.mark.parametrize("nodes, flows, expected", STRUCTURE_CASES,
                             ids=[c[2] for c in STRUCTURE_CASES])
    def test_structure(self, docset, nodes, flows, expected):
        refused(docset, ship(nodes, flows), expected)

    def test_flow_without_an_end(self, docset):
        supplement = ship_supplement(SHA)
        t = supplement["figureTranscriptions"][0]
        t["nodes"], t["flows"] = t["nodes"][:2], [flow("start", "ship"), flow("ship", "ship")]
        refused(docset, supplement, "the flow has no end node")

    def test_transcription_for_another_paragraph(self, docset):
        supplement = ship_supplement(SHA)
        supplement["figureTranscriptions"][0]["cite"] = "D03 ¶12"
        refused(docset, supplement, "D03 ¶12 is not the flow figure of 'ACME Ship Order' (D03 ¶47)")

    def test_two_transcriptions_of_one_figure(self, docset):
        supplement = ship_supplement(SHA)
        supplement["figureTranscriptions"].append(
            copy.deepcopy(supplement["figureTranscriptions"][0]))
        refused(docset, supplement, "2 transcriptions of the same figure; nothing was picked")

    def test_transcription_of_another_image(self, docset):
        supplement = ship_supplement(SHA)
        supplement["figureTranscriptions"][0]["image"] = "media/image9.png"
        refused(docset, supplement, "transcription is of 'media/image9.png'")

    def test_transcribed_interface_must_be_documented(self, docset):
        nodes = [{**node("review"), "interface": "ACME_FRM_Missing"}]
        refused(docset, ship(nodes, BASE), "names interface 'ACME_FRM_Missing', which the documents")

    def test_transcription_is_not_used_for_a_text_flow(self, docset):
        supplement = approve_supplement()
        supplement["figureTranscriptions"] = ship_supplement(SHA)["figureTranscriptions"]
        refused(docset, supplement, "is a text diagram (D03 ¶17–33); a transcription is not used")

    def test_transcribed_inputs_that_differ_from_rule_inputs_are_reported(self, docset):
        review = {**node("review"), "interface": "ACME_FRM_Review", "inputs": []}
        supplement = ship([review], [flow("start", "review"), flow("review", "ship"),
                                     flow("ship", "done")], review={"outputs": ["order"]})
        result = build_spec(docset, supplement)
        message = next(d.message for d in result.diagnostics
                       if d.code == "inputs-differ-from-rule-inputs")
        assert "gives inputs none; the rule inputs at D04 ¶6–10 are order." in message
        assert result.spec["assumptions"] == []  # nothing is added to a transcribed spec


class TestClaims:
    def with_assumption(self, **assumption):
        supplement = approve_supplement()
        supplement["assumptions"] = [{"id": "A-1", **assumption}]
        return supplement

    def test_cited_statement_needs_a_quote_from_the_paragraph(self, docset):
        refused(docset, self.with_assumption(text="Reviewers are managers (D03 ¶12)."),
                "assumption A-1: D03 ¶12 is cited without a supporting quote from it")

    def test_quote_must_be_in_the_cited_paragraph(self, docset):
        supplement = self.with_assumption(
            text="Reviewers are managers (D03 ¶12).",
            support=[{"cite": "D03 ¶12", "quote": "assigned to managers"}])
        refused(docset, supplement, "D03 ¶12 does not contain the quoted support")

    def test_supported_statement_is_accepted(self, docset):
        supplement = self.with_assumption(
            text="The decision is a Boolean (D03 ¶12).",
            support=[{"cite": "D03 ¶12", "quote": "| `approved` | Boolean |"}])
        assert build_spec(docset, supplement).spec["assumptions"][0] == {
            "id": "A-1", "text": "The decision is a Boolean (D03 ¶12)."}

    def test_node_notes_are_held_to_the_same_rule(self, docset):
        refused(docset, approve_with(("reviewOrder", "notes"), "Assigned to managers (D03 ¶21)."),
                "design.nodes.reviewOrder: D03 ¶21 is cited without a supporting quote")

    def test_references_that_are_not_paragraphs_are_reported_as_unchecked(self, docset):
        result = build_spec(docset, self.with_assumption(text="See D03 Figure 7 and D04 §3."))
        notes = [d.message for d in result.diagnostics if d.code == "unverifiable-reference"]
        assert len(notes) == 2 and "'Figure 7'" in notes[0]

    def test_uncited_statement_needs_no_support(self, docset):
        build_spec(docset, self.with_assumption(text="No assignee is documented."))


class TestScenarios:
    def scenario(self, **start):
        supplement = approve_supplement()
        supplement["tests"] = [{"name": "approves", "start": start, "complete": {},
                                "expect": {"status": "COMPLETED", "saves": 1}}]
        return supplement

    def test_undeclared_variable(self, docset):
        refused(docset, self.scenario(aproved=True),
                "test approves: 'aproved' is not a declared process variable")

    def test_unknown_model_field(self, docset):
        refused(docset, self.scenario(order={"orderNo": 1}),
                "test approves: Orders has no field 'orderNo'")

    @pytest.mark.parametrize("start, expected", [
        ({"approved": "yes"}, "start.approved must be a Boolean value, not 'yes'"),
        ({"order": "x"}, "start.order must be an object of Orders fields"),
        ({"order": {"orderId": "7"}}, "start.order.orderId must be a Integer value, not '7'"),
        ({"order": {"orderId": True}}, "start.order.orderId must be a Integer value, not True"),
        ({"order": {"total": 1.5}}, "start.order.total is a java.math.BigDecimal; scenarios can"),
    ])
    def test_values_must_be_literals_the_generator_can_emit(self, docset, start, expected):
        refused(docset, self.scenario(**start), expected)

    def test_valid_scenario_is_passed_through(self, docset):
        supplement = self.scenario(approved=True, order={"orderId": 7})
        assert build_spec(docset, supplement).spec["tests"] == supplement["tests"]

    def test_no_scenarios_is_reported(self, docset):
        codes = [d.code for d in build_spec(docset, approve_supplement()).diagnostics]
        assert "no-test-scenarios" in codes


class TestWhatIsNotCarried:
    def test_unconsumed_table_content_is_reported(self, docset):
        notes = [d.message for d in build_spec(docset, approve_supplement()).diagnostics
                 if d.code == "not-carried"]
        assert notes == [
            "process attributes (UUID) at D03 ¶6 are not carried into the spec",
            "variable columns Parameter, Description (D03 ¶10–13) are not carried into the spec"]


class TestCombinedBuildRegressions:
    """Keep the combined branch's newer contracts while hardening validation."""

    def test_start_only_scenario_survives(self, docset):
        supplement = ship_supplement(SHA)
        supplement["tests"] = [{
            "name": "ships", "start": {"order": {"orderId": 7}}, "steps": [],
            "expect": {"status": "COMPLETED", "saves": {"Shipper": 1}}}]
        assert build_spec(docset, supplement).spec["tests"] == supplement["tests"]

    def test_multi_step_shape_checks_task_and_scalar_value(self, docset):
        supplement = approve_supplement()
        supplement["tests"] = [{
            "name": "approves", "start": {"order": {"orderId": 7}}, "steps": [
                {"task": "reviewOrder", "complete": {"approved": True}}],
            "expect": {"status": "COMPLETED", "saves": {"OrderStore": 1}}}]
        assert build_spec(docset, supplement).spec["tests"] == supplement["tests"]
        supplement["tests"][0]["steps"][0]["complete"]["approved"] = "yes"
        refused(docset, supplement, "step 1.approved must be a Boolean value")

    def test_routing_and_assignment_are_preserved(self, make_docx):
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"))
        supplement = check_supplement(
            process={"descriptionTemplate": "Order #{order.orderId}"},
            flowRules={"checkGateway->end2": {"default": True},
                       "checkGateway->end1": {"priority": 1}})
        supplement["design"]["nodes"]["check"]["candidateGroups"] = ["Reviewers"]
        spec = build_spec(docs, supplement).spec
        assert spec["process"]["descriptionTemplate"] == "Order #{order.orderId}"
        assert next(n for n in spec["nodes"] if n["id"] == "check")["candidateGroups"] == ["Reviewers"]
        assert spec["flows"][2]["priority"] == 1
        assert spec["flows"][3]["default"] is True
        assert "condition" not in spec["flows"][3]
        assert any("default by design ruling" in a["text"] for a in spec["assumptions"])

    @pytest.mark.parametrize("value", [[], {}, [None]])
    def test_unhashable_enum_values_report_extraction_errors(self, docset, value):
        supplement = ship_supplement(SHA)
        supplement["figureTranscriptions"][0]["nodes"][0]["type"] = value
        refused(docset, supplement, "nodes[0].type: must be one of")

    def test_process_id_cannot_collide_with_a_node(self, docset):
        supplement = approve_supplement()
        supplement["design"]["process"] = {"id": "reviewOrder"}
        refused(docset, supplement, "process id 'reviewOrder' is also a node or variable id")

    def test_typed_list_values_are_checked(self, make_docx):
        workflow = list(WORKFLOW)
        workflow[13] = "| `order` | ACME Orders list | Yes | No | Many orders |"
        docs = flow_docset(make_docx, two_way("approved = true", "approved = false"), workflow)
        supplement = check_supplement()
        supplement["tests"] = [{
            "name": "checks", "start": {"order": [{"orderId": 7}]},
            "steps": [{"task": "check", "complete": {"approved": True}}],
            "expect": {"status": "COMPLETED", "saves": {}}}]
        assert build_spec(docs, supplement).spec["variables"][1]["elementType"] == "acme.model.Orders"
        supplement["tests"][0]["start"]["order"] = [None]
        refused(docs, supplement, "start.order[0] must be an object of Orders fields")


class TestCli:
    def run(self, docset, tmp_path, supplement, capsys, out=None):
        path = tmp_path / "supplement.json"
        if supplement is not None:
            path.write_text(supplement if isinstance(supplement, str)
                            else json.dumps(supplement), encoding="utf-8")
        args = ["--docs", str(tmp_path), "--supplement", str(path)]
        code = main(args + (["--out", str(out)] if out else []))
        return code, capsys.readouterr()

    def test_writes_the_spec(self, docset, tmp_path, capsys):
        out = tmp_path / "spec.json"
        code, captured = self.run(docset, tmp_path, approve_supplement(), capsys, out)
        assert code == 0 and captured.out == ""
        assert json.loads(out.read_text(encoding="utf-8"))["process"]["id"] == "approveOrder"
        assert "[gateway-synthesized]" in captured.err

    def test_spec_goes_to_stdout_without_out(self, docset, tmp_path, capsys):
        code, captured = self.run(docset, tmp_path, approve_supplement(), capsys)
        assert code == 0 and json.loads(captured.out)["process"]["id"] == "approveOrder"

    @pytest.mark.parametrize("supplement, expected", [
        ("{not json", "is not valid JSON"),
        ("[1, 2]", "supplement: must be a JSON object"),
        ('{"process": "ACME Approve Order", "design": {"nodes": []}}', "design.nodes: must be"),
        (None, "cannot be read"),
    ])
    def test_failures_are_listed_and_nothing_is_written(self, docset, tmp_path, capsys,
                                                        supplement, expected):
        out = tmp_path / "spec.json"
        code, captured = self.run(docset, tmp_path, supplement, capsys, out)
        assert code == 1 and not out.exists()
        assert captured.err.startswith("No spec written:") and expected in captured.err
        assert "Traceback" not in captured.err
