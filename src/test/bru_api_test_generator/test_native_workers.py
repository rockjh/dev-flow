"""Synthetic fixture handoffs test consistency only, never real host execution."""
import copy
import json
from pathlib import Path

import pytest

from toolkit.bru_api_test_generator import cli, constraints, host
from toolkit.core.artifacts import write_version_file


@pytest.fixture
def worker_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    qa_root = project / "qa"
    for name in ("alpha", "beta"):
        directory = qa_root / "contracts" / "modules" / name
        directory.mkdir(parents=True)
        (directory / "endpoints.yaml").write_text(json.dumps({"module": name, "endpoints": []}), encoding="utf-8")
        (directory / "cases.yaml").write_text(json.dumps({"module": name, "cases": []}), encoding="utf-8")
    (project / "app.py").write_text("# fixture: source must remain unchanged\n", encoding="utf-8")
    monkeypatch.setattr(host, "state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(constraints, "state_root", lambda: tmp_path / "state")
    monkeypatch.setattr("toolkit.core.artifacts.state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(host, "validate_stage", lambda *args, **kwargs: [])
    constraints.ensure_rule_library(qa_root)
    write_version_file(project, "bru-api", {"version": 1, "status": "draft", "business": {}})
    prepared = host.prepare_workers(qa_root, ["alpha", "beta"])
    package = json.loads(Path(prepared["task_package"]).read_text(encoding="utf-8"))
    return qa_root, prepared, package


def submit(qa_root, prepared, package, task, *, child=None):
    result = host.worker_result(qa_root, package, task, attempt=1, diagnostics=["fixture: independent module generation result"])
    return {"run_id": package["run_id"], "task_id": task["task_id"], "package_hash": host.digest(package),
            "task_hash": host.digest(task), "input_hash": package["input_hash"], "record_origin": "fixture",
            "permission_enforcement": "shared_workspace_instructions", "attempts": [{"attempt": 1, "status": "success",
            "child_agent_id": child or "fixture-child-" + task["module"], "tool_references": ["fixture:session/spawn", "fixture:session/result"],
            "time_source": "unavailable", "started_at": "", "ended_at": "", "reclaimed_at": "", "reclaim_state": "unsupported", "error": ""}],
            "result": result, "result_hash": host.digest(result), "active_observations": []}


def collect(qa_root, prepared, package, task, value, *, fixture=True):
    path = Path(package["handoff_root"]) / (task["task_id"] + "-input.json")
    path.write_text(json.dumps(value), encoding="utf-8")
    return host.check_worker(qa_root, task["module"], prepared["run_id"], path, "generation", allow_fixtures=fixture)


def test_existing_commands_freeze_all_authorized_workers_in_state(worker_project, monkeypatch):
    qa_root, _, _ = worker_project
    monkeypatch.setenv("DEVFLOW_AGENT_EXECUTOR", "unrelated-config-does-not-detect-session-tools")
    assert cli.worker_command(["--qa-root", str(qa_root), "--delegate", "--module", "alpha", "--module", "beta"], True) == 0
    snapshot = constraints.write_worker_snapshot(qa_root, "alpha")
    assert not snapshot.is_relative_to(qa_root)
    assert not (qa_root / "contracts" / "worker-assignments").exists()


def test_partial_then_all_tasks_and_agent_reuse_counted_once(worker_project):
    qa_root, prepared, package = worker_project
    tasks = package["tasks"]
    values = [submit(qa_root, prepared, package, task, child="fixture-reused-child") for task in tasks]
    first = collect(qa_root, prepared, package, tasks[0], values[0])
    assert first["state"] == "partial" and first["completed_tasks"] == 1 and first["completed_child_agents"] == 1
    last = collect(qa_root, prepared, package, tasks[1], values[1])
    assert last["state"] == "domain_checks_passed" and last["completed_child_agents"] == 1
    assert not last["parallel"] and not last["degraded"] and last["mode"] == "native"
    assert last["record_origin"] == "fixture" and last["coordinator_merge"] == "pending"
    assert collect(qa_root, prepared, package, tasks[1], values[1])["idempotent"]


@pytest.mark.parametrize("field", ["run_id", "task_id", "package_hash", "task_hash", "input_hash", "result_hash"])
def test_foreign_or_stale_binding_is_rejected(worker_project, field):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    value[field] = "a" * 32 if field == "run_id" else "a" * 64
    with pytest.raises(ValueError):
        collect(qa_root, prepared, package, task, value)
    manifest = json.loads((Path(package["handoff_root"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == {} and manifest["state"] == "tasks_prepared"


def test_unknown_fixture_or_missing_native_execution_cannot_enter_production(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    with pytest.raises(ValueError, match="fixture"):
        collect(qa_root, prepared, package, task, value, fixture=False)
    value["attempts"][0]["child_agent_id"] = ""
    with pytest.raises(ValueError, match="actual child"):
        collect(qa_root, prepared, package, task, value)


def test_attempt_failure_retry_and_duplicate_success(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    failed = {**value["attempts"][0], "status": "failed", "error": "fixture: child task failed"}
    success = {**value["attempts"][0], "attempt": 2}
    value["attempts"] = [failed, success]
    value["result"]["attempt"] = 2
    value["result_hash"] = host.digest(value["result"])
    assert collect(qa_root, prepared, package, task, value)["state"] == "partial"
    changed = copy.deepcopy(value)
    changed["attempts"].append({**success, "attempt": 3})
    with pytest.raises(ValueError):
        collect(qa_root, prepared, package, task, changed)


def test_rejected_failed_attempt_is_preserved_on_retry(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    failed = submit(qa_root, prepared, package, task)
    failed["attempts"][0].update(status="failed", error="fixture: actual task failed")
    with pytest.raises(ValueError, match="incomplete: failed"):
        collect(qa_root, prepared, package, task, failed)
    erased = submit(qa_root, prepared, package, task)
    with pytest.raises(ValueError, match="preserve previously observed failed attempts"):
        collect(qa_root, prepared, package, task, erased)
    retry = copy.deepcopy(failed)
    retry["attempts"].append({**erased["attempts"][0], "attempt": 2})
    retry["result"]["attempt"] = 2
    retry["result_hash"] = host.digest(retry["result"])
    assert collect(qa_root, prepared, package, task, retry)["state"] == "partial"
    assert list(Path(package["handoff_root"]).glob("attempts-*.json"))


def test_foreign_failed_attempt_does_not_poison_recovery(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    foreign = submit(qa_root, prepared, package, task)
    foreign["run_id"] = "a" * 32
    foreign["attempts"][0].update(status="failed", error="fixture: wrong run")
    with pytest.raises(ValueError, match="binding"):
        collect(qa_root, prepared, package, task, foreign)
    assert collect(qa_root, prepared, package, task, submit(qa_root, prepared, package, task))["state"] == "partial"


def test_failed_startup_cannot_claim_a_reclaimed_worker(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    failed = {**value["attempts"][0], "status": "spawn_failed", "child_agent_id": "",
              "error": "fixture: actual startup failed", "time_source": "coordinator_observed",
              "started_at": "2026-10-13T00:00:00+00:00", "ended_at": "2026-10-13T00:00:01+00:00",
              "reclaim_state": "reclaimed", "reclaimed_at": "2026-10-13T00:00:02+00:00"}
    value["attempts"] = [failed, {**value["attempts"][0], "attempt": 2}]
    value["result"]["attempt"] = 2
    value["result_hash"] = host.digest(value["result"])
    with pytest.raises(ValueError, match="failed worker startup cannot claim"):
        collect(qa_root, prepared, package, task, value)
    failed.update(reclaim_state="unsupported", reclaimed_at="")
    assert collect(qa_root, prepared, package, task, value)["state"] == "partial"


def test_parallel_snapshot_binds_real_owner_attempts(worker_project):
    qa_root, prepared, package = worker_project
    tasks = package["tasks"]
    values = [submit(qa_root, prepared, package, task) for task in tasks]
    observation = {"observed_at": "2026-10-13T00:00:00+00:00", "active_task_ids": [task["task_id"] for task in tasks],
        "active_child_agent_ids": [value["attempts"][0]["child_agent_id"] for value in values], "active_attempts": [1, 1],
        "tool_reference": "fixture:session/list-active", "time_source": "coordinator_observed"}
    values[1]["active_observations"] = [observation]
    collect(qa_root, prepared, package, tasks[0], values[0])
    invalid = copy.deepcopy(values[1])
    invalid["active_observations"][0]["active_attempts"] = [1, 2]
    with pytest.raises(ValueError, match="stale child or attempt"):
        collect(qa_root, prepared, package, tasks[1], invalid)
    assert collect(qa_root, prepared, package, tasks[1], values[1])["parallel"]


def test_failed_attempt_cannot_overlap_same_child_on_another_task(worker_project):
    qa_root, prepared, package = worker_project
    tasks = package["tasks"]
    values = [submit(qa_root, prepared, package, task) for task in tasks]
    failed = {**values[0]["attempts"][0], "status": "failed", "error": "fixture: task failed",
              "child_agent_id": "fixture-reused", "time_source": "host",
              "started_at": "2026-10-13T00:00:00+00:00", "ended_at": "2026-10-13T00:02:00+00:00"}
    values[0]["attempts"] = [failed, {**values[0]["attempts"][0], "attempt": 2}]
    values[0]["result"]["attempt"] = 2
    values[0]["result_hash"] = host.digest(values[0]["result"])
    values[1]["attempts"][0].update(child_agent_id="fixture-reused", time_source="host",
        started_at="2026-10-13T00:00:30+00:00", ended_at="2026-10-13T00:01:30+00:00")
    collect(qa_root, prepared, package, tasks[0], values[0])
    with pytest.raises(ValueError, match="overlapping host task intervals"):
        collect(qa_root, prepared, package, tasks[1], values[1])


def test_active_snapshot_preserves_started_failed_attempt(worker_project):
    qa_root, prepared, package = worker_project
    tasks = package["tasks"]
    values = [submit(qa_root, prepared, package, task) for task in tasks]
    failed = {**values[0]["attempts"][0], "status": "failed", "error": "fixture: child failed after observation"}
    values[0]["attempts"] = [failed, {**values[0]["attempts"][0], "attempt": 2, "child_agent_id": "fixture-retry"}]
    values[0]["result"]["attempt"] = 2
    values[0]["result_hash"] = host.digest(values[0]["result"])
    values[1]["active_observations"] = [{"observed_at": "2026-10-13T00:00:00+00:00",
        "active_task_ids": [task["task_id"] for task in tasks], "active_attempts": [1, 1],
        "active_child_agent_ids": [failed["child_agent_id"], values[1]["attempts"][0]["child_agent_id"]],
        "tool_reference": "fixture:actual-active-before-failure", "time_source": "coordinator_observed"}]
    collect(qa_root, prepared, package, tasks[0], values[0])
    report = collect(qa_root, prepared, package, tasks[1], values[1])
    assert report["parallel"] and report["completed_child_agents"] == 2


@pytest.mark.parametrize("path", ["app.py", "qa/contracts/index.yaml", "qa/reports/latest.md", "qa/execution/config.yaml"])
def test_protected_source_shared_assets_and_report_writes_fail(worker_project, path):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    target = qa_root.parent / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fixture: forbidden write\n", encoding="utf-8")
    value = submit(qa_root, prepared, package, task)
    with pytest.raises(ValueError, match="protected"):
        collect(qa_root, prepared, package, task, value)


def test_other_owner_paths_in_result_are_rejected_and_domain_gates_preserved(worker_project, monkeypatch):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    value["result"]["changed_paths"].append("qa/contracts/modules/beta/cases.yaml")
    value["result_hash"] = host.digest(value["result"])
    with pytest.raises(ValueError, match="exclusive module artifacts"):
        collect(qa_root, prepared, package, task, value)
    value = submit(qa_root, prepared, package, task)
    monkeypatch.setattr(host, "validate_stage", lambda *args, **kwargs: ["critical design evidence missing"])
    with pytest.raises(ValueError, match="domain gates failed"):
        collect(qa_root, prepared, package, task, value)


def test_changed_output_and_different_successful_receipt_require_new_run(worker_project):
    qa_root, prepared, package = worker_project
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    collect(qa_root, prepared, package, task, value)
    target = qa_root / "contracts" / "modules" / task["directory"] / "logic.yaml"
    target.write_text("fixture: changed output\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exclusive module artifacts"):
        collect(qa_root, prepared, package, task, value)
    different = submit(qa_root, prepared, package, task)
    with pytest.raises(ValueError, match="different successful worker result"):
        collect(qa_root, prepared, package, task, different)


def test_serial_requires_explicit_approval_and_zero_children(worker_project):
    qa_root, _, _ = worker_project
    with pytest.raises(ValueError, match="explicit scope authorization"):
        host.prepare_workers(qa_root, ["alpha"], mode="serial")
    prepared = host.prepare_workers(qa_root, ["alpha"], mode="serial", approval="fixture:explicit-current-scope-serial-choice")
    package = json.loads(Path(prepared["task_package"]).read_text(encoding="utf-8"))
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    value["attempts"][0]["child_agent_id"] = ""
    value["attempts"][0]["tool_references"] = []
    report = collect(qa_root, prepared, package, task, value)
    assert report["degraded"] and not report["parallel"] and report["completed_child_agents"] == 0
    persisted = json.loads(Path(report["authority"]).read_text(encoding="utf-8"))
    assert persisted["serial_approval"] == package["execution_approval"]


def test_serial_cannot_relabel_native_startup_failure_as_zero_child_history(worker_project):
    qa_root, _, _ = worker_project
    prepared = host.prepare_workers(qa_root, ["alpha"], mode="serial", approval="fixture:explicit-current-scope-serial-choice")
    package = json.loads(Path(prepared["task_package"]).read_text(encoding="utf-8"))
    task = package["tasks"][0]
    value = submit(qa_root, prepared, package, task)
    value["attempts"][0]["child_agent_id"] = ""
    failure = {**value["attempts"][0], "status": "spawn_failed", "error": "fixture:native startup failed"}
    value["attempts"] = [failure, {**value["attempts"][0], "attempt": 2}]
    value["result"]["attempt"] = 2
    value["result_hash"] = host.digest(value["result"])
    with pytest.raises(ValueError, match="no spawn attempts"):
        collect(qa_root, prepared, package, task, value)
    manifest = json.loads((Path(package["handoff_root"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed"] == {} and manifest["state"] == "tasks_prepared"
