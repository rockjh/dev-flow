"""Synthetic host records verify gates, never claim real delegation happened."""
from dataclasses import replace
import json
import subprocess

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.cli import build_workflow
from toolkit.sequence_diagram_generator.models import (AcceptRequest, CollectRequest, DiscoverRequest, HostActiveObservation,
    InitRequest, PrepareRequest, RenderReport, RequirementInput, RequirementSnapshot, RunState, TaskPackage, VerifyRequest)
from toolkit.sequence_diagram_generator.repository import digest, to_dict
from test_workflow import context, prepare, submission


def native(package):
    package = replace(package, execution_mode="native", execution_approval="")
    value = submission(package)
    receipts = tuple(replace(receipt, child_agent_id="fixture-child-" + str(index), child_count=1, degraded=False,
                             tool_references=("fixture:session/spawn/" + str(index), "fixture:session/result/" + str(index)),
                             started_at="", ended_at="", time_source="unavailable", reclaim_state="unsupported")
                     for index, receipt in enumerate(value.receipts))
    return package, replace(value, receipts=receipts, completed_child_agents=len(receipts))


def test_native_sequential_without_precise_times_or_reclamation(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    flow.handoff.validate(package, value)
    report = flow.handoff.execution_report(package, value)
    assert report.mode == "native" and not report.parallel and not report.degraded
    assert report.completed_child_agents == len(package.tasks)
    assert report.record_origin == "fixture" and report.trust_boundary == "structure-and-consistency-only"


@pytest.mark.parametrize("invalid", ["unknown_task", "missing_result"])
def test_execution_report_rejects_unknown_receipt_or_missing_success_result(context, invalid):
    flow, _, package = prepare(context)
    package, value = native(package)
    if invalid == "unknown_task":
        value = replace(value, receipts=(replace(value.receipts[0], task_id="unknown"), *value.receipts[1:]))
    else:
        value = replace(value, results=value.results[1:])
    with pytest.raises(DevflowError) as error:
        flow.handoff.execution_report(package, value)
    assert error.value.code == "GATE_FAILED"


@pytest.mark.parametrize("location", ["package", "receipt"])
def test_native_execution_rejects_serial_approval(context, location):
    flow, _, package = prepare(context)
    package, value = native(package)
    if location == "package":
        package = replace(package, execution_approval="fixture: serial authorization")
        value = replace(value, package_hash=digest(package),
                        receipts=tuple(replace(receipt, package_hash=digest(package)) for receipt in value.receipts))
    else:
        value = replace(value, receipts=(replace(value.receipts[0], execution_approval="fixture: serial authorization"), *value.receipts[1:]))
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, value)


def test_serial_receipt_times_cannot_imply_child_parallelism(context):
    flow, _, package = prepare(context)
    value = submission(package)
    value = replace(value, receipts=tuple(replace(receipt, time_source="host", started_at="2026-10-13T00:00:00+00:00",
                                                ended_at="2026-10-13T00:01:00+00:00") for receipt in value.receipts))
    flow.handoff.validate(package, value)
    report = flow.handoff.execution_report(package, value)
    assert report.mode == "serial" and report.degraded and not report.parallel and report.completed_child_agents == 0


@pytest.mark.parametrize("status", ["spawn_failed", "failed"])
def test_serial_failure_history_cannot_include_native_startup_attempt(context, status):
    flow, _, package = prepare(context)
    value = submission(package)
    failed = replace(value.receipts[0], status=status, result_hash="", error="fixture: observed task failure")
    value = replace(value, receipts=(failed,), results=())
    if status == "spawn_failed":
        with pytest.raises(DevflowError) as error:
            flow.handoff.execution_report(package, value)
        assert error.value.code == "AUTHORIZATION_REQUIRED"
    else:
        assert flow.handoff.execution_report(package, value).mode == "serial"


