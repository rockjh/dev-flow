"""E2E scenario-owner handoff; the current session runs the native tools."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..core.artifacts import ProjectDomainLock, state_root, write_json, write_version_file
from ..core.agents import validate_active_observations
from ..core.schema import validate_schema, get_schema
from ..core.redaction import redact
from .source_versions import scenario_snapshot
from .discovery import _git


PROTOCOL_VERSION = 1
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _run_path(project: Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
        raise ValueError("invalid E2E host run identifier")
    project_key = digest(str(project.resolve()))[:24]
    return state_root() / "e2e" / project_key / run_id / "manifest.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _tree(root: Path, excluded: tuple[str, ...] = ()) -> dict[str, str]:
    """Hash actual files; aliases cannot establish exclusive ownership."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if any(part in SKIP for part in path.relative_to(root).parts):
            continue
        if any(relative == prefix or relative.startswith(prefix + "/") for prefix in excluded):
            continue
        if path.is_symlink() or hasattr(path, "is_junction") and path.is_junction():
            raise ValueError(f"filesystem alias is not an isolated E2E write target: {relative}")
        if path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def scenario_digest(directory: Path) -> str:
    """Exclude only coordinator-owned generation metadata to avoid circular hashes."""
    files = _tree(directory)
    definition = directory / "场景定义.yaml"
    if definition.is_file():
        files["场景定义.yaml"] = hashlib.sha256(_generation_text(definition, {}).encode("utf-8")).hexdigest()
    return digest(files)


def _scenario_directory(project: Path, scope: str) -> Path:
    if not isinstance(scope, str) or not re.fullmatch(r"scenarios/[^/\\]+", scope) or scope.split("/")[-1] in {".", ".."}:
        raise ValueError("invalid exclusive scenario write scope")
    directory = project / scope
    if (directory.is_symlink() or hasattr(directory, "is_junction") and directory.is_junction()
            or directory.parent.is_symlink() or hasattr(directory.parent, "is_junction") and directory.parent.is_junction() or not directory.resolve().is_relative_to(project.resolve())):
        raise ValueError("scenario write scope is not an isolated project directory")
    return directory


def _generation_text(path: Path, generation: dict[str, Any]) -> str:
    """Change only coordinator metadata; preserve human formatting elsewhere."""
    text = path.read_bytes().decode("utf-8")
    root = yaml.compose(text)
    nodes = [(key, value) for key, value in root.value if key.value == "generation"]
    if len(nodes) != 1:
        raise ValueError("generation metadata must appear exactly once")
    key, value = nodes[0]
    last = value
    while isinstance(last, (yaml.MappingNode, yaml.SequenceNode)) and last.value:
        last = last.value[-1][1] if isinstance(last, yaml.MappingNode) else last.value[-1]
    # Mapping end marks include the next block's leading comments. Replace
    # through the last metadata line and leave those human comments intact.
    line_end = text.find("\n", last.end_mark.index)
    end = len(text) if line_end < 0 else line_end + 1
    replacement = yaml.safe_dump({"generation": generation}, allow_unicode=True, sort_keys=False)
    return text[:key.start_mark.index] + replacement + text[end:]


def _inputs(project: Path) -> dict[str, Any]:
    lock = _load(project / "analysis" / "e2e-test-generator-version.json")
    return {key: lock.get(key) for key in ("design", "protocol", "source", "support")}


def _source_workspaces(project: Path, scopes: tuple[str, ...]) -> dict[str, Any]:
    """Detect forbidden source writes without using dirty source as code evidence."""
    workspace = yaml.safe_load((project / "analysis" / "workspace.yaml").read_text(encoding="utf-8"))
    result = {}
    for repository in workspace.get("inventory", {}).get("repositories", []):
        root = Path(repository["root"])
        root = root.resolve() if root.is_absolute() else (project / root).resolve()
        listing = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        head = _git(root, "rev-parse", "HEAD")
        if listing.returncode or head.returncode:
            raise ValueError("committed repository evidence is unavailable")
        allowed = tuple((project / scope).resolve() for scope in scopes)
        files = {}
        for relative in listing.stdout.split("\0"):
            if not relative:
                continue
            path = root / relative
            if any(path.resolve().is_relative_to(directory) for directory in allowed):
                continue
            if path.is_symlink() or hasattr(path, "is_junction") and path.is_junction():
                raise ValueError("source filesystem aliases cannot establish scenario write isolation")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        result[repository["id"]] = {"head": head.stdout.strip(), "workspace_sha256": digest(files)}
    return result


