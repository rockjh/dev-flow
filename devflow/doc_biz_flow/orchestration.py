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
    """Build a single-writer plan without mutating Markdown from entry roles."""
    tasks: list[AgentTask] = []
    modules = sorted({entry.module for entry in scan.entries})
    if affected_modules is not None:
        modules = [module for module in modules if module in affected_modules]
    for module in modules:
        module_id = f"module:{module}"
        tasks.append(AgentTask(module_id, "module", module, scan.source_fingerprint))
        entries = sorted((entry for entry in scan.entries if entry.module == module), key=lambda item: item.entry_id)
        for entry in entries:
            tasks.append(AgentTask(
                f"entry:{entry.entry_id}", "entry", entry.entry_id,
                scan.source_fingerprint,
            ))
    return {
        "schema_version": 1,
        "source_fingerprint": scan.source_fingerprint,
        "incremental": incremental,
        "single_writer": "module",
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
    ids = [str(item.get("task_id")) for item in tasks if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        return ["agent plan contains duplicate task ids"]
    expected_modules = {entry.module for entry in scan.entries}
    expected_entries = {entry.entry_id for entry in scan.entries}
    module_tasks = {task_id.split(":", 1)[1] for task_id in ids if task_id.startswith("module:")}
    entry_tasks = {task_id.split(":", 1)[1] for task_id in ids if task_id.startswith("entry:")}
    missing_modules = sorted(expected_modules - module_tasks)
    missing_entries = sorted(expected_entries - entry_tasks)
    if missing_modules or missing_entries:
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
    return []
