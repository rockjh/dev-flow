"""Entry directory and canonical-fact Markdown rendering."""
from __future__ import annotations
import re
import shutil
import subprocess
import tempfile
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from ..core.artifacts import write_json, state_root
from ..core.redaction import redact
from ..core.sequence import Activations, TECHNICAL_ROLES, participant_declaration, validate_sequence
from ..core.schema import BIZ_FLOW_MODULE_MAP_SCHEMA, BIZ_FLOW_SCHEMA_VERSION, validate_schema
from .models import EntryPoint, ScanResult
from .evidence import FACT_ARRAYS, digest, trim_cache


# Renderer work is keyed by diagram content.  A process-local cache keeps
# repeated check/verify passes from invoking Mermaid for the same graph.
_MERMAID_CACHE: dict[str, tuple[str, ...]] = {}


def confirmation_signature(markdown):
    fingerprint = re.search(r'<!-- devflow:source-fingerprint value="([^"]+)" -->', markdown)
    commit = re.search(r"^Git 版本：([0-9a-f]+)$", markdown, re.M)
    modules = sorted((name, file, tuple(sorted(_split_entry_ids(ids)))) for name, file, ids in re.findall(
        r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->', markdown))
    exclusions = sorted(re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+reason="([^"]+)"\s+evidence="([^"]+)"\s*-->', markdown))
    return digest([commit[1] if commit else None, fingerprint[1] if fingerprint else None, modules, exclusions])


def confirmation_valid(markdown):
    binding = re.search(r'<!-- devflow:confirmation value="([^"]+)" -->', markdown)
    return bool(binding and binding[1] == confirmation_signature(markdown)
                and "<!-- devflow:module-confirmed -->" in markdown)


def write_discovery(scan: ScanResult, docs_root: Path) -> tuple[Path, Path]:
    """Shallow registration inventory; never promotes behavior completion."""
    docs_root.mkdir(parents=True, exist_ok=True)
    candidates = list(scan.all_entries or scan.entries)
    overview = docs_root / "业务流程覆盖总览.md"
    reviewed = overview.read_text(encoding="utf-8") if overview.exists() else ""
    metadata = {}
    for raw in re.findall(r"<!-- devflow:module-meta (.+?) -->", reviewed):
        try:
            item = json.loads(raw)
            metadata[item["name"]] = item
        except (ValueError, KeyError, TypeError):
            raise ValueError("MODULE_METADATA_INVALID: repair the overview module-meta block")
    descriptions = {}
    for row in reviewed.splitlines():
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if row.startswith("| ") and len(cells) == 3 and cells[-1].isdigit():
            descriptions[cells[0]] = cells[1].replace("\\|", "|")
    owners, filenames = {}, {}
    for name, filename, raw in re.findall(r'<!--\s*devflow:module\s+name="([^"]+)"\s+file="([^"]+)"\s+entries="([^"]*)"\s*-->', reviewed):
        filenames[name] = filename
        owners.update({entry_id: name for entry_id in _split_entry_ids(raw)})
    exclusions = {}
    ids = {e.entry_id for e in candidates}
    for entry_id, reason, proof in re.findall(r'<!--\s*devflow:exclude\s+id="([^"]+)"\s+reason="([^"]+)"\s+evidence="([^"]+)"\s*-->', reviewed):
        if entry_id in ids:
            exclusions[entry_id] = {"candidate": entry_id, "reason": reason, "evidence": [proof]}
    for entry in candidates:
        reason = entry.exclusion_reason or _non_business_reason(entry)
        if reason and entry.entry_id not in exclusions:
            exclusions[entry.entry_id] = {"candidate": entry.entry_id, "reason": reason,
                "evidence": [f"{entry.file}:{entry.line}"], "module": entry.module}
    groups = {}
    for entry in candidates:
        if entry.entry_id not in exclusions:
            groups.setdefault(owners.get(entry.entry_id, entry.module), []).append(entry)
    modules = []
    renames = []
    for i, (name, entries) in enumerate(sorted(groups.items())):
        title = _module_function_summary(name, entries)
        filename = filenames.get(name, _chinese_module_filename(i, title))
        prior = metadata.get(name, next((m for m in metadata.values() if set(m["entry_ids"]) == {e.entry_id for e in entries}), {}))
        if prior.get("file") and prior["file"] != filename:
            renames.append((prior["file"], filename))
        modules.append({**prior, "name": name, "display_name": prior.get("display_name", _display(name)), "file": filename,
            "entry_ids": sorted(e.entry_id for e in entries),
            "rationale": prior.get("rationale", f"依据入口注册和业务归属确认：{name}。"),
            "responsibility": descriptions.get(Path(filename).stem, prior.get("responsibility", _module_business_description(entries, candidates)))})
    fingerprint = re.search(r'<!-- devflow:source-fingerprint value="([^"]+)" -->', reviewed)
    confirmed = bool(fingerprint and fingerprint[1] == scan.source_fingerprint
                     and f"Git 版本：{scan.git.target}\n" in reviewed and confirmation_valid(reviewed))
    mapping = {"schema_version": int(BIZ_FLOW_SCHEMA_VERSION), "source_fingerprint": scan.source_fingerprint,
        "effective_git": scan.git.target, "confirmed": confirmed, "modules": modules,
        "exclusions": list(exclusions.values())}
    errors = validate_schema(BIZ_FLOW_MODULE_MAP_SCHEMA, mapping)
    if errors:
        raise ValueError("MODULE_MAP_INVALID: " + "; ".join(errors))
    for previous, current in renames:
        if not all(_is_chinese_module_filename(name) for name in (previous, current)):
            raise ValueError("MODULE_FILENAME_INVALID: use a numbered module filename inside docs/biz-flow")
        old, new = docs_root / previous, docs_root / current
        if old.is_symlink() or new.is_symlink():
            raise ValueError("MODULE_FILENAME_UNSAFE: module paths cannot be aliases")
        if old.is_file():
            if new.exists():
                raise ValueError(f"MODULE_FILENAME_CONFLICT: {previous} -> {current}; preserve one reviewed file before retrying")
            old.replace(new)
    source = {"schema_version": int(BIZ_FLOW_SCHEMA_VERSION), "source_fingerprint": scan.source_fingerprint,
        "source_commit": scan.git.target, "entries": [{"entry_id": e.entry_id, "source_evidence": e.source_evidence}
        for e in candidates], "unresolved": scan.unresolved}
    discovery_path = write_json(docs_root / "biz-flow-discovery.json", source)
    module_path = write_json(docs_root / "biz-flow-modules.json", mapping)
    directives = [f'<!-- devflow:module name="{m["name"]}" file="{m["file"]}" entries="{",".join(m["entry_ids"])}" -->' for m in modules]
    directives += [f'<!-- devflow:exclude id="{e["candidate"]}" reason="{e["reason"]}" evidence="{e["evidence"][0]}" -->' for e in exclusions.values()]
    directives += ["<!-- devflow:module-meta " + json.dumps(m, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c").replace(">", "\\u003e") + " -->" for m in modules]
    lines = ["# 业务流程覆盖总览", "", f"Git 版本：{scan.git.target}", "",
        f"工作区状态：{'包含未提交变更，分析使用提交快照' if scan.git.dirty else '指定提交快照'}", "",
        f'<!-- devflow:source-fingerprint value="{scan.source_fingerprint}" -->',
        '<!-- devflow:ownership-policy value="business-domain" -->', "",
        f"模块划分状态：{'已确认' if confirmed else '待用户确认'}", "", *readable_inventory(scan, mapping),
        "", analysis_status_overview(scan, mapping, docs_root),
        "", "<!-- devflow:machine-map -->", *directives]
    if confirmed:
        lines.append("<!-- devflow:module-confirmed -->")
        lines.append(f'<!-- devflow:confirmation value="{confirmation_signature(chr(10).join(lines))}" -->')
    overview.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return discovery_path, module_path


def fact_index(facts):
    return {f["fact_id"]: f for array in FACT_ARRAYS for f in facts[array]}


def render_entry(facts, analysis, *, validate_diagram=True):
    annotations = {a["target_id"]: a for a in analysis["annotations"]}
    items = fact_index(facts)
    label = lambda identifier: _mermaid_text(annotations[identifier]["text"])
    participants = facts["participants"]
    aliases = {p["identity"]: f"A{i}" for i, p in enumerate(participants)}
    fallback = next((aliases[p["identity"]] for p in participants if p["role"] == "service"), "A0")
    caller = next((aliases[p["identity"]] for p in participants if p["role"] == "caller"), fallback)
    lines = [f'<!-- biz-flow-entry: {facts["entry_id"]} -->',
        f'## {facts["registration"]["business_name"]}', "",
        f'入口描述：{analysis["review"]["trigger"]["text"]}', "",
        f'业务功能：{analysis["review"]["purpose"]["text"]}', "", "```mermaid", "sequenceDiagram", "autonumber"]
    for p in participants:
        name = label(p["participant_id"])
        if p["role"] == "storage":
            name = _mermaid_text(p["identity"]) + "（" + name + "）"
        lines.append(participant_declaration(aliases[p["identity"]], name, p["role"]))
    activations = Activations(lines, {aliases[p["identity"]] for p in participants if p["role"] in TECHNICAL_ROLES})
    previous_phase = None
    contexts = {}
    senders = {}
    local_calls = set()
    control_indices = {}
    control_stack = []
    activation_scopes = {}
    arm_names = {"false": "条件不成立", "true": "条件成立", "rejected": "任务被拒绝", "accepted": "任务已提交",
                 "left_true": "前置条件成立", "left_false": "前置条件不成立"}
    for position, step in enumerate(facts["flow"]):
        fact = items[step["fact_id"]]
        fid, kind = fact["fact_id"], step["kind"]
        lines.append(f'%% devflow:step id="{step["step_id"]}" fact="{fid}" phase="{step["phase"]}"')
        if step["phase"] != previous_phase:
            if previous_phase is not None:
                activations.boundary({"phase"})
                activations.close("phase")
            lines.append(f'Note over {fallback}: {"后台执行，入口未观察完成" if step["phase"] == "background" else "入口处理"}')
            activations.open("phase", fallback)
            previous_phase = step["phase"]
        message = label(fid)
        active = {identifier for identifier, _ in control_stack} | {guard for _, wrapped in control_stack for guard in wrapped}
        guards = [identifier for identifier in step["controls"] if identifier in items
                  and items[identifier] in facts["branches"] and identifier not in active]
        if kind in {"control_else", "control_end"}:
            guards = []
        for identifier in guards:
            index = step["controls"].index(identifier)
            arm = step["controls"][index + 1] if index + 1 < len(step["controls"]) else ""
            lines.append(f'opt {label(identifier)}，{arm_names.get(arm, "所列控制条件")}')
        guard_activations = set(activations.active)
        if kind == "control_start":
            control = "loop" if fact["type"] in {"for_statement", "enhanced_for_statement", "while_statement", "do_statement", "synchronous_iteration", "For", "While"} else "opt" if fact["type"] in {"finally", "synchronized_statement"} else "alt"
            if fact["type"] == "short_circuit":
                message += "，" + arm_names[fact["details"]["arms"][0]]
            lines.append(f'{control} {message}')
            control_indices[fid] = 0
            control_stack.append((fid, guards))
            activation_scopes[fid] = set(activations.active)
        elif kind == "control_else":
            activations.boundary(activation_scopes[fid])
            control_indices[fid] += 1
            arm = step["arm"] or fact["details"]["arms"][min(control_indices[fid], len(fact["details"]["arms"]) - 1)]
            arm_label = arm_names.get(arm, "无论前序结果均执行" if arm.startswith("finally") else "捕获所列异常" if arm.startswith("catch") else "其他条件")
            lines.append(f'else {arm_label}')
            lines.append(f'%% devflow:arm {arm}')
        elif kind == "control_end":
            activations.boundary(activation_scopes.pop(fid))
            lines.append("end")
            opened, wrapped = control_stack.pop()
            if opened != fid:
                raise ValueError("FLOW_CONTROL_NESTING_INVALID")
            lines.extend("end" for _ in wrapped)
        elif kind == "call":
            target = aliases.get(fact["details"].get("target_owner", fact["details"]["receiver_type"]))
            parent = aliases.get(fact["details"].get("sender_type"), contexts.get(fact["details"]["parent_context"], fallback))
            contexts[fact["context_id"]] = target or parent
            senders[fact["context_id"]] = parent
            if target:
                lines.append(f'{parent}->>{target}: {message}')
                activations.open(fact["context_id"], target)
            else:
                local_calls.add(fact["context_id"])
                lines.append(f'Note over {parent}: {message}')
        elif kind == "return":
            target = contexts.get(fact["context_id"], fallback)
            parent = senders.get(fact["context_id"], fallback)
            ending = "结束，异常按控制分支传播" if fact["details"].get("may_throw") else "返回"
            lines.append(f'Note over {parent}: {message}{ending}' if fact["context_id"] in local_calls else f'{target}-->>{parent}: {message}{ending}')
            activations.close(fact["context_id"])
        elif kind == "persistence":
            target = aliases[fact["details"]["resource_name"]]
            lines.append(f'%% devflow:persistence id="{fid}"')
            lines.append(f'{contexts.get(fact["context_id"], fallback)}->>{target}: {message}')
            activations.open(fid, target)
            activations.close(fid)
        elif kind == "outcome":
            owner = contexts.get(fact["context_id"], fallback)
            if fact["type"] in {"entry_response", "normal_completion"} and step["phase"] == "entry":
                lines.append(f'{owner}-->>{caller}: {message}')
            else:
                lines.append(f'Note over {owner}: {message}')
        else:
            lines.append(f'Note over {contexts.get(fact["context_id"], fallback)}: {message}')
        if kind in {"control_start", "control_else"}:
            following = facts["flow"][position + 1] if position + 1 < len(facts["flow"]) else None
            if following and following["fact_id"] == fid and following["kind"] in {"control_else", "control_end"}:
                # Empty arms have no actor bounds in Mermaid and can produce NaN coordinates.
                lines.append(f'Note over {contexts.get(fact["context_id"], fallback)}: 此条件内无业务动作')
        if kind != "control_start":
            if guards:
                activations.boundary(guard_activations)
            lines.extend("end" for _ in guards)
    activations.boundary({"phase"})
    activations.close("phase")
    lines += ["```", "", "| 业务行为与结果 | 执行阶段 | 适用条件 |", "| --- | --- | --- |"]
    for array in FACT_ARRAYS:
        for fact in facts[array]:
            conditions = [label(c) if c in annotations else arm_names.get(c, "已提交的后台任务" if c == "submitted" else "异常处理范围" if c.startswith("catch") else "最终清理范围" if c.startswith("finally") else "所列控制条件") for c in fact["conditions"]]
            lines.append(f'<!-- devflow:matrix fact="{fact["fact_id"]}" -->')
            lines.append(f'| {label(fact["fact_id"])} | {"入口处理" if fact["phase"] == "entry" else "后台执行"} | {"，".join(conditions) or "当前声明的正常执行范围"} |')
    lines += ["", f'结果：{analysis["review"]["outcome"]["text"]}', f'失败：{analysis["review"]["failure"]["text"]}', "",
              "验证范围：确定性 Mermaid 子集与冻结事实逐步对账；静态可达表示在所列条件下可能执行。", ""]
    for resolution in analysis.get("resolutions", []):
        locations = "、".join(f"{p['file']}:{p['line']}" for p in resolution["evidence"])
        caption = "非业务决策行" if resolution["classification"] == "non_business_decision" else "误判说明" if resolution["classification"] == "non_persistence" else "正常完成说明"
        lines += [f"{caption}：{resolution['explanation']}（证据 `{locations}`；`{resolution['finding']}`）。", ""]
    rendered = "\n".join(lines)
    for diagram in re.findall(r"```mermaid\n(.*?)```", rendered, re.S) if validate_diagram else []:
        errors = _validate_mermaid(diagram)
        if errors:
            raise ValueError("MERMAID_INVALID: " + "; ".join(errors))
    return rendered


def render_module(module, entries, git, scan, *, facts, analyses, module_meta, comparison="business_changed"):
    return "\n".join([f"<!-- biz-flow-module: {module} -->",
        f'<!-- devflow:flow-source-fingerprint value="{scan.source_fingerprint}" -->',
        f'# {module_meta["display_name"]}', "",
        *[render_entry(facts[e.entry_id], analyses[e.entry_id]) for e in entries]]).rstrip() + "\n"


def _split_entry_ids(raw: str) -> list[str]:
    """拆分入口列表，保留方法参数中的逗号。"""
    parts, start, depth = [], 0, 0
    for index, char in enumerate(raw):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and not depth:
            if value := raw[start:index].strip():
                parts.append(value)
            start = index + 1
    if value := raw[start:].strip():
        parts.append(value)
    return parts


def _slug(value: str) -> str:
    # Keep the source comment's words, including CJK, in the stable filename.
    return re.sub(r"[^\w-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-_") or "module"


_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _chinese_module_filename(index: int, name: str) -> str:
    """文件名主体使用一句业务短语，仅保留中文、字母和数字。"""
    label = re.sub(r"[^A-Za-z0-9\u3400-\u9fff]", "", _display(str(name)))
    return f"{index:02d}-{label}.md"


def _is_chinese_module_filename(value: object) -> bool:
    raw = str(value or "").replace("\\", "/")
    return bool(
        re.fullmatch(r"\d{2}-[A-Za-z0-9\u3400-\u9fff]+\.md", raw)
        and _CJK_RE.search(raw)
        and ".." not in Path(raw).parts
    )


def _module_function_summary(name: str, entries: list[EntryPoint]) -> str:
    """Use the source or user label verbatim, without a business vocabulary."""
    return _display(name)


def _module_business_description(entries: list[EntryPoint], candidates: list[EntryPoint]) -> str:
    """Keep source descriptions and labels; ownership remains user controlled."""
    included = {entry.entry_id for entry in entries}
    partial = any(entry.entry_id not in included and any(
        (entry.file, entry.module_label) == (owned.file, owned.module_label) for owned in entries)
        for entry in candidates)
    labels = [entry.business_name if partial else entry.module_description.strip() or entry.business_name for entry in entries]
    return "；".join(dict.fromkeys(label for label in labels if label))


def _mermaid_text(value: object, limit: int = 140) -> str:
    """Make arbitrary evidence safe for Mermaid sequence labels."""
    text = str(redact(value)).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).replace(";", "；").replace("|", "／").strip()
    return text[:limit]


def _display(value: str) -> str:
    """Preserve source/user labels without a project vocabulary."""
    value = str(value).strip()
    return value if _CJK_RE.search(value) else f"业务模块（{value}）"


def exclusion_categories(exclusions: list[dict]) -> list[tuple[str, int, str]]:
    """按排除语义分类展示；完整入口和源码证据仍由总览保存。"""
    groups: dict[str, int] = {}
    reasons = {
        "测试及契约校验": "测试、契约声明不属于运行时业务入口。",
        "客户端与外部调用契约": "出站调用属于协作依赖，不是服务端接收入口。",
        "仓储及数据访问": "保留调用链中的数据操作，不作为独立入口。",
        "基础设施配置及日志": "配置和辅助日志不直接产生业务结果。",
        "文件处理辅助方法": "被业务调用，没有独立文件触发注册。",
        "框架管理及静态资源": "健康检查、指标、管理和静态资源不承载业务处理。",
        "其他已证明的非业务候选": "按逐项源码证据排除，明细保留在总览。",
    }
    for item in exclusions:
        reason = str(item.get("reason", ""))
        if re.search(r"测试|SDK|契约声明", reason):
            category = "测试及契约校验"
        elif re.search(r"Feign|出站|客户端", reason):
            category = "客户端与外部调用契约"
        elif re.search(r"DAO|仓储|数据访问|持久化适配器", reason):
            category = "仓储及数据访问"
        elif re.search(r"配置|日志", reason):
            category = "基础设施配置及日志"
        elif "文件" in reason:
            category = "文件处理辅助方法"
        elif re.search(r"健康|框架管理|静态资源", reason):
            category = "框架管理及静态资源"
        else:
            category = "其他已证明的非业务候选"
        groups[category] = groups.get(category, 0) + 1
    return [(category, groups[category], reason) for category, reason in reasons.items() if category in groups]






def _non_business_reason(entry: EntryPoint) -> str | None:
    """Suggest exclusions while keeping every candidate in the scan evidence."""
    identifier = entry.identifier.casefold()
    relative = entry.file.replace("\\", "/").casefold()
    filename = Path(relative).stem
    parts = set(Path(relative).parts)
    if re.search(r"(?:^|[/ ])(?:health|actuator|metrics|static|swagger|openapi)(?:[/ ]|$)", identifier):
        return "健康检查、框架管理或静态资源入口，不承载业务处理。"
    if {"test", "tests", "src/test", "src/tests"} & parts or re.search(r"(?:test|tests|it|architecturetest)$", filename):
        return "测试或架构校验入口，不是运行时业务触发器。"
    if re.search(r"(?:^|[/])(?:config|configuration|settings|bootstrap)(?:[/]|$)", relative) or re.search(r"(?:config|configuration|settings)$", filename):
        return "基础设施配置入口，不直接产生业务结果。"
    if re.search(r"(?:dao|repository|persistence|persistenceadapter|dataaccess)$", filename) or re.search(r"(?:^|[/])(?:dao|repository|persistence|infrastructure)(?:[/]|$)", relative):
        return "DAO、仓储或基础设施适配器是被调用的数据访问实现，不是独立业务触发器。"
    return None


def _non_business_candidate(entry: EntryPoint) -> bool:
    return _non_business_reason(entry) is not None


def module_overview(mapping: dict) -> list[str]:
    """对话与持久化总览共用三列表格，显示文件名主体而非扩展名。"""
    excluded_ids = {item["candidate"] for item in mapping.get("exclusions", [])}
    lines = ["| 业务模块文件名 | 业务描述 | 入口数量 |", "| --- | --- | ---: |"]
    for module in sorted(mapping.get("modules", []), key=lambda item: item["name"]):
        filename = str(redact(Path(str(module["file"])).stem))
        description = str(redact(module["responsibility"])).replace("|", "\\|").replace("\n", " ")
        count = len(set(module["entry_ids"]) - excluded_ids)
        lines.append(f"| {filename} | {description} | {count} |")
    return lines


def registration_overview(scan: ScanResult) -> list[str]:
    """注册候选审计与业务入口清单分别对账，未支持注册不能静默丢弃。"""
    groups = {}
    for item in scan.registration_audit:
        counts = groups.setdefault(str(item["adapter"]), {"registered": 0, "business": set(), "excluded": set(), "unresolved": 0})
        counts["registered"] += 1
        status = item["status"]
        if status in {"business", "excluded"}:
            counts[status].update(item.get("entry_ids", []))
        else:
            counts["unresolved"] += 1
    lines = ["## 注册覆盖审计", "", "| 注册类型 | 注册候选 | 业务入口 | 排除入口 | 未解析注册 |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for adapter, counts in sorted(groups.items()):
        lines.append(f"| {adapter} | {counts['registered']} | {len(counts['business'])} | {len(counts['excluded'])} | {counts['unresolved']} |")
    lines.extend(["", "覆盖边界：审计已支持的静态注册；动态注册及未支持的声明必须保留未决，不能据此推断不存在其他业务入口。", ""])
    if scan.coverage_gaps:
        lines.extend(["## 注册覆盖缺口", "", *[
            f"- `{item['file']}:{item['line']}`：{item['reason']}；补充静态注册证据或扩展包内适配器后重新 discover。"
            for item in scan.coverage_gaps], ""])
    return lines


def readable_inventory(scan: ScanResult, mapping: dict) -> list[str]:
    """Render the same complete, evidence-backed inventory at every CLI stage."""
    entries = {entry.entry_id: entry for entry in (scan.all_entries or scan.entries)}
    modules = sorted(mapping.get("modules", []), key=lambda item: item["name"])
    exclusions = {item["candidate"]: item for item in mapping.get("exclusions", [])}
    owners = {entry_id: module["name"] for module in modules for entry_id in module["entry_ids"]}
    groups = {
        module["name"]: sorted(
            entry_id for entry_id, entry in entries.items()
            if owners.get(entry_id) == module["name"]
            or (entry_id in exclusions and exclusions[entry_id].get("module", entry.module) == module["name"])
        )
        for module in modules
    }

    def clean(value: object) -> str:
        return str(redact(value or "")).replace("|", "\\|").replace("\n", " ").strip()

    def entry_row(entry_id: str) -> str:
        entry = entries[entry_id]
        exclusion = exclusions.get(entry_id)
        evidence = "; ".join(
            f"{item.get('file', entry.file)}:{item.get('line', entry.line)}"
            for item in entry.source_evidence if isinstance(item, dict)
        )
        evidence = evidence or f"{entry.file}:{entry.line}"
        status = "excluded" if exclusion else entry.scope_status
        reason = exclusion["reason"] if exclusion else (entry.exclusion_reason or "")
        return (
            f"| {clean(entry.business_name or '待确认')} | {clean(entry.trigger_summary)} | `{clean(entry_id)}` | "
            f"`{clean(evidence)}` | {status} | {clean(reason)} |"
        )

    lines = ["<!-- devflow:inventory -->", "## 业务模块划分", "", *module_overview(mapping)]
    lines.extend(["", *registration_overview(scan)])
    lines.extend(["", "## 建议忽略的入口", "", "| 类别 | 数量 | 原因 |", "| --- | ---: | --- |"])
    for category, count, reason in exclusion_categories(list(exclusions.values())):
        lines.append(f"| {category} | {count} | {reason} |")
    lines.extend(["", '<details id="排除明细">', "<summary>展开忽略项明细与源码证据</summary>", "",
                  "| 入口 ID | 源码位置 | 建议 | 原因 |", "| --- | --- | --- | --- |"])
    for entry_id, item in sorted(exclusions.items()):
        lines.append(f"| `{clean(entry_id)}` | `{clean('; '.join(item['evidence']))}` | 排除 | {clean(item['reason'])} |")
    if not exclusions:
        lines.append("| — | — | 保留 | 未发现建议忽略项。 |")
    lines.extend(["", "</details>"])
    lines.extend(["", "## 完整入口清单", ""])
    rendered = set()
    for module in modules:
        ids = groups[module["name"]]
        lines.extend([f'<details id="{_slug(module["name"])}-入口">',
                      f"<summary>{clean(module['display_name'])}入口（{len(ids)} 个）</summary>", "",
                      "| 业务名称 | 触发方式 | 入口 ID | 源码位置 | 范围状态 | 排除原因 |",
                      "| --- | --- | --- | --- | --- | --- |", *[entry_row(entry_id) for entry_id in ids],
                      "", "</details>", ""])
        rendered.update(ids)
    remaining = sorted(set(entries) - rendered)
    if remaining:
        lines.extend(['<details id="技术候选入口">', f"<summary>技术候选入口（{len(remaining)} 个）</summary>", "",
                      "| 业务名称 | 触发方式 | 入口 ID | 源码位置 | 范围状态 | 排除原因 |",
                      "| --- | --- | --- | --- | --- | --- |", *[entry_row(entry_id) for entry_id in remaining],
                      "", "</details>", ""])
    unresolved = [entry for entry in entries.values() if entry.entry_id not in exclusions and entry.business_name in {"", "待确认"}]
    if unresolved:
        lines.extend(["## 待确认名称", "", *[
            f"- `{clean(entry.entry_id)}`：入口适配器未提供可确认的中文行为名称；请补齐触发、处理器或注册证据。"
            for entry in unresolved
        ], ""])
    if scan.unresolved:
        lines.extend(["## 待源码复核", "", "静态未解析记录应先由只读入口代理补证；不是要求用户逐条解答的业务问题。", "",
                      "<details>", f"<summary>展开 {len(scan.unresolved)} 项待复核证据</summary>", "",
                      *[f"- {clean(finding)}" for finding in scan.unresolved], "", "</details>", ""])
    lines.append("<!-- /devflow:inventory -->")
    return lines


def analysis_status_overview(scan, mapping, docs_root, completed=()):
    lines = ["<!-- devflow:analysis-status -->", "## 模块分析状态", "",
             "| 模块文件 | 流程分析状态 |", "| --- | --- |"]
    for module in sorted(mapping["modules"], key=lambda item: item["name"]):
        path = docs_root / module["file"]
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        fingerprint = re.search(r'<!-- devflow:flow-source-fingerprint value="([^"]+)" -->', text)
        status = "已完成" if module["file"] in completed or fingerprint and fingerprint[1] == scan.source_fingerprint else (
            "源码已变更，原流程待重新分析" if "```mermaid" in text else "待分析")
        filename = str(redact(module["file"]))
        lines.append(f"| [{Path(filename).stem}]({filename}) | {status} |")
    return "\n".join([*lines, "", "<!-- /devflow:analysis-status -->"])


def validate_inventory(scan, markdown, mapping):
    block = re.search(r"(?s)<!-- devflow:inventory -->\n(.*?)\n<!-- /devflow:inventory -->", markdown)
    expected = "\n".join(readable_inventory(scan, mapping)[1:-1])
    return [] if block and block[1] == expected else ["总览业务范围及入口清单与注册证据或模块归属不一致"]


def _validate_mermaid(diagram: str, *, render=True) -> list[str]:
    """Validate the sequence subset emitted by this skill before claiming it renders."""
    renderer = (shutil.which("mmdc.cmd") or shutil.which("mmdc")) if render else None
    renderer_path = Path(renderer) if renderer else None
    signature = str(renderer_path.resolve()) + str(renderer_path.stat().st_mtime_ns) if renderer_path and renderer_path.is_file() else str(renderer) + ":" + str(id(subprocess.run))
    cache_key = hashlib.sha256((signature + "\0" + diagram.replace("\r\n", "\n").replace("\r", "\n")).encode("utf-8")).hexdigest()
    cached = _MERMAID_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    if ";" in diagram:
        return ["ASCII semicolon is not allowed in Mermaid sequence labels"]
    lines = [line.strip() for line in diagram.splitlines() if line.strip()]
    if lines and lines[0].startswith("%%{init:"):
        lines = lines[1:]
    if not lines or lines[0] != "sequenceDiagram":
        return ["missing sequenceDiagram header"]
    if "autonumber" not in lines[1:]:
        return ["missing autonumber"]
    generic_database_labels = [
        line for line in lines
        if line.startswith("participant ")
        and ("账号库" in line or "会话库" in line or "需确认具体表名" in line)
    ]
    if generic_database_labels:
        return ["database participants must use a confirmed table name and Chinese name"]
    errors = validate_sequence(diagram)
    if errors or not renderer:
        return errors
    cache_path = state_root() / "biz-flow" / "render-cache" / (cache_key + ".json")
    if renderer_path.is_file() and cache_path.is_file():
        try:
            if json.loads(cache_path.read_text(encoding="utf-8")) == {"diagram_hash": cache_key, "passed": True}:
                _MERMAID_CACHE[cache_key] = ()
                return []
        except (ValueError, OSError):
            pass
    # Use Mermaid's own parser when the optional CLI is installed. The custom
    # validator above remains the deterministic fallback for normal installs.
    try:
        timeout = float(os.environ.get("DEVFLOW_MERMAID_TIMEOUT", "60"))
        if not 0 < timeout < float("inf"):
            raise ValueError("DEVFLOW_MERMAID_TIMEOUT must be a finite positive number of seconds")
        with tempfile.TemporaryDirectory(prefix="biz-flow-mermaid-") as temporary:
            source = Path(temporary) / "diagram.mmd"
            output = Path(temporary) / "diagram.svg"
            source.write_text(diagram, encoding="utf-8")
            completed = subprocess.run(
                [renderer, "-i", str(source), "-o", str(output), "-q"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout or "Mermaid renderer failed").strip()
                errors = [f"Mermaid renderer rejected diagram: {detail[:240]}"]
                return errors
            svg = ET.parse(output).getroot()
            if svg.tag != "{http://www.w3.org/2000/svg}svg":
                errors = ["Mermaid renderer did not produce an SVG document"]
                return errors
            geometry = {"x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "dx", "dy",
                        "width", "height", "viewBox", "points", "d", "transform"}
            if any(re.search(r"(?<!\w)(?:NaN|[+-]?Inf(?:inity)?|undefined)(?!\w)", value, re.I)
                   for element in svg.iter() for key, value in element.attrib.items() if key in geometry):
                errors = ["Mermaid renderer produced non-finite SVG coordinates"]
                return errors
    except ET.ParseError as exc:
        errors = [f"Mermaid renderer produced invalid SVG: {exc}"]
        return errors
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        errors = [f"Mermaid renderer unavailable: {exc}"]
        return errors
    if renderer_path.is_file():
        write_json(cache_path, {"diagram_hash": cache_key, "passed": True})
        trim_cache(cache_path.parent)
    _MERMAID_CACHE[cache_key] = tuple(errors)
    return errors


def write_entry_directory(scan: ScanResult, docs_root: Path, mapping: dict) -> list[str]:
    """总览拥有完整清单；模块仅保留标题及已有流程内容。"""
    candidates = {entry.entry_id: entry for entry in (scan.all_entries or scan.entries)}
    excluded = {item["candidate"] for item in mapping.get("exclusions", [])}
    assigned = [entry_id for module in mapping.get("modules", []) for entry_id in module["entry_ids"]]
    errors = []
    if len(assigned) != len(set(assigned)):
        errors.append("入口目录存在重复归属")
    if set(assigned) != set(candidates) - excluded:
        errors.append("入口目录未完整覆盖业务入口")
    for module in mapping.get("modules", []):
        if not _is_chinese_module_filename(module["file"]):
            errors.append(f"模块文件名不符合业务命名要求：{module['file']}")
    if errors:
        return errors
    current_files = {module["file"] for module in mapping.get("modules", [])}
    for path in docs_root.glob("*.md"):
        if path.name in current_files:
            continue
        text = path.read_text(encoding="utf-8")
        # 归组变更只清理完整的自动清单骨架，已有流程或人工补充必须保留。
        if re.fullmatch(r"(?s)<!-- biz-flow-module: [^\n]+ -->\n# [^\n]+\n\s*(?:<!-- devflow:entry-directory -->.*?<!-- /devflow:entry-directory -->\s*)?", text):
            path.unlink()
    for module in mapping.get("modules", []):
        path = docs_root / module["file"]
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if "<!-- devflow:entry-directory -->" in text:
            text = re.sub(r"(?s)<!-- devflow:entry-directory -->.*?<!-- /devflow:entry-directory -->\n?", "", text)
        if not text:
            text = f"<!-- biz-flow-module: {module['name']} -->\n# {module['display_name']}\n"
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    return []
