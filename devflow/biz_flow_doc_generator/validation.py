"""Fail-closed acceptance of source inventories, agent events and Markdown."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime

from ..core.schema import BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, validate_schema
from ..core.redaction import redact
from .evidence import RESOURCE_TYPES


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_no_critical_unresolved(value: dict) -> list[str]:
    errors = []
    for item in value.get("unresolved", []):
        if not isinstance(item, dict) or item.get("critical") is not False:
            errors.append("CRITICAL_UNRESOLVED: " + str(item))
        elif not item.get("reason") or not item.get("evidence"):
            errors.append("UNRESOLVED_CLASSIFICATION_MISSING")
    for branch in value.get("source_branch_inventory", []):
        if branch.get("business_relevant") is None or branch.get("reachability") == "unknown":
            errors.append("CRITICAL_UNRESOLVED_BRANCH: " + str(branch.get("branch_id")))
    return errors


def validate_entry_analysis(value: object, inventory: dict) -> list[str]:
    # Keep the low-level validator usable by legacy/custom inventory providers;
    # the CLI's module-map gate enforces unresolved business names before
    # generation. Providers that expose the presentation contract are checked
    # strictly below.
    if isinstance(value, dict) and not any(key in inventory for key in ("business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason")):
        value = {
            "business_name": "待确认", "trigger_summary": str(inventory.get("entry_id", "入口")),
            "source_evidence": [], "scope_status": "business", "exclusion_reason": None,
            **value,
        }
    errors = validate_schema(BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, value)
    if errors:
        return errors
    errors.extend(validate_no_critical_unresolved(inventory))
    errors.extend(validate_no_critical_unresolved(value))
    for key in ("entry_id", "source_fingerprint"):
        if value[key] != inventory[key]:
            errors.append(f"ENTRY_EVIDENCE_MISMATCH: {key}")
    if "business_name" in inventory:
        for key in ("business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason"):
            if key not in value:
                errors.append(f"ENTRY_PRESENTATION_FIELD_MISSING: {key}")
            elif value[key] != redact(inventory.get(key)):
                errors.append(f"SOURCE_EVIDENCE_CHANGED: {key}")
        source_evidence = inventory.get("source_evidence")
        if inventory.get("scope_status") == "excluded" and (
            not inventory.get("exclusion_reason") or not source_evidence
        ):
            errors.append("EXCLUDED_ENTRY_EVIDENCE_MISSING")
    # The source analyzer owns every machine-readable field.  Entry agents may
    # add human labels for branches and persistence objects, but they may not
    # drop or rewrite participants, calls, async/external effects, or outcomes.
    for key in ("participants", "calls", "async_actions", "external_calls", "outcomes"):
        expected = [redact(item) for item in inventory.get(key, [])]
        if value.get(key) != expected:
            errors.append(f"SOURCE_EVIDENCE_CHANGED: {key}")
    for field, source_field, id_field in (
        ("branches", "source_branch_inventory", "branch_id"),
        ("persistence_actions", "persistence_inventory", "persistence_id"),
    ):
        expected = {item[id_field]: item for item in inventory[source_field]}
        actual = {item[id_field]: item for item in value[field]}
        if len(actual) != len(value[field]) or set(actual) != set(expected):
            errors.append(f"{field.upper()}_COVERAGE_MISMATCH")
        for identifier in expected.keys() & actual.keys():
            source, result = expected[identifier], actual[identifier]
            for key, original in source.items():
                if key == "display_name" and not original:
                    continue  # Human business labels may be supplied by the entry agent.
                if result.get(key) != redact(original):
                    errors.append(f"SOURCE_EVIDENCE_CHANGED: {identifier}:{key}")
            if field == "branches":
                if source["business_relevant"] is not True or source["reachability"] == "unreachable":
                    if not result.get("exclusion_reason"):
                        errors.append(f"BRANCH_EXCLUSION_REASON_MISSING: {identifier}")
                elif not result.get("label") or len(result.get("outcome_labels", [])) != len(source["outcomes"]):
                    errors.append(f"BRANCH_OUTCOMES_MISSING: {identifier}")
            else:
                resource_name = str(result.get("resource_name", "")).strip()
                display_name = str(result.get("display_name", "")).strip()
                generic_resources = {"数据库", "持久化资源", "资源", "database", "db", "repository", "table", "collection"}
                if (not resource_name or resource_name.casefold() in generic_resources
                        or not re.search(r"[\u3400-\u9fff]", display_name)
                        or display_name in {"业务对象", "资源", "数据库"}):
                    errors.append(f"PERSISTENCE_OBJECT_UNRESOLVED: {identifier}")
                if result.get("resource_type") not in RESOURCE_TYPES:
                    errors.append(f"PERSISTENCE_TYPE_INVALID: {identifier}")
    return errors


def entry_sections(markdown: str) -> dict[str, str]:
    markers = list(re.finditer(r"^<!--\s*biz-flow-entry:\s*(.+?)\s*-->\s*$", markdown, re.M))
    return {m[1]: markdown[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(markdown)] for i, m in enumerate(markers)}


def _diagrams(markdown: str) -> list[str]:
    return re.findall(r"^```mermaid[^\n]*\n(.*?)^```\s*$", markdown, re.M | re.S)


def parse_diagram_ids(markdown: str, kind: str) -> set[str]:
    return set(re.findall(r'^\s*%% devflow:' + kind + r' id="([A-Za-z0-9_-]+)"\s*$', "\n".join(_diagrams(markdown)), re.M))


def _matrix_rows(markdown: str, column: str) -> list[dict[str, str]]:
    # IDs outside an actual table cell (including comments) do not count.
    text = re.sub(r"```.*?```|<!--.*?-->", "", markdown, flags=re.S)
    lines = text.splitlines()
    rows = []
    for index, line in enumerate(lines[:-1]):
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or column not in headers or not re.fullmatch(r"[\s|:\-]+", lines[index + 1]):
            continue
        for row in lines[index + 2:]:
            if not row.startswith("|"):
                break
            cells = [cell.strip().strip("`") for cell in row.strip().strip("|").split("|")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows


def parse_matrix_ids(markdown: str, kind: str) -> set[str]:
    column = "分支编号" if kind == "branch" else "持久化编号"
    return {row[column] for row in _matrix_rows(markdown, column) if row.get(column)}


def validate_branch_coverage(analysis: dict, markdown: str) -> list[str]:
    branches = [b for b in analysis["branches"] if b["business_relevant"] is True and b["reachability"] != "unreachable"]
    expected = {b["branch_id"] for b in branches}
    errors = []
    if expected != parse_diagram_ids(markdown, "branch") or expected != parse_matrix_ids(markdown, "branch"):
        errors.append("BRANCH_COVERAGE_MISMATCH")
    diagrams = "\n".join(_diagrams(markdown))
    rows = _matrix_rows(markdown, "分支编号")
    for branch in branches:
        identifier = branch["branch_id"]
        chunks = re.findall(r'%% devflow:branch id="' + re.escape(identifier) + r'"\s*\n(.*?)(?=\n\s*%% devflow:branch|\Z)', diagrams, re.S)
        row = [r for r in rows if r["分支编号"] == identifier]
        labels = [branch["label"], *branch["outcome_labels"]]
        if not chunks or len(row) != 1 or any(label not in "\n".join(chunks) or label not in str(row) for label in labels):
            errors.append(f"BRANCH_CONTENT_MISMATCH: {identifier}")
    return errors


def validate_persistence_coverage(analysis: dict, markdown: str) -> list[str]:
    actions = analysis["persistence_actions"]
    expected = {a["persistence_id"] for a in actions}
    errors = []
    if expected != parse_diagram_ids(markdown, "persistence") or expected != parse_matrix_ids(markdown, "persistence"):
        errors.append("PERSISTENCE_COVERAGE_MISMATCH")
    diagrams = "\n".join(_diagrams(markdown))
    participants = dict(re.findall(r"^\s*participant\s+(\w+)\s+as\s+(.+)$", diagrams, re.M))
    rows = _matrix_rows(markdown, "持久化编号")
    for action in actions:
        identifier = action["persistence_id"]
        label = f"{action['resource_name']}（{action['display_name']}）"
        aliases = {alias for alias, name in participants.items() if name.strip().strip('"') == label}
        row = [r for r in rows if r["持久化编号"] == identifier]
        operation = re.search(r'%% devflow:persistence id="' + re.escape(identifier) + r'"\s*\n\s*(\w+)(?:-->>|->>)(\w+):\s*([^\n]+)', diagrams)
        if (not aliases or len(row) != 1 or label not in str(row) or not operation
                or not aliases.intersection(operation.groups()[:2])
                or action["operation_label"] not in operation[3]
                or action["operation_label"] not in str(row)
                or any(field not in operation[3] or field not in str(row) for field in action["fields"])):
            errors.append(f"PERSISTENCE_CONTENT_MISMATCH: {identifier}")
    return errors


def validate_no_generic_participants(markdown: str) -> list[str]:
    labels = re.findall(r"^\s*participant\s+\w+\s+as\s+(.+)$", "\n".join(_diagrams(markdown)), re.M)
    generic = {"当前系统", "数据库", "调用服务", "处理数据", "账号库", "会话库", "持久化资源", "database", "db", "repository"}
    return [f"GENERIC_PARTICIPANT: {label}" for label in labels
            if label.strip().strip('"').casefold() in generic
            or label.strip().strip('"').endswith(("持久化资源", "数据库", "外部接口", "消息基础设施"))]


def validate_markdown_structure(markdown: str, analyses: dict[str, dict]) -> list[str]:
    from .documents import _validate_mermaid

    sections = entry_sections(markdown)
    markers = re.findall(r"^<!--\s*biz-flow-entry:", markdown, re.M)
    errors = []
    if set(sections) != set(analyses) or len(markers) != len(analyses):
        errors.append("MARKDOWN_ENTRY_OWNERSHIP_MISMATCH")
    for entry_id, section in sections.items():
        if entry_id not in analyses:
            continue
        title = re.search(r"^## (.+)$", section, re.M)
        intro = re.search(r"^入口描述[：:]\s*\S.+$", section, re.M)
        purpose = re.search(r"^业务功能[：:]\s*\S.+$", section, re.M)
        diagrams = _diagrams(section)
        first_diagram = section.find("```mermaid")
        purpose = purpose or re.search(r"^-\s+\S.+$", section, re.M)
        if not title or not intro or not purpose or not (title.start() < intro.start() < purpose.start() < first_diagram):
            errors.append(f"MARKDOWN_STRUCTURE_INVALID: {entry_id}")
        if title and (not re.search(r"[\u3400-\u9fff]", title[1]) or re.search(r"/|\b(?:GET|POST|class)\b", title[1])):
            errors.append(f"BUSINESS_TITLE_INVALID: {entry_id}")
        if not diagrams:
            errors.append(f"MERMAID_MISSING: {entry_id}")
        for diagram in diagrams:
            errors.extend(_validate_mermaid(diagram))
        errors.extend(validate_no_generic_participants(section))
        errors.extend(validate_branch_coverage(analyses[entry_id], section))
        errors.extend(validate_persistence_coverage(analyses[entry_id], section))
        if re.search(r"其他情况|处理失败|调用数据库|代码中未确认|title_unresolved", section):
            errors.append(f"VAGUE_BUSINESS_RESULT: {entry_id}")
    return errors


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result


def _ready(manifest: dict, task_id: str) -> dict:
    return next((event for event in manifest["events"]
                 if event["kind"] in {"ready", "success"}
                 and event["task_id"] == task_id), {})


def validate_task_tree(manifest: dict, *, prepared: bool = False) -> list[str]:
    tasks = manifest["tasks"]
    ids = [t["task_id"] for t in tasks]
    errors = []
    coordinators = [t for t in tasks if t["role"] == "coordinator"]
    if len(ids) != len(set(ids)) or len(coordinators) != 1:
        return ["TASK_TREE_INVALID"]
    modules = manifest["modules"]
    expected = {entry: module for module, spec in modules.items() for entry in spec["entry_ids"]}
    if len(expected) != sum(len(spec["entry_ids"]) for spec in modules.values()):
        errors.append("ENTRY_OWNERSHIP_DUPLICATE")
    if Counter(t["module_id"] for t in tasks if t["role"] == "module") != Counter(modules.keys()):
        errors.append("MODULE_TASK_COUNT_MISMATCH")
    if Counter(t["entry_id"] for t in tasks if t["role"] == "entry") != Counter(expected.keys()):
        errors.append("ENTRY_TASK_COUNT_MISMATCH")
    by_id = {t["task_id"]: t for t in tasks}

    def end_time(task):
        if prepared and task["role"] == "module":
            return _ready(manifest, task["task_id"]).get("timestamp")
        if prepared and task["role"] == "coordinator":
            return manifest["events"][-1]["timestamp"] if manifest["events"] else None
        return task["finished_at"]

    for task in tasks:
        parent = by_id.get(task["parent_task_id"])
        pending_commit = prepared and task["role"] != "entry"
        if (task["run_id"] != manifest["run_id"]
                or task["status"] != ("running" if pending_commit else "success")
                or (not task["result_hash"] and not (prepared and task["role"] == "coordinator"))
                or task["error"]):
            errors.append(f"TASK_NOT_SUCCESSFUL: {task['task_id']}")
        if pending_commit and task["finished_at"] is not None:
            errors.append("TASK_FINISHED_BEFORE_COMMIT")
        if task["role"] == "coordinator":
            if task["parent_task_id"] is not None or task["module_id"] is not None or task["entry_id"] is not None:
                errors.append("TASK_PARENT_INVALID")
        elif task["role"] == "module":
            if not parent or parent["role"] != "coordinator" or task["entry_id"] is not None:
                errors.append("TASK_PARENT_INVALID")
        elif task["role"] == "entry":
            if not parent or parent["role"] != "module" or parent["module_id"] != expected.get(task["entry_id"]) or task["module_id"] != parent["module_id"]:
                errors.append("TASK_PARENT_INVALID")
        else:
            errors.append("TASK_ROLE_INVALID")
        try:
            start, end = _time(task["started_at"]), _time(end_time(task))
            if start >= end:
                errors.append("TASK_TIME_INVALID")
            if parent and not (_time(parent["started_at"]) <= start < end <= _time(end_time(parent))):
                errors.append("TASK_PARENT_TIME_INVALID")
        except (TypeError, ValueError):
            errors.append("TASK_TIME_INVALID")
    return errors


def validate_task_parent_relation(manifest: dict) -> list[str]:
    return [e for e in validate_task_tree(manifest) if "PARENT" in e]


def _validate_batch(manifest: dict, role: str, *, prepared: bool = False) -> list[str]:
    errors = []
    parents = [t for t in manifest["tasks"] if t["role"] == ("coordinator" if role == "module" else "module")]
    for parent in parents:
        tasks = [t for t in manifest["tasks"] if t["parent_task_id"] == parent["task_id"]]
        dispatches = [e for e in manifest["events"] if e["kind"] == "dispatch_batch" and e["task_id"] == parent["task_id"]]
        joins = [e for e in manifest["events"] if e["kind"] == "join_batch" and e["task_id"] == parent["task_id"]]
        if len(dispatches) != 1 or len(joins) != 1:
            errors.append(f"{role.upper()}_BATCH_INVALID")
            continue
        dispatch, join = dispatches[0], joins[0]
        if (not dispatch["batch_id"] or set(dispatch["task_ids"]) != {t["task_id"] for t in tasks}
                or len(dispatch["task_ids"]) != len(tasks)
                or dispatch["batch_id"] != join["batch_id"]
                or any(t["batch_id"] != dispatch["batch_id"] for t in tasks)):
            errors.append(f"{role.upper()}_BATCH_INVALID")
        for task in tasks:
            finish_kind = "ready" if role == "module" else "success"
            events = [e for e in manifest["events"] if e["task_id"] == task["task_id"] and e["kind"] in {"started", finish_kind}]
            if (len(events) != 2 or [e["kind"] for e in events] != ["started", finish_kind]
                    or not dispatch["sequence"] < events[0]["sequence"] < events[1]["sequence"] < join["sequence"]
                    or any(e["batch_id"] != dispatch["batch_id"] for e in events)
                    or events[0]["timestamp"] != task["started_at"]
                    or (role == "entry" and events[1]["timestamp"] != task["finished_at"])
                    or events[1]["result_hash"] != task["result_hash"]):
                errors.append("TASK_EVENT_MISMATCH")
            if role == "module":
                finishes = [e for e in manifest["events"] if e["kind"] == "success" and e["task_id"] == task["task_id"]]
                entry_dispatch = next((e for e in manifest["events"]
                                       if e["kind"] == "dispatch_batch"
                                       and e["task_id"] == task["task_id"]), None)
                entry_join = next((e for e in manifest["events"]
                                   if e["kind"] == "join_batch"
                                   and e["task_id"] == task["task_id"]
                                   and entry_dispatch is not None
                                   and e.get("batch_id") == entry_dispatch.get("batch_id")), None)
                ready = next((e for e in manifest["events"]
                              if e["kind"] in {"ready", "success"}
                              and e["task_id"] == task["task_id"]), None)
                if not entry_join or not ready or ready["sequence"] <= entry_join["sequence"]:
                    errors.append("MODULE_WRITE_BEFORE_ENTRY_JOIN")
                if prepared:
                    if finishes:
                        errors.append("MODULE_FINISHED_BEFORE_WRITE")
                elif (len(finishes) != 1 or finishes[0]["timestamp"] != task["finished_at"]
                      or finishes[0]["result_hash"] != task["result_hash"]
                      or finishes[0]["sequence"] <= join["sequence"]):
                    errors.append("TASK_EVENT_MISMATCH")
    return errors


def validate_module_batch(manifest: dict, *, prepared: bool = False) -> list[str]:
    return _validate_batch(manifest, "module", prepared=prepared)


def validate_entry_batch(manifest: dict) -> list[str]:
    return _validate_batch(manifest, "entry")


def validate_parallel_execution(manifest: dict) -> list[str]:
    if manifest["degraded"]:
        return [] if manifest["allow_degraded"] and manifest["parallel"] is False else ["DEGRADATION_NOT_AUTHORIZED"]
    if not manifest["parallel"]:
        return ["PARALLEL_EXECUTION_REQUIRED"]
    errors = []
    for event in manifest["events"]:
        if event["kind"] != "dispatch_batch":
            continue
        tasks = [t for t in manifest["tasks"] if t["task_id"] in event["task_ids"]]
        # Observe overlap of analysis lifetimes, never extend lifetimes to the
        # later artifact commit in order to manufacture parallel execution.
        try:
            starts = [_time(t["started_at"]) for t in tasks]
            ends = [_time(_ready(manifest, t["task_id"]).get("timestamp") if t["role"] == "module" else t["finished_at"]) for t in tasks]
            if len(tasks) > 1 and max(starts) >= min(ends):
                errors.append("PARALLEL_EXECUTION_NOT_OBSERVED")
        except (TypeError, ValueError):
            errors.append("TASK_TIME_INVALID")
    return errors


def validate_single_writer(manifest: dict) -> list[str]:
    errors = []
    tasks = {t["task_id"]: t for t in manifest["tasks"]}
    writes = [e for e in manifest["events"] if e["kind"] == "write"]
    for module, spec in manifest["modules"].items():
        events = [e for e in writes if e["path"] == spec["file"]]
        if len(events) != 1:
            errors.append("SINGLE_WRITER_VIOLATION")
            continue
        event = events[0]
        task = tasks.get(event["task_id"], {})
        joins = [e for e in manifest["events"] if e["kind"] == "join_batch" and e["task_id"] == event["task_id"]]
        finishes = [e for e in manifest["events"] if e["kind"] == "success" and e["task_id"] == event["task_id"]]
        if (task.get("role") != "module" or task.get("module_id") != module
                or event.get("batch_id") != task.get("batch_id")
                or len(joins) != 1 or joins[0]["sequence"] >= event["sequence"]
                or len(finishes) != 1 or finishes[0]["sequence"] <= event["sequence"]
                or _ready(manifest, event["task_id"]).get("sequence", float("inf")) >= event["sequence"]):
            errors.append("WRITE_BEFORE_ENTRY_JOIN")
        if event["result_hash"] != manifest["document_hashes"].get(spec["file"]):
            errors.append("DOCUMENT_HASH_MISMATCH")
    if len(writes) != len(manifest["modules"]) or any(e["kind"] == "write_denied" for e in manifest["events"]):
        errors.append("SINGLE_WRITER_VIOLATION")
    return errors


def validate_run(manifest: dict, *, prepared: bool = False) -> list[str]:
    from ..core.schema import BIZ_FLOW_RUN_MANIFEST_SCHEMA

    errors = validate_schema(BIZ_FLOW_RUN_MANIFEST_SCHEMA, manifest)
    if errors:
        return errors
    if manifest["errors"] or manifest["status"] != ("running" if prepared else "success"):
        errors.append("RUN_NOT_SUCCESSFUL")
    report = manifest["report"]
    counts = {
        "module_count": len(manifest["modules"]),
        "entry_count": sum(len(spec["entry_ids"]) for spec in manifest["modules"].values()),
        "module_tasks": sum(t["role"] == "module" for t in manifest["tasks"]),
        "entry_tasks": sum(t["role"] == "entry" for t in manifest["tasks"]),
    }
    for key, value in counts.items():
        if report[key] != value:
            errors.append(f"REPORT_{key.upper()}_MISMATCH")
    if report["parallel"] != manifest["parallel"] or report["degraded"] != manifest["degraded"]:
        errors.append("REPORT_EXECUTION_MODE_MISMATCH")
    if not prepared and (not report["stable"] or report["branch_coverage"] != 1.0
                         or report["persistence_coverage"] != 1.0 or report["critical_unresolved"] != 0):
        errors.append("REPORT_INCOMPLETE")
    if prepared and (report["stable"] or manifest["document_hashes"]):
        errors.append("PREMATURE_COMPLETION")
    if manifest["mapping_hash"] != digest(manifest["modules"]):
        errors.append("MAPPING_HASH_MISMATCH")
    filenames = [spec["file"] for spec in manifest["modules"].values()]
    if len(set(name.casefold() for name in filenames)) != len(filenames):
        errors.append("MODULE_FILE_DUPLICATE")
    from .orchestration import FileWriteGuard
    for filename in filenames:
        try:
            FileWriteGuard("module", filename, manifest["docs_root"]).assert_allowed("module", filename)
        except PermissionError:
            errors.append("MODULE_FILE_INVALID")
    events = manifest["events"]
    task_ids = {task["task_id"] for task in manifest["tasks"]}
    if ([e["sequence"] for e in events] != list(range(1, len(events) + 1))
            or any(e["run_id"] != manifest["run_id"] or e["task_id"] not in task_ids for e in events)):
        errors.append("EVENT_SEQUENCE_INVALID")
    try:
        times = [_time(e["timestamp"]) for e in events]
        if times != sorted(times):
            errors.append("EVENT_TIME_INVALID")
    except (TypeError, ValueError):
        errors.append("EVENT_TIME_INVALID")
    batches = [e["batch_id"] for e in events if e["kind"] == "dispatch_batch"]
    if len(batches) != len(set(batches)):
        errors.append("BATCH_ID_DUPLICATE")
    if any(e["kind"] in {"failed", "write_denied"} for e in events):
        errors.append("TASK_EXECUTION_FAILED")
    errors.extend(validate_task_tree(manifest, prepared=prepared))
    errors.extend(validate_module_batch(manifest, prepared=prepared))
    errors.extend(validate_entry_batch(manifest))
    errors.extend(validate_parallel_execution(manifest))
    if prepared:
        if any(e["kind"] == "write" for e in events):
            errors.append("SINGLE_WRITER_VIOLATION")
    else:
        errors.extend(validate_single_writer(manifest))
    for entry_id, inventory in manifest["inventories"].items():
        analysis = manifest["entry_analyses"].get(entry_id)
        errors.extend(validate_entry_analysis(analysis, inventory))
        if inventory["entry_id"] != entry_id or inventory["source_fingerprint"] != manifest["source_fingerprint"]:
            errors.append("ENTRY_EVIDENCE_MISMATCH")
        task = next((t for t in manifest["tasks"] if t["entry_id"] == entry_id), {})
        if task.get("result_hash") != digest(analysis):
            errors.append("ENTRY_RESULT_HASH_MISMATCH")
    expected_entries = {e for m in manifest["modules"].values() for e in m["entry_ids"]}
    if set(manifest["inventories"]) != expected_entries or set(manifest["entry_analyses"]) != expected_entries:
        errors.append("ENTRY_INVENTORY_MISMATCH")
    module_results = manifest.get("module_results", {})
    if set(module_results) != set(manifest["modules"]):
        errors.append("MODULE_RESULT_MISSING")
    for module, result in module_results.items():
        spec = manifest["modules"].get(module, {})
        analyses = {entry: manifest["entry_analyses"].get(entry) for entry in spec.get("entry_ids", [])}
        if result["module_id"] != module or result["entry_analyses"] != analyses:
            errors.append("MODULE_RESULT_MISMATCH")
        errors.extend(validate_markdown_structure(result["markdown"], result["entry_analyses"]))
        task = next((t for t in manifest["tasks"] if t["role"] == "module" and t["module_id"] == module), {})
        if task.get("result_hash") != digest(result):
            errors.append("MODULE_RESULT_HASH_MISMATCH")
        if not prepared and manifest["document_hashes"].get(spec.get("file")) != hashlib.sha256(result["markdown"].encode()).hexdigest():
            errors.append("DOCUMENT_HASH_MISMATCH")
    return list(dict.fromkeys(errors))
