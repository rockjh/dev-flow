"""Render biz-flow Markdown, indexes, and coverage reports."""

from __future__ import annotations

import json
import ast
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..core.artifacts import write_json
from ..core.redaction import redact
from ..core.schema import (
    BIZ_FLOW_COMPARISON_SCHEMA,
    BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA,
    BIZ_FLOW_DISCOVERY_SCHEMA,
    BIZ_FLOW_EVIDENCE_CACHE_SCHEMA,
    BIZ_FLOW_INDEX_SCHEMA,
    BIZ_FLOW_MIGRATIONS_SCHEMA,
    BIZ_FLOW_MODULE_MAP_SCHEMA,
    BIZ_FLOW_OWNERSHIP_SCHEMA,
    BIZ_FLOW_REPORT_SCHEMA,
    BIZ_FLOW_SCHEMA_VERSION,
    validate_schema,
)
from .models import BehaviorEvidence, EntryPoint, EntryReview, ErrorEvidence, FlowStep, GitInfo, ScanResult


PLACEHOLDER_RE = re.compile(
    r"(?:代码中未确认|处理链中的业务步骤|更具体的业务目的|错误后果按可传播错误记录|"
    r"执行[^；。]*未确认|结果代码中未确认)",
)


def _required_control_counts(scan: ScanResult, entry: EntryPoint) -> tuple[int, int, int]:
    """Return minimum control blocks for the confirmed Python call chain."""
    if scan.git.target != scan.git.head:
        return 0, 0, 0
    references = [entry.file]
    references.extend(
        value.split(":", 1)[0]
        for value in entry.functions
        if ":" in value
    )
    required = [0, 0, 0]
    for relative in dict.fromkeys(references):
        suffix = Path(relative).suffix.lower()
        if suffix != ".py":
            try:
                text = (scan.root / relative).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            # C-like languages have stable lexical control markers even when
            # a full compiler is unavailable. Count only the entry call-chain
            # source files already recorded by discovery.
            required[0] += len(re.findall(r"\bif\s*\(", text))
            required[1] += len(re.findall(r"\b(?:for|while)\s*\(", text))
            required[2] += len(re.findall(r"\bif\s*\([^\n]*\)\s*\{[^{}]*\}\s*else\b", text, re.S))
            continue
        try:
            tree = ast.parse((scan.root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError):
            continue
        names = {
            entry.handler,
            *(
                value.rsplit(":", 1)[-1]
                for value in entry.functions
                if ":" in value and value.startswith(relative + ":")
            ),
            *(value for value in entry.functions if ":" not in value and relative == entry.file),
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in names:
                continue
            required[0] += sum(isinstance(item, ast.If) for item in ast.walk(node))
            required[1] += sum(
                isinstance(item, (ast.For, ast.AsyncFor, ast.While))
                for item in ast.walk(node)
            )
            required[2] += sum(
                isinstance(item, ast.If) and bool(item.orelse)
                for item in ast.walk(node)
            )
    return tuple(required)


def _slug(value: str) -> str:
    # Keep the source comment's words, including CJK, in the stable filename.
    return re.sub(r"[^\w-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-_") or "module"


_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _chinese_module_filename(index: int, name: str) -> str:
    """Return the canonical NN-Chinese-name.md module filename."""
    chinese = "".join(re.findall(r"[\u3400-\u9fff]+", str(name)))
    if not chinese:
        chinese = "".join(re.findall(r"[\u3400-\u9fff]+", _display(str(name))))
    if not chinese:
        chinese = "业务模块"
    return f"{index:02d}-{chinese[:40]}.md"


def _is_chinese_module_filename(value: object) -> bool:
    raw = str(value or "").replace("\\", "/")
    return bool(
        re.fullmatch(r"\d{2}-[^/]+\.md", raw)
        and _CJK_RE.search(raw)
        and ".." not in Path(raw).parts
    )


def _mermaid_text(value: object, limit: int = 140) -> str:
    """Make arbitrary evidence safe for Mermaid sequence labels."""
    text = str(redact(value)).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).replace(";", "；").replace("|", "／").strip()
    return text[:limit]


_MODULE_WORDS = {
    "admin": "管理",
    "api": "接口",
    "config": "配置",
    "configuration": "配置",
    "dao": "数据访问",
    "device": "设备",
    "esim": "eSIM",
    "file": "文件",
    "order": "订单",
    "profile": "Profile",
    "relation": "关系",
    "sync": "同步",
    "user": "用户",
    "vehicle": "车辆",
}


def _display(value: str) -> str:
    """Return a stable, human-facing business name with Chinese context."""
    if value == "公共能力":
        return value
    raw = str(value).replace("_", "-").strip("-")
    parts = [part for part in raw.split("-") if part and part.casefold() not in {"v0", "v1", "impl", "src"}]
    labels = [_MODULE_WORDS.get(part.casefold(), part) for part in parts]
    rendered = "".join(labels).strip()
    if not rendered or rendered.casefold() == raw.casefold():
        rendered = f"业务模块（{raw}）"
    elif not re.search(r"[\u3400-\u9fff]", rendered):
        rendered = f"{rendered}业务"
    return rendered


def _entry_title(entry: EntryPoint) -> str:
    names = {
        "url": "URL",
        "webhook": "Webhook",
        "websocket": "WebSocket",
        "sse": "SSE",
        "rpc": "RPC",
        "message": "消息",
        "scheduled": "定时任务",
        "event": "事件监听",
        "cli": "命令行任务",
        "file": "文件入口",
        "batch": "批处理任务",
    }
    if entry.title and not entry.title_unresolved:
        return entry.title[:80]
    # A generated document must still have a business-shaped heading when the
    # source has no human label.  Keep protocol details in the trigger line.
    return {
        "url": "HTTP 请求处理",
        "webhook": "Webhook 处理",
        "websocket": "WebSocket 消息处理",
        "sse": "事件流处理",
        "rpc": "RPC 业务调用",
        "message": "消息消费处理",
        "scheduled": "定时任务处理",
        "event": "事件监听处理",
        "cli": "命令行任务",
        "file": "文件导入处理",
        "batch": "批处理任务",
        "worker": "异步任务处理",
    }.get(entry.kind, "业务入口处理")


def _codes(entry: EntryPoint) -> str:
    return "；".join(entry.error_codes()) if entry.error_codes() else "无"


def _error_dict(error: ErrorEvidence) -> dict[str, Any]:
    return {
        "code": error.code,
        "condition": str(redact(error.condition)),
        "source": f"{error.file}:{error.line}",
        "capture_boundary": error.capture_boundary,
        "propagation": error.propagation,
        "consequence": error.consequence,
        "phase": error.phase,
        "recovery": error.recovery,
    }


def _error_from_dict(value: object, fallback: str) -> ErrorEvidence:
    item = value if isinstance(value, dict) else {}
    file, separator, number = str(item.get("source", fallback)).rpartition(":")
    line = int(number) if separator and number.isdigit() else int(fallback.rpartition(":")[-1] or 1)
    if not file:
        file = fallback.rpartition(":")[0]
    return ErrorEvidence(
        str(item.get("code", "代码中未确认")),
        str(item.get("condition", "代码中未确认")),
        file,
        line,
        str(item.get("capture_boundary", "代码中未确认")),
        str(item.get("propagation", "代码中未确认")),
        str(item.get("consequence", "代码中未确认")),
        str(item.get("phase", "sync")),
        str(item.get("recovery", "代码中未确认")),
    )


def _cache_entry(entry: EntryPoint) -> dict[str, Any]:
    """Serialize all parsed evidence needed to resume without rescanning."""
    return {
        "id": entry.entry_id,
        "type": entry.kind,
        "identifier": entry.identifier,
        "handler": entry.handler,
        "source": f"{entry.file}:{entry.line}",
        "module": entry.module,
        "module_rationale": entry.module_rationale,
        "caller": str(redact(entry.caller)),
        "input_summary": str(redact(entry.input_summary)),
        "functions": list(entry.functions),
        "errors": [_error_dict(error) for error in entry.errors],
        "behaviors": [
            {
                "kind": behavior.kind,
                "statement": str(redact(behavior.statement)),
                "source": f"{behavior.file}:{behavior.line}",
            }
            for behavior in entry.behaviors
        ],
        "has_loop": entry.has_loop,
        "has_external_call": entry.has_external_call,
        "has_persistence": entry.has_persistence,
        "has_async": entry.has_async,
        "binding_confirmed": entry.binding_confirmed,
        "handler_confirmed": entry.handler_confirmed,
        "title": entry.title,
        "title_unresolved": entry.title_unresolved,
        "parent_entry_id": entry.parent_entry_id,
        "submit_source": entry.submit_source,
    }


def _cache_payload(scan: ScanResult) -> dict[str, Any]:
    return {
        "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "source_fingerprint": scan.source_fingerprint,
        "root": str(scan.root),
        "git": {
            "branch": scan.git.branch,
            "head": scan.git.head,
            "target": scan.git.target,
            "dirty": scan.git.dirty,
            "includes_uncommitted": scan.git.includes_uncommitted,
            "comparison": scan.git.comparison,
        },
        "languages": list(scan.languages),
        "frameworks": list(scan.frameworks),
        "files": list(scan.files),
        "source_lines": dict(scan.source_lines),
        "unresolved": list(scan.unresolved),
        "exclusions": list(scan.exclusions),
        "candidate_entry_count": scan.candidate_entry_count,
        "confirmed_binding_count": scan.confirmed_binding_count,
        "confirmed_handler_count": scan.confirmed_handler_count,
        "entries": {entry.entry_id: _cache_entry(entry) for entry in scan.entries},
    }


def _review_placeholders(review: EntryReview) -> list[str]:
    fields = {
        "trigger": review.trigger,
        "purpose": review.purpose,
        "input": review.input,
        "outcome": review.outcome,
        "failure": review.failure,
    }
    problems = [name for name, value in fields.items() if not str(value).strip() or PLACEHOLDER_RE.search(str(value))]
    if not review.steps:
        problems.append("steps")
    if any(not step.text.strip() or PLACEHOLDER_RE.search(step.text) for step in review.steps):
        problems.append("step_text")
    if not any(step.kind == "action" for step in review.steps):
        problems.append("action_step")
    return problems


def _review(entry: EntryPoint) -> EntryReview:
    if entry.review is not None:
        return entry.review
    steps: list[FlowStep] = []
    # Evidence supplied by the entry task is the only source for business
    # decisions in generated Markdown.  Discovery metadata can add readable
    # actions, but it cannot invent branch outcomes.
    for branch in entry.agent_branches:
        if branch.get("business_relevant") is not True or branch.get("reachability") == "unreachable":
            continue
        branch_id = str(branch.get("branch_id", ""))
        condition = str(branch.get("label") or branch.get("condition") or "")
        if branch_id and condition:
            steps.append(FlowStep("alt", f"{branch_id}：{condition}", f"{branch.get('source_file', entry.file)}:{branch.get('source_line', entry.line)}"))
            for outcome in branch.get("outcome_labels", branch.get("outcomes", [])):
                steps.append(FlowStep("action", f"{branch_id} 结果：{outcome}", f"{branch.get('source_file', entry.file)}:{branch.get('source_line', entry.line)}"))
            steps.append(FlowStep("end", f"结束 {branch_id} 分支", f"{branch.get('source_file', entry.file)}:{branch.get('source_line', entry.line)}"))
    for action in entry.agent_persistence:
        if action.get("resource_name") and action.get("display_name"):
            steps.append(FlowStep("persistence", f"{action.get('operation_label', action.get('operation'))} {action['resource_name']}（{action['display_name']}）",
                                  f"{action.get('source_file', entry.file)}:{action.get('source_line', entry.line)}",
                                  f"{action['resource_name']}（{action['display_name']}）"))
    explicit_loops = 0
    for behavior in entry.behaviors:
        if behavior.kind == "循环":
            explicit_loops += 1
            steps.append(FlowStep(
                "loop",
                f"按源码循环条件逐项处理：{behavior.statement}",
                f"{behavior.file}:{behavior.line}",
            ))
            continue
        participant = "当前系统"
        if behavior.kind == "持久化":
            # A generic storage participant would turn missing evidence into
            # a false claim. Resolved persistence actions above carry the real
            # resource label; unresolved storage is kept local until the
            # evidence gate rejects it.
            participant = "当前系统"
        elif behavior.kind == "外部调用":
            participant = "可见外部接口"
        elif behavior.kind in {"消息", "异步"}:
            participant = "消息/异步系统"
        source = f"{behavior.file}:{behavior.line}"
        # The source condition is authoritative even when a localized
        # behavior label was not recovered by discovery.
        if (
            (behavior.kind == "校验" or re.search(r"^\s*if\b", behavior.statement, re.I))
            and re.search(r"\bif\b|\bunless\b|\bwhen\b", behavior.statement, re.I)
        ):
            steps.append(FlowStep("alt", f"满足前置条件：{behavior.statement}", source, "当前系统"))
            steps.append(FlowStep("action", _business_step(behavior), source, participant))
            steps.append(FlowStep("end", "结束前置条件分支", source, "当前系统"))
        else:
            steps.append(FlowStep("action", _business_step(behavior), source, participant))
    if not steps:
        steps.append(FlowStep("action", f"调用入口处理器 {entry.handler}", f"{entry.file}:{entry.line}"))
    if explicit_loops:
        end_source = (
            f"{entry.file}:{max((behavior.line for behavior in entry.behaviors), default=entry.line)}"
        )
        steps.extend(
            FlowStep("end", "结束源码循环", end_source)
            for _ in range(explicit_loops)
        )
    elif entry.has_loop:
        loop_source = f"{entry.file}:{min((behavior.line for behavior in entry.behaviors), default=entry.line)}"
        end_source = f"{entry.file}:{max((behavior.line for behavior in entry.behaviors), default=entry.line)}"
        steps = [FlowStep("loop", "源码中的逐项循环处理", loop_source), *steps, FlowStep("end", "结束循环", end_source)]
    input_value = entry.input_summary
    if not input_value or input_value == "代码中未确认":
        input_value = entry.identifier
    return EntryReview(
        review_id=entry.entry_id,
        trigger=entry.caller,
        purpose=f"处理入口 {entry.identifier} 的业务请求",
        input=input_value,
        outcome=(f"返回源码定义的处理结果；已确认行为见步骤" if entry.behaviors or entry.agent_branches else "返回入口处理器结果"),
        failure=(f"按源码错误分支处理：{', '.join(entry.error_codes())}" if entry.errors else "源码未发现显式失败分支"),
        steps=steps,
        status="draft",
    )


def _business_step(behavior: BehaviorEvidence) -> str:
    statements = {
        "校验": "校验输入或前置条件，未通过时停止后续动作（具体错误结果见异常表）。",
        "循环": "按源码循环条件逐项处理；单项失败是否继续以异常捕获证据为准。",
        "分支": "进入源码明确的条件分支。",
        "事务": "在源码标记的事务边界内执行后续本地动作。",
        "锁与幂等": "执行源码可确认的并发或幂等控制。",
        "持久化": "写入或读取本地持久化对象；具体对象和提交点以证据为准。",
        "外部调用": "调用源码可见的外部接口；远端内部实现不在本地证据范围内。",
        "消息": "发送或发布消息，后续消费结果不等同于本入口同步完成。",
        "异步": "提交后台或异步处理；受理成功不等同于后台终态成功。",
        "缓存或文件": "读写缓存或文件资源。",
        "状态变化": "改变业务状态，前后状态值以源码证据为准。",
        "结果": "形成源码中的返回或产出结果。",
    }
    return statements.get(behavior.kind, f"执行 {behavior.kind} 处理；具体规则代码中未确认。")


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


def _source_line(value: str) -> int:
    number = value.rsplit(":", 1)[-1]
    return int(number) if number.isdigit() else 0


def _append_error(lines: list[str], error: ErrorEvidence) -> None:
    condition = str(redact(error.condition)).replace("\n", " ")[:100]
    consequence = str(redact(error.consequence)).replace("\n", " ")[:100]
    lines.append(f"alt {error.code}：{condition}")
    lines.append(f"P1-->>P0: {error.phase}错误；{consequence}")
    lines.append("P1-->>P0: 协议失败；结果未落库；未投递")
    lines.append("end")


def _append_error(lines: list[str], error: ErrorEvidence) -> None:
    """Render optional async interruptions as opt; synchronous errors remain alt branches."""
    condition = _mermaid_text(error.condition, 100)
    consequence = _mermaid_text(error.consequence, 100).replace("代码中未确认", "未见源码证据")
    kind = "opt" if error.phase in {"async", "worker"} else "alt"
    lines.append(f"{kind} {_mermaid_text(error.code, 60)}: {condition}")
    lines.append(f"P1-->>P0: {_mermaid_text('业务失败；' + consequence)}")
    lines.append("end")


def _diagram(entry: EntryPoint) -> str:
    review = _review(entry)
    caller = entry.caller
    if not caller or caller == "代码中未确认":
        caller = {"url": "HTTP调用方", "webhook": "Webhook调用方", "message": "消息生产方",
                  "scheduled": "调度器", "worker": "任务提交方"}.get(entry.kind, "入口调用方")
    lines = ["```mermaid", "sequenceDiagram", "autonumber",
             f"participant P0 as {_mermaid_text(caller, 80)}",
             f"participant P1 as {_mermaid_text(entry.module or '业务入口', 80)}"]
    aliases: dict[str, str] = {}
    for action in entry.agent_persistence:
        label = f"{action['resource_name']}（{action['display_name']}）"
        alias = f"P{len(aliases) + 2}"
        aliases[action["persistence_id"]] = alias
        lines.append(f"participant {alias} as {_mermaid_text(label, 80)}")
    lines.append(f"P0->>P1: {_mermaid_text(entry.identifier, 100)}")
    lines.append(f"P1->>P1: {_mermaid_text('进入 ' + entry.handler, 100)}")
    for branch in entry.agent_branches:
        if branch.get("business_relevant") is not True or branch.get("reachability") == "unreachable":
            continue
        branch_id = str(branch.get("branch_id", ""))
        condition = str(branch.get("label") or branch.get("condition") or "")
        lines.append(f'%% devflow:branch id="{branch_id}"')
        lines.append(f"alt {_mermaid_text(branch_id + '：' + condition, 110)}")
        outcomes = branch.get("outcome_labels", branch.get("outcomes", [])) or ["源码结果"]
        for index, outcome in enumerate(outcomes):
            if index:
                lines.append(f"else {_mermaid_text(branch_id + '：' + str(outcome), 100)}")
            lines.append(f"P1->>P1: {_mermaid_text(str(outcome), 100)}")
        lines.append("end")
    for action in entry.agent_persistence:
        identifier = action["persistence_id"]
        lines.append(f'%% devflow:persistence id="{identifier}"')
        lines.append(f"P1->>{aliases[identifier]}: {_mermaid_text(action.get('operation_label', action.get('operation', '操作')), 100)}")
    for step in review.steps:
        if step.kind == "action" and not any(str(branch.get("branch_id", "")) in step.text for branch in entry.agent_branches):
            lines.append(f"P1->>P1: {_mermaid_text(step.text, 110)}")
    for error in sorted(entry.errors, key=lambda item: item.line):
        _append_error(lines, error)
    lines.append(f"P1-->>P0: {_mermaid_text(str(redact(review.outcome)), 120)}")
    lines.append("Note over P0,P1: 入口结果由源码证据确定")
    lines.append("```")
    return "\n".join(lines)


def _validate_mermaid(diagram: str) -> list[str]:
    """Validate the sequence subset emitted by this skill before claiming it renders."""
    if ";" in diagram:
        return ["ASCII semicolon is not allowed in Mermaid sequence labels"]
    lines = [line.strip() for line in diagram.splitlines() if line.strip()]
    if lines and lines[0].startswith("%%{init:"):
        lines = lines[1:]
    if not lines or lines[0] != "sequenceDiagram":
        return ["missing sequenceDiagram header"]
    if "autonumber" not in lines[1:]:
        return ["missing autonumber"]
    aliases = {match.group(1) for line in lines if (match := re.match(r"participant\s+(\w+)\s+as\s+", line))}
    generic_database_labels = [
        line for line in lines
        if line.startswith("participant ")
        and ("账号库" in line or "会话库" in line or "需确认具体表名" in line)
    ]
    if generic_database_labels:
        return ["database participants must use a confirmed table name and Chinese name"]
    blocks: list[str] = []
    errors: list[str] = []
    for line in lines[1:]:
        if line.startswith(("alt ", "opt ", "loop ")):
            blocks.append(line.split(" ", 1)[0])
        elif line.startswith("else "):
            if not blocks or blocks[-1] != "alt":
                errors.append(f"line {lines.index(line) + 1}: else outside alt")
        elif line == "end":
            if not blocks:
                errors.append(f"line {lines.index(line) + 1}: unmatched end")
            else:
                blocks.pop()
        elif match := re.match(r"(\w+)(?:-->>|->>)(\w+):\s*", line):
            if match.group(1) not in aliases or match.group(2) not in aliases:
                errors.append(f"line {lines.index(line) + 1}: unknown participant in message: {line}")
        elif line.startswith("Note over "):
            note_match = re.match(r"Note over\s+(\w+)(?:,(\w+))?:", line)
            if not note_match:
                errors.append(f"line {lines.index(line) + 1}: invalid note statement: {line}")
            else:
                for participant in note_match.groups():
                    if participant and participant not in aliases:
                        errors.append(f"line {lines.index(line) + 1}: unknown participant in note: {line}")
        elif line == "autonumber" or line.startswith("participant ") or line.startswith("%%"):
            continue
        else:
            errors.append(f"line {lines.index(line) + 1}: unsupported sequence statement: {line}")
    if blocks:
        errors.append("unclosed " + ", ".join(blocks))
    renderer = shutil.which("mmdc.cmd") or shutil.which("mmdc")
    if errors or not renderer:
        return errors
    # Use Mermaid's own parser when the optional CLI is installed. The custom
    # validator above remains the deterministic fallback for normal installs.
    try:
        with tempfile.TemporaryDirectory(prefix="biz-flow-mermaid-") as temporary:
            source = Path(temporary) / "diagram.mmd"
            output = Path(temporary) / "diagram.svg"
            source.write_text(diagram, encoding="utf-8")
            completed = subprocess.run(
                [renderer, "-i", str(source), "-o", str(output), "-q"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout or "Mermaid renderer failed").strip()
                return [f"Mermaid renderer rejected diagram: {detail[:240]}"]
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"Mermaid renderer unavailable: {exc}"]
    return errors


def _validate_branch_matrix(section: str) -> list[str]:
    """Require one entry-local matrix with the stable business columns."""
    headings = re.findall(r"^###\s+.*分支矩阵\s*$", section, flags=re.MULTILINE)
    if len(headings) != 1:
        return ["each entry must contain exactly one branch matrix"]
    matrix_start = section.find(headings[0])
    matrix = section[matrix_start:]
    header = next(
        (line.strip() for line in matrix.splitlines() if line.strip().startswith("|") and "---" not in line),
        "",
    )
    required = ("分支条件", "数据读取与比较", "数据写入与副作用", "响应")
    errors = [f"branch matrix missing column: {column}" for column in required if column not in header]
    if "源代码依据" in header or "源代码证据" in matrix:
        errors.append("branch matrix must not contain source-code evidence prose")
    return errors


def _description(review: EntryReview) -> str:
    """Render short business points; machine validation enforces the limit."""
    values = [review.purpose, review.input, review.outcome, review.failure]
    def clean(value: object) -> str:
        text = str(value or "").strip()
        # Source locations belong to machine evidence, never to the readable
        # entry body.  Keep the surrounding business sentence intact.
        text = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z0-9_./\\-]+:\d+(?!\d)", "", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" ，,;；")
        return text
    return "\n".join(f"- {clean(value)}" for value in values if clean(value))


