from dataclasses import replace

import pytest

from toolkit.sequence_diagram_generator.models import FlowModel, Requirement, RequirementLink, RequirementInput
from toolkit.sequence_diagram_generator.inputs import SourceReader
from toolkit.sequence_diagram_generator.requirements import RequirementMapper
from toolkit.sequence_diagram_generator.repository import stable_id
from test_workflow import context, prepare


@pytest.mark.parametrize("status", ["partially_implemented", "requirement_only", "conflict"])
def test_proposal_pending_states_do_not_pass_implementation(context, status):
    flow, _, package = prepare(context, requirements="Accept positive amounts.")
    snapshot = package.requirements
    step = package.facts.scopes[0].steps[0]
    assessment = "checked_not_found" if status == "requirement_only" else "checked"
    requirement = Requirement(stable_id("R", snapshot.segments[0].segment_id), (snapshot.segments[0].segment_id,),
                              "Accept positive amounts.", status, assessment, "pending or conflicting rule")
    links = () if status == "requirement_only" else (RequirementLink(requirement.requirement_id, (step.step_id,), step.evidence_ids),)
    mapper = RequirementMapper()
    proposed = mapper.evaluate((snapshot, (requirement,)), links, package.facts, "proposal")
    assert proposed.validation.passed
    assert proposed.implementation_consistency == "failed"
    assert not mapper.evaluate((snapshot, (requirement,)), links, package.facts, "implementation").validation.passed


def test_requirement_source_reconciliation_does_not_hide_unhandled_paragraph(context):
    snapshot = SourceReader(context).read(RequirementInput("text", "First rule.\nSecond rule."))
    requirement = Requirement(stable_id("R", "one"), (snapshot.segments[0].segment_id,), "First rule.",
                              "requirement_only", "not_evaluated", "pending")
    report = RequirementMapper().evaluate((snapshot, (requirement,)), (), FlowModel((), "", ""), "proposal")
    assert not report.validation.passed
    assert report.candidate_segments == 2 and report.processed_segments == 1


def test_unknown_implementation_is_not_checked_absence(context):
    flow, _, package = prepare(context, requirements="Notify after saving.")
    scope = package.facts.scopes[0]
    from toolkit.sequence_diagram_generator.models import CoverageGap
    model = replace(package.facts, scopes=(replace(scope, gaps=(CoverageGap("UNKNOWN", "app.py", "line:1", scope.scope.entry_id, (), True, "unresolved dispatch"),)),))
    requirement = Requirement(stable_id("R", "notify"), (package.requirements.segments[0].segment_id,), "Notify after saving.",
                              "requirement_only", "checked_not_found", "not found")
    report = RequirementMapper().evaluate((package.requirements, (requirement,)), (), model, "proposal")
    assert not report.validation.passed


def test_proposal_targets_use_requirement_proofs_without_becoming_code_facts(context):
    from toolkit.sequence_diagram_generator.models import ProposedStep, ProposedControl
    snapshot = SourceReader(context).read(RequirementInput("text", "Notify requester.\nRecord failure if notification fails."))
    first, second = snapshot.segments
    requirements = tuple(Requirement(stable_id("R", segment.segment_id), (segment.segment_id,), segment.text,
                                    "requirement_only", "not_evaluated", "no code supplied") for segment in snapshot.segments)
    step = ProposedStep(stable_id("S", "notify"), (requirements[0].requirement_id,), "Service", "Requester", "Notify")
    control = ProposedControl(stable_id("B", "failure"), "opt", (requirements[1].requirement_id,), "Failure", (stable_id("B", "exit"),))
    links = (RequirementLink(requirements[0].requirement_id, (step.step_id,), (first.segment_id,)),
             RequirementLink(requirements[1].requirement_id, (control.control_id, *control.exit_ids), (second.segment_id,)))
    mapper = RequirementMapper()
    def evaluate(items, mapped, intent="proposal"):
        return mapper.evaluate((snapshot, items), mapped, FlowModel((), "", ""), intent,
                               proposed_steps=(step,), proposed_controls=(control,))
    report = evaluate(requirements, links)
    assert report.validation.passed
    assert report.implementation_consistency == "not_evaluated"
    assert not evaluate(requirements, links, "implementation").validation.passed
    assert not evaluate((replace(requirements[0], status="implemented", implementation_assessment="checked"), requirements[1]), links).validation.passed
    assert not evaluate(requirements, (replace(links[0], evidence_ids=(second.segment_id,)), links[1])).validation.passed
    assert not evaluate(requirements, (replace(links[0], target_ids=(control.control_id,), evidence_ids=(second.segment_id,)), links[1])).validation.passed
