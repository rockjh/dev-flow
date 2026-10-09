from __future__ import annotations

import asyncio
import json
import subprocess
import time
import threading
from pathlib import Path

from toolkit.biz_flow_doc_generator.models import EntryPoint, GitInfo, ScanResult
from toolkit.biz_flow_doc_generator.orchestration import (
    DelegationUnavailable,
    FileWriteGuard,
    ModuleAgentContext,
    NativeAgentExecutor,
    create_run_manifest,
    discover_agent_executor,
    run_workflow,
)
from toolkit.biz_flow_doc_generator.validation import parse_diagram_ids, parse_matrix_ids
from toolkit.biz_flow_doc_generator.validation import validate_entry_analysis
from toolkit.core.agents import ClaudeAdapter, CodexAdapter


def test_removed_builtin_probe_never_discovers_or_starts_an_executor(monkeypatch) -> None:
    class Adapter:
        def probe(self):
            raise AssertionError("removed hidden executor probe must not run")
        def create_executor(self, run_id):
            raise AssertionError("removed hidden executor must not start")
    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.BUILTIN_AGENT_ADAPTERS", (Adapter(),))
    executor, info = discover_agent_executor("run")
    assert executor is None
    assert info["type"] == "unavailable"
    assert info["capabilities"] == {}


def _scan() -> ScanResult:
    root = Path(__file__).resolve().parents[3]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    return ScanResult(
        root, GitInfo("main", head, head, False, False), ["Python"], ["FastAPI"],
        [EntryPoint("url:GET /x:app.py:get_x", "url", "GET /x", "get_x", "app.py", 1, "orders", "app.py")],
        ["app.py"], [], "fingerprint",
    )


def test_default_executor_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "toolkit.biz_flow_doc_generator.orchestration.discover_agent_executor",
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
            from toolkit.biz_flow_doc_generator.orchestration import TaskHandle
            return [TaskHandle(task.task_id, batch_id) for task in tasks]
        def join_batch(self, batch_id):
            return []
        def get_events(self, run_id):
            return []
    executor = Executor()
    context = ModuleAgentContext("orders", [{"entry_id": "e1"}, {"entry_id": "e2"}], "00-orders.md", executor, "module:orders")
    context.dispatch_entry_batch()
    assert [task.entry_id for task in executor.tasks[0][0]] == ["e1", "e2"]


def test_entry_batch_receives_pending_discovery_findings() -> None:
    """父模块收到的待复核记录必须随入口任务传递。"""
    from toolkit.biz_flow_doc_generator.orchestration import TaskHandle

    class Executor:
        def dispatch_batch(self, tasks, parent_task_id, batch_id):
            self.tasks = tasks
            return [TaskHandle(task.task_id, batch_id) for task in tasks]

    executor = Executor()
    findings = ["app.py:1: handler for event is not statically resolvable"]
    context = ModuleAgentContext("orders", [{"entry_id": "e1", "discovery_findings": findings}],
                                 "00-订单.md", executor, "module:orders")
    context.dispatch_entry_batch()
    assert executor.tasks[0].context["discovery_findings"] == findings


