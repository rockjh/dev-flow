"""Simulated host records are fixtures, never evidence of real native execution."""

import copy
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from toolkit.core.artifacts import version_metadata
from toolkit.core.schema import get_schema, validate_schema
from toolkit.e2e_test_generator import host


@pytest.mark.skipif(os.name != "nt", reason="Windows junction ownership regression")
def test_junctions_cannot_share_scenario_write_targets(tmp_path):
    project = tmp_path / "project"
    scenarios = project / "scenarios"
    actual = scenarios / "actual"
    actual.mkdir(parents=True)
    (actual / "场景定义.yaml").write_text("fixture: true\n", encoding="utf-8")
    alias = scenarios / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(actual)], check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match="isolated project directory"):
            host._scenario_directory(project, "scenarios/alias")
        with pytest.raises(ValueError, match="isolated E2E write target"):
            host._tree(project)
        before = (actual / "场景定义.yaml").read_bytes()
        with pytest.raises(ValueError, match="isolated project directory"):
            host.prepare_scenario_owners(project)
        assert (actual / "场景定义.yaml").read_bytes() == before
        assert not (project / "analysis").exists()
    finally:
        alias.rmdir()


@pytest.fixture
def handoff(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    repository = tmp_path / "source"
    repository.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Fixture"), ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(repository), *args], check=True)
    (repository / "source.py").write_text("def observed():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    analysis = project / "analysis"
    analysis.mkdir()
    (analysis / "workspace.yaml").write_text(yaml.safe_dump({"inventory": {"repositories": [{"id": "fixture-repo", "root": str(repository), "commit": commit}]}}), encoding="utf-8")
    lock = {**version_metadata("e2e"), "design": {}, "protocol": {}, "source": [{"repo": "fixture-repo", "commit": commit}], "support": {}, "scenarios": {}}
    (analysis / "e2e-test-generator-version.json").write_text(json.dumps(lock), encoding="utf-8")
    for name in ("场景甲", "场景乙"):
        directory = project / "scenarios" / name
        directory.mkdir(parents=True)
        document = {
            "meta": {"id": "SCENARIO_A" if name.endswith("甲") else "SCENARIO_B", "name": name},
            "generation": {"mode": "main_agent", "owner": "main-agent", "write_scope": f"scenarios/{name}", "degradation_reason": None},
            "source": [{"repo": "fixture-repo", "commit": commit, "anchors": ["source.py"]}],
            "steps": [{"design_rule_id": "RULE"}], "cleanup": {"actions": []},
        }
        (directory / "场景定义.yaml").write_text("# 人工保留的业务说明。\n" + yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
        (directory / "业务数据.json").write_text("{}", encoding="utf-8")
    with patch.object(host, "state_root", return_value=tmp_path / "state"):
        prepared = host.prepare_scenario_owners(project)
        manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
        receipts = [{
            **{field: task[field] for field in ("run_id", "task_id", "task_sha256", "input_sha256", "write_scope")},
            "child_agent_id": f"fixture-child-{index}", "attempt": 1, "status": "success",
            "result_sha256": host.scenario_digest(project / task["write_scope"]),
            "tool_records": [f"fixture://spawn/{index}", f"fixture://result/{index}"],
            "analysis_summary": "明确标记的测试分析回执，不证明实际宿主执行。",
            "source_evidence": ["fixture-repo#source.py"], "written_paths": [],
        } for index, task in enumerate(manifest["tasks"])]
        payload = {"protocol_version": 1, "domain": "e2e", "run_id": manifest["run_id"], "mode": "native", "degraded": False,
                   "parallel": False, "completed_child_agents": 2, "receipts": receipts, "observations": [], "fixture": True}
        yield project, repository, manifest, payload


def test_tasks_prepared_are_not_execution_and_match_public_contract(handoff):
    project, _, manifest, payload = handoff
    assert manifest["status"] == "tasks_prepared"
    assert manifest["completed_child_agents"] == 0
    for task in manifest["tasks"]:
        assert validate_schema(get_schema("e2e.host-task")["document"], task) == []
        assert (project / task["write_scope"] / "场景定义.yaml").is_file()
        definition = yaml.safe_load((project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8"))
        assert definition["generation"]["mode"] == "main_agent"
        assert definition["generation"]["host_task"] == {"run_id": manifest["run_id"], "task_id": task["task_id"]}
    assert validate_schema(get_schema("e2e.host-results")["document"], payload) == []
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    assert any("fixture" in error for error in host._validate_results(project, manifest, payload))


def test_single_scenario_delegate_is_bound_before_execution(handoff):
    project, _, manifest, _ = handoff
    import shutil
    removed = (project / manifest["tasks"][1]["write_scope"]).resolve()
    assert removed.is_relative_to(project.resolve())
    shutil.rmtree(removed)
    assert host.prepare_scenario_owners(project) is None
    prepared = host.prepare_scenario_owners(project, delegate=True)
    assert len(prepared["tasks"]) == 1
    task = prepared["tasks"][0]
    definition = yaml.safe_load((project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8"))
    assert definition["generation"]["owner"] == "main-agent"
    assert definition["generation"]["host_task"]["run_id"] == prepared["run_id"]
    assert host.ownership_errors(project, definition=definition)


def test_superseded_prepared_run_cannot_overwrite_current_scenario_tasks(handoff, tmp_path):
    project, _, old, payload = handoff
    old_path = host._run_path(project, old["run_id"])
    old_manifest = old_path.read_bytes()
    assert host._validate_results(project, old, payload, allow_fixture=True) == []
    prepared = host.prepare_scenario_owners(project)
    current_path = Path(prepared["manifest_path"])
    current = json.loads(current_path.read_text(encoding="utf-8"))
    # Identical source and inputs do not permit an old run to reclaim ownership.
    assert current["input_sha256"] == old["input_sha256"]
    assert [task["starter_sha256"] for task in current["tasks"]] == [task["starter_sha256"] for task in old["tasks"]]
    before_project = host._tree(project)
    before_current = host._tree(current_path.parent)
    results = tmp_path / "fixture-superseded-results.json"
    results.write_text(json.dumps(payload), encoding="utf-8")
    report, errors = host.collect_scenario_owners(project, results, allow_fixture=True)
    assert report == {} and any("current scenario task binding changed" in error for error in errors)
    assert host._tree(project) == before_project
    assert host._tree(current_path.parent) == before_current
    assert old_path.read_bytes() == old_manifest
    assert list(old_path.parent.glob("rejected-*.json"))


@pytest.mark.parametrize("mutation,expected", [
    (lambda p: p["receipts"].pop(), "incomplete"),
    (lambda p: p["receipts"].append(copy.deepcopy(p["receipts"][0])), "duplicate"),
    (lambda p: p["receipts"][0].update(run_id="other-run"), "cross-run"),
    (lambda p: p["receipts"][0].update(input_sha256="0" * 64), "stale"),
    (lambda p: p["receipts"][0].update(result_sha256="0" * 64), "digest mismatch"),
    (lambda p: p.update(completed_child_agents=99), "child count"),
    (lambda p: p.update(parallel=True), "overlap"),
    (lambda p: p["receipts"][0].update(written_paths=["common/forbidden.py"]), "exclusive scope"),
    (lambda p: p["receipts"][0].update(status="failed", result_sha256=None, error="fixture interruption"), "incomplete"),
    (lambda p: p["receipts"][0].update(attempt=2), "consecutive"),
    (lambda p: p["receipts"][0].update(error="fixture success with an old error"), "successful attempt"),
])
def test_rejects_inconsistent_receipts_without_writing_owner(handoff, mutation, expected):
    project, _, manifest, payload = handoff
    before = host._tree(project)
    mutation(payload)
    errors = host._validate_results(project, manifest, payload, allow_fixture=True)
    assert any(expected in error for error in errors), errors
    assert host._tree(project) == before


def test_single_slot_can_reuse_one_native_child_without_serial_authorization(handoff, tmp_path):
    from toolkit.e2e_test_generator.contracts import _cross_scenario_errors

    project, _, manifest, payload = handoff
    payload["receipts"][1]["child_agent_id"] = payload["receipts"][0]["child_agent_id"]
    payload["completed_child_agents"] = 1
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    path = tmp_path / "fixture-reused-child-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report, errors = host.collect_scenario_owners(project, path, allow_fixture=True)
    assert errors == []
    collected = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
    assert collected["completed_child_agents"] == 1 and collected["parallel"] is False
    assert host.ownership_errors(project, manifest=collected, allow_fixture=True) == []
    scenarios = [(project / task["write_scope"], yaml.safe_load((project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8"))) for task in manifest["tasks"]]
    assert len({definition["generation"]["owner"] for _, definition in scenarios}) == 1
    assert _cross_scenario_errors(scenarios) == []


def test_parallel_requires_observed_distinct_active_children(handoff, tmp_path):
    project, _, manifest, payload = handoff
    payload["parallel"] = True
    payload["observations"] = [{
        "observed_at": "2026-10-13T12:00:00+08:00", "time_source": "coordinator_observed",
        "tool_reference": "fixture://active-agents", "active_task_ids": [receipt["task_id"] + ":1" for receipt in payload["receipts"]],
    }]
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    payload["parallel"] = False
    assert any("parallel=false" in error for error in host._validate_results(project, manifest, payload, allow_fixture=True))
    payload["parallel"] = True
    payload["receipts"][1]["child_agent_id"] = payload["receipts"][0]["child_agent_id"]
    payload["completed_child_agents"] = 1
    assert host._validate_results(project, manifest, payload, allow_fixture=True)
    path = tmp_path / "fixture-overlapping-reused-child.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = host._tree(project)
    report, errors = host.collect_scenario_owners(project, path, allow_fixture=True)
    assert report == {} and errors
    assert host._tree(project) == before


def test_retry_retains_failed_attempt_and_stops_after_success(handoff):
    project, _, manifest, payload = handoff
    failed = copy.deepcopy(payload["receipts"][0])
    failed.update(status="failed", result_sha256=None, error="fixture execution failure")
    payload["receipts"][0]["attempt"] = 2
    payload["receipts"].insert(0, failed)
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    after_success = copy.deepcopy(failed)
    after_success["attempt"] = 3
    payload["receipts"].append(after_success)
    assert any("after successful" in error for error in host._validate_results(project, manifest, payload, allow_fixture=True))


@pytest.mark.parametrize("status", ["failed", "interrupted", "timeout", "spawn_failed"])
def test_rejected_bound_failure_must_survive_retries_even_when_other_task_result_was_invalid(handoff, tmp_path, status):
    project, _, manifest, payload = handoff
    failed = copy.deepcopy(payload["receipts"][0])
    failed.update(status=status, result_sha256=None, error="fixture explicit prior failure")
    if status == "spawn_failed":
        failed["child_agent_id"] = None
    rejected = copy.deepcopy(payload)
    rejected["receipts"][0] = failed
    rejected["receipts"][1]["result_sha256"] = "0" * 64
    rejected["completed_child_agents"] = 1
    results = tmp_path / "fixture-failure-recovery.json"
    results.write_text(json.dumps(rejected), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1]
    diagnostics = [json.loads(path.read_text(encoding="utf-8")) for path in host._run_path(project, manifest["run_id"]).parent.glob("rejected-*.json")]
    assert any(record["retained_failures"] == [failed] for record in diagnostics)
    before_project = host._tree(project)
    # Rewriting attempt one as success cannot erase a recorded failure.
    results.write_text(json.dumps(payload), encoding="utf-8")
    assert any("failed attempt history changed" in error for error in host.collect_scenario_owners(project, results, allow_fixture=True)[1])
    retry = copy.deepcopy(payload)
    retry["receipts"][0].update(attempt=2, child_agent_id="fixture-retry-child")
    results.write_text(json.dumps(retry), encoding="utf-8")
    assert any("failed attempt history missing" in error for error in host.collect_scenario_owners(project, results, allow_fixture=True)[1])
    retry["receipts"].insert(0, copy.deepcopy(failed))
    retry["receipts"][0]["error"] = "fixture rewritten error"
    results.write_text(json.dumps(retry), encoding="utf-8")
    assert any("failed attempt history changed" in error for error in host.collect_scenario_owners(project, results, allow_fixture=True)[1])
    assert host._tree(project) == before_project
    # Invalid replacement diagnostics cannot poison the original valid retry.
    retry["receipts"][0] = failed
    results.write_text(json.dumps(retry), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1] == []
    collected = json.loads(host._run_path(project, manifest["run_id"]).read_text(encoding="utf-8"))
    assert collected["receipts"][0] == failed and collected["receipts"][1]["attempt"] == 2


@pytest.mark.parametrize("invalid", ["run", "input", "task", "child", "refs", "error", "duplicate"])
def test_invalid_failure_evidence_cannot_poison_same_run_recovery(handoff, tmp_path, invalid):
    project, _, manifest, payload = handoff
    rejected = copy.deepcopy(payload)
    failure = rejected["receipts"][0]
    failure.update(status="failed", result_sha256=None, error="fixture invalid evidence")
    rejected["completed_child_agents"] = 1
    if invalid == "run":
        failure["run_id"] = "fixture-other-run"
    elif invalid == "input":
        failure["input_sha256"] = "0" * 64
    elif invalid == "task":
        failure["task_sha256"] = "0" * 64
    elif invalid == "child":
        failure["child_agent_id"] = None
    elif invalid == "refs":
        failure["tool_records"] = [" "]
    elif invalid == "error":
        failure["error"] = " "
    else:
        rejected["receipts"].insert(0, copy.deepcopy(failure))
    results = tmp_path / "fixture-invalid-failure.json"
    results.write_text(json.dumps(rejected), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1]
    diagnostic = next(host._run_path(project, manifest["run_id"]).parent.glob("rejected-*.json"))
    assert json.loads(diagnostic.read_text(encoding="utf-8"))["retained_failures"] == []
    results.write_text(json.dumps(payload), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1] == []


@pytest.mark.parametrize("target", ["common", "source"])
def test_detects_readonly_writes_in_project_and_external_source(handoff, target):
    project, repository, manifest, payload = handoff
    if target == "common":
        (project / "common").mkdir()
        (project / "common" / "forbidden.py").write_text("changed", encoding="utf-8")
    else:
        (repository / "source.py").write_text("changed", encoding="utf-8")
    errors = host._validate_results(project, manifest, payload, allow_fixture=True)
    assert any("changed outside" in error for error in errors)


def test_collection_is_idempotent_and_fixture_never_passes_real_ownership(handoff, tmp_path):
    project, _, manifest, payload = handoff
    path = tmp_path / "fixture-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rejected, errors = host.collect_scenario_owners(project, path)
    assert rejected == {} and any("fixture" in error for error in errors)
    report, errors = host.collect_scenario_owners(project, path, allow_fixture=True)
    assert errors == []
    assert report["status"] == "results_collected"
    for task in manifest["tasks"]:
        assert (project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8").startswith("# 人工保留的业务说明。\n")
    assert host.collect_scenario_owners(project, path, allow_fixture=True)[0]["idempotent"]
    current = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
    assert current["fixture"] is True
    assert host.ownership_errors(project, manifest=current)
    payload["receipts"][0]["analysis_summary"] = "changed fixture"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert any("overwrite" in error for error in host.collect_scenario_owners(project, path, allow_fixture=True)[1])
    assert json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8")) == current


def test_changed_scenario_cannot_reuse_collected_owner(handoff, tmp_path):
    project, _, _, payload = handoff
    path = tmp_path / "fixture-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    report, errors = host.collect_scenario_owners(project, path, allow_fixture=True)
    assert errors == []
    manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
    directory = project / manifest["tasks"][0]["write_scope"]
    (directory / "业务数据.json").write_text('{"changed": true}', encoding="utf-8")
    assert any("result changed" in error for error in host.ownership_errors(project, manifest=manifest, allow_fixture=True))


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_scenario_digest_preserves_human_text_outside_generation(tmp_path, newline):
    from toolkit.e2e_test_generator.contracts import _write_artifacts

    path = tmp_path / "场景定义.yaml"
    prefix = "# 用途：人工业务说明。\nmeta:\n  id: SCENARIO\n# 生成协调元数据。\n".replace("\n", newline)
    metadata = "generation:\n  mode: main_agent\n  owner: initial\n".replace("\n", newline)
    suffix = "\n# 人工源码说明必须保留。\nsource:\n  - committed-source\n".replace("\n", newline)
    path.write_bytes((prefix + metadata + suffix).encode("utf-8"))
    initial = host.scenario_digest(tmp_path)

    _write_artifacts({path: host._generation_text(path, {"mode": "delegated", "owner": "actual-child"})})
    updated = path.read_bytes().decode("utf-8")
    assert updated.startswith(prefix) and updated.endswith(suffix)
    assert host.scenario_digest(tmp_path) == initial

    for edited in (
        updated.replace("人工源码说明必须保留", "人工源码说明已编辑"),
        updated.replace("id: SCENARIO", "id: 'SCENARIO'"),
        updated.replace(newline, "\r\n" if newline == "\n" else "\n"),
    ):
        path.write_bytes(edited.encode("utf-8"))
        assert host.scenario_digest(tmp_path) != initial


def test_spawn_failure_retries_without_inventing_a_child(handoff):
    project, _, manifest, payload = handoff
    failed = copy.deepcopy(payload["receipts"][0])
    failed.update(status="spawn_failed", child_agent_id=None, result_sha256=None, error="fixture host spawn rejected")
    payload["receipts"][0]["attempt"] = 2
    payload["receipts"].insert(0, failed)
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    payload["parallel"] = True
    payload["observations"] = [{
        "observed_at": "2026-10-13T12:00:00+08:00", "time_source": "coordinator_observed",
        "tool_reference": "fixture://invalid-spawn-observation",
        "active_task_ids": [failed["task_id"] + ":1", payload["receipts"][2]["task_id"] + ":1"],
    }]
    assert host._validate_results(project, manifest, payload, allow_fixture=True)


@pytest.mark.parametrize("status,child,error", [
    ("spawn_failed", "fixture-never-started", "fixture failure"),
    ("failed", None, "fixture failure"),
    ("interrupted", None, "fixture failure"),
    ("timeout", " ", "fixture failure"),
    ("spawn_failed", None, " "),
])
def test_rejects_inconsistent_spawn_and_started_attempts(handoff, status, child, error):
    project, _, manifest, payload = handoff
    failed = copy.deepcopy(payload["receipts"][0])
    failed.update(status=status, child_agent_id=child, result_sha256=None, error=error)
    payload["receipts"][0]["attempt"] = 2
    payload["receipts"].insert(0, failed)
    assert host._validate_results(project, manifest, payload, allow_fixture=True)


def _pending_document_baseline(project):
    from toolkit.core.artifacts import write_version_file
    from toolkit.e2e_test_generator.document_gate import GateReport

    path = project / "analysis/e2e-test-generator-version.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    lock["document_baseline"] = {"git_commit": "a" * 40}
    write_version_file(project, "e2e", lock, path=path)
    state_path = project / ".devflow/e2e-document-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"status": "confirmed", "pending_changes": {"current_commit": "b" * 40}}), encoding="utf-8")
    report = GateReport(recorded_commit="a" * 40, current_commit="b" * 40, baseline_pending=True)
    return path, state_path, report


@pytest.mark.parametrize("command", ["generate", "init"])
def test_cli_prepares_native_tasks_before_any_baseline_advance(handoff, monkeypatch, command):
    from toolkit.e2e_test_generator import cli

    project, _, manifest, _ = handoff
    path, state_path, report = _pending_document_baseline(project)
    # Simulate newly generated, unbound starter assets. This catches an advance
    # before prepare, rather than relying on the old task reference to stop it.
    for task in manifest["tasks"]:
        definition_path = project / task["write_scope"] / "场景定义.yaml"
        definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
        definition["generation"].pop("host_task")
        definition_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    monkeypatch.setattr(cli, "_generate_artifacts", lambda *a, **k: ({}, []))
    if command == "init":
        monkeypatch.setattr(cli, "initialize", lambda *a: [])
        monkeypatch.setattr(cli, "initialize_document_state", lambda *a, **k: {"status": "confirmed"})
        code = cli.init_command(["--project", str(project), "--design-file", "fixture.md"])
    else:
        code = cli.generate_command(["--project", str(project)])
    assert code == 0
    assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "a" * 40
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "generated" and state["pending_changes"]
    for task in manifest["tasks"]:
        definition = yaml.safe_load((project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8"))
        assert definition["generation"]["host_task"]["run_id"] != manifest["run_id"]


def test_non_delegated_generation_keeps_existing_baseline_behavior(handoff, monkeypatch):
    from toolkit.e2e_test_generator import cli
    import shutil

    project, _, manifest, _ = handoff
    path, state_path, report = _pending_document_baseline(project)
    shutil.rmtree(project / manifest["tasks"][1]["write_scope"])
    definition_path = project / manifest["tasks"][0]["write_scope"] / "场景定义.yaml"
    definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
    definition["generation"].pop("host_task")
    definition_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    # This case represents a project with no previous delegation, rather than
    # erasing a real run's ownership tags from the shared handoff fixture.
    monkeypatch.setattr(host, "state_root", lambda: project.parent / "never-delegated-state")
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    monkeypatch.setattr(cli, "_generate_artifacts", lambda *a, **k: ({}, []))
    assert cli.generate_command(["--project", str(project)]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "b" * 40
    assert "pending_changes" not in json.loads(state_path.read_text(encoding="utf-8"))


def test_pending_or_rejected_native_results_preserve_baseline(handoff, tmp_path):
    from toolkit.e2e_test_generator.document_gate import advance_baseline

    project, _, _, payload = handoff
    path, state_path, report = _pending_document_baseline(project)
    before = path.read_bytes(), state_path.read_bytes()
    assert advance_baseline(project, report) is False
    payload["receipts"].pop()
    results = tmp_path / "fixture-incomplete.json"
    results.write_text(json.dumps(payload), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1]
    assert advance_baseline(project, report) is False
    assert (path.read_bytes(), state_path.read_bytes()) == before


@pytest.mark.parametrize("collected", [False, True])
def test_removing_multi_scenario_task_tags_cannot_bypass_baseline_gates(handoff, tmp_path, monkeypatch, collected):
    from toolkit.e2e_test_generator import cli
    from toolkit.e2e_test_generator.document_gate import advance_baseline

    project, _, manifest, payload = handoff
    if collected:
        results = tmp_path / "fixture-collected-before-tag-removal.json"
        results.write_text(json.dumps(payload), encoding="utf-8")
        assert host.collect_scenario_owners(project, results, allow_fixture=True)[1] == []
    path, state_path, report = _pending_document_baseline(project)
    for task in manifest["tasks"]:
        definition_path = project / task["write_scope"] / "场景定义.yaml"
        definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
        definition["generation"] = {"mode": "main_agent", "owner": "main-agent", "write_scope": task["write_scope"], "degradation_reason": None}
        definition_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    before = path.read_bytes(), state_path.read_bytes()
    assert advance_baseline(project, report) is False
    # source-status is a reachable caller that does not run contracts itself.
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    monkeypatch.setattr(cli, "source_version_results", lambda *a: ([], []))
    assert cli.source_status_command(["--project", str(project)]) == 0
    assert (path.read_bytes(), state_path.read_bytes()) == before


@pytest.mark.parametrize("collected", [False, True])
def test_removing_explicit_single_scenario_delegate_tags_cannot_erase_authoritative_run(handoff, tmp_path, monkeypatch, collected):
    from toolkit.e2e_test_generator import cli
    from toolkit.e2e_test_generator.document_gate import advance_baseline
    import shutil

    project, _, old, payload = handoff
    shutil.rmtree(project / old["tasks"][1]["write_scope"])
    prepared = host.prepare_scenario_owners(project, delegate=True)
    task = prepared["tasks"][0]
    receipt = payload["receipts"][0]
    receipt.update({key: task[key] for key in ("run_id", "task_id", "task_sha256", "input_sha256", "write_scope")})
    payload.update(run_id=prepared["run_id"], completed_child_agents=1, receipts=[receipt])
    if collected:
        results = tmp_path / "fixture-explicit-single-results.json"
        results.write_text(json.dumps(payload), encoding="utf-8")
        assert host.collect_scenario_owners(project, results, allow_fixture=True)[1] == []
    path, state_path, report = _pending_document_baseline(project)
    definition_path = project / task["write_scope"] / "场景定义.yaml"
    definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
    definition["generation"] = {"mode": "main_agent", "owner": "main-agent", "write_scope": task["write_scope"], "degradation_reason": None}
    definition_path.write_text(yaml.safe_dump(definition, allow_unicode=True), encoding="utf-8")
    before = path.read_bytes(), state_path.read_bytes()
    assert advance_baseline(project, report) is False
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    monkeypatch.setattr(cli, "source_version_results", lambda *a: ([], []))
    assert cli.source_status_command(["--project", str(project)]) == 0
    assert (path.read_bytes(), state_path.read_bytes()) == before


@pytest.mark.parametrize("failure", [None, "static", "changed_documents"])
@pytest.mark.parametrize("execution_mode", ["native", "serial"])
def test_native_baseline_waits_for_collected_results_and_current_ordered_static_gates(handoff, tmp_path, monkeypatch, failure, execution_mode):
    from toolkit.core.errors import ExitCode
    from toolkit.e2e_test_generator import cli, runner, static_checks

    project, _, old, payload = handoff
    path, state_path, report = _pending_document_baseline(project)
    prepared = host.prepare_scenario_owners(project, serial_approval=_serial_approval(old) if execution_mode == "serial" else None)
    tasks = {task["task_id"]: task for task in prepared["tasks"]}
    payload["run_id"] = prepared["run_id"]
    for receipt in payload["receipts"]:
        receipt.update({key: tasks[receipt["task_id"]][key] for key in ("run_id", "task_sha256", "input_sha256")})
    if execution_mode == "serial":
        manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
        payload = _serial_payload(project, manifest)
    results = tmp_path / "fixture-results.json"
    results.write_text(json.dumps(payload), encoding="utf-8")
    assert host.collect_scenario_owners(project, results, allow_fixture=True)[1] == []
    # Explicit fixture seam: the production baseline guard still rejects fixture
    # runs. Existing domain tests validate these engines; here real CLI stage
    # ordering, seals, owner/result binding and persisted baseline are exercised.
    original_ownership = host.ownership_errors
    monkeypatch.setattr(host, "ownership_errors", lambda *a, **k: original_ownership(*a, **k, allow_fixture=True))
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    monkeypatch.setattr(cli, "source_version_results", lambda *a: ([], []))
    monkeypatch.setattr(runner, "discovery_errors", lambda *a: ([], {}))
    monkeypatch.setattr(runner, "contract_errors", lambda *a: ([], [], {}))
    diagnostics = ["fixture static rejection"] if failure == "static" else []
    monkeypatch.setattr(runner, "static_errors", lambda *a: diagnostics)
    monkeypatch.setattr(static_checks, "static_errors", lambda *a: diagnostics)
    if failure == "changed_documents":
        documents = project / "docs/e2e"
        documents.mkdir(parents=True)
        (documents / "changed.md").write_text("# Changed after the native snapshot\n", encoding="utf-8")
    assert cli.check_command(["--project", str(project), "--gate", "contracts"]) == 0
    assert cli.source_status_command(["--project", str(project)]) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "a" * 40
    for stage in runner.ORDERED_GATE_SEQUENCE:
        code = cli.check_command(["--project", str(project), "--gate", stage])
        assert code == (int(ExitCode.GATE_FAILED) if stage == "static" and failure == "static" else 0)
        if stage != "static":
            assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "a" * 40
            assert json.loads(state_path.read_text(encoding="utf-8"))["pending_changes"]
    assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == ("b" if failure is None else "a") * 40
    assert ("pending_changes" in json.loads(state_path.read_text(encoding="utf-8"))) is (failure is not None)


def test_initial_native_check_can_reach_collection_without_accepting_missing_baseline(handoff, monkeypatch):
    from toolkit.core.artifacts import write_version_file
    from toolkit.e2e_test_generator import document_gate

    project, _, _, _ = handoff
    path, _, _ = _pending_document_baseline(project)
    lock = json.loads(path.read_text(encoding="utf-8"))
    lock["document_baseline"] = {"git_commit": None}
    write_version_file(project, "e2e", lock, path=path)
    document_gate.mark_generated(project)
    monkeypatch.setattr(document_gate, "validate_markdown", lambda *a: ([], []))
    monkeypatch.setattr(document_gate, "validate_scenario_artifacts", lambda *a: [])
    monkeypatch.setattr(document_gate, "_state_issues", lambda *a: [])
    monkeypatch.setattr(document_gate, "_git", lambda project, *args: ("b" * 40 if args == ("rev-parse", "HEAD") else "", None))
    report = document_gate.run_document_gate(project, "check")
    assert report.allowed and report.baseline_pending
    assert document_gate.advance_baseline(project, report) is False
    assert json.loads(path.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] is None
    assert not document_gate.run_document_gate(project, "source-status").allowed
    lock["document_baseline"] = {"git_commit": "invalid"}
    write_version_file(project, "e2e", lock, path=path)
    assert not document_gate.run_document_gate(project, "check").allowed


def _serial_approval(manifest):
    return {"decision": "serial", "reference": "fixture://session/user-explicit-serial-choice",
            "scopes": [task["write_scope"] for task in manifest["tasks"]],
            "native_status": "host_forbidden", "reason": "测试宿主明确禁止启动，不是直接生成授权。",
            "diagnostic_reference": "fixture://session/host-prohibition", "prior_run_ids": [manifest["run_id"]]}


def _serial_payload(project, manifest, *, complete=True):
    receipts = []
    for task in manifest["tasks"]:
        relative = task["write_scope"] + "/业务数据.json"
        if complete:
            (project / relative).write_text('{"fixture_analysis":"仅测试实际场景写入，不是真实会话分析"}', encoding="utf-8")
        receipts.append({**{key: task[key] for key in ("run_id", "task_id", "task_sha256", "input_sha256", "write_scope")},
            "child_agent_id": None, "attempt": 1, "status": "success", "result_sha256": host.scenario_digest(project / task["write_scope"]),
            "tool_records": ["fixture://session/main-agent-analysis"], "written_paths": [relative] if complete else [],
            "analysis_summary": "测试主 Agent 独立源码分析，不是真实执行证明。", "source_evidence": ["fixture-repo#source.py"]})
    return {"protocol_version": 1, "domain": "e2e", "run_id": manifest["run_id"], "mode": "serial", "degraded": True,
            "parallel": False, "completed_child_agents": 0, "receipts": receipts, "observations": [], "fixture": True,
            "serial_approval": manifest["serial_approval"]}


def test_serial_run_collects_actual_main_agent_artifacts_without_rewriting_native_history(handoff, tmp_path):
    from toolkit.e2e_test_generator.contracts import _cross_scenario_errors

    project, _, old, native_payload = handoff
    old_path = host._run_path(project, old["run_id"])
    # The fixture native run retains a failed child attempt and its successful
    # retry. Serial prepares a new run and never resets that history to zero.
    failed = {**native_payload["receipts"][0], "status": "failed", "result_sha256": None, "error": "fixture prior failure"}
    native_payload["receipts"][0]["attempt"] = 2
    native_payload["receipts"].insert(0, failed)
    native_results = tmp_path / "fixture-prior-native-results.json"
    native_results.write_text(json.dumps(native_payload), encoding="utf-8")
    assert host.collect_scenario_owners(project, native_results, allow_fixture=True)[1] == []
    old_files = host._tree(old_path.parent)
    prepared = host.prepare_scenario_owners(project, serial_approval=_serial_approval(old))
    manifest_path = Path(prepared["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert prepared["mode"] == "serial" and prepared["degraded"] is True
    assert prepared["parallel"] is False and prepared["completed_child_agents"] == 0
    assert manifest["run_id"] != old["run_id"]
    assert manifest["serial_approval"]["prior_run_ids"] == [old["run_id"]]
    payload = _serial_payload(project, manifest)
    assert validate_schema(get_schema("e2e.host-results")["document"], payload) == []
    assert host._validate_results(project, manifest, payload, allow_fixture=True) == []
    path = tmp_path / "fixture-serial-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert host.collect_scenario_owners(project, path)[1]  # Fixture cannot become a real report.
    report, errors = host.collect_scenario_owners(project, path, allow_fixture=True)
    assert errors == []
    assert {key: report[key] for key in ("mode", "degraded", "parallel", "completed_child_agents")} == {
        "mode": "serial", "degraded": True, "parallel": False, "completed_child_agents": 0}
    collected = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert host.ownership_errors(project, manifest=collected, allow_fixture=True) == []
    definitions = [(project / task["write_scope"], yaml.safe_load((project / task["write_scope"] / "场景定义.yaml").read_text(encoding="utf-8"))) for task in manifest["tasks"]]
    for _, definition in definitions:
        generation = definition["generation"]
        assert generation["owner"] == "main-agent" and generation["mode"] == "sequential_degraded"
        assert generation["serial_approval"] == {"reference": manifest["serial_approval"]["reference"], "scope": generation["write_scope"]}
    assert _cross_scenario_errors(definitions) == []
    assert host.collect_scenario_owners(project, path, allow_fixture=True)[0]["idempotent"] is True
    assert host._tree(old_path.parent) == old_files
    previous = json.loads(old_path.read_text(encoding="utf-8"))
    assert previous["mode"] == "native" and previous["completed_child_agents"] == 2
    assert previous["receipts"][0]["status"] == "failed"
    payload["receipts"][0]["analysis_summary"] += "changed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert any("overwrite" in error for error in host.collect_scenario_owners(project, path, allow_fixture=True)[1])


@pytest.mark.parametrize("mutation, expected", [
    (lambda p: p.update(mode="native"), "schema"),
    (lambda p: p.update(degraded=False), "schema"),
    (lambda p: p.update(parallel=True), "schema"),
    (lambda p: p.update(completed_child_agents=1), "schema"),
    (lambda p: p["receipts"][0].update(child_agent_id="fixture-old-child"), "cannot claim"),
    (lambda p: p["receipts"][0].update(status="spawn_failed", result_sha256=None, error="fixture"), "spawn attempt"),
    (lambda p: p["receipts"][0].update(status="failed", result_sha256=None, error="fixture"), "incomplete"),
    (lambda p: p["receipts"][0].update(written_paths=["common/forbidden.py"]), "exclusive scope"),
    (lambda p: p["receipts"][0].update(input_sha256="stale"), "cross-run"),
    (lambda p: p.update(serial_approval={**p["serial_approval"], "reference": "fixture://different-choice"}), "approval changed"),
])
def test_serial_receipts_keep_mode_child_scope_input_and_authorization_gates(handoff, mutation, expected):
    project, _, old, _ = handoff
    prepared = host.prepare_scenario_owners(project, serial_approval=_serial_approval(old))
    manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
    payload = _serial_payload(project, manifest)
    mutation(payload)
    before = host._tree(project)
    errors = host._validate_results(project, manifest, payload, allow_fixture=True)
    assert any(expected in error for error in errors), errors
    assert host._tree(project) == before


def test_serial_prepared_templates_cannot_be_collected_or_advance_baseline(handoff, tmp_path):
    from toolkit.e2e_test_generator.document_gate import advance_baseline

    project, _, old, _ = handoff
    baseline, state, report = _pending_document_baseline(project)
    prepared = host.prepare_scenario_owners(project, serial_approval=_serial_approval(old))
    manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
    before = baseline.read_bytes(), state.read_bytes()
    payload = _serial_payload(project, manifest, complete=False)
    path = tmp_path / "fixture-unanalysed-serial.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    errors = host.collect_scenario_owners(project, path, allow_fixture=True)[1]
    assert any("prepared templates" in error for error in errors)
    assert advance_baseline(project, report) is False
    assert (baseline.read_bytes(), state.read_bytes()) == before


@pytest.mark.parametrize("command", ["generate", "init"])
def test_cli_serial_authorization_reaches_new_run_and_collect(handoff, tmp_path, monkeypatch, capsys, command):
    from toolkit.e2e_test_generator import cli

    project, _, old, _ = handoff
    baseline, _, report = _pending_document_baseline(project)
    authorization = tmp_path / "fixture-serial-approval.json"
    authorization.write_text(json.dumps(_serial_approval(old)), encoding="utf-8")
    design = tmp_path / "fixture-cli-design.md"
    design.write_text("# 场景甲\nRule ID: SCENARIO_A\nGET /fixture\nAssertion: status=OK\n", encoding="utf-8")
    protocol = tmp_path / "fixture-cli-openapi.json"
    protocol.write_text(json.dumps({"openapi": "3.0.0", "paths": {"/fixture": {"get": {"operationId": "fixture", "responses": {"200": {"description": "ok"}}}}}}), encoding="utf-8")
    calls = []
    original_generation = cli._generate_artifacts
    def generation(*args, **kwargs):
        calls.append(kwargs)
        return original_generation(*args, **kwargs)
    monkeypatch.setattr(cli, "_generate_artifacts", generation)
    monkeypatch.setattr(cli, "run_document_gate", lambda *a, **k: report)
    if command == "init":
        monkeypatch.setattr(cli, "initialize", lambda *a: [])
        monkeypatch.setattr(cli, "initialize_document_state", lambda *a, **k: {"status": "confirmed"})
    code = getattr(cli, command + "_command")(["--project", str(project), "--design-file", str(design), "--openapi-file", str(protocol), "--serial-approval", str(authorization)])
    assert code == 0
    assert calls[0]["preview"] is True and calls[1]["serial_approval"] == _serial_approval(old)
    line = next(line for line in capsys.readouterr().out.splitlines() if '"host_handoff"' in line)
    prepared = json.loads(line)["host_handoff"]
    manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["mode"] == "serial" and manifest["status"] == "tasks_prepared"
    assert json.loads(baseline.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "a" * 40
    results = tmp_path / "fixture-cli-serial-results.json"
    results.write_text(json.dumps(_serial_payload(project, manifest)), encoding="utf-8")
    original_collect = host.collect_scenario_owners
    monkeypatch.setattr(cli, "collect_scenario_owners", lambda *a: original_collect(*a, allow_fixture=True))
    monkeypatch.setattr(cli, "check_gate", lambda *a: ["fixture domain rejection"])
    assert cli.check_command(["--project", str(project), "--host-results", str(results), "--gate", "contracts"]) != 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["document_baseline"]["git_commit"] == "a" * 40
    assert json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))["status"] == "results_collected"


@pytest.mark.parametrize("command", ["generate", "init"])
@pytest.mark.parametrize("invalid", ["scope", "choice", "diagnostic", "prior"])
def test_invalid_serial_authorization_stops_cli_before_project_or_state_writes(handoff, tmp_path, monkeypatch, capsys, command, invalid):
    from toolkit.e2e_test_generator import cli

    project, _, old, _ = handoff
    approval = _serial_approval(old)
    if invalid == "scope":
        approval["scopes"].pop()
    elif invalid == "choice":
        approval["decision"] = "direct_generate"
    elif invalid == "diagnostic":
        approval["diagnostic_reference"] = " "
    else:
        approval["prior_run_ids"] = []
    path = tmp_path / "fixture-invalid-approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    # Drive actual generation preflight/preview using local design/protocol
    # inputs. No document-state writer is reached, even for scope mismatch.
    design = tmp_path / "fixture-design.md"
    design.write_text("# 场景甲\nRule ID: SCENARIO_A\nGET /fixture\nAssertion: status=OK\n", encoding="utf-8")
    protocol = tmp_path / "fixture-openapi.json"
    protocol.write_text(json.dumps({"openapi": "3.0.0", "paths": {"/fixture": {"get": {"operationId": "fixture", "responses": {"200": {"description": "ok"}}}}}}), encoding="utf-8")
    def unexpected(*a, **k):
        pytest.fail("invalid authorization reached a document or project writer")
    monkeypatch.setattr(cli, "run_document_gate", unexpected)
    monkeypatch.setattr(cli, "initialize_document_state", unexpected)
    monkeypatch.setattr(cli, "initialize", unexpected)
    before_project = host._tree(project)
    before_state = host._tree(host._run_path(project, old["run_id"]).parent.parent)
    code = getattr(cli, command + "_command")(["--project", str(project), "--design-file", str(design), "--openapi-file", str(protocol), "--serial-approval", str(path)])
    assert code != 0
    diagnostic = capsys.readouterr().err
    assert ("complete current scenario scopes" if invalid == "scope" else "serial approval") in diagnostic
    assert host._tree(project) == before_project
    assert host._tree(host._run_path(project, old["run_id"]).parent.parent) == before_state
