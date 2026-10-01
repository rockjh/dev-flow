from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

from devflow.biz_flow_doc_generator.models import EntryPoint, GitInfo, ScanResult
from devflow.biz_flow_doc_generator.orchestration import (
    DelegationUnavailable,
    FileWriteGuard,
    ModuleAgentContext,
    NativeAgentExecutor,
    create_run_manifest,
    run_workflow,
)
from devflow.biz_flow_doc_generator.validation import parse_diagram_ids, parse_matrix_ids
from devflow.biz_flow_doc_generator.validation import validate_entry_analysis
from devflow.core.agents import ClaudeAdapter, CodexAdapter


def _scan() -> ScanResult:
    root = Path(__file__).resolve().parents[2]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    return ScanResult(
        root, GitInfo("main", head, head, False, False), ["Python"], ["FastAPI"],
        [EntryPoint("url:GET /x:app.py:get_x", "url", "GET /x", "get_x", "app.py", 1, "orders", "app.py")],
        ["app.py"], [], "fingerprint",
    )


def test_default_executor_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "devflow.biz_flow_doc_generator.orchestration.discover_agent_executor",
        lambda _run_id: (None, {"type": "unavailable", "adapter": "", "probed": True, "capabilities": {}}),
    )
    scan = _scan()
    mapping = {"modules": [{"name": "orders", "file": "00-orders.md", "entry_ids": [scan.entries[0].entry_id]}]}
    manifest = create_run_manifest(scan, mapping)
    assert manifest["status"] == "failed"
    assert any("DELEGATION_UNAVAILABLE" in error for error in manifest["errors"])


def test_degraded_mode_fails_when_scan_evidence_is_missing() -> None:
    scan = _scan()
    mapping = {"modules": [{"name": "orders", "file": "00-orders.md", "entry_ids": [scan.entries[0].entry_id]}]}
    manifest = create_run_manifest(scan, mapping, allow_degraded=True)
    assert manifest["status"] == "failed"
    assert manifest["degraded"] is True
    assert {task["role"] for task in manifest["tasks"]} == {"coordinator", "module", "entry"}
    assert [event["kind"] for event in manifest["events"]].count("dispatch_batch") == 2


def test_async_workflow_entrypoint_returns_manifest() -> None:
    scan = _scan()
    mapping = {"modules": [{"name": "orders", "file": "00-orders.md", "entry_ids": [scan.entries[0].entry_id]}]}
    manifest = asyncio.run(run_workflow(scan, mapping, allow_degraded=True))
    assert manifest["source_fingerprint"] == "fingerprint"


def test_coverage_parsers_ignore_ids_outside_their_artifact() -> None:
    markdown = """```mermaid
sequenceDiagram
%% devflow:branch id="B-001"
P1->>P1: ok
```
| 分支编号 | 分支条件 | 数据读取与比较 | 数据写入与副作用 | 响应 | 持久化编号 |
| --- | --- | --- | --- | --- | --- |
| `B-001` | x | y | z | ok |  |
"""
    assert parse_diagram_ids(markdown, "branch") == {"B-001"}
    assert parse_matrix_ids(markdown, "branch") == {"B-001"}
    assert parse_matrix_ids(markdown, "persistence") == set()


def test_module_context_batches_all_entries() -> None:
    class Executor:
        def __init__(self):
            self.tasks = []
        def dispatch_batch(self, tasks, parent_task_id, batch_id):
            self.tasks.append((tasks, parent_task_id, batch_id))
            from devflow.biz_flow_doc_generator.orchestration import TaskHandle
            return [TaskHandle(task.task_id, batch_id) for task in tasks]
        def join_batch(self, batch_id):
            return []
        def get_events(self, run_id):
            return []
    executor = Executor()
    context = ModuleAgentContext("orders", [{"entry_id": "e1"}, {"entry_id": "e2"}], "00-orders.md", executor, "module:orders")
    context.dispatch_entry_batch()
    assert [task.entry_id for task in executor.tasks[0][0]] == ["e1", "e2"]


