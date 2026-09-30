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

from ..core.artifacts import require_version_file, write_json, write_version_file, state_root
from ..core.errors import DevflowError
from .discovery import scan
from .documents import apply_module_map, write_artifacts, write_discovery, _validate_mermaid
from .git import changed_paths, working_tree_paths
from .models import BehaviorEvidence, EntryPoint, ErrorEvidence, GitInfo, ScanResult
from .orchestration import create_run_manifest, fail_run, finish_run, write_module
from .validation import validate_run, validate_markdown_structure, parse_diagram_ids, parse_matrix_ids


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


def _locked(argv: list[str], action, *, init: bool = False):
    if any(value in {"-h", "--help"} for value in argv):
        return action()
    try:
        project, docs_root = _command_paths(argv)
        if error := _write_scope_error(project, docs_root):
            print(f"ERROR: {error}", file=sys.stderr)
            return 8
        if init and not (project / ".git").exists():
            return action()
        if not init and not docs_root.is_dir():
            print(f"ERROR: biz-flow is not initialized: {docs_root}", file=sys.stderr)
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


def _markdown_snapshot(docs_root: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in docs_root.glob("*.md")
        if path.is_file()
    }


def _restore_markdown_snapshot(docs_root: Path, snapshot: dict[str, bytes]) -> None:
    for path in docs_root.glob("*.md"):
        if path.name not in snapshot:
            path.unlink(missing_ok=True)
    for name, content in snapshot.items():
        temporary = docs_root / f".{name}.restore.tmp"
        temporary.write_bytes(content)
        temporary.replace(docs_root / name)


def _safe_write_artifacts(result: ScanResult, docs_root: Path, snapshot: dict[str, bytes], **kwargs):
    try:
        return write_artifacts(result, docs_root, **kwargs)
    except Exception:
        _restore_markdown_snapshot(docs_root, snapshot)
        _remove_transient_artifacts(docs_root)
        raise


def _scan_for_run(
    project: Path,
    docs_root: Path,
    target: str | None,
) -> tuple[ScanResult | None, bool, int, str | None]:
    try:
        return scan(project, target), False, 0, None
    except Exception as exc:
        return None, False, 0, f"biz-flow scan failed: {exc}"


def _progress(*_args: object, **_kwargs: object) -> None:
    """Retained as a no-op for callers; progress is process-local state."""
    return None


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
    return _locked(argv, lambda: _init_command_unlocked(argv), init=True)


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
        write_version_file(root, "biz-flow", {"source": {"git_commit": None}})
    print(f"initialized biz-flow project={root} docs_root={docs_root}")
    return 0


_VERSION_LOCK_NAME = "biz-flow-doc-generator-version.json"


