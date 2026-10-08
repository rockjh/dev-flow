"""Conservative source discovery for business entry points and active errors."""

from __future__ import annotations

import ast
import configparser
from difflib import SequenceMatcher
import hashlib
import json
import re
import textwrap
import tomllib
from pathlib import Path
from typing import Callable

from .git import source_view
from .models import BehaviorEvidence, EntryPoint, ErrorEvidence, FunctionInfo, ScanResult

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
    "vendor", "docs", "logs", "log", "__pycache__", ".gradle", ".mvn", ".pytest_cache",
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


_BUSINESS_DOMAIN_LABELS = {
    # 通用领域词汇；未命中时仍回退到源码路径模块，避免凭空创造业务域。
    "ac": "AC",
    "user": "用户",
    "account": "账户",
    "auth": "用户认证",
    "login": "用户认证",
    "esim": "eSIM",
    "device": "设备",
    "terminal": "设备",
    "oti": "设备",
    "tbox": "车辆",
    "vehicle": "车辆",
    "car": "车辆",
    "sim": "SIM 卡",
    "iccid": "码号",
    "imsi": "码号",
    "msisdn": "码号",
    "number": "码号",
    "profile": "套餐",
    "plan": "套餐",
    "package": "套餐",
    "usage": "套餐用量",
    "operator": "运营商",
    "country": "国家地区",
    "region": "国家地区",
    "rule": "规则",
    "monitor": "监控",
    "order": "订单",
    "salearea": "销售地",
    "tsp": "TSP",
    "sms": "短信",
    "record": "记录",
    "group": "分组",
    "allocation": "分配",
    "file": "文件",
    "batch": "批量任务",
    "log": "日志",
}
_BUSINESS_ACTION_LABELS = {
    "sync": "同步", "report": "上报", "receive": "接收", "push": "推送",
    "callback": "回调", "import": "导入", "export": "导出", "query": "查询",
    "list": "查询", "get": "查询", "search": "查询", "create": "创建",
    "register": "登记", "claim": "领取", "allocate": "分配", "download": "下载",
    "delete": "删除", "remove": "删除", "update": "更新", "change": "变更",
    "status": "状态处理", "request": "请求", "generate": "生成", "process": "处理",
    "reset": "重置", "trigger": "触发", "complete": "完成", "release": "释放",
}