def test_critical_resolution_requires_complete_scanned_path() -> None:
    from toolkit.biz_flow_doc_generator.orchestration import _apply_agent_resolutions
    result = _scan()
    result.source_lines = {"app.py": 5}
    finding = "app.py:1: qualified call persist has an unknown receiver type"
    result.unresolved = [finding]
    resolution = {"finding": finding, "resolution": "已核对依赖声明和调用路径", "evidence": ["app.py:1"]}
    assert _apply_agent_resolutions(result, {"e1": {"resolutions": [resolution]}}) == []
    assert result.unresolved == [finding]
    resolution.update(path=["app.py:2"], controls=[], unknowns=[])
    resolution["path"] = ["outside.py:2"]
    assert _apply_agent_resolutions(result, {"e1": {"resolutions": [resolution]}}) == []
    resolution["path"] = ["app.py:2"]
    resolution["unknowns"] = ["仍存在未知分支"]
    assert _apply_agent_resolutions(result, {"e1": {"resolutions": [resolution]}}) == []
    resolution["unknowns"] = []
    assert _apply_agent_resolutions(result, {"e1": {"resolutions": [resolution]}}) == [resolution]
    assert result.unresolved == []


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
    for entry in scan.entries:
        entry.caller = "caller"
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
        "toolkit.biz_flow_doc_generator.orchestration.collect_evidence",
        lambda _scan, **_kwargs: inventories,
    )
    calls = []
    overlap = threading.Barrier(2)

    class Backend:
        name = "fake"

    def run(_backend, _executable, prompt, **callbacks):
        callbacks["started"]()
        calls.append(prompt)
        overlap.wait(timeout=20)
        task = json.loads(prompt.split("\n", 1)[1])["task"]
        callbacks["finished"]()
        return {key: inventories[task["entry_id"]][key] for key in (
            "entry_id", "source_fingerprint", "participants", "calls", "async_actions",
            "external_calls", "outcomes", "unresolved",
        )} | {"branches": [], "persistence_actions": [], "review": {
            "id": task["entry_id"], "trigger": "调用订单查询入口", "purpose": "查询订单状态",
            "input": "订单查询参数", "outcome": "返回订单状态", "failure": "源代码未定义失败分支",
            "status": "confirmed", "confirmed_by": "agent:fake", "steps": [
                {"kind": "action", "text": "查询订单状态", "source": "app.py:1", "participant": "orders"},
                {"kind": "action", "text": "返回订单状态", "source": "app.py:1", "participant": "caller",
                 "sender": "orders", "response": True}]}}

    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.run_entry", run)
    executor = NativeAgentExecutor(Backend(), "fake", "run", {"read_only_source": True, "brokered_module_writes": True})
    manifest = create_run_manifest(
        scan,
        {"modules": [{"name": "orders", "file": "00-orders.md", "entry_ids": [entry.entry_id for entry in scan.entries]}]},
        executor=executor,
    )
    assert manifest["status"] == "running", manifest["errors"]
    assert len(calls) == 2
    assert all(entry.review.outcome == "返回订单状态" for entry in scan.entries)
    assert all(entry.review.confirmed_by == "agent:fake" for entry in scan.entries)
    assert manifest["parallel"] is True
    assert manifest["executor"]["capabilities"]["real_child_agents"] is True
    assert sum(event["kind"] == "dispatch_batch" and event["task_id"] == "module:orders" for event in manifest["events"]) == 1


def test_real_child_not_reading_large_prompt_still_times_out(tmp_path):
    import sys
    import pytest
    from toolkit.core.agents import run_entry

    class Adapter:
        name = "python"

        def command(self, executable):
            return [executable, "-c", "import time; time.sleep(30)"]

    events = []
    begin = time.monotonic()
    with pytest.raises(RuntimeError, match="AGENT_EXECUTOR_TIMEOUT"):
        run_entry(Adapter(), sys.executable, "x" * 2_000_000, cwd=tmp_path,
                  started=lambda: events.append("start"),
                  finished=lambda: events.append("finish"), timeout_seconds=0.2)
    assert time.monotonic() - begin < 5
    assert events == ["start", "finish"]


def test_file_backed_agent_input_and_output_preserve_utf8(tmp_path):
    import sys
    from toolkit.core.agents import run_entry

    class Adapter:
        name = "python"

        def command(self, executable):
            return [executable, "-X", "utf8", "-c",
                    "import sys,json; print(json.dumps({'prompt':sys.stdin.read()},ensure_ascii=False))"]

        def parse(self, output):
            return json.loads(output)

    assert run_entry(Adapter(), sys.executable, "中文源码证据", cwd=tmp_path,
                     timeout_seconds=20) == {"prompt": "中文源码证据"}


def test_parallel_receipts_ignore_module_coordination_and_reuse():
    from toolkit.biz_flow_doc_generator.validation import validate_parallel_execution

    manifest = {"degraded": False, "allow_degraded": False, "parallel": False,
                "tasks": [{"task_id": "entry:a", "role": "entry"}],
                "events": [{"task_id": "entry:a", "kind": "started", "timestamp": "2026-01-01T00:00:00+00:00"},
                           {"task_id": "entry:a", "kind": "success", "timestamp": "2026-01-01T00:00:01+00:00"}]}
    assert validate_parallel_execution(manifest) == []
    manifest["tasks"].append({"task_id": "entry:b", "role": "entry"})
    manifest["events"].extend([
        {"task_id": "entry:b", "kind": "started", "timestamp": "2026-01-01T00:00:02+00:00"},
        {"task_id": "entry:b", "kind": "success", "timestamp": "2026-01-01T00:00:03+00:00"}])
    assert "PARALLEL_EXECUTION_REQUIRED" in validate_parallel_execution(manifest)
    manifest["events"].append({"task_id": "entry:b", "kind": "reused"})
    assert validate_parallel_execution(manifest) == []
    manifest["parallel"] = True
    assert "PARALLEL_EXECUTION_NOT_OBSERVED" in validate_parallel_execution(manifest)