def validate_serial_approval(project: Path, approval: dict[str, Any], scopes: set[str] | None = None, *, check_current_runs: bool = True) -> list[str]:
    """Check explicit scoped authorization before any generation/state writes."""
    errors = validate_schema(get_schema("e2e.serial-approval")["document"], approval)
    if errors:
        return ["serial approval schema: " + error for error in errors]
    if redact(approval) != approval:
        errors.append("serial approval must be redacted")
    for key in ("reference", "reason", "diagnostic_reference"):
        if not approval[key].strip():
            errors.append(f"serial approval requires a real {key}")
    if len(set(approval["scopes"])) != len(approval["scopes"]) or scopes is not None and set(approval["scopes"]) != scopes:
        errors.append("serial approval must cover the complete current scenario scopes exactly")
    for scope in approval["scopes"]:
        try:
            _scenario_directory(project, scope)
        except ValueError as exc:
            errors.append(str(exc))
    prior = approval["prior_run_ids"]
    if len(set(prior)) != len(prior):
        errors.append("serial approval has duplicate prior runs")
    try:
        for run_id in prior:
            old = _load(_run_path(project, run_id))
            if old.get("project_root") != str(project.resolve()) or old.get("run_id") != run_id:
                errors.append("serial approval prior run belongs to another project")
        referenced = {yaml.safe_load(path.read_text(encoding="utf-8")).get("generation", {}).get("host_task", {}).get("run_id")
                      for path in (project / "scenarios").glob("*/场景定义.yaml")}
        if check_current_runs and not (referenced - {None}).issubset(prior):
            errors.append("serial approval must link every previous scenario run; old history is preserved")
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        errors.append(f"serial approval prior run unavailable: {exc}")
    return errors


def load_serial_approval(project: Path, path: Path) -> dict[str, Any]:
    approval = _load(path)
    errors = validate_serial_approval(project, approval)
    if errors:
        raise ValueError("; ".join(errors))
    return approval