def _name_tokens(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", value)]
    return [token[:-1] if token.endswith("s") and token[:-1] in _BUSINESS_DOMAIN_LABELS else token for token in tokens]


def _inferred_business_name(entry: EntryPoint) -> str:
    """从入口注释、类名、路由和方法名推断可读名称，保留源码可追溯性。"""
    sources = " ".join((entry.title, entry.handler, Path(entry.file).stem, entry.identifier))
    tokens = _name_tokens(sources)
    # 批量、记录等描述处理形式，只有没有更具体业务对象时才作为模块。
    generic = {"batch", "record", "group", "allocation", "log", "sync"}
    tokens = [token for token in tokens if token not in generic] + [token for token in tokens if token in generic]
    domain = next((_BUSINESS_DOMAIN_LABELS[token] for token in tokens if token in _BUSINESS_DOMAIN_LABELS), "")
    action = next((_BUSINESS_ACTION_LABELS[token] for token in tokens if token in _BUSINESS_ACTION_LABELS), "")
    if domain and action:
        return f"{domain}{action}"
    if domain:
        return f"{domain}业务入口"
    if action:
        return f"业务{action}"
    return ""


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
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
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
    """按一级业务域归组，渠道、操作和触发方式保留在域内入口说明。"""
    aliases = {
        "user": "user", "account": "account", "auth": "auth", "login": "auth",
        "ac": "ac", "esim": "number", "sim": "number", "iccid": "number", "imsi": "number",
        "msisdn": "number", "number": "number", "device": "device", "terminal": "device",
        "oti": "device", "tbox": "vehicle", "vehicle": "vehicle", "car": "vehicle",
        "profile": "plan", "plan": "plan", "package": "plan", "usage": "usage",
        "operator": "operator", "country": "country", "region": "country", "rule": "rule",
        "monitor": "monitor", "order": "order", "salearea": "salearea", "tsp": "tsp",
        "sms": "sms", "log": "log",
    }

    def domain(value: str) -> str:
        tokens = _name_tokens(value)
        # 小写包名常把业务形容词与对象连写，如 salableplan；仍按既有业务对象归一。
        for token in tokens:
            if token in aliases:
                return aliases[token]
            for noun in ("usage", "plan", "profile", "package", "vehicle", "device"):
                if token.endswith(noun) and len(token) > len(noun):
                    return aliases[noun]
        return ""

    def display(value: str) -> str:
        if value == "usage":
            return "用量"
        label = _BUSINESS_DOMAIN_LABELS.get(value, value)
        return label if re.search(r"[\u3400-\u9fff]", label) else f"{label}业务"

    parts = list(Path(entry.file).parts[:-1])
    source_domain = next((parts[index + 1] for index, part in enumerate(parts[:-1])
                          if re.fullmatch(r"v\d+", part, re.I)), "")
    class_name = Path(entry.file).stem
    semantics = f"{class_name} {entry.identifier} {entry.module_label} {entry.business_name}"
    # 用量是独立业务域，即使注册在车辆或套餐命名空间下也不按查询渠道拆分。
    if "usage" in _name_tokens(semantics) or "用量" in entry.module_label:
        return "用量"
    # 未收录的源码一级域可由同名缩写证明，不把 DMS 等业务系统拆成配置/回调/任务。
    abbreviation = re.match(r"([A-Z][A-Z0-9_-]{1,})", entry.module_label)
    if source_domain and abbreviation and abbreviation.group(1).casefold() == source_domain.casefold():
        return display(abbreviation.group(1))
    class_tokens = _name_tokens(class_name)
    if any(token in {"sim", "esim", "iccid", "imsi", "msisdn", "number"} for token in class_tokens):
        return "码号"
    if source_domain and domain(source_domain):
        return display(domain(source_domain))
    route_resources = [part for part in entry.identifier.split(" ", 1)[-1].split("/")
                       if part and not part.startswith("{") and not re.fullmatch(r"v\d+", part, re.I)
                       and part.casefold() not in {"api", "admin", "public", "internal", "private"}]
    if route_resources and domain(route_resources[0]):
        return display(domain(route_resources[0]))
    # 套餐目录、订单、订购、履约及提醒均属于套餐域，不按运营商或销售渠道拆模块。
    if any(domain(token) == "plan" for token in _name_tokens(semantics)) or "套餐" in semantics:
        return "套餐"
    if abbreviation and not domain(abbreviation.group(1)):
        return display(abbreviation.group(1))
    for token in _name_tokens(f"{class_name} {entry.identifier}"):
        if token in aliases:
            return display(aliases[token])
    for part in reversed(parts):
        if domain(part):
            return display(domain(part))
    # 没有通用领域词时保留源码中文业务对象，去掉动作和入口形式，不猜测其他领域。
    label = entry.module_label or entry.business_name
    label = re.sub(r"^(?:查询|创建|新增|编辑|删除|配置|管理|同步|回调|通知|履约|恢复|接收|开通|变更)", "", label)
    label = re.sub(r"(?:(?:查询|创建|新增|编辑|删除|配置|管理|同步|回调|通知|履约|恢复|接收|开通|变更)[，、；：。\s]*)+$", "", label).strip("，、；：。 ")
    label = re.sub(r"(?:与|和|及|以及|或)+$", "", label).strip()
    if label and label != "待确认" and re.search(r"[\u3400-\u9fff]", label):
        return label
    return display(source_domain or entry.module)


def _error(line: str, file: str, number: int) -> ErrorEvidence:
    # Prefer the code attached to the raised/thrown error.  Conditions often
    # contain unrelated uppercase literals (for example a payment status
    # ``"PAID"``) before the actual ``raise OrderError("PAYMENT_FAILED")``.
    # Searching the whole condition first mislabels the business error.
    raised = re.search(r"(?:raise|throw|panic)\b[^\n;]*", line, re.IGNORECASE)
    code_match = (
        (CODE_RE.search(raised.group(0)) if raised else None)
        or CODE_RE.search(line)
        or ENUM_RE.search(line)
        or STATUS_CODE_RE.search(line)
    )
    code = code_match.group(1) if code_match else "代码中未确认"
    condition = line.strip()
    phase = "async" if re.search(r"\b(?:async|await|submit|enqueue|publish|send)\b", condition, re.I) else "sync"
    return ErrorEvidence(
        code=code,
        condition=condition,
        file=file,
        line=number,
        capture_boundary="入口或当前调用链抛出；未见本地捕获" if phase == "sync" else "异步任务边界；工作线程结果不回到同步响应",
        propagation="向调用方传播或由上层映射；具体映射以证据为准",
        consequence="本地写入、远端状态和后续任务结果代码中未确认",
        phase=phase,
        recovery="代码中未确认自动重试、补偿或人工恢复入口",
    )


def _source_syntax(text: str) -> str:
    """屏蔽字符串和注释，保留偏移与行号用于声明和调用匹配。"""
    return re.sub(
        r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|#[^\n]*|/\*[\s\S]*?\*/',
        lambda match: re.sub(r"[^\n]", " ", match.group()), text,
    )


def _qualified_calls(body: str) -> list[tuple[str, str]]:
    """Keep receiver information so a same-named method is not merged blindly."""
    body = _source_syntax(body)
    calls = [
        (receiver, name)
        for receiver, name in re.findall(
            r"\b(?:self\s*\.\s*)?([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)\s*\(", body
        )
        if receiver not in {"self", "cls", "super"}
    ]
    return list(dict.fromkeys(calls))


def _functions(text: str, language: str, relative: str) -> list[FunctionInfo]:
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
                    _calls("\n".join(lines[node.lineno - 1:node.end_lineno])),
                    _python_errors("\n".join(lines[node.lineno - 1:node.end_lineno]), relative, node.lineno),
                    owner=_python_owner(root, node),
                    qualified_calls=_qualified_calls("\n".join(lines[node.lineno - 1:node.end_lineno])),
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
                name, start + 1, end, body, _calls(body), _python_errors(body, relative, start + 1),
                qualified_calls=_qualified_calls(body),
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
            name, start + 1, end, body, _calls(body), _c_style_errors(body, relative, start + 1),
            owner=owner,
            qualified_calls=_qualified_calls(body),
        ))
    return result


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