def test_builtin_probe_allows_windows_wrapper_startup(monkeypatch):
    from toolkit.core.agents import probe_adapter

    monkeypatch.setattr("toolkit.core.agents.shutil.which", lambda _name: "codex.cmd")
    seen = []
    def run(command, **kwargs):
        seen.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, " ".join(CodexAdapter().required_flags()), "")
    monkeypatch.setattr("toolkit.core.agents.subprocess.run", run)
    assert probe_adapter(CodexAdapter())[0] == "codex.cmd"
    assert seen == [20]


def test_codex_keeps_only_existing_connection_configuration(tmp_path, monkeypatch):
    from toolkit.core.agents import _codex_connection_args

    (tmp_path / "config.toml").write_text(
        'model="existing-model"\nmodel_provider="custom"\n'
        '[model_providers.custom]\nname="Existing"\nbase_url="https://example.invalid/v1"\n'
        'wire_api="responses"\nenv_key="EXISTING_KEY"\napi_key="never-copy"\n'
        '[mcp_servers.unsafe]\ncommand="unsafe-tool"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    arguments = _codex_connection_args()
    assert 'model="existing-model"' in arguments
    assert 'model_providers.custom.env_key="EXISTING_KEY"' in arguments
    assert all("never-copy" not in value and "unsafe-tool" not in value for value in arguments)
    command = CodexAdapter().command("codex")
    assert "--ignore-user-config" in command and "read-only" in command


def test_codex_accepts_completed_turn_after_transient_reconnect():
    output = "\n".join(json.dumps(event) for event in (
        {"type": "error", "message": "Reconnecting"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok": true}'}},
        {"type": "turn.completed"},
    ))
    assert CodexAdapter().parse(output) == {"ok": True}


def test_entry_source_broker_keeps_complete_referenced_declarations(tmp_path, monkeypatch):
    from toolkit.biz_flow_doc_generator.orchestration import AgentTask

    (tmp_path / "Controller.java").write_text("class Controller { Helper helper; }\n", encoding="utf-8")
    (tmp_path / "Helper.java").write_text("class Helper { Entity entity; }\n", encoding="utf-8")
    (tmp_path / "Entity.java").write_text('@Table(name="vehicle_order")\nclass Entity {}\n', encoding="utf-8")
    scan = _scan()
    scan.files = ["Controller.java", "Helper.java", "Entity.java"]
    inventory = {"entry_id": "entry", "source_fingerprint": "fp", "participants": [], "calls": [],
                 "async_actions": [], "external_calls": [], "outcomes": [],
                 "source_branch_inventory": [], "persistence_inventory": [], "unresolved": []}
    def run(_backend, _exe, prompt, **kwargs):
        payload = json.loads(prompt.split("\n", 1)[1])
        assert set(payload["source_code"]) == set(scan.files)
        assert payload["source_code"]["Entity.java"].startswith('@Table(name="vehicle_order")')
        assert "cwd" not in kwargs  # 子进程隔离，项目配置不进入执行上下文。
        kwargs["started"]()
        kwargs["finished"]()
        return {"entry_id": "entry"}
    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.run_entry", run)
    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.validate_entry_analysis", lambda *_: [])
    executor = NativeAgentExecutor(CodexAdapter(), "codex", "source-test", {})
    executor.cwd, executor.scan = tmp_path, scan
    task = AgentTask("entry:entry", "entry", "车辆订单", "entry",
                     context={"source_file": "Controller.java", "inventory": inventory})
    assert executor._execute(task, "batch").status == "success"
    assert [event.kind for event in executor.get_events("source-test")] == ["started", "process_finished", "success"]
    assert executor.parallel is False


def test_business_failure_wording_allows_specific_result_only():
    from toolkit.biz_flow_doc_generator.validation import validate_markdown_structure

    def errors(label):
        markdown = '<!-- biz-flow-entry: e1 -->\n## 授权登录\n入口描述：授权登录请求\n- 校验授权并返回结果\n\n```mermaid\nsequenceDiagram\nautonumber\nparticipant P0 as 登录客户端\nparticipant P1 as 用户认证\nP0->>P1: 授权登录\nP1-->>P0: ' + label + '\n```\n'
        return validate_markdown_structure(markdown, {"e1": {"branches": [], "persistence_actions": []}})
    assert not any("VAGUE_BUSINESS_RESULT" in error for error in errors("返回授权或账号处理失败"))
    for label in ("处理失败", "调用处理方法", "获取处理结果"):
        assert "VAGUE_BUSINESS_RESULT: e1" in errors(label)


def test_masked_credentials_do_not_clear_business_control_unknowns():
    from toolkit.biz_flow_doc_generator.validation import validate_no_critical_unresolved

    masked_value = {"code": "SESSION_TOKEN_VALUE_REDACTED", "critical": False,
                    "reason": "仅敏感值遮蔽，写入会话及返回路径已有源码证明，不推断令牌值", "evidence": "app.py:53"}
    assert validate_no_critical_unresolved({"unresolved": [masked_value]}) == []
    masked_control = {**masked_value, "critical": True,
                      "reason": "被遮蔽表达式决定授权分支，无法证明状态流转"}
    assert any("CRITICAL_UNRESOLVED" in error for error in
               validate_no_critical_unresolved({"unresolved": [masked_control]}))
    assert "UNRESOLVED_CLASSIFICATION_MISSING" in validate_no_critical_unresolved({
        "unresolved": [{"code": "SESSION_TOKEN_VALUE_REDACTED", "critical": False}]})


def test_caught_python_raise_retains_business_failure_and_silent_exclusion():
    from toolkit.biz_flow_doc_generator.evidence import PythonEvidenceAdapter, SourceContext

    entry = EntryPoint("e1", "url", "POST /login", "login", "app.py", 1, "用户认证", "app.py")
    def branch(body, function="login", full=None):
        context = SourceContext(entry, "app.py", function, 1, body, {"app.py": full or body})
        return next(item for item in PythonEvidenceAdapter().branches(context) if item.condition.startswith("raise "))
    for effect in ('return {"status": 401, "error": str(error)}', 'save_failure(error)', 'raise error'):
        source = 'def login():\n    try:\n        raise LoginError("EXPIRED")\n    except LoginError as error:\n        ' + effect + '\n'
        value = branch(source)
        assert value.reachability == "reachable" and value.business_relevant is True
    for effect in ('pass', 'logger.warning("辅助异常")'):
        source = 'def login():\n    try:\n        raise LoginError("AUXILIARY")\n    except LoginError:\n        ' + effect + '\n'
        value = branch(source)
        assert value.reachability == "reachable" and value.business_relevant is False
    skipped = 'def login():\n    try:\n        if should_skip:\n            raise LoginError("SKIP")\n        save_success()\n    except LoginError:\n        pass\n'
    assert branch(skipped).business_relevant is True
    helper = 'def load():\n    try:\n        raise LoginError("AUXILIARY")\n    except LoginError:\n        return []\n'
    discarded = helper + '\ndef login():\n    load()\n'
    assert branch(helper, "load", discarded).business_relevant is False
    context = SourceContext(entry, "app.py", "load", 1, helper, {"app.py": discarded})
    assert all(item.business_relevant is False for item in PythonEvidenceAdapter().branches(context))
    consumed = helper + '\ndef login():\n    return load()\n'
    assert branch(helper, "load", consumed).business_relevant is True
    context = SourceContext(entry, "app.py", "load", 1, helper, {"app.py": consumed})
    assert all(item.business_relevant is True for item in PythonEvidenceAdapter().branches(context))
    skipped_write = helper + '    save_success()\n' + '\ndef login():\n    load()\n'
    assert branch(helper + '    save_success()\n', "load", skipped_write).business_relevant is True
    skipped_return = helper + '    return save_success()\n' + '\ndef login():\n    load()\n'
    assert branch(helper + '    return save_success()\n', "load", skipped_return).business_relevant is True


def test_raise_inside_handler_is_not_caught_by_same_try():
    from toolkit.biz_flow_doc_generator.evidence import PythonEvidenceAdapter, SourceContext

    source = 'def login():\n    try:\n        authenticate()\n    except LoginError:\n        raise LoginError("RETHROWN")\n'
    entry = EntryPoint("e1", "url", "POST /login", "login", "app.py", 1, "用户认证", "app.py")
    context = SourceContext(entry, "app.py", "login", 1, source, {"app.py": source})
    value = next(item for item in PythonEvidenceAdapter().branches(context) if item.condition.startswith("raise "))
    assert value.reachability == "reachable" and value.business_relevant is True


def test_review_cache_rechecks_ordered_renderer_without_mutating_history(tmp_path, monkeypatch):
    """合法审核继续复用；旧步骤缺响应时重新委派，历史执行记录保持原样。"""
    from copy import deepcopy
    from toolkit.biz_flow_doc_generator.orchestration import finish_run, write_module
    from toolkit.biz_flow_doc_generator.validation import digest, validate_run

    entry = EntryPoint("entry-orders", "url", "GET /orders", "query", "app.py", 1,
                       "orders", "app.py", business_name="查询订单", caller="caller")
    scan = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                      ["Python"], [], [entry], ["app.py"], [], "fingerprint",
                      source_lines={"app.py": 1})
    (tmp_path / "app.py").write_text("def query(): return 'ok'\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    mapping = {"modules": [{"name": "orders", "file": "00-订单.md", "entry_ids": [entry.entry_id]}]}
    inventory = {
        "entry_id": entry.entry_id, "source_fingerprint": "fingerprint",
        "participants": ["caller", "orders"], "calls": ["query"], "async_actions": [],
        "external_calls": [], "outcomes": ["ok"], "source_branch_inventory": [],
        "persistence_inventory": [], "unresolved": [],
    }
    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.collect_evidence",
                        lambda _scan, **_kwargs: {entry.entry_id: deepcopy(inventory)})
    delegated = []

    class Backend:
        name = "fake"

    def run(_backend, _executable, prompt, **callbacks):
        callbacks["started"]()
        delegated.append(prompt)
        callbacks["finished"]()
        return {key: deepcopy(inventory[key]) for key in (
            "entry_id", "source_fingerprint", "participants", "calls", "async_actions",
            "external_calls", "outcomes", "unresolved",
        )} | {"branches": [], "persistence_actions": [], "review": {
            "id": entry.entry_id, "trigger": "调用订单查询入口", "purpose": "查询订单状态",
            "input": "订单查询参数", "outcome": "返回订单状态", "failure": "源码未定义失败分支",
            "status": "confirmed", "confirmed_by": "agent:fake", "steps": [
                {"kind": "action", "text": "查询订单状态", "source": "app.py:1", "participant": "orders"},
                {"kind": "action", "text": "返回订单状态", "source": "app.py:1", "participant": "caller",
                 "sender": "orders", "response": True}]}}

    monkeypatch.setattr("toolkit.biz_flow_doc_generator.orchestration.run_entry", run)

    def execute(previous=None):
        executor = NativeAgentExecutor(Backend(), "fake", "run", {
            "read_only_source": True, "brokered_module_writes": True, "real_child_agents": True})
        return create_run_manifest(scan, mapping, executor=executor, docs_root=docs, previous_run=previous)

    previous = execute()
    assert previous["status"] == "running", previous["errors"]
    write_module(previous, "orders", docs / "00-订单.md", previous["module_results"]["orders"]["markdown"])
    finish_run(previous)
    previous["status"] = "success"
    previous["report"].update(stable=True, branch_coverage=1.0, persistence_coverage=1.0)
    assert validate_run(previous) == []
    snapshot = deepcopy(previous)
    reused = execute(previous)
    assert reused["status"] == "running", reused["errors"]
    assert len(delegated) == 1 and any(event["kind"] == "reused" for event in reused["events"])
    assert previous == snapshot

    legacy = deepcopy(previous)
    old_entry_hash = digest(legacy["entry_analyses"][entry.entry_id])
    old_module_hash = digest(legacy["module_results"]["orders"])
    legacy["entry_analyses"][entry.entry_id]["review"]["steps"][-1]["response"] = False
    new_entry_hash = digest(legacy["entry_analyses"][entry.entry_id])
    new_module_hash = digest(legacy["module_results"]["orders"])
    # 历史记录在旧契约下自洽：其字节、回执和摘要均完整，只是步骤不满足新绘图语义。
    encoded = json.dumps(legacy).replace(old_entry_hash, new_entry_hash).replace(old_module_hash, new_module_hash)
    legacy = json.loads(encoded)
    assert validate_run(legacy) == []
    legacy_snapshot = deepcopy(legacy)
    refreshed = execute(legacy)
    assert refreshed["status"] == "running", refreshed["errors"]
    assert len(delegated) == 2
    assert not any(event["kind"] == "reused" for event in refreshed["events"])
    assert legacy == legacy_snapshot
