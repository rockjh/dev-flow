"""Registration identity and business ownership; behavior belongs to fact adapters."""

from __future__ import annotations

import ast
import configparser
from difflib import SequenceMatcher
import hashlib
import json
import os
import subprocess
import tempfile
import sys
import time
import re
import textwrap
import tomllib
from pathlib import Path
from typing import Callable

from .git import source_view, git_info, _run
from .models import EntryPoint, FunctionInfo, ScanResult
from .paths import is_alias, normal_path

_LOCAL_SYNTAX_NAMES = {"if", "else", "catch", "try", "for", "while", "input", "return"}


def _package_name(relative: str, text: str) -> str:
    match = re.search(r"^\s*package\s+([\w.]+)", text, re.M)
    if match:
        return match.group(1)
    parts = Path(relative).with_suffix("").parts[:-1]
    return ".".join(part for part in parts if part not in {"src", "main", "java", "kotlin", "python"})


def _capability_id(language: str, relative: str, function: FunctionInfo, text: str = "") -> str:
    package = _package_name(relative, text)
    if function.owner:
        qualified_owner = f"{package}.{function.owner}" if package else function.owner
    else:
        module_parts = Path(relative).with_suffix("").parts
        module = ".".join(part for part in module_parts if part not in {"src", "main", "java", "kotlin", "python"})
        qualified_owner = module or package or Path(relative).stem
    signature = function.signature or function.name
    return f"{language.lower()}:{qualified_owner}#{signature}"


EXCLUDED_DIRS = {
    ".git", ".idea", ".venv", "venv", "env", ".tox", ".nox", "node_modules", "dist", "build", "target",
    "vendor", "__pycache__", ".gradle", ".mvn", ".pytest_cache",
    # Tool-owned worktrees and editor/agent state are never source evidence.
    ".worktrees", ".git-worktrees", ".trae", ".dltk", ".codex", ".agents", ".idea-workspace",
    ".vscode", ".fleet", ".cursor", ".windsurf", ".clinerules", ".devflow", ".local",
}
_EXCLUDED_DIRS_CASEFOLD = {item.casefold() for item in EXCLUDED_DIRS}
EXTENSIONS = {
    ".py": "Python", ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".js": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".cs": "C#", ".rb": "Ruby",
    ".php": "PHP", ".rs": "Rust", ".proto": "Protocol Buffers", ".graphql": "GraphQL",
    ".graphqls": "GraphQL", ".scala": "Scala", ".groovy": "Groovy", ".dart": "Dart",
    ".ex": "Elixir", ".exs": "Elixir", ".fs": "F#", ".fsx": "F#", ".lua": "Lua",
    ".c": "C", ".cc": "C++", ".cpp": "C++", ".h": "C/C++", ".hpp": "C++",
    ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
}

# Statically registered trigger adapters. Discovery may support many source
# languages, but presentation is normalized only through these explicit
# adapter records; there is no runtime plugin or framework guessing.
TRIGGER_ADAPTERS = {
    "url": "http",
    "webhook": "webhook",
    "websocket": "websocket",
    "sse": "sse",
    "rpc": "rpc",
    "message": "message",
    "scheduled": "scheduled",
    "event": "event",
    "cli": "cli",
    "file": "file",
    "batch": "batch",
    "worker": "worker",
}


def _trigger_summary(entry: EntryPoint) -> str:
    labels = {
        "url": "HTTP", "webhook": "Webhook", "websocket": "WebSocket", "sse": "SSE",
        "rpc": "RPC", "message": "消息", "scheduled": "定时任务", "event": "事件",
        "cli": "命令行", "file": "文件", "batch": "批处理", "worker": "异步任务",
    }
    adapter = TRIGGER_ADAPTERS.get(entry.kind)
    return f"{labels.get(entry.kind, entry.kind)}：{entry.identifier}" if adapter else f"{entry.kind}：{entry.identifier}"


def _name_tokens(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", value)]


def _inferred_business_name(entry: EntryPoint) -> str:
    """Keep source wording when no explicit business description exists."""
    return entry.title.strip() or f"业务入口：{entry.handler}（{entry.identifier}）"


def _business_name(entry: EntryPoint) -> str:
    if entry.kind in {"message", "scheduled"} and entry.module_label:
        # 任务入口的模板方法常只描述审计上下文；业务动作来自注册处理器类型说明。
        return re.sub(r"(?:定时任务|接口)$", "", entry.module_label).replace("恢复任务", "恢复").replace("回收任务", "回收")[:120]
    if entry.title and not entry.title_unresolved and re.search(r"[\u3400-\u9fff]", entry.title):
        return re.sub(r"^client:[A-Za-z0-9_-]+\s*", "", entry.title.strip())[:120]
    inferred = _inferred_business_name(entry)
    return inferred[:120] if inferred else "待确认"


def _exclusion_reason(entry: EntryPoint) -> str | None:
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
    if "/sdk/" in relative and re.search(r"(?:api|contract)$", filename):
        return "SDK 接口契约声明，不是服务端运行时业务处理入口。"
    if entry.kind == "file" and entry.identifier == "代码中未确认":
        return "静态扫描识别到文件处理辅助调用，但源码没有独立文件触发注册。"
    return None
CONFIG_NAMES = {
    "application.yml", "application.yaml", "application.properties", "bootstrap.yml", "bootstrap.yaml",
    "build.gradle", "build.gradle.kts", "package.json", "pom.xml", "pyproject.toml", "routes.rb",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json", "application.json",
    "routes.json", "config.json", "web.xml", "setup.cfg", "setup.py",
}
CONFIG_SUFFIXES = {".properties", ".toml", ".xml", ".yaml", ".yml"}
# Python has syntax-aware function/error traversal.  Other declared languages
# still get conservative registration candidates, but their call/type/CFG
# resolution is heuristic and must remain unresolved until manually verified.
SYNTAX_AWARE_LANGUAGES = {"Python"}

ERROR_RE = re.compile(r"\b(?:raise|throw|panic)\b[^\n;]*", re.IGNORECASE)
CODE_RE = re.compile(r"[\"']((?:[A-Z][A-Z0-9_.:-]{2,}|\d{3,}))[\"']")
ENUM_RE = re.compile(r"\b(?:ErrorCode|Errors?|StatusCode)\.([A-Z][A-Z0-9_]+)")
STATUS_CODE_RE = re.compile(r"\b(?:status_code|code)\s*=\s*(\d{3,})\b", re.IGNORECASE)
IGNORED_EXTERNAL_CALLS = {
    "get", "post", "put", "patch", "delete", "head", "request", "fetch", "save", "insert", "update",
    "create", "publish", "send", "emit", "execute", "query", "commit", "rollback", "close", "log",
    "abs", "all", "any", "bool", "bytes", "callable", "dict", "dir", "enumerate", "filter", "float",
    "format", "getattr", "hasattr", "hash", "int", "isinstance", "issubclass", "iter", "len", "list",
    "map", "max", "min", "next", "object", "open", "ord", "pow", "print", "range", "repr", "reversed",
    "round", "set", "setattr", "sorted", "str", "sum", "super", "tuple", "type", "vars", "zip",
    "append", "extend", "items", "keys", "values", "loads", "dumps", "now", "strftime",
}


def _comment_label(text: str, line: int, *, description: bool = False) -> str:
    """Return the nearest contiguous source comment before an entry."""
    lines = text.splitlines()
    # 将完整注解块视为一个声明前缀；续行不能阻断前面的业务摘要。
    annotation_blocks: dict[int, tuple[int, str]] = {}
    cursor = 0
    while cursor < len(lines):
        if not lines[cursor].lstrip().startswith("@"):
            cursor += 1
            continue
        start = cursor
        block: list[str] = []
        balance = 0
        while cursor < len(lines):
            value = lines[cursor]
            block.append(value)
            masked = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", value)
            balance += masked.count("(") - masked.count(")")
            cursor += 1
            if balance <= 0:
                break
        joined = " ".join(block)
        for index in range(start, cursor):
            annotation_blocks[index] = (start, joined)
    index = min(len(lines) - 1, max(0, line - 1))
    comments: list[str] = []
    annotation_label = ""
    while index >= 0:
        # ``Path.read_text(encoding="utf-8")`` preserves a UTF-8 BOM.  Treat
        # it as transport metadata so a comment on the first source line can
        # still provide adapter-backed business-name evidence.
        value = lines[index].strip().lstrip("\ufeff")
        if index == line - 1:
            inline = re.search(r"@(?:business|domain|module)\s*[:=]\s*(.*?)(?=\s+@|$)", value, re.I)
            if inline:
                comments.append(inline.group(1).strip())
            index -= 1
            continue
        if not value:
            if comments:
                break
            index -= 1
            continue
        annotation_start = index
        if index in annotation_blocks:
            annotation_start, value = annotation_blocks[index]
        annotation = None
        if re.search(r"@(?:Operation|ApiOperation|ApiDescription|Tag|Api)\b", value, re.I):
            fields = ("description",) if description else ("summary", "value", "name", "description")
            annotation = next((match for field in fields
                               if (match := re.search(rf'''\b{field}\s*=\s*((?:"(?:\\.|[^"\\])*"\s*\+\s*)*"(?:\\.|[^"\\])*"|'[^']*')''', value, re.I))), None)
        if annotation:
            literals = re.findall(r"\"((?:\\.|[^\"\\])*)\"|'([^']*)'", annotation.group(1))
            annotation_label = annotation_label or "".join(first or second for first, second in literals).strip()
            index = annotation_start - 1
            continue
        if value.lstrip().startswith("@"):
            index = annotation_start - 1
            continue
        if value.startswith(("#", "//", "///", "/*", "*", "*/")):
            value = re.sub(r"^(?:#|//+|/\*+|\*+/?)\s*", "", value).strip()
            value = re.sub(r"\s*\*/\s*$", "", value).strip()
            if value.startswith("@") and not re.match(r"@(?:module|business|domain)\b", value, re.I):
                index -= 1
                continue
            value = re.sub(r"^@(?:module|business|domain)\s*[:=]?\s*", "", value, flags=re.I)
            if value:
                comments.append(value)
            index -= 1
            continue
        break
    label = annotation_label or " ".join(reversed(comments)).strip()
    label = re.sub(r"<[^>]+>", " ", label)
    label = re.sub(r"\bclient:[A-Za-z0-9_-]+\s*", "", label).strip()
    if description and annotation_label:
        return label
    # 类注释后续段落通常是线程池、阈值等实现说明，概览只取业务摘要。
    label = re.split(r"(?<=[。！？])\s*", label, maxsplit=1)[0].strip()
    return re.sub(r"(?:平台)?\s*Kafka\s*(?:Receiver|消费者)", "", label, flags=re.I) if description else label


def _label_evidence(text: str, line: int, label: str) -> list[dict[str, object]]:
    """Locate the source lines that supplied a readable adapter label."""
    if not label:
        return []
    lines = text.splitlines()
    # The registration line is 1-based. Walk the small annotation/comment
    # window used by _comment_label and retain exact source locations.
    found: list[dict[str, object]] = []
    for number in range(max(1, line - 8), min(len(lines), line + 8) + 1):
        if label in lines[number - 1]:
            found.append({"line": number, "reason": "入口适配器提供的中文注释、注解或注册名称"})
    return found


def _module_label(text: str, line: int) -> tuple[str, int]:
    """复用入口所属类型的 Swagger 名称或类注释，不改变业务归属。"""
    declarations = list(re.finditer(r"(?m)^[ \t]*(?:(?:public|private|protected|abstract|final|static)\s+)*(?:class|interface|enum)\s+\w+", text))
    preceding = [item for item in declarations if text.count("\n", 0, item.start()) + 1 <= line]
    if not preceding:
        return "", 0
    declaration_line = text.count("\n", 0, preceding[-1].start()) + 1
    prefix = text[preceding[-2].end() if len(preceding) > 1 else 0:preceding[-1].start()]
    tags = list(re.finditer(r'@Tag\s*\([^)]*?\bname\s*=\s*"([^"]+)"', prefix, re.DOTALL))
    label = tags[-1].group(1) if tags else _comment_label(text, declaration_line)
    label = re.split(r"[。，；]", label, maxsplit=1)[0]
    label = re.sub(r"(?:平台)?\s*Kafka\s*(?:消费者|Receiver)$|(?:消费者|管理|控制器)$", "", label, flags=re.I).strip()
    # 模块名称表达业务对象和动作，注册渠道、接口及任务只是触发方式。
    label = re.sub(r"(?:公开|内部|外部|后台)(?=接口|查询|同步|回调|$)", "", label)
    label = re.sub(r"(?:定时任务|任务|接口)$", "", label).strip()
    return (label, declaration_line) if re.search(r"[\u3400-\u9fff]", label) else ("", declaration_line)


def _module_name(relative: Path, identifier: str, text: str = "", line: int = 0) -> str:
    # Module ownership comes from source/package boundaries, never prose.
    parts = [
        part for part in relative.parts[:-1]
        if part.lower() not in {
            "src", "app", "api", "controller", "controllers", "service", "services",
            "impl", "implementation", "config", "configuration", "infra", "infrastructure",
            "dao", "repository", "persistence", "v0", "v1",
        }
    ]
    candidate = parts[-1] if parts else relative.stem
    if not candidate or candidate.lower() in {"main", "index", "app"}:
        route_parts = [part for part in identifier.split(" ", 1)[-1].strip("/").split("/") if part]
        route_parts = [part for part in route_parts if part.lower() not in {"api", "admin", "public", "internal", "private"} and not re.fullmatch(r"v\d+", part, re.I)]
        candidate = route_parts[0] if route_parts else relative.stem
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "-", candidate).strip("-") or "公共能力"
    return candidate.replace("_", "-").lower()