def _calls(body: str) -> list[str]:
    body = _source_syntax(body)
    ignored = {"if", "for", "while", "switch", "catch", "return", "raise", "throw", "def", "class"}
    names = [name for name in CALL_RE.findall(body) if name not in ignored]
    names.extend(
        name
        for name in re.findall(r"\b(?:submit|create_task|spawn|schedule|enqueue|delay)\s*\(\s*([A-Za-z_]\w*)", body)
        if name not in ignored
    )
    return list(dict.fromkeys(names))


def _unresolved_call(name: str) -> bool:
    if name.lower() in IGNORED_EXTERNAL_CALLS:
        return False
    if name.endswith(("Error", "Exception", "ErrorCode")):
        return False
    return True


def _errors(body: str, relative: str, offset: int) -> list[ErrorEvidence]:
    lines = body.splitlines()
    found: list[ErrorEvidence] = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("#", "//", "/*", "*")) or not ERROR_RE.search(line):
            continue
        condition = line.strip()
        guard = next(
            (
                candidate.strip()
                for candidate in reversed(lines[max(0, index - 4):index])
                if re.search(r"\b(?:if|unless|when)\b", candidate)
            ),
            "",
        )
        if guard:
            condition = f"{guard} -> {condition}"
        found.append(_error(condition, relative, offset + index))
    return found