def test_completed_agent_reuse_is_counted_once(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    value = replace(value, completed_child_agents=1,
                    receipts=tuple(replace(receipt, child_agent_id="fixture-reused-agent") for receipt in value.receipts))
    flow.handoff.validate(package, value)
    assert flow.handoff.execution_report(package, value).completed_child_agents == 1
    with pytest.raises(DevflowError, match="child count"):
        flow.handoff.validate(package, replace(value, completed_child_agents=len(package.tasks)))


def test_observed_dispatch_and_receive_bounds_do_not_establish_overlap(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    value = replace(value, receipts=tuple(replace(receipt, started_at="2026-10-13T00:00:00+00:00",
                    ended_at="2026-10-13T00:01:00+00:00", time_source="coordinator_observed") for receipt in value.receipts))
    flow.handoff.validate(package, value)
    assert not flow.handoff.execution_report(package, value).parallel
    with pytest.raises(DevflowError, match="parallel claim"):
        flow.handoff.validate(package, replace(value, receipts=tuple(replace(receipt, parallel=True) for receipt in value.receipts)))


def test_active_snapshot_establishes_observed_parallelism(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    observation = HostActiveObservation("2026-10-13T00:00:30+00:00", tuple(task.task_id for task in package.tasks), "fixture:session/list-agents/1",
                    active_attempts=tuple(receipt.attempt for receipt in value.receipts), active_child_agent_ids=tuple(receipt.child_agent_id for receipt in value.receipts))
    value = replace(value, active_observations=(observation,), receipts=tuple(replace(receipt, parallel=True) for receipt in value.receipts))
    flow.handoff.validate(package, value)
    assert flow.handoff.execution_report(package, value).parallel
    for invalid in (replace(observation, active_task_ids=("unknown", *observation.active_task_ids)),
                    replace(observation, tool_reference=""), replace(observation, observed_at="2026-10-13T00:00:30"),
                    replace(observation, active_attempts=tuple(2 for _ in observation.active_attempts)),
                    replace(observation, active_child_agent_ids=tuple("fixture-old-child" for _ in observation.active_child_agent_ids))):
        with pytest.raises(DevflowError):
            flow.handoff.validate(package, replace(value, active_observations=(invalid,)))


def test_host_internal_intervals_allow_parallel_without_snapshot(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    value = replace(value, receipts=tuple(replace(receipt, started_at="2026-10-13T00:00:00+00:00",
                    ended_at="2026-10-13T00:01:00+00:00", time_source="host", parallel=True) for receipt in value.receipts))
    flow.handoff.validate(package, value)
    assert flow.handoff.execution_report(package, value).parallel
    with pytest.raises(DevflowError, match="one child agent"):
        flow.handoff.validate(package, replace(value, completed_child_agents=1,
                              receipts=tuple(replace(receipt, child_agent_id="fixture-one-owner") for receipt in value.receipts)))


@pytest.mark.parametrize("started_at, ended_at", [
    ("2026-10-13T00:01:00+00:00", ""),
    ("", "2026-10-13T00:00:00+00:00"),
])
def test_active_snapshot_respects_each_available_same_source_endpoint(context, started_at, ended_at):
    flow, _, package = prepare(context)
    package, value = native(package)
    receipts = tuple(replace(receipt, started_at=started_at, ended_at=ended_at,
                             time_source="coordinator_observed", parallel=True) for receipt in value.receipts)
    observation = HostActiveObservation("2026-10-13T00:00:30+00:00", tuple(task.task_id for task in package.tasks),
                    "fixture:session/list-agents/partial-time", active_attempts=tuple(receipt.attempt for receipt in receipts),
                    active_child_agent_ids=tuple(receipt.child_agent_id for receipt in receipts))
    with pytest.raises(DevflowError, match="outside the declared task observations"):
        flow.handoff.validate(package, replace(value, receipts=receipts, active_observations=(observation,)))
    # A clock from a different source cannot contradict the coordinator's snapshot.
    other_source = tuple(replace(receipt, time_source="host") for receipt in receipts)
    flow.handoff.validate(package, replace(value, receipts=other_source, active_observations=(observation,)))


@pytest.mark.parametrize("started_at, ended_at", [
    ("2026-10-13T00:00:00+00:00", ""),
    ("", "2026-10-13T00:01:00+00:00"),
])
def test_active_snapshot_accepts_consistent_partial_times(context, started_at, ended_at):
    flow, _, package = prepare(context)
    package, value = native(package)
    receipts = tuple(replace(receipt, started_at=started_at, ended_at=ended_at,
                             time_source="coordinator_observed", parallel=True) for receipt in value.receipts)
    observation = HostActiveObservation("2026-10-13T00:00:30+00:00", tuple(task.task_id for task in package.tasks),
                    "fixture:session/list-agents/partial-time", active_attempts=tuple(receipt.attempt for receipt in receipts),
                    active_child_agent_ids=tuple(receipt.child_agent_id for receipt in receipts))
    flow.handoff.validate(package, replace(value, receipts=receipts, active_observations=(observation,)))
    assert flow.handoff.execution_report(package, replace(value, receipts=receipts, active_observations=(observation,))).parallel


@pytest.mark.parametrize("status", ["failed", "interrupted", "timeout"])
def test_failed_started_attempts_cannot_overlap_another_task_on_the_same_child(context, status):
    flow, _, package = prepare(context)
    package, value = native(package)
    first, second, *others = value.receipts
    failed = replace(first, status=status, result_hash="", error="fixture: prior attempt did not complete",
                     child_agent_id=second.child_agent_id, time_source="host",
                     started_at="2026-10-13T00:00:00+00:00", ended_at="2026-10-13T00:02:00+00:00")
    result = replace(value.results[0], attempt=2)
    retry = replace(first, attempt=2, result_hash=digest(result), time_source="host",
                    started_at="2026-10-13T00:03:00+00:00", ended_at="2026-10-13T00:04:00+00:00")
    overlap = replace(second, time_source="host", started_at="2026-10-13T00:00:30+00:00", ended_at="2026-10-13T00:01:30+00:00")
    value = replace(value, results=(result, *value.results[1:]), receipts=(failed, retry, overlap, *others))
    with pytest.raises(DevflowError, match="one child agent cannot own overlapping"):
        flow.handoff.validate(package, value)
    # Reusing the child after its failed attempt has ended remains valid.
    later = replace(overlap, started_at=failed.ended_at, ended_at=retry.started_at)
    flow.handoff.validate(package, replace(value, receipts=(failed, retry, later, *others)))


@pytest.mark.parametrize("mutation", [
    lambda r: replace(r, package_hash="foreign"),
    lambda r: replace(r, result_hash="foreign"),
    lambda r: replace(r, scope_ids=("foreign",)),
    lambda r: replace(r, child_count=2),
    lambda r: replace(r, child_agent_id=""),
    lambda r: replace(r, tool_references=()),
    lambda r: replace(r, degraded=True),
    lambda r: replace(r, reclaimed_at="2026-10-13T00:00:00+00:00"),
    lambda r: replace(r, started_at="2026-10-13T00:00:00+00:00", time_source="unavailable"),
    lambda r: replace(r, status="failed"),
])
def test_native_receipt_binding_and_evidence_rejections(context, mutation):
    flow, _, package = prepare(context)
    package, value = native(package)
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, replace(value, receipts=(mutation(value.receipts[0]), *value.receipts[1:])))


def test_retry_preserves_failed_attempt_without_duplicate_success(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    result = replace(value.results[0], attempt=2)
    failed = replace(value.receipts[0], status="failed", result_hash="", error="fixture: source interpretation needed correction")
    success = replace(value.receipts[0], attempt=2, result_hash=digest(result))
    value = replace(value, results=(result, *value.results[1:]), receipts=(failed, success, *value.receipts[1:]))
    flow.handoff.validate(package, value)
    assert flow.handoff.execution_report(package, value).attempts == len(package.tasks) + 1
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, replace(value, receipts=(*value.receipts, success)))
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, replace(value, receipts=(replace(failed, attempt=2), success, *value.receipts[2:])))
    out_of_order = replace(failed, time_source="coordinator_observed", ended_at="2026-10-13T00:02:00+00:00")
    early_retry = replace(success, time_source="coordinator_observed", started_at="2026-10-13T00:01:00+00:00")
    with pytest.raises(DevflowError, match="preceding attempt"):
        flow.handoff.validate(package, replace(value, receipts=(out_of_order, early_retry, *value.receipts[2:])))


@pytest.mark.parametrize("evidence", ["host_interval", "active_snapshot"])
def test_parallel_evidence_can_bind_failed_attempt_before_successful_retry(context, evidence):
    flow, _, package = prepare(context)
    package, value = native(package)
    first, second, *others = value.receipts
    failed = replace(first, status="failed", result_hash="", error="fixture: analysis failed after parallel execution", parallel=True)
    result = replace(value.results[0], attempt=2)
    retry = replace(first, attempt=2, child_agent_id="fixture-retry-child", result_hash=digest(result))
    second = replace(second, parallel=True)
    observations = ()
    if evidence == "host_interval":
        failed = replace(failed, time_source="host", started_at="2026-10-13T00:00:00+00:00", ended_at="2026-10-13T00:02:00+00:00")
        second = replace(second, time_source="host", started_at="2026-10-13T00:00:30+00:00", ended_at="2026-10-13T00:01:30+00:00")
        retry = replace(retry, time_source="host", started_at="2026-10-13T00:03:00+00:00", ended_at="2026-10-13T00:04:00+00:00")
    else:
        observations = (HostActiveObservation("2026-10-13T00:00:30+00:00", (failed.task_id, second.task_id),
            "fixture:session/list-agents/failed-attempt", active_attempts=(failed.attempt, second.attempt),
            active_child_agent_ids=(failed.child_agent_id, second.child_agent_id)),)
    value = replace(value, results=(result, *value.results[1:]), receipts=(failed, retry, second, *others), active_observations=observations)
    flow.handoff.validate(package, value)
    assert flow.handoff.execution_report(package, value).parallel
    assert flow.handoff.execution_report(package, value).completed_child_agents == len(package.tasks)
    flow.handoff.validate_attempt_history(package, value, value)
    without_failure = replace(value, receipts=(replace(first, child_agent_id=retry.child_agent_id), second, *others),
                              results=(replace(result, attempt=1), *value.results[1:]))
    with pytest.raises(DevflowError, match="previous failed attempt must be retained"):
        flow.handoff.validate_attempt_history(package, without_failure, value)
    # The later retry cannot inherit overlap from the failed attempt's evidence.
    with pytest.raises(DevflowError, match="parallel claim"):
        flow.handoff.validate(package, replace(value, receipts=(failed, replace(retry, parallel=True), second, *others)))


def test_failed_startup_cannot_claim_a_reclaimed_child(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    result = replace(value.results[0], attempt=2)
    failed = replace(value.receipts[0], status="spawn_failed", child_agent_id="", child_count=0,
                     result_hash="", error="fixture: actual startup failed")
    success = replace(value.receipts[0], attempt=2, result_hash=digest(result))
    value = replace(value, results=(result, *value.results[1:]), receipts=(failed, success, *value.receipts[1:]))
    flow.handoff.validate(package, value)
    invalid = replace(failed, time_source="coordinator_observed", started_at="2026-10-13T00:00:00+00:00",
                      ended_at="2026-10-13T00:00:01+00:00", reclaim_state="reclaimed",
                      reclaimed_at="2026-10-13T00:00:02+00:00")
    with pytest.raises(DevflowError, match="failed startup cannot claim"):
        flow.handoff.validate(package, replace(value, receipts=(invalid, *value.receipts[1:])))


def test_fixture_receipts_are_rejected_by_production_handoff(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    flow.handoff.allow_fixtures = False
    with pytest.raises(DevflowError, match="fixture"):
        flow.handoff.validate(package, value)


def test_invalid_collection_is_diagnosed_and_correctable_without_rewriting_manifest(context):
    flow, run_id, package = prepare(context)
    path = flow.repository.artifact_path(context, run_id, "handoff.json")
    value = submission(package)
    invalid = replace(value, receipts=(*value.receipts, value.receipts[0]))
    path.write_text(json.dumps(to_dict(invalid)), encoding="utf-8")
    with pytest.raises(DevflowError):
        flow.collect(CollectRequest(context, run_id, path))
    manifest = flow.repository.load(context, run_id)
    assert manifest.state == RunState.PREPARED and manifest.operation_errors
    assert not (context.assets / "matrix.md").exists()
    assert list(flow.repository.run_path(context, run_id).glob("rejected-*.json"))
    path.write_text(json.dumps(to_dict(value)), encoding="utf-8")
    assert flow.collect(CollectRequest(context, run_id, path)).data["state"] == "collected"
    assert flow.collect(CollectRequest(context, run_id, path)).data["idempotent"]


def test_empty_source_analysis_cannot_pass_as_native_result(context):
    flow, _, package = prepare(context)
    package, value = native(package)
    result = replace(value.results[0], annotations=replace(value.results[0].annotations, labels=()))
    receipts = (replace(value.receipts[0], result_hash=digest(result)), *value.receipts[1:])
    with pytest.raises(DevflowError, match="source analysis requires"):
        flow.handoff.validate(package, replace(value, results=(result, *value.results[1:]), receipts=receipts))


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
@pytest.mark.parametrize("field", ["label", "diagnostics"])
def test_source_analysis_rejects_blank_text(context, field, text):
    flow, _, package = prepare(context)
    package, value = native(package)
    result = value.results[0]
    if field == "label":
        labels = (replace(result.annotations.labels[0], label=text), *result.annotations.labels[1:])
        result = replace(result, annotations=replace(result.annotations, labels=labels))
    else:
        result = replace(result, diagnostics=(text,))
    receipts = (replace(value.receipts[0], result_hash=digest(result)), *value.receipts[1:])
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, replace(value, results=(result, *value.results[1:]), receipts=receipts))


def test_selected_requirement_segments_remain_bound_through_acceptance(context):
    flow = build_workflow(context)
    flow.handoff.allow_fixtures = True
    flow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("fixture: scope test does not need a renderer",))
    flow.init(InitRequest(context))
    found = flow.discover(DiscoverRequest(context, "requirement", "proposal", (), RequirementInput("text", "First requirement.\n\nSecond requirement.")))
    run_id = found.data["run_id"]
    snapshot = flow.repository.read_artifact(context, run_id, "requirements.json", RequirementSnapshot)
    assert len(snapshot.segments) == 2
    selected = snapshot.segments[0].segment_id
    flow.prepare(PrepareRequest(context, run_id, (), True, True, "serial", "fixture: explicit scoped serial approval",
                                selected_segment_ids=(selected,)))
    package = flow.repository.read_artifact(context, run_id, "task-package.json", TaskPackage)
    assert package.tasks[0].segment_ids == (selected,)
    assert package.requirements == snapshot and package.requirement_hash == digest(snapshot)
    value = submission(package)
    # An unselected segment cannot be submitted merely because the full input is frozen.
    with pytest.raises(DevflowError, match="requirement identity or source scope"):
        flow.handoff.validate(package, value)
    result = value.results[0]
    requirements = tuple(item for item in result.annotations.requirements if item.segment_ids == (selected,))
    requirement_ids = {item.requirement_id for item in requirements}
    proposals = tuple(item for item in result.annotations.proposed_steps if set(item.requirement_ids) <= requirement_ids)
    result = replace(result, annotations=replace(result.annotations, requirements=requirements, proposed_steps=proposals))
    value = replace(value, results=(result,), receipts=(replace(value.receipts[0], result_hash=digest(result)),))
    path = flow.repository.artifact_path(context, run_id, "fixture-selected-submission.json")
    path.write_text(json.dumps(to_dict(value)), encoding="utf-8")
    flow.collect(CollectRequest(context, run_id, path))
    from toolkit.sequence_diagram_generator.models import DocumentBundle
    bundle = flow.repository.read_artifact(context, run_id, "document-bundle.json", DocumentBundle)
    assert bundle.requirement_report.candidate_segments == bundle.requirement_report.processed_segments == 1
    flow.verify(VerifyRequest(context, run_id))
    assert flow.accept(AcceptRequest(context, run_id)).data["revision"] == 1
    assert flow.repository.read_artifact(context, run_id, "requirements.json", RequirementSnapshot) == snapshot


@pytest.mark.parametrize("status", ["failed", "timeout", "interrupted", "spawn_failed"])
def test_rejected_failure_attempt_is_retained_before_same_run_retry(context, status):
    flow, run_id, package = prepare(context, execution_mode="native")
    package, value = native(package)
    flow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("fixture: attempt history test",))
    failed = replace(value.receipts[0], status=status, result_hash="", error="fixture: actual task failure")
    if status == "spawn_failed":
        failed = replace(failed, child_agent_id="", child_count=0)
    incomplete = replace(value, receipts=(failed, *value.receipts[1:]), completed_child_agents=len(value.receipts) - 1)
    path = flow.repository.artifact_path(context, run_id, "fixture-retry-submission.json")
    path.write_text(json.dumps(to_dict(incomplete)), encoding="utf-8")
    with pytest.raises(DevflowError):
        flow.collect(CollectRequest(context, run_id, path))
    rejected = set(flow.repository.run_path(context, run_id).glob("rejected-*.json"))
    assert rejected and flow.repository.load(context, run_id).state == RunState.PREPARED
    for rewritten in (value, replace(value, receipts=(replace(failed, error="fixture: rewritten diagnostic"), *value.receipts[1:]))):
        path.write_text(json.dumps(to_dict(rewritten)), encoding="utf-8")
        with pytest.raises(DevflowError, match="previous failed attempt must be retained"):
            flow.collect(CollectRequest(context, run_id, path))
    result = replace(value.results[0], attempt=2)
    retry = replace(value.receipts[0], attempt=2, result_hash=digest(result))
    valid = replace(value, results=(result, *value.results[1:]), receipts=(failed, retry, *value.receipts[1:]))
    path.write_text(json.dumps(to_dict(valid)), encoding="utf-8")
    assert flow.collect(CollectRequest(context, run_id, path)).data["state"] == "collected"
    assert rejected <= set(flow.repository.run_path(context, run_id).glob("rejected-*.json"))


@pytest.mark.parametrize("foreign", ["run", "package", "task", "receipt_package", "scope"])
def test_unbound_rejected_failure_cannot_poison_current_attempt_history(context, foreign):
    flow, run_id, package = prepare(context, execution_mode="native")
    package, value = native(package)
    flow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("fixture: unbound attempt history",))
    failed = replace(value.receipts[0], status="failed", result_hash="", error="fixture: unbound failure")
    invalid = replace(value, receipts=(failed, *value.receipts[1:]))
    if foreign == "run":
        invalid = replace(invalid, run_id="f" * 32)
    elif foreign == "package":
        invalid = replace(invalid, package_hash="foreign")
    else:
        failed = replace(failed, **{"task": {"task_id": "foreign"}, "receipt_package": {"package_hash": "foreign"},
                                   "scope": {"scope_ids": ("foreign",)}}[foreign])
        invalid = replace(invalid, receipts=(failed, *value.receipts[1:]))
    path = flow.repository.artifact_path(context, run_id, "fixture-foreign-submission.json")
    path.write_text(json.dumps(to_dict(invalid)), encoding="utf-8")
    with pytest.raises(DevflowError):
        flow.collect(CollectRequest(context, run_id, path))
    path.write_text(json.dumps(to_dict(value)), encoding="utf-8")
    assert flow.collect(CollectRequest(context, run_id, path)).data["state"] == "collected"