def _remove_transient_artifacts(docs_root: Path) -> None:
    """Keep JSON/index/progress data process-local; Markdown and the version file persist."""
    for path in docs_root.glob("*.json"):
        if path.name == _VERSION_LOCK_NAME:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for path in docs_root.glob("*.tmp"):
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
    exclude_markers = re.findall(r"<!--\s*devflow:exclude\b.*?-->", text)
    if len(exclusions) != len(exclude_markers):
        return ["invalid devflow:exclude syntax; use id=\"...\" reason=\"...\" evidence=\"file:line\""]
    excluded_ids = set()
    exclusion_values = []
    for entry_id, reason, evidence in exclusions:
        if entry_id not in by_id:
            return [f"exclusion references unknown entry {entry_id}"]
        if entry_id in excluded_ids:
            return [f"entry {entry_id} is excluded more than once"]
        source_file, separator, source_line = evidence.rpartition(":")
        if not separator or not source_file or not source_line.isdigit() or not (1 <= int(source_line) <= result.source_lines.get(source_file, 0)):
            return [f"exclusion {entry_id} evidence must be a valid scanned file:line: {evidence}"]
        if any(entry_id in [value.strip() for value in raw.split(",")] for _, _, raw in directives):
            return [f"excluded entry {entry_id} must not also appear in a devflow:module directive"]
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
    # A discovery-created map is only a proposal. The first explicit overview
    # confirmation is allowed to establish its user-owned partition; later
    # changes to an already confirmed partition must be reviewed again.
    if document.get("confirmed") is True and existing_signature != proposed_signature:
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
    # The overview confirmation marker is the explicit partition confirmation.
    # Promote only complete evidence-derived drafts; preserve any user-authored
    # status, text, and steps byte-for-byte.
    for review in document.get("entry_reviews", []):
        if not isinstance(review, dict) or review.get("status") != "draft":
            continue
        fields = ("trigger", "purpose", "input", "outcome", "failure")
        if all(str(review.get(field, "")).strip() for field in fields) and review.get("steps"):
            review["status"] = "confirmed"
            review["confirmed_by"] = "overview-confirmation"
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
        "# 业务流程覆盖总览", "",
        f"Git 版本：`{result.git.target}`", "",
        "Module partition: user confirmed（模块划分：用户已确认）", "",
        "## Coverage Statistics（覆盖统计）", "",
        f"- Candidate entries（候选入口）：{result.candidate_entry_count}",
        f"- Confirmed business entries（已确认业务入口）：{len(entries)}",
        f"- Excluded entries（已排除入口）：{len(result.exclusions)}",
        f"- HTTP entries（HTTP 入口）：{sum(entry.kind in kinds for entry in entries)}",
        f"- Scheduled entries（定时任务入口）：{sum(entry.kind == 'scheduled' for entry in entries)}",
        f"- Message entries（消息入口）：{sum(entry.kind == 'message' for entry in entries)}",
        f"- Unresolved findings（未解决发现）：{len(result.unresolved)}",
        f"- Mermaid errors（Mermaid 错误）：{len(report.get('coverage', {}).get('markdown_diagram_mismatches', [])) if isinstance(report.get('coverage'), dict) else 0}",
        "", "## Module List（模块列表）", "",
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
        f"- {module}: {sum(entry.module == module for entry in entries)} entries; file `{directive_map.get(module, '')}`（{sum(entry.module == module for entry in entries)} 个入口；文件）"
        for module in modules
    )
    lines.extend(["", "## Entry Details", "", "| 入口 ID | 业务描述 | 入口 | 归属 | 入口类型 | 源码位置 |", "| --- | --- | --- | --- | --- | --- |"])
    for entry in entries:
        title = entry.title if entry.title and not entry.title_unresolved else "title_unresolved"
        lines.append(
            f"| `{entry.entry_id}` | {title} | {entry.identifier} | `{directive_map.get(entry.module, '')}` | {entry.kind} | `{entry.file}:{entry.line}` |"
        )
    lines.extend(["", "## Exclusions（排除项）", ""])
    lines.extend(f"- {item}" for item in sorted(result.exclusions))
    if not result.exclusions:
        lines.append("- None（无）")
    lines.extend(["", "## Acceptance（验收结果）", "", "- Module partition: confirmed（模块划分：已确认）", "- Entry ownership: unique（入口归属：唯一）", "- Markdown generation: passed（Markdown 生成：通过）", "- Mermaid validation: passed（Mermaid 校验：通过）"])
    if result.unresolved:
        lines.extend(["", "## 未解决证据", "", *[f"- {item}" for item in result.unresolved]])
    if directives:
        lines.extend(["", *directives])
    if marker:
        lines.append(marker)
    rendered = "\n".join(lines).rstrip() + "\n"
    temporary = overview.with_name(overview.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(overview)


def _version_lock_path(docs_root: Path) -> Path:
    return docs_root / _VERSION_LOCK_NAME


def _recorded_commit(docs_root: Path) -> str | None:
    """Read the documented-source revision from the skill version file."""
    path = _version_lock_path(docs_root)
    if _version_lock_error(path):
        return None
    try:
        value = require_version_file(docs_root.parent.parent, "biz-flow", path=path)
    except DevflowError:
        return None
    source = value.get("source")
    commit = source.get("git_commit") if isinstance(source, dict) else None
    return commit if isinstance(commit, str) else None


def _version_lock_error(path: Path) -> bool:
    try:
        value = require_version_file(path.parent.parent.parent, "biz-flow", path=path)
    except DevflowError:
        return True
    source = value.get("source")
    if not isinstance(source, dict) or "git_commit" not in source:
        return True
    commit = source.get("git_commit")
    return commit is not None and (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit))


