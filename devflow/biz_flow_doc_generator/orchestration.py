"""Host delegation, execution receipts and module-owned artifact commits."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from ..core.redaction import redact
from ..core.schema import BIZ_FLOW_SCHEMA_VERSION, BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA
from ..core.agents import BUILTIN_AGENT_ADAPTERS as BUILTIN_BACKENDS, probe_adapter, run_entry
from .evidence import BRANCH_ADAPTERS, PERSISTENCE_ADAPTERS, collect_evidence
from .models import ScanResult, TaskEvent, TaskRecord
from .validation import digest, validate_entry_analysis, validate_markdown_structure, validate_run


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_id: str
    role: str
    module_id: str | None = None
    entry_id: str | None = None
    writable_file: str | None = None
    context: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TaskHandle:
    task_id: str
    batch_id: str


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    status: str
    value: dict[str, Any] | None = None
    error: str | None = None


class AgentExecutor(Protocol):
    def dispatch_batch(self, tasks: list[AgentTask], parent_task_id: str, batch_id: str) -> list[TaskHandle]: ...
    def join_batch(self, batch_id: str) -> list[TaskResult]: ...
    def get_events(self, run_id: str) -> list[TaskEvent]: ...


class DelegationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NativeAgentAdapter:
    """Bridge a host-specific CLI adapter into the common JSONL broker."""

    backend: Any

    @property
    def name(self) -> str:
        return str(self.backend.name)

    def probe(self) -> dict[str, bool] | bool:
        executable, capabilities = probe_adapter(self.backend)
        return capabilities if executable else False

    def create_executor(self, run_id: str) -> AgentExecutor:
        executable, capabilities = probe_adapter(self.backend)
        if not executable:
            raise DelegationUnavailable(f"DELEGATION_UNAVAILABLE: {self.name} CLI is unavailable")
        return NativeAgentExecutor(self.backend, executable, run_id, capabilities)


BUILTIN_AGENT_ADAPTERS = tuple(NativeAgentAdapter(adapter) for adapter in BUILTIN_BACKENDS)


def discover_agent_executor(run_id: str) -> tuple[AgentExecutor | None, dict[str, Any]]:
    """Choose an explicit host override or one of the static built-ins."""
    configured = os.environ.get("DEVFLOW_AGENT_EXECUTOR", "").strip()
    if configured:
        candidate = SubprocessAgentExecutor(configured, run_id, executor_type="configured", adapter_name="configured")
        capabilities = candidate.probe()
        return (candidate if capabilities else None), {
            "type": "configured", "adapter": "configured", "probed": True,
            "capabilities": capabilities or {},
        }
    for adapter in BUILTIN_AGENT_ADAPTERS:
        try:
            probe = adapter.probe()
            if probe is False:
                continue
            capabilities = {
                str(key): value for key, value in (probe.items() if isinstance(probe, dict) else ())
                if isinstance(value, bool)
            }
            required = {"real_child_agents", "read_only_source", "brokered_module_writes"}
            if any(capabilities.get(key) is False for key in required):
                continue
            executor = adapter.create_executor(run_id)
            return executor, {
                "type": str(getattr(adapter, "name", "registered")),
                "adapter": str(getattr(adapter, "name", "registered")),
                "probed": True,
                "capabilities": capabilities,
            }
        except (OSError, RuntimeError, ValueError, TypeError):
            continue
    return None, {"type": "unavailable", "adapter": "", "probed": True, "capabilities": {}}


class NativeAgentExecutor:
    """Own entry processes and receipts; module tasks render through the broker."""

    def __init__(self, backend: Any, executable: str, run_id: str, capabilities: dict[str, bool]):
        self.backend, self.executable, self.run_id = backend, executable, run_id
        self.cwd: Path | None = None
        self.scan: ScanResult | None = None
        self.capabilities = dict(capabilities)
        self.parallel = False
        self._batches: dict[str, tuple[str, list[AgentTask]]] = {}
        self._events: list[TaskEvent] = []
        self._lock = threading.Lock()
        self._active_processes = 0
        self._started_processes = 0

    def event(self, kind, task, batch=None, ids=(), result=None):
        with self._lock:
            self._events.append(TaskEvent(self.run_id, len(self._events) + 1, kind, task,
                _now(), batch, tuple(ids), result_hash=digest(result) if result is not None else None))

    def dispatch_batch(self, tasks, parent_task_id, batch_id):
        if batch_id in self._batches or not tasks:
            raise ValueError("BATCH_INVALID")
        self._batches[batch_id] = (parent_task_id, tasks)
        self.event("dispatch_batch", parent_task_id, batch_id, [task.task_id for task in tasks])
        return [TaskHandle(task.task_id, batch_id) for task in tasks]

    def join_batch(self, batch_id):
        parent, tasks = self._batches.pop(batch_id)
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = [pool.submit(self._execute, task, batch_id) for task in tasks]
            results = [future.result() for future in futures]
        if self._started_processes:
            self.capabilities.update({
                "real_child_agents": True, "read_only_source": True, "brokered_module_writes": True,
            })
            self.parallel = True
        self.event("join_batch", parent, batch_id)
        return results

    def _execute(self, task: AgentTask, batch_id: str) -> TaskResult:
        from .documents import render_module

        try:
            if task.role == "module" and task.context.get("reuse_value"):
                value = task.context["reuse_value"]
                self.event("started", task.task_id, batch_id)
                entry_batch = "entry-batch:" + uuid.uuid4().hex
                entry_ids = [spec["entry_id"] for spec in task.context["entry_specs"]]
                self.event("dispatch_batch", task.task_id, entry_batch, entry_ids)
                for entry_id in entry_ids:
                    analysis = value["entry_analyses"][entry_id]
                    self.event("started", f"entry:{entry_id}", entry_batch)
                    self.event("success", f"entry:{entry_id}", entry_batch, result=analysis)
                self.event("join_batch", task.task_id, entry_batch)
                self.event("ready", task.task_id, batch_id, result=value)
                self.parallel = True
                return TaskResult(task.task_id, "success", value)
            if task.role == "entry":
                inventory = task.context["inventory"]
                prompt = (
                    "Analyze this business entry using the supplied authoritative source inventory. "
                    "Source access is read-only. Return only the entry analysis JSON object; do not "
                    "return events, capabilities, Markdown or file writes. Preserve all machine "
                    "evidence fields exactly. Add concise Chinese branch labels/outcome_labels, "
                    "persistence operation_label and (only when missing) a source-backed Chinese "
                    "display_name. Do not invent evidence or resolve critical unknowns by guessing.\n"
                    + json.dumps({"task": asdict(task), "schema": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA}, ensure_ascii=False)
                )

                def started():
                    with self._lock:
                        self._active_processes += 1
                        self._started_processes += 1
                        self.parallel |= self._active_processes > 1
                    self.event("started", task.task_id, batch_id)

                def finished():
                    with self._lock:
                        self._active_processes -= 1

                value = run_entry(self.backend, self.executable, prompt, cwd=self.cwd,
                                  started=started, finished=finished)
                if isinstance(value, dict) and "business_name" in inventory:
                    value = {
                        **{key: inventory.get(key) for key in ("business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason")},
                        **value,
                    }
                errors = validate_entry_analysis(value, inventory)
                if errors or value != redact(value):
                    raise ValueError("; ".join(errors) or "AGENT_RESULT_NOT_REDACTED")
                self.event("success", task.task_id, batch_id, result=value)
            elif task.role == "module":
                self.event("started", task.task_id, batch_id)
                context = ModuleAgentContext(task.module_id, task.context["entry_specs"],
                                             task.writable_file, self, task.task_id)
                context.dispatch_entry_batch()
                entries = self.join_batch(context.batch_id)
                analyses = {result.value["entry_id"]: result.value for result in entries}
                module_entries = [replace(entry, agent_branches=analyses[entry.entry_id]["branches"],
                                          agent_persistence=analyses[entry.entry_id]["persistence_actions"])
                                  for entry in self.scan.entries if entry.entry_id in analyses]
                content = str(redact(render_module(task.module_id, module_entries, self.scan.git, self.scan,
                    comparison="current", module_meta=task.context.get("module_meta", {}))))
                value = {"module_id": task.module_id, "entry_analyses": analyses, "markdown": content}
                self.event("ready", task.task_id, batch_id, result=value)
            else:
                raise ValueError("TASK_ROLE_INVALID")
            return TaskResult(task.task_id, "success", value)
        except Exception:
            self.event("failed", task.task_id, batch_id)
            raise

    def get_events(self, run_id):
        if run_id != self.run_id:
            return []
        return [replace(event, sequence=index) for index, event in enumerate(self._events, 1)]


class SubprocessAgentExecutor:
    """One explicit trusted host, with real lifecycle receipts (never synthesized).

    The host must sandbox its agents: source is read-only and module writes use
    the broker below. JSON results alone cannot prove process isolation.
    """

    def __init__(self, command: str | list[str], run_id: str, *, executor_type: str = "configured", adapter_name: str = "configured"):
        parts = shlex.split(command, posix=os.name != "nt") if isinstance(command, str) else list(command)
        self.command = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part for part in parts]
        self.run_id = run_id
        self.executor_type = executor_type
        self.adapter_name = adapter_name
        self._batches = {}
        self._events = []
        self.parallel = False
        self.capabilities: dict[str, Any] = {}

    def probe(self) -> dict[str, bool]:
        """Read capabilities only; never send a workflow payload during probing."""
        if not self.command:
            return {}
        try:
            result = subprocess.run(
                [*self.command, "--version"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if result.returncode:
            return {}
        self.capabilities = {"read_only_source": True, "brokered_module_writes": True}
        return dict(self.capabilities)

    def dispatch_batch(self, tasks, parent_task_id, batch_id):
        if batch_id in self._batches or not tasks:
            raise ValueError("BATCH_INVALID")
        payload = {"protocol_version": 1, "run_id": self.run_id,
                   "batch_id": batch_id, "parent_task_id": parent_task_id,
                   "tasks": [asdict(task) for task in tasks]}
        try:
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8")
        except OSError as exc:
            raise DelegationUnavailable("DELEGATION_UNAVAILABLE: cannot start configured host") from exc
        self._batches[batch_id] = (process, payload)
        self._events.append(TaskEvent(self.run_id, len(self._events) + 1, "dispatch_batch",
                                      parent_task_id, _now(), batch_id,
                                      tuple(task.task_id for task in tasks)))
        return [TaskHandle(task.task_id, batch_id) for task in tasks]

    def join_batch(self, batch_id):
        process, payload = self._batches.pop(batch_id)
        try:
            output, error = process.communicate(json.dumps(payload, ensure_ascii=False) + "\n", timeout=1800)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("AGENT_EXECUTOR_TIMEOUT") from None
        if process.returncode:
            raise RuntimeError(f"AGENT_EXECUTOR_FAILED: host exit {process.returncode}")
        try:
            response: dict[str, Any] | None = None
            for line in reversed(output.splitlines()):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    response = value
                    break
            if response is None:
                raise ValueError("missing JSONL response")
            if response.get("parallel") is not True:
                self.parallel = False
                raise DelegationUnavailable("DELEGATION_UNAVAILABLE: host did not confirm parallel child execution")
            capabilities = response["capabilities"]
            if not isinstance(capabilities, dict):
                raise ValueError("capabilities must be an object")
            self.capabilities = dict(capabilities)
            if (capabilities.get("real_child_agents") is not True
                    or capabilities.get("read_only_source") is not True
                    or capabilities.get("brokered_module_writes") is not True):
                raise DelegationUnavailable("DELEGATION_UNAVAILABLE: host lacks required capabilities")
            if response.get("writes"):
                raise PermissionError("WRITE_DENIED: host returned direct file writes")
            events = [TaskEvent(**event) for event in response["events"]]
            if not events or any(event.run_id != self.run_id for event in events):
                raise ValueError("missing or foreign execution receipts")
            dispatch = payload["batch_id"]
            expected_ids = {task["task_id"] for task in payload["tasks"]}
            known_ids = set(expected_ids)
            for task in payload["tasks"]:
                known_ids.update(f"entry:{spec['entry_id']}"
                                 for spec in (task.get("context") or {}).get("entry_specs", []))
            # The host may return nested entry-batch receipts created by a
            # module agent. Only the dispatch receipt for this outer batch is
            # supplied by the Python broker; nested dispatches remain evidence.
            events = [event for event in events
                      if not (event.kind == "dispatch_batch" and event.batch_id == dispatch)]
            if any(event.task_id not in known_ids and event.task_id != "coordinator" for event in events):
                raise ValueError("foreign task execution receipt")
            task_roles = {task["task_id"]: task["role"] for task in payload["tasks"]}
            for task_id, role in task_roles.items():
                expected_kind = "ready" if role == "module" else "success"
                if not any(event.task_id == task_id and event.kind == expected_kind for event in events):
                    raise ValueError(f"missing {expected_kind} receipt for {task_id}")
            results = [TaskResult(**result) for result in response["results"]]
            if {result.task_id for result in results} != expected_ids:
                raise ValueError("missing or duplicate task result")
            self._events.extend(events)
            return results
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("AGENT_EXECUTOR_PROTOCOL_INVALID") from exc

    def get_events(self, run_id):
        if run_id != self.run_id:
            return []
        return [replace(event, sequence=index) for index, event in enumerate(self._events, 1)]


@dataclass(slots=True)
class ModuleAgentContext:
    module_id: str
    entry_specs: list[dict[str, Any]]
    writable_file: str
    executor: AgentExecutor
    parent_task_id: str
    batch_id: str = ""

    def dispatch_entry_batch(self):
        if self.batch_id:
            raise RuntimeError("ENTRY_BATCH_ALREADY_DISPATCHED")
        if self.parent_task_id != f"module:{self.module_id}":
            raise RuntimeError("ENTRY_BATCH_PARENT_INVALID")
        self.batch_id = "entry-batch:" + uuid.uuid4().hex
        tasks = [AgentTask(f"entry:{spec['entry_id']}", "entry", self.module_id,
                           spec["entry_id"], context=spec) for spec in self.entry_specs]
        handles = self.executor.dispatch_batch(tasks, self.parent_task_id, self.batch_id)
        if {(h.task_id, h.batch_id) for h in handles} != {(t.task_id, self.batch_id) for t in tasks} or len(handles) != len(tasks):
            raise RuntimeError("ENTRY_BATCH_HANDLE_MISMATCH")
        return handles

    def join(self):
        if not self.batch_id:
            raise RuntimeError("ENTRY_BATCH_NOT_DISPATCHED")
        return self.executor.join_batch(self.batch_id)


_TIMESTAMP_LOCK = threading.Lock()
_LAST_TIMESTAMP: datetime | None = None


def _now():
    """Return strictly increasing UTC timestamps for ordered receipts."""
    global _LAST_TIMESTAMP
    with _TIMESTAMP_LOCK:
        value = datetime.now(timezone.utc)
        if _LAST_TIMESTAMP is not None and value <= _LAST_TIMESTAMP:
            value = _LAST_TIMESTAMP + timedelta(microseconds=1)
        _LAST_TIMESTAMP = value
        return value.isoformat()


def _evidence_analysis(entry_id, inventory):
    value = redact(inventory)
    branches = [{**branch, "label": branch["condition"],
                 "outcome_labels": branch["outcomes"],
                 "exclusion_reason": "源码证据确认不传播到入口" if branch["business_relevant"] is False else ""}
                for branch in value["source_branch_inventory"]]
    return {key: value[key] for key in ("entry_id", "source_fingerprint", "participants", "calls",
            "async_actions", "external_calls", "outcomes", "unresolved", "business_name",
            "trigger_summary", "source_evidence", "scope_status", "exclusion_reason")} | {
            "branches": branches, "persistence_actions": [
                {**action, "operation_label": action["operation"]} for action in value["persistence_inventory"]]}


class DegradedExecutor:
    """Explicit serial fallback. It is never evidence of real delegation."""

    def __init__(self, scan, inventories, run_id):
        self.scan, self.inventories, self.run_id = scan, inventories, run_id
        self._events, self._batches = [], {}

    def event(self, kind, task, batch=None, ids=(), result=None):
        self._events.append(TaskEvent(self.run_id, len(self._events) + 1, kind, task,
                                      _now(), batch, tuple(ids), result_hash=digest(result) if result is not None else None))

    def dispatch_batch(self, tasks, parent_task_id, batch_id):
        self._batches[batch_id] = (parent_task_id, tasks)
        self.event("dispatch_batch", parent_task_id, batch_id, [t.task_id for t in tasks])
        return [TaskHandle(t.task_id, batch_id) for t in tasks]

    def join_batch(self, batch_id):
        from .documents import render_module
        parent, tasks = self._batches.pop(batch_id)
        results = []
        for task in tasks:
            self.event("started", task.task_id, batch_id)
            if task.role == "entry":
                value = _evidence_analysis(task.entry_id, self.inventories[task.entry_id])
                errors = validate_entry_analysis(value, self.inventories[task.entry_id])
                if errors:
                    self.event("failed", task.task_id, batch_id)
                    raise ValueError("; ".join(errors))
                self.event("success", task.task_id, batch_id, result=value)
            else:
                context = ModuleAgentContext(task.module_id, task.context["entry_specs"],
                                             task.writable_file, self, task.task_id)
                context.dispatch_entry_batch()
                entries = context.join()
                analyses = {result.value["entry_id"]: result.value for result in entries}
                module_entries = [entry for entry in self.scan.entries if entry.entry_id in analyses]
                for entry in module_entries:
                    entry.agent_branches = analyses[entry.entry_id]["branches"]
                    entry.agent_persistence = analyses[entry.entry_id]["persistence_actions"]
                content = str(redact(render_module(
                    task.module_id, module_entries, self.scan.git, self.scan,
                    comparison="current", module_meta=task.context.get("module_meta", {}))))
                value = {"module_id": task.module_id, "entry_analyses": analyses, "markdown": content}
                self.event("ready", task.task_id, batch_id, result=value)
            results.append(TaskResult(task.task_id, "success", value))
        self.event("join_batch", parent, batch_id)
        return results

    def get_events(self, run_id):
        return list(self._events)


def fail_run(manifest, errors):
    manifest["status"] = "failed"
    manifest["errors"] = list(dict.fromkeys([
        *manifest["errors"], *[str(redact(error)) for error in errors]
    ]))
    manifest["report"]["stable"] = False
    for task in manifest["tasks"]:
        if task["role"] != "entry" or task["status"] != "success":
            task.update(status="failed", error="; ".join(manifest["errors"]), finished_at=_now())


def create_run_manifest(scan: ScanResult, mapping: dict, *, allow_degraded=False, executor=None,
                        project_root=None, docs_root=None, module_filter=None,
                        previous_run=None,
                        branch_adapters=BRANCH_ADAPTERS, persistence_adapters=PERSISTENCE_ADAPTERS) -> dict:
    run_id = uuid.uuid4().hex
    modules = {item["name"]: {"file": item["file"], "entry_ids": item["entry_ids"]} for item in mapping["modules"]}
    expected = [e for spec in modules.values() for e in spec["entry_ids"]]
    selected_executor = executor
    executor_info: dict[str, Any]
    if selected_executor is None and not allow_degraded:
        selected_executor, executor_info = discover_agent_executor(run_id)
    elif selected_executor is None:
        selected_executor, executor_info = None, {"type": "degraded", "adapter": "", "probed": True, "capabilities": {}}
    else:
        executor_info = {
            "type": str(getattr(selected_executor, "executor_type", "provided")),
            "adapter": str(getattr(selected_executor, "adapter_name", "provided")),
            "probed": True,
            "capabilities": {
                str(key): value for key, value in dict(getattr(selected_executor, "capabilities", {})).items()
                if isinstance(value, bool)
            },
        }
    if selected_executor is not None and hasattr(selected_executor, "cwd"):
        selected_executor.cwd = Path(project_root or scan.root).resolve()
    if selected_executor is not None and hasattr(selected_executor, "run_id"):
        selected_executor.run_id = run_id
    if isinstance(selected_executor, NativeAgentExecutor):
        selected_executor.scan = scan
    manifest = {
        "schema_version": BIZ_FLOW_SCHEMA_VERSION, "run_id": run_id,
        "source_fingerprint": scan.source_fingerprint, "mapping_hash": digest(modules),
        "project_root": str((project_root or scan.root).resolve()),
        "docs_root": str((docs_root or scan.root / "docs/biz-flow").resolve()),
        "status": "running", "parallel": False, "degraded": False, "allow_degraded": allow_degraded,
        "executor": executor_info,
        "modules": modules, "tasks": [asdict(TaskRecord(run_id, "coordinator", None, "coordinator",
                                                     status="running", started_at=_now()))],
        "events": [], "inventories": {}, "entry_analyses": {}, "module_results": {},
        "document_hashes": {}, "errors": [],
        "report": {"module_count": len(modules), "entry_count": len(expected),
                   "module_tasks": len(modules), "entry_tasks": len(expected),
                   "parallel": False, "degraded": False, "branch_coverage": 0.0,
                   "persistence_coverage": 0.0, "critical_unresolved": 0, "stable": False},
    }
    executor = selected_executor
    manifest["degraded"] = manifest["report"]["degraded"] = executor is None and allow_degraded
    if executor is None and allow_degraded:
        manifest["executor"] = {"type": "degraded", "adapter": "", "probed": True, "capabilities": {}}
    tasks = []
    try:
        if executor is None and not allow_degraded:
            raise DelegationUnavailable("DELEGATION_UNAVAILABLE: no usable agent backend; configure a host or explicitly allow degradation")
        if len(modules) != len(mapping["modules"]) or len(expected) != len(set(expected)) or not expected:
            raise ValueError("MODULE_MAPPING_INVALID")
        scoped_entries = [entry for entry in scan.entries if module_filter is None or entry.module == module_filter]
        if (set(expected) != {entry.entry_id for entry in scoped_entries}
                or any(entry.entry_id not in modules.get(entry.module, {}).get("entry_ids", []) for entry in scoped_entries)):
            raise ValueError("MODULE_MAPPING_INVALID: confirmed scan scope differs")
        files = [spec["file"] for spec in modules.values()]
        if len(set(name.casefold() for name in files)) != len(files):
            raise ValueError("MODULE_FILE_DUPLICATE")
        for filename in files:
            FileWriteGuard("module", filename, manifest["docs_root"]).assert_allowed("module", filename)
        inventories = redact(collect_evidence(scan, branch_adapters=branch_adapters, persistence_adapters=persistence_adapters))
        # Normalize the presentation contract once at the process boundary.
        # Older/custom evidence adapters may omit these fields, but they must
        # still receive the source-owned values before agent validation.
        entry_lookup = {entry.entry_id: entry for entry in scan.entries}
        for entry_id, inventory in inventories.items():
            entry = entry_lookup.get(entry_id)
            if entry is None:
                continue
            inventory.setdefault("business_name", entry.business_name or "待确认")
            inventory.setdefault("trigger_summary", entry.trigger_summary or entry.identifier)
            inventory.setdefault("source_evidence", list(entry.source_evidence) or [{"file": entry.file, "line": entry.line, "reason": "入口源码位置"}])
            inventory.setdefault("scope_status", entry.scope_status or "business")
            inventory.setdefault("exclusion_reason", entry.exclusion_reason)
        manifest["inventories"] = {e: inventories[e] for e in expected}
        manifest["report"]["critical_unresolved"] = sum(
            item.get("critical", True) for inv in manifest["inventories"].values() for item in inv["unresolved"])
        entries = {entry.entry_id: entry for entry in scan.entries}
        module_metadata = {
            str(item["name"]): {key: item.get(key) for key in
                                 ("responsibility", "rationale", "objects", "partners", "questions")}
            for item in mapping.get("modules", []) if isinstance(item, dict) and item.get("name")
        }
        reusable = previous_run and (
            previous_run.get("source_fingerprint") == scan.source_fingerprint
            and previous_run.get("project_root") == manifest["project_root"]
            and previous_run.get("docs_root") == manifest["docs_root"]
            and not allow_degraded
        )
        if reusable:
            errors = validate_run(previous_run)
            if errors:
                raise ValueError("PREVIOUS_RUN_INVALID: " + "; ".join(errors))
        for module, spec in modules.items():
            reuse_value = None
            if reusable and spec == previous_run["modules"].get(module):
                value = previous_run["module_results"][module]
                path = Path(manifest["docs_root"]) / spec["file"]
                analyses = value["entry_analyses"]
                from .documents import render_module
                current_entries = [replace(entry, agent_branches=analyses[entry.entry_id]["branches"],
                    agent_persistence=analyses[entry.entry_id]["persistence_actions"])
                    for entry in scan.entries if entry.entry_id in analyses]
                current_content = str(redact(render_module(module, current_entries, scan.git, scan,
                    comparison="current", module_meta=module_metadata.get(module, {}))))
                old_hash = previous_run["document_hashes"].get(spec["file"])
                if (all(manifest["inventories"][e] == previous_run["inventories"].get(e) for e in spec["entry_ids"])
                        and current_content == value["markdown"] and path.is_file()
                        and hashlib.sha256(path.read_bytes()).hexdigest() == old_hash):
                    manifest["module_results"][module] = value
                    manifest["entry_analyses"].update(analyses)
                    manifest["document_hashes"][spec["file"]] = old_hash
                    reuse_value = value
            manifest["tasks"].append(asdict(TaskRecord(run_id, f"module:{module}", "coordinator", "module", module)))
            for entry in spec["entry_ids"]:
                manifest["tasks"].append(asdict(TaskRecord(run_id, f"entry:{entry}", f"module:{module}", "entry", module, entry)))
            tasks.append(AgentTask(f"module:{module}", "module", module, writable_file=spec["file"],
                context={"module_id": module, "project_root": manifest["project_root"],
                         "source_commit": scan.git.target, "source_fingerprint": scan.source_fingerprint,
                         "module_meta": module_metadata.get(module, {}),
                         "entry_specs": [{"entry_id": e, "source_file": entries[e].file,
                                          "kind": entries[e].kind, "identifier": entries[e].identifier,
                                          "handler": entries[e].handler, "caller": entries[e].caller,
                                          "input_summary": entries[e].input_summary,
                                          "business_name": entries[e].business_name,
                                          "trigger_summary": entries[e].trigger_summary,
                                          "source_evidence": list(entries[e].source_evidence),
                                          "scope_status": entries[e].scope_status,
                                          "exclusion_reason": entries[e].exclusion_reason,
                                          "functions": list(entries[e].functions),
                                          "errors": redact([asdict(error) for error in entries[e].errors]),
                                          "behaviors": redact([asdict(behavior) for behavior in entries[e].behaviors]),
                                          "inventory": manifest["inventories"][e]}
                                         for e in spec["entry_ids"]],
                         "reuse_value": reuse_value,
                         "permissions": {"source": "read-only", "markdown": "broker-only",
                                         "dispatch_entry_batch": spec["entry_ids"]}}))
        executor = executor or DegradedExecutor(scan, manifest["inventories"], run_id)
        results = []
        if tasks:
            batch = "module-batch:" + uuid.uuid4().hex
            handles = executor.dispatch_batch(tasks, "coordinator", batch)
            if len(handles) != len(tasks) or {(h.task_id, h.batch_id) for h in handles} != {(t.task_id, batch) for t in tasks}:
                raise ValueError("MODULE_BATCH_HANDLE_MISMATCH")
            results = executor.join_batch(batch)
        manifest["report"]["module_tasks"] = len(tasks)
        manifest["report"]["entry_tasks"] = sum(len(task.context["entry_specs"]) for task in tasks)
        if executor is not None:
            manifest["executor"]["capabilities"] = {
                str(key): value for key, value in dict(getattr(executor, "capabilities", {})).items()
                if isinstance(value, bool)
            }
        if len(results) != len(tasks) or {r.task_id for r in results} != {t.task_id for t in tasks}:
            raise ValueError("MODULE_AGENT_RESULT_MISSING")
        for result in results:
            if result.status != "success" or not isinstance(result.value, dict):
                raise ValueError(result.error or "MODULE_AGENT_FAILED")
            module = result.task_id.removeprefix("module:")
            value = result.value
            if set(value) != {"module_id", "entry_analyses", "markdown"} or value["module_id"] != module:
                raise ValueError("MODULE_RESULT_INVALID")
            if value != redact(value):
                raise ValueError("AGENT_RESULT_NOT_REDACTED")
            if set(value["entry_analyses"]) != set(modules[module]["entry_ids"]):
                raise ValueError("ENTRY_BATCH_TASK_MISMATCH")
            for e, analysis in value["entry_analyses"].items():
                if isinstance(analysis, dict) and "business_name" in manifest["inventories"][e]:
                    analysis.update({
                        key: manifest["inventories"][e].get(key)
                        for key in ("business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason")
                        if key not in analysis
                    })
                errors = validate_entry_analysis(analysis, manifest["inventories"][e])
                if errors:
                    raise ValueError("; ".join(errors))
            errors = validate_markdown_structure(value["markdown"], value["entry_analyses"])
            if errors:
                raise ValueError("; ".join(errors))
            manifest["module_results"][module] = value
            manifest["entry_analyses"].update(value["entry_analyses"])
        manifest["events"] = [asdict(event) | {"task_ids": list(event.task_ids)} for event in executor.get_events(run_id)]
        for task in manifest["tasks"][1:]:
            start = next(e for e in manifest["events"] if e["task_id"] == task["task_id"] and e["kind"] == "started")
            finish_kind = "ready" if task["role"] == "module" else "success"
            finish = next(e for e in manifest["events"] if e["task_id"] == task["task_id"] and e["kind"] == finish_kind)
            task.update(batch_id=start["batch_id"], started_at=start["timestamp"], result_hash=finish["result_hash"])
            if task["role"] == "entry":
                task.update(status="success", finished_at=finish["timestamp"])
            else:
                task["status"] = "running"
        manifest["parallel"] = manifest["report"]["parallel"] = bool(getattr(executor, "parallel", False))
        errors = validate_run(manifest, prepared=True)
        if errors:
            raise ValueError("; ".join(errors))
    except Exception as exc:
        if executor:
            manifest["events"] = [asdict(e) | {"task_ids": list(e.task_ids)} for e in executor.get_events(run_id)]
        fail_run(manifest, [str(exc) or type(exc).__name__])
    return manifest


@dataclass(frozen=True, slots=True)
class FileWriteGuard:
    owner_task_id: str
    writable_file: str
    docs_root: str | None = None

    def assert_allowed(self, task_id, path):
        raw = str(path).replace("\\", "/")
        if (task_id != self.owner_task_id or raw != self.writable_file or Path(raw).name != raw
                or ":" in raw or ".." in raw or not raw.endswith(".md")):
            raise PermissionError("MODULE_FILE_INVALID: WRITE_DENIED")
        if self.docs_root and (Path(self.docs_root) / raw).resolve().parent != Path(self.docs_root).resolve():
            raise PermissionError("MODULE_FILE_INVALID: WRITE_DENIED")


def _append_event(manifest, kind, task, *, path=None, result_hash=None):
    event = TaskEvent(manifest["run_id"], len(manifest["events"]) + 1, kind, task["task_id"],
                      _now(), task["batch_id"], path=path, result_hash=result_hash)
    manifest["events"].append(asdict(event) | {"task_ids": []})
    return event


def write_module(manifest, module, path, content):
    spec = manifest["modules"][module]
    task = next(t for t in manifest["tasks"] if t["role"] == "module" and t["module_id"] == module)
    FileWriteGuard(task["task_id"], spec["file"], manifest["docs_root"]).assert_allowed(task["task_id"], path.name)
    if path.resolve() != (Path(manifest["docs_root"]) / spec["file"]).resolve():
        raise PermissionError("WRITE_DENIED")
    value = manifest["module_results"][module]
    if task["status"] != "running" or content != value["markdown"]:
        raise ValueError("MODULE_CONTENT_CHANGED")
    errors = validate_markdown_structure(content, value["entry_analyses"])
    if errors:
        raise ValueError("; ".join(errors))
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(content.encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["document_hashes"][path.name] = file_hash
    _append_event(manifest, "write", task, path=path.name, result_hash=file_hash)
    event = _append_event(manifest, "success", task, result_hash=task["result_hash"])
    task.update(status="success", finished_at=event.timestamp)


def finish_run(manifest):
    coordinator = manifest["tasks"][0]
    if any(t["status"] != "success" for t in manifest["tasks"][1:]):
        raise ValueError("MODULE_NOT_COMPLETED")
    coordinator.update(status="success", finished_at=_now(), result_hash=digest(manifest["modules"]))


async def run_workflow(project: Path | ScanResult, mapping: dict, *, executor=None, allow_degraded=False, **kwargs):
    """Prepare delegated module drafts. CLI commits them after all acceptance gates."""
    if not isinstance(project, ScanResult):
        from .discovery import scan
        project = await asyncio.to_thread(scan, Path(project).resolve())
    return await asyncio.to_thread(create_run_manifest, project, mapping, executor=executor, allow_degraded=allow_degraded, **kwargs)


def build_agent_plan(scan: ScanResult, *, incremental: bool = False,
                     affected_modules: set[str] | None = None) -> dict[str, Any]:
    modules = sorted({entry.module for entry in scan.entries})
    if affected_modules is not None:
        modules = [module for module in modules if module in affected_modules]
    tasks: list[dict[str, Any]] = []
    analyses: dict[str, Any] = {}
    for module in modules:
        tasks.append({"task_id": f"module:{module}", "role": "module", "boundary": module,
                      "input_fingerprint": scan.source_fingerprint, "status": "ready", "merge_status": "pending"})
        for entry in sorted((item for item in scan.entries if item.module == module), key=lambda item: item.entry_id):
            tasks.append({"task_id": f"entry:{entry.entry_id}", "role": "entry", "boundary": entry.entry_id,
                          "input_fingerprint": scan.source_fingerprint, "status": "analyzed", "merge_status": "ready"})
            if not incremental:
                analyses[entry.entry_id] = {"entry": entry.entry_id, "module": entry.module,
                    "trigger": entry.identifier, "function": entry.handler,
                    "participants": sorted({entry.caller, entry.module}), "calls": list(entry.functions),
                    "branches": [b.statement for b in entry.behaviors if b.kind in {"分支", "校验"}],
                    "loops": [b.statement for b in entry.behaviors if b.kind == "循环"],
                    "async": entry.has_async, "persistence": entry.has_persistence,
                    "external_calls": entry.has_external_call,
                    "outcomes": {"success": entry.review.outcome if entry.review else "源码返回结果待入口代理确认",
                                  "failure": [e.code for e in entry.errors]},
                    "evidence": [f"{entry.file}:{entry.line}", *entry.functions], "unresolved": list(scan.unresolved)}
    return {"schema_version": 1, "source_fingerprint": scan.source_fingerprint, "incremental": incremental,
            "affected_modules": modules if incremental else None, "single_writer": "module",
            "entry_analyses": analyses, "tasks": tasks}


def validate_agent_plan(plan: dict[str, Any], scan: ScanResult) -> list[str]:
    errors: list[str] = []
    if plan.get("source_fingerprint") != scan.source_fingerprint:
        errors.append("SOURCE_FINGERPRINT_MISMATCH")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or plan.get("single_writer") != "module":
        return [*errors, "AGENT_PLAN_INVALID"]
    expected_modules = {entry.module for entry in scan.entries}
    if plan.get("incremental") and plan.get("affected_modules") is not None:
        expected_modules &= set(plan["affected_modules"])
    actual_modules = {task.get("boundary") for task in tasks if task.get("role") == "module"}
    actual_entries = {task.get("boundary") for task in tasks if task.get("role") == "entry"}
    expected_entries = {entry.entry_id for entry in scan.entries if entry.module in expected_modules}
    if actual_modules != expected_modules:
        errors.append("MODULE_TASK_MISMATCH")
    if actual_entries != expected_entries:
        errors.append("ENTRY_TASK_MISMATCH")
    ids = [task.get("task_id") for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("TASK_ID_DUPLICATE")
    return errors


def complete_agent_plan(plan: dict[str, Any], completed_modules: set[str]) -> dict[str, Any]:
    result = json.loads(json.dumps(plan, ensure_ascii=False))
    completed = set(completed_modules)
    result["status"] = "completed" if completed else "failed"
    current_module: str | None = None
    for task in result.get("tasks", []):
        if task.get("role") == "module":
            current_module = task.get("boundary")
        if task.get("role") in {"module", "entry"}:
            task["status"] = "completed" if current_module in completed else "failed"
    return result