def _entry_text(entry: EntryPoint) -> str:
    """Render one summary and the entry's source-backed sequence diagrams."""
    review = _review(entry)
    return "\n".join([
        f"<!-- biz-flow-entry: {entry.entry_id} -->",
        "",
        f"## {_entry_title(entry)}",
        "",
        _entry_intro(entry),
        "",
        _description(review),
        "",
        _diagram(entry),
        "",
        _branch_matrix(entry),
        "",
    ])


def _branch_matrix(entry: EntryPoint) -> str:
    """Render one compact decision matrix for this entry only."""
    rows: list[str] = []
    for branch in entry.agent_branches:
        if branch.get("business_relevant") is not True or branch.get("reachability") == "unreachable":
            continue
        branch_id = str(branch.get("branch_id", ""))
        condition = _mermaid_text(str(branch.get("condition") or branch.get("label") or ""), 100)
        outcomes = _mermaid_text(" / ".join(str(value) for value in branch.get("outcome_labels", branch.get("outcomes", []))), 100)
        effects = _mermaid_text(" / ".join(str(value) for value in branch.get("effects", [])), 100)
        rows.append(f"| `{branch_id}` | {condition} | {condition} | {effects or '代码中未确认'} | {outcomes} |  |")
    for action in entry.agent_persistence:
        identifier = str(action.get("persistence_id", ""))
        label = _mermaid_text(f"{action.get('resource_name')}（{action.get('display_name')}）", 100)
        operation = _mermaid_text(str(action.get("operation_label", action.get("operation", ""))), 80)
        rows.append(f"|  | {label} | {operation} | {operation} | {label} | `{identifier}` |")
    for error in sorted(entry.errors, key=lambda item: item.line):
        condition = _mermaid_text(error.condition, 100)
        code = _mermaid_text(error.code, 60)
        write = "不写入持久化数据"
        if error.phase in {"async", "worker"}:
            write = "不确认持久化结果"
        rows.append(f"|  | {code} | {condition} | {write} | {code} |  |")
    review = _review(entry)
    if not rows:
        write = "无持久化写入"
        rows.append(f"|  | 成功 | {redact(review.outcome)} | {write} | 成功 |  |")
    return "\n".join([
        "### 分支矩阵",
        "",
        "| 分支编号 | 分支条件 | 数据读取与比较 | 数据写入与副作用 | 响应 | 持久化编号 |",
        "| --- | --- | --- | --- | --- | --- |",
        *rows,
    ])