def _business_module_name(entry: EntryPoint) -> str:
    """Project-owned labels first; the source package/path is the fallback."""
    return entry.module_label.strip() or entry.module


def _source_syntax(text: str) -> str:
    """屏蔽字符串和注释，保留偏移与行号用于声明和调用匹配。"""
    return re.sub(
        r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|#[^\n]*|/\*[\s\S]*?\*/',
        lambda match: re.sub(r"[^\n]", " ", match.group()), text,
    )


def _functions(text: str, language: str, relative: str) -> list[FunctionInfo]:
    if language in {"TypeScript", "JavaScript", "Go"}:
        from ..core.syntax import parser_for, field, walk, text as node_text
        raw = text.encode("utf-8")
        tree = parser_for(language.lower(), relative.endswith(".tsx")).parse(raw).root_node
        functions = []
        for node in walk(tree):
            if node.type not in {"function_declaration", "method_definition", "method_declaration"}:
                continue
            name_node = field(node, "name")
            if name_node is None:
                continue
            owner, parent = "", node.parent
            while parent:
                if parent.type in {"class_declaration", "class"}:
                    owner = node_text(field(parent, "name"), raw)
                    break
                parent = parent.parent
            functions.append(FunctionInfo(node_text(name_node, raw), name_node.start_point.row + 1,
                node.end_point.row + 1, node_text(node, raw), owner))
        return sorted(functions, key=lambda item: item.start)
    if language == "Java":
        from .java_behavior import JavaIndex
        from ..core.syntax import field, text as node_text
        index = JavaIndex({relative: text})
        functions = []
        for owner in index.types.values():
            for method in owner.methods:
                body = node_text(method.node, owner.raw)
                start = field(method.node, "name").start_point.row + 1
                name = owner.name.removeprefix(owner.package + ".") if owner.package else owner.name
                functions.append(FunctionInfo(
                    method.name, start, method.node.end_point.row + 1, body,
                    name, method.name + "(" + ",".join(method.parameter_types) + ")",
                ))
        return sorted(functions, key=lambda f: f.start)
    lines = text.splitlines()
    starts: list[tuple[int, str, int]] = []
    if language == "Python":
        try:
            root = ast.parse(text)
        except SyntaxError:
            root = None
        if root is not None:
            nodes = sorted(
                (node for node in ast.walk(root) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
                key=lambda node: node.lineno,
            )
            return [
                FunctionInfo(
                    node.name,
                    node.lineno,
                    node.end_lineno or node.lineno,
                    "\n".join(lines[node.lineno - 1:node.end_lineno]),
                    owner=_python_owner(root, node),
                )
                for node in nodes
            ]
        pattern = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
        for index, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                starts.append((index, match.group(1), len(line) - len(line.lstrip())))
        result: list[FunctionInfo] = []
        for position, (start, name, indent) in enumerate(starts):
            end = len(lines)
            for next_start, _, next_indent in starts[position + 1:]:
                if next_indent <= indent:
                    end = next_start
                    if next_start > start and lines[next_start - 1].lstrip().startswith("@"):
                        end = next_start - 1
                    break
            body = "\n".join(lines[start:end])
            result.append(FunctionInfo(
                name, start + 1, end, body,
            ))
        return result
    # 字符串中的 {、} 和 ; 不参与声明匹配与代码块计数，偏移和行号保持不变。
    structural_text = _source_syntax(text)
    structural_lines = structural_text.splitlines()
    pattern = re.compile(
        r"\b(?:public|private|protected|static|final|abstract|synchronized|native|async|override|function)?\s*"
        r"(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
        r"[\w.$<>?,\[\]\s]+?\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws [^{]+)?\{|"
        r"\bfun\s+([A-Za-z_]\w*)\s*\([^;{}]*\)[^{]*\{",
        re.DOTALL,
    )
    if language == "Java":
        pattern = re.compile(
            r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*"
            r"(?:[\w.$<>?,\[\]]+\s+)?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws [^{;]+)?\{",
            re.MULTILINE,
        )
    for match in pattern.finditer(structural_text):
        # 声明位置以方法名所在行定位，不能把前置注解归到下一接口。
        name_group = 1 if match.group(1) else 2
        if match.group(name_group) in _LOCAL_SYNTAX_NAMES | {"switch", "new", "synchronized"}:
            continue
        starts.append((text[:match.start(name_group)].count("\n"), match.group(name_group), 0))
    result = []
    class_ranges: list[tuple[int, int, str]] = []
    class_pattern = re.compile(r"\b(?:class|interface|object|struct)\s+([A-Za-z_]\w*)[^\{]*\{")
    for match in class_pattern.finditer(structural_text):
        start_line = text[:match.start()].count("\n")
        depth = 0
        end_line = len(lines) - 1
        for index in range(start_line, len(lines)):
            depth += structural_lines[index].count("{") - structural_lines[index].count("}")
            if index > start_line and depth <= 0:
                end_line = index
                break
        class_ranges.append((start_line, end_line, match.group(1)))
    qualified_ranges: list[tuple[int, int, str]] = []
    for class_start, class_end, class_name in class_ranges:
        parents = [
            (parent_start, parent_end, qualified)
            for parent_start, parent_end, qualified in qualified_ranges
            if parent_start <= class_start <= parent_end
        ]
        parent = max(parents, key=lambda item: (item[0], -item[1]), default=None)
        qualified_name = f"{parent[2]}.{class_name}" if parent else class_name
        qualified_ranges.append((class_start, class_end, qualified_name))
    for position, (start, name, _) in enumerate(starts):
        end = len(lines)
        depth = 0
        opened = False
        for index in range(start, len(lines)):
            opened |= "{" in structural_lines[index]
            depth += structural_lines[index].count("{") - structural_lines[index].count("}")
            if opened and depth <= 0:
                end = index + 1
                break
        if position + 1 < len(starts):
            end = min(end, starts[position + 1][0])
        body = "\n".join(lines[start:end])
        owners = [
            (class_start, class_end, owner)
            for class_start, class_end, owner in qualified_ranges
            if class_start <= start <= class_end
        ]
        owner = max(owners, key=lambda item: (item[0], -item[1]))[2] if owners else ""
        result.append(FunctionInfo(
            name, start + 1, end, body,
            owner=owner,
        ))
    return sorted(result, key=lambda item: (item.start, item.name))


def _python_owner(root: ast.AST, function: ast.AST) -> str:
    parents: dict[ast.AST, ast.AST] = {
        child: parent
        for parent in ast.walk(root)
        for child in ast.iter_child_nodes(parent)
    }
    owners: list[str] = []
    parent = parents.get(function)
    while parent is not None:
        if isinstance(parent, ast.ClassDef):
            owners.append(parent.name)
        parent = parents.get(parent)
    return ".".join(reversed(owners))


def _decorated_entries(text: str, language: str, relative: str) -> list[tuple[str, str, int, str]]:
    lines = text.splitlines()
    found: list[tuple[str, str, int, str]] = []
    constants = dict(re.findall(
        r"\b(?:(?:public|private|protected)\s+)?(?:(?:static\s+final|final|static|const))\s+(?:String|string)\s+([A-Za-z_]\w*)\s*=\s*[\"']([^\"']+)[\"']",
        text,
    ))

    def resolve_value(value: str) -> str:
        value = value.strip().strip('{}() ')
        return constants.get(value, value.strip("\"'"))

    declarations = _functions(text, language, relative) if language in {"Java", "Python", "TypeScript", "JavaScript", "Go"} else []
    outbound_lines = set()
    if language == "Java":
        from .java_behavior import JavaIndex
        for owner in JavaIndex({relative: text}).types.values():
            header = owner.raw[owner.node.start_byte:owner.node.end_byte].decode("utf-8").split("{", 1)[0]
            if re.search(r"@FeignClient\b|@HttpExchange\b", header):
                outbound_lines.update(range(owner.node.start_point.row + 1, owner.node.end_point.row + 2))
    base_path = ""
    base_paths = [""]
    proto_service = ""
    graphql_owner = ""
    outbound_only = bool(
        re.search(r"@FeignClient\b|@HttpExchange\b", text)
        and not re.search(r"@(?:RestController|Controller)\b", text)
    )
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*")):
            continue
        annotation_text = stripped
        if stripped.startswith("@") and stripped.count("(") > stripped.count(")"):
            block = [stripped]
            balance = stripped.count("(") - stripped.count(")")
            for continuation in lines[index + 1:index + 12]:
                block.append(continuation.strip())
                balance += continuation.count("(") - continuation.count(")")
                if balance <= 0:
                    break
            annotation_text = " ".join(block)
        if (outbound_only or index + 1 in outbound_lines) and re.search(
            r"@(Get|Post|Put|Patch|Delete|Options|Head)Mapping\b|@RequestMapping\b|@HttpExchange\b",
            annotation_text,
        ):
            continue
        annotation = annotation_text.lstrip("@")
        kind = ""
        identifier = ""
        binding_identifiers: list[str] = []
        if language == "Protocol Buffers":
            service = re.match(r"service\s+([A-Za-z_]\w*)", stripped)
            if service:
                proto_service = service.group(1)
                continue
            rpc = re.match(r"rpc\s+([A-Za-z_]\w*)\s*\(", stripped)
            if rpc:
                kind, identifier = "rpc", f"{proto_service or '代码中未确认'}/{rpc.group(1)}"
        elif language == "GraphQL":
            owner = re.match(r"type\s+(Query|Mutation|Subscription)\b", stripped)
            if owner:
                graphql_owner = owner.group(1)
                continue
            field = re.match(r"([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:", stripped)
            if graphql_owner and field:
                kind, identifier = "rpc", f"{graphql_owner}/{field.group(1)}"
        csharp = re.match(r"\[Http(Get|Post|Put|Patch|Delete)\s*\(\s*[\"']([^\"']*)", stripped, re.I)
        ruby = re.match(r"(get|post|put|patch|delete)\s+[\"']([^\"']+)", stripped, re.I)
        laravel = re.match(r"Route::(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)", stripped, re.I)
        quartz = re.search(r"\bclass\s+([A-Za-z_]\w*)\b[^\n{]*\bimplements\s+[^\n{]*\bJob\b", stripped)
        if kind:
            # Protocol/GraphQL entries already have their identifier.
            pass
        elif csharp:
            kind, identifier = "url", f"{csharp.group(1).upper()} {csharp.group(2) or '代码中未确认'}"
        elif ruby:
            kind, identifier = "url", f"{ruby.group(1).upper()} {ruby.group(2)}"
        elif laravel:
            kind, identifier = "url", f"{laravel.group(1).upper()} {laravel.group(2)}"
        elif quartz:
            kind, identifier = "scheduled", quartz.group(1)
        elif language == "Java" and re.match(r"@Path\s*\(", annotation_text):
            value = re.search(r'@Path\s*\(\s*"([^"]*)"', annotation_text)
            following = " ".join(lines[index:index + 6])
            # JAX-RS uses the same annotation for class and method scopes.  A
            # method path is consumed by the following HTTP annotation and
            # must never replace the class prefix.
            if value and re.search(r"\b(class|interface|record)\b", following):
                base_path = value[1]
            continue
        elif language == "Java" and re.match(r"@(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", annotation_text):
            method = re.match(r"@(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", annotation_text)[1]
            declaration = next((f for f in declarations if f.start >= index + 1), None)
            local = re.search(r'@Path\s*\(\s*"([^"]*)"', declaration.body.split("{", 1)[0] if declaration else annotation_text)
            kind, identifier = "url", f"{method} {base_path.rstrip('/') + '/' + local[1].lstrip('/') if local else base_path or '/'}"
        elif re.match(r"@Controller\b", annotation_text) and re.search(r"\bclass\s+[A-Za-z_]\w*", " ".join(lines[index + 1:index + 5])):
            value = re.search(r"@Controller\s*\(\s*[\"']([^\"']+)", annotation_text)
            base_path = value.group(1) if value else ""
            continue
        elif stripped.startswith("@") and re.match(r"(?:app|router|blueprint|bp)\.(?:get|post|put|patch|delete|options|head)\s*\(", annotation, re.I):
            method = re.search(r"\.([A-Za-z]+)\s*\(", annotation).group(1).upper()
            value = re.search(r"\(\s*[\"']([^\"']+)", annotation)
            kind, identifier = "url", f"{method} {(value.group(1) if value else '代码中未确认')}"
        elif stripped.startswith("@") and re.match(r"(?:app|router|blueprint|bp)\.api_route\s*\(", annotation, re.I):
            value = re.search(r"\(\s*[\"']([^\"']+)", annotation)
            methods = re.search(r"methods\s*=\s*\[([^\]]+)\]", annotation, re.I)
            method_values = re.findall(r"[\"']([A-Za-z]+)[\"']", methods.group(1)) if methods else []
            method = "/".join(item.upper() for item in method_values) or "REQUEST"
            kind, identifier = "url", f"{method} {(value.group(1) if value else '代码中未确认')}"
        elif stripped.startswith("@") and re.match(r"(?:app|router|blueprint|bp)\.route\s*\(", annotation, re.I):
            value = re.search(r"\(\s*[\"']([^\"']+)", annotation)
            methods = re.search(r"methods\s*=\s*\[([^\]]+)\]", annotation, re.I)
            method = "REQUEST"
            if methods:
                method_values = re.findall(r"[\"']([A-Za-z]+)[\"']", methods.group(1))
                method = "/".join(item.upper() for item in method_values) or method
            kind, identifier = "url", f"{method} {(value.group(1) if value else '代码中未确认')}"
        elif re.search(r"(?:websocket|WebSocket)\s*\(", annotation):
            value = re.search(r"\(\s*[\"']([^\"']+)", annotation)
            kind, identifier = "websocket", f"WEBSOCKET {(value.group(1) if value else '代码中未确认')}"
        elif re.search(r"@(?:Get|Post|Put|Patch|Delete|Options|Head)\s*(?:\(|$)", annotation_text):
            mapping = re.search(r"@(Get|Post|Put|Patch|Delete|Options|Head)\s*(?:\(\s*[\"']([^\"']*)[\"'])?", annotation_text)
            method = mapping.group(1).upper() if mapping else "REQUEST"
            paths = re.findall(r"[\"']([^\"']*)[\"']", annotation_text)
            paths = paths or ([mapping.group(2)] if mapping and mapping.group(2) else [""])
            binding_identifiers = [
                f"{method} {f'{base_path.rstrip('/')}/{path.lstrip('/')}' if base_path and path else (path or base_path or '代码中未确认')}"
                for path in dict.fromkeys(paths)
            ]
            kind, identifier = "url", binding_identifiers[0]
        elif re.search(r"@(?:Get|Post|Put|Patch|Delete|Options|Head|Request)Mapping\b", annotation_text):
            method_match = re.search(r"@(Get|Post|Put|Patch|Delete|Options|Head|Request)Mapping", annotation_text)
            method = (method_match.group(1).replace("Mapping", "") if method_match else "REQUEST").upper()
            if method == "REQUEST":
                method = "REQUEST"
            route_value = re.search(r"\b(?:value|path)\s*=\s*(\{[^}]*\}|[\"'][^\"']*[\"'])|Mapping\s*\(\s*(\{[^}]*\}|[\"'][^\"']*[\"'])", annotation_text)
            raw_paths = next((value for value in route_value.groups() if value), "") if route_value else ""
            paths = re.findall(r"[\"']([^\"']*)[\"']", raw_paths) or [""]
            methods = re.findall(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)", annotation_text) or [method]
            following_text = "\n".join(lines[index + 1:])
            class_declaration = re.search(r"\b(?:class|interface)\s+\w+", following_text)
            first_method = next((function for function in declarations if function.start > index + 1), None)
            class_before_method = bool(class_declaration and (
                first_method is None or index + 2 + following_text.count("\n", 0, class_declaration.start()) < first_method.start
            ))
            if method == "REQUEST" and class_before_method:
                base_paths = list(dict.fromkeys(paths))
                base_path = base_paths[0]
                continue
            binding_identifiers = [
                f"{registered_method} {f'{base.rstrip('/')}/{item.lstrip('/')}' if base else item}"
                for base in base_paths for item in dict.fromkeys(paths) for registered_method in dict.fromkeys(methods)
            ]
            kind, identifier = "url", binding_identifiers[0]
        elif re.search(r"@(Query|Mutation|Subscription)Mapping\b", annotation_text):
            mapping = re.search(r"@(Query|Mutation|Subscription)Mapping\b", annotation_text)
            kind, identifier = "rpc", mapping.group(1) if mapping else "代码中未确认"
        elif re.search(r"(?:KafkaListener|RabbitListener|JmsListener|PulsarListener|RocketMQMessageListener)\s*\(", annotation_text):
            value = re.search(
                r"(?:topics|queues|destination|topic|value)\s*=\s*(\{[^}]*\}|[A-Za-z_]\w*|[\"'][^\"']+[\"'])|\(\s*[\"']([^\"']+)",
                annotation_text,
            )
            raw_topic = value.group(1) if value and value.group(1) else (value.group(2) if value else "")
            topics = [resolve_value(item) for item in re.findall(r"[\"']([^\"']+)[\"']", raw_topic)]
            if not topics and raw_topic:
                topics = [resolve_value(raw_topic)]
            kind, identifier = "message", (topics[0] if topics else "代码中未确认")
        elif (
            (stripped.startswith("@") and re.search(r"@?(?:XxlJob|JobHandler|Scheduled|Cron|scheduler\.scheduled_job)\b", annotation_text, re.I))
        ):
            value = re.search(r"(?:cron|fixedDelay|fixedRate|fixedDelayString|fixedRateString|name|value)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", annotation_text, re.I)
            kind, identifier = "scheduled", next((item for item in (value.groups() if value else ()) if item), "代码中未确认")
        elif (
            (stripped.startswith("@") and re.search(
                r"(?:EventListener|EventPattern|MessagePattern|OnEvent|Transition|Workflow|state_machine)", stripped, re.I
            ))
            or re.search(r"\b(?:event_handler|on_event)\s*\(", stripped, re.I)
        ):
            value = re.search(r"(?:classes|value|pattern|event)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", stripped, re.I)
            kind = "message" if "MessagePattern" in stripped else "event"
            identifier = next((item for item in value.groups() if item), "代码中未确认") if value else "代码中未确认"
            if identifier == "代码中未确认" and language == "Java":
                event_type = re.search(r"@EventListener\s*\(\s*(?:classes\s*=\s*)?([\w.]+)\.class", stripped)
                if event_type:
                    identifier = event_type[1]
        elif re.match(r"@(?:click\.command|app\.command|typer\.command|Command)\s*\(", stripped, re.I):
            value = re.search(r"(?:name|value)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", stripped, re.I)
            kind, identifier = "cli", next((item for item in (value.groups() if value else ()) if item), "代码中未确认")
        elif re.search(r"@OnMessage\b|(?:socketio|io)\.on\s*\(", stripped, re.I):
            value = re.search(r"\(\s*[\"']([^\"']+)", stripped)
            kind, identifier = "websocket", (value.group(1) if value else "代码中未确认")
        elif re.search(r"@(?:FileListener|OnFile)\b", stripped, re.I):
            value = re.search(r"(?:path|value)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", stripped)
            kind, identifier = "file", next((item for item in value.groups() if item), "代码中未确认") if value else "代码中未确认"
        elif re.search(r"@Bean\b", stripped) and re.search(r"\bJob\s+[A-Za-z_]\w*\s*\(", " ".join(lines[index + 1:index + 6])):
            job = re.search(r"\bJob\s+([A-Za-z_]\w*)\s*\(", " ".join(lines[index + 1:index + 6]))
            kind, identifier = "batch", job.group(1) if job else "代码中未确认"
        if kind:
            if kind == "url" and re.search(r"event[-_]stream|SseEmitter|EventSource", annotation_text, re.I):
                kind = "sse"
            if kind == "url" and "webhook" in identifier.lower():
                kind = "webhook"
            handler = "代码中未确认"
            # 方法声明、参数注解和 throws 可以跨行；不能逐行匹配或把注解当作方法。
            following = next((function for function in declarations if function.start >= index + 1), None)
            if following and following.start <= index + 20:
                handler = following.name
            for candidate in ([] if following else lines[index + 1:index + 8]):
                match = re.search(
                    r"(?:async\s+)?def\s+([A-Za-z_]\w*)|\b(?:fun\s+)?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:throws\s+[^{};]+)?\{",
                    candidate,
                )
                if match:
                    handler = match.group(1) or match.group(2)
                    break
            if kind == "rpc" and identifier in {"Query", "Mutation", "Subscription"} and handler != "代码中未确认":
                identifier = f"{identifier}/{handler}"
            if binding_identifiers and len(binding_identifiers) > 1:
                found.extend((kind, item, index + 1, handler) for item in binding_identifiers)
                continue
            if kind == "message":
                topic_values = re.findall(
                    r"(?:topics|queues|destination|topic|value)\s*=\s*(?:\{([^}]*)\}|([A-Za-z_]\w*|[\"'][^\"']+[\"']))",
                    annotation_text,
                    re.IGNORECASE,
                )
                identifiers = [
                    topic
                    for group in topic_values
                    for topic in re.findall(r"[\"']([^\"']+)[\"']|\b([A-Z_]\w*)\b", " ".join(group))
                ] or [identifier]
                identifiers = [resolve_value((topic[0] or topic[1]) if isinstance(topic, tuple) else topic) for topic in identifiers]
                found.extend((kind, topic, index + 1, handler) for topic in dict.fromkeys(identifiers))
            else:
                found.append((kind, identifier, index + 1, handler))
    for index, line in enumerate(lines):
        if line.lstrip().startswith("@"):
            continue
        match = re.search(
            r"\b(?:app|router|r|mux)\.(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)[\"'](?P<tail>.*)",
            line,
            re.I,
        )
        if match:
            handler_match = re.search(r",\s*([A-Za-z_]\w*)\s*\)?\s*;?\s*$", match.group("tail"))
            found.append((
                "url", f"{match.group(1).upper()} {match.group(2)}", index + 1,
                handler_match.group(1) if handler_match else "代码中未确认",
            ))
        django = re.search(r"\b(?:path|re_path)\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*([A-Za-z_]\w*)", line)
        if django and "urlpatterns" in text:
            found.append(("url", f"REQUEST {django.group(1)}", index + 1, django.group(2)))
        route = re.search(r"Route::(get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)", line, re.I)
        if route and not any(item[2] == index + 1 and item[1].endswith(route.group(2)) for item in found):
            found.append(("url", f"{route.group(1).upper()} {route.group(2)}", index + 1, "代码中未确认"))
        go_http = re.search(r"\b(?:http|mux)\.HandleFunc\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*([A-Za-z_]\w*)", line)
        if go_http:
            found.append(("url", f"REQUEST {go_http.group(1)}", index + 1, go_http.group(2)))
        defaults = re.search(r"\.set_defaults\s*\([^)]*\bfunc\s*=\s*([A-Za-z_]\w*)", line)
        if defaults:
            prior = "\n".join(lines[max(0, index - 8):index + 1])
            command = re.findall(r"\.add_parser\s*\(\s*[\"']([^\"']+)", prior)
            found.append(("cli", command[-1] if command else "代码中未确认", index + 1, defaults.group(1)))
        if language == "Python":
            job = re.search(r"\bscheduler\.add_job\(\s*([A-Za-z_]\w*)\s*,\s*['\"](cron|interval|date)['\"]([^)]*)\)", line)
            if job:
                found.append(("scheduled", job[2] + job[3].strip(), index + 1, job[1]))
    call_pattern = re.compile(
        r"\b(?:app|router|blueprint|bp|r|mux)\.(get|post|put|patch|delete|options|head|all)\s*\(\s*[\"']([^\"']+)[\"'](?P<tail>[^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in call_pattern.finditer(text):
        line = text[:match.start()].count("\n") + 1
        identifier = f"{match.group(1).upper()} {match.group(2)}"
        handler_match = re.search(r"(?:endpoint|view_func|handler)\s*=\s*([A-Za-z_]\w*)|,\s*([A-Za-z_]\w*)\s*(?:,|$)", match.group("tail"))
        handler = (handler_match.group(1) or handler_match.group(2)) if handler_match else "代码中未确认"
        existing = next((position for position, item in enumerate(found) if item[2] == line and item[1] == identifier), None)
        if existing is None:
            found.append(("url", identifier, line, handler))
        elif found[existing][3] == "代码中未确认" and handler != "代码中未确认":
            found[existing] = ("url", identifier, line, handler)
    for match in re.finditer(
        r"\b(?:app|router|blueprint|bp)\.add_api_route\s*\(\s*[\"']([^\"']+)[\"'](?P<tail>[^)]*)\)",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        line = text[:match.start()].count("\n") + 1
        methods = re.search(r"methods\s*=\s*\[([^\]]+)\]", match.group("tail"), re.I)
        method_values = re.findall(r"[\"']([A-Za-z]+)[\"']", methods.group(1)) if methods else ["REQUEST"]
        handler_match = re.search(r"(?:endpoint|handler)\s*=\s*([A-Za-z_]\w*)", match.group("tail"))
        handler = handler_match.group(1) if handler_match else "代码中未确认"
        for method in dict.fromkeys(method_values):
            item = ("url", f"{method.upper()} {match.group(1)}", line, handler)
            if not any(existing[0:3] == item[0:3] for existing in found):
                found.append(item)
    if language == "Protocol Buffers":
        for service in re.finditer(r"\bservice\s+([A-Za-z_]\w*)\s*\{(?P<body>.*?)\}", text, re.DOTALL):
            for rpc in re.finditer(r"\brpc\s+([A-Za-z_]\w*)\s*\(", service.group("body")):
                line = text[:service.start("body") + rpc.start()].count("\n") + 1
                item = ("rpc", f"{service.group(1)}/{rpc.group(1)}", line, "代码中未确认")
                if not any(existing[0:3] == item[0:3] for existing in found):
                    found.append(item)
    if language == "GraphQL":
        for owner in re.finditer(r"\btype\s+(Query|Mutation|Subscription)\b[^\{]*\{(?P<body>.*?)\}", text, re.DOTALL):
            for field in re.finditer(r"^\s*([A-Za-z_]\w*)\s*(?:\([^\n]*\))?\s*:", owner.group("body"), re.MULTILINE):
                line = text[:owner.start("body") + field.start()].count("\n") + 1
                item = ("rpc", f"{owner.group(1)}/{field.group(1)}", line, "代码中未确认")
                if not any(existing[0:3] == item[0:3] for existing in found):
                    found.append(item)
    if language == "Python":
        guard = re.search(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']\s*:", text, re.MULTILINE)
        if guard:
            following = text[guard.end():]
            call = re.search(r"^\s*([A-Za-z_]\w*)\s*\(", following, re.MULTILINE)
            handler = call.group(1) if call else "代码中未确认"
            item = ("cli", relative, text[:guard.start()].count("\n") + 1, handler)
            if not any(existing[0:3] == item[0:3] for existing in found):
                found.append(item)
    if language in {"Java", "Kotlin", "Scala", "Groovy"} and re.search(r"@GrpcService\b|\bImplBase\b|@DubboService\b", text):
        owner = re.search(r"\bclass\s+([A-Za-z_]\w*)", text)
        for method in re.finditer(
            r"@Override\s+(?:public\s+)?(?:suspend\s+)?[\w<>,.?\[\]]+\s+([A-Za-z_]\w*)\s*\(",
            text,
            re.DOTALL,
        ):
            item = (
                "rpc", f"{owner.group(1) if owner else '代码中未确认'}/{method.group(1)}",
                text[:method.start()].count("\n") + 1, method.group(1),
            )
            if not any(existing[0:3] == item[0:3] for existing in found):
                found.append(item)
    if language in {"Shell", "PowerShell", "Batch"} and any(
        part.lower() in {"bin", "commands", "jobs", "scripts", "tasks"} for part in Path(relative).parts
    ):
        kind = "batch" if any(part.lower() in {"jobs", "tasks"} for part in Path(relative).parts) else "cli"
        found.append((kind, relative, 1, Path(relative).name))
    return found


def _platform_message_entries(text: str, relative: str, functions: list[FunctionInfo],
                              source_texts: dict[str, str] | None = None) -> list[tuple[str, str, int, str]]:
    """Find message receivers implemented through platform base classes/registries.

    Annotation-only discovery misses the common ``class X extends Receiver`` shape.
    This deliberately records the receiver even when the topic or handler is only
    partially resolvable; the caller then preserves an unresolved finding.
    """
    lines = text.splitlines()
    result: list[tuple[str, str, int, str]] = []
    constants = dict(re.findall(r"\b(?:(?:public|private|protected)\s+)?(?:(?:static\s+final|final|static|const))\s+(?:String|string)\s+([A-Za-z_]\w*)\s*=\s*[\"']([^\"']+)[\"']", text))
    def resolve_topic(value: str) -> str:
        value = value.strip().strip('{}() ')
        return constants.get(value, value.strip("\"'"))
    class_re = re.compile(
        r"\bclass\s+([A-Za-z_]\w*)\s+(?:extends|implements)\s+([A-Za-z_]\w*(?:Receiver|Consumer|Listener|MessageHandler|MessageReceiver)\b)"
    )
    for match in class_re.finditer(text):
        class_name = match.group(1)
        line = text[:match.start()].count("\n") + 1
        window = "\n".join(lines[line - 1:line + 20])
        topic_match = re.search(
            r"(?:topic|topics|queue|destination|channel)\s*(?:=|\(|:)\s*(?:\{\s*)?([A-Za-z_]\w*|[\"'][^\"']+[\"'])",
            window,
            re.I,
        )
        topic = resolve_topic(topic_match.group(1)) if topic_match else "代码中未确认"
        handler = "代码中未确认"
        for function in functions:
            if function.owner.rsplit(".", 1)[-1] == class_name and function.name.lower() in {"serve", "doserve", "receive", "handle", "onmessage"}:
                handler = function.name
                break
        topic_method = next((function for function in functions
            if function.owner.rsplit(".", 1)[-1] == class_name and function.name.lower() in {"topic", "topics", "queue", "channel"}), None)
        if topic == "代码中未确认" and topic_method:
            returned = re.search(r"\breturn\s+([\w.]+|[\"'][^\"']+[\"'])\s*;", topic_method.body)
            if returned:
                value = returned.group(1)
                topic = resolve_topic(value)
                if "." in value:
                    owner, name = value.rsplit(".", 1)
                    candidates = [source for file, source in (source_texts or {}).items() if Path(file).stem == owner]
                    literal = re.search(rf"\b{re.escape(name)}\s*=\s*[\"']([^\"']+)[\"']", candidates[0]) if len(candidates) == 1 else None
                    topic = literal.group(1) if literal else "代码中未确认"
        result.append(("message", topic, line, handler))
    registry_re = re.compile(
        r"\b(?P<registration>register(?:Listener|Consumer|Receiver|MessageHandler)?|subscribe|add(?:Listener|Consumer)|bind)\s*\(\s*([A-Za-z_]\w*|[\"'][^\"']+[\"'])\s*,\s*(?:new\s+)?([A-Za-z_]\w*)",
        re.I,
    )
    for match in registry_re.finditer(text):
        line = text[:match.start()].count("\n") + 1
        target = match.group(3)
        handler = next((f.name for f in functions if f.owner == target and f.name.lower() in {"serve", "doserve", "receive", "handle", "onmessage"}), "代码中未确认")
        if handler == "代码中未确认" and match.group("registration").casefold() in {"register", "bind"}:
            # 普通重载和仓储调用没有消息接收器或明确监听注册证据。
            continue
        result.append(("message", resolve_topic(match.group(2)), line, handler))
    return result


def _enrich_signatures(functions: list[FunctionInfo], language: str) -> None:
    """Attach stable, source-derived method signatures for capability IDs."""
    for function in functions:
        if function.signature:
            continue
        declaration_body = re.sub(r'"(?:\\.|[^"\\])*"', lambda match: " " * len(match.group()), function.body)
        head = declaration_body.split("{", 1)[0] if language != "Python" else (function.body.splitlines()[0] if function.body else "")
        match = re.search(rf"\b{re.escape(function.name)}\s*\(", head)
        params = ""
        if match:
            depth = 1
            for end in range(match.end(), len(head)):
                depth += (head[end] == "(") - (head[end] == ")")
                if not depth:
                    params = head[match.end():end].strip()
                    break
        if language == "Python":
            names = []
            for item in params.split(",") if params else []:
                item = item.strip().split("=", 1)[0].strip()
                if not item or item in {"self", "cls", "/", "*"}:
                    continue
                names.append(item.split(":", 1)[1].strip() if ":" in item else "Any")
            params = ",".join(names)
        else:
            params = re.sub(r"\s+", " ", params)
            if language == "Java":
                # 参数名不属于方法身份；保留类型、泛型与数组维度。
                params = re.sub(r"@[\w.]+(?:\([^()]*\))?\s*", "", params)
                params = re.sub(r"\bfinal\s+", "", params)
                params = re.sub(r"\s+[A-Za-z_$][\w$]*(\s*\[\s*\])*\s*(?=,|$)", lambda match: (match.group(1) or "").replace(" ", ""), params)
            params = ",".join(part.strip() for part in params.split(",") if part.strip())
        function.signature = f"{function.name}({params})"


def _select_handler(
    functions: list[FunctionInfo],
    global_candidates: list[tuple[str, FunctionInfo]],
    handler: str,
    registration_line: int,
) -> FunctionInfo | None:
    """Bind a registration to its nearest same-file declaration.

    Framework entry methods commonly share names such as ``doExecute``. The
    registration line is the only local evidence needed to choose the method
    in that class; a global same-name match remains ambiguous.
    """
    local = [function for function in functions if function.name == handler]
    if local:
        return min(
            local,
            key=lambda function: (
                function.start < registration_line,
                abs(function.start - registration_line),
                function.start,
            ),
        )
    return global_candidates[0][1] if len(global_candidates) == 1 else None


def _platform_job_entries(text: str, functions: list[FunctionInfo]) -> list[tuple[str, str, int, str]]:
    """Find XXL-JOB handlers registered through annotations or platform bases."""
    job_classes: set[str] = set()
    class_identifiers: dict[str, str] = {}
    class_pattern = re.compile(
        r"\bclass\s+([A-Za-z_]\w*)[^\n{]*(?:extends|implements)\s+[^\n{]*(?:Job|JobHandler|XxlJob)\b",
        re.I,
    )
    for match in class_pattern.finditer(text):
        class_name = match.group(1)
        job_classes.add(class_name)
        annotation = re.search(
            r'''@(?:XxlJob|JobHandler)\s*(?:\(\s*(?:value\s*=\s*)?["']([^"']+)")?''',
            text[max(0, match.start() - 600):match.start()],
            re.I,
        )
        if annotation and annotation.group(1):
            class_identifiers[class_name] = annotation.group(1)
    result: list[tuple[str, str, int, str]] = []
    lines = text.splitlines()
    for function in functions:
        if function.name.lower() not in {"doexecute", "execute"}:
            continue
        if function.name.lower() == "execute" and any(
            other.owner == function.owner and other.name.lower() == "doexecute" for other in functions
        ):
            continue
        annotation_window = "\n".join(lines[max(0, function.start - 8):function.start - 1])
        annotation = re.search(r'''@(?:XxlJob|JobHandler)\s*(?:\(\s*(?:value\s*=\s*)?["']([^"']+)")?''', annotation_window, re.I)
        class_name = function.owner.rsplit(".", 1)[-1]
        if annotation or class_name in job_classes:
            identifier = (
                annotation.group(1) if annotation and annotation.group(1)
                else class_identifiers.get(class_name) or function.name
            )
            result.append(("scheduled", identifier, function.start, function.name))
    return result


def _executor_submissions(text: str, relative: str) -> list[tuple[str, int, str]]:
    """Return (worker target, submit line, executor expression) for Runnable calls."""
    found: list[tuple[str, int, str]] = []
    pattern = re.compile(
        r"(?P<executor>(?:executor|pool)|[A-Za-z_]\w*(?:executor|pool)\w*)\s*\.\s*(?:execute|submit)\s*\(\s*(?P<body>[^;\n]+)",
        re.I,
    )
    for match in pattern.finditer(text):
        body = match.group("body")
        targets = re.findall(r"(?:->\s*[^{]*?\b|\b)([A-Za-z_]\w*)\s*\(", body)
        if not targets:
            targets = re.findall(r"(?:^|[.&])([A-Za-z_]\w*)\s*::\s*([A-Za-z_]\w*)", body)
            targets = [item[-1] for item in targets]
        if not targets:
            direct = re.match(r"\s*([A-Za-z_]\w*)\s*(?:[,)]|$)", body)
            if direct:
                targets = [direct.group(1)]
        target = next((name for name in targets if name not in {"wrap", "execute", "submit"}), "")
        line = text[:match.start()].count("\n") + 1
        found.append((target, line, match.group("executor")))
    return found


def _unrecognized_registration_lines(text: str, language: str, known_lines: set[int]) -> list[int]:
    if language in {"Protocol Buffers", "GraphQL", "Configuration"}:
        return []
    patterns = (
        r"@(?:Get|Post|Put|Patch|Delete)Mapping\b",
        r"@(?:Get|Post|Put|Patch|Delete|Options|Head)\s*(?:\(|$)",
        r"\b(?:app|router|blueprint|bp|r|mux)\.(?:get|post|put|patch|delete|all|route|api_route|add_api_route)\s*\(",
        r"@(?:KafkaListener|RabbitListener|JmsListener|PulsarListener|RocketMQMessageListener)\b",
        r"@(?:XxlJob|JobHandler|Scheduled|Cron)\b",
        r"@(?:EventListener|MessagePattern|OnEvent)\b",
        r"@(?:Controller|RestController|GrpcService|DubboService)\b",
        r"\b(?:websocket|WebSocket)\s*\(",
        r"\b(?:socketio|io)\.on\s*\(",
        r"\b(?:routes?|url_patterns?)\s*=\s*[\[{]",
    )
    marker = re.compile("|".join(patterns), re.IGNORECASE)
    outbound = bool(re.search(r"@FeignClient\b|@HttpExchange\b", text)
                    and not re.search(r"@(?:RestController|Controller)\b", text))
    return [index for index, line in enumerate(text.splitlines(), 1)
            if marker.search(line) and index not in known_lines
            and not (outbound and re.search(r"@(?:Get|Post|Put|Patch|Delete|Options|Head)Mapping\b", line))]


def _configuration_entries(text: str, relative: str) -> list[tuple[str, str, int, str]]:
    name = Path(relative).name.lower()
    found: list[tuple[str, str, int, str]] = []

    def line_of(needle: str) -> int:
        return next((index for index, line in enumerate(text.splitlines(), 1) if needle in line), 1)

    try:
        if name == "pyproject.toml":
            document = tomllib.loads(text)
            project = document.get("project", {}) if isinstance(document, dict) else {}
            for group in ("scripts", "gui-scripts"):
                scripts = project.get(group, {}) if isinstance(project, dict) else {}
                if isinstance(scripts, dict):
                    for command, target in scripts.items():
                        handler = str(target).split(":")[-1].strip() or "代码中未确认"
                        found.append(("cli", str(command), line_of(str(command)), handler))
        elif name == "package.json":
            document = json.loads(text)
            bins = document.get("bin", {}) if isinstance(document, dict) else {}
            if isinstance(bins, str):
                bins = {str(document.get("name", "代码中未确认")): bins}
            if isinstance(bins, dict):
                for command, target in bins.items():
                    found.append(("cli", str(command), line_of(str(command)), str(target)))
        elif name == "setup.cfg":
            parser = configparser.ConfigParser()
            parser.read_string(text)
            for group in parser.sections():
                if not group.startswith("options.entry_points"):
                    continue
                for command, target in parser.items(group):
                    if "=" in target:
                        handler = target.split("=", 1)[1].strip().split(":")[-1]
                        found.append(("cli", command.strip(), line_of(command), handler))
        elif name == "setup.py":
            for match in re.finditer(
                r"(?P<command>[A-Za-z_][\w.-]*)\s*=\s*[\"'](?P<target>[^\"']+):(?P<handler>[A-Za-z_]\w*)[\"']",
                text,
            ):
                found.append(("cli", match.group("command"), text[:match.start()].count("\n") + 1, match.group("handler")))
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, TypeError, ValueError):
        return []
    return found


def _frameworks(files: list[Path]) -> list[str]:
    names: set[str] = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        checks = {
            "Spring": ("org.springframework", "@RestController", "@GetMapping"),
            "FastAPI": ("fastapi", "FastAPI(", "APIRouter("),
            "Flask": ("flask", "@app.route", "Blueprint("),
            "Express": ("express", "router.get(", "app.post("),
            "NestJS": ("@Controller", "@MessagePattern", "@Cron("),
            "Django": ("django", "urlpatterns", "path("),
            "gRPC": ("grpc", "GrpcService", "ImplBase"),
        }
        for name, needles in checks.items():
            if any(needle in text for needle in needles):
                names.add(name)
    return sorted(names)


def _source_files(root: Path, project: Path | None = None) -> list[Path]:
    """Return every readable project text file used by discovery and fingerprinting."""
    def generated_docs(path: Path) -> bool:
        parts = path.relative_to(root).parts
        name = path.name.casefold()
        return (
            (len(parts) >= 2 and parts[-2].casefold() == "biz-flow")
            or name.startswith("biz-flow-")
            or name == "biz-flow-doc-generator-version.json"
        )

    def readable_text(path: Path) -> bool:
        try:
            return b"\0" not in path.read_bytes()[:8192]
        except OSError:
            return False

    files = []
    for directory, children, names in os.walk(root, followlinks=False):
        children[:] = sorted(name for name in children if name.casefold() not in _EXCLUDED_DIRS_CASEFOLD
                             and not is_alias(Path(directory) / name))
        for name in sorted(names):
            path = Path(directory) / name
            if (not is_alias(path) and path.suffix.casefold() not in {".log", ".trace", ".out"}
                    and not generated_docs(path) and readable_text(path)):
                files.append(path)
    if project is not None and files:
        # Let Git implement nested rules, negation and info/exclude semantics.
        # --no-index applies rules to archived tracked files as well.  The
        # archive supplies .gitignore, while the repository supplies info/exclude.
        git_dir = _run(project, "rev-parse", "--absolute-git-dir")
        payload = "\0".join(path.relative_to(root).as_posix() for path in files) + "\0"
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            completed = subprocess.run(["git", "--git-dir=" + git_dir, "--work-tree=" + str(normal_path(root)),
                "check-ignore", "--no-index", "-z", "--stdin"], cwd=normal_path(root),
                input=payload.encode("utf-8"), stdout=output, stderr=error)
            output.seek(0)
            ignored = set(output.read().decode("utf-8").split("\0"))
            if completed.returncode not in {0, 1}:
                error.seek(0)
                raise ValueError("SOURCE_IGNORE_FAILED: " + error.read().decode("utf-8", errors="replace"))
        files = [path for path in files if path.relative_to(root).as_posix() not in ignored]
    config = root / ".devflow-biz-flow.json"
    if config.is_file():
        settings = json.loads(config.read_text(encoding="utf-8"))
        if set(settings) != {"exclude"} or not isinstance(settings["exclude"], list) or any(not isinstance(p, str) for p in settings["exclude"]):
            raise ValueError("SOURCE_CONFIG_INVALID: .devflow-biz-flow.json accepts only exclude: string[]")
        import fnmatch
        files = [path for path in files if not any(fnmatch.fnmatchcase(path.relative_to(root).as_posix(), pattern.rstrip("/") + "/*")
                 or fnmatch.fnmatchcase(path.relative_to(root).as_posix(), pattern) for pattern in settings["exclude"])]
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _fingerprint_files(
    root: Path,
    files: list[Path],
    on_error: Callable[[str], None] | None = None,
) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            # A snapshot fingerprint describes source text, not the checkout's
            # platform line ending.  Git archives can preserve either CRLF or
            # LF depending on attributes, so normalize before hashing.
            digest.update(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        except OSError as exc:
            if on_error is not None:
                on_error(f"{relative}: cannot fingerprint source: {exc}")
            digest.update(b"<unreadable>")
    return digest.hexdigest()


def source_fingerprint(project_root: Path, target: str | None = None) -> str:
    """Compute a snapshot fingerprint without parsing source files.

    Resume uses this cheap pass to validate that cached evidence belongs to the
    same source snapshot before reconstructing a ``ScanResult``.
    """
    with source_view(project_root, target) as (root, _git):
        return _fingerprint_files(root, _source_files(root, project_root))


def scan(project_root: Path, target: str | None = None, *, entry_only: bool = False, entry_ids: set[str] | None = None) -> ScanResult:
    """Cache immutable registration inventories by target and ignore policy."""
    from dataclasses import asdict
    from ..core.artifacts import state_root, write_json
    from .evidence import ADAPTER_VERSION
    info = git_info(project_root, target)
    info.includes_uncommitted = False
    exclude = Path(_run(project_root, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = project_root / exclude
    identity = json.dumps([str(project_root.resolve()), info.target,
        exclude.read_text(encoding="utf-8", errors="replace") if exclude.is_file() else "",
        "registration-v5", ADAPTER_VERSION], ensure_ascii=False)
    cache = state_root() / "biz-flow" / "scan-cache" / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
    result = None
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        value = saved["scan"]
        if saved["sha256"] != hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest():
            raise ValueError("cache checksum mismatch")
        if value["git"]["target"] != info.target or Path(value["root"]).resolve() != project_root.resolve():
            raise ValueError("cache scope mismatch")
        value["root"] = Path(value["root"])
        value["git"] = info
        value["entries"] = [EntryPoint(**item) for item in value["entries"]]
        value["all_entries"] = [EntryPoint(**item) for item in value["all_entries"]]
        result = ScanResult(**value)
        print(f"progress stage=scan completed={len(result.files)} total={len(result.files)} cache=hit", file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError):
        result = _scan(project_root, info.target)
        value = asdict(result)
        value["root"] = str(result.root)
        write_json(cache, {"sha256": hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest(), "scan": value})
        from .evidence import trim_cache
        trim_cache(cache.parent)
    if entry_ids is not None:
        result.entries = [entry for entry in result.entries if entry.entry_id in entry_ids]
    return result


def _scan(project_root: Path, target: str | None = None) -> ScanResult:
    started = time.monotonic()
    with source_view(project_root, target) as (root, git):
        files = _source_files(root, project_root)
        print(f"progress stage=scan completed=0 total={len(files)} cache=miss", file=sys.stderr)
        entries: list[EntryPoint] = []
        unresolved: list[str] = []
        registration_audit: list[dict[str, object]] = []
        source_lines: dict[str, int] = {}
        language_names: set[str] = set()
        records: list[tuple[Path, str, str, list[FunctionInfo], dict[str, FunctionInfo], dict]] = []
        global_functions: dict[str, list[tuple[str, FunctionInfo]]] = {}
        typed_functions: dict[tuple[str, str], list[tuple[str, FunctionInfo]]] = {}
        source_texts: dict[str, str] = {}
        for path in files:
            relative = path.relative_to(root).as_posix()
            language = EXTENSIONS.get(path.suffix.lower(), "Configuration")
            if language != "Configuration":
                language_names.add(language)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                unresolved.append(f"{relative}: cannot read source: {exc}")
                continue
            source_lines[relative] = len(text.splitlines())
            source_texts[relative] = text
            funcs = _functions(text, language, relative) if language != "Configuration" else []
            _enrich_signatures(funcs, language)
            name_counts: dict[str, int] = {}
            for item in funcs:
                name_counts[item.name] = name_counts.get(item.name, 0) + 1
            by_name = {item.name: item for item in funcs if name_counts[item.name] == 1}
            mappings = {}
            records.append((path, relative, text, funcs, by_name, mappings))
            for function in funcs:
                global_functions.setdefault(function.name, []).append((relative, function))
                if function.owner:
                    typed_functions.setdefault((function.owner, function.name), []).append((relative, function))

        for path, relative, text, funcs, by_name, mappings in records:
            language = EXTENSIONS.get(path.suffix.lower(), "Configuration")
            discovered = (
                _configuration_entries(text, relative)
                if language == "Configuration"
                else _decorated_entries(text, language, relative)
            )
            if language != "Configuration":
                discovered.extend(_platform_message_entries(text, relative, funcs, source_texts))
                platform_jobs = _platform_job_entries(text, funcs)
                # 类级注册和平台模板方法描述的是同一入口，使用已绑定的接收器。
                discovered = [item for item in discovered if not any(
                    item[0] == job[0] and item[1] == job[1]
                    and (item[3] in {job[3], "代码中未确认"}
                         or re.search(r"\bclass\b", "\n".join(text.splitlines()[item[2] - 1:job[2]]).split("{", 1)[0])
                         or any(function.name == item[3] == function.owner.rsplit(".", 1)[-1]
                                for function in funcs))
                    for job in platform_jobs
                )]
                discovered.extend(platform_jobs)
            discovered = list(dict.fromkeys(discovered))
            for kind, identifier, registration_line, handler in discovered:
                # 在业务分类和调用链处理前记录注册发现，不能从最终文档反推扫描完整性。
                registration_audit.append({
                    "adapter": kind, "file": relative, "line": registration_line,
                    "identifier": identifier, "handler": handler, "status": "registered",
                    "entry_ids": [], "reason": "源代码中的触发注册或平台注册处理器声明",
                })
            known_lines = {item[2] for item in discovered}
            for registration_line, candidate in enumerate(text.splitlines(), 1):
                if re.search(r"@(?:JobHandler|XxlJob)\b", candidate) and any(
                    item[0] == "scheduled" and item[1] in candidate for item in discovered
                ):
                    known_lines.add(registration_line)
            for registration_line in _unrecognized_registration_lines(text, language, known_lines):
                registration_text = text.splitlines()[registration_line - 1]
                if discovered and (
                    re.search(r"(?:urlpatterns|routes?|url_patterns?)\s*=", registration_text, re.I)
                    or re.search(r"@(?:Controller|RestController|GrpcService|DubboService)\b", registration_text, re.I)
                ):
                    continue
                registration_audit.append({
                    "adapter": "unsupported", "file": relative, "line": registration_line,
                    "identifier": registration_text.strip(), "handler": "", "status": "unresolved",
                    "entry_ids": [], "reason": "注册标记无法映射到受支持的处理器",
                })
                unresolved.append(
                    f"{relative}:{registration_line}: registered business entry could not be mapped to a handler"
                )
            if language == "Configuration":
                registration = re.compile(
                    r"^\s*(?:routes?|consumers?|listeners?|jobs?|commands?|workflows?|websockets?|grpc[_-]?services?)\s*[:=]|"
                    r"<\s*(?:route|consumer|listener|job|task|workflow)\b",
                    re.IGNORECASE,
                )
                discovered_lines = {item[2] for item in discovered}
                for number, candidate in enumerate(text.splitlines(), 1):
                    # 通用消费者参数块不是具体消息订阅注册。
                    following_config = next((item.strip() for item in text.splitlines()[number:] if item.strip() and not item.lstrip().startswith("#")), "")
                    if re.fullmatch(r"\s*consumer\s*:\s*", candidate) and following_config.startswith("config:"):
                        continue
                    if registration.search(candidate) and number not in discovered_lines:
                        registration_audit.append({
                            "adapter": "configuration", "file": relative, "line": number,
                            "identifier": candidate.strip(), "handler": "", "status": "unresolved",
                            "entry_ids": [], "reason": "配置注册没有可证明的处理器绑定",
                        })
                        unresolved.append(
                            f"{relative}:{number}: possible business entry registration in configuration requires review"
                        )
            for kind, identifier, line, handler in discovered:
                global_candidates = global_functions.get(handler, [])
                selected = _select_handler(funcs, global_candidates, handler, line)
                handler_confirmed = selected is not None
                if kind == "url" and selected and re.search(
                    r"text/event-stream|SseEmitter|EventSource|StreamingResponse", selected.body, re.IGNORECASE
                ):
                    kind = "sse"
                # Registration discovery owns identity and scope only. Behavior
                # is expanded once by the canonical source-fact adapters.
                functions = [_capability_id(language, relative, selected, text)] if selected else []
                if not selected:
                    unresolved.append(f"{relative}:{line}: handler for {identifier} is not statically resolvable")
                entry_id = f"{kind}:{identifier}:{functions[0] if functions else f'{relative}:{handler}'}"
                if "代码中未确认" in identifier:
                    unresolved.append(f"{relative}:{line}: business entry identifier is not statically resolvable")
                entries.append(EntryPoint(
                    entry_id=entry_id,
                    kind=kind,
                    identifier=identifier,
                    handler=handler,
                    file=relative,
                    line=line,
                    module=_module_name(Path(relative), identifier, source_texts.get(relative, ""), line),
                    source=relative,
                    # Shared helpers may be reached through multiple paths;
                    # core capabilities are a unique ordered list.
                    functions=list(dict.fromkeys(functions)),
                    caller={
                        "url": "HTTP 客户端", "webhook": "Webhook 调用方", "websocket": "WebSocket 客户端",
                        "sse": "SSE 客户端",
                        "rpc": "RPC 客户端", "message": "消息生产方", "scheduled": "调度系统",
                        "event": "事件发布方", "cli": "命令行调用方", "file": "文件提供方",
                        "batch": "批处理调度方",
                    }.get(kind, "代码中未确认"),
                    binding_confirmed=True,
                    handler_confirmed=handler_confirmed,
                    title=_comment_label(text, selected.start if selected else line),
                    title_unresolved=not bool(_comment_label(text, selected.start if selected else line)),
                ))
        # 线程池提交和执行方法是已注册入口的异步步骤，不是独立入口。
        # Keep one deterministic record per registration/source handler.  The
        # same entry is often found through both an annotation and a platform
        # registry, while its stable id must survive repeated scans.
        # Presentation metadata is computed from the same adapter evidence as
        # the structural fields, so every consumer can render a complete list
        # without inspecting a private machine map.
        for entry in entries:
            entry.trigger_summary = _trigger_summary(entry)
            entry.exclusion_reason = _exclusion_reason(entry)
            entry.module_label, label_line = _module_label(source_texts.get(entry.file, ""), entry.line)
            entry.module_description = _comment_label(source_texts.get(entry.file, ""), label_line, description=True) if label_line else ""
            entry.business_name = _business_name(entry)
            # Excluded candidates may retain a descriptive technical label;
            # this label never satisfies the business-name gate.
            if entry.exclusion_reason and entry.business_name == "待确认":
                labels = {
                    "url": "HTTP 技术入口", "webhook": "Webhook 技术入口",
                    "message": "消息技术入口", "scheduled": "定时任务技术入口",
                    "event": "事件技术入口", "cli": "命令行技术入口",
                    "file": "文件技术入口", "worker": "异步任务技术入口",
                }
                entry.business_name = f"{labels.get(entry.kind, '技术入口')}：{entry.identifier}"
            evidence = [{
                "file": entry.file,
                "line": entry.line,
                "reason": "入口适配器注册、触发标识和处理器源码位置",
            }]
            evidence.extend({"file": entry.file, **item} for item in _label_evidence(
                source_texts.get(entry.file, ""), entry.line, entry.title if entry.title and not entry.title_unresolved else ""
            ))
            if entry.module_label:
                evidence.extend({"file": entry.file, **item} for item in _label_evidence(
                    source_texts.get(entry.file, ""), label_line, entry.module_label
                ))
            if entry.module_description:
                evidence.append({"file": entry.file, "line": label_line,
                                 "reason": "所属类型的 Swagger 业务说明或类注释"})
            entry.source_evidence = list(dict.fromkeys(
                (item["file"], item["line"], item["reason"]) for item in evidence
            ))
            entry.source_evidence = [
                {"file": file, "line": line, "reason": reason}
                for file, line, reason in entry.source_evidence
            ]
            entry.scope_status = "excluded" if entry.exclusion_reason else "business"
            if entry.scope_status == "business" and entry.business_name == "待确认":
                unresolved.append(f"{entry.entry_id}: business name evidence is unresolved")
            entry.module = _business_module_name(entry)
            entry.module_rationale = "按入口所属一级业务域归组；动作、渠道和触发方式作为域内业务场景。"

        # 无业务包/类型说明的轻量应用以已注册资源归域，不按查询/新增动作拆文件。
        resource_groups: dict[str, list[EntryPoint]] = {}
        for entry in entries:
            if entry.kind not in {"url", "webhook", "sse"} or entry.exclusion_reason or entry.module_label:
                continue
            resources = [part for part in entry.identifier.split(" ", 1)[-1].split("/")
                         if part and not part.startswith("{") and not re.fullmatch(r"v\d+", part, re.I)
                         and part.casefold() not in {"api", "admin", "public", "internal", "private"}]
            if resources:
                resource_groups.setdefault(resources[0], []).append(entry)
        for grouped in resource_groups.values():
            labels = sorted({entry.module for entry in grouped})
            label = labels[0]
            for other in labels[1:]:
                match = SequenceMatcher(None, label, other, autojunk=False).find_longest_match()
                label = label[match.a:match.a + match.size]
            if len(re.findall(r"[\u3400-\u9fff]", label)) >= 2:
                for entry in grouped:
                    entry.module = re.sub(r"(?:与|和|及|以及|或)+$", "", label)
                    entry.module_rationale = "同一注册资源所属一级业务域，查询及新增等动作保留在入口章节。"

        # 非版本化任务/消息处理器使用同业务声明的一级域，不将整句任务说明当作领域名。
        roles = {"controller", "query", "job", "handler", "consumer", "receiver", "recovery", "service", "impl"}
        http_entries = [entry for entry in entries if entry.kind in {"url", "webhook", "sse"} and not entry.exclusion_reason]
        for entry in entries:
            if entry.kind not in {"message", "scheduled"} or entry.exclusion_reason:
                continue
            tokens = set(_name_tokens(Path(entry.file).stem)) - roles
            candidates = [(len(tokens & (set(_name_tokens(f"{Path(candidate.file).stem} {candidate.identifier}")) - roles)), candidate)
                          for candidate in http_entries]
            candidates = [item for item in candidates if item[0] >= 2]
            if candidates:
                entry.module = max(candidates, key=lambda item: (item[0], -len(item[1].module), item[1].module))[1].module
                entry.module_rationale = "注册处理器与接口的共同声明业务对象归属同一一级业务域。"

        # 排除项的静态解析问题不应阻塞业务流程文档；它们仍保留在
        # 完整候选清单中，供用户查看排除原因。
        excluded_evidence = {
            f"{entry.file}:{entry.line}"
            for entry in entries
            if entry.exclusion_reason
        }
        unresolved = [
            finding for finding in unresolved
            if not any(evidence in finding for evidence in excluded_evidence)
            and not ("/sdk/" in finding.replace("\\", "/") and "registered business entry could not be mapped" in finding)
            and "/src/test/" not in finding.replace("\\", "/")
            and "/tests/" not in finding.replace("\\", "/")
        ]

        unique_entries: dict[tuple[str, str, str, str], EntryPoint] = {}
        for entry in entries:
            key = entry.entry_id
            existing = unique_entries.get(key)
            if existing is None or entry.line < existing.line:
                unique_entries[key] = entry
        entries = list(unique_entries.values())
        # 入口顺序按触发类型和标识稳定排序；模块是业务归属，不应改变
        # 同一项目入口清单的既有顺序。
        entries.sort(key=lambda item: (item.kind, item.identifier, item.file, item.line))
        # Capability preflight: IDs are qualified symbols, so same-named
        # methods in different classes remain distinct while an exact ID at a
        # second source location is a generation-blocking conflict.
        declaration_locations: dict[str, set[tuple[str, int]]] = {}
        for path, relative, text, funcs, _by_name, _mappings in records:
            language = EXTENSIONS.get(path.suffix.lower(), "Configuration")
            for function in funcs:
                capability = _capability_id(language, relative, function, text)
                declaration_locations.setdefault(capability, set()).add((relative, function.start))
        capability_locations: dict[str, list[dict[str, object]]] = {}
        for entry in entries:
            for capability in entry.functions:
                if capability.casefold() in _LOCAL_SYNTAX_NAMES:
                    unresolved.append(json.dumps({"code": "GENERIC_LOCAL_CAPABILITY", "capability_id": capability,
                                                  "entry_id": entry.entry_id}, ensure_ascii=False, sort_keys=True))
                    continue
                # 共享调用不构成身份冲突；比较方法声明位置，而不是调用入口位置。
                for file, line in sorted(declaration_locations.get(capability.split("@", 1)[0], set())):
                    capability_locations.setdefault(capability, []).append({
                        "entry_id": entry.entry_id,
                        "entry_identifier": entry.identifier,
                        "declaring_class": capability.split("#", 1)[0].split(":", 1)[-1],
                        "method_signature": capability.split("#", 1)[-1].split("@", 1)[0],
                        "source": f"{file}:{line}",
                        "adapter": entry.kind,
                    })
        for capability, locations in capability_locations.items():
            if len({item["source"] for item in locations}) > 1:
                unresolved.append(json.dumps({"code": "CAPABILITY_ID_CONFLICT", "capability_id": capability,
                                              "locations": locations,
                                              "suggestion": "为注册入口或声明实现补充唯一绑定"},
                                             ensure_ascii=False, sort_keys=True))
        for registration in registration_audit:
            bound = [entry for entry in entries if entry.file == registration["file"]
                     and entry.identifier == registration["identifier"] and entry.line == registration["line"]]
            registration["entry_ids"] = [entry.entry_id for entry in bound]
            if bound:
                registration["status"] = "excluded" if all(entry.exclusion_reason for entry in bound) else (
                    "business" if all(entry.handler_confirmed for entry in bound) else "unresolved"
                )
                registration["reason"] = next((entry.exclusion_reason for entry in bound if entry.exclusion_reason),
                                              "注册入口已绑定处理器并归属业务模块")
                registration["modules"] = sorted({entry.module for entry in bound if not entry.exclusion_reason})
            elif registration["status"] == "registered":
                registration["status"] = "unresolved"
                registration["reason"] = "已发现注册没有对应入口记录"
        registration_audit = [item for item in registration_audit if not (
            item["status"] == "unresolved" and (
                "/src/test/" in str(item["file"]) or "/tests/" in str(item["file"]) or "/sdk/" in str(item["file"])
            )
        )]
        coverage_gaps = [item for item in registration_audit if item["adapter"] in {"unsupported", "configuration"}
                         and item["status"] == "unresolved"]
        gap_locations = {f"{item['file']}:{item['line']}:" for item in coverage_gaps}
        unresolved = [item for item in unresolved if not any(item.startswith(location) for location in gap_locations)]
        source_fingerprint = _fingerprint_files(root, files, unresolved.append)
        print(f"progress stage=scan completed={len(files)} total={len(files)} elapsed={time.monotonic() - started:.3f}s budget=300s", file=sys.stderr)
        return ScanResult(
            root=project_root.resolve(),
            git=git,
            languages=sorted(language_names),
            frameworks=_frameworks(files),
            entries=entries,
            files=[path.relative_to(root).as_posix() for path in files],
            unresolved=sorted(dict.fromkeys(unresolved)),
            source_fingerprint=source_fingerprint,
            source_lines=source_lines,
            discovered_entry_count=len(entries),
            discovered_binding_count=sum(
                entry.binding_confirmed and entry.identifier != "代码中未确认" for entry in entries
            ),
            discovered_handler_count=len({entry.handler for entry in entries if entry.handler_confirmed and entry.handler != "代码中未确认"}),
            all_entries=list(entries),
            registration_audit=registration_audit,
            coverage_gaps=coverage_gaps,
        )