def _python_errors(body: str, relative: str, offset: int) -> list[ErrorEvidence]:
    try:
        root = ast.parse(textwrap.dedent(body))
    except SyntaxError:
        return _errors(body, relative, offset)
    function = next((node for node in root.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if function is None:
        return _errors(body, relative, offset)
    found: list[ErrorEvidence] = []

    def exception_name(node: ast.AST | None) -> str:
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    normalized = textwrap.dedent(body)

    def source_of(node: ast.AST) -> str:
        return ast.get_source_segment(normalized, node) or "代码中未确认"

    def visit(
        statements: list[ast.stmt],
        caught: set[str],
        conditions: tuple[str, ...] = (),
        loop_depth: int = 0,
    ) -> None:
        terminated = False
        for statement in statements:
            if terminated:
                break
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(statement, ast.Raise):
                name = exception_name(statement.exc)
                is_caught = bool(
                    name and (name in caught or "*" in caught or "Exception" in caught or "BaseException" in caught)
                )
                if is_caught and loop_depth:
                    source = source_of(statement)
                    condition = f"{' 且 '.join(conditions)} -> {source}" if conditions else source
                    item_error = _error(condition, relative, offset + statement.lineno - 1)
                    item_error.capture_boundary = "循环单项捕获边界；异常未传播到入口"
                    item_error.propagation = "当前项记录失败并继续后续项；不改写整批同步响应"
                    item_error.consequence = "当前项失败；已处理项和后续项按源码路径继续，批次不因该项立即终止"
                    item_error.phase = "item"
                    item_error.recovery = "仅记录当前项失败；是否重试或补偿须由源码另行确认"
                    found.append(item_error)
                if is_caught:
                    continue
                source = source_of(statement)
                condition = f"{' 且 '.join(conditions)} -> {source}" if conditions else source
                found.append(_error(condition, relative, offset + statement.lineno - 1))
                terminated = True
                continue
            if isinstance(statement, ast.Try):
                handler_types = {exception_name(handler.type) or "*" for handler in statement.handlers}
                visit(statement.body, caught | handler_types, conditions, loop_depth)
                for handler in statement.handlers:
                    visit(handler.body, caught, conditions, loop_depth)
                visit(statement.orelse, caught, conditions, loop_depth)
                visit(statement.finalbody, caught, conditions, loop_depth)
                continue
            if isinstance(statement, ast.If):
                condition = source_of(statement.test)
                visit(statement.body, caught, (*conditions, condition), loop_depth)
                visit(statement.orelse, caught, (*conditions, f"非（{condition}）"), loop_depth)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                condition = source_of(statement.target if isinstance(statement, (ast.For, ast.AsyncFor)) else statement.test)
                visit(statement.body, caught, (*conditions, condition), loop_depth + 1)
                visit(statement.orelse, caught, (*conditions, f"循环结束：{condition}"), loop_depth)
                continue
            if isinstance(statement, (ast.Return, ast.Break, ast.Continue)):
                terminated = True
                continue
            child_blocks = [
                value for _, value in ast.iter_fields(statement)
                if isinstance(value, list) and value and all(isinstance(item, ast.stmt) for item in value)
            ]
            for block in child_blocks:
                visit(block, caught, conditions, loop_depth)

    visit(function.body, set())
    return found


def _caught_calls(body: str) -> set[str]:
    try:
        root = ast.parse(textwrap.dedent(body))
    except SyntaxError:
        return set()
    caught: set[str] = set()
    def exception_name(node: ast.AST | None) -> str:
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    for statement in ast.walk(root):
        if not isinstance(statement, ast.Try):
            continue
        types = {"*"}
        explicit = {exception_name(handler.type) for handler in statement.handlers if handler.type is not None}
        if explicit:
            types = explicit
        if not types:
            continue
        for nested in ast.walk(ast.Module(body=statement.body, type_ignores=[])):
            if not isinstance(nested, ast.Call):
                continue
            if "*" in types or types & {"Exception", "BaseException", "BusinessError", "Error"}:
                if isinstance(nested.func, ast.Name):
                    caught.add(nested.func.id)
                elif isinstance(nested.func, ast.Attribute):
                    caught.add(nested.func.attr)
    return caught


def _c_style_errors(body: str, relative: str, offset: int) -> list[ErrorEvidence]:
    caught_lines: set[int] = set()
    pattern = re.compile(
        r"try\s*\{(?P<body>.*?)\}\s*catch\s*\((?P<parameter>[^)]*)\)",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        type_match = re.search(r"\b([A-Za-z_]\w*(?:Exception|Error|Throwable))\b", match.group("parameter"))
        catch_type = type_match.group(1) if type_match else "*"
        start_line = body[:match.start("body")].count("\n")
        for throw in re.finditer(r"\bthrow\s+new\s+([A-Za-z_]\w*)", match.group("body")):
            thrown = throw.group(1)
            if catch_type == "*" or catch_type in {thrown, "Exception", "RuntimeException", "Throwable", "Error"}:
                caught_lines.add(start_line + match.group("body")[:throw.start()].count("\n"))
    return [
        error
        for error in _errors(body, relative, offset)
        if error.line - offset not in caught_lines
    ]


def _c_style_caught_calls(body: str) -> set[str]:
    caught: set[str] = set()
    pattern = re.compile(
        r"try\s*\{(?P<body>.*?)\}\s*catch\s*\((?P<parameter>[^)]*)\)",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        parameter = match.group("parameter")
        if re.search(r"(?:Exception|Error|Throwable)|^\s*[A-Za-z_]\w*\s*$", parameter):
            caught.update(
                name for name in CALL_RE.findall(match.group("body"))
                if name not in {"if", "for", "while", "try", "catch", "throw", "return"}
            )
    return caught


def _exception_mappings(text: str, relative: str) -> dict[str, ErrorEvidence]:
    lines = text.splitlines()
    mappings: dict[str, ErrorEvidence] = {}
    for index, line in enumerate(lines):
        marker = re.search(
            r"(?:@ExceptionHandler|exception_handler|errorhandler|exceptionHandler)\s*\(\s*([A-Za-z_]\w*)",
            line,
        )
        if not marker:
            continue
        exception = marker.group(1)
        for offset, candidate in enumerate(lines[index:index + 20]):
            code = CODE_RE.search(candidate) or ENUM_RE.search(candidate) or STATUS_CODE_RE.search(candidate)
            if code:
                mappings[exception] = ErrorEvidence(code.group(1), f"统一异常处理器将 {exception} 转换为 {code.group(1)}", relative, index + offset + 1)
                break
    return mappings


BEHAVIOR_PATTERNS = (
    ("循环", re.compile(r"^\s*(?:for|while|foreach)\b", re.I)),
    ("分支", re.compile(r"^\s*else\b", re.I)),
    ("校验", re.compile(r"\b(assert|validate|validation|require|check|guard|verify)\b|\bif\s*\(", re.I)),
    ("事务", re.compile(r"@Transactional|\b(transaction|commit|rollback)\b", re.I)),
    ("锁与幂等", re.compile(r"\b(lock|unlock|synchronized|idempot|dedup|compareAndSet|nonce)\b", re.I)),
    ("持久化", re.compile(r"\b(repository|dao|save|insert|update|delete|persist|select|query|findBy)\b", re.I)),
    ("外部调用", re.compile(r"\b(requests|httpx|urllib|RestTemplate|WebClient|grpc|axios|fetch|httpClient)\b", re.I)),
    ("消息", re.compile(r"\b(kafka|rabbit|rocketmq|pulsar|publish|producer|send|emit)\b", re.I)),
    ("异步", re.compile(r"\b(async|await|executor|threadPool|future|submit)\b", re.I)),
    ("缓存或文件", re.compile(r"\b(cache|redis|memcached|open|read|write|file|path)\b", re.I)),
    ("状态变化", re.compile(r"\b(status|state)\b\s*(?:=|\.|,)|setStatus|setState", re.I)),
    ("结果", re.compile(r"^\s*(?:return|yield)\b", re.I)),
)


def _behaviors(function: FunctionInfo, relative: str) -> list[BehaviorEvidence]:
    evidence: list[BehaviorEvidence] = []
    for offset, line in enumerate(function.body.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*")):
            continue
        # Python control flow is business evidence even when the localized
        # behavior table is unavailable or encoded differently.
        if re.match(r"^if\b", stripped):
            evidence.append(BehaviorEvidence("校验", stripped, relative, function.start + offset))
        for kind, pattern in BEHAVIOR_PATTERNS:
            if pattern.search(stripped):
                evidence.append(BehaviorEvidence(kind, stripped, relative, function.start + offset))
    return evidence


def _declaration_behaviors(function: FunctionInfo, relative: str, text: str) -> list[BehaviorEvidence]:
    lines = text.splitlines()
    start = max(0, function.start - 8)
    evidence: list[BehaviorEvidence] = []
    for index in range(start, function.start - 1):
        stripped = lines[index].strip()
        if not stripped.startswith(("@", "[")):
            continue
        for kind, pattern in BEHAVIOR_PATTERNS:
            if pattern.search(stripped):
                evidence.append(BehaviorEvidence(kind, stripped, relative, index + 1))
    return evidence


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

    declarations = _functions(text, language, relative) if language == "Java" else []
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
        if outbound_only and re.search(
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
            (stripped.startswith("@") and re.search(r"@?(?:XxlJob|JobHandler|Scheduled|Cron)\b", annotation_text, re.I))
            or re.search(r"\b(?:schedule|scheduler\.add_job|add_job)\s*\(", stripped, re.I)
        ):
            value = re.search(r"(?:cron|fixedDelay|fixedRate|fixedDelayString|fixedRateString|name|value)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", annotation_text, re.I)
            kind, identifier = "scheduled", next((item for item in (value.groups() if value else ()) if item), "代码中未确认")
        elif (
            (stripped.startswith("@") and re.search(
                r"(?:EventListener|EventPattern|MessagePattern|Transition|Workflow|state_machine)", stripped, re.I
            ))
            or re.search(r"\b(?:event_handler|on_event)\s*\(", stripped, re.I)
        ):
            value = re.search(r"(?:classes|value|pattern|event)\s*=\s*[\"']([^\"']+)", stripped, re.I)
            kind, identifier = "event", (value.group(1) if value else "代码中未确认")
        elif re.match(r"@(?:click\.command|app\.command|typer\.command|Command)\s*\(", stripped, re.I):
            value = re.search(r"(?:name|value)\s*=\s*[\"']([^\"']+)|\(\s*[\"']([^\"']+)", stripped, re.I)
            kind, identifier = "cli", next((item for item in (value.groups() if value else ()) if item), "代码中未确认")
        elif re.search(r"@OnMessage\b|(?:socketio|io)\.on\s*\(", stripped, re.I):
            value = re.search(r"\(\s*[\"']([^\"']+)", stripped)
            kind, identifier = "websocket", (value.group(1) if value else "代码中未确认")
        elif re.search(r"\b(?:FileListener|OnFile|FileSystemEventHandler|watchdog)\b", stripped, re.I):
            kind, identifier = "file", "代码中未确认"
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
            following = next((function for function in declarations if function.start > index + 1), None)
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
                identifiers = [resolve_value(topic[0] or topic[1]) for topic in identifiers]
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
        return_match = re.search(r"\)\s*(?:->\s*([\w.<>\[\]]+)|:\s*([\w.<>\[\]]+))", head)
        function.return_type = next((value for value in (return_match.groups() if return_match else ()) if value), "")


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
        r"\b(?:app|router|blueprint|bp|r|mux)\.(?:get|post|put|patch|delete|all|route|api_route|add_api_route)\s*\(\s*[\"']",
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


def _source_files(root: Path) -> list[Path]:
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

    return sorted(
        (
            path for path in root.rglob("*")
            if path.is_file()
            and not any(part.casefold() in _EXCLUDED_DIRS_CASEFOLD for part in path.parts)
            and path.suffix.casefold() not in {".log", ".trace", ".out"}
            and not generated_docs(path)
            and readable_text(path)
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )


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
            digest.update(path.read_bytes())
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
        return _fingerprint_files(root, _source_files(root))


def scan(project_root: Path, target: str | None = None, *, entry_only: bool = False, entry_ids: set[str] | None = None) -> ScanResult:
    with source_view(project_root, target) as (root, git):
        files = _source_files(root)
        entries: list[EntryPoint] = []
        unresolved: list[str] = []
        registration_audit: list[dict[str, object]] = []
        source_lines: dict[str, int] = {}
        language_names: set[str] = set()
        records: list[tuple[Path, str, str, list[FunctionInfo], dict[str, FunctionInfo], dict[str, ErrorEvidence]]] = []
        global_functions: dict[str, list[tuple[str, FunctionInfo]]] = {}
        typed_functions: dict[tuple[str, str], list[tuple[str, FunctionInfo]]] = {}
        global_mappings: dict[str, list[ErrorEvidence]] = {}
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
            mappings = _exception_mappings(text, relative)
            records.append((path, relative, text, funcs, by_name, mappings))
            for exception, mapping in mappings.items():
                global_mappings.setdefault(exception, []).append(mapping)
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
                errors: list[ErrorEvidence] = []
                functions: list[str] = []
                bodies: list[str] = []
                behaviors: list[BehaviorEvidence] = []
                registered_id = f"{kind}:{identifier}:{_capability_id(language, relative, selected, text) if selected else f'{relative}:{handler}'}"
                excluded = _exclusion_reason(EntryPoint(registered_id, kind, identifier, handler, relative, line, "", relative))
                shallow = entry_only or bool(excluded) or (entry_ids is not None and registered_id not in entry_ids)
                if selected and shallow:
                    functions.append(_capability_id(language, relative, selected, text))
                elif selected:
                    pending: list[tuple[str, str, str]] = [(relative, selected.name, selected.owner)]
                    seen: set[tuple[str, str, str]] = set()
                    async_nodes: set[tuple[str, str, str]] = set()
                    while pending:
                        current_file, name, owner_hint = pending.pop(0)
                        key = (current_file, name, owner_hint)
                        if key in seen:
                            continue
                        seen.add(key)
                        if owner_hint:
                            candidates = typed_functions.get((owner_hint, name), [])
                        else:
                            candidates = (
                                [(current_file, by_name[name])]
                                if current_file == relative and name in by_name
                                else global_functions.get(name, [])
                            )
                        if not candidates:
                            if not _unresolved_call(name):
                                continue
                            unresolved.append(f"{relative}:{line}: called function {name} is outside this repository or not statically resolvable")
                            continue
                        if len(candidates) > 1:
                            unresolved.append(f"{relative}:{line}: call {name} has multiple possible definitions")
                            # A same-named method in another service is not evidence of a
                            # reachable call. Keep the edge unresolved instead of merging
                            # unrelated side effects and error codes into this entry.
                            continue
                        for candidate_file, function in candidates:
                            capability = _capability_id(
                                EXTENSIONS.get(Path(candidate_file).suffix.lower(), language),
                                candidate_file,
                                function,
                                source_texts.get(candidate_file, ""),
                            )
                            if function.name.casefold() not in _LOCAL_SYNTAX_NAMES:
                                functions.append(capability)
                            bodies.append(function.body)
                            for error in function.errors:
                                if key in async_nodes:
                                    errors.append(ErrorEvidence(
                                        error.code,
                                        error.condition,
                                        error.file,
                                        error.line,
                                        "后台工作线程边界；结果不会回到已返回的同步响应",
                                        "工作线程失败写入日志或任务状态；同步入口不再传播该异常",
                                        "入口已受理；后台任务终态失败，具体持久化结果以源码为准",
                                        "worker",
                                        "是否重试、补偿或人工恢复须由后台任务实现确认",
                                    ))
                                else:
                                    errors.append(error)
                            behaviors.extend(
                                _declaration_behaviors(function, candidate_file, source_texts.get(candidate_file, ""))
                            )
                            behaviors.extend(_behaviors(function, candidate_file))
                            caught_calls = _caught_calls(function.body) | _c_style_caught_calls(function.body)
                            receiver_types: dict[str, str] = {}
                            for receiver, called_name in function.qualified_calls:
                                type_match = re.search(
                                    rf"(?:\b{re.escape(receiver)}\b\s*:\s*|\b{re.escape(receiver)}\b\s*=\s*(?:new\s+)?)"
                                    r"([A-Za-z_]\w*)",
                                    function.body,
                                )
                                if type_match:
                                    receiver_types[called_name] = type_match.group(1)
                                elif language == "Java":
                                    # Java 的依赖常声明为类字段；局部变量和参数优先，不能只查赋值表达式。
                                    declaration = re.search(
                                        rf"\b([A-Za-z_]\w*)(?:\s*<[^;{{}}]+?>)?\s+{re.escape(receiver)}\s*(?=[,;=)])",
                                        function.body,
                                    ) or re.search(
                                        rf"\b([A-Za-z_]\w*)(?:\s*<[^;{{}}]+?>)?\s+{re.escape(receiver)}\s*(?=[;=])",
                                        source_texts.get(candidate_file, ""),
                                    )
                                    if declaration:
                                        receiver_types[called_name] = declaration.group(1)
                            qualified_names = {name for _, name in function.qualified_calls}
                            submitted_workers = {name for name, _line, _executor in _executor_submissions(function.body, candidate_file) if name}
                            for call in dict.fromkeys([*function.calls, *sorted(submitted_workers)]):
                                if call in caught_calls:
                                    continue
                                owner = receiver_types.get(call, "")
                                if owner and (owner, call) not in typed_functions and re.search(
                                    rf"\bimport\s+[\w.]+\.{re.escape(owner)}\s*;",
                                    source_texts.get(candidate_file, ""),
                                ) and not any(path.name == f"{owner}.java" for path in files):
                                    # 可证明是项目外类型时保留调用边界，不把 SDK 实现缺失报成内部未知调用。
                                    behaviors.append(BehaviorEvidence("外部调用", f"{owner}.{call}", candidate_file, function.start))
                                    continue
                                if call in qualified_names and not owner:
                                    # An unresolved receiver such as ``client.save()`` must not
                                    # be matched to an unrelated global ``save`` function.
                                    unresolved.append(
                                        f"{candidate_file}:{function.start}: qualified call {call} has an unknown receiver type"
                                    )
                                    continue
                                child_key = (candidate_file, call, owner)
                                if child_key not in seen:
                                    pending.append(child_key)
                                    if call in submitted_workers or re.search(
                                        rf"\b(?:submit|execute|create_task|spawn|schedule|enqueue|delay)\s*\([^\n)]*\b{re.escape(call)}\b",
                                        function.body,
                                        re.IGNORECASE,
                                    ):
                                        async_nodes.add(child_key)
                else:
                    unresolved.append(f"{relative}:{line}: handler for {identifier} is not statically resolvable")
                entry_capability = functions[0] if functions else f"{relative}:{handler}"
                entry_id = f"{kind}:{identifier}:{entry_capability}"
                mapped_errors: list[ErrorEvidence] = []
                for error in errors:
                    if error.code == "代码中未确认":
                        exception = re.search(r"(?:raise|throw\s+new)\s+([A-Za-z_]\w*)", error.condition)
                        candidates = global_mappings.get(exception.group(1), []) if exception else []
                        if len(candidates) == 1:
                            mapping = candidates[0]
                            error = ErrorEvidence(
                                mapping.code,
                                f"{error.condition}；{mapping.condition}（映射证据：{mapping.file}:{mapping.line}）",
                                error.file,
                                error.line,
                                error.capture_boundary,
                                error.propagation,
                                error.consequence,
                                error.phase,
                                error.recovery,
                            )
                        elif len(candidates) > 1:
                            unresolved.append(f"{relative}:{line}: exception {exception.group(1)} has multiple outward mappings")
                    mapped_errors.append(error)
                unique_errors: list[ErrorEvidence] = []
                seen_errors: set[tuple[str, str, int]] = set()
                for error in mapped_errors:
                    key = (error.code, error.file, error.line)
                    if key not in seen_errors:
                        seen_errors.add(key)
                        unique_errors.append(error)
                for error in unique_errors:
                    if error.code == "代码中未确认":
                        unresolved.append(
                            f"{error.file}:{error.line}: active error code for {identifier} is not statically resolvable"
                        )
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
                    errors=unique_errors,
                    behaviors=behaviors,
                    caller={
                        "url": "HTTP 客户端", "webhook": "Webhook 调用方", "websocket": "WebSocket 客户端",
                        "sse": "SSE 客户端",
                        "rpc": "RPC 客户端", "message": "消息生产方", "scheduled": "调度系统",
                        "event": "事件发布方", "cli": "命令行调用方", "file": "文件提供方",
                        "batch": "批处理调度方",
                    }.get(kind, "代码中未确认"),
                    input_summary=(selected.body.splitlines()[0].strip() if selected else "代码中未确认"),
                    has_loop=bool(bodies and re.search(r"\b(for|while|foreach)\b", "\n".join(bodies))),
                    has_external_call=bool(bodies and re.search(r"\b(requests|httpx|urllib|RestTemplate|WebClient|grpc|axios|fetch)\b", "\n".join(bodies), re.I)),
                    has_persistence=bool(bodies and re.search(r"\b(save|insert|update|delete|persist|repository|dao|\.create\s*\()", "\n".join(bodies), re.I)),
                    has_async=bool(bodies and re.search(r"\b(async|await|thread|executor|queue|publish|send)\b", "\n".join(bodies), re.I)),
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
        source_fingerprint = _fingerprint_files(root, files, unresolved.append)
        return ScanResult(
            root=project_root.resolve(),
            git=git,
            languages=sorted(language_names),
            frameworks=_frameworks(files),
            entries=[entry for entry in entries if entry_ids is None or entry.entry_id in entry_ids],
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
        )