def _entry_intro(entry: EntryPoint) -> str:
    """Objective trigger description kept separate from business prose."""
    if entry.kind in {"url", "webhook", "websocket", "sse"}:
        return f"入口描述：{entry.kind.upper()} {entry.identifier}"
    if entry.kind == "message":
        return f"入口描述：TOPIC {entry.identifier}"
    if entry.kind == "scheduled":
        return f"入口描述：XXL-JOB {entry.identifier}"
    if entry.kind == "worker":
        return "入口描述：异步任务提交"
    labels = {"cli": "CLI 命令", "file": "文件导入", "event": "事件监听", "rpc": "RPC 调用", "batch": "批处理"}
    return f"入口描述：{labels.get(entry.kind, entry.kind)}"


def _module_files(
    docs_root: Path,
    modules: list[str],
    previous: dict[str, Any],
    preferred: dict[str, str] | None = None,
) -> dict[str, str]:
    def safe_filename(value: object) -> bool:
        raw = str(value or "").replace("\\", "/")
        path = Path(raw)
        return bool(raw) and path.suffix.lower() == ".md" and not path.is_absolute() and ".." not in path.parts

    old = {
        str(item.get("name")): str(item.get("file"))
        for item in previous.get("modules", [])
        if isinstance(item, dict) and safe_filename(item.get("file"))
    }
    used = set(old.values())
    result: dict[str, str] = {}
    for index, module in enumerate(sorted(modules)):
        if preferred and _is_chinese_module_filename(preferred.get(module)):
            result[module] = preferred[module]
            used.add(preferred[module])
            continue
        if module in old and _is_chinese_module_filename(old[module]):
            result[module] = old[module]
            continue
        candidate = _chinese_module_filename(index, module)
        while candidate in used:
            index += 1
            candidate = _chinese_module_filename(index, module)
        used.add(candidate)
        result[module] = candidate
    return result


def _read_index(docs_root: Path) -> dict[str, Any]:
    path = docs_root / "biz-flow-index.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _markdown_entry_sections(docs_root: Path, index: dict[str, Any]) -> dict[str, str]:
    """Read prior generated entry sections without treating prose as code facts."""
    sections: dict[str, str] = {}
    for module in index.get("modules", []):
        if not isinstance(module, dict):
            continue
        filename = str(module.get("file", ""))
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            continue
        path = docs_root / filename
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        matches = list(re.finditer(r"<!-- biz-flow-entry:\s*([^>]+?)\s*-->", text))
        for index, match in enumerate(matches):
            entry_id = match.group(1).strip()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[entry_id] = text[match.start():end]
    return sections


def _fact_tokens(section: str) -> dict[str, set[str]]:
    """Extract comparable facts from a generated entry section.

    This intentionally reports category-level differences, not a fabricated
    semantic score.  A human can follow each category back to the old/new
    entry section and its source evidence.
    """
    diagram = "\n".join(
        block for block in re.findall(r"```mermaid\s*(.*?)```", section, flags=re.S)
    )
    participants = set(re.findall(r"^participant\s+\w+\s+as\s+(.+)$", diagram, flags=re.M))
    controls = set(re.findall(r"^(alt|opt|loop)\s+(.+)$", diagram, flags=re.M))
    errors = set(re.findall(r"^[-*]\s+`([^`]+)`：", section, flags=re.M))
    evidence = set(re.findall(r"`([^`\n]+:\d+)`", section))
    async_terms = {
        token for token in ("异步", "后台", "消息", "受理", "远端完成", "结果未知")
        if token in section
    }
    # Keep the business prose separate from source/version metadata.  These
    # lines are useful for detecting a changed rule without comparing line
    # numbers that naturally move between snapshots.
    prose = {
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("- ")
        and not any(marker in line for marker in ("证据：`", "源码", "入口类型", "主归属业务模块"))
    }
    return {
        "prose": prose,
        "controls": {f"{kind}:{text}" for kind, text in controls},
        "errors": errors,
        "participants": participants,
        "async": async_terms,
        "evidence": evidence,
    }


def compare_markdown_facts(
    docs_root: Path,
    previous_index: dict[str, Any],
    entries: list[EntryPoint],
) -> list[dict[str, Any]]:
    """Align prior Markdown by stable entry marker and report factual drift."""
    if not previous_index:
        return []
    old_sections = _markdown_entry_sections(docs_root, previous_index)
    diffs: list[dict[str, Any]] = []
    categories = ("prose", "controls", "errors", "participants", "async", "evidence")
    for entry in entries:
        old_section = old_sections.get(entry.entry_id)
        if old_section is None:
            diffs.append({
                "id": entry.entry_id, "category": "entry", "status": "added",
                "old": [], "new": [entry.identifier],
                "reason": "旧 Markdown 没有同一稳定入口标记，无法把旧正文对齐到当前入口。",
            })
            continue
        if "### 入口说明" not in old_section or "### 业务流程" not in old_section:
            diffs.append({
                "id": entry.entry_id,
                "category": "entry",
                "status": "unknown",
                "old": [],
                "new": [entry.identifier],
                "reason": "旧正文有入口标记但缺少标准章节，无法可靠比较业务事实。",
            })
        old_facts = _fact_tokens(old_section)
        new_facts = _fact_tokens(_entry_text(entry))
        for category in categories:
            old_values = old_facts[category]
            new_values = new_facts[category]
            if old_values == new_values:
                continue
            if not old_values:
                status = "added"
                reason = "当前入口新增该类可观察事实。"
            elif not new_values:
                status = "missing"
                reason = "旧正文存在该类事实，但当前正文没有对应表达；需核对是否删除或漏写。"
            elif old_values & new_values:
                status = "contradictory"
                reason = "旧新正文仅部分重合，存在规则、分支、参与方、错误、异步或证据差异。"
            else:
                status = "contradictory"
                reason = "旧新正文在该事实类别完全不一致，不能用版本号变化解释。"
            diffs.append({
                "id": entry.entry_id,
                "category": category,
                "status": status,
                "old": sorted(old_values),
                "new": sorted(new_values),
                "reason": reason,
            })
    current_ids = {entry.entry_id for entry in entries}
    for entry_id in sorted(set(old_sections) - current_ids):
        diffs.append({
            "id": entry_id, "category": "entry", "status": "missing", "old": [entry_id], "new": [],
            "reason": "旧 Markdown 中存在该入口标记，但当前源码入口集合没有对应入口。",
        })
    return diffs


def _require_contract(schema: dict[str, Any], value: dict[str, Any], name: str) -> None:
    errors = validate_schema(schema, value)
    if errors:
        raise ValueError(f"invalid generated {name}: {'; '.join(errors)}")


def _review_dict(review: EntryReview) -> dict[str, Any]:
    return {
        "id": review.review_id,
        "trigger": review.trigger,
        "purpose": review.purpose,
        "input": review.input,
        "outcome": review.outcome,
        "failure": review.failure,
        "status": review.status,
        "confirmed_by": review.confirmed_by,
        "steps": [
            {"kind": step.kind, "text": step.text, "source": step.source, "participant": step.participant}
            for step in review.steps
        ],
    }


def _review_from_dict(value: object, fallback: EntryPoint) -> EntryReview | None:
    if not isinstance(value, dict):
        return None
    steps = [
        FlowStep(
            str(step.get("kind", "action")), str(step.get("text", "代码中未确认")),
            str(step.get("source", f"{fallback.file}:{fallback.line}")), str(step.get("participant", "当前系统")),
        )
        for step in value.get("steps", []) if isinstance(step, dict)
    ]
    return EntryReview(
        str(value.get("id", fallback.entry_id)), str(value.get("trigger", fallback.caller)),
        str(value.get("purpose", "代码中未确认")), str(value.get("input", fallback.input_summary)),
        str(value.get("outcome", "代码中未确认")), str(value.get("failure", "代码中未确认")), steps,
        str(value.get("status", "draft")), str(value.get("confirmed_by", "")),
    )


