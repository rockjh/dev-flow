"""Synthetic receipts are fixtures; real host acceptance is a separate session run."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from toolkit.biz_flow_doc_generator import cli, host
from toolkit.biz_flow_doc_generator.validation import digest


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "# 查询订单\n@app.get('/orders')\ndef orders():\n    return []\n"
        "# 查询发票\n@app.get('/invoices')\ndef invoices():\n    return []\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid"), ("add", "."), ("commit", "-qm", "fixture")):
        subprocess.run(["git", *args], cwd=project, check=True)
    state = tmp_path / "state"
    monkeypatch.setattr(cli, "state_root", lambda: state)
    monkeypatch.setattr(host, "state_root", lambda: state)
    monkeypatch.setenv("DEVFLOW_AGENT_EXECUTOR", "unrelated-retired-setting")
    assert cli.init_command(["--project", str(project)]) == 0
    assert cli.discover_command(["--project", str(project)]) == 0
    assert cli.prepare_command(["--project", str(project), "--confirm"]) == 0
    path = next(p for p in state.glob("biz-flow/*.json") if not p.name.endswith(".tasks.json"))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["host_capability"] == "unknown"
    return project, path, manifest


def fixture_submission(manifest):
    results, receipts = {}, []
    for i, task in enumerate(manifest["tasks"]):
        facts = manifest["entry_facts"][task["entry_id"]]
        refs = [facts["sources"][0]["evidence_id"]]
        targets = [(f["fact_id"], f["evidence_refs"]) for k in ("calls", "branches", "persistence_actions", "effects", "outcomes") for f in facts[k]]
        targets += [(p["participant_id"], p["evidence_refs"]) for p in facts["participants"]]
        value = {"kind": "analysis", "analysis": {
            "entry_id": task["entry_id"], "source_fingerprint": facts["source_fingerprint"], "facts_hash": digest(facts),
            "review": {k: {"text": text, "evidence_refs": refs} for k, text in {
                "trigger": "接收业务查询请求", "purpose": facts["registration"]["business_name"], "input": "查询请求",
                "outcome": "返回查询结果", "failure": "未声明业务失败分支"}.items()},
            "annotations": [{"target_id": target, "text": "返回查询结果" if target.startswith("O-") else "查询业务数据", "evidence_refs": proof}
                            for target, proof in targets]}}
        results[task["entry_id"]] = value
        receipts.append({"run_id": manifest["run_id"], "task_id": task["task_id"], "batch_id": "fixture-batch", "task_hash": task["task_hash"],
            "input_hash": task["input_hash"], "child_agent_id": f"fixture-child-{i}", "attempt": 1,
            "status": "success", "result_hash": digest(value), "error": None, "record_origin": "fixture",
            "tool_references": [f"fixture://spawn/{i}", f"fixture://result/{i}"],
            "time_source": "unavailable", "started_at": None, "finished_at": None,
            "reclaim_state": "unsupported", "reclaimed_at": None})
    return {"protocol_version": host.PROTOCOL_VERSION, "run_id": manifest["run_id"],
        "source_fingerprint": manifest["source_fingerprint"], "mapping_hash": manifest["mapping_hash"],
        "package_hash": manifest["package_hash"], "mode": "native", "parallel": False,
        "completed_child_agents": len(receipts), "serial_approval": None,
        "results": results, "execution": {"receipts": receipts, "active_observations": []}}


def test_native_sequential_and_counting(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    assert "FIXTURE_NOT_ACCEPTABLE" in host.validate_execution(manifest, payload)
    payload["execution"]["receipts"][1]["child_agent_id"] = "fixture-child-0"
    payload["completed_child_agents"] = 1
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    payload["completed_child_agents"] = 2
    assert "NATIVE_CHILD_COUNT_MISMATCH" in host.validate_execution(manifest, payload, allow_fixture=True)


@pytest.mark.parametrize("change", ["modify", "delete", "add"])
def test_unrelated_checkout_edits_do_not_change_committed_run(prepared, monkeypatch, change):
    project, path, manifest = prepared
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "submission.json"
    submission.write_text(json.dumps(fixture_submission(manifest)), encoding="utf-8")
    source = project / "app.py"
    if change == "delete":
        source.unlink()
    elif change == "add":
        (project / "unexpected.py").write_text("print('outside assignment')\n", encoding="utf-8")
    else:
        source.write_text(source.read_text(encoding="utf-8") + "\n# unauthorized write\n", encoding="utf-8")
    assert cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["source_commit"] == manifest["source_commit"]


@pytest.mark.parametrize("mutation,expected", [
    (lambda p: p["execution"]["receipts"].append(copy.deepcopy(p["execution"]["receipts"][0])), "NATIVE_DUPLICATE_SUCCESS"),
    (lambda p: p["execution"]["receipts"].pop(), "NATIVE_EXECUTION_RECEIPTS_INCOMPLETE"),
    (lambda p: p["execution"]["receipts"][0].update(run_id="wrong"), "NATIVE_RECEIPT_BINDING_MISMATCH"),
    (lambda p: p["execution"]["receipts"][0].update(result_hash="wrong"), "NATIVE_RESULT_HASH_MISMATCH"),
    (lambda p: p.update(parallel=True), "PARALLEL_EVIDENCE_MISMATCH"),
    (lambda p: p["execution"]["receipts"][0].update(reclaimed_at="2026-10-13T00:00:00+00:00"), "NATIVE_RECEIPT_TIME_INVALID"),
])
def test_invalid_bindings_are_rejected(prepared, mutation, expected):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    mutation(payload)
    assert expected in host.validate_execution(manifest, payload, allow_fixture=True)


def test_parallel_requires_observed_running_children_and_serial_requires_scope(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    payload["parallel"] = True
    payload["execution"]["active_observations"] = [{"observed_at": "2026-10-13T00:00:00+00:00",
        "time_source": "coordinator_observed", "tool_reference": "fixture://running-snapshot",
        "active_task_ids": [task["task_id"] + ":1" for task in manifest["tasks"]]}]
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    payload.update(mode="serial", parallel=False, completed_child_agents=0)
    payload["execution"] = {"receipts": [], "active_observations": []}
    assert "SERIAL_AUTHORIZATION_INVALID" in host.validate_execution(manifest, payload)
    payload["serial_approval"] = {"choice_reference": "fixture://explicit-serial-choice",
        "scope": list(payload["results"])}
    assert host.validate_execution(manifest, payload) == []


def test_collect_verify_accept_idempotence_and_conflict(prepared, monkeypatch):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    # Only this isolated unit test permits fixture records. Production has no flag.
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "fixture-submission.json"
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    args = ["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]
    assert cli.collect_command(args) == 0
    assert cli.collect_command(args) == 0
    assert cli.check_command(["--project", str(project)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    assert cli.accept_command(["--project", str(project), "--run-id", manifest["run_id"]]) == 0
    # The authorized baseline write has its own recorded digest; it must neither
    # invalidate the accepted run nor permit subsequent unobserved lock edits.
    assert cli.check_command(["--project", str(project)]) == 0
    payload["execution"]["receipts"][0]["tool_references"].append("fixture://different")
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert cli.collect_command(args) == 8
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "accepted"


def test_scope_and_snapshot_mutation_rejected_before_assets(prepared, monkeypatch):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "fixture-submission.json"
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")}
    assert host.validate_package(manifest) == []
    (Path(manifest["tasks"][0]["source_snapshot"]) / "app.py").write_text("tampered", encoding="utf-8")
    assert "SOURCE_SNAPSHOT_CHANGED" in host.validate_package(manifest)
    assert cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]) == 8
    assert {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")} == before


def test_frozen_mapping_and_retry_order_are_bound(prepared):
    _, _, manifest = prepared
    altered = copy.deepcopy(manifest)
    altered["mapping"]["modules"][0]["file"] = "changed.md"
    assert "MAPPING_HASH_MISMATCH" in host.validate_package(altered)
    altered = copy.deepcopy(manifest)
    altered["source_commit"] = "different"
    assert "PACKAGE_BINDING_MISMATCH: source_commit" in host.validate_package(altered)
    payload = fixture_submission(manifest)
    success = payload["execution"]["receipts"][0]
    failure = copy.deepcopy(success)
    failure.update(status="failed", error="fixture failure", result_hash=None)
    success["attempt"] = 2
    payload["execution"]["receipts"].insert(0, failure)
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    payload["execution"]["receipts"][0:2] = [success, failure]
    assert "NATIVE_ATTEMPT_SEQUENCE_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


def test_spawn_failure_is_preserved_when_a_native_retry_is_collected(prepared, monkeypatch):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    success = copy.deepcopy(payload["execution"]["receipts"][0])
    failed = payload["execution"]["receipts"][0]
    failed.update(status="spawn_failed", child_agent_id=None, result_hash=None, error="fixture host launch failure")
    payload["completed_child_agents"] = 1
    errors = host.validate_execution(manifest, payload, allow_fixture=True)
    assert "NATIVE_EXECUTION_RECEIPTS_INCOMPLETE" in errors
    assert "NATIVE_CHILD_COUNT_MISMATCH" not in errors
    before = {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")}
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "fixture-spawn-retry.json"
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    args = ["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]
    assert cli.collect_command(args) == 8
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "prepared"
    assert {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")} == before

    success["attempt"] = 2
    payload["execution"]["receipts"].insert(1, success)
    payload["completed_child_agents"] = 2
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert cli.collect_command(args) == 0
    assert cli.collect_command(args) == 0
    collected = json.loads(path.read_text(encoding="utf-8"))
    assert collected["execution"]["receipts"][:2] == [failed, success]
    assert collected["completed_child_agents"] == 2


@pytest.mark.parametrize("mutation,expected", [
    ({"child_agent_id": "fixture-invented-child"}, "NATIVE_CHILD_ID_INVALID"),
    ({"error": None}, "NATIVE_FAILURE_EVIDENCE_INVALID"),
    ({"error": "   "}, "NATIVE_FAILURE_EVIDENCE_INVALID"),
    ({"result_hash": "invented-result"}, "NATIVE_FAILURE_EVIDENCE_INVALID"),
    ({"tool_references": ["   "]}, "NATIVE_TOOL_REFERENCE_INVALID"),
    ({"reclaim_state": "reclaimed"}, "NATIVE_FAILURE_EVIDENCE_INVALID"),
])
def test_spawn_failure_cannot_claim_a_child_result_or_missing_error(prepared, mutation, expected):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    success = payload["execution"]["receipts"][0]
    failed = copy.deepcopy(success)
    failed.update(status="spawn_failed", child_agent_id=None, result_hash=None, error="fixture launch failure")
    failed.update(mutation)
    success["attempt"] = 2
    payload["execution"]["receipts"].insert(0, failed)
    assert expected in host.validate_execution(manifest, payload, allow_fixture=True)


@pytest.mark.parametrize("status", ["success", "failed", "interrupted", "timed_out", "evidence_missing"])
def test_spawned_attempts_require_a_real_child_id(prepared, status):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    receipt = payload["execution"]["receipts"][0]
    receipt.update(status=status, child_agent_id=None)
    if status != "success":
        receipt.update(result_hash=None, error="fixture task failure")
    assert "NATIVE_CHILD_ID_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


def test_failed_spawn_cannot_supply_parallel_activity(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    payload["execution"]["receipts"][0].update(
        status="spawn_failed", child_agent_id=None, result_hash=None, error="fixture launch failure")
    payload.update(completed_child_agents=1, parallel=True)
    payload["execution"]["active_observations"] = [{
        "observed_at": "2026-10-13T00:00:00+00:00", "time_source": "coordinator_observed",
        "tool_reference": "fixture://invalid-active-snapshot",
        "active_task_ids": [task["task_id"] + ":1" for task in manifest["tasks"]],
    }]
    assert "ACTIVE_OBSERVATION_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


def test_parallel_snapshot_binds_the_launched_attempt_and_its_times(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    success = payload["execution"]["receipts"][0]
    failed = copy.deepcopy(success)
    failed.update(status="failed", error="fixture: first analysis failed", result_hash=None,
                  child_agent_id="fixture-old-child", time_source="coordinator_observed",
                  started_at="2026-10-13T00:00:00+00:00", finished_at="2026-10-13T00:01:00+00:00")
    success.update(attempt=2, time_source="coordinator_observed",
                   started_at="2026-10-13T00:01:00+00:00", finished_at="2026-10-13T00:02:00+00:00")
    payload["execution"]["receipts"].insert(0, failed)
    observation = {"observed_at": "2026-10-13T00:00:30+00:00", "time_source": "coordinator_observed",
                   "tool_reference": "fixture://first-attempt-running",
                   "active_task_ids": [failed["task_id"] + ":1", manifest["tasks"][1]["task_id"] + ":1"]}
    payload["execution"]["active_observations"] = [observation]
    payload["parallel"] = True
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    assert payload["completed_child_agents"] == 2  # The failed child's identity is retained, not counted as completed.
    observation["active_task_ids"][0] = success["task_id"] + ":2"
    assert "ACTIVE_OBSERVATION_OUTSIDE_TASK" in host.validate_execution(manifest, payload, allow_fixture=True)
    for unbound in (success["task_id"], success["task_id"] + ":3"):
        observation["active_task_ids"][0] = unbound
        assert "ACTIVE_OBSERVATION_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)
    observation["active_task_ids"] = [failed["task_id"] + ":1", success["task_id"] + ":2"]
    assert "ACTIVE_OBSERVATION_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


def test_parallel_snapshot_cannot_treat_reused_child_as_two_owners(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    for receipt in payload["execution"]["receipts"]:
        receipt["child_agent_id"] = "fixture-reused-child"
    payload.update(completed_child_agents=1, parallel=True)
    payload["execution"]["active_observations"] = [{
        "observed_at": "2026-10-13T00:00:00+00:00", "time_source": "coordinator_observed",
        "tool_reference": "fixture://invalid-two-owners",
        "active_task_ids": [task["task_id"] + ":1" for task in manifest["tasks"]]}]
    assert "ACTIVE_OBSERVATION_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


def test_host_intervals_reject_one_child_owning_overlapping_tasks(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    for receipt in payload["execution"]["receipts"]:
        receipt.update(time_source="host", started_at="2026-10-13T00:00:00+00:00",
                       finished_at="2026-10-13T00:01:00+00:00")
    payload["parallel"] = True
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    for receipt in payload["execution"]["receipts"]:
        receipt["child_agent_id"] = "fixture-reused-child"
    payload.update(completed_child_agents=1, parallel=False)
    assert "NATIVE_CHILD_INTERVAL_OVERLAP" in host.validate_execution(manifest, payload, allow_fixture=True)
    payload["execution"]["receipts"][1].update(started_at="2026-10-13T00:01:00+00:00",
                                                   finished_at="2026-10-13T00:02:00+00:00")
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []


def test_retry_observation_cannot_start_before_prior_attempt_ended(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    success = payload["execution"]["receipts"][0]
    failed = copy.deepcopy(success)
    failed.update(status="failed", error="fixture: analysis failed", result_hash=None,
                  time_source="coordinator_observed", started_at="2026-10-13T00:00:00+00:00",
                  finished_at="2026-10-13T00:02:00+00:00")
    success.update(attempt=2, time_source="coordinator_observed",
                   started_at="2026-10-13T00:01:00+00:00", finished_at="2026-10-13T00:03:00+00:00")
    payload["execution"]["receipts"].insert(0, failed)
    assert "NATIVE_RETRY_TIME_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)
    success["started_at"] = failed["finished_at"]
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []


@pytest.mark.parametrize("status", ["failed", "spawn_failed"])
def test_rejected_failure_cannot_be_replaced_or_omitted_in_native_retry(prepared, monkeypatch, status):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    failed_payload = copy.deepcopy(payload)
    failed = failed_payload["execution"]["receipts"][0]
    failed.update(status=status, result_hash=None, error="fixture: observed native failure")
    if status == "spawn_failed":
        failed["child_agent_id"] = None
    failed_payload["completed_child_agents"] -= 1
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "fixture-preserved-failure.json"
    submission.write_text(json.dumps(failed_payload), encoding="utf-8")
    args = ["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]
    assert cli.collect_command(args) == 8
    history = json.loads(path.read_text(encoding="utf-8"))
    assert "NATIVE_FAILURE_HISTORY_CHANGED" in host.validate_execution(history, payload, allow_fixture=True)
    payload["execution"]["receipts"][0]["attempt"] = 2
    assert "NATIVE_FAILURE_HISTORY_MISSING" in host.validate_execution(history, payload, allow_fixture=True)
    payload["execution"]["receipts"].insert(0, failed)
    assert host.validate_execution(history, payload, allow_fixture=True) == []
    submission.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.collect_command(args) == 0
    assert cli.collect_command(args) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["rejected_submissions"][0] == failed_payload


def test_invalid_failure_format_can_be_corrected_without_freezing_invented_child(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    invalid = copy.deepcopy(payload)
    invalid["execution"]["receipts"][0].update(
        status="spawn_failed", result_hash=None, error="fixture: failed launch", child_agent_id="fixture-invented")
    history = {**manifest, "rejected_submissions": [invalid]}
    failed = copy.deepcopy(invalid["execution"]["receipts"][0])
    failed["child_agent_id"] = None
    payload["execution"]["receipts"][0]["attempt"] = 2
    payload["execution"]["receipts"].insert(0, failed)
    assert host.validate_execution(history, payload, allow_fixture=True) == []


@pytest.mark.parametrize("change", [
    {"time_source": "coordinator_observed", "started_at": "2026-10-13T00:00:00+00:00"},
    {"reclaim_state": "not_observed"},
])
def test_valid_failed_observations_cannot_be_rewritten_on_retry(prepared, change):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    failed = copy.deepcopy(payload["execution"]["receipts"][0])
    failed.update(status="failed", result_hash=None, error="fixture: observed task failure")
    previous = copy.deepcopy(payload)
    previous["execution"]["receipts"][0] = failed
    previous["completed_child_agents"] -= 1
    history = {**manifest, "rejected_submissions": [previous]}
    payload["execution"]["receipts"][0]["attempt"] = 2
    payload["execution"]["receipts"].insert(0, copy.deepcopy(failed))
    assert host.validate_execution(history, payload, allow_fixture=True) == []
    payload["execution"]["receipts"][0].update(change)
    assert "NATIVE_FAILURE_HISTORY_CHANGED" in host.validate_execution(history, payload, allow_fixture=True)


def test_invalid_failed_time_format_can_be_corrected(prepared):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    invalid = copy.deepcopy(payload)
    invalid["execution"]["receipts"][0].update(status="failed", result_hash=None,
        error="fixture: task failure", started_at="not-a-timestamp", time_source="host")
    history = {**manifest, "rejected_submissions": [invalid]}
    failed = copy.deepcopy(invalid["execution"]["receipts"][0])
    failed["started_at"] = "2026-10-13T00:00:00+00:00"
    payload["execution"]["receipts"][0]["attempt"] = 2
    payload["execution"]["receipts"].insert(0, failed)
    assert host.validate_execution(history, payload, allow_fixture=True) == []


@pytest.mark.parametrize("field", ["started_at", "finished_at"])
@pytest.mark.parametrize("observation_source", ["host", "coordinator_observed"])
def test_partial_host_lifecycle_keeps_the_available_observation(prepared, field, observation_source):
    _, _, manifest = prepared
    payload = fixture_submission(manifest)
    receipt = payload["execution"]["receipts"][0]
    receipt.update(time_source="host", **{field: "2026-10-13T00:00:01+00:00"})
    assert host.validate_execution(manifest, payload, allow_fixture=True) == []
    assert not payload["parallel"]
    payload["parallel"] = True
    payload["execution"]["active_observations"] = [{
        "observed_at": "2026-10-13T00:00:00+00:00" if field == "started_at" else "2026-10-13T00:00:02+00:00",
        "time_source": observation_source, "tool_reference": "fixture://outside-partial-bound",
        "active_task_ids": [task["task_id"] + ":1" for task in manifest["tasks"]]}]
    errors = host.validate_execution(manifest, payload, allow_fixture=True)
    if observation_source == "host":
        assert "ACTIVE_OBSERVATION_OUTSIDE_TASK" in errors
    else:
        assert errors == []
    receipt[field] = "invalid-observation"
    assert "NATIVE_RECEIPT_TIME_INVALID" in host.validate_execution(manifest, payload, allow_fixture=True)


@pytest.mark.parametrize("edit", ["baseline", "metadata", "formatting"])
def test_version_file_bytes_are_frozen_even_when_docs_are_git_ignored(prepared, monkeypatch, edit):
    project, _, _ = prepared
    (project / ".gitignore").write_text("docs/\n", encoding="utf-8")
    assert cli.prepare_command(["--project", str(project), "--confirm"]) == 0
    state = host.state_root() / "biz-flow"
    path = max((p for p in state.glob("*.json") if not p.name.endswith(".tasks.json")), key=lambda p: p.stat().st_mtime_ns)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = project / "docs/biz-flow/biz-flow-doc-generator-version.json"
    assert version.relative_to(project).as_posix() in manifest["protected_hashes"]
    original = version.read_bytes()
    value = json.loads(original)
    if edit == "baseline":
        value["source"]["git_commit"] = manifest["source_commit"]
    elif edit == "metadata":
        value["operator_note"] = "fixture: unexpected mutation"
    version.write_text(json.dumps(value), encoding="utf-8")
    assert version.read_bytes() != original
    payload = fixture_submission(manifest)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = state / "fixture-version-edit.json"
    submission.write_text(json.dumps(payload), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in version.parent.glob("*.md")}
    assert cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]) == 8
    assert {p.name: p.read_bytes() for p in version.parent.glob("*.md")} == before
    assert version.read_text(encoding="utf-8") == json.dumps(value)


def test_version_baseline_changes_after_collect_block_verify_and_accept(prepared, monkeypatch):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "fixture-collected-version-edit.json"
    submission.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    version = project / "docs/biz-flow/biz-flow-doc-generator-version.json"
    value = json.loads(version.read_text(encoding="utf-8"))
    value["source"]["git_commit"] = "0" * 40
    version.write_text(json.dumps(value), encoding="utf-8")
    assert cli.verify_command(["--project", str(project)]) == 1
    assert cli.accept_command(["--project", str(project), "--run-id", manifest["run_id"]]) == 8
    assert json.loads(version.read_text(encoding="utf-8")) == value


def test_os_lock_conflict_preserves_owner_and_releases_when_process_exits(tmp_path, monkeypatch):
    from toolkit.core import artifacts
    project, state = tmp_path / "fixture-project", tmp_path / "fixture-state"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.setattr(artifacts, "state_root", lambda: state)
    script = (
        "import sys; from pathlib import Path; from toolkit.core import artifacts; "
        "artifacts.state_root=lambda: Path(sys.argv[2]); "
        "lock=artifacts.ProjectDomainLock(Path(sys.argv[1]), 'biz-flow'); lock.__enter__(); "
        "print('fixture-lock-acquired', flush=True); sys.stdin.readline()"
    )
    child = subprocess.Popen([sys.executable, "-B", "-c", script, str(project), str(state)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "fixture-lock-acquired"
        assert cli._locked(["--project", str(project)], lambda: 0, init=True) == 8
        assert child.poll() is None
        child.stdin.write("fixture-release\n")
        child.stdin.flush()
        assert child.wait(timeout=10) == 0
        assert cli._locked(["--project", str(project)], lambda: 0, init=True) == 0
        assert not (project / "docs/biz-flow/biz-flow-run.lock").exists()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


@pytest.mark.parametrize("directory", ["docs", "biz-flow"])
@pytest.mark.parametrize("alias", ["symlink", "junction"])
def test_business_asset_directory_alias_cannot_escape_project(tmp_path, directory, alias):
    project, outside = tmp_path / "fixture-project", tmp_path / "fixture-outside"
    (project / ".git").mkdir(parents=True)
    outside.mkdir()
    (outside / "fixture-marker.txt").write_text("must stay unchanged", encoding="utf-8")
    if directory == "docs":
        link = project / "docs"
    else:
        (project / "docs").mkdir()
        link = project / "docs/biz-flow"
    if alias == "junction":
        if os.name != "nt":
            pytest.skip("Windows junction regression")
        assert link.parent.resolve().is_relative_to(tmp_path.resolve())
        assert outside.resolve().is_relative_to(tmp_path.resolve())
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        assert created.returncode == 0, created.stderr.decode(errors="replace")
    else:
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink unavailable: {exc}")
    try:
        with pytest.raises(ValueError, match="DOCS_PATH_UNSAFE"):
            cli._docs_root(project, Path("docs/biz-flow"))
        assert cli.init_command(["--project", str(project)]) == 8
        assert sorted(p.name for p in outside.iterdir()) == ["fixture-marker.txt"]
        assert (outside / "fixture-marker.txt").read_text(encoding="utf-8") == "must stay unchanged"
    finally:
        if alias == "junction":
            link.rmdir()
        else:
            link.unlink()
