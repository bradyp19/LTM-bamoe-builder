"""Allocation conflict rulings that need support in the extractor:
design.flowRules (gateway default flow / flow priority) and design.nodes.<id>.candidateGroups.

Nothing here is part of the committed allocations supplement; each test applies one
ruling to a copy of it.
"""

import json

import pytest

from conftest import SPECS, SUPPLEMENTS
from ltm_extract import ExtractionError, build_spec, load_supplement

GATEWAY = "allocationMainScreenGateway"


@pytest.fixture
def supplement():
    return load_supplement(SUPPLEMENTS / "allocations.json")


def flow(spec, source, target):
    return next(f for f in spec["flows"] if f["from"] == source and f["to"] == target)


def test_baseline_is_unchanged_by_the_new_keys(real_docset, supplement):
    on_disk = json.loads((SPECS / "allocations.json").read_text(encoding="utf-8"))
    assert build_spec(real_docset, supplement).spec == on_disk


class TestFlowRules:
    def test_default_flow_has_no_condition(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"default": True}}
        f = flow(build_spec(real_docset, supplement).spec, GATEWAY, "end1")
        assert f["default"] is True
        assert "condition" not in f
        assert f["name"] == "allocationCancel = true"

    def test_other_branches_keep_their_conditions(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"default": True}}
        spec = build_spec(real_docset, supplement).spec
        assert flow(spec, GATEWAY, "allocationConfirmation")["condition"].startswith("return isAssign")

    def test_priorities(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {
            f"{GATEWAY}->end1": {"priority": 1},
            f"{GATEWAY}->allocationConfirmation": {"priority": 2},
            f"{GATEWAY}->employeeSearchScreen": {"priority": 3},
            f"{GATEWAY}->subcontractorSearchScreen": {"priority": 4},
        }
        spec = build_spec(real_docset, supplement).spec
        assert [flow(spec, GATEWAY, t)["priority"] for t in (
            "end1", "allocationConfirmation", "employeeSearchScreen",
            "subcontractorSearchScreen")] == [1, 2, 3, 4]

    def test_priority_on_only_some_branches_is_an_error(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"priority": 1}}
        with pytest.raises(ExtractionError, match="priorities must be given for every branch"):
            build_spec(real_docset, supplement)

    def test_rule_for_a_flow_that_does_not_exist_is_an_error(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->nowhere": {"default": True}}
        with pytest.raises(ExtractionError, match="flowRules.*nowhere.*no such sequence flow"):
            build_spec(real_docset, supplement)

    def test_rule_for_a_flow_that_does_not_leave_a_branching_gateway_is_an_error(
            self, real_docset, supplement):
        supplement["design"]["flowRules"] = {"allocationMainScreen->" + GATEWAY: {"default": True}}
        with pytest.raises(ExtractionError, match="does not leave a branching gateway"):
            build_spec(real_docset, supplement)

    def test_two_defaults_on_one_gateway_are_an_error(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"default": True},
                                              f"{GATEWAY}->allocationConfirmation": {"default": True}}
        with pytest.raises(ExtractionError, match="more than one default"):
            build_spec(real_docset, supplement)

    def test_unknown_rule_key_is_an_error(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"weight": 3}}
        with pytest.raises(ExtractionError, match="weight.*not allowed"):
            build_spec(real_docset, supplement)

    @pytest.mark.parametrize("priority", [0, -1, "1", 1.5, True])
    def test_priority_must_be_a_positive_integer(self, real_docset, supplement, priority):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"priority": priority}}
        with pytest.raises(ExtractionError, match="priority must be a positive integer"):
            build_spec(real_docset, supplement)

    def test_default_flow_cannot_also_be_given_a_condition(self, real_docset, supplement):
        supplement["design"]["flowRules"] = {f"{GATEWAY}->end1": {"default": True}}
        supplement["design"]["conditions"] = {f"{GATEWAY}->end1": "return true;"}
        with pytest.raises(ExtractionError, match="default flow.*condition"):
            build_spec(real_docset, supplement)


class TestCandidateGroups:
    def test_groups_are_carried_on_the_user_task(self, real_docset, supplement):
        supplement["design"]["nodes"]["allocationMainScreen"]["candidateGroups"] = ["NP Users"]
        spec = build_spec(real_docset, supplement).spec
        task = next(n for n in spec["nodes"] if n["id"] == "allocationMainScreen")
        assert task["candidateGroups"] == ["NP Users"]
        other = next(n for n in spec["nodes"] if n["id"] == "employeeSearchScreen")
        assert "candidateGroups" not in other

    def test_service_task_cannot_have_groups(self, real_docset, supplement):
        supplement["design"]["nodes"]["writeMapEmployeeRecords"]["candidateGroups"] = ["NP Users"]
        with pytest.raises(ExtractionError, match="candidateGroups.*not a user task"):
            build_spec(real_docset, supplement)

    @pytest.mark.parametrize("groups", [[], "NP Users", [""], ["a,b"], [1]])
    def test_groups_must_be_a_list_of_names_without_commas(self, real_docset, supplement, groups):
        supplement["design"]["nodes"]["allocationMainScreen"]["candidateGroups"] = groups
        with pytest.raises(ExtractionError, match="candidateGroups must be a non-empty list"):
            build_spec(real_docset, supplement)
