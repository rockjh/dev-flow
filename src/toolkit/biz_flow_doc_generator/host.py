"""Frozen task packages and consistency validation for the session handoff."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..core.agents import parse_timestamp, validate_active_observations
from ..core.artifacts import state_root, write_json
from ..core.schema import BIZ_FLOW_SUBMISSION_SCHEMA, validate_schema
from .validation import digest
from .git import source_view

PROTOCOL_VERSION = "5.0"


def run_path(run_id: str) -> Path:
    # User-supplied run IDs must never escape the authoritative state directory.
    if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("RUN_ID_INVALID")
    return state_root() / "biz-flow" / f"{run_id}.json"


def source_path(run_id: str) -> Path:
    parent = run_path(run_id).parent
    run_root = parent / run_id
    source = run_root / "source"
    if (any(path.is_symlink() or hasattr(path, "is_junction") and path.is_junction()
            for path in (run_root, source))
            or run_root.resolve().parent != parent.resolve()
            or source.resolve().parent != run_root.resolve()):
        raise ValueError("SOURCE_PATH_UNSAFE")
    return source


def protected_hashes(project: Path, docs_root: Path) -> dict[str, str]:
    # The user's checkout can change independently of this run (C3). Freeze
    # business assets and locks; validate the archive snapshot separately.
    names = set()
    result = {}
    names.update(p.relative_to(project).as_posix() for p in docs_root.rglob("*") if p.is_file() or p.is_symlink())
    transient = {"biz-flow-discovery.json", "biz-flow-modules.json", "biz-flow-failures.log", "biz-flow-run.lock"}
    for name in sorted(names):
        if not name:
            continue
        path = project / name
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
            raise ValueError("SOURCE_PATH_UNSAFE")
        if path.parent.resolve() == docs_root.resolve() and (
                path.suffix == ".md" or path.name in transient or path.name == "biz-flow-doc-generator-version.json"):
            # Markdown and the version lock have separate frozen-input checks.
            continue
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
    version = docs_root / "biz-flow-doc-generator-version.json"
    if version.is_symlink() or not version.resolve().is_relative_to(project.resolve()):
        raise ValueError("VERSION_PATH_UNSAFE")
    result[version.relative_to(project).as_posix()] = hashlib.sha256(version.read_bytes()).hexdigest()
    return result


def snapshot_sources(project: Path, commit: str, files: list[str], run_id: str) -> tuple[Path, str]:
    root = source_path(run_id)
    hashes = {}
    # One archive replaces one git subprocess per source file.  The snapshot
    # is the exact same export view used by discovery (including attributes).
    with source_view(project, commit) as (view, _):
        for relative in files:
            destination = root / relative
            if not destination.resolve().is_relative_to(root.resolve()):
                raise ValueError("SOURCE_PATH_UNSAFE")
            content = (view / relative).read_bytes()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.is_file() or destination.read_bytes() != content:
                destination.write_bytes(content)
            hashes[relative] = hashlib.sha256(content).hexdigest()
    write_json(root.parent / "source-hashes.json", hashes)
    return root, digest(hashes)


def validate_package(manifest: dict) -> list[str]:
    import json
    errors = []
    path = run_path(manifest["run_id"]).with_suffix(".tasks.json")
    package = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(package, dict) or package.get("protocol_version") != PROTOCOL_VERSION or package.get("domain") != "biz-flow":
        return ["UNSUPPORTED_TASK_PACKAGE: prepare a new biz-flow run, do not convert stored packages"]
    if digest(package) != manifest["package_hash"] or package["tasks"] != manifest["tasks"]:
        errors.append("TASK_PACKAGE_CHANGED")
    for key in ("run_id", "project_root", "source_commit", "source_fingerprint", "mapping_hash",
                "source_status", "adapter_version", "verified_evidence", "entry_facts", "version_input_hash"):
        if package.get(key) != manifest.get(key):
            errors.append("PACKAGE_BINDING_MISMATCH: " + key)
    if digest(manifest["mapping"]) != manifest["mapping_hash"]:
        errors.append("MAPPING_HASH_MISMATCH")
    checked_snapshots = set()
    for task in manifest["tasks"]:
        if digest({key: value for key, value in task.items() if key != "task_hash"}) != task["task_hash"]:
            errors.append("TASK_HASH_MISMATCH")
        if digest(manifest["entry_facts"][task["entry_id"]]) != task["input_hash"]:
            errors.append("TASK_INPUT_MISMATCH")
        root = source_path(manifest["run_id"])
        if Path(task["source_snapshot"]) != root:
            errors.append("SOURCE_SNAPSHOT_SCOPE_MISMATCH")
            continue
        if manifest.get("status") == "accepted" and manifest.get("snapshot_cleaned"):
            continue  # Canonical facts are still rebuilt from the fixed commit.
        key = (str(root), task["snapshot_hash"])
        if key in checked_snapshots:
            continue
        checked_snapshots.add(key)
        hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob("*") if p.is_file()}
        if any(p.is_symlink() for p in root.rglob("*")) or digest(hashes) != task["snapshot_hash"]:
            errors.append("SOURCE_SNAPSHOT_CHANGED")
    return errors


def _valid_receipt_times(receipt: dict) -> bool:
    try:
        start, end = receipt["started_at"], receipt["finished_at"]
        if receipt["time_source"] == "unavailable":
            if start is not None or end is not None:
                raise ValueError("unavailable timestamps supplied")
        else:
            if start is not None:
                parse_timestamp(start)
            if end is not None:
                parse_timestamp(end)
            if start is not None and end is not None and parse_timestamp(start) > parse_timestamp(end):
                raise ValueError("time reversed")
        reclaimed = receipt["reclaimed_at"]
        if receipt["reclaim_state"] == "reclaimed":
            if not reclaimed or not end or parse_timestamp(reclaimed) < parse_timestamp(end):
                raise ValueError("reclamation evidence missing")
        elif reclaimed is not None:
            raise ValueError("unobserved reclamation supplied")
    except (TypeError, ValueError):
        return False
    return True


def validate_execution(manifest: dict, submitted: dict, *, allow_fixture: bool = False) -> list[str]:
    errors = validate_schema(BIZ_FLOW_SUBMISSION_SCHEMA, submitted)
    if errors:
        return errors
    for key in ("run_id", "source_fingerprint", "mapping_hash", "package_hash"):
        if submitted[key] != manifest[key]:
            errors.append(f"HANDOFF_BINDING_MISMATCH: {key}")
    tasks = {task["task_id"]: task for task in manifest["tasks"]}
    entries = {task["entry_id"] for task in tasks.values()}
    if set(submitted["results"]) != entries:
        errors.append("RESULT_COVERAGE_MISMATCH")
    receipts = submitted["execution"]["receipts"]
    observations = submitted["execution"]["active_observations"]
    if submitted["mode"] == "serial":
        authorization = submitted["serial_approval"]
        if not authorization or set(authorization["scope"]) != entries or len(authorization["scope"]) != len(entries):
            errors.append("SERIAL_AUTHORIZATION_INVALID")
        if receipts or observations or submitted["completed_child_agents"] != 0 or submitted["parallel"]:
            errors.append("SERIAL_EXECUTION_FLAGS_INVALID")
        if any(item.get("execution", {}).get("receipts") for item in manifest.get("rejected_submissions", [])):
            errors.append("SERIAL_REQUIRES_NEW_RUN_AFTER_NATIVE_ATTEMPT")
        return errors
    if submitted["serial_approval"] is not None:
        errors.append("NATIVE_SERIAL_AUTHORIZATION_INVALID")
    received = {(receipt["task_id"], receipt["attempt"]): receipt for receipt in receipts}
    bound_fields = ("run_id", "source_fingerprint", "mapping_hash", "package_hash")
    failure_fields = ("run_id", "task_id", "batch_id", "task_hash", "input_hash", "attempt", "status", "child_agent_id",
                      "result_hash", "error", "record_origin", "tool_references", "time_source", "started_at",
                      "finished_at", "reclaim_state", "reclaimed_at")
    for rejected in manifest.get("rejected_submissions", []):
        if validate_schema(BIZ_FLOW_SUBMISSION_SCHEMA, rejected) or rejected["mode"] != "native" or any(
                rejected[key] != manifest[key] for key in bound_fields):
            continue
        for failed in rejected["execution"]["receipts"]:
            task = tasks.get(failed["task_id"])
            spawned = failed["status"] != "spawn_failed"
            child = failed["child_agent_id"]
            if (failed["status"] == "success" or task is None or not failed["error"] or not failed["error"].strip()
                    or failed["result_hash"] is not None or failed["run_id"] != manifest["run_id"]
                    or failed["task_hash"] != task["task_hash"] or failed["input_hash"] != task["input_hash"]
                    or not spawned and child is not None or spawned and (not isinstance(child, str) or not child.strip())
                    or any(not reference.strip() for reference in failed["tool_references"])
                    or failed["record_origin"] != "host-attested" and not allow_fixture
                    or not _valid_receipt_times(failed)
                    or not spawned and (failed["reclaim_state"] == "reclaimed" or failed["reclaimed_at"] is not None)):
                continue
            current = received.get((failed["task_id"], failed["attempt"]))
            if current is None:
                errors.append("NATIVE_FAILURE_HISTORY_MISSING")
            elif any(current[key] != failed[key] for key in failure_fields):
                errors.append("NATIVE_FAILURE_HISTORY_CHANGED")
    successes = {}
    launched = {}
    attempts = set()
    all_attempts = {}
    for receipt in receipts:
        task = tasks.get(receipt["task_id"])
        if task is None:
            errors.append("NATIVE_UNKNOWN_TASK")
            continue
        identity = (receipt["task_id"], receipt["attempt"])
        if identity in attempts:
            errors.append("NATIVE_DUPLICATE_ATTEMPT")
        attempts.add(identity)
        all_attempts.setdefault(receipt["task_id"], []).append(receipt["attempt"])
        if (receipt["run_id"] != manifest["run_id"] or receipt["task_hash"] != task["task_hash"]
                or receipt["input_hash"] != task["input_hash"]):
            errors.append("NATIVE_RECEIPT_BINDING_MISMATCH")
        if receipt["record_origin"] != "host-attested" and not allow_fixture:
            errors.append("FIXTURE_NOT_ACCEPTABLE")
        spawn_failed = receipt["status"] == "spawn_failed"
        child = receipt["child_agent_id"]
        if (spawn_failed and child is not None) or (not spawn_failed and (not isinstance(child, str) or not child.strip())):
            errors.append("NATIVE_CHILD_ID_INVALID")
        if not spawn_failed and isinstance(child, str) and child.strip():
            launched[f'{receipt["task_id"]}:{receipt["attempt"]}'] = receipt
        if any(not reference.strip() for reference in receipt["tool_references"]):
            errors.append("NATIVE_TOOL_REFERENCE_INVALID")
        if not receipt["batch_id"].strip():
            errors.append("NATIVE_BATCH_ID_INVALID")
        if receipt["status"] == "success":
            if receipt["task_id"] in successes:
                errors.append("NATIVE_DUPLICATE_SUCCESS")
            successes[receipt["task_id"]] = receipt
            result = submitted["results"].get(task["entry_id"])
            if result is None or receipt["result_hash"] != digest(result) or receipt["error"] is not None:
                errors.append("NATIVE_RESULT_HASH_MISMATCH")
        elif not receipt["error"] or not receipt["error"].strip() or receipt["result_hash"] is not None:
            errors.append("NATIVE_FAILURE_EVIDENCE_INVALID")
        if spawn_failed and (receipt["reclaim_state"] == "reclaimed" or receipt["reclaimed_at"] is not None):
            errors.append("NATIVE_FAILURE_EVIDENCE_INVALID")
        if not _valid_receipt_times(receipt):
            errors.append("NATIVE_RECEIPT_TIME_INVALID")
    if set(successes) != set(tasks):
        errors.append("NATIVE_EXECUTION_RECEIPTS_INCOMPLETE")
    for task_id, values in all_attempts.items():
        if values != list(range(1, len(values) + 1)):
            errors.append("NATIVE_ATTEMPT_SEQUENCE_INVALID")
        if task_id in successes and successes[task_id]["attempt"] != max(values):
            errors.append("NATIVE_SUCCESS_NOT_FINAL")
    for task_id in all_attempts:
        history = [receipt for receipt in receipts if receipt["task_id"] == task_id]
        for previous, current in zip(history, history[1:]):
            if previous["time_source"] == current["time_source"] and previous["finished_at"] and current["started_at"]:
                try:
                    if parse_timestamp(current["started_at"]) < parse_timestamp(previous["finished_at"]):
                        errors.append("NATIVE_RETRY_TIME_INVALID")
                except (TypeError, ValueError):
                    errors.append("NATIVE_RECEIPT_TIME_INVALID")
    if submitted["completed_child_agents"] != len({receipt["child_agent_id"] for receipt in successes.values()}):
        errors.append("NATIVE_CHILD_COUNT_MISMATCH")
    bindings = {key: receipt["child_agent_id"] for key, receipt in launched.items()}
    errors.extend(validate_active_observations(observations, bindings))
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(observation.get("active_task_ids"), list):
            continue
        try:
            moment = parse_timestamp(observation["observed_at"])
            active = [launched[key] for key in observation["active_task_ids"] if key in launched]
            if len({receipt["task_id"] for receipt in active}) != len(observation["active_task_ids"]):
                errors.append("ACTIVE_OBSERVATION_INVALID")
            for receipt in active:
                if receipt["time_source"] != observation["time_source"]:
                    continue
                if (receipt["started_at"] and moment < parse_timestamp(receipt["started_at"])
                        or receipt["finished_at"] and moment > parse_timestamp(receipt["finished_at"])):
                    errors.append("ACTIVE_OBSERVATION_OUTSIDE_TASK")
        except (KeyError, TypeError, ValueError):
            errors.append("ACTIVE_OBSERVATION_TIME_INVALID")
    host_intervals = [r for r in launched.values() if r["time_source"] == "host" and r["started_at"] and r["finished_at"]]
    overlap = False
    if "NATIVE_RECEIPT_TIME_INVALID" not in errors:
        for index, left in enumerate(host_intervals):
            for right in host_intervals[index + 1:]:
                if left["task_id"] == right["task_id"]:
                    continue
                if max(parse_timestamp(left["started_at"]), parse_timestamp(right["started_at"])) < min(parse_timestamp(left["finished_at"]), parse_timestamp(right["finished_at"])):
                    if left["child_agent_id"] == right["child_agent_id"]:
                        errors.append("NATIVE_CHILD_INTERVAL_OVERLAP")
                    else:
                        overlap = True
    if submitted["parallel"] != bool(observations or overlap):
        errors.append("PARALLEL_EVIDENCE_MISMATCH")
    return sorted(set(errors))