def test_file_write_guard_rejects_entry_writer() -> None:
    guard = FileWriteGuard("module:orders", "00-orders.md")
    guard.assert_allowed("module:orders", "00-orders.md")
    try:
        guard.assert_allowed("entry:e1", "00-orders.md")
    except PermissionError as error:
        assert "WRITE_DENIED" in str(error)
    else:
        raise AssertionError("entry task must not receive a write capability")


def test_manifest_rejects_module_file_escape() -> None:
    scan = _scan()
    mapping = {"modules": [{"name": "orders", "file": "../outside.md", "entry_ids": [scan.entries[0].entry_id]}]}
    manifest = create_run_manifest(scan, mapping, allow_degraded=True)
    assert manifest["status"] == "failed"
    assert any("MODULE_FILE_INVALID" in error for error in manifest["errors"])


def test_entry_agent_cannot_rewrite_non_label_evidence() -> None:
    inventory = {
        "entry_id": "e1", "source_fingerprint": "fp", "participants": ["caller"],
        "calls": ["handler"], "async_actions": [], "external_calls": [],
        "outcomes": ["success"], "source_branch_inventory": [],
        "persistence_inventory": [], "unresolved": [],
    }
    analysis = {
        key: value for key, value in inventory.items()
        if key not in {"source_branch_inventory", "persistence_inventory"}
    }
    analysis.update({"branches": [], "persistence_actions": [], "outcomes": ["invented"]})
    errors = validate_entry_analysis(analysis, inventory)
    assert "SOURCE_EVIDENCE_CHANGED: outcomes" in errors


def test_builtin_adapters_parse_final_structured_messages() -> None:
    response = {
        "parallel": True,
        "capabilities": {
            "real_child_agents": True,
            "read_only_source": True,
            "brokered_module_writes": True,
        },
        "events": [],
        "results": [],
    }
    codex = "\n".join([
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "```json\n" + json.dumps(response) + "\n```"}}),
        json.dumps({"type": "turn.completed"}),
    ])
    assert CodexAdapter().parse(codex) == response
    claude = json.dumps({"type": "result", "is_error": False, "result": json.dumps(response)})
    assert ClaudeAdapter().parse(claude) == response


def test_native_executor_starts_one_entry_process_per_batch(monkeypatch) -> None:
    scan = _scan()
    second = EntryPoint("url:GET /y:app.py:get_y", "url", "GET /y", "get_y", "app.py", 2, "orders", "app.py")
    scan.entries.append(second)
    inventories = {
        entry.entry_id: {
            "entry_id": entry.entry_id, "source_fingerprint": "fingerprint",
            "participants": ["caller", "orders"], "calls": [entry.handler],
            "async_actions": [], "external_calls": [], "outcomes": ["ok"],
            "source_branch_inventory": [], "persistence_inventory": [], "unresolved": [],
        }
        for entry in scan.entries
    }
    monkeypatch.setattr(
        "devflow.biz_flow_doc_generator.orchestration.collect_evidence",
        lambda _scan, **_kwargs: inventories,
    )
    calls = []

    class Backend:
        name = "fake"

    def run(_backend, _executable, prompt, **callbacks):
        callbacks["started"]()
        calls.append(prompt)
        time.sleep(0.01)
        task = json.loads(prompt.split("\n", 1)[1])["task"]
        callbacks["finished"]()
        return {key: inventories[task["entry_id"]][key] for key in (
            "entry_id", "source_fingerprint", "participants", "calls", "async_actions",
            "external_calls", "outcomes", "unresolved",
        )} | {"branches": [], "persistence_actions": []}

    monkeypatch.setattr("devflow.biz_flow_doc_generator.orchestration.run_entry", run)
    executor = NativeAgentExecutor(Backend(), "fake", "run", {"read_only_source": True, "brokered_module_writes": True})
    manifest = create_run_manifest(
        scan,
        {"modules": [{"name": "orders", "file": "00-orders.md", "entry_ids": [entry.entry_id for entry in scan.entries]}]},
        executor=executor,
    )
    assert manifest["status"] == "running"
    assert len(calls) == 2
    assert manifest["parallel"] is True
    assert manifest["executor"]["capabilities"]["real_child_agents"] is True
    assert sum(event["kind"] == "dispatch_batch" and event["task_id"] == "module:orders" for event in manifest["events"]) == 1
