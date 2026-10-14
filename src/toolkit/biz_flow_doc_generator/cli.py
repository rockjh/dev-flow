"""CLI for source-backed biz-flow design documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from subprocess import SubprocessError
from collections import Counter
from pathlib import Path

from ..core.artifacts import ProjectDomainLock, require_version_file, write_json, write_version_file, state_root
from ..core.errors import DevflowError
from ..core.redaction import redact
from ..core.schema import BIZ_FLOW_SCHEMA_VERSION, BIZ_FLOW_HANDOFF_SCHEMA, BIZ_FLOW_ENTRY_FACTS_SCHEMA, validate_schema
from .discovery import scan
from .supplement import rebuild_verified
from .documents import write_discovery, write_entry_directory, readable_inventory, module_overview, registration_overview, exclusion_categories, _split_entry_ids, _display, _is_chinese_module_filename, render_module, confirmation_signature, confirmation_valid, validate_inventory, analysis_status_overview
from .evidence import ADAPTER_VERSION, digest
from .models import EntryPoint, GitInfo, ScanResult
from .orchestration import FileWriteGuard
from .host import PROTOCOL_VERSION, run_path, source_path, snapshot_sources, protected_hashes, validate_package, validate_execution
from .validation import validate_markdown_structure, validate_entry_analysis, validate_evidence_request, digest


_PROTECTED_NAMES = {"prod", "prd", "live", "production"}


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


def _locked(argv: list[str], action, *, init: bool = False, report_input_gates: bool = False):
    if any(value in {"-h", "--help"} for value in argv):
        return action()
    def fail(error):
        if report_input_gates:
            print(json.dumps({"gates": _failed_input_report(error), "errors": [str(error)]}, ensure_ascii=False))
        print(f"ERROR: {error}", file=sys.stderr)
        return 8
    try:
        project, docs_root = _command_paths(argv)
        if error := _write_scope_error(project, docs_root):
            return fail(error)
        if init and not (project / ".git").exists():
            return action()
        if not init and not docs_root.is_dir():
            return fail(f"biz-flow is not initialized: {docs_root}; run devflow biz-flow init --project {project}")
        if not init:
            require_version_file(project, "biz-flow")
        with ProjectDomainLock(project, "biz-flow"):
            try:
                return action()
            finally:
                _remove_transient_artifacts(docs_root)
    except (RuntimeError, ValueError, DevflowError) as exc:
        return fail(exc)


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


def _project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--docs-root", type=Path, default=Path("docs/biz-flow"))


def _docs_root(project: Path, value: Path) -> Path:
    project = project.resolve()
    for path in (project / "docs", project / "docs" / "biz-flow"):
        if path.is_symlink() or hasattr(path, "is_junction") and path.is_junction():
            raise ValueError(f"DOCS_PATH_UNSAFE: business asset directories cannot be aliases: {path}")
    canonical = (project / "docs" / "biz-flow").resolve()
    if not canonical.is_relative_to(project):
        raise ValueError("DOCS_PATH_UNSAFE: business assets must stay inside the project")
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
            print(f"ERROR: unsupported biz-flow version lock: {lock}; archive the old project and run init again", file=sys.stderr)
            return 8
    else:
        write_version_file(root, "biz-flow", {"source": {"git_commit": None}})
    print(f"initialized biz-flow project={root} docs_root={docs_root}")
    return 0


_VERSION_LOCK_NAME = "biz-flow-doc-generator-version.json"


def _remove_transient_artifacts(docs_root: Path) -> None:
    """Remove only transient names owned by this workflow."""
    for name in ("biz-flow-discovery.json", "biz-flow-modules.json"):
        path = docs_root / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for name in {"biz-flow-failures.log"}:
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
        if confirmation_valid(text):
            return True
    return False


def _overview_source_matches(docs_root: Path, result: ScanResult) -> bool:
    """重建瞬态映射之前核对持久清单，不能借重写绕过过期确认。"""
    path = docs_root / "业务流程覆盖总览.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    fingerprint = re.search(r'<!-- devflow:source-fingerprint value="([^"]+)" -->', text)
    return bool(fingerprint and fingerprint.group(1) == result.source_fingerprint
                and f"Git 版本：{result.git.target}\n" in text)


def _confirm_overview(docs_root: Path) -> None:
    path = docs_root / "业务流程覆盖总览.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else "# 业务流程覆盖总览\n"
    text = re.sub(r"模块划分状态：[^\n]+", "模块划分状态：已确认", text, count=1)
    text = text.replace("请在生成前确认模块边界。确认后将本节改为 `模块划分状态：已确认`，或使用 CLI 的显式确认选项。", "确认人：CLI 显式确认")
    if "<!-- devflow:module-confirmed -->" not in text:
        text += "\n<!-- devflow:module-confirmed -->\n"
    text = re.sub(r'<!-- devflow:confirmation value="[^"]+" -->\n?', "", text)
    text = text.rstrip() + f'\n<!-- devflow:confirmation value="{confirmation_signature(text)}" -->\n'
    path.write_text(text, encoding="utf-8")




def _apply_overview_mapping(
    docs_root: Path,
    module_path: Path,
    result: ScanResult,
    *,
    allow_partition_change: bool = False,
) -> list[str]:
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
    candidates = list(result.all_entries or result.entries)
    by_id = {entry.entry_id: entry for entry in candidates}
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
        if any(entry_id in _split_entry_ids(raw) for _, _, raw in directives):
            return [f"excluded entry {entry_id} must not also appear in a devflow:module directive"]
        excluded_ids.add(entry_id)
        candidate = by_id[entry_id]
        exclusion_values.append({
            "candidate": entry_id, "reason": reason, "evidence": [evidence],
            "module": candidate.module,
        })
    assigned: dict[str, str] = {}
    modules: list[dict[str, object]] = []
    for name, filename, raw_entries in directives:
        entry_ids = _split_entry_ids(raw_entries)
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
    if document.get("confirmed") is True and existing_signature != proposed_signature and not allow_partition_change:
        document["confirmed"] = False
        module_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        overview.write_text(overview.read_text(encoding="utf-8").replace("<!-- devflow:module-confirmed -->", ""), encoding="utf-8")
        return ["module partition changed; review the proposal and explicitly confirm it again"]
    missing = sorted(set(by_id) - set(assigned) - excluded_ids)
    if missing:
        return ["entries are not assigned to a module: " + ", ".join(missing)]
    template = {str(item.get("name")): item for item in document.get("modules", []) if isinstance(item, dict)}
    rebuilt = []
    for item in modules:
        old = dict(template.get(str(item["name"]), {}))
        old.update(item)
        old.setdefault("display_name", _display(str(item["name"])))
        old.setdefault("rationale", f"依据入口归属和源码调用关系确认模块边界：{item['name']}。")
        old.setdefault("responsibility", f"{old['display_name']}：处理已确认的业务入口。")
        rebuilt.append(old)
    document["modules"] = rebuilt
    document["exclusions"] = exclusion_values
    document["confirmed"] = True
    # 模块分类确认只确认入口归属，不提升行为草稿的审核状态。
    # 显式用户审核及代理审核原样保留，行为草稿由第二阶段重新分析。
    module_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return []



def _version_lock_path(docs_root: Path) -> Path:
    return docs_root / _VERSION_LOCK_NAME




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


def _read_manifest(path: Path) -> dict[str, object]:
    value = _read_json(path)
    if not value:
        raise ValueError(f"RUN_MANIFEST_UNAVAILABLE: {path}; choose a run listed by devflow biz-flow clean, or prepare a new run")
    if value.get("protocol_version") != PROTOCOL_VERSION or value.get("schema_version") != int(BIZ_FLOW_SCHEMA_VERSION):
        raise ValueError(f"UNSUPPORTED_PROTOCOL_SCHEMA: {path}; requires protocol={PROTOCOL_VERSION}, schema={BIZ_FLOW_SCHEMA_VERSION}; prepare a new run, do not rewrite stored versions")
    errors = validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, value)
    if errors:
        raise ValueError("HANDOFF_INVALID: " + "; ".join(errors))
    if value["adapter_version"] != ADAPTER_VERSION:
        raise ValueError("ADAPTER_VERSION_CHANGED: prepare a new run, do not reuse old adapter evidence")
    return value








def discover_command(argv: list[str]) -> int:
    print("progress stage=discover", file=sys.stderr)
    return _locked(argv, lambda: _discover_command_unlocked(argv))


def _conversation_overview(result: ScanResult, proposal: dict[str, object], docs_root: Path) -> str:
    """输出模块、跳过项和待复核分类；逐条证据保留在 Markdown。"""
    def clean(value: object) -> str:
        return str(redact(value)).replace("|", "\\|").replace("\n", " ")

    lines = ["业务模块总览", "", f"Git 版本：`{result.git.target}`；包含未提交变更：{'是' if result.git.includes_uncommitted else '否'}。", "", *module_overview(proposal)]
    lines.extend(["", *registration_overview(result)])
    exclusions = proposal.get("exclusions", [])
    lines.extend(["", "建议忽略项（仅排除独立入口身份，调用链仍保留）", "", "| 类别 | 数量 | 原因 |", "| --- | ---: | --- |"])
    for category, count, reason in exclusion_categories(exclusions):
        lines.append(f"| {category} | {count} | {reason} |")
    if not exclusions:
        lines.append("| 无 | 0 | 未发现建议忽略项。 |")
    categories = Counter()
    for finding in result.unresolved:
        if "unknown receiver" in finding:
            category = "调用接收者类型未解析"
        elif "multiple possible definitions" in finding:
            category = "调用声明存在多个候选"
        elif "handler for " in finding or "registered business entry" in finding:
            category = "入口注册与处理器待核对"
        elif "identifier is not statically resolvable" in finding:
            category = "触发标识待核对"
        else:
            category = "其他源码证据待核对"
        categories[category] += 1
    lines.extend(["", "待源码复核", "", "| 不确定项类别 | 数量 | 处理方式 |", "| --- | ---: | --- |"])
    for category, count in sorted(categories.items()):
        lines.append(f"| {category} | {count} | CLI 只读入口代理核对源码并提交证据；无法证明时保留未决。 |")
    if not categories:
        lines.append("| 无 | 0 | 未发现静态待复核记录。 |")
    lines.extend(["", f"待源码复核：{len(result.unresolved)} 项静态未解析记录，不需要用户逐条解答。",
                  "第一阶段只核对入口注册、业务归属和完整性，不分析业务调用链。确认分类后运行 prepare，再由宿主会话选择原生子代理或明确授权串行分析，随后 collect、check 和 verify。",
                  "完整入口、忽略项明细和逐条待复核证据保留在总览 Markdown；本次对话必须展示上述表格，不能仅回复文件链接。",
                  "", f"总览文件：{docs_root / '业务流程覆盖总览.md'}"])
    return "\n".join(lines)


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
    try:
        result = scan(project, args.commit, entry_only=True)
    except Exception as exc:
        print(f"ERROR: biz-flow entry scan failed: {exc}", file=sys.stderr)
        return 8
    discovery_path, module_map_path = write_discovery(result, docs_root)
    proposal = _read_json(module_map_path) or {}
    directory_errors = write_entry_directory(result, docs_root, proposal)
    print(_conversation_overview(result, proposal, docs_root))
    _remove_transient_artifacts(docs_root)
    print(
        f"discovered entries={len(result.entries)} unresolved={len(result.unresolved)} "
        f"overview={docs_root / '业务流程覆盖总览.md'} status=pending-confirmation stage=entries modules={len(proposal.get('modules', []))}"
    )
    for error in directory_errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 8 if directory_errors or result.unresolved else 0


def _check_entry_directory(project: Path, docs_root: Path, target: str | None) -> int:
    """第一阶段独立验收，不要求代理、时序图或已推进的版本基线。"""
    result = scan(project, target, entry_only=True)
    overview = docs_root / "业务流程覆盖总览.md"
    if not overview.is_file():
        print("ERROR: business entry overview is missing", file=sys.stderr)
        return 1
    text = overview.read_text(encoding="utf-8")
    errors = list(result.unresolved)
    for registration in result.registration_audit:
        if registration["status"] not in {"business", "excluded"} and registration not in result.coverage_gaps:
            errors.append(f"注册候选尚未完成处理：{registration['file']}:{registration['line']}")
    fingerprint = re.search(r'<!-- devflow:source-fingerprint value="([^"]+)" -->', text)
    if not fingerprint or fingerprint.group(1) != result.source_fingerprint:
        errors.append("入口目录源码指纹已失效，请重新 discover")
    directives = re.findall(r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->', text)
    candidates = {entry.entry_id: entry for entry in result.entries}
    exclusions = re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+reason="([^"]+)"\s+evidence="([^"]+)"\s*-->', text)
    if len(exclusions) != len(re.findall(r"<!--\s*devflow:exclude\b.*?-->", text)):
        errors.append("排除指令格式不完整，必须包含原因和注册证据")
    excluded = {entry_id for entry_id, _, _ in exclusions}
    if len(excluded) != len(exclusions):
        errors.append("存在重复排除记录")
    for entry_id, reason, evidence in exclusions:
        file, separator, line = evidence.rpartition(":")
        if not reason.strip() or entry_id not in candidates or not separator or not line.isdigit() or not (1 <= int(line) <= result.source_lines.get(file, 0)):
            errors.append(f"排除记录没有有效源码证据：{entry_id}")
    assigned = []
    try:
        metadata = {item["name"]: item for raw in re.findall(r"<!-- devflow:module-meta (.+?) -->", text)
                    for item in [json.loads(raw)]}
    except (ValueError, KeyError, TypeError):
        metadata = {}
        errors.append("总览模块元数据格式无效")
    modules = []
    for name, filename, raw in directives:
        ids = _split_entry_ids(raw)
        assigned.extend(ids)
        module = metadata.get(name)
        if not module or module.get("file") != filename or set(module.get("entry_ids", [])) != set(ids):
            errors.append(f"总览模块元数据与归属不一致：{name}")
        else:
            modules.append(module)
        if not ids:
            errors.append(f"模块入口清单为空：{name}")
        if not _is_chinese_module_filename(filename):
            errors.append(f"模块文件名不合法：{filename}")
            continue
        path = docs_root / filename
        if not path.is_file():
            errors.append(f"模块清单缺失：{filename}")
            continue
        module_text = path.read_text(encoding="utf-8")
        if f"<!-- biz-flow-module: {name} -->" not in module_text:
            errors.append(f"模块文件所有权与总览不一致：{filename}")
        if "<!-- devflow:entry-directory -->" in module_text:
            errors.append(f"业务范围及入口清单应集中在总览：{filename}")
    if len(modules) == len(directives):
        errors.extend(validate_inventory(result, text, {"modules": modules, "exclusions": [
            {"candidate": entry_id, "reason": reason, "evidence": [proof]}
            for entry_id, reason, proof in exclusions]}))
    if len(assigned) != len(set(assigned)):
        errors.append("业务入口存在多个模块所有者")
    if set(assigned) != set(candidates) - excluded or excluded - set(candidates):
        errors.append("业务入口目录没有完整对账")
    for entry_id in set(assigned) & set(candidates):
        entry = candidates[entry_id]
        if not entry.business_name or entry.business_name == "待确认" or not entry.source_evidence:
            errors.append(f"入口业务名称或注册证据缺失：{entry_id}")
    print(json.dumps({"stage": "entries", "git_commit": result.git.target,
                      "workspace_dirty": result.git.dirty, "module_count": len(directives),
                      "business_entry_count": len(set(assigned)), "excluded_count": len(excluded),
                      "coverage_complete": not result.coverage_gaps, "coverage_gaps": result.coverage_gaps,
                      "entry_reconciliation": not errors, "gates": _gate_report(errors),
                      "errors": errors}, ensure_ascii=False))
    return 1 if errors else 0


def _current_manifest(project):
    for path in sorted((state_root() / "biz-flow").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
            continue
        value = _read_json(path)
        if value.get("project_root") == str(project) and value.get("status") != "superseded":
            return path, _read_manifest(path)
    raise ValueError("CURRENT_RUN_MISSING: run prepare/collect")


def _mapping_signature(mapping):
    return sorted((m["name"], m["file"], tuple(sorted(m["entry_ids"]))) for m in mapping["modules"])


def _validate_mapping_surface(docs_root, manifest):
    overview = (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    directives = re.findall(r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->', overview)
    signature = sorted((name, file, tuple(sorted(_split_entry_ids(raw)))) for name, file, raw in directives)
    if signature != _mapping_signature(manifest["mapping"]) or not confirmation_valid(overview):
        raise ValueError("MAPPING_CHANGED_AFTER_PREPARE")
    exclusions = re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+reason="([^"]+)"\s+evidence="([^"]+)"\s*-->', overview)
    if sorted(exclusions) != sorted((e["candidate"], e["reason"], e["evidence"][0]) for e in manifest["mapping"]["exclusions"]):
        raise ValueError("EXCLUSIONS_CHANGED_AFTER_PREPARE")


def _canonical(project, manifest):
    ids = {t["entry_id"] for t in manifest["tasks"]}
    shallow = scan(project, manifest["source_commit"], entry_only=True)
    result = scan(project, manifest["source_commit"], entry_ids=ids)
    if shallow.source_fingerprint != result.source_fingerprint or result.source_fingerprint != manifest["source_fingerprint"]:
        raise ValueError(f"SOURCE_CHANGED_AFTER_PREPARE: SOURCE_FINGERPRINT_MISMATCH at target={manifest['source_commit']}; check committed exclude policy and .git/info/exclude, then discover/prepare again; checkout edits do not change this target")
    source_ids = {e.entry_id for e in shallow.entries}
    if not ids <= source_ids or {e.entry_id for e in result.entries} != ids:
        raise ValueError("ENTRY_SCOPE_MISMATCH")
    by_id = {e.entry_id: e for e in shallow.entries}
    for entry in result.entries:
        registered = by_id[entry.entry_id]
        if (entry.handler, entry.source_evidence) != (registered.handler, registered.source_evidence):
            raise ValueError("ENTRY_REGISTRATION_CHANGED")
    facts = rebuild_verified(result, manifest["verified_evidence"])
    if facts != manifest["entry_facts"]:
        raise ValueError("CANONICAL_FACTS_MISMATCH")
    if manifest["adapter_version"] != ADAPTER_VERSION:
        raise ValueError("ADAPTER_VERSION_CHANGED")
    return result, facts


def _validate_manifest(project, docs_root, manifest, *, gates=None):
    from .documents import _validate_mermaid
    reports = [{"gate": name, "executed": False, "passed": False, "errors": []}
               for name in ("input_contract", "entry_reconciliation", "business_copy", "markdown_structure", "mermaid_render")]
    if gates is not None:
        gates.extend(reports)
    def concluded(name, findings):
        report = next(item for item in reports if item["gate"] == name)
        report.update(executed=True, passed=not findings, errors=list(findings))
        return findings
    errors = validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, manifest)
    if errors:
        concluded("input_contract", errors)
        return errors
    try:
        require_version_file(project, "biz-flow")
        _validate_version_input(docs_root, manifest)
        if manifest["project_root"] != str(project) or manifest["docs_root"] != str(docs_root):
            raise ValueError("PROJECT_SCOPE_MISMATCH")
        if manifest["status"] not in {"collected", "verified", "accepted"}:
            raise ValueError("RUN_NOT_COLLECTED")
        errors.extend(validate_package(manifest))
        submitted = {key: manifest[key] for key in ("protocol_version", "run_id", "source_fingerprint",
            "mapping_hash", "package_hash", "mode", "parallel", "completed_child_agents", "serial_approval", "execution", "results")}
        errors.extend(validate_execution(manifest, submitted))
        if protected_hashes(project, docs_root) != manifest["protected_hashes"]:
            raise ValueError("READ_ONLY_SCOPE_CHANGED")
        _validate_mapping_surface(docs_root, manifest)
        result, facts = _canonical(project, manifest)
        inventory_errors = validate_inventory(scan(project, manifest["source_commit"], entry_only=True),
            (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8"), manifest["mapping"])
        errors.extend(inventory_errors)
        concluded("input_contract", list(errors))
        concluded("entry_reconciliation", inventory_errors)
        analyses = {}
        analysis_errors = []
        for entry_id, value in manifest["results"].items():
            if value["kind"] != "analysis":
                raise ValueError("FINAL_ANALYSIS_REQUIRED")
            analyses[entry_id] = value["analysis"]
            analysis_errors.extend(validate_entry_analysis(value["analysis"], facts[entry_id]))
            if digest(value) != manifest["result_hashes"][entry_id]:
                analysis_errors.append("RESULT_HASH_MISMATCH")
        errors.extend(concluded("business_copy", analysis_errors))
        document_errors, diagram_errors, diagrams = [], [], []
        if manifest["purpose"] == "generate":
            overview_path = docs_root / "业务流程覆盖总览.md"
            if hashlib.sha256(overview_path.read_bytes()).hexdigest() != manifest["document_hashes"].get(overview_path.name):
                document_errors.append("DOCUMENT_HASH_MISMATCH: 业务流程覆盖总览.md")
            for module in manifest["mapping"]["modules"]:
                ids = set(module["entry_ids"]) & set(facts)
                if not ids:
                    continue
                path = docs_root / module["file"]
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["document_hashes"].get(path.name):
                    document_errors.append(f"DOCUMENT_HASH_MISMATCH: {module['file']}; restore the collected document or prepare a new run")
                if path.is_file():
                    markdown = path.read_text(encoding="utf-8")
                    document_errors.extend(validate_markdown_structure(markdown,
                        {i: analyses[i] for i in ids}, {i: facts[i] for i in ids}))
                    graphs = re.findall(r"```mermaid\s*\n(.*?)```", markdown, re.S)
                    if len(graphs) != len(ids):
                        document_errors.append("MERMAID_DIAGRAM_COUNT_MISMATCH: " + module["file"])
                    for graph in graphs:
                        document_errors.extend(_validate_mermaid(graph, render=False))
                    diagrams.extend(graphs)
            errors.extend(concluded("markdown_structure", document_errors))
            if shutil.which("mmdc.cmd") or shutil.which("mmdc"):
                if not diagrams:
                    diagram_errors.append("MERMAID_DIAGRAM_MISSING")
                for graph in diagrams:
                    diagram_errors.extend(_validate_mermaid(graph))
                errors.extend(concluded("mermaid_render", diagram_errors))
            else:
                reports[-1]["warning"] = "renderer unavailable; structural validation only"
                print("WARNING: gate=mermaid_render executed=false; only structural validation", file=sys.stderr)
        else:
            reports[-2]["warning"] = "audit scope does not generate Markdown"
            reports[-1]["warning"] = "audit scope does not generate diagrams"
    except (OSError, ValueError, KeyError, RuntimeError, SubprocessError, DevflowError) as exc:
        errors.append(str(exc))
        if not reports[0]["executed"]:
            concluded("input_contract", [str(exc)])
    for report in reports:
        if not report["executed"]:
            report.setdefault("warning", "prerequisite failed; gate not executed")
    return sorted(set(errors))


def _gate_report(errors: list[str]) -> list[dict[str, object]]:
    return [{"gate": "entry_reconciliation", "executed": True,
             "passed": not errors, "errors": sorted(set(errors))}]


def _failed_input_report(error):
    return [{"gate": name, "executed": name == "input_contract", "passed": False,
             "errors": [str(error)] if name == "input_contract" else [],
             "warning": "input contract failed; dependent gate not executed"}
            for name in ("input_contract", "entry_reconciliation", "business_copy", "markdown_structure", "mermaid_render")]


def _version_hash(docs_root):
    path = docs_root / _VERSION_LOCK_NAME
    if path.is_symlink() or not path.resolve().is_relative_to(docs_root.resolve()):
        raise ValueError("VERSION_PATH_UNSAFE")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_version_input(docs_root, manifest):
    expected = manifest["accepted_version_hash"] if manifest["status"] == "accepted" else manifest["version_input_hash"]
    if _version_hash(docs_root) != expected:
        raise ValueError("VERSION_CHANGED_AFTER_PREPARE")


def _freeze_run(project, docs_root, result, mapping, *, purpose="generate", module=None, hints=(), supersedes=None):
    run_id = uuid.uuid4().hex
    facts = rebuild_verified(result, hints)
    for item in facts.values():
        errors = validate_schema(BIZ_FLOW_ENTRY_FACTS_SCHEMA, item)
        if errors:
            raise ValueError("ENTRY_FACTS_INVALID: " + "; ".join(errors))
    snapshot, snapshot_hash = snapshot_sources(project, result.git.target, result.files, run_id)
    owners = {i: m["name"] for m in mapping["modules"] for i in m["entry_ids"]}
    by_id = {e.entry_id: e for e in result.entries}
    tasks = []
    for i, entry_id in enumerate(sorted(facts)):
        destination = state_root() / "biz-flow" / run_id / "results" / f"{i}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        task = {"task_id": f"entry:{entry_id}", "entry_id": entry_id, "module_id": owners[entry_id],
            "registration_evidence": by_id[entry_id].source_evidence,
            "reachable_analysis": ["calls", "branches", "persistence_actions", "effects", "outcomes", "flow"],
            "unresolved_questions": facts[entry_id]["gaps"], "source_commit": result.git.target,
            "source_snapshot": str(snapshot), "snapshot_hash": snapshot_hash, "input_hash": digest(facts[entry_id]),
            "result_path": str(destination), "permissions": {"read_only_source": True,
            "write_scope": str(destination), "enforcement": "coordinator_scope_check"},
            "result_schema": "biz-flow.entry-result", "status": "pending"}
        task["task_hash"] = digest(task)
        tasks.append(task)
    if not tasks:
        raise ValueError("TASK_COVERAGE_INVALID")
    mapping_hash = digest(mapping)
    source_status = {"target_commit": result.git.target, "head_commit": result.git.head,
        "workspace_dirty": result.git.dirty, "includes_uncommitted_changes": False}
    package = {"protocol_version": PROTOCOL_VERSION, "domain": "biz-flow", "run_id": run_id,
        "project_root": str(project), "source_commit": result.git.target,
        "source_status": source_status,
        "source_fingerprint": result.source_fingerprint, "mapping_hash": mapping_hash,
        "adapter_version": ADAPTER_VERSION, "verified_evidence": list(hints),
        "tasks": tasks, "entry_facts": facts, "result_schema": "biz-flow.entry-result",
        "submission_schema": "biz-flow.submission", "version_input_hash": _version_hash(docs_root)}
    manifest = {"protocol_version": PROTOCOL_VERSION, "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "run_id": run_id, "project_root": str(project), "docs_root": str(docs_root),
        "source_commit": result.git.target, "source_fingerprint": result.source_fingerprint,
        "source_status": source_status,
        "mapping_hash": mapping_hash, "mapping": mapping, "package_hash": digest(package),
        "adapter_version": ADAPTER_VERSION, "verified_evidence": list(hints), "supersedes_run_id": supersedes,
        "protected_hashes": protected_hashes(project, docs_root),
        "version_input_hash": package["version_input_hash"],
        "document_inputs": {name: hashlib.sha256(content).hexdigest() for name, content in _markdown_snapshot(docs_root).items()},
        "purpose": purpose, "module_filter": module, "mode": None, "parallel": False, "degraded": False,
        "status": "prepared", "host_capability": "unknown", "tasks": tasks, "completed_child_agents": 0,
        "entry_facts": facts, "comparison": _source_comparison(project, result, facts, module=module),
        "serial_approval": None, "execution": {"receipts": [], "active_observations": []},
        "results": {}, "verification_runs": 0, "errors": []}
    errors = validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, manifest)
    if errors:
        raise ValueError("HANDOFF_INVALID: " + "; ".join(errors))
    path = run_path(run_id)
    package_path = path.with_suffix(".tasks.json")
    write_json(package_path, package)
    write_json(path, manifest)
    return path, manifest


def _prepared_output(path, manifest):
    reusable = set(manifest["results"])
    for rejected in manifest.get("rejected_submissions", []):
        for entry_id, response in rejected.get("results", {}).items():
            if entry_id in manifest["entry_facts"] and response.get("kind") == "analysis" and not validate_entry_analysis(response["analysis"], manifest["entry_facts"][entry_id]):
                if rejected.get("mode") == "serial" or any(r.get("status") == "success" and r.get("result_hash") == digest(response)
                        and r.get("task_id") == "entry:" + entry_id for r in rejected.get("execution", {}).get("receipts", [])):
                    reusable.add(entry_id)
    return {"run_id": manifest["run_id"], "status": manifest["status"], "manifest": str(path),
        "task_package": str(path.with_suffix(".tasks.json")), "package_hash": manifest["package_hash"],
        "host_capability": "unknown", "supersedes_run_id": manifest["supersedes_run_id"],
        "source_status": manifest["source_status"], "comparison": manifest["comparison"],
        "behavior_gaps": sum(len(f["gaps"]) for f in manifest["entry_facts"].values()),
        "reusable_entry_ids": sorted(reusable), "pending_entry_ids": sorted(set(manifest["entry_facts"]) - reusable)}


def _source_comparison(project, result, facts, *, module=None):
    baseline = require_version_file(project, "biz-flow")["source"]["git_commit"]
    current = set(facts)
    if baseline is None:
        return {"baseline_commit": None, "available": False, "reason": "no accepted baseline",
            "added_entry_ids": sorted(current), "changed_entry_ids": [], "deleted_entry_ids": [],
            "reuse": "none; every selected task requires new execution"}
    try:
        old = None
        for path in sorted((state_root() / "biz-flow").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
                continue
            value = _read_json(path)
            if value.get("protocol_version") != PROTOCOL_VERSION or value.get("schema_version") != int(BIZ_FLOW_SCHEMA_VERSION):
                continue
            if value.get("project_root") != str(project) or value.get("status") != "accepted" or value.get("source_commit") != baseline:
                continue
            errors = validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, value)
            if errors or value["adapter_version"] != ADAPTER_VERSION:
                raise ValueError("accepted baseline evidence is invalid or uses a different adapter")
            prior_ids = {i for m in value["mapping"]["modules"] if module is None or m["name"] == module for i in m["entry_ids"]}
            if not prior_ids or not prior_ids <= set(value["entry_facts"]):
                continue
            previous = scan(project, baseline, entry_ids=prior_ids)
            old = rebuild_verified(previous, [r for r in value["verified_evidence"] if r["entry_id"] in prior_ids])
            break
        if old is None:
            raise ValueError("accepted baseline scope and verified evidence unavailable")
        def semantic(value):
            value = {k: v for k,v in value.items() if k not in {"source_commit", "source_fingerprint"}}
            value["sources"] = [{k:v for k,v in s.items() if k not in {"line", "end_line"}} for s in value["sources"]]
            return digest(value)
        return {"baseline_commit": baseline, "available": True, "reason": "source-rebuilt comparison; no receipt reuse",
            "added_entry_ids": sorted(current - set(old)), "changed_entry_ids": sorted(i for i in current & set(old) if semantic(facts[i]) != semantic(old[i])),
            "deleted_entry_ids": sorted(set(old) - current), "reuse": "none; every selected task requires new execution"}
    except (OSError, ValueError, KeyError, RuntimeError, SubprocessError) as exc:
        return {"baseline_commit": baseline, "available": False, "reason": redact(str(exc)),
            "added_entry_ids": [], "changed_entry_ids": sorted(current), "deleted_entry_ids": [],
            "reuse": "none; full selected scope requires new execution"}


def _delivery_summary(manifest):
    accepted = set()
    docs = Path(manifest["docs_root"])
    for path in (state_root() / "biz-flow").glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
            continue
        other = _read_json(path)
        if (other.get("status") != "accepted" or other.get("project_root") != manifest["project_root"]
                or other.get("docs_root") != manifest["docs_root"]
                or other.get("source_commit") != manifest["source_commit"] or other.get("mapping_hash") != manifest["mapping_hash"]
                or other.get("adapter_version") != ADAPTER_VERSION or validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, other)):
            continue
        for module in manifest["mapping"]["modules"]:
            target = docs / module["file"]
            if (set(module["entry_ids"]) <= set(other.get("results", {})) and target.is_file()
                    and other.get("document_hashes", {}).get(target.name) == hashlib.sha256(target.read_bytes()).hexdigest()):
                accepted.add(module["name"])
    required = {module["name"] for module in manifest["mapping"]["modules"]}
    blocked = [{"module": module["name"], "reason": "not accepted for this target and mapping",
                "findings": [gap for i in module["entry_ids"] for gap in manifest["entry_facts"].get(i, {}).get("gaps", [])]}
               for module in manifest["mapping"]["modules"] if module["name"] not in accepted]
    return {"overall_status": "success" if accepted == required else "partial",
            "accepted_modules": sorted(accepted), "blocked_modules": blocked}


def prepare_command(argv):
    print("progress stage=prepare", file=sys.stderr)
    return _locked(argv, lambda: _prepare(argv))


def _prepare(argv):
    parser = argparse.ArgumentParser(prog="devflow biz-flow prepare")
    _project(parser)
    parser.add_argument("--module")
    parser.add_argument("--commit")
    parser.add_argument("--purpose", choices=("generate", "audit"), default="generate")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--resume", metavar="RUN_ID")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    docs_root = _docs_root(project, args.docs_root)
    try:
        if args.resume:
            path = run_path(args.resume)
            manifest = _read_manifest(path)
            if manifest.get("project_root") != str(project) or manifest.get("docs_root") != str(docs_root):
                raise ValueError("PROJECT_SCOPE_MISMATCH")
            if args.module and args.module != manifest["module_filter"] or args.commit and args.commit != manifest["source_commit"]:
                raise ValueError("RESUME_SCOPE_MISMATCH: reuse the prepared target and module")
            if manifest["status"] not in {"prepared", "collected", "verified"}:
                raise ValueError("RUN_NOT_RESUMABLE: prepare a new run")
            errors = validate_package(manifest)
            if errors:
                raise ValueError("; ".join(errors))
            _validate_mapping_surface(docs_root, manifest)
            _validate_version_input(docs_root, manifest)
            print(json.dumps(_prepared_output(path, manifest), ensure_ascii=False))
            return 0
        shallow = scan(project, args.commit, entry_only=True)
        if shallow.unresolved and not args.module:
            raise ValueError("ENTRY_CLASSIFICATION_UNRESOLVED: " + "; ".join(shallow.unresolved))
        if not _overview_source_matches(docs_root, shallow):
            raise ValueError("ENTRY_DIRECTORY_STALE: rerun discover")
        if not args.confirm and not _overview_confirmed(docs_root):
            raise ValueError("CLASSIFICATION_CONFIRMATION_REQUIRED: mapping or snapshot confirmation is missing/stale; review the overview and rerun prepare --confirm once")
        mapping_path = docs_root / "biz-flow-modules.json"
        write_discovery(shallow, docs_root)
        _confirm_overview(docs_root)
        errors = _apply_overview_mapping(docs_root, mapping_path, shallow)
        if errors:
            raise ValueError("; ".join(errors))
        mapping = _read_json(mapping_path)
        ids = {i for m in mapping["modules"] if not args.module or m["name"] == args.module for i in m["entry_ids"]}
        if args.module and not ids:
            raise ValueError(f"MODULE_NOT_FOUND: {args.module}; choose a module name from the overview")
        selected_entries = [entry for entry in shallow.entries if entry.entry_id in ids]
        selected_errors = [finding for finding in shallow.unresolved if any(
            entry.entry_id in finding or finding.startswith(f"{entry.file}:{entry.line}:") for entry in selected_entries)]
        if selected_errors:
            raise ValueError("ENTRY_CLASSIFICATION_UNRESOLVED: " + "; ".join(selected_errors))
        result = scan(project, shallow.git.target, entry_ids=ids)
        if result.source_fingerprint != shallow.source_fingerprint or {e.entry_id for e in result.entries} != ids:
            raise ValueError("TWO_STAGE_SCOPE_MISMATCH")
        path, manifest = _freeze_run(project, docs_root, result, mapping, purpose=args.purpose, module=args.module)
        print(json.dumps(_prepared_output(path, manifest), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, SubprocessError) as exc:
        print(f"ERROR: prepare failed: {exc}", file=sys.stderr)
        return 8


def _verify_requests(manifest, submitted, result):
    """Only registered, source-rebuildable hints can alter the next run."""
    tasks = {t["entry_id"]: t for t in manifest["tasks"]}
    verified = list(manifest["verified_evidence"])
    for entry_id, response in submitted["results"].items():
        facts = manifest["entry_facts"][entry_id]
        if response["kind"] == "analysis":
            errors = validate_entry_analysis(response["analysis"], facts)
            if errors:
                raise ValueError("ENTRY_RESULT_INVALID: " + "; ".join(errors))
            continue
        for request in response["evidence_requests"]:
            errors = validate_evidence_request(request, manifest, tasks[entry_id], facts)
            if errors:
                raise ValueError("EVIDENCE_REQUEST_INVALID: " + "; ".join(errors))
            verified.append(request)
    rebuilt = rebuild_verified(result, verified)
    if rebuilt == manifest["entry_facts"]:
        raise ValueError("EVIDENCE_REQUEST_NO_PROGRESS")
    return verified


def collect_command(argv):
    print("progress stage=collect", file=sys.stderr)
    return _locked(argv, lambda: _collect(argv))


def _collect(argv):
    parser = argparse.ArgumentParser(prog="devflow biz-flow collect")
    _project(parser)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args(argv)
    project, path, submitted, manifest = args.project.resolve(), None, None, None
    try:
        path = run_path(args.run_id)
        manifest = _read_manifest(path)
        if manifest["status"] not in {"prepared", "collected", "verified", "accepted"}:
            raise ValueError("RUN_NOT_COLLECTABLE")
        docs_root = _docs_root(project, args.docs_root)
        if manifest["project_root"] != str(project) or manifest["docs_root"] != str(docs_root):
            raise ValueError("PROJECT_SCOPE_MISMATCH")
        submitted = json.loads(args.results.read_text(encoding="utf-8"))
        errors = validate_execution(manifest, submitted) + validate_package(manifest)
        if errors:
            raise ValueError("; ".join(errors))
        if submitted != redact(submitted):
            raise ValueError("RESULT_NOT_REDACTED")
        if protected_hashes(project, docs_root) != manifest["protected_hashes"]:
            raise ValueError("READ_ONLY_SCOPE_CHANGED")
        _validate_version_input(docs_root, manifest)
        _validate_mapping_surface(docs_root, manifest)
        result, facts = _canonical(project, manifest)
        submission_hash = digest(submitted)
        if manifest.get("submission_hash"):
            if submission_hash != manifest["submission_hash"]:
                raise ValueError("COLLECT_CONFLICT_NEW_RUN_REQUIRED")
            errors = _validate_manifest(project, docs_root, manifest)
            if errors:
                raise ValueError("; ".join(errors))
            print(json.dumps({"run_id": args.run_id, "status": manifest["status"], "manifest": str(path), "idempotent": True}))
            return 0
        if {n: hashlib.sha256(b).hexdigest() for n, b in _markdown_snapshot(docs_root).items()} != manifest["document_inputs"]:
            raise ValueError("HUMAN_DOCUMENT_CHANGED")
        if any(v["kind"] == "evidence_request" for v in submitted["results"].values()):
            verified = _verify_requests(manifest, submitted, result)
            new_path, replacement = _freeze_run(project, docs_root, result, manifest["mapping"],
                purpose=manifest["purpose"], module=manifest["module_filter"], hints=verified, supersedes=args.run_id)
            manifest.update(status="superseded", superseded_by_run_id=replacement["run_id"],
                evidence_submission=submitted, verified_output_hashes={i: digest(f) for i, f in replacement["entry_facts"].items()})
            write_json(path, manifest)
            print(json.dumps(_prepared_output(new_path, replacement), ensure_ascii=False))
            return 0
        analyses = {}
        for entry_id, value in submitted["results"].items():
            errors = validate_entry_analysis(value["analysis"], facts[entry_id])
            if errors:
                raise ValueError(f"ENTRY_RESULT_INVALID {entry_id}: " + "; ".join(errors))
            analyses[entry_id] = value["analysis"]
        modules, owners = manifest["mapping"]["modules"], {}
        for module in modules:
            for entry_id in module["entry_ids"]:
                owners[entry_id] = module
        for entry in result.entries:
            entry.module = owners[entry.entry_id]["name"]
        contents = {}
        if manifest["purpose"] == "generate":
            for module in modules:
                entries = [e for e in result.entries if e.entry_id in module["entry_ids"]]
                if entries:
                    contents[module["file"]] = render_module(module["name"], entries, result.git, result,
                        facts=facts, analyses=analyses, module_meta=module)
            # Validate all assets before invoking the single writer.
            for module in modules:
                ids = set(module["entry_ids"]) & set(analyses)
                if ids:
                    errors = validate_markdown_structure(contents[module["file"]], {i: analyses[i] for i in ids}, {i: facts[i] for i in ids})
                    if errors:
                        raise ValueError("; ".join(errors))
            before = _markdown_snapshot(docs_root)
            try:
                overview_path = docs_root / "业务流程覆盖总览.md"
                overview = overview_path.read_text(encoding="utf-8")
                contents[overview_path.name] = re.sub(r"(?s)<!-- devflow:analysis-status -->.*?<!-- /devflow:analysis-status -->",
                    lambda _: analysis_status_overview(result, manifest["mapping"], docs_root, completed=contents), overview)
                for name, content in contents.items():
                    FileWriteGuard("coordinator", name, str(docs_root)).assert_allowed("coordinator", name)
                    temporary = docs_root / (name + ".tmp")
                    temporary.write_text(content, encoding="utf-8")
                    temporary.replace(docs_root / name)
            except Exception:
                _restore_markdown_snapshot(docs_root, before)
                raise
        manifest.update({key: submitted[key] for key in ("mode", "parallel", "completed_child_agents", "serial_approval", "execution", "results")})
        manifest.update(status="collected", degraded=submitted["mode"] == "serial", submission_hash=submission_hash,
            comparison=_source_comparison(project, result, facts, module=manifest["module_filter"]),
            result_hashes={i: digest(v) for i, v in submitted["results"].items()},
            document_hashes={n: hashlib.sha256((docs_root / n).read_bytes()).hexdigest() for n in contents},
            host_capability="available" if submitted["mode"] == "native" else "session_reported_unavailable",
            trust_boundary="host-attested" if submitted["mode"] == "native" else "coordinator-attested",
            validation_scope="source-rebuilt-facts-and-canonical-assets")
        write_json(path, manifest)
        print(json.dumps({"run_id": args.run_id, "status": "collected", "manifest": str(path)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, SubprocessError) as exc:
        if manifest is not None and path and path.is_file():
            failed = _read_json(path)
            if failed.get("protocol_version") == PROTOCOL_VERSION and failed.get("schema_version") == int(BIZ_FLOW_SCHEMA_VERSION):
                failed.setdefault("collection_errors", []).append(redact(str(exc)))
                if isinstance(submitted, dict):
                    failed.setdefault("rejected_submissions", []).append(redact(submitted))
                write_json(path, failed)
        print(f"ERROR: collect failed: {exc}", file=sys.stderr)
        return 8


def check_command(argv):
    print("progress stage=check", file=sys.stderr)
    parser = argparse.ArgumentParser(prog="devflow biz-flow check")
    _project(parser)
    parser.add_argument("--stage", choices=("entries", "flows"), default="flows")
    parser.add_argument("--commit")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    project, docs = args.project.resolve(), _docs_root(args.project.resolve(), args.docs_root)
    try:
        require_version_file(project, "biz-flow")
        if args.stage == "entries":
            return _check_entry_directory(project, docs, args.commit)
        path, manifest = (run_path(args.run_id), _read_manifest(run_path(args.run_id))) if args.run_id else _current_manifest(project)
        gates = []
        errors = _validate_manifest(project, docs, manifest, gates=gates)
        report_path = path.with_suffix(".check.json")
        write_json(report_path, {"run_id": manifest["run_id"], "gates": gates, "errors": errors})
        print(json.dumps({"run_id": manifest["run_id"], "manifest": str(path),
                          "report": str(report_path), "gates": gates, "errors": errors}, ensure_ascii=False))
        return 1 if errors else 0
    except (ValueError, OSError, KeyError, DevflowError) as exc:
        print(json.dumps({"gates": _failed_input_report(exc), "errors": [str(exc)]}, ensure_ascii=False))
        print(f"ERROR: check failed: {exc}", file=sys.stderr)
        return 1


def verify_command(argv):
    print("progress stage=verify", file=sys.stderr)
    return _locked(argv, lambda: _verify(argv), report_input_gates=True)


def _verify(argv):
    parser = argparse.ArgumentParser(prog="devflow biz-flow verify")
    _project(parser)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    project, docs = args.project.resolve(), _docs_root(args.project.resolve(), args.docs_root)
    gates = []
    try:
        path, manifest = (run_path(args.run_id), _read_manifest(run_path(args.run_id))) if args.run_id else _current_manifest(project)
        errors = _validate_manifest(project, docs, manifest, gates=gates)
        report_path = path.with_suffix(".verify.json")
        write_json(report_path, {"run_id": manifest["run_id"], "gates": gates, "errors": errors})
        if errors:
            if (manifest.get("status") == "verified" and manifest.get("project_root") == str(project)
                    and manifest.get("docs_root") == str(docs) and not validate_schema(BIZ_FLOW_HANDOFF_SCHEMA, manifest)):
                manifest.update(status="collected", verification_runs=0)
                manifest.pop("verify_digest", None)
                write_json(path, manifest)
            print(json.dumps({"run_id": manifest["run_id"], "manifest": str(path),
                              "report": str(report_path), "gates": gates, "errors": errors}, ensure_ascii=False))
            print("ERROR: verify failed: " + "; ".join(errors), file=sys.stderr)
            return 1
        value = digest({"facts": manifest["entry_facts"], "results": manifest["results"], "documents": manifest["document_hashes"]})
        manifest["verification_runs"] = manifest["verification_runs"] + 1 if manifest.get("verify_digest") == value else 1
        manifest.update(status="accepted" if manifest["status"] == "accepted" else "verified", verify_digest=value)
        write_json(path, manifest)
        print(json.dumps({"run_id": manifest["run_id"], "verification_runs": manifest["verification_runs"],
            "canonical_facts_verified": True, "stable": manifest["verification_runs"] >= 2,
            "gates": gates, "report": str(report_path), "manifest": str(path)}))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"gates": gates or _failed_input_report(exc), "errors": [str(exc)]}, ensure_ascii=False))
        print(f"ERROR: verify failed: {exc}", file=sys.stderr)
        return 1


def accept_command(argv):
    print("progress stage=accept", file=sys.stderr)
    return _locked(argv, lambda: _accept(argv))


def _accept(argv):
    parser = argparse.ArgumentParser(prog="devflow biz-flow accept")
    _project(parser)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        path = run_path(args.run_id)
        manifest = _read_manifest(path)
        if manifest.get("status") != "verified" or manifest["verification_runs"] < 2:
            raise ValueError("TWO_STABLE_VERIFY_RUNS_REQUIRED")
        docs = _docs_root(args.project.resolve(), args.docs_root)
        errors = _validate_manifest(args.project.resolve(), docs, manifest)
        if errors:
            raise ValueError("; ".join(errors))
        source_root = source_path(args.run_id)
        # Cleanup must succeed before changing the accepted source baseline.
        if source_root.is_dir():
            files = [p.relative_to(source_root).as_posix() for p in source_root.rglob("*") if p.is_file()]
            try:
                shutil.rmtree(source_root)
            except OSError:
                # Restore a partially removed snapshot from its fixed commit for retry.
                snapshot_sources(args.project.resolve(), manifest["source_commit"], files, args.run_id)
                raise
        # A module-filtered run cannot advance the whole project's baseline.
        covered = set(manifest["entry_facts"])
        if (manifest["purpose"] == "generate" and manifest["module_filter"] is None
                and covered == {i for m in manifest["mapping"]["modules"] for i in m["entry_ids"]}):
            _write_recorded_commit(docs, manifest["source_commit"])
            version = _version_lock_path(docs)
            manifest["protected_hashes"][version.relative_to(args.project.resolve()).as_posix()] = hashlib.sha256(version.read_bytes()).hexdigest()
        manifest["status"] = "accepted"
        manifest["accepted_version_hash"] = _version_hash(docs)
        manifest["snapshot_cleaned"] = True
        write_json(path, manifest)
        print(json.dumps({"run_id": args.run_id, "status": "accepted", "manifest": str(path),
                          **_delivery_summary(manifest)}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: accept failed: {exc}", file=sys.stderr)
        return 8


def clean_command(argv):
    """Bounded cleanup for old process artifacts in the shared state area."""
    parser = argparse.ArgumentParser(prog="devflow biz-flow clean")
    parser.add_argument("--run-id")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.run_id and args.all:
        parser.error("provide at most one of --run-id or --all")
    root = (state_root() / "biz-flow").resolve()
    if not root.is_dir():
        print(json.dumps({"removed": 0, "state_root": str(root)}, ensure_ascii=False))
        return 0
    if not args.run_id and not args.all:
        runs = [{"run_id": path.stem, "status": _read_json(path).get("status", "unknown"),
                 "manifest": str(path)} for path in sorted(root.glob("*.json"))
                if re.fullmatch(r"[0-9a-f]{32}", path.stem)]
        print(json.dumps({"runs": runs, "state_root": str(root)}, ensure_ascii=False))
        return 0
    if args.run_id:
        run_path(args.run_id)  # Validate before computing any delete targets.
    targets = ([p for p in root.iterdir() if p.name in {"scan-cache", "facts-cache", "render-cache"}
                or re.fullmatch(r"[0-9a-f]{32}(?:\.[\w-]+)?\.json|[0-9a-f]{32}", p.name)]
               if args.all else [root / args.run_id, root / (args.run_id + ".json"), *root.glob(args.run_id + ".*.json")])
    removed = 0
    for target in targets:
        if target.is_symlink() or target.resolve().parent != root:
            print("ERROR: invalid run id", file=sys.stderr)
            return 8
        if target.is_dir():
            shutil.rmtree(target)
            removed += 1
        elif target.is_file():
            target.unlink()
            removed += 1
    print(json.dumps({"removed": removed, "state_root": str(root)}, ensure_ascii=False))
    return 0


def main(argv=None):
    commands = {"init": init_command, "discover": discover_command, "prepare": prepare_command,
        "collect": collect_command, "check": check_command, "verify": verify_command, "accept": accept_command,
        "clean": clean_command}
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="devflow biz-flow")
    parser.add_argument("command", nargs="?", choices=tuple(commands))
    if not args or args[0] in {"-h", "--help"}:
        parser.parse_args(args)
        return 0
    if args[0] not in commands:
        parser.error(f"unsupported command: {args[0]}")
    return commands[args[0]](args[1:])