def test_failure_history_survives_later_domain_gate_rejection(context):
    flow, run_id, package = prepare(context, execution_mode="native")
    package, value = native(package)
    failed = replace(value.receipts[0], status="failed", result_hash="", error="fixture: first task attempt failed")
    result = replace(value.results[0], attempt=2)
    retry = replace(value.receipts[0], attempt=2, result_hash=digest(result))
    valid = replace(value, results=(result, *value.results[1:]), receipts=(failed, retry, *value.receipts[1:]))
    path = flow.repository.artifact_path(context, run_id, "fixture-domain-retry.json")
    path.write_text(json.dumps(to_dict(valid)), encoding="utf-8")
    flow.renderer.render = lambda *args: RenderReport("failed", "fixture", "", (), ("fixture: renderer failed after host validation",))
    with pytest.raises(DevflowError, match="render gate failed"):
        flow.collect(CollectRequest(context, run_id, path))
    assert flow.repository.load(context, run_id).state == RunState.PREPARED
    path.write_text(json.dumps(to_dict(value)), encoding="utf-8")
    with pytest.raises(DevflowError, match="previous failed attempt must be retained"):
        flow.collect(CollectRequest(context, run_id, path))
    flow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("fixture: corrected renderer state",))
    path.write_text(json.dumps(to_dict(valid)), encoding="utf-8")
    assert flow.collect(CollectRequest(context, run_id, path)).data["state"] == "collected"


