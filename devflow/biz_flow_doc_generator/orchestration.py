"""Deterministic module/entry orchestration records for biz-flow runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import ScanResult


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_id: str
    role: str
    boundary: str
    input_fingerprint: str
    status: str = "planned"
    merge_status: str = "pending"


def build_agent_plan(scan: ScanResult, *, incremental: bool = False, affected_modules: set[str] | None = None) -> dict[str, Any]:
    """Build a deterministic plan and read-only evidence for every entry."""
    tasks: list[AgentTask] = []
    modules = sorted({entry.module for entry in scan.entries})
    if affected_modules is not None:
        modules = [module for module in modules if module in affected_modules]
    for module in modules:
        module_id = f"module:{module}"
        tasks.append(AgentTask(module_id, "module", module, scan.source_fingerprint, status="ready"))
        entries = sorted((entry for entry in scan.entries if entry.module == module), key=lambda item: item.entry_id)
        for entry in entries:
            tasks.append(AgentTask(
                f"entry:{entry.entry_id}", "entry", entry.entry_id,
                scan.source_fingerprint, status="analyzed", merge_status="ready",
            ))
    analyses = {
        entry.entry_id: {
            "entry": entry.entry_id,
            "module": entry.module,
            "trigger": entry.identifier,
            "function": entry.handler,
            "participants": sorted({entry.caller, entry.module, *((step.participant for step in entry.review.steps) if entry.review else ())}),
            "calls": list(entry.functions),
            "branches": [behavior.statement for behavior in entry.behaviors if behavior.kind in {"分支", "校验"}],
            "loops": [behavior.statement for behavior in entry.behaviors if behavior.kind == "循环"],
            "async": entry.has_async,
            "persistence": entry.has_persistence,
            "external_calls": entry.has_external_call,
            "outcomes": {"success": entry.review.outcome if entry.review else "源码返回结果待入口代理确认", "failure": [error.code for error in entry.errors]},
            "evidence": [f"{entry.file}:{entry.line}", *entry.functions],
            "unresolved": list(scan.unresolved),
        }
        for entry in scan.entries
        if not incremental or entry.module in modules
    }
    return {
        "schema_version": 1,
        "source_fingerprint": scan.source_fingerprint,
        "incremental": incremental,
        # Preserve the exact validation scope for incremental plans.  An
        # omitted scope means the plan covers the complete scan.
        "affected_modules": modules if incremental else None,
        "single_writer": "module",
        "entry_analyses": analyses,
        "tasks": [asdict(task) for task in tasks],
    }


def validate_agent_plan(plan: object, scan: ScanResult) -> list[str]:
    if not isinstance(plan, dict):
        return ["agent plan must be an object"]
    if plan.get("source_fingerprint") != scan.source_fingerprint:
        return ["agent plan input fingerprint is stale"]
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return ["agent plan tasks must be an array"]
    analyses = plan.get("entry_analyses")
    if not isinstance(analyses, dict):
        return ["agent plan entry_analyses must be an object"]
    ids = [str(item.get("task_id")) for item in tasks if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        return ["agent plan contains duplicate task ids"]
    scope = plan.get("affected_modules")
    if plan.get("incremental") and isinstance(scope, list):
        allowed = {str(module) for module in scope}
        expected_modules = {entry.module for entry in scan.entries if entry.module in allowed}
        expected_entries = {entry.entry_id for entry in scan.entries if entry.module in allowed}
    else:
        expected_modules = {entry.module for entry in scan.entries}
        expected_entries = {entry.entry_id for entry in scan.entries}
    module_tasks = {task_id.split(":", 1)[1] for task_id in ids if task_id.startswith("module:")}
    entry_tasks = {task_id.split(":", 1)[1] for task_id in ids if task_id.startswith("entry:")}
    missing_modules = sorted(expected_modules - module_tasks)
    missing_entries = sorted(expected_entries - entry_tasks)
    missing_analyses = sorted(expected_entries - set(analyses))
    if missing_analyses:
        return ["agent plan missing entry analyses: " + ", ".join(missing_analyses)]
    if missing_modules or missing_entries or missing_analyses:
        return [
            *(["agent plan missing module tasks: " + ", ".join(missing_modules)] if missing_modules else []),
            *(["agent plan missing entry tasks: " + ", ".join(missing_entries)] if missing_entries else []),
        ]
    module_by_entry = {entry.entry_id: entry.module for entry in scan.entries}
    for item in tasks:
        if not isinstance(item, dict) or item.get("role") != "entry":
            continue
        module = module_by_entry.get(str(item.get("boundary")))
        if module is None or f"module:{module}" not in ids:
            return [f"agent plan entry task has no module writer: {item.get('task_id')}" ]
    required = {"entry", "module", "trigger", "function", "participants", "calls", "branches", "loops", "async", "persistence", "external_calls", "outcomes", "evidence", "unresolved"}
    for entry_id in expected_entries:
        value = analyses.get(entry_id)
        if not isinstance(value, dict) or not required.issubset(value):
            return [f"agent plan entry analysis is incomplete: {entry_id}"]
    return []


def complete_agent_plan(plan: dict[str, Any], modules: set[str]) -> dict[str, Any]:
    """Close entry analyses and module writers after their Markdown is committed."""
    completed = {"module:" + module for module in modules}
    result = dict(plan)
    result["tasks"] = [
        {
            **task,
            "status": "completed" if task.get("task_id") in completed or task.get("role") == "entry" else task.get("status", "planned"),
            "merge_status": "merged" if task.get("task_id") in completed or task.get("role") == "entry" else task.get("merge_status", "pending"),
        }
        for task in plan.get("tasks", [])
        if isinstance(task, dict)
    ]
    result["status"] = "completed"
    result["completed_modules"] = sorted(modules)
    return result
