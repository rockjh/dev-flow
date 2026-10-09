"""Adversarial edits retain IDs and receipts but violate frozen source facts."""
from dataclasses import replace

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.models import BusinessLabel, FlowModel, Requirement, RequirementLink
from toolkit.sequence_diagram_generator.repository import digest, stable_id
from toolkit.sequence_diagram_generator.validation import FlowValidator
from toolkit.sequence_diagram_generator.requirements import RequirementMapper
from test_boundaries import analyze
from test_workflow import context, prepare, submission


def report(scope):
    return FlowValidator().validate_model(FlowModel((scope,), "", ""))


def test_same_ids_reordered_call_and_return_fail():
    scope = analyze("python", "def flow():\n print('first')\n print('second')\n return True\n")
    assert report(scope).passed
    arm = scope.sequence.arms[0]
    tree = replace(scope.sequence, arms=(replace(arm, items=tuple(reversed(arm.items))),))
    result = report(replace(scope, sequence=tree))
    assert not result.passed
    assert any(r.rule_id == "control.source_order" and not r.passed for r in result.rules)


def test_all_nested_exits_terminate_enclosing_path():
    scope = analyze("python", "def flow(x):\n if x: return True\n else: return False\n")
    donor = analyze("python", "def flow(x):\n print('invalid continuation')\n")
    # Retain a complete ordering record to exercise termination independently.
    action = replace(donor.steps[0], context_id=scope.contexts[0].context_id, evidence_ids=scope.controls[0].evidence_ids)
    root_arm = scope.sequence.arms[0]
    reference = donor.sequence.arms[0].items[0]
    tree = replace(scope.sequence, arms=(replace(root_arm, items=(*root_arm.items, reference)),))
    ordering = tuple(replace(item, item_ids=(*item.item_ids, action.step_id)) if item.block_id == tree.block_id else item for item in scope.ordering)
    result = report(replace(scope, steps=(*scope.steps, action), sequence=tree, ordering=ordering))
    assert any(r.rule_id == "step.after_termination" and not r.passed for r in result.rules)


def test_missing_order_facts_cannot_claim_coverage():
    scope = analyze("python", "def flow():\n return True\n")
    assert not report(replace(scope, ordering=())).passed


def test_false_branch_label_cannot_reinterpret_true_exit():
    scope = analyze("python", "def flow(x):\n if x: return True\n else: return False\n")
    block = scope.sequence.arms[0].items[0]
    changed = replace(block, arms=(replace(block.arms[0], label="false"), block.arms[1]))
    tree = replace(scope.sequence, arms=(replace(scope.sequence.arms[0], items=(changed,)),))
    result = report(replace(scope, sequence=tree))
    assert any(r.rule_id == "control.exit_label" and not r.passed for r in result.rules)


def test_unrelated_label_proof_is_rejected(context):
    workflow, _, package = prepare(context)
    submitted = submission(package)
    task_result = submitted.results[0]
    scope = package.facts.scopes[0]
    step = scope.steps[0]
    unrelated = next(e.evidence_id for e in scope.evidence if e.evidence_id not in step.evidence_ids)
    annotations = replace(task_result.annotations, labels=(BusinessLabel(step.step_id, "false attribution", (unrelated,), "unrelated proof"),))
    changed = replace(task_result, annotations=annotations)
    receipt = replace(submitted.receipts[0], result_hash=digest(changed))
    with pytest.raises(DevflowError, match="business label"):
        workflow.handoff.validate(package, replace(submitted, results=(changed, *submitted.results[1:]), receipts=(receipt, *submitted.receipts[1:])))


def test_unrelated_requirement_proof_never_reports_consistency_passed(context):
    _, _, package = prepare(context, requirements="Accept the request.")
    scope = package.facts.scopes[0]
    step = scope.steps[0]
    unrelated = next(e.evidence_id for e in scope.evidence if e.evidence_id not in step.evidence_ids)
    segment = package.requirements.segments[0]
    requirement = Requirement(stable_id("R", segment.segment_id), (segment.segment_id,), segment.text, "implemented", "checked", "")
    link = RequirementLink(requirement.requirement_id, (step.step_id,), (unrelated,))
    result = RequirementMapper().evaluate((package.requirements, (requirement,)), (link,), package.facts, "implementation")
    assert not result.validation.passed
    assert result.implementation_consistency == "failed"