def test_worktree_write_is_rejected_even_when_committed_analysis_facts_are_unchanged(context):
    source = context.project / "app.py"
    from test_adapters import FIXTURES
    source.write_text(FIXTURES["python"][1], encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(context.project)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(context.project), "add", "app.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(context.project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture input"], check=True, capture_output=True)
    flow, run_id, package = prepare(context)
    source.write_text(source.read_text(encoding="utf-8") + "\n# unauthorized child edit\n", encoding="utf-8")
    path = flow.repository.artifact_path(context, run_id, "submission.json")
    path.write_text(json.dumps(to_dict(submission(package))), encoding="utf-8")
    assert flow.scanner.snapshot(context).fingerprint == package.facts.source_fingerprint
    with pytest.raises(DevflowError, match="read-only workspace"):
        flow.collect(CollectRequest(context, run_id, path))
    assert "unauthorized child edit" in source.read_text(encoding="utf-8")
    assert flow.committer.baseline(context).revision == 0


def test_project_root_handoff_is_rejected_without_writing_assets(context):
    flow, run_id, package = prepare(context)
    path = context.project / "submission.json"
    path.write_text(json.dumps(to_dict(submission(package))), encoding="utf-8")
    with pytest.raises(DevflowError, match="escapes"):
        flow.collect(CollectRequest(context, run_id, path))
    assert flow.committer.baseline(context).revision == 0
