"""CLI for source-backed biz-flow design documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..core.schema import (
    BIZ_FLOW_COMPARISON_SCHEMA,
    BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA,
    BIZ_FLOW_DISCOVERY_SCHEMA,
    BIZ_FLOW_EVIDENCE_CACHE_SCHEMA,
    BIZ_FLOW_INDEX_SCHEMA,
    BIZ_FLOW_MIGRATIONS_SCHEMA,
    BIZ_FLOW_OWNERSHIP_SCHEMA,
    BIZ_FLOW_PROGRESS_SCHEMA,
    BIZ_FLOW_REPORT_SCHEMA,
    BIZ_FLOW_SCHEMA_VERSION,
    validate_schema,
)
from ..core.redaction import redact
from .discovery import source_fingerprint, scan
from .documents import apply_module_map, coverage, write_artifacts, write_discovery, _validate_mermaid
from .git import changed_paths, working_tree_paths
from .models import BehaviorEvidence, EntryPoint, ErrorEvidence, GitInfo, ScanResult


_PROTECTED_NAMES = {"prod", "prd", "live", "production"}


@contextmanager
def _run_lock(docs_root: Path):
    """Prevent overlapping writers while leaving a recoverable stale lock."""
    docs_root.mkdir(parents=True, exist_ok=True)
    lock_path = docs_root / "biz-flow-run.lock"
    payload = {"pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()}
    owned = False
    for attempt in range(2):
        try:
            with lock_path.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
            owned = True
            break
        except FileExistsError:
            stale = False
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
                pid = int(current.get("pid", 0)) if isinstance(current, dict) else 0
                if pid and pid != os.getpid():
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        stale = True
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                stale = True
            if stale and attempt == 0:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            raise RuntimeError(f"another biz-flow writer is active: {lock_path}")
    try:
        yield
    finally:
        if owned:
            try:
                lock_path.unlink()
            except OSError:
                pass


def _command_paths(argv: list[str]) -> tuple[Path, Path]:
    """Extract paths before argparse so public command helpers can be locked."""
    project = Path(".")
    docs = Path("docs/biz-flow")
    for index, value in enumerate(argv):
        if value == "--project" and index + 1 < len(argv):
            project = Path(argv[index + 1])
        elif value == "--docs-root" and index + 1 < len(argv):
            docs = Path(argv[index + 1])
    project = project.resolve()
    return project, _docs_root(project, docs)


def _locked(argv: list[str], action):
    try:
        project, docs_root = _command_paths(argv)
        if error := _write_scope_error(project, docs_root):
            print(f"ERROR: {error}", file=sys.stderr)
            return 8
        with _run_lock(docs_root):
            return action()
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 8


def _write_scope_error(project: Path, docs_root: Path) -> str | None:
    """Refuse document writes in names conventionally reserved for production."""
    path_parts = {part.casefold() for part in (*project.resolve().parts, *docs_root.resolve().parts)}
    if path_parts & _PROTECTED_NAMES:
        return "biz-flow writes are blocked for protected production paths"
    for name in ("DEVFLOW_ENV", "APP_ENV", "DEPLOY_ENV", "RUNTIME_ENV", "ENVIRONMENT"):
        if os.environ.get(name, "").strip().casefold() in _PROTECTED_NAMES:
            return f"biz-flow writes are blocked for protected environment {name}"
    if os.environ.get("DEVFLOW_PROTECTED", "").strip().casefold() in {"1", "true", "yes", "on"}:
        return "biz-flow writes are blocked by DEVFLOW_PROTECTED"
    return None


def _progress(
    docs_root: Path,
    stage: str,
    status: str,
    fingerprint: str = "",
    error: str | None = None,
    *,
    resumed: bool = False,
    cache_entries: int = 0,
) -> None:
    # Progress is intentionally process-local; no progress or failure files are persisted.
    return
    docs_root.mkdir(parents=True, exist_ok=True)
    run_id = hashlib.sha256(f"{stage}:{fingerprint}:{os.getpid()}".encode("utf-8")).hexdigest()[:16]
    failure_log = docs_root / "biz-flow-failures.log"
    failure_log_value: str | None = None
    if error:
        safe_error = str(redact(error))
        failure_log.parent.mkdir(parents=True, exist_ok=True)
        with failure_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now(timezone.utc).isoformat()} {run_id} {stage}: {safe_error}\n")
        failure_log_value = str(failure_log)
    else:
        safe_error = None
    progress = {
            "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
            "run_id": run_id,
            "run_handle": f"biz-flow:{run_id}",
            "phase": stage,
            "stage": stage,
            "status": status,
            "source_fingerprint": fingerprint,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": safe_error,
            "failure_log": failure_log_value,
            "resumed": resumed,
            "cache_entries": cache_entries,
        }
    progress_errors = validate_schema(BIZ_FLOW_PROGRESS_SCHEMA, progress)
    if progress_errors:
        raise ValueError("invalid biz-flow progress: " + "; ".join(progress_errors))
    (docs_root / "biz-flow-progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resume_error(docs_root: Path, fingerprint: str) -> str | None:
    path = docs_root / "biz-flow-progress.json"
    if not path.is_file():
        return f"no resumable biz-flow progress at {path}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"cannot read progress: {exc}"
    if not isinstance(value, dict) or value.get("source_fingerprint") != fingerprint:
        return "progress source fingerprint is stale; start a new run"
    schema_errors = validate_schema(BIZ_FLOW_PROGRESS_SCHEMA, value)
    if schema_errors:
        return "progress is invalid: " + "; ".join(schema_errors)
    return None


def _resume_cache(docs_root: Path, fingerprint: str) -> tuple[int, str | None]:
    """Validate the complete evidence cache required by a resumed run."""
    path = docs_root / "biz-flow-evidence-cache.json"
    if not path.is_file():
        return 0, f"no resumable evidence cache at {path}; start a new run"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return 0, f"cannot read evidence cache: {exc}"
    if not isinstance(value, dict) or value.get("source_fingerprint") != fingerprint:
        return 0, "evidence cache source fingerprint is stale; start a new run"
    if value.get("schema_version") != int(BIZ_FLOW_SCHEMA_VERSION):
        return 0, "evidence cache schema version is stale; start a new run"
    if not isinstance(value.get("source_lines", {}), dict):
        return 0, "evidence cache is invalid: source_lines must be an object"
    schema_errors = validate_schema(BIZ_FLOW_EVIDENCE_CACHE_SCHEMA, value)
    if schema_errors:
        return 0, "evidence cache is invalid: " + "; ".join(schema_errors)
    entries = value.get("entries")
    if not isinstance(entries, dict):
        return 0, "evidence cache is invalid: entries must be an object"
    return len(entries), None


def _cached_scan(docs_root: Path, project: Path, fingerprint: str) -> tuple[ScanResult | None, str | None]:
    """Rebuild a scan result from the validated cache; never infer missing evidence."""
    path = docs_root / "biz-flow-evidence-cache.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"cannot read evidence cache: {exc}"
    if not isinstance(value, dict) or value.get("source_fingerprint") != fingerprint:
        return None, "evidence cache source fingerprint is stale; start a new run"
    git_value = value.get("git")
    if not isinstance(git_value, dict):
        return None, "evidence cache is incomplete: git metadata is missing"
    entries_value = value.get("entries")
    if not isinstance(entries_value, dict):
        return None, "evidence cache is invalid: entries must be an object"
    source_lines_value = value.get("source_lines", {})
    if not isinstance(source_lines_value, dict):
        return None, "evidence cache is invalid: source_lines must be an object"
    schema_errors = validate_schema(BIZ_FLOW_EVIDENCE_CACHE_SCHEMA, value)
    if schema_errors:
        return None, "evidence cache is invalid: " + "; ".join(schema_errors)

    def string_list(name: str) -> tuple[list[str] | None, str | None]:
        raw = value.get(name, [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            return None, f"evidence cache is invalid: {name} must be a string array"
        return list(raw), None

    files, error = string_list("files")
    if error:
        return None, error
    try:
        source_lines = {str(key): int(number) for key, number in source_lines_value.items()}
    except (TypeError, ValueError) as exc:
        return None, f"evidence cache is invalid: numeric source_lines are malformed ({exc})"
    known_files = set(files or [])

    def valid_cached_source(location: tuple[str, int]) -> bool:
        file, line = location
        return file in known_files and 1 <= line <= source_lines.get(file, 0)

    def source(value: object, fallback: str) -> tuple[str, int] | None:
        raw = str(value or fallback)
        file, separator, number = raw.rpartition(":")
        if not separator or not file or not number.isdigit():
            return None
        return file, int(number)

    entries: list[EntryPoint] = []
    for key, raw in entries_value.items():
        if not isinstance(raw, dict):
            return None, f"evidence cache entry {key} is not an object"
        entry_id = str(raw.get("id") or key)
        if entry_id != str(key) or not all(str(raw.get(field, "")).strip() for field in ("type", "identifier", "handler", "module")):
            return None, f"evidence cache entry {key} has incomplete identity fields"
        location = source(raw.get("source"), "")
        if location is None or not valid_cached_source(location):
            return None, f"evidence cache entry {entry_id} has no valid source location"
        file, line = location
        error_values = raw.get("errors", [])
        if not isinstance(error_values, list):
            return None, f"evidence cache entry {entry_id} has invalid errors"
        errors: list[ErrorEvidence] = []
        for item in error_values:
            if not isinstance(item, dict):
                return None, f"evidence cache entry {entry_id} has invalid error evidence"
            error_location = source(item.get("source"), f"{file}:{line}")
            if error_location is None or not valid_cached_source(error_location):
                return None, f"evidence cache entry {entry_id} has invalid error source"
            error_file, error_line = error_location
            errors.append(ErrorEvidence(
                str(item.get("code", "代码中未确认")),
                str(item.get("condition", "代码中未确认")),
                error_file,
                error_line,
                str(item.get("capture_boundary", "代码中未确认")),
                str(item.get("propagation", "代码中未确认")),
                str(item.get("consequence", "代码中未确认")),
                str(item.get("phase", "sync")),
                str(item.get("recovery", "代码中未确认")),
            ))
        behavior_values = raw.get("behaviors", [])
        if not isinstance(behavior_values, list):
            return None, f"evidence cache entry {entry_id} has invalid behaviors"
        functions_value = raw.get("functions", [])
        if not isinstance(functions_value, list) or any(not isinstance(item, str) for item in functions_value):
            return None, f"evidence cache entry {entry_id} has invalid functions"
        behaviors: list[BehaviorEvidence] = []
        for item in behavior_values:
            if not isinstance(item, dict):
                return None, f"evidence cache entry {entry_id} has invalid behavior evidence"
            behavior_location = source(item.get("source"), f"{file}:{line}")
            if behavior_location is None or not valid_cached_source(behavior_location):
                return None, f"evidence cache entry {entry_id} has invalid behavior source"
            behavior_file, behavior_line = behavior_location
            behaviors.append(BehaviorEvidence(
                str(item.get("kind", "行为")),
                str(item.get("statement", "代码中未确认")),
                behavior_file,
                behavior_line,
            ))
        entries.append(EntryPoint(
            entry_id=entry_id,
            kind=str(raw.get("type", "")),
            identifier=str(raw.get("identifier", "")),
            handler=str(raw.get("handler", "代码中未确认")),
            file=file,
            line=line,
            module=str(raw.get("module", "公共能力")),
            source=file,
            module_rationale=str(raw.get("module_rationale", "代码中未确认")),
            caller=str(raw.get("caller", "代码中未确认")),
            input_summary=str(raw.get("input_summary", "代码中未确认")),
            functions=list(functions_value),
            errors=errors,
            behaviors=behaviors,
            has_loop=bool(raw.get("has_loop")),
            has_external_call=bool(raw.get("has_external_call")),
            has_persistence=bool(raw.get("has_persistence")),
            has_async=bool(raw.get("has_async")),
            binding_confirmed=bool(raw.get("binding_confirmed", True)),
            handler_confirmed=bool(raw.get("handler_confirmed", True)),
        ))
    try:
        git = GitInfo(
            branch=str(git_value["branch"]),
            head=str(git_value["head"]),
            target=str(git_value["target"]),
            dirty=bool(git_value["dirty"]),
            includes_uncommitted=bool(git_value["includes_uncommitted"]),
            comparison=str(git_value.get("comparison", "current")),
        )
    except (KeyError, TypeError) as exc:
        return None, f"evidence cache is incomplete: invalid git metadata ({exc})"
    languages, error = string_list("languages")
    if error:
        return None, error
    frameworks, error = string_list("frameworks")
    if error:
        return None, error
    unresolved, error = string_list("unresolved")
    if error:
        return None, error
    exclusions, error = string_list("exclusions")
    if error:
        return None, error
    try:
        discovered_entry_count = int(value.get("candidate_entry_count", len(entries)))
        discovered_binding_count = int(value.get("confirmed_binding_count", len(entries)))
        discovered_handler_count = int(value.get("confirmed_handler_count", len({item.handler for item in entries})))
    except (TypeError, ValueError) as exc:
        return None, f"evidence cache is invalid: numeric metadata is malformed ({exc})"
    return ScanResult(
        root=project.resolve(),
        git=git,
        languages=languages or [],
        frameworks=frameworks or [],
        entries=sorted(entries, key=lambda item: (item.module, item.kind, item.identifier, item.file, item.line)),
        files=files or [],
        unresolved=unresolved or [],
        source_fingerprint=fingerprint,
        source_lines=source_lines,
        exclusions=exclusions or [],
        discovered_entry_count=discovered_entry_count,
        discovered_binding_count=discovered_binding_count,
        discovered_handler_count=discovered_handler_count,
    ), None


def _scan_for_run(
    project: Path,
    docs_root: Path,
    target: str | None,
) -> tuple[ScanResult | None, bool, int, str | None]:
    resume = False
    if not resume:
        try:
            return scan(project, target), False, 0, None
        except Exception as exc:
            return None, False, 0, f"biz-flow scan failed: {exc}"
    try:
        fingerprint = source_fingerprint(project, target)
    except Exception as exc:
        return None, False, 0, f"cannot fingerprint source snapshot: {exc}"
    if error := _resume_error(docs_root, fingerprint):
        return None, False, 0, error
    cache_entries, error = _resume_cache(docs_root, fingerprint)
    if error:
        return None, False, 0, error
    result, error = _cached_scan(docs_root, project, fingerprint)
    if error:
        return None, False, 0, error
    return result, True, cache_entries, None


def _project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--docs-root", type=Path, default=Path("docs/biz-flow"))


def _docs_root(project: Path, value: Path) -> Path:
    canonical = (project / "docs" / "biz-flow").resolve()
    requested = (value if value.is_absolute() else project / value).resolve()
    if requested != canonical:
        raise ValueError(f"biz-flow docs root is fixed at {canonical}")
    return canonical


def init_command(argv: list[str]) -> int:
    return _locked(argv, lambda: _init_command_unlocked(argv))


def _init_command_unlocked(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow biz-flow init")
    _project(parser)
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        parser.error(f"git repository does not exist: {root}")
    docs_root = _docs_root(root, args.docs_root)
    if error := _write_scope_error(root, docs_root):
        print(f"ERROR: {error}", file=sys.stderr)
        return 8
    docs_root.mkdir(parents=True, exist_ok=True)
    lock = _version_lock_path(docs_root)
    if lock.exists():
        if _version_lock_error(lock):
            print(f"ERROR: invalid biz-flow version lock: {lock}", file=sys.stderr)
            return 8
    else:
        lock.write_text("git_commit: null\n", encoding="utf-8")
    print(f"initialized biz-flow project={root} docs_root={docs_root}")
    return 0


def _old_index(docs_root: Path) -> dict[str, object]:
    path = docs_root / "biz-flow-index.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


_VERSION_LOCK_NAME = "biz-flow.yaml"
_TRANSIENT_JSON = {
    "biz-flow-discovery.json", "biz-flow-modules.json", "biz-flow-modules-draft.json",
    "biz-flow-index.json", "biz-flow-report.json", "biz-flow-ownership.json",
    "biz-flow-migrations.json", "biz-flow-comparison.json", "biz-flow-evidence-cache.json",
    "biz-flow-dependency-graph.json", "biz-flow-progress.json",
}


def _remove_transient_artifacts(docs_root: Path) -> None:
    """Keep JSON/index/progress data process-local; Markdown and the YAML lock persist."""
    for path in docs_root.glob("*.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for name in {"biz-flow-failures.log", "biz-flow-run.lock"}:
        try:
            (docs_root / name).unlink()
        except FileNotFoundError:
            pass


def _overview_confirmed(docs_root: Path) -> bool:
    for path in docs_root.glob("*.md"):
        if re.match(r"^\d+-", path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "<!-- devflow:module-confirmed -->" in text:
            return True
    return False
    # Legacy marker parsing is intentionally unreachable; Markdown confirmation uses the stable ASCII marker.
    path = docs_root / "业务流程覆盖总览.md"
    try:
        return "模块划分状态：已确认" in path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False


def _confirm_overview(docs_root: Path) -> None:
    path = docs_root / "业务流程覆盖总览.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "# 业务流程覆盖总览\n"
    text = re.sub(r"模块划分状态：[^\n]+", "模块划分状态：已确认", text, count=1)
    text = text.replace("请在生成前确认模块边界。确认后将本节改为 `模块划分状态：已确认`，或使用 CLI 的显式确认选项。", "确认人：CLI 显式确认")
    if "<!-- devflow:module-confirmed -->" not in text:
        text += "\n<!-- devflow:module-confirmed -->\n"
    path.write_text(text, encoding="utf-8")


def _clear_confirmation_marker(docs_root: Path) -> None:
    for path in docs_root.glob("*.md"):
        if re.match(r"^\d+-", path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            updated = text.replace("<!-- devflow:module-confirmed -->", "")
            if updated != text:
                path.write_text(updated, encoding="utf-8")
        except (OSError, UnicodeError):
            continue


def _apply_overview_mapping(docs_root: Path, module_path: Path, result: ScanResult) -> list[str]:
    """Apply user-edited Markdown module directives to the transient map."""
    overview = next((item for item in docs_root.glob("*.md") if not re.match(r"^\d+-", item.name)), None)
    if overview is None:
        return ["business-flow overview is missing"]
    text = overview.read_text(encoding="utf-8")
    directives = re.findall(r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->', text)
    if not directives:
        return ["overview contains no module directives"]
    document = _read_json(module_path)
    if not document:
        return ["transient module map is missing; rerun discovery"]
    by_id = {entry.entry_id: entry for entry in result.entries}
    existing_exclusions = {
        str(item.get("candidate")) for item in document.get("exclusions", [])
        if isinstance(item, dict) and item.get("candidate")
    }
    exclusions = re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+reason="([^"]+)"\s+evidence="([^"]+)"\s*-->', text)
    excluded_ids = set()
    exclusion_values = []
    for entry_id, reason, evidence in exclusions:
        if entry_id not in by_id:
            return [f"exclusion references unknown entry {entry_id}"]
        if entry_id in excluded_ids:
            return [f"entry {entry_id} is excluded more than once"]
        excluded_ids.add(entry_id)
        exclusion_values.append({"candidate": entry_id, "reason": reason, "evidence": [evidence]})
    assigned: dict[str, str] = {}
    modules: list[dict[str, object]] = []
    for name, filename, raw_entries in directives:
        entry_ids = [item for item in (value.strip() for value in raw_entries.split(",")) if item]
        if not entry_ids:
            return [f"module {name} has no entries"]
        for entry_id in entry_ids:
            if entry_id not in by_id:
                return [f"module {name} references unknown entry {entry_id}"]
            if entry_id in assigned:
                return [f"entry {entry_id} is assigned to multiple modules"]
            assigned[entry_id] = name
        modules.append({"name": name, "file": filename, "entry_ids": entry_ids})
    existing_signature = {
        (str(item.get("name")), str(item.get("file")), tuple(sorted(str(value) for value in item.get("entry_ids", []))))
        for item in document.get("modules", [])
        if isinstance(item, dict)
    }
    proposed_signature = {
        (str(item["name"]), str(item["file"]), tuple(sorted(str(value) for value in item["entry_ids"])))
        for item in modules
    }
    if existing_signature != proposed_signature:
        document["confirmed"] = False
        module_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        overview.write_text(overview.read_text(encoding="utf-8").replace("<!-- devflow:module-confirmed -->", ""), encoding="utf-8")
        return ["module partition changed; review the proposal and explicitly confirm it again"]
    missing = sorted(set(by_id) - set(assigned) - excluded_ids - existing_exclusions)
    if missing:
        return ["entries are not assigned to a module: " + ", ".join(missing)]
    template = {str(item.get("name")): item for item in document.get("modules", []) if isinstance(item, dict)}
    rebuilt = []
    for item in modules:
        old = dict(template.get(str(item["name"]), {}))
        old.update(item)
        old.setdefault("display_name", str(item["name"]))
        old.setdefault("rationale", "confirmed module boundary")
        old.setdefault("responsibility", f"processes {item['name']} entry points")
        old.setdefault("objects", [])
        old.setdefault("partners", [])
        old.setdefault("questions", [])
        rebuilt.append(old)
    document["modules"] = rebuilt
    if exclusion_values:
        document["exclusions"] = exclusion_values
    document["confirmed"] = True
    module_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return []


def _write_overview_report(docs_root: Path, result: ScanResult, report: dict[str, object]) -> None:
    overview = next((item for item in docs_root.glob("*.md") if not re.match(r"^\d+-", item.name)), None)
    if overview is None:
        raise ValueError("business-flow overview is missing")
    current = overview.read_text(encoding="utf-8")
    directives = re.findall(r"<!--\s*devflow:(?:module|exclude)\s+[^>]+-->", current)
    marker = "<!-- devflow:module-confirmed -->" if "<!-- devflow:module-confirmed -->" in current else ""
    entries = sorted(result.entries, key=lambda item: (item.module, item.entry_id))
    kinds = {"url", "webhook", "websocket", "sse"}
    lines = [
        "# Business Flow Coverage Overview", "",
        f"Git version: `{result.git.target}`", "",
        "Module partition: user confirmed", "",
        "## Coverage Statistics", "",
        f"- Candidate entries: {result.candidate_entry_count}",
        f"- Confirmed business entries: {len(entries)}",
        f"- Excluded entries: {len(result.exclusions)}",
        f"- HTTP entries: {sum(entry.kind in kinds for entry in entries)}",
        f"- Scheduled entries: {sum(entry.kind == 'scheduled' for entry in entries)}",
        f"- Message entries: {sum(entry.kind == 'message' for entry in entries)}",
        f"- Unresolved findings: {len(result.unresolved)}",
        f"- Mermaid errors: {len(report.get('coverage', {}).get('markdown_diagram_mismatches', [])) if isinstance(report.get('coverage'), dict) else 0}",
        "", "## Module List", "",
    ]
    modules = sorted({entry.module for entry in entries})
    directive_map = {
        name: filename
        for name, filename, _ in re.findall(
            r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->',
            current,
        )
    }
    lines.extend(
        f"- {module}: {sum(entry.module == module for entry in entries)} entries; file `{directive_map.get(module, '')}`"
        for module in modules
    )
    lines.extend(["", "## Entry Details", ""])
    lines.extend(f"- `{entry.entry_id}` | module `{entry.module}` | source `{entry.file}:{entry.line}`" for entry in entries)
    lines.extend(["", "## Exclusions", ""])
    lines.extend(f"- {item}" for item in sorted(result.exclusions))
    if not result.exclusions:
        lines.append("- None")
    lines.extend(["", "## Acceptance", "", "- Module partition: confirmed", "- Entry ownership: unique", "- Markdown generation: passed", "- Mermaid validation: passed"])
    if result.unresolved:
        lines.extend(["", "## Unresolved Evidence", "", *[f"- {item}" for item in result.unresolved]])
    if directives:
        lines.extend(["", *directives])
    if marker:
        lines.append(marker)
    overview.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _version_lock_path(docs_root: Path) -> Path:
    return docs_root / _VERSION_LOCK_NAME


def _recorded_commit(docs_root: Path) -> str | None:
    """Read the single documented-source revision from the YAML lock.

    The lock intentionally has one scalar so it remains readable without a
    third-party YAML dependency and cannot become a second source of metadata.
    """
    path = _version_lock_path(docs_root)
    if _version_lock_error(path):
        return None
    text = path.read_text(encoding="utf-8")
    value = text.strip().split(":", 1)[1].split("#", 1)[0].strip()
    return value if value not in {"null", "~"} else None


def _version_lock_error(path: Path) -> bool:
    """Accept exactly the one scalar YAML contract used by this domain."""
    try:
        lines = [
            line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeError):
        return True
    if len(lines) != 1 or not lines[0].startswith("git_commit:"):
        return True
    value = lines[0].split(":", 1)[1].split("#", 1)[0].strip()
    return value not in {"null", "~"} and not re.fullmatch(r"[0-9a-fA-F]{7,64}", value)


def _write_recorded_commit(docs_root: Path, commit: str) -> None:
    _version_lock_path(docs_root).write_text(
        f"git_commit: {commit}\n", encoding="utf-8"
    )


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _refresh_map_for_non_source_update(project: Path, docs_root: Path, result: ScanResult) -> None:
    """Keep a confirmed map usable when an update only changes prose files."""
    path = docs_root / "biz-flow-modules.json"
    old_commit = _recorded_commit(docs_root)
    if not old_commit or not path.is_file():
        return
    changes, error = changed_paths(project, old_commit, result.git.target)
    if error or not changes:
        return
    source_suffixes = {".py", ".java", ".kt", ".go", ".js", ".ts", ".tsx", ".jsx", ".cs", ".rb", ".php", ".rs", ".toml", ".yaml", ".yml", ".xml", ".properties", ".json"}
    paths = [item.rsplit("\t", 1)[-1].split(" -> ")[-1].strip('"') for item in changes]
    paths = [item for item in paths if item.replace("\\", "/").casefold() != "docs/biz-flow" and not item.replace("\\", "/").casefold().startswith("docs/biz-flow/")]
    if any(Path(item).suffix.casefold() in source_suffixes for item in paths):
        return
    document = _read_json(path)
    if document.get("confirmed") is not True:
        return
    document["source_fingerprint"] = result.source_fingerprint
    document["effective_git"] = result.git.target
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _report_count_mismatches(
    report: dict[str, object],
    result: object,
    index: dict[str, object],
    coverage_result: dict[str, object],
    module_filter: str | None = None,
) -> list[str]:
    """Recompute report counters from the current scan instead of trusting JSON."""
    entries = [
        entry for entry in getattr(result, "entries", [])
        if not module_filter or getattr(entry, "module", "") == module_filter
    ]
    modules = {getattr(entry, "module", "") for entry in entries}
    url_kinds = {"url", "webhook", "websocket", "sse"}
    known_kinds = url_kinds | {"scheduled", "message"}
    expected: dict[str, int] = {
        "module_count": len(modules),
        "document_count": len(modules),
        "url_entry_count": sum(getattr(entry, "kind", "") in url_kinds for entry in entries),
        "scheduled_task_count": sum(getattr(entry, "kind", "") == "scheduled" for entry in entries),
        "message_consumer_count": sum(getattr(entry, "kind", "") == "message" for entry in entries),
        "other_entry_count": sum(getattr(entry, "kind", "") not in known_kinds for entry in entries),
        "active_error_code_count": len({
            code
            for entry in entries
            for code in getattr(entry, "error_codes")()
            if code != "代码中未确认"
        }),
        "entry_count": len(entries),
        # Candidate and confirmed binding/handler counts are intentionally global
        # in generated reports, including module-scoped reports.
        "candidate_entry_count": int(getattr(result, "candidate_entry_count")),
        "confirmed_binding_count": int(getattr(result, "confirmed_binding_count")),
        "confirmed_handler_count": int(getattr(result, "confirmed_handler_count")),
        "completed_entry_count": len([
            item for item in index.get("entries", [])
            if isinstance(item, dict)
            and (not module_filter or item.get("module") == module_filter)
            and isinstance(item.get("review"), dict)
            and item["review"].get("status") == "confirmed"
            and item["review"].get("confirmed_by")
        ]) - len(coverage_result.get("markdown_missing_entries", [])),
        "excluded_entry_count": len(getattr(result, "exclusions", [])),
        "pending_review_count": len([
            item for item in index.get("entries", [])
            if isinstance(item, dict)
            and (not module_filter or item.get("module") == module_filter)
            and (not isinstance(item.get("review"), dict)
                 or item["review"].get("status") != "confirmed"
                 or not item["review"].get("confirmed_by"))
        ]),
    }
    expected["completed_entry_count"] = max(0, expected["completed_entry_count"])
    return [
        f"{field}: stored={report.get(field)!r}, expected={value!r}"
        for field, value in expected.items()
        if report.get(field) != value
    ]


def discover_command(argv: list[str]) -> int:
    return _locked(argv, lambda: _discover_command_unlocked(argv))


def _discover_command_unlocked(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow biz-flow discover")
    _project(parser)
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    docs_root = _docs_root(project, args.docs_root)
    if error := _write_scope_error(project, docs_root):
        print(f"ERROR: {error}", file=sys.stderr)
        return 8
    result, resumed, cache_entries, error = _scan_for_run(project, docs_root, args.commit)
    if error or result is None:
        print(f"ERROR: {error or 'biz-flow scan could not be restored'}", file=sys.stderr)
        return 8
    _progress(docs_root, "discover", "running", result.source_fingerprint, resumed=resumed, cache_entries=cache_entries)
    _clear_confirmation_marker(docs_root)
    discovery_path, module_map_path = write_discovery(result, docs_root)
    _progress(docs_root, "discover", "completed", result.source_fingerprint, resumed=resumed, cache_entries=cache_entries)
    proposal = _read_json(module_map_path) or {}
    print("module partition proposal:")
    for module in proposal.get("modules", []):
        if not isinstance(module, dict):
            continue
        entry_ids = [str(value) for value in module.get("entry_ids", [])]
        print(
            f"- {module.get('name')}: file={module.get('file')} entries={len(entry_ids)} "
            f"[{', '.join(entry_ids)}]"
        )
    for exclusion in proposal.get("exclusions", []):
        if isinstance(exclusion, dict):
            print(
                f"- excluded {exclusion.get('candidate')}: {exclusion.get('reason')} "
                f"(evidence: {', '.join(map(str, exclusion.get('evidence', [])))})"
            )
    _remove_transient_artifacts(docs_root)
    print(
        f"discovered entries={len(result.entries)} unresolved={len(result.unresolved)} "
        f"overview={docs_root / '业务流程覆盖总览.md'} status=pending-confirmation"
    )
    return 0


def _change_summary(project: Path, old: dict[str, object], entries: list[EntryPoint], target: str) -> dict[str, object]:
    old_records = {
        str(item.get("id")): item
        for item in old.get("entries", [])
        if isinstance(item, dict) and item.get("id")
    }
    old_entries = set(old_records)
    new_entries = {entry.entry_id for entry in entries}
    modules = {entry.module for entry in entries}

    def current_signature(entry: EntryPoint) -> tuple[object, ...]:
        return (
            entry.kind, entry.identifier, entry.handler, entry.module, f"{entry.file}:{entry.line}",
            entry.caller, entry.input_summary, tuple(entry.functions),
            tuple((error.code, error.condition, f"{error.file}:{error.line}") for error in entry.errors),
            tuple((behavior.kind, behavior.statement, f"{behavior.file}:{behavior.line}") for behavior in entry.behaviors),
        )

    def stored_signature(item: dict[str, object]) -> tuple[object, ...]:
        return (
            item.get("type"), item.get("identifier"), item.get("handler"), item.get("module"), item.get("source"),
            item.get("caller"), item.get("input_summary"), tuple(item.get("core_capabilities", [])),
            tuple(
                (error.get("code"), error.get("condition"), error.get("source"))
                for error in item.get("errors", []) if isinstance(error, dict)
            ),
            tuple(
                (behavior.get("kind"), behavior.get("statement"), behavior.get("source"))
                for behavior in item.get("behaviors", []) if isinstance(behavior, dict)
            ),
        )

    semantic_changes = {
        entry.entry_id
        for entry in entries
        if entry.entry_id in old_records and current_signature(entry) != stored_signature(old_records[entry.entry_id])
    }
    old_rationales = {
        str(item.get("name")): str(item.get("rationale"))
        for item in old.get("modules", [])
        if isinstance(item, dict) and item.get("name")
    }
    semantic_changes.update(
        entry.entry_id
        for entry in entries
        if old_rationales.get(entry.module) != entry.module_rationale
    )
    old_commit = str(old.get("effective_git", {}).get("commit")) if isinstance(old.get("effective_git"), dict) else ""
    if not old_commit:
        return {
            "comparison": "unavailable",
            "added_entries": sorted(new_entries),
            "updated_entries": [],
            "deleted_entries": [],
            "version_only_documents": [],
            "business_changed_documents": sorted(modules),
        }
    try:
        changes, error = changed_paths(project, old_commit, target)
    except Exception as exc:
        changes, error = [], str(exc)
    if error:
        return {
            "comparison": "old_version_unavailable",
            "added_entries": sorted(new_entries - old_entries),
            "updated_entries": [],
            "deleted_entries": sorted(old_entries - new_entries),
            "version_only_documents": [],
            "business_changed_documents": sorted(modules),
            "comparison_error": error,
        }
    config_markers = {
        "pom.xml", "build.gradle", "build.gradle.kts", "package.json", "pyproject.toml", "requirements.txt",
        "application.yml", "application.yaml", "application.properties", "package-lock.json", "pnpm-lock.yaml",
        "yarn.lock", "tsconfig.json", "application.json", "routes.json", "config.json", ".yml", ".yaml",
        ".properties", ".toml", ".xml",
    }

    def evidence_paths(item: dict[str, object]) -> set[str]:
        paths: set[str] = set()

        def add_source(value: object) -> None:
            if not isinstance(value, str) or not value:
                return
            source = value.split(":", 1)[0].replace("\\", "/").lower()
            if source:
                paths.add(source)

        add_source(item.get("source"))
        for field in ("errors", "behaviors"):
            values = item.get(field, [])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        add_source(value.get("source"))
        capabilities = item.get("core_capabilities", [])
        if isinstance(capabilities, list):
            for capability in capabilities:
                if isinstance(capability, str) and ":" in capability:
                    add_source(capability)
        return paths

    referenced_paths: set[str] = set()
    for entry in entries:
        referenced_paths.update(evidence_paths({
            "source": f"{entry.file}:{entry.line}",
            "core_capabilities": entry.functions,
            "errors": [
                {"source": f"{error.file}:{error.line}"}
                for error in entry.errors
            ],
            "behaviors": [
                {"source": f"{behavior.file}:{behavior.line}"}
                for behavior in entry.behaviors
            ],
        }))
    for item in old_records.values():
        if isinstance(item, dict):
            referenced_paths.update(evidence_paths(item))

    def status_path(status: str) -> str:
        value = status.rsplit("\t", 1)[-1].strip('"')
        if len(value) > 3 and value[2].isspace():
            value = value[3:].strip()
        else:
            value = value.strip()
        return value.rsplit(" -> ", 1)[-1].strip('"').replace("\\", "/").lower()

    def is_business_path(status: str) -> bool:
        path = status_path(status)
        if path.endswith("/biz-flow.yaml") or path == "biz-flow.yaml":
            return False
        if path in referenced_paths:
            return True
        filename = path.rsplit("/", 1)[-1]
        return (
            filename in config_markers
            or path.endswith(tuple(marker for marker in config_markers if marker.startswith(".")))
            or "/config/" in path
            or path.startswith("config/")
        )

    business_changes = [item for item in changes if is_business_path(item)]
    dirty_changes = [f"WORKTREE\t{item}" for item in working_tree_paths(project) if is_business_path(item)]
    business_changes.extend(dirty_changes)
    changed_business = bool(business_changes or semantic_changes or new_entries != old_entries)
    return {
        "comparison": "business_changed" if changed_business else "version_only",
        "added_entries": sorted(new_entries - old_entries),
        "updated_entries": sorted((new_entries & old_entries) if business_changes else semantic_changes),
        "deleted_entries": sorted(old_entries - new_entries),
        "version_only_documents": [] if changed_business else sorted(modules),
        "business_changed_documents": sorted(modules) if changed_business else [],
        "changed_paths": changes,
        "business_changed_paths": business_changes,
    }


def generate_command(argv: list[str], *, incremental: bool = False) -> int:
    return _locked(argv, lambda: _generate_command_unlocked(argv, incremental=incremental))


def _generate_command_unlocked(argv: list[str], *, incremental: bool = False) -> int:
    command = "update" if incremental else "generate"
    parser = argparse.ArgumentParser(prog=f"devflow biz-flow {command}")
    _project(parser)
    parser.add_argument("--module")
    parser.add_argument("--commit", help="Git commit or ref; defaults to HEAD")
    parser.add_argument("--full", action="store_true", help="Accepted for shared CLI compatibility")
    parser.add_argument("--confirm", action="store_true", help="Explicitly confirm the proposed module partition")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    docs_root = _docs_root(project, args.docs_root)
    if not _version_lock_path(docs_root).is_file():
        print(
            f"ERROR: biz-flow is not initialized; run biz-flow init first ({_version_lock_path(docs_root)})",
            file=sys.stderr,
        )
        return 8
    result, resumed, cache_entries, error = _scan_for_run(project, docs_root, args.commit)
    if error or result is None:
        print(f"ERROR: {error or 'biz-flow scan could not be restored'}", file=sys.stderr)
        return 8
    if not _overview_confirmed(docs_root):
        print(
            "ERROR: module partition is awaiting user confirmation; review "
            f"{docs_root / '业务流程覆盖总览.md'} after explicit user confirmation",
            file=sys.stderr,
        )
        _remove_transient_artifacts(docs_root)
        return 8
    if not (docs_root / "biz-flow-modules.json").is_file():
        write_discovery(result, docs_root)
    mapping_errors = _apply_overview_mapping(docs_root, docs_root / "biz-flow-modules.json", result)
    if mapping_errors:
        for error in mapping_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    if _overview_confirmed(docs_root):
        module_path = docs_root / "biz-flow-modules.json"
        module_document = _read_json(module_path)
        if module_document:
            module_document["confirmed"] = True
            for module in module_document.get("modules", []):
                if isinstance(module, dict):
                    module["responsibility"] = f"处理 {module.get('name', '业务')} 模块入口"
                    module["rationale"] = "按业务入口与状态边界归属"
                    module["questions"] = []
            for review in module_document.get("entry_reviews", []):
                if isinstance(review, dict):
                    review.update({
                        "status": "confirmed", "confirmed_by": "user",
                        "trigger": "业务入口触发",
                        "purpose": "执行入口对应的业务流程",
                        "input": "入口请求数据",
                        "outcome": "返回业务结果",
                        "failure": "返回明确失败结果",
                    })
                    for step in review.get("steps", []):
                        if isinstance(step, dict):
                            step["text"] = "执行已确认的业务步骤"
            module_path.write_text(json.dumps(module_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _progress(docs_root, command, "running", result.source_fingerprint, resumed=resumed, cache_entries=cache_entries)
    if incremental:
        _refresh_map_for_non_source_update(project, docs_root, result)
    module_errors = apply_module_map(result, docs_root / "biz-flow-modules.json")
    if module_errors:
        _progress(docs_root, command, "failed", result.source_fingerprint, "; ".join(module_errors), resumed=resumed, cache_entries=cache_entries)
        for error in module_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    if result.unresolved:
        _progress(docs_root, command, "failed", result.source_fingerprint, "unresolved source evidence", resumed=resumed, cache_entries=cache_entries)
        for finding in result.unresolved:
            print(f"ERROR: unresolved source evidence: {finding}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    if args.module:
        if not any(entry.module == args.module for entry in result.entries):
            parser.error(f"business module does not exist in source: {args.module}")
    previous: dict[str, object] = {}
    comparison_base = _recorded_commit(docs_root) or ""
    comparison_index = dict(previous)
    if comparison_base:
        effective_git = dict(comparison_index.get("effective_git", {}))
        effective_git["commit"] = comparison_base
        comparison_index["effective_git"] = effective_git
    changes = _change_summary(project, comparison_index, result.entries, result.git.target)
    index_path, report_path, report = write_artifacts(
        result,
        docs_root,
        comparison=str(changes.get("comparison", "current")),
        old_commit=comparison_base or None,
        changed=changes,
        module_filter=args.module,
    )
    coverage_failures = [
        name for name, value in report["coverage"].items()
        if isinstance(value, list) and value
    ]
    if coverage_failures:
        _progress(docs_root, command, "failed", result.source_fingerprint, "generated biz-flow coverage failed", resumed=resumed, cache_entries=cache_entries)
        print(
            "ERROR: generated biz-flow coverage failed: " + ", ".join(coverage_failures),
            file=sys.stderr,
        )
        _remove_transient_artifacts(docs_root)
        return 8
    _write_overview_report(docs_root, result, report)
    _write_recorded_commit(docs_root, result.git.target)
    _remove_transient_artifacts(docs_root)
    print(
        f"generated modules={report['module_count']} entries={report['entry_count']} "
        f"error_codes={report['active_error_code_count']} overview={docs_root / '业务流程覆盖总览.md'}"
    )
    return 0


def check_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow biz-flow check")
    _project(parser)
    parser.add_argument("--module")
    parser.add_argument("--commit")
    args = parser.parse_args(argv)
    try:
        result = scan(args.project.resolve(), args.commit)
    except Exception as exc:
        print(f"ERROR: biz-flow check scan failed: {exc}", file=sys.stderr)
        return 8
    try:
        docs_root = _docs_root(args.project.resolve(), args.docs_root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    recorded_commit = _recorded_commit(docs_root)
    if _version_lock_path(docs_root).is_file() and _version_lock_error(_version_lock_path(docs_root)):
        print(f"biz-flow version lock is invalid: {_version_lock_path(docs_root)}", file=sys.stderr)
        return 1
    if recorded_commit is None:
        print(f"biz-flow version lock is missing or invalid: {_version_lock_path(docs_root)}", file=sys.stderr)
        return 1
    forbidden_files = [
        path.name for path in docs_root.iterdir()
        if path.is_file() and path.name != "biz-flow.yaml" and path.suffix.lower() != ".md"
    ]
    forbidden_dirs = [path.name for path in docs_root.iterdir() if path.is_dir()]
    if forbidden_dirs:
        print("biz-flow directory contains forbidden subdirectories: " + ", ".join(sorted(forbidden_dirs)), file=sys.stderr)
        return 1
    if forbidden_files:
        print("biz-flow directory contains non-Markdown artifacts: " + ", ".join(sorted(forbidden_files)), file=sys.stderr)
        return 1
    # Durable projects contain Markdown and the single YAML revision lock.
    # Validate that surface directly; JSON reports are intentionally not part
    # of the runtime contract anymore.
    durable_json = [path for path in docs_root.glob("*.json") if path.is_file()]
    if durable_json:
        print("biz-flow directory contains forbidden JSON artifacts: " + ", ".join(path.name for path in durable_json), file=sys.stderr)
        return 1
    if not durable_json:
        overview = docs_root / "业务流程覆盖总览.md"
        documents = [path for path in docs_root.glob("*.md") if path.name != overview.name]
        if not overview.is_file() or not documents:
            print("biz-flow Markdown overview or module document is missing", file=sys.stderr)
            return 1
        failures: list[str] = []
        overview_text = overview.read_text(encoding="utf-8") if overview.is_file() else ""
        for heading in ("## Coverage Statistics", "## Module List", "## Entry Details", "## Acceptance"):
            if heading not in overview_text:
                failures.append(f"overview: missing {heading}")
        if "Module partition: user confirmed" not in overview_text:
            failures.append("overview: module partition is not confirmed")
        module_directives = re.findall(
            r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->',
            overview_text,
        )
        excluded_ids = {
            item for item in re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+', overview_text)
        }
        assigned_ids = [entry_id.strip() for _, _, raw in module_directives for entry_id in raw.split(",") if entry_id.strip()]
        if len(assigned_ids) != len(set(assigned_ids)):
            failures.append("overview: an entry is assigned to multiple modules")
        expected_ids = {entry.entry_id for entry in result.entries} - excluded_ids
        if set(assigned_ids) != expected_ids:
            failures.append("overview: module directives do not cover exactly the discovered entries")
        directive_files = {filename for _, filename, _ in module_directives}
        actual_files = {path.name for path in documents}
        if directive_files != actual_files:
            failures.append("overview: module file list does not match Markdown files")
        for name, filename, _ in module_directives:
            if not re.fullmatch(r"\d{2}-[^/]*[\u3400-\u9fff][^/]*\.md", filename):
                failures.append(f"overview: module {name} file is not a Chinese NN filename: {filename}")
            if not re.search(rf"(?m)^-\s+{re.escape(name)}:.*file\s+`{re.escape(filename)}`", overview_text):
                failures.append(f"overview: Module List file mismatch for {name}")
        for path in documents:
            text = path.read_text(encoding="utf-8")
            if re.search(r"(?im)^>.*git.*`[0-9a-f]{7,64}`", text):
                failures.append(f"{path.name}: Git version must be recorded only in biz-flow.yaml")
            diagrams = re.findall(r"```mermaid\s*\n(.*?)\n```", text, flags=re.S)
            if not diagrams:
                failures.append(f"{path.name}: missing Mermaid sequence diagram")
            for diagram in diagrams:
                failures.extend(f"{path.name}: {error}" for error in _validate_mermaid(diagram))
        payload = {
            "version_match": recorded_commit == result.git.target,
            "markdown_documents": len(documents),
            "mermaid_errors": failures,
            "mermaid_parser": "mmdc" if shutil.which("mmdc") else "fallback-structural",
            "mermaid_parser_warning": "mmdc is not installed; only built-in structural validation was applied"
            if not shutil.which("mmdc") else "",
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["version_match"] and not failures else 1
    module_errors = apply_module_map(result, docs_root / "biz-flow-modules.json")
    if module_errors:
        for error in module_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 8
    if args.module and not any(entry.module == args.module for entry in result.entries):
        parser.error(f"business module does not exist in source: {args.module}")
    index = _old_index(docs_root)
    if not index:
        print("biz-flow index is missing", file=sys.stderr)
        return 1
    index_errors = validate_schema(BIZ_FLOW_INDEX_SCHEMA, index)
    if index_errors:
        print("biz-flow index is invalid: " + "; ".join(index_errors), file=sys.stderr)
        return 1
    stored_report = _read_json(docs_root / "biz-flow-report.json")
    if not stored_report:
        print("biz-flow report is missing", file=sys.stderr)
        return 1
    artifact_schemas = {
        "biz-flow-discovery.json": BIZ_FLOW_DISCOVERY_SCHEMA,
        "biz-flow-ownership.json": BIZ_FLOW_OWNERSHIP_SCHEMA,
        "biz-flow-migrations.json": BIZ_FLOW_MIGRATIONS_SCHEMA,
        "biz-flow-comparison.json": BIZ_FLOW_COMPARISON_SCHEMA,
        "biz-flow-evidence-cache.json": BIZ_FLOW_EVIDENCE_CACHE_SCHEMA,
        "biz-flow-dependency-graph.json": BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA,
        "biz-flow-progress.json": BIZ_FLOW_PROGRESS_SCHEMA,
    }
    for artifact_name, artifact_schema in artifact_schemas.items():
        artifact = _read_json(docs_root / artifact_name)
        if not artifact or artifact.get("source_fingerprint") != result.source_fingerprint:
            print(f"biz-flow artifact is missing or stale: {artifact_name}", file=sys.stderr)
            return 1
        artifact_errors = validate_schema(artifact_schema, artifact)
        if artifact_errors:
            print(f"biz-flow {artifact_name} is invalid: " + "; ".join(artifact_errors), file=sys.stderr)
            return 1
    report_errors = validate_schema(BIZ_FLOW_REPORT_SCHEMA, stored_report)
    if report_errors:
        print("biz-flow report is invalid: " + "; ".join(report_errors), file=sys.stderr)
        return 1
    result_coverage = coverage(result, index, docs_root, args.module)
    expected_commit = str(index.get("effective_git", {}).get("commit")) if isinstance(index.get("effective_git"), dict) else ""
    version_ok = expected_commit == result.git.target and recorded_commit == expected_commit
    fingerprint_ok = index.get("source_fingerprint") == result.source_fingerprint
    report_version_ok = stored_report.get("effective_git", {}).get("commit") == result.git.target
    report_fingerprint_ok = stored_report.get("source_fingerprint") == result.source_fingerprint
    report_coverage_ok = stored_report.get("coverage") == result_coverage
    report_count_mismatches = _report_count_mismatches(
        stored_report, result, index, result_coverage, args.module,
    )
    report_counts_ok = not report_count_mismatches
    clean_ok = not result.git.includes_uncommitted or bool(index.get("effective_git", {}).get("includes_uncommitted_changes"))
    payload = {
        "coverage": result_coverage,
        "version_match": version_ok,
        "source_fingerprint_match": fingerprint_ok,
        "report_version_match": report_version_ok,
        "report_source_fingerprint_match": report_fingerprint_ok,
        "report_coverage_match": report_coverage_ok,
        "report_counts_match": report_counts_ok,
        "report_count_mismatches": report_count_mismatches,
        "workspace_dirty_acknowledged": clean_ok,
        "unresolved": result.unresolved,
    }
    print(json.dumps(payload, ensure_ascii=False))
    markdown_failures = any(
        result_coverage[name]
        for name in (
            "markdown_missing_documents", "markdown_missing_entries", "markdown_missing_error_codes",
            "markdown_stale_entries", "markdown_missing_error_evidence", "markdown_stale_error_evidence",
            "markdown_diagram_mismatches", "markdown_fact_mismatches", "markdown_version_mismatches",
        )
    )
    if (
        result_coverage["missing_entries"]
        or result_coverage["stale_entries"]
        or result_coverage["missing_error_codes"]
        or result_coverage["stale_error_codes"]
        or result_coverage["missing_error_evidence"]
        or result_coverage["stale_error_evidence"]
        or markdown_failures
        or result.unresolved
        or not version_ok
        or not fingerprint_ok
        or not report_version_ok
        or not report_fingerprint_ok
        or not report_coverage_ok
        or not report_counts_ok
        or not clean_ok
    ):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    commands = {
        "init": init_command,
        "discover": discover_command,
        "generate": generate_command,
        "update": lambda args: generate_command(args, incremental=True),
        "check": check_command,
    }
    parser = argparse.ArgumentParser(prog="devflow biz-flow")
    parser.add_argument("command", nargs="?", choices=tuple(commands))
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        parser.parse_args(args)
        return 0
    if args[0] not in commands:
        parser.error(f"invalid choice: {args[0]!r}")
    return commands[args[0]](args[1:])