def write_discovery(scan: ScanResult, docs_root: Path) -> tuple[Path, Path]:
    docs_root.mkdir(parents=True, exist_ok=True)
    suggestions: dict[str, list[str]] = {}
    for entry in scan.entries:
        parts = Path(entry.file).parts
        prefix = next((part for part in parts if part.lower() not in {"src", "main", "java", "kotlin", "python", "app", "api", "controller", "controllers", "service", "services"}), entry.module)
        suggestions.setdefault(prefix, []).append(entry.entry_id)
    discovery = {
        "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "source_fingerprint": scan.source_fingerprint,
        "effective_git": {
            "commit": scan.git.target,
            "branch": scan.git.branch,
            "workspace_dirty": scan.git.dirty,
            "includes_uncommitted_changes": scan.git.includes_uncommitted,
        },
        "languages": scan.languages,
        "frameworks": scan.frameworks,
        "source_files": scan.files,
        "entries": [
            {
                "id": entry.entry_id,
                "type": entry.kind,
                "identifier": entry.identifier,
                "handler": entry.handler,
                "source": f"{entry.file}:{entry.line}",
                "suggested_module": entry.module,
                "non_business_candidate": _non_business_candidate(entry),
                "core_capabilities": entry.functions,
                "errors": [_error_dict(error) for error in entry.errors],
            }
            for entry in scan.entries
        ],
        "candidate_entry_count": scan.candidate_entry_count,
        "confirmed_binding_count": scan.confirmed_binding_count,
        "confirmed_handler_count": scan.confirmed_handler_count,
        "unresolved": scan.unresolved,
        "module_suggestions": [
            {"name": name, "entry_ids": sorted(ids), "basis": "source package/path prefix; human confirmation required"}
            for name, ids in sorted(suggestions.items())
        ],
    }
    _require_contract(BIZ_FLOW_DISCOVERY_SCHEMA, discovery, "biz-flow discovery")
    discovery_path = write_json(docs_root / "biz-flow-discovery.json", discovery)
    module_map_path = docs_root / "biz-flow-modules.json"
    previous: dict[str, Any] = {}
    if module_map_path.is_file():
        try:
            loaded = json.loads(module_map_path.read_text(encoding="utf-8"))
            previous = loaded if isinstance(loaded, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            previous = {}
    old_owners = {
        str(entry_id): str(module.get("name"))
        for module in previous.get("modules", [])
        if isinstance(module, dict)
        for entry_id in module.get("entry_ids", [])
    }
    known_candidates = {entry.entry_id for entry in scan.entries}
    previous_exclusions = {
        str(item.get("candidate")): item
        for item in previous.get("exclusions", [])
        if isinstance(item, dict) and str(item.get("candidate", "")) in known_candidates
    }
    for entry in scan.entries:
        reason = _non_business_reason(entry)
        if reason and entry.entry_id not in previous_exclusions:
            previous_exclusions[entry.entry_id] = {
                "candidate": entry.entry_id,
                "reason": reason,
                "evidence": [f"{entry.file}:{entry.line}"],
            }
    excluded_ids = set(previous_exclusions)
    groups: dict[str, list[str]] = {}
    for entry in scan.entries:
        if entry.entry_id in excluded_ids:
            continue
        groups.setdefault(old_owners.get(entry.entry_id, entry.module), []).append(entry.entry_id)
    additional_ids = {
        str(item.get("id"))
        for item in previous.get("additional_entries", [])
        if isinstance(item, dict) and item.get("id")
    }
    for entry_id in additional_ids:
        if entry_id in excluded_ids:
            continue
        groups.setdefault(old_owners.get(entry_id, "公共能力"), []).append(entry_id)
    current_ids = ({entry.entry_id for entry in scan.entries} | additional_ids) - excluded_ids
    unchanged = (
        bool(previous)
        and previous.get("source_fingerprint") == scan.source_fingerprint
        and set(old_owners) == current_ids
    )
    previous_modules = {
        str(module.get("name")): module
        for module in previous.get("modules", [])
        if isinstance(module, dict) and module.get("name")
    }
    entry_lookup = {entry.entry_id: entry for entry in scan.entries}

    def draft_module_facts(name: str, entry_ids: list[str]) -> tuple[str, str, list[str], list[str]]:
        group = [entry_lookup[item] for item in entry_ids if item in entry_lookup]
        objects = sorted({
            token
            for entry in group
            for behavior in entry.behaviors
            if behavior.kind in {"持久化", "状态变化"}
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", behavior.statement)
            if token.lower() not in {"repository", "service", "status", "state"}
        })[:12]
        partners = sorted({
            "可见外部接口" if entry.has_external_call else ""
            for entry in group
        } | ({"消息/异步系统"} if any(entry.has_async for entry in group) else set()))
        partners = [item for item in partners if item]
        display_name = next(
            (
                entry.title.strip()
                for entry in group
                if entry.title.strip() and not entry.title_unresolved and re.search(r"[\u3400-\u9fff]", entry.title)
            ),
            _display(name),
        )
        responsibility = f"{display_name}：处理 {len(entry_ids)} 个已发现业务入口及其调用结果。"
        rationale = f"依据入口标识、源码包路径和调用关系归组；证据入口：{', '.join(entry_ids)}。"
        return rationale, responsibility, objects, partners
    previous_reviews = {
        str(review.get("id")): review
        for review in previous.get("entry_reviews", [])
        if isinstance(review, dict) and review.get("id")
    }

    def review_for(entry: EntryPoint) -> dict[str, Any]:
        previous_review = previous_reviews.get(entry.entry_id)
        if previous_review is None:
            return _review_dict(_review(entry))
        if previous.get("source_fingerprint") == scan.source_fingerprint:
            return previous_review
        refreshed = dict(previous_review)
        refreshed["status"] = "draft"
        refreshed["confirmed_by"] = ""
        return refreshed

    module_map = {
        "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "source_fingerprint": scan.source_fingerprint,
        "effective_git": scan.git.target,
        "confirmed": bool(previous.get("confirmed")) and unchanged,
        "entry_reviews": [
            review_for(entry)
            for entry in scan.entries
            if entry.entry_id not in excluded_ids
        ],
        "migrations": previous.get("migrations", []),
        "resolutions": previous.get("resolutions", []),
        "entry_overrides": previous.get("entry_overrides", []),
        "additional_entries": previous.get("additional_entries", []),
        "exclusions": list(previous_exclusions.values()),
        "modules": [
            {
                "name": name,
                "display_name": next(
                    (
                        entry.title.strip()
                        for entry in (entry_lookup[item] for item in entry_ids if item in entry_lookup)
                        if entry.title.strip() and not entry.title_unresolved and re.search(r"[\u3400-\u9fff]", entry.title)
                    ),
                    _display(name),
                ),
                "rationale": next((
                    str(module.get("rationale"))
                    for module in previous.get("modules", [])
                    if isinstance(module, dict) and module.get("name") == name
                ), draft_module_facts(name, entry_ids)[0]),
                "file": str(previous_modules.get(name, {}).get("file") or _chinese_module_filename(index, name)),
                "responsibility": str(previous_modules.get(name, {}).get("responsibility") or draft_module_facts(name, entry_ids)[1]),
                "objects": [str(value) for value in previous_modules.get(name, {}).get("objects", [])] or draft_module_facts(name, entry_ids)[2],
                "partners": [str(value) for value in previous_modules.get(name, {}).get("partners", [])] or draft_module_facts(name, entry_ids)[3],
                "questions": [str(value) for value in previous_modules.get(name, {}).get("questions", [])],
                "entry_ids": sorted(entry_ids),
            }
            for index, (name, entry_ids) in enumerate(sorted(groups.items()))
        ],
    }
    _require_contract(BIZ_FLOW_MODULE_MAP_SCHEMA, module_map, "biz-flow module map")
    draft_path = docs_root / "biz-flow-modules-draft.json"
    draft_stale = True
    if draft_path.is_file():
        try:
            draft_stale = json.loads(draft_path.read_text(encoding="utf-8")).get("source_fingerprint") != scan.source_fingerprint
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            draft_stale = True
    if draft_stale:
        write_json(draft_path, module_map)
    write_json(module_map_path, module_map)
    # Keep a complete parsed-evidence snapshot so a same-fingerprint resume can
    # rebuild the scan result without parsing the source tree again.
    write_json(docs_root / "biz-flow-evidence-cache.json", _cache_payload(scan))
    # The JSON objects above are an implementation detail of one invocation.
    # The durable review surface is Markdown; callers remove the transient
    # files before returning to the operator.
    overview = docs_root / "业务流程覆盖总览.md"
    previously_confirmed = False
    try:
        previously_confirmed = "<!-- devflow:module-confirmed -->" in overview.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        pass
    if overview.is_file():
        try:
            previously_confirmed = "模块划分状态：已确认" in overview.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            previously_confirmed = False
    status = "已确认" if module_map["confirmed"] or previously_confirmed else "待用户确认"
    existing_directives: list[str] = []
    try:
        existing_text = overview.read_text(encoding="utf-8") if overview.is_file() else ""
        existing_directives = re.findall(r"<!--\s*devflow:(?:module|exclude)\s+[^>]+-->", existing_text)
    except (OSError, UnicodeError):
        pass
    generated_directives = [
        f'<!-- devflow:module name="{module["name"]}" file="{module["file"]}" entries="{",".join(module["entry_ids"])}" -->'
        for module in module_map["modules"]
    ]
    generated_directives.extend(
        f'<!-- devflow:exclude id="{item["candidate"]}" reason="{item["reason"]}" evidence="{item["evidence"][0]}" -->'
        for item in module_map.get("exclusions", [])
        if isinstance(item, dict) and item.get("candidate") and item.get("reason") and item.get("evidence")
    )
    if existing_directives:
        existing_exclusion_ids = {
            match.group(1)
            for line in existing_directives
            for match in [re.match(r'<!--\s*devflow:exclude\s+id="([^"]+)"', line)]
            if match
        }
        missing_exclusion_directives = [
            line for line in generated_directives
            if line.startswith("<!-- devflow:exclude ")
            and (match := re.match(r'<!--\s*devflow:exclude\s+id="([^"]+)"', line))
            and match.group(1) not in existing_exclusion_ids
        ]
        machine_lines = [*existing_directives, *missing_exclusion_directives]
    else:
        machine_lines = generated_directives
    module_lines = [
        "## 业务模块划分",
        "",
        "| 模块标识 | 业务模块 | 职责 | 归属业务入口 | 文档文件 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for module in module_map["modules"]:
        ids = [str(value) for value in module["entry_ids"]]
        representative = ids if len(ids) <= 5 else [*ids[:3], f"入口 {len(ids)} 个"]
        module_lines.append(
            f"| `{module['name']}` | {module['display_name']} | {module['responsibility']} | "
            f"{'; '.join(f'`{value}`' for value in representative)} | `{module['file']}` |"
        )
    if len(module_lines) == 4:
        module_lines.append("| — | 暂无业务模块 | — | — | — |")
    exclusion_lines = [
        "",
        "## 建议忽略的入口",
        "",
        "| 入口标识 | 来源证据 | 建议 | 原因 |",
        "| --- | --- | --- | --- |",
    ]
    for item in module_map.get("exclusions", []):
        if isinstance(item, dict):
            evidence = "; ".join(str(value) for value in item.get("evidence", []))
            exclusion_lines.append(
                f"| `{item.get('candidate', '')}` | `{evidence}` | 忽略 | {item.get('reason', '')} |"
            )
    if len(exclusion_lines) == 5:
        exclusion_lines.append("| — | — | 保留 | 未发现建议忽略项。 |")
    confirmation_marker = "<!-- devflow:module-confirmed -->\n" if previously_confirmed else ""
    overview.write_text(
        "# 业务流程覆盖总览\n\n"
        f"Git 版本：`{scan.git.target}`\n\n"
        f"模块划分状态：{status}\n\n"
        + "\n".join(module_lines)
        + "\n"
        + "\n".join(exclusion_lines)
        + "\n\n"
        + "<!-- devflow:machine-map -->\n"
        + "\n".join(machine_lines)
        + "\n\n"
        "## 确认记录\n\n"
        "请在生成前确认模块边界。确认后将本节改为 `模块划分状态：已确认`，或使用 CLI 的显式确认选项。\n",
        encoding="utf-8",
    )
    if confirmation_marker:
        with overview.open("a", encoding="utf-8") as stream:
            stream.write(confirmation_marker)
    return discovery_path, module_map_path


def apply_module_map(scan: ScanResult, path: Path) -> list[str]:
    if not path.is_file():
        return [f"module map does not exist: {path}; run biz-flow discover"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"cannot read module map {path}: {exc}"]
    schema_errors = validate_schema(BIZ_FLOW_MODULE_MAP_SCHEMA, document)
    if schema_errors:
        return [f"invalid module map: {error}" for error in schema_errors]
    if not isinstance(document, dict) or document.get("confirmed") is not True:
        return [f"module map is not confirmed: {path}"]
    if document.get("source_fingerprint") != scan.source_fingerprint:
        return [
            "module map source fingerprint is stale; run biz-flow discover and review/confirm the new map"
        ]
    capability_owners: dict[str, str] = {}
    for entry in scan.entries:
        unique_functions: list[str] = []
        seen_functions: set[str] = set()
        for capability in entry.functions:
            if capability in seen_functions:
                continue
            seen_functions.add(capability)
            owner = capability_owners.setdefault(capability, entry.entry_id)
            if owner != entry.entry_id:
                return [f"core capability is assigned to multiple entries: {capability} ({owner}, {entry.entry_id})"]
            unique_functions.append(capability)
        entry.functions = unique_functions

    def source_parts(value: object, fallback: str = "") -> tuple[str, int] | None:
        file, separator, number = str(value or fallback).rpartition(":")
        if not separator or not number.isdigit() or not file:
            return None
        return file, int(number)

    def valid_source(value: object) -> bool:
        location = source_parts(value)
        return bool(
            location
            and location[0] in scan.files
            and 1 <= location[1] <= scan.source_lines.get(location[0], 0)
        )

    resolutions = {
        str(item.get("finding")): item
        for item in document.get("resolutions", [])
        if isinstance(item, dict)
        and str(item.get("finding", "")).strip()
        and str(item.get("resolution", "")).strip()
        and item.get("evidence")
    }
    resolution_findings = [
        str(item.get("finding")) for item in document.get("resolutions", []) if isinstance(item, dict)
    ]
    if len(resolution_findings) != len(set(resolution_findings)):
        return ["module map contains duplicate unresolved finding resolutions"]
    unknown_resolutions = set(resolutions) - set(scan.unresolved)
    if unknown_resolutions:
        return ["module map resolves findings not present in discovery: " + ", ".join(sorted(unknown_resolutions))]
    invalid_resolution_evidence = [
        str(evidence)
        for item in resolutions.values()
        for evidence in item.get("evidence", [])
        if not valid_source(evidence)
    ]
    if invalid_resolution_evidence:
        return ["resolution evidence is not a scanned source location: " + ", ".join(invalid_resolution_evidence)]
    critical_resolution_errors: list[str] = []
    critical_markers = (
        "unknown receiver type",
        "handler for ",
        "multiple possible definitions",
        "registered business entry could not be mapped",
        "business entry identifier is not statically resolvable",
    )
    for finding, item in resolutions.items():
        if not any(marker in finding for marker in critical_markers):
            continue
        missing = [field for field in ("path", "controls", "unknowns") if field not in item]
        if missing:
            critical_resolution_errors.append(
                f"resolution for critical finding requires structured fields: {finding} ({', '.join(missing)})"
            )
            continue
        path_values = item.get("path", [])
        invalid_path = [str(value) for value in path_values if not valid_source(value)]
        if not path_values or invalid_path:
            critical_resolution_errors.append(
                f"resolution for critical finding has invalid path evidence: {finding}"
            )
    if critical_resolution_errors:
        return critical_resolution_errors
    scan.unresolved = [finding for finding in scan.unresolved if finding not in resolutions]

    entry_by_id = {entry.entry_id: entry for entry in scan.entries}
    override_ids = [
        str(item.get("id")) for item in document.get("entry_overrides", []) if isinstance(item, dict)
    ]
    if len(override_ids) != len(set(override_ids)):
        return ["module map contains duplicate entry overrides"]
    unknown_overrides = {
        str(item.get("id"))
        for item in document.get("entry_overrides", [])
        if isinstance(item, dict) and str(item.get("id", "")) not in entry_by_id
    }
    if unknown_overrides:
        return ["module map overrides unknown entries: " + ", ".join(sorted(unknown_overrides))]
    invalid_override_evidence = [
        str(evidence.get("source", ""))
        for override in document.get("entry_overrides", [])
        if isinstance(override, dict)
        for field in ("errors", "behaviors")
        for evidence in override.get(field, [])
        if isinstance(evidence, dict) and not valid_source(evidence.get("source"))
    ]
    if invalid_override_evidence:
        return ["entry override evidence is not a scanned source location: " + ", ".join(invalid_override_evidence)]
    for override in document.get("entry_overrides", []):
        if not isinstance(override, dict) or str(override.get("id")) not in entry_by_id:
            continue
        entry = entry_by_id[str(override["id"])]
        for field in ("kind", "identifier", "handler", "caller", "input_summary", "title"):
            document_field = "type" if field == "kind" else field
            if str(override.get(document_field, "")).strip():
                setattr(entry, field, str(override[document_field]))
                if field == "title":
                    entry.title_unresolved = False
        if override.get("core_capabilities"):
            entry.functions = [str(value) for value in override["core_capabilities"]]
        if override.get("errors") is not None:
            entry.errors = [_error_from_dict(error, f"{entry.file}:{entry.line}") for error in override.get("errors", [])]
        if override.get("behaviors") is not None:
            entry.behaviors = [
                BehaviorEvidence(str(behavior.get("kind", "业务处理")), str(behavior.get("statement", "代码中未确认")), *(source_parts(behavior.get("source"), f"{entry.file}:{entry.line}") or (entry.file, entry.line)))
                for behavior in override.get("behaviors", []) if isinstance(behavior, dict)
            ]

    errors: list[str] = []
    for item in document.get("additional_entries", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", ""))
        location = source_parts(source, "")
        if not location:
            errors.append(f"additional entry {item.get('id', '')} has invalid source location")
            continue
        file, line = location
        if not valid_source(source):
            errors.append(f"additional entry {item.get('id', '')} source is not in the scanned source set: {source}")
            continue
        nested_sources = [
            str(evidence.get("source", ""))
            for field in ("errors", "behaviors")
            for evidence in item.get(field, [])
            if isinstance(evidence, dict) and not valid_source(evidence.get("source"))
        ]
        if nested_sources:
            errors.append(
                f"additional entry {item.get('id', '')} has invalid evidence: {', '.join(nested_sources)}"
            )
            continue
        entry_errors = [_error_from_dict(error, source) for error in item.get("errors", [])]
        behaviors = [
            BehaviorEvidence(str(behavior.get("kind", "业务处理")), str(behavior.get("statement", "代码中未确认")), *(source_parts(behavior.get("source"), source) or (file, line)))
            for behavior in item.get("behaviors", [])
            if isinstance(behavior, dict)
        ]
        scan.entries.append(EntryPoint(
            entry_id=str(item.get("id", "")), kind=str(item.get("type", "other")),
            identifier=str(item.get("identifier", "代码中未确认")), handler=str(item.get("handler", "代码中未确认")),
            file=file, line=line, module="", source=file,
            caller=str(item.get("caller", "代码中未确认")), input_summary=str(item.get("input_summary", "代码中未确认")),
            functions=[str(value) for value in item.get("core_capabilities", [])], errors=entry_errors, behaviors=behaviors,
        ))
    entry_by_id = {entry.entry_id: entry for entry in scan.entries}
    review_ids = [str(item.get("id")) for item in document.get("entry_reviews", []) if isinstance(item, dict)]
    if len(review_ids) != len(set(review_ids)):
        return ["module map contains duplicate entry reviews"]
    unknown_reviews = set(review_ids) - set(entry_by_id)
    if unknown_reviews:
        return ["module map reviews unknown entries: " + ", ".join(sorted(unknown_reviews))]
    excluded_review_ids = {
        str(item.get("candidate"))
        for item in document.get("exclusions", [])
        if isinstance(item, dict) and item.get("candidate")
    }
    expected_review_ids = set(entry_by_id) - excluded_review_ids
    missing_reviews = expected_review_ids - set(review_ids)
    stale_reviews = set(review_ids) - expected_review_ids
    if missing_reviews:
        return [
            "module map must contain exactly one confirmed entry review for every non-excluded entry; missing: "
            + ", ".join(sorted(missing_reviews))
        ]
    if stale_reviews:
        return ["module map contains reviews for excluded entries: " + ", ".join(sorted(stale_reviews))]
    for item in document.get("entry_reviews", []):
        if not isinstance(item, dict):
            continue
        entry = entry_by_id[str(item["id"])]
        review = _review_from_dict(item, entry)
        if review is None or not review.steps:
            return [f"entry review {entry.entry_id} must contain at least one step"]
        if review.status not in {"draft", "confirmed"}:
            return [f"entry review {entry.entry_id} has invalid status: {review.status}"]
        if review.status != "confirmed" or not review.confirmed_by.strip():
            return [f"entry review {entry.entry_id} is not explicitly human-confirmed"]
        placeholder_fields = _review_placeholders(review)
        if placeholder_fields:
            return [
                f"entry review {entry.entry_id} still contains generated placeholder facts: "
                + ", ".join(placeholder_fields)
            ]
        overlong = [
            field for field, value in {
                "trigger": review.trigger,
                "purpose": review.purpose,
                "input": review.input,
                "outcome": review.outcome,
                "failure": review.failure,
            }.items() if len(value) > 200
        ]
        if overlong:
            return [
                f"entry review {entry.entry_id} description fields exceed 200 characters: "
                + ", ".join(overlong)
            ]
        if len(_description(review)) > 200:
            return [f"entry review {entry.entry_id} combined description exceeds 200 characters"]
        long_points = [
            field for field, value in {
                "purpose": review.purpose, "input": review.input,
                "outcome": review.outcome, "failure": review.failure,
            }.items() if len(str(value).strip()) > 50
        ]
        if long_points:
            return [f"entry review {entry.entry_id} business description points exceed 50 characters: {', '.join(long_points)}"]
        invalid_steps = [step.source for step in review.steps if not valid_source(step.source)]
        if invalid_steps:
            return [f"entry review {entry.entry_id} has evidence outside scanned source: {', '.join(invalid_steps)}"]
        controls: list[str] = []
        for step in review.steps:
            if step.kind in {"alt", "opt", "loop"}:
                controls.append(step.kind)
            elif step.kind == "else" and (not controls or controls[-1] != "alt"):
                return [f"entry review {entry.entry_id} has an else step outside alt"]
            elif step.kind == "end":
                if not controls:
                    return [f"entry review {entry.entry_id} has an unmatched end step"]
                controls.pop()
        if controls:
            return [f"entry review {entry.entry_id} has unclosed control blocks: {', '.join(controls)}"]
        if review.review_id != entry.entry_id:
            return [f"entry review id does not match entry id: {review.review_id} != {entry.entry_id}"]
        entry.review = review
    excluded_ids: set[str] = set()
    known_candidates = {entry.entry_id for entry in scan.entries}
    exclusion_candidates = [
        str(item.get("candidate")) for item in document.get("exclusions", []) if isinstance(item, dict)
    ]
    if len(exclusion_candidates) != len(set(exclusion_candidates)):
        errors.append("module map contains duplicate exclusions")
    for exclusion in document.get("exclusions", []):
        if not isinstance(exclusion, dict) or not all(exclusion.get(name) for name in ("candidate", "reason", "evidence")):
            errors.append("each exclusion requires candidate, reason, and evidence")
        elif str(exclusion["candidate"]) not in known_candidates:
            errors.append(f"exclusion references an unknown candidate: {exclusion['candidate']}")
        elif not isinstance(exclusion["evidence"], list) or not exclusion["evidence"]:
            errors.append(f"exclusion {exclusion['candidate']} evidence must be a non-empty file:line list")
        elif any(not valid_source(value) for value in exclusion["evidence"]):
            errors.append(f"exclusion {exclusion['candidate']} has evidence outside scanned source")
        else:
            excluded_ids.add(str(exclusion["candidate"]))
    if excluded_ids:
        scan.entries = [entry for entry in scan.entries if entry.entry_id not in excluded_ids]
    scan.exclusions = [
        f"{item['candidate']}：{item['reason']}（证据：{', '.join(str(value) for value in item['evidence'])}）"
        for item in document.get("exclusions", [])
        if isinstance(item, dict) and all(item.get(name) for name in ("candidate", "reason", "evidence"))
    ]
    owners: dict[str, str] = {}
    rationales: dict[str, str] = {}
    module_names = [
        str(item.get("name")) for item in document.get("modules", []) if isinstance(item, dict)
    ]
    if len(module_names) != len(set(module_names)):
        errors.append("module map contains duplicate module names")
    module_files: dict[str, str] = {}
    for module in document.get("modules", []):
        if not isinstance(module, dict) or not str(module.get("name", "")).strip():
            errors.append("module map contains a module without a name")
            continue
        name = str(module["name"])
        if not module.get("entry_ids"):
            errors.append(f"module {name} has no entries")
        rationales[name] = str(module.get("rationale", ""))
        filename = str(module.get("file", "")).strip()
        if not filename:
            errors.append(f"module {name} has no stable file name")
        elif not filename.lower().endswith(".md"):
            errors.append(f"module {name} file must be Markdown: {filename}")
        elif not _is_chinese_module_filename(filename):
            errors.append(f"module {name} file must match NN-ChineseName.md: {filename}")
        elif (path.parent / filename).resolve().parent != path.parent.resolve():
            errors.append(f"module {name} file escapes docs root: {filename}")
        elif filename in module_files.values():
            errors.append(f"multiple modules use the same document file: {filename}")
        else:
            module_files[name] = filename
        rationale = str(module.get("rationale", "")).strip()
        if not rationale or rationale in {"代码中未确认", "待依据业务职责、对象、数据归属和调用关系确认"}:
            errors.append(f"module {name} has no boundary rationale")
        responsibility = str(module.get("responsibility", "")).strip()
        if not responsibility or responsibility in {"代码中未确认", "待人工确认"}:
            errors.append(f"module {name} has no confirmed responsibility")
        elif re.fullmatch(r"围绕 .+ 模块入口处理已确认的业务动作", responsibility):
            errors.append(f"module {name} still uses generated responsibility placeholder")
        questions = [str(value).strip() for value in module.get("questions", []) if str(value).strip()]
        if questions:
            errors.append(f"module {name} has unresolved ownership questions: {', '.join(questions)}")
        for entry_id in module.get("entry_ids", []):
            entry_id = str(entry_id)
            if entry_id in excluded_ids:
                errors.append(f"excluded entry {entry_id} must not appear in module {name}")
                continue
            if entry_id in owners:
                errors.append(f"entry {entry_id} belongs to multiple modules")
            owners[entry_id] = name
    active_entry_ids = {entry.entry_id for entry in scan.entries}
    for module in document.get("modules", []):
        if not isinstance(module, dict):
            continue
        name = str(module.get("name", ""))
        active_ids = set(str(value) for value in module.get("entry_ids", [])) & active_entry_ids
        if not active_ids:
            errors.append(f"module {name} has no active entries after exclusions")
    expected = {entry.entry_id for entry in scan.entries}
    if "" in expected:
        errors.append("additional entry is missing an id")
    duplicate_ids = {entry.entry_id for entry in scan.entries if sum(item.entry_id == entry.entry_id for item in scan.entries) > 1}
    if duplicate_ids:
        errors.append("duplicate entry ids: " + ", ".join(sorted(duplicate_ids)))
    missing = expected - set(owners)
    stale = set(owners) - expected
    if missing:
        errors.append("module map is missing entries: " + ", ".join(sorted(missing)))
    if stale:
        errors.append("module map contains stale entries: " + ", ".join(sorted(stale)))
    if errors:
        return errors
    for entry in scan.entries:
        entry.module = owners[entry.entry_id]
        entry.module_rationale = rationales[entry.module]
    return []


def build_index(
    scan: ScanResult,
    docs_root: Path,
    files: dict[str, str],
    *,
    comparison: str,
    old_commit: str | None = None,
    migrations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    modules = []
    for module in sorted(files):
        entries = [entry for entry in scan.entries if entry.module == module]
        modules.append({
            "name": module,
            "file": files[module],
            "rationale": entries[0].module_rationale if entries else "代码中未确认",
            "entry_ids": [entry.entry_id for entry in entries],
        })
    return {
        "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "source_fingerprint": scan.source_fingerprint,
        "effective_git": {
            "commit": scan.git.target,
            "branch": scan.git.branch,
            "workspace_dirty": scan.git.dirty,
            "includes_uncommitted_changes": scan.git.includes_uncommitted,
        },
        "comparison": comparison,
        "old_commit": old_commit,
        "languages": scan.languages,
        "frameworks": scan.frameworks,
        "modules": modules,
        "migrations": migrations or [],
        "entries": [
            {
                "id": entry.entry_id,
                "type": entry.kind,
                "identifier": entry.identifier,
                "handler": entry.handler,
                "module": entry.module,
                "source": f"{entry.file}:{entry.line}",
                "caller": entry.caller,
                "input_summary": entry.input_summary,
                "core_capabilities": entry.functions,
                "error_codes": entry.error_codes(),
                "errors": [_error_dict(error) for error in entry.errors],
                "behaviors": [
                    {"kind": behavior.kind, "statement": str(redact(behavior.statement)), "source": f"{behavior.file}:{behavior.line}"}
                    for behavior in entry.behaviors
                ],
                "review": _review_dict(_review(entry)),
            }
            for entry in scan.entries
        ],
        "counts": {
            "entries": len(scan.entries),
            "modules": len(modules),
            "error_codes": len({code for entry in scan.entries for code in entry.error_codes() if code != "代码中未确认"}),
            "by_type": {kind: sum(entry.kind == kind for entry in scan.entries) for kind in sorted({entry.kind for entry in scan.entries})},
        },
        "unresolved": scan.unresolved,
    }


def render_module(
    module: str,
    entries: list[EntryPoint],
    git: GitInfo,
    scan: ScanResult,
    *,
    comparison: str,
    module_meta: dict[str, Any] | None = None,
) -> str:
    module_meta = dict(module_meta or {})
    for key in ("objects", "partners", "questions"):
        if not isinstance(module_meta.get(key), list):
            module_meta[key] = []
    dirty = "；包含未提交变更" if git.includes_uncommitted else ""
    lines = [
        f"# {_display(module)}流程设计",
        "",
        f"> 生效 Git 版本：`{git.target}`{dirty}",
        ">",
        f"> 源码指纹：`{scan.source_fingerprint}`；来源类型：已实现源码与配置（不是未来方案）。",
        ">",
        f"> 覆盖说明：本文依据指定版本代码整理，覆盖本模块 {len(entries)} 个可确认业务入口；无法从代码确认的内容保留为“代码中未确认”。",
        f">",
        f"> 模块边界：{(entries[0].module_rationale if entries else '代码中未确认').rstrip('。')}。",
        f"> 模块职责：{str((module_meta or {}).get('responsibility', '代码中未确认')).rstrip('。')}。",
        f"> 核心对象：{', '.join(str(value) for value in (module_meta or {}).get('objects', [])) or '代码中未确认'}；关键协作方：{', '.join(str(value) for value in (module_meta or {}).get('partners', [])) or '代码中未确认'}。",
        f"> 待确认问题：{'；'.join(str(value) for value in (module_meta or {}).get('questions', [])) or '无'}。",
        f">",
        f"> 代码识别：语言 {', '.join(scan.languages) or '代码中未确认'}；框架 {', '.join(scan.frameworks) or '代码中未确认'}；更新模式 `{comparison}`。",
        "",
    ]
    # Keep generated module content compact: version metadata plus entry summaries and diagrams.
    lines = [
        f"<!-- biz-flow-module: {module} -->",
        f"# {_display(module)}",
        "",
    ]
    lines.extend(_entry_text(entry) for entry in entries)
    return "\n".join(lines).rstrip() + "\n"


def _update_version_only(path: Path, git: GitInfo) -> None:
    path.write_text(_version_only_text(path, git), encoding="utf-8")


def _version_only_text(path: Path, git: GitInfo) -> str:
    canonical = path.read_text(encoding="utf-8")
    cleaned = re.sub(r"^>.*Git.*`[0-9a-fA-F]{7,64}`.*\n?", "", canonical, flags=re.MULTILINE)
    if cleaned != canonical:
        return redact(cleaned)
    updated = re.sub(
        r"^> 生效 Git 版本：\s*`[^`]+`.*$",
        f"> 生效 Git 版本：`{git.target}`" + ("；包含未提交变更" if git.includes_uncommitted else ""),
        canonical,
        count=1,
        flags=re.MULTILINE,
    )
    if updated != canonical:
        return redact(updated)
    text = path.read_text(encoding="utf-8")
    marker = "；包含未提交变更" if git.includes_uncommitted else ""
    replacement = f"> 生效 Git 版本：`{git.target}`{marker}"
    updated = re.sub(r"^> 生效 Git 版本：.*$", replacement, text, count=1, flags=re.MULTILINE)
    return redact(updated if updated != text else text)


def _markdown_coverage(
    scan: ScanResult,
    index: dict[str, Any],
    docs_root: Path | None,
    module_filter: str | None = None,
) -> dict[str, Any]:
    if docs_root is None:
        return {
            "markdown_document_count": 0,
            "markdown_entry_count": 0,
            "markdown_missing_documents": [],
            "markdown_missing_entries": [],
            "markdown_stale_entries": [],
            "markdown_missing_error_codes": [],
            "markdown_missing_error_evidence": [],
            "markdown_stale_error_evidence": [],
            "markdown_diagram_mismatches": [],
            "markdown_fact_mismatches": [],
            "markdown_version_mismatches": [],
        }
    entries = [
        item for item in index.get("entries", [])
        if isinstance(item, dict) and (not module_filter or item.get("module") == module_filter)
    ]
    modules = [
        item for item in index.get("modules", [])
        if isinstance(item, dict) and (not module_filter or item.get("name") == module_filter)
    ]
    text_by_module: dict[str, str] = {}
    missing_documents: list[str] = []
    for module in modules:
        filename = str(module.get("file", ""))
        path = docs_root / filename
        if not filename or not path.is_file():
            missing_documents.append(filename or str(module.get("name", "unknown")))
            continue
        try:
            text_by_module[str(module.get("name", ""))] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            missing_documents.append(filename)
    missing_entries: list[str] = []
    stale_entries: list[str] = []
    missing_error_codes: list[str] = []
    missing_error_evidence: list[str] = []
    stale_error_evidence: list[str] = []
    diagram_mismatches: list[str] = []
    fact_mismatches: list[str] = []
    version_mismatches: list[str] = []
    marker = re.compile(r"^<!-- biz-flow-entry: (.+) -->\s*$", re.MULTILINE)
    for module in modules:
        name = str(module.get("name", ""))
        text = text_by_module.get(name, "")
        module_entries = [entry for entry in entries if str(entry.get("module")) == name]
        matches = list(marker.finditer(text))
        if matches:
            module_preamble = text[:matches[0].start()]
            for line in module_preamble.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("<!-- biz-flow-module:"):
                    continue
                if re.match(r"^>\s+.*Git", stripped) or stripped.startswith("# "):
                    continue
                fact_mismatches.append(f"{name}:content-outside-entry-sections")
                break
        sections = {
            match.group(1): text[match.start():matches[position + 1].start() if position + 1 < len(matches) else len(text)]
            for position, match in enumerate(matches)
        }
        expected_ids = {str(entry.get("id", "")) for entry in module_entries}
        stale_entries.extend(sorted(set(sections) - expected_ids))
        if any(
            section.count("sequenceDiagram") < 1
            for section in sections.values()
        ) or (module_entries and not sections):
            diagram_mismatches.append(name)
        for entry in module_entries:
            entry_id = str(entry.get("id", ""))
            source = str(entry.get("source", ""))
            identifier = str(entry.get("identifier", ""))
            section = sections.get(entry_id, "")
            if not section or identifier not in section:
                missing_entries.append(entry_id)
            if "源代码证据" in section:
                fact_mismatches.append(f"{entry_id}:source-evidence-section-not-allowed")
            for matrix_error in _validate_branch_matrix(section):
                fact_mismatches.append(f"{entry_id}:{matrix_error}")
            if section and section.count("sequenceDiagram") < 1:
                diagram_mismatches.append(f"{entry_id}:mermaid:missing-diagram")
            review = entry.get("review", {})
            if isinstance(review, dict):
                steps = review.get("steps", [])
                diagram_matches = list(re.finditer(r"```mermaid\s*(.*?)```", section, re.DOTALL))
                diagrams = [match.group(1) for match in diagram_matches]
                diagram = "\n".join(diagrams)
                if diagram_matches:
                    preamble = section[:diagram_matches[0].start()]
                    preamble_lines = [
                        line.strip() for line in preamble.splitlines()
                        if line.strip() and not line.startswith("<!--") and not line.startswith("# ") and not line.startswith("## ")
                    ]
                    if not preamble_lines or not preamble_lines[0].startswith(("入口类型", "入口描述")):
                        fact_mismatches.append(f"{entry_id}:missing-entry-introduction")
                    business_points = [line[2:].strip() for line in preamble_lines[1:] if line.startswith("- ")]
                    if len(business_points) != len(preamble_lines) - 1:
                        fact_mismatches.append(f"{entry_id}:summary-shape")
                    if any(len(point) > 50 for point in business_points):
                        fact_mismatches.append(f"{entry_id}:business-description-over-50")
                    trailing = section[diagram_matches[-1].end():].strip()
                    if trailing and not re.match(r"^###\s+.*分支矩阵\s*(?:\n|$)", trailing):
                        fact_mismatches.append(f"{entry_id}:content-after-diagram")
                if diagram:
                    for block in diagrams:
                        diagram_mismatches.extend(
                            f"{entry_id}:mermaid:{problem}" for problem in _validate_mermaid(block)
                        )
                    if not re.search(r"(?:-->>|->>)P0:", diagram):
                        diagram_mismatches.append(f"{entry_id}:mermaid:missing-entry-result")
                    if entry.get("errors") and not re.search(r"业务失败|失败|异常", diagram):
                        diagram_mismatches.append(f"{entry_id}:mermaid:missing-failure-path")
                    result_messages = [
                        line for line in diagram.splitlines()
                        if line.startswith("P1-->>P0:")
                    ]
                    error_prefixes = {
                        f"alt {str(error.get('code', ''))}："
                        for error in entry.get("errors", [])
                        if isinstance(error, dict)
                    }
                    error_prefixes.update(
                        f"{kind} {str(error.get('code', ''))}:"
                        for error in entry.get("errors", [])
                        if isinstance(error, dict)
                        for kind in ("alt", "opt")
                    )
                    diagram_controls = [
                        line.split(" ", 1)[0]
                        for line in diagram.splitlines()
                        if line.startswith(("alt ", "opt ", "loop "))
                        and not any(line.startswith(prefix) for prefix in error_prefixes)
                    ]
                    for line in diagram.splitlines():
                        if line.startswith(("alt ", "else ")) and not any(
                            line.startswith(prefix) for prefix in error_prefixes
                        ) and not re.search(r"\bbranch\s+\d+\b|\bB-[A-Za-z0-9-]+", line, re.I):
                            diagram_mismatches.append(f"{entry_id}:mermaid:unlabelled-branch")
                    review_controls = [
                        str(step.get("kind"))
                        for step in steps
                        if isinstance(step, dict) and step.get("kind") in {"alt", "opt", "loop"}
                    ]
                    # Branch IDs and the independent inventory are authoritative
                    # for the new protocol; legacy review-step counts are not.
                    live_entry = next((candidate for candidate in scan.entries if candidate.entry_id == entry_id), None)
                    if live_entry is not None:
                        required_alts, required_loops, required_elses = _required_control_counts(scan, live_entry)
                        actual_alts = sum(line.startswith("alt ") for line in diagram.splitlines())
                        actual_loops = sum(line.startswith("loop ") for line in diagram.splitlines())
                        actual_elses = sum(line.startswith("else ") for line in diagram.splitlines())
                        if actual_alts < required_alts:
                            diagram_mismatches.append(f"{entry_id}:mermaid:missing-source-branches")
                        if actual_loops < required_loops:
                            diagram_mismatches.append(f"{entry_id}:mermaid:missing-source-loops")
                        if actual_elses < required_elses:
                            diagram_mismatches.append(f"{entry_id}:mermaid:missing-source-else-branches")
                    if "Note over " not in diagram:
                        diagram_mismatches.append(f"{entry_id}:mermaid:missing-note")
                    for message in diagram.splitlines():
                        if re.match(r"P1-->>P0:", message) and not message.split(":", 1)[1].strip():
                            diagram_mismatches.append(f"{entry_id}:mermaid:empty-entry-result")
                    for error in entry.get("errors", []):
                        if not isinstance(error, dict):
                            continue
                        code = str(error.get("code", ""))
                        expected_kind = "opt" if str(error.get("phase", "")) in {"async", "worker"} else "alt"
                        if code and not any(line.startswith(f"{expected_kind} {code}") for line in diagram.splitlines()):
                            diagram_mismatches.append(f"{entry_id}:mermaid:error-control:{code}")
                        consequence = str(redact(error.get("consequence", ""))).replace("代码中未确认", "未见源码证据").replace("\n", " ")[:100]
                        if code and code != "代码中未确认" and code not in diagram:
                            diagram_mismatches.append(f"{entry_id}:mermaid:error-code:{code}")
                        if consequence and consequence not in diagram:
                            diagram_mismatches.append(f"{entry_id}:mermaid:error-consequence:{code}")
                        condition = _mermaid_text(error.get("condition", ""), 100)
                        if condition and condition not in diagram:
                            diagram_mismatches.append(f"{entry_id}:mermaid:error-condition:{code}")
                else:
                    diagram_mismatches.append(f"{entry_id}:missing-mermaid")
                shape = re.sub(r"```mermaid\s*.*?```", "", section, flags=re.S)
                shape_lines = [line.strip() for line in shape.splitlines() if line.strip()]
                extra_sections = [
                    line for line in shape_lines
                    if line.startswith("###") and "分支矩阵" not in line
                ]
                if extra_sections:
                    fact_mismatches.append(f"{entry_id}:extra-markdown-section")
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    if step.get("kind") == "end":
                        continue
                    expected_text = _mermaid_text(step.get("text", ""), 120)
                    if expected_text and expected_text not in diagram:
                        diagram_mismatches.append(f"{entry_id}:step:{expected_text}")
            for code in entry.get("error_codes", []):
                if str(code) != "代码中未确认" and str(code) not in section:
                    missing_error_codes.append(f"{entry_id}:{code}")
            expected_errors: set[tuple[str, str, str, str, str, str, str, str]] = set()
            for error in entry.get("errors", []):
                if isinstance(error, dict):
                    code = str(error.get("code", ""))
                    evidence = str(error.get("source", ""))
                    condition = str(redact(error.get("condition", "")))
                    expected_errors.add((
                        code,
                        condition,
                        evidence,
                        str(redact(error.get("phase", ""))),
                        str(redact(error.get("capture_boundary", ""))),
                        str(redact(error.get("propagation", ""))),
                        str(redact(error.get("consequence", ""))),
                        str(redact(error.get("recovery", ""))),
                    ))
                    # Source evidence is authoritative in the JSON index. Markdown
                    # intentionally contains only the summary and diagram.
            documented_errors = {
                (
                    match.group("code"), match.group("condition").strip(), match.group("source"),
                    match.group("phase").strip(), match.group("capture").strip(),
                    match.group("propagation").strip(), match.group("consequence").strip(),
                    match.group("recovery").strip(),
                )
                for match in re.finditer(
                    r"^- `(?P<code>[^`]+)`：(?P<condition>.*?)（阶段：(?P<phase>.*?)；捕获：(?P<capture>.*?)；传播：(?P<propagation>.*?)；后果：(?P<consequence>.*?)；恢复：(?P<recovery>.*?)；证据：`(?P<source>[^`]+)`）$",
                    section,
                    re.MULTILINE,
                )
            }
            # Do not require diagnostic evidence prose in the compact document.
    return {
        "markdown_document_count": len(text_by_module),
        "markdown_entry_count": len(entries) - len(missing_entries),
        "markdown_missing_documents": sorted(dict.fromkeys(missing_documents)),
        "markdown_missing_entries": sorted(dict.fromkeys(missing_entries)),
        "markdown_stale_entries": sorted(dict.fromkeys(stale_entries)),
        "markdown_missing_error_codes": sorted(dict.fromkeys(missing_error_codes)),
        "markdown_missing_error_evidence": sorted(dict.fromkeys(missing_error_evidence)),
        "markdown_stale_error_evidence": sorted(dict.fromkeys(stale_error_evidence)),
        "markdown_diagram_mismatches": sorted(dict.fromkeys(diagram_mismatches)),
        "markdown_fact_mismatches": sorted(dict.fromkeys(fact_mismatches)),
        "markdown_version_mismatches": sorted(dict.fromkeys(version_mismatches)),
    }


def coverage(
    scan: ScanResult,
    index: dict[str, Any],
    docs_root: Path | None = None,
    module_filter: str | None = None,
) -> dict[str, Any]:
    code_entries = [entry for entry in scan.entries if not module_filter or entry.module == module_filter]
    index_entries = [
        item for item in index.get("entries", [])
        if isinstance(item, dict) and (not module_filter or item.get("module") == module_filter)
    ]
    code_ids = {entry.entry_id for entry in code_entries}
    documented_ids = {str(item.get("id")) for item in index_entries}
    code_errors = {
        (
            entry.entry_id, error.code, str(redact(error.condition)), f"{error.file}:{error.line}",
            str(redact(error.phase)), str(redact(error.capture_boundary)),
            str(redact(error.propagation)), str(redact(error.consequence)), str(redact(error.recovery)),
        )
        for entry in code_entries
        for error in entry.errors
        if error.code != "代码中未确认"
    }
    documented_errors = {
        (
            str(item.get("id")), str(error.get("code")), str(error.get("condition")), str(error.get("source")),
            str(error.get("phase")), str(error.get("capture_boundary")), str(error.get("propagation")),
            str(error.get("consequence")), str(error.get("recovery")),
        )
        for item in index_entries
        for error in item.get("errors", [])
        if isinstance(error, dict) and str(error.get("code")) != "代码中未确认"
    }
    code_codes = {item[1] for item in code_errors}
    documented_codes = {item[1] for item in documented_errors}
    missing_error_evidence = sorted(":".join(item) for item in code_errors - documented_errors)
    stale_error_evidence = sorted(":".join(item) for item in documented_errors - code_errors)
    result = {
        "code_entry_count": len(code_ids),
        "documented_entry_count": len(documented_ids),
        "missing_entries": sorted(code_ids - documented_ids),
        "stale_entries": sorted(documented_ids - code_ids),
        "code_error_code_count": len(code_codes),
        "documented_error_code_count": len(documented_codes),
        "missing_error_codes": sorted(code_codes - documented_codes),
        "stale_error_codes": sorted(documented_codes - code_codes),
        "missing_error_evidence": missing_error_evidence,
        "stale_error_evidence": stale_error_evidence,
        "unique_module_count": len({entry.module for entry in code_entries}),
    }
    result.update(_markdown_coverage(scan, index, docs_root, module_filter))
    return result


def write_artifacts(
    scan: ScanResult,
    docs_root: Path,
    *,
    comparison: str,
    old_commit: str | None,
    changed: dict[str, Any],
    module_filter: str | None = None,
    on_module_write: Callable[[str, Path], None] | None = None,
    module_writer: Callable[[str, Path, str], None] | None = None,
    module_contents: dict[str, str] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    docs_root.mkdir(parents=True, exist_ok=True)
    previous = _read_index(docs_root)
    modules = sorted({entry.module for entry in scan.entries})
    preferred: dict[str, str] = {}
    module_metadata: dict[str, Any] = {}
    mapping: dict[str, Any] = {}
    module_map_path = docs_root / "biz-flow-modules.json"
    if module_map_path.is_file():
        try:
            mapping = json.loads(module_map_path.read_text(encoding="utf-8"))
            for item in mapping.get("modules", []):
                if isinstance(item, dict) and item.get("name"):
                    name = str(item["name"])
                    preferred[name] = str(item.get("file", ""))
                    module_metadata[name] = item
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    files = _module_files(docs_root, modules, previous, preferred)
    # Capture old Markdown before any module file is rewritten so the
    # comparison artifact describes the actual migration, not the new output.
    semantic_diffs = compare_markdown_facts(
        docs_root,
        previous,
        [entry for entry in scan.entries if not module_filter or entry.module == module_filter],
    )
    for module, filename in files.items():
        if module_filter and module != module_filter:
            continue
        entries = [entry for entry in scan.entries if entry.module == module]
        path = docs_root / filename
        if module_contents is not None:
            rendered = module_contents[module]
        elif comparison == "version_only" and path.is_file():
            rendered = _version_only_text(path, scan.git)
        else:
            rendered = redact(render_module(module, entries, scan.git, scan, comparison=comparison, module_meta=module_metadata.get(module)))
        if module_writer is not None:
            module_writer(module, path, rendered)
        else:
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(rendered, encoding="utf-8")
            temporary.replace(path)
        if on_module_write is not None:
            on_module_write(module, path)
    stale_files = {
        str(item.get("file")).replace("\\", "/")
        for item in previous.get("modules", [])
        if isinstance(item, dict)
        and str(item.get("file", "")).replace("\\", "/").endswith(".md")
        and ".." not in Path(str(item.get("file", ""))).parts
        and not Path(str(item.get("file", ""))).is_absolute()
    } - set(files.values())
    for filename in (stale_files if not module_filter else ()):
        path = docs_root / filename
        if path.is_file():
            path.unlink()
    mapping_migrations = mapping.get("migrations", [])
    index = build_index(
        scan, docs_root, files, comparison=comparison, old_commit=old_commit, migrations=mapping_migrations,
    )
    _require_contract(BIZ_FLOW_INDEX_SCHEMA, index, "biz-flow index")
    index_path = write_json(docs_root / "biz-flow-index.json", index)
    ownership = {
            "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
            "source_fingerprint": scan.source_fingerprint,
            "confirmed": True,
            "entries": [
                {"id": entry.entry_id, "module": entry.module, "file": files[entry.module]}
                for entry in scan.entries
            ],
        }
    _require_contract(BIZ_FLOW_OWNERSHIP_SCHEMA, ownership, "biz-flow ownership")
    write_json(docs_root / "biz-flow-ownership.json", ownership)
    migrations = {
            "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
            "source_fingerprint": scan.source_fingerprint,
            "migrations": mapping_migrations,
        }
    _require_contract(BIZ_FLOW_MIGRATIONS_SCHEMA, migrations, "biz-flow migrations")
    write_json(docs_root / "biz-flow-migrations.json", migrations)
    comparison_artifact = {
            "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
            "source_fingerprint": scan.source_fingerprint,
            "comparison": changed.get("comparison", comparison),
            "entry_alignment": {
                "added": changed.get("added_entries", []),
                "updated": changed.get("updated_entries", []),
                "deleted": changed.get("deleted_entries", []),
            },
            "version_only_documents": changed.get("version_only_documents", []),
            "business_changed_documents": changed.get("business_changed_documents", modules),
            "changed_paths": changed.get("business_changed_paths", changed.get("changed_paths", [])),
            "comparison_error": changed.get("comparison_error"),
            "semantic_diffs": semantic_diffs,
            "fact_diffs": [
                {
                    "id": entry.entry_id,
                    "changes": [field for field, old_value, new_value in (
                        ("type", old.get("type"), entry.kind),
                        ("identifier", old.get("identifier"), entry.identifier),
                        ("handler", old.get("handler"), entry.handler),
                        ("module", old.get("module"), entry.module),
                        ("errors", old.get("errors", []), [_error_dict(error) for error in entry.errors]),
                        ("behaviors", old.get("behaviors", []), [
                            {"kind": item.kind, "statement": str(redact(item.statement)), "source": f"{item.file}:{item.line}"}
                            for item in entry.behaviors
                        ]),
                    ) if old_value != new_value]
                }
                for entry in scan.entries
                for old in previous.get("entries", [])
                if isinstance(old, dict) and old.get("id") == entry.entry_id
            ],
        }
    _require_contract(BIZ_FLOW_COMPARISON_SCHEMA, comparison_artifact, "biz-flow comparison")
    write_json(docs_root / "biz-flow-comparison.json", comparison_artifact)
    evidence_cache = _cache_payload(scan)
    _require_contract(BIZ_FLOW_EVIDENCE_CACHE_SCHEMA, evidence_cache, "biz-flow evidence cache")
    write_json(docs_root / "biz-flow-evidence-cache.json", evidence_cache)
    dependency_graph = {
            "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
            "source_fingerprint": scan.source_fingerprint,
            "nodes": [
                {"entry": entry.entry_id, "functions": entry.functions}
                for entry in scan.entries
            ],
            "shared_sources": sorted({
                function
                for entry in scan.entries
                for function in entry.functions
                if ":" in function
            }),
        }
    _require_contract(BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA, dependency_graph, "biz-flow dependency graph")
    write_json(docs_root / "biz-flow-dependency-graph.json", dependency_graph)
    reported_entries = [entry for entry in scan.entries if not module_filter or entry.module == module_filter]
    reported_modules = sorted({entry.module for entry in reported_entries})
    reported_ids = {entry.entry_id for entry in reported_entries}
    report_coverage = coverage(scan, index, docs_root, module_filter)
    confirmed_review_ids = {
        str(item.get("id"))
        for item in index.get("entries", [])
        if isinstance(item, dict)
        and (not module_filter or item.get("module") == module_filter)
        and isinstance(item.get("review"), dict)
        and item["review"].get("status") == "confirmed"
        and item["review"].get("confirmed_by")
    }
    completed_entry_count = len(confirmed_review_ids) - len(
        set(report_coverage["markdown_missing_entries"])
    )
    pending_review_count = len([
        item for item in index.get("entries", [])
        if isinstance(item, dict)
        and (not module_filter or item.get("module") == module_filter)
        and (not isinstance(item.get("review"), dict)
             or item["review"].get("status") != "confirmed"
             or not item["review"].get("confirmed_by"))
    ])
    report = {
        "schema_version": int(BIZ_FLOW_SCHEMA_VERSION),
        "source_fingerprint": scan.source_fingerprint,
        "effective_git": index["effective_git"],
        "project": str(scan.root),
        "scope": module_filter,
        "languages": scan.languages,
        "frameworks": scan.frameworks,
        "module_count": len(reported_modules),
        "document_count": len(reported_modules),
        "url_entry_count": sum(entry.kind in {"url", "webhook", "websocket", "sse"} for entry in reported_entries),
        "scheduled_task_count": sum(entry.kind == "scheduled" for entry in reported_entries),
        "message_consumer_count": sum(entry.kind == "message" for entry in reported_entries),
        "other_entry_count": sum(entry.kind not in {"url", "webhook", "websocket", "sse", "scheduled", "message"} for entry in reported_entries),
        "active_error_code_count": len({code for entry in reported_entries for code in entry.error_codes() if code != "代码中未确认"}),
        "entry_count": len(reported_entries),
        "candidate_entry_count": scan.candidate_entry_count,
        "confirmed_binding_count": scan.confirmed_binding_count,
        "confirmed_handler_count": scan.confirmed_handler_count,
        "completed_entry_count": max(0, completed_entry_count),
        "excluded_entry_count": len(scan.exclusions),
        "pending_review_count": pending_review_count,
        "added_entries": [value for value in changed.get("added_entries", []) if value in reported_ids],
        "updated_entries": [value for value in changed.get("updated_entries", []) if value in reported_ids],
        "deleted_entries": changed.get("deleted_entries", []) if not module_filter else [],
        "version_only_documents": [value for value in changed.get("version_only_documents", []) if value in reported_modules],
        "business_changed_documents": [value for value in changed.get("business_changed_documents", modules) if value in reported_modules],
        "comparison": changed.get("comparison", comparison),
        "comparison_error": changed.get("comparison_error"),
        "exclusions": scan.exclusions,
        "unresolved": scan.unresolved,
        "coverage": report_coverage,
        "index_path": str(index_path),
    }
    _require_contract(BIZ_FLOW_REPORT_SCHEMA, report, "biz-flow report")
    report_path = write_json(docs_root / "biz-flow-report.json", report)
    return index_path, report_path, report