def _write_recorded_commit(docs_root: Path, commit: str) -> None:
    write_version_file(docs_root.parent.parent, "biz-flow", {"source": {"git_commit": commit}})


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _manifest_matches(path: Path, source_fingerprint: str, project: Path, docs_root: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and value.get("source_fingerprint") == source_fingerprint
        and Path(str(value.get("project_root", ""))).resolve() == project.resolve()
        and Path(str(value.get("docs_root", ""))).resolve() == docs_root.resolve()
    )


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
    _clear_confirmation_marker(docs_root)
    discovery_path, module_map_path = write_discovery(result, docs_root)
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
        if path.endswith("/" + _VERSION_LOCK_NAME) or path == _VERSION_LOCK_NAME:
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
    parser.add_argument("--confirm", action="store_true", help="Explicitly confirm the proposed module partition")
    parser.add_argument("--allow-degraded", action="store_true", help="Explicitly allow serial execution without child agents")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    docs_root = _docs_root(project, args.docs_root)
    if not _version_lock_path(docs_root).is_file():
        _remove_transient_artifacts(docs_root)
        print(
            f"ERROR: biz-flow is not initialized; run biz-flow init first ({_version_lock_path(docs_root)})",
            file=sys.stderr,
        )
        return 8
    result, resumed, cache_entries, error = _scan_for_run(project, docs_root, args.commit)
    if error or result is None:
        _remove_transient_artifacts(docs_root)
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
    if incremental:
        _refresh_map_for_non_source_update(project, docs_root, result)
    module_errors = apply_module_map(result, docs_root / "biz-flow-modules.json")
    if module_errors:
        for error in module_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    if args.module and not any(entry.module == args.module for entry in result.entries):
        parser.error(f"business module does not exist in source: {args.module}")
    try:
        mapping = _read_json(docs_root / "biz-flow-modules.json")
        if args.module:
            mapping = {
                **mapping,
                "modules": [item for item in mapping.get("modules", [])
                            if isinstance(item, dict) and str(item.get("name")) == args.module],
            }
        manifest = create_run_manifest(
            result, mapping, allow_degraded=args.allow_degraded,
            project_root=project, docs_root=docs_root, module_filter=args.module,
        )
    except Exception as exc:
        _remove_transient_artifacts(docs_root)
        print(f"ERROR: delegation/evidence setup failed: {exc}", file=sys.stderr)
        return 8
    manifest_path = state_root() / "biz-flow" / f"{manifest['run_id']}.json"
    write_json(manifest_path, manifest)
    if manifest.get("errors") or manifest.get("status") != "running":
        code = "DELEGATION_UNAVAILABLE" if any("DELEGATION_UNAVAILABLE" in str(error) for error in manifest.get("errors", [])) else "AGENT_EXECUTION_FAILED"
        print(f"ERROR: {code}; run_manifest={manifest_path}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    analyses = manifest.get("entry_analyses", {})
    for entry in result.entries:
        analysis = analyses.get(entry.entry_id, {}) if isinstance(analyses, dict) else {}
        if isinstance(analysis, dict):
            entry.agent_branches = list(analysis.get("branches", []))
            entry.agent_persistence = list(analysis.get("persistence_actions", []))
    if result.unresolved:
        fail_run(manifest, [f"SOURCE_UNRESOLVED: {finding}" for finding in result.unresolved])
        write_json(manifest_path, manifest)
        for finding in result.unresolved:
            print(f"ERROR: unresolved source evidence: {finding}", file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    previous: dict[str, object] = {}
    comparison_base = _recorded_commit(docs_root) or ""
    comparison_index = dict(previous)
    if comparison_base:
        effective_git = dict(comparison_index.get("effective_git", {}))
        effective_git["commit"] = comparison_base
        comparison_index["effective_git"] = effective_git
    changes = _change_summary(project, comparison_index, result.entries, result.git.target)
    markdown_snapshot = _markdown_snapshot(docs_root)
    def write_module_artifact(module: str, path: Path, content: str) -> None:
        write_module(manifest, module, path, content)

    try:
        index_path, report_path, report = _safe_write_artifacts(
            result, docs_root, markdown_snapshot,
            comparison=str(changes.get("comparison", "current")),
            old_commit=comparison_base or None, changed=changes,
            module_filter=args.module, module_writer=write_module_artifact,
            module_contents={module: value["markdown"] for module, value in manifest["module_results"].items()},
        )
    except Exception as exc:
        fail_run(manifest, [str(exc)])
        write_json(manifest_path, manifest)
        print(f"ERROR: module write failed; run_manifest={manifest_path}", file=sys.stderr)
        return 8
    markdown_agent_errors: list[str] = []
    for module, spec in manifest.get("modules", {}).items():
        module_path = docs_root / str(spec.get("file", ""))
        if module_path.is_file():
            module_analyses = {
                entry_id: manifest.get("entry_analyses", {}).get(entry_id, {})
                for entry_id in spec.get("entry_ids", [])
                if entry_id in manifest.get("entry_analyses", {})
            }
            markdown_agent_errors.extend(
                f"{module}: {error}"
                for error in validate_markdown_structure(module_path.read_text(encoding="utf-8"), module_analyses)
            )
    if markdown_agent_errors:
        fail_run(manifest, markdown_agent_errors)
        write_json(manifest_path, manifest)
        _restore_markdown_snapshot(docs_root, markdown_snapshot)
        print("ERROR: Markdown evidence coverage failed: " + "; ".join(markdown_agent_errors), file=sys.stderr)
        _remove_transient_artifacts(docs_root)
        return 8
    coverage_failures = [
        name for name, value in report["coverage"].items()
        if isinstance(value, list) and value
    ]
    if coverage_failures:
        fail_run(manifest, coverage_failures)
        write_json(manifest_path, manifest)
        _restore_markdown_snapshot(docs_root, markdown_snapshot)
        print(
            "ERROR: generated biz-flow coverage failed: " + ", ".join(coverage_failures),
            file=sys.stderr,
        )
        _remove_transient_artifacts(docs_root)
        return 8
    expected_branches = {
        branch["branch_id"]
        for inventory in manifest.get("inventories", {}).values()
        for branch in inventory.get("source_branch_inventory", [])
        if branch.get("business_relevant") is True and branch.get("reachability") != "unreachable"
    }
    expected_persistence = {
        action["persistence_id"]
        for inventory in manifest.get("inventories", {}).values()
        for action in inventory.get("persistence_inventory", [])
    }
    actual_branches: set[str] = set()
    actual_persistence: set[str] = set()
    for spec in manifest.get("modules", {}).values():
        module_path = docs_root / str(spec.get("file", ""))
        if module_path.is_file():
            markdown = module_path.read_text(encoding="utf-8")
            actual_branches |= parse_diagram_ids(markdown, "branch") & parse_matrix_ids(markdown, "branch")
            actual_persistence |= parse_diagram_ids(markdown, "persistence") & parse_matrix_ids(markdown, "persistence")
    branch_coverage = (len(actual_branches & expected_branches) / len(expected_branches)) if expected_branches else 1.0
    persistence_coverage = (len(actual_persistence & expected_persistence) / len(expected_persistence)) if expected_persistence else 1.0
    critical_unresolved = sum(
        1 for inventory in manifest.get("inventories", {}).values()
        for item in inventory.get("unresolved", [])
        if item.get("critical", True)
    )
    report.update({
        "module_tasks": sum(task.get("role") == "module" for task in manifest["tasks"]),
        "entry_tasks": sum(task.get("role") == "entry" for task in manifest["tasks"]),
        "parallel": bool(manifest.get("parallel")),
        "degraded": bool(manifest.get("degraded")),
        "branch_coverage": branch_coverage,
        "persistence_coverage": persistence_coverage,
        "critical_unresolved": critical_unresolved,
        "stable": True,
        "run_manifest": str(manifest_path),
    })
    manifest["report"] = {
        key: report[key]
        for key in (
            "module_count", "entry_count", "module_tasks", "entry_tasks", "parallel", "degraded",
            "branch_coverage", "persistence_coverage", "critical_unresolved", "stable",
        )
    }
    write_json(report_path, report)
    finish_run(manifest)
    manifest["status"] = "success"
    manifest["errors"] = validate_run(manifest)
    if manifest["errors"]:
        fail_run(manifest, manifest["errors"])
        write_json(manifest_path, manifest)
        print(f"ERROR: run validation failed: {manifest['errors']}; run_manifest={manifest_path}", file=sys.stderr)
        _restore_markdown_snapshot(docs_root, markdown_snapshot)
        _remove_transient_artifacts(docs_root)
        return 8
    write_json(manifest_path, manifest)
    _write_overview_report(docs_root, result, report)
    _write_recorded_commit(docs_root, result.git.target)
    _remove_transient_artifacts(docs_root)
    print(
        f"generated modules={report['module_count']} entries={report['entry_count']} "
        f"module_tasks={report['module_tasks']} entry_tasks={report['entry_tasks']} "
        f"parallel={report['parallel']} degraded={report['degraded']} "
        f"branch_coverage={report['branch_coverage']} persistence_coverage={report['persistence_coverage']} "
        f"critical_unresolved={report['critical_unresolved']} stable={report['stable']} "
        f"error_codes={report['active_error_code_count']} run_manifest={manifest_path} "
        f"overview={docs_root / '业务流程覆盖总览.md'}"
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
    manifest_candidates = sorted((state_root() / "biz-flow").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    run_manifest_path = next((path for path in manifest_candidates if path.is_file() and _manifest_matches(path, result.source_fingerprint, args.project.resolve(), docs_root)), None)
    if run_manifest_path is None:
        print("biz-flow execution manifest is missing for the current source fingerprint", file=sys.stderr)
        return 1
    try:
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(f"biz-flow execution manifest is unreadable: {run_manifest_path}", file=sys.stderr)
        return 1
    manifest_errors = validate_run(run_manifest)
    if manifest_errors:
        print("biz-flow execution manifest failed: " + "; ".join(manifest_errors), file=sys.stderr)
        return 1
    # Re-run the evidence gate against the durable Markdown.  A successful
    # generation manifest records what was written; check must reject edits
    # made after that run instead of trusting the old in-memory validation.
    markdown_errors: list[str] = []
    for module, spec in run_manifest.get("modules", {}).items():
        filename = str(spec.get("file", ""))
        path = docs_root / filename
        if not path.is_file():
            markdown_errors.append(f"Markdown overview or module document is missing: {module}")
            continue
        expected_hash = run_manifest.get("document_hashes", {}).get(filename)
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_hash != actual_hash:
            markdown_errors.append(f"{module}: Markdown hash differs from execution manifest")
        analyses = {
            entry_id: run_manifest.get("entry_analyses", {}).get(entry_id, {})
            for entry_id in spec.get("entry_ids", [])
        }
        markdown_errors.extend(
            f"{module}: {error}"
            for error in validate_markdown_structure(path.read_text(encoding="utf-8"), analyses)
        )
    if markdown_errors:
        print("biz-flow Markdown evidence gate failed: " + "; ".join(markdown_errors), file=sys.stderr)
        return 1
    if _version_lock_path(docs_root).is_file() and _version_lock_error(_version_lock_path(docs_root)):
        print(f"biz-flow version lock is invalid: {_version_lock_path(docs_root)}", file=sys.stderr)
        return 1
    if recorded_commit is None:
        print(f"biz-flow version lock is missing or invalid: {_version_lock_path(docs_root)}", file=sys.stderr)
        return 1
    forbidden_files = [
        path.name for path in docs_root.iterdir()
        if path.is_file()
        and path.name != _VERSION_LOCK_NAME
        and path.suffix.lower() != ".md"
    ]
    forbidden_dirs = [path.name for path in docs_root.iterdir() if path.is_dir()]
    if forbidden_dirs:
        print("biz-flow directory contains forbidden subdirectories: " + ", ".join(sorted(forbidden_dirs)), file=sys.stderr)
        return 1
    if forbidden_files:
        print("biz-flow directory contains non-Markdown artifacts: " + ", ".join(sorted(forbidden_files)), file=sys.stderr)
        return 1
    # Durable projects contain Markdown and the single JSON version file.
    # Validate that surface directly; JSON reports are intentionally not part
    # of the runtime contract anymore.
    durable_json = [
        path for path in docs_root.glob("*.json")
        if path.is_file() and path.name != _VERSION_LOCK_NAME
    ]
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
        table_ids = re.findall(r"^\|\s*`([^`]+)`\s*\|", overview_text, flags=re.M)
        if set(table_ids) != expected_ids or len(table_ids) != len(set(table_ids)):
            failures.append("overview: entry table does not cover each discovered entry exactly once")
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
                failures.append(f"{path.name}: Git version must be recorded only in {_VERSION_LOCK_NAME}")
            diagrams = re.findall(r"```mermaid\s*\n(.*?)\n```", text, flags=re.S)
            if not diagrams:
                failures.append(f"{path.name}: missing Mermaid sequence diagram")
            for diagram in diagrams:
                failures.extend(f"{path.name}: {error}" for error in _validate_mermaid(diagram))
            entry_markers = list(re.finditer(r"<!--\s*biz-flow-entry:\s*([^>]+?)\s*-->", text))
            for marker_index, marker in enumerate(entry_markers):
                entry_id = marker.group(1).strip()
                section_end = entry_markers[marker_index + 1].start() if marker_index + 1 < len(entry_markers) else len(text)
                section = text[marker.start():section_end]
                if "title_unresolved" in section[:220]:
                    failures.append(f"{path.name}:{entry_id}: title_unresolved requires human title")
                paragraphs = [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]
                if any(len(value) > 50 for value in paragraphs):
                    failures.append(f"{path.name}:{entry_id}: business description point exceeds 50 characters")
                if any(marker in section for marker in ("pending business steps", "confirmed business steps", "执行已确认的业务步骤", "待补充业务步骤")):
                    failures.append(f"{path.name}:{entry_id}: placeholder business text is forbidden")
        mermaid_renderer = shutil.which("mmdc.cmd") or shutil.which("mmdc")
        payload = {
            "version_match": recorded_commit == result.git.target,
            "markdown_documents": len(documents),
            "mermaid_errors": failures,
            "mermaid_parser": "mmdc" if mermaid_renderer else "fallback-structural",
            "mermaid_parser_warning": "mmdc is not installed; only built-in structural validation was applied"
            if not mermaid_renderer else "",
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["version_match"] and not failures else 1
def verify_command(argv: list[str]) -> int:
    """Repeat the durable gate and prove stable Markdown output."""
    parser = argparse.ArgumentParser(prog="devflow biz-flow verify")
    _project(parser)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    docs_root = _docs_root(project, args.docs_root)

    def snapshot() -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in docs_root.glob("*.md") if path.is_file()
        }

    before = snapshot()
    first = check_command(argv)
    middle = snapshot()
    second = check_command(argv)
    after = snapshot()
    if first or second:
        print("ERROR: repeated biz-flow check did not pass", file=sys.stderr)
        return 1
    if before != middle or middle != after:
        print("ERROR: repeated biz-flow check changed durable Markdown", file=sys.stderr)
        return 1
    if any(path.name.endswith(".tmp") for path in docs_root.iterdir()):
        print("ERROR: temporary generation artifacts remain in docs/biz-flow", file=sys.stderr)
        return 1
    print(json.dumps({"stable": True, "markdown_documents": len(after), "checks": 2}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    commands = {
        "init": init_command,
        "discover": discover_command,
        "generate": generate_command,
        "update": lambda args: generate_command(args, incremental=True),
        "check": check_command,
        "verify": verify_command,
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