def prepare_scenario_owners(project: Path, *, delegate: bool = False, serial_approval: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Freeze existing domain inputs after generate; templates are not child results."""
    project = project.resolve()
    directories = sorted(path for path in (project / "scenarios").iterdir() if path.is_dir() and (path / "场景定义.yaml").is_file())
    if len(directories) < 2 and not delegate and serial_approval is None:
        return None
    for directory in directories:
        _scenario_directory(project, f"scenarios/{directory.name}")
    if serial_approval is not None:
        errors = validate_serial_approval(project, serial_approval, {f"scenarios/{path.name}" for path in directories})
        if errors:
            raise ValueError("; ".join(errors))
    # Init can also generate native tasks. Freeze its generated document state
    # before the read-only snapshot, while keeping non-delegated init unchanged.
    from .document_gate import mark_generated
    mark_generated(project)
    run_id = uuid.uuid4().hex
    manifest_path = _run_path(project, run_id)
    inputs = _inputs(project)
    input_sha256 = digest(inputs)
    tasks = []
    for directory in directories:
        _scenario_directory(project, f"scenarios/{directory.name}")
        definition = yaml.safe_load((directory / "场景定义.yaml").read_text(encoding="utf-8"))
        task = {
            "protocol_version": PROTOCOL_VERSION, "domain": "e2e", "run_id": run_id,
            "task_id": digest(directory.name)[:24], "scenario_id": definition["meta"]["id"],
            "project_root": str(project), "write_scope": f"scenarios/{directory.name}",
            "input_sha256": input_sha256, "inputs": inputs,
            "source": definition.get("source", []),
            "design_rule_ids": sorted({str(step.get("design_rule_id")) for step in definition.get("steps", []) if isinstance(step, dict) and step.get("design_rule_id")}),
            "starter_sha256": scenario_digest(directory),
            "result_path": str(manifest_path.parent / (digest(directory.name)[:24] + ".result.json")),
            "instructions": "Independently analyze committed design, protocol and source evidence, then complete or correct only this scenario. Starter assets are not analysis results. Do not execute remote tests, change source/common/configuration/dependencies/discovery/version locks, or spawn nested agents. Report evidence, blockers and shared changes. Stop on unsafe or missing evidence.",
            "permission_enforcement": "shared_workspace_with_scope_validation",
        }
        if serial_approval is not None:
            task.update({"mode": "serial", "serial_approval": serial_approval})
        task["task_sha256"] = digest(task)
        tasks.append(task)
    scopes = tuple(task["write_scope"] for task in tasks)
    manifest = {
        "protocol_version": PROTOCOL_VERSION, "domain": "e2e", "run_id": run_id,
        "project_root": str(project), "input_sha256": input_sha256,
        "status": "tasks_prepared", "mode": "serial" if serial_approval is not None else "native", "parallel": False,
        "degraded": serial_approval is not None, "completed_child_agents": 0, "tasks": tasks,
        "readonly_snapshot": _tree(project, scopes), "receipts": [], "observations": [],
        "source_workspaces": _source_workspaces(project, scopes),
        "trust_boundary": "host-attested; CLI verifies structure and consistency, not tool-call authenticity",
    }
    if serial_approval is not None:
        manifest["serial_approval"] = serial_approval
    write_json(manifest_path, manifest)
    documents = {}
    for task in tasks:
        write_json(manifest_path.parent / (task["task_id"] + ".task.json"), task)
        path = _scenario_directory(project, task["write_scope"]) / "场景定义.yaml"
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        generation = dict(definition["generation"])
        generation["host_task"] = {"run_id": run_id, "task_id": task["task_id"]}
        documents[path] = _generation_text(path, generation)
    from .contracts import _write_artifacts
    _write_artifacts(documents)
    return {"status": "tasks_prepared", "run_id": run_id, "manifest_path": str(manifest_path), "tasks": tasks,
            **{key: manifest[key] for key in ("mode", "degraded", "parallel", "completed_child_agents")}}


def _validate_results(project: Path, manifest: dict[str, Any], payload: dict[str, Any], *, allow_fixture: bool = False, verify_workspace: bool = True) -> list[str]:
    errors = validate_schema(get_schema("e2e.host-run")["document"], manifest)
    errors.extend(validate_schema(get_schema("e2e.host-results")["document"], payload))
    if errors:
        return ["host-results schema: " + error for error in errors]
    if payload.get("fixture") and not allow_fixture:
        errors.append("fixture receipts cannot enter a real E2E acceptance report")
    if redact(payload) != payload:
        errors.append("host-results must be redacted before hashes and submission")
    if manifest.get("protocol_version") != PROTOCOL_VERSION or payload.get("run_id") != manifest.get("run_id") or manifest.get("project_root") != str(project):
        errors.append("host-results run/project/protocol mismatch")
    if manifest.get("input_sha256") != digest(_inputs(project)):
        errors.append("host-results inputs changed; generate a new run")
    for kind in ("design", "protocol"):
        for document in _inputs(project).get(kind, {}).get("documents", []):
            if document.get("source_type") in {"runtime_url", "service_config"}:
                continue
            path = Path(document["path"])
            path = path if path.is_absolute() else project / path
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]:
                errors.append(f"host-results locked {kind} document changed")
    tasks = {task["task_id"]: task for task in manifest.get("tasks", [])}
    serial = manifest["mode"] == "serial"
    if payload["mode"] != manifest["mode"] or payload["degraded"] is not serial or manifest["degraded"] is not serial:
        errors.append("host-results execution mode/degradation mismatch")
    if serial:
        errors.extend(validate_serial_approval(project, manifest.get("serial_approval", {}), {task["write_scope"] for task in tasks.values()}, check_current_runs=False))
        if payload.get("serial_approval") != manifest.get("serial_approval"):
            errors.append("host-results serial approval changed")
        if payload["parallel"] or payload["completed_child_agents"] != 0 or payload["observations"]:
            errors.append("host-results serial mode requires zero children and no parallel observations")
    elif "serial_approval" in payload or "serial_approval" in manifest:
        errors.append("host-results native mode cannot carry serial approval")
    if len(tasks) != len(manifest.get("tasks", [])) or len({task["write_scope"] for task in tasks.values()}) != len(tasks):
        errors.append("host-results duplicate frozen task or write scope")
    successes: dict[str, dict[str, Any]] = {}
    attempts: set[tuple[str, int]] = set()
    next_attempt: dict[str, int] = {}
    bindings: dict[str, str] = {}
    for receipt in payload.get("receipts", []):
        task_id = receipt["task_id"]
        task = tasks.get(task_id)
        if task is None:
            errors.append(f"host-results unknown task: {task_id}")
            continue
        key = (task_id, receipt["attempt"])
        if key in attempts:
            errors.append(f"host-results duplicate attempt: {task_id}")
        attempts.add(key)
        if receipt["attempt"] != next_attempt.get(task_id, 1):
            errors.append(f"host-results attempts must be consecutive and ordered: {task_id}")
        next_attempt[task_id] = receipt["attempt"] + 1
        if task_id in successes:
            errors.append(f"host-results attempt after successful completion: {task_id}")
        if any(not reference.strip() for reference in receipt["tool_records"]):
            errors.append(f"host-results tool records must contain real references: {task_id}")
        if receipt["run_id"] != manifest["run_id"] or any(receipt[field] != task[field] for field in ("task_sha256", "input_sha256", "write_scope")):
            errors.append(f"host-results stale or cross-run task binding: {task_id}")
        if task.get("task_sha256") != digest({key: value for key, value in task.items() if key != "task_sha256"}):
            errors.append(f"host-results frozen task changed: {task_id}")
        if serial and (task.get("mode") != "serial" or task.get("serial_approval") != manifest.get("serial_approval")) or not serial and ("mode" in task or "serial_approval" in task):
            errors.append(f"host-results task execution context changed: {task_id}")
        if (task.get("run_id") != manifest["run_id"] or task.get("project_root") != str(project)
                or task.get("input_sha256") != manifest["input_sha256"]):
            errors.append(f"host-results task input/run/project mismatch: {task_id}")
        if serial:
            if receipt["child_agent_id"] is not None or receipt["status"] == "spawn_failed":
                errors.append(f"host-results serial analysis cannot claim a child or spawn attempt: {task_id}")
        elif receipt["status"] == "spawn_failed":
            if receipt["child_agent_id"] is not None:
                errors.append(f"host-results spawn_failed cannot claim a child agent: {task_id}")
        elif not isinstance(receipt["child_agent_id"], str) or not receipt["child_agent_id"].strip():
            errors.append(f"host-results started attempt requires a child agent: {task_id}")
        else:
            bindings[f"{task_id}:{receipt['attempt']}"] = receipt["child_agent_id"]
        if receipt["status"] != "success":
            if not isinstance(receipt.get("error"), str) or not receipt["error"].strip() or receipt.get("result_sha256") is not None:
                errors.append(f"host-results failed attempt must retain error and no success digest: {task_id}")
            continue
        if task_id in successes:
            errors.append(f"host-results duplicate success: {task_id}")
        if receipt.get("error") is not None:
            errors.append(f"host-results successful attempt cannot retain an error: {task_id}")
        successes[task_id] = receipt
        directory = _scenario_directory(project, task["write_scope"])
        if receipt["result_sha256"] != scenario_digest(directory):
            errors.append(f"host-results result digest mismatch: {task_id}")
        definition = yaml.safe_load((directory / "场景定义.yaml").read_text(encoding="utf-8"))
        if definition.get("meta", {}).get("id") != task["scenario_id"]:
            errors.append(f"host-results scenario identity changed: {task_id}")
        if definition.get("generation", {}).get("host_task") != {"run_id": manifest["run_id"], "task_id": task_id}:
            errors.append(f"host-results current scenario task binding changed; collect its latest prepared run: {task_id}")
        if not receipt.get("analysis_summary", "").strip() or not receipt.get("source_evidence"):
            errors.append(f"host-results source analysis evidence required: {task_id}")
        if serial and (not receipt.get("written_paths") or receipt["result_sha256"] == task["starter_sha256"]):
            errors.append(f"host-results serial analysis must complete scenario artifacts; prepared templates are not results: {task_id}")
        allowed_evidence = {f"{source.get('repo')}#{anchor}" for source in definition.get("source", []) for anchor in source.get("anchors", [])}
        if not set(receipt.get("source_evidence", [])).issubset(allowed_evidence):
            errors.append(f"host-results source evidence is outside the scenario contract: {task_id}")
        if any(not isinstance(path, str) or "\\" in path or ".." in Path(path).parts or not path.startswith(task["write_scope"] + "/") for path in receipt.get("written_paths", [])):
            errors.append(f"host-results child wrote outside its exclusive scope: {task_id}")
    if set(successes) != set(tasks):
        errors.append("host-results required scenarios are incomplete")
    completed = {receipt["child_agent_id"] for receipt in successes.values() if receipt["child_agent_id"] is not None}
    if payload.get("completed_child_agents") != len(completed):
        errors.append("host-results child count must equal unique successful child agents")
    observations = payload.get("observations", [])
    errors.extend(validate_active_observations(observations, bindings))
    for observation in observations:
        active = observation.get("active_task_ids", [])
        if len({item.rsplit(":", 1)[0] for item in active}) != len(active):
            errors.append("host-results overlapping attempts cannot own the same scenario")
    # A shared workspace prompt is not an OS sandbox. Detect changes outside
    # all independently owned scenario scopes before accepting any owner.
    scopes = tuple(task["write_scope"] for task in tasks.values())
    if verify_workspace and _tree(project, scopes) != manifest.get("readonly_snapshot"):
        errors.append("host-results read-only files changed outside the delegated scenario scopes")
    if verify_workspace and _source_workspaces(project, scopes) != manifest.get("source_workspaces"):
        errors.append("host-results source repository changed outside the delegated scenario scopes")
    if payload.get("parallel"):
        if not any(len(observation.get("active_task_ids", [])) >= 2 for observation in observations):
            errors.append("host-results parallel=true requires observed active task overlap")
    elif observations:
        errors.append("host-results parallel=false conflicts with observed active task overlap")
    return errors


def _failed_receipts(project: Path, manifest: dict[str, Any], payload: Any, *, allow_fixture: bool) -> list[dict[str, Any]]:
    """Validate failure evidence without depending on another task's outputs."""
    if not isinstance(payload, dict) or not isinstance(payload.get("receipts"), list):
        return []
    receipts = payload["receipts"]
    valid = []
    for index, receipt in enumerate(receipts):
        if validate_schema(get_schema("e2e.host-receipt")["document"], receipt) or receipt["status"] == "success":
            continue
        identity = receipt["task_id"], receipt["attempt"]
        if sum(isinstance(item, dict) and (item.get("task_id"), item.get("attempt")) == identity for item in receipts) != 1:
            continue
        prefix = [item for item in receipts[:index + 1] if isinstance(item, dict) and item.get("task_id") == receipt["task_id"]]
        # Counts and parallel observations concern the whole submission; they do
        # not change a bound, explicit task failure. No successful output enters
        # this prefix, because attempts after success fail the existing gate.
        candidate = {**payload, "receipts": prefix, "parallel": False, "completed_child_agents": 0, "observations": []}
        errors = _validate_results(project, manifest, candidate, allow_fixture=allow_fixture, verify_workspace=False)
        if all(error == "host-results required scenarios are incomplete" for error in errors):
            valid.append(receipt)
    return valid


def _failure_history(project: Path, manifest: dict[str, Any], payload: dict[str, Any], *, allow_fixture: bool) -> tuple[list[str], list[dict[str, Any]]]:
    """Keep legal failed attempts while excluding invalid replacement evidence."""
    retained: dict[tuple[str, int], dict[str, Any]] = {}
    errors = []
    for path in sorted(_run_path(project, manifest["run_id"]).parent.glob("rejected-*.json")):
        try:
            rejected = _load(path)
            valid = _failed_receipts(project, manifest, rejected.get("submission"), allow_fixture=allow_fixture)
            for receipt in rejected.get("retained_failures", valid):
                if receipt in valid:
                    identity = receipt["task_id"], receipt["attempt"]
                    if identity in retained and retained[identity] != receipt:
                        errors.append(f"host-results failed attempt history conflicts: {identity[0]}:{identity[1]}")
                    else:
                        retained[identity] = receipt
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            continue
    if not isinstance(payload.get("receipts"), list):
        return errors, []
    current = {(receipt["task_id"], receipt["attempt"]): receipt for receipt in payload.get("receipts", [])
               if not validate_schema(get_schema("e2e.host-receipt")["document"], receipt)}
    for identity, receipt in retained.items():
        if identity not in current:
            errors.append(f"host-results failed attempt history missing: {identity[0]}:{identity[1]}")
        elif current[identity] != receipt:
            errors.append(f"host-results failed attempt history changed: {identity[0]}:{identity[1]}")
    failures = [receipt for receipt in _failed_receipts(project, manifest, payload, allow_fixture=allow_fixture)
                if (receipt["task_id"], receipt["attempt"]) not in retained or retained[(receipt["task_id"], receipt["attempt"])] == receipt]
    return errors, failures


def collect_scenario_owners(project: Path, payload_path: Path, *, allow_fixture: bool = False) -> tuple[dict[str, Any], list[str]]:
    """Existing check consumes a complete handoff before running domain gates."""
    project = project.resolve()
    try:
        payload = _load(payload_path)
        manifest_path = _run_path(project, payload.get("run_id"))
        manifest = _load(manifest_path)
        with ProjectDomainLock(project, "e2e"):
            if manifest.get("status") == "results_collected":
                if manifest.get("submission_sha256") != digest({**payload, "fixture": bool(payload.get("fixture"))}):
                    return {}, ["host-results different results cannot overwrite a collected run"]
                errors = ownership_errors(project, manifest=manifest, allow_fixture=allow_fixture)
                return {"status": "results_collected", "manifest_path": str(manifest_path), "idempotent": True,
                        **{key: manifest[key] for key in ("mode", "degraded", "parallel", "completed_child_agents")}}, errors
            errors = _validate_results(project, manifest, payload, allow_fixture=allow_fixture)
            history_errors, failures = _failure_history(project, manifest, payload, allow_fixture=allow_fixture)
            errors.extend(history_errors)
            if errors:
                write_json(manifest_path.parent / ("rejected-" + digest(payload)[:16] + ".json"), {"status": "rejected", "errors": errors, "submission": redact(payload), "retained_failures": failures})
                return {}, errors
            successes = {receipt["task_id"]: receipt for receipt in payload["receipts"] if receipt["status"] == "success"}
            documents = {}
            for task in manifest["tasks"]:
                path = _scenario_directory(project, task["write_scope"]) / "场景定义.yaml"
                generation = {
                    "mode": "sequential_degraded" if manifest["mode"] == "serial" else "delegated",
                    "owner": "main-agent" if manifest["mode"] == "serial" else successes[task["task_id"]]["child_agent_id"],
                    "write_scope": task["write_scope"], "degradation_reason": manifest.get("serial_approval", {}).get("reason"),
                    "host_task": {"run_id": manifest["run_id"], "task_id": task["task_id"]},
                }
                if manifest["mode"] == "serial":
                    generation["serial_approval"] = {"reference": manifest["serial_approval"]["reference"], "scope": task["write_scope"]}
                documents[path] = _generation_text(path, generation)
            from .contracts import _write_artifacts
            _write_artifacts(documents)
            # Only the CLI updates the existing version authority after ownership
            # validation; child generation never grants this write permission.
            lock_path = project / "analysis" / "e2e-test-generator-version.json"
            lock = _load(lock_path)
            lock["scenarios"] = scenario_snapshot(project)
            write_version_file(project, "e2e", lock, path=lock_path)
            manifest.update({key: payload[key] for key in ("parallel", "completed_child_agents", "receipts", "observations")})
            manifest.update({"status": "results_collected", "submission_sha256": digest({**payload, "fixture": bool(payload.get("fixture"))}), "fixture": bool(payload.get("fixture"))})
            for task in manifest["tasks"]:
                write_json(manifest_path.parent / (task["task_id"] + ".result.json"), successes[task["task_id"]])
            write_json(manifest_path, manifest)
            return {"status": "results_collected", "manifest_path": str(manifest_path), **{key: manifest[key] for key in ("mode", "degraded", "parallel", "completed_child_agents", "trust_boundary")}}, []
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        return {}, [f"host-results invalid handoff: {exc}"]


def ownership_errors(project: Path, *, definition: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None, allow_fixture: bool = False) -> list[str]:
    """Retain collected task/result binding at every existing ownership gate."""
    try:
        if manifest is None:
            reference = definition.get("generation", {}).get("host_task") if definition else None
            if not isinstance(reference, dict) or set(reference) != {"run_id", "task_id"}:
                return ["delegated owner requires a collected host_task run/task reference"]
            manifest = _load(_run_path(project, reference["run_id"]))
        if manifest.get("status") != "results_collected" or (manifest.get("fixture") and not allow_fixture):
            return ["delegated owner requires non-fixture collected host results"]
        if manifest.get("input_sha256") != digest(_inputs(project)):
            return ["delegated owner input fingerprint is stale"]
        submission = {key: manifest.get(key) for key in ("protocol_version", "domain", "run_id", "mode", "degraded", "parallel", "completed_child_agents", "receipts", "observations", "fixture")}
        if "serial_approval" in manifest:
            submission["serial_approval"] = manifest["serial_approval"]
        if digest(submission) != manifest.get("submission_sha256"):
            return ["delegated owner receipt set changed after collection"]
        errors = _validate_results(project, manifest, submission, allow_fixture=allow_fixture, verify_workspace=False)
        successes = {receipt["task_id"]: receipt for receipt in manifest["receipts"] if receipt["status"] == "success"}
        for task in manifest["tasks"]:
            path = _scenario_directory(project, task["write_scope"]) / "场景定义.yaml"
            current = yaml.safe_load(path.read_text(encoding="utf-8"))
            expected = {"run_id": manifest["run_id"], "task_id": task["task_id"]}
            generation = current.get("generation", {})
            receipt = successes.get(task["task_id"], {})
            serial = manifest["mode"] == "serial"
            owner = "main-agent" if serial else receipt.get("child_agent_id")
            mode = "sequential_degraded" if serial else "delegated"
            if generation.get("host_task") != expected or generation.get("owner") != owner or generation.get("mode") != mode or generation.get("write_scope") != task["write_scope"]:
                errors.append("delegated owner/task/scenario binding mismatch")
            if serial and (generation.get("degradation_reason") != manifest["serial_approval"]["reason"] or generation.get("serial_approval") != {"reference": manifest["serial_approval"]["reference"], "scope": task["write_scope"]}):
                errors.append("serial owner authorization/scenario binding mismatch")
            if receipt.get("result_sha256") != scenario_digest(path.parent):
                errors.append("delegated owner result changed after collection")
        if definition is not None:
            reference = definition["generation"]["host_task"]
            if reference["task_id"] not in successes:
                errors.append("delegated owner references an unknown task")
        return errors
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        return [f"delegated owner receipt is unavailable or invalid: {exc}"]
