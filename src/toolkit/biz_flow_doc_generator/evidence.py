"""Source inventories. Adapters are statically registered, never loaded from projects."""

from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from dataclasses import asdict, dataclass
from typing import Protocol

from .discovery import _capability_id, _enrich_signatures, _functions
from .git import source_view
from .models import BranchEvidence, EntryPoint, FunctionInfo, PersistenceAction, ScanResult


RESOURCE_TYPES = {
    "relational_table", "document_collection", "kv_namespace", "search_index",
    "object_storage", "file_resource", "external_resource",
}


@dataclass(frozen=True)
class SourceContext:
    entry: EntryPoint
    source_file: str
    function: str
    start_line: int
    text: str
    project_sources: dict[str, str]


class PersistenceEvidenceAdapter(Protocol):
    def can_handle(self, project_context: SourceContext) -> bool: ...

    def analyze(self, source_context: SourceContext) -> list[PersistenceAction]: ...


class BranchEvidenceAdapter(Protocol):
    """Project supplied branch extractor; language/framework agnostic."""

    def can_handle(self, source_context: SourceContext) -> bool: ...

    def branches(self, source_context: SourceContext) -> list[BranchEvidence]: ...


def evidence_id(prefix: str, context: SourceContext, value: str, ordinal: int) -> str:
    # Line numbers are evidence, not identity: adding blank lines preserves IDs.
    key = f"{context.entry.entry_id}|{context.source_file}|{context.function}|{value}|{ordinal}"
    return f"{prefix}-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


class LiteralStorageAdapter:
    """Literal SQL and explicitly named storage API operations; no naming guesses."""

    def can_handle(self, project_context: SourceContext) -> bool:
        return project_context.source_file.endswith((".py", ".java", ".xml"))

    def analyze(self, source_context: SourceContext) -> list[PersistenceAction]:
        context = source_context
        actions = []
        # SQL joins are separate reads. Dynamic identifiers never become table names.
        sql = re.compile(
            r"\b(?P<op>FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
            r"[`\"]?(?P<name>[A-Za-z_][\w.]*)[`\"]?", re.I,
        )
        operations = {"from": "read", "join": "read", "insert into": "insert", "update": "update", "delete from": "delete"}
        for match in sql.finditer(context.text):
            op = operations[re.sub(r"\s+", " ", match["op"].lower())]
            actions.append(self._action(context, match, "relational_table", match["name"], op, len(actions)))
        # Explicit object names only. A variable/concatenation is an unresolved action.
        patterns = (
            (r'\b(?:collection|get_collection)\(\s*["\']([^"\']+)["\']\s*\)\.(find_one|find|insert_one|update_one|delete_one)\(', "document_collection"),
            (r'\b[A-Za-z_]\w*\.(get|set|delete|hget|hset)\(\s*["\']([^"\']+)["\']\s*[,)]', "kv_namespace"),
            (r'\b(?:open|Path)\(\s*["\']([^"\']+)["\']\s*[,)]', "file_resource"),
            (r'\b(?:search|index|delete)\(\s*index\s*=\s*["\']([^"\']+)["\']\s*[,)]', "search_index"),
            (r'\b(?:get_object|put_object|delete_object)\(\s*Bucket\s*=\s*["\']([^"\']+)["\']\s*,\s*Key\s*=\s*["\']([^"\']+)["\']\s*[,)]', "object_storage"),
        )
        for pattern, kind in patterns:
            for match in re.finditer(pattern, context.text):
                name = match[2] if kind == "kv_namespace" else match[1]
                if kind == "object_storage":
                    name += "/" + match[2]
                operation = match[1] if kind == "kv_namespace" else (match[2] if kind == "document_collection" else match[0].split("(")[0])
                actions.append(self._action(context, match, kind, name, operation, len(actions)))
        return actions

    @staticmethod
    def _action(context, match, kind, name, operation, ordinal):
        label_match = re.search(r"devflow:persistence(?:-name)?\s*[:=]\s*([^\n]+)", context.text)
        display_name = label_match.group(1).strip() if label_match else ""
        return PersistenceAction(
            evidence_id("P", context, f"{kind}:{name}:{operation}", ordinal), kind, name, display_name,
            operation, None, [], context.source_file,
            context.start_line + context.text[:match.start()].count("\n"),
        )


class PythonEvidenceAdapter:
    def can_handle(self, context: SourceContext) -> bool:
        return context.source_file.endswith(".py")

    def branches(self, context: SourceContext) -> list[BranchEvidence]:
        tree = ast.parse(textwrap.dedent(context.text))
        result = []
        # Conservatively include control decisions, exception boundaries, short
        # circuits and early returns; only evidence-backed exclusions may remove them.
        kinds = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                 ast.Assert, ast.BoolOp, ast.Raise, ast.Match)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        nodes = [n for n in ast.walk(tree) if isinstance(n, kinds)]
        # A plain terminal return is not a decision.  Include an early return
        # only when a surrounding control construct makes it a business branch.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return):
                continue
            parent = parents.get(node)
            while parent is not None and not isinstance(parent, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler)):
                parent = parents.get(parent)
            if parent is not None:
                nodes.append(node)
        for node in sorted(nodes, key=lambda n: (n.lineno, n.col_offset)):
            target = getattr(node, "test", None) or getattr(node, "iter", None) or getattr(node, "type", None)
            condition = ast.unparse(target or node).splitlines()[0]
            kind = type(node).__name__
            reachability = "reachable"
            business_relevant: bool | None = True
            handler = node if isinstance(node, ast.ExceptHandler) else parents.get(node)
            if isinstance(handler, ast.ExceptHandler) and isinstance(node, (ast.ExceptHandler, ast.Return)):
                try_node = parents.get(handler)
                # 被调用且返回值被丢弃的纯辅助回退，不改变入口结果；保留有实际处理动作的捕获。
                if (isinstance(try_node, ast.Try) and self._ignored_helper_return(context)
                        and self._swallows_without_business_effect(handler, context)
                        and not try_node.orelse
                        and all(isinstance(statement, (ast.Raise, ast.Pass))
                                or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
                                for statement in try_node.body)):
                    business_relevant = False
            if isinstance(node, ast.Raise):
                child, ancestor = node, parents.get(node)
                while ancestor is not None and not isinstance(ancestor, ast.Try):
                    child, ancestor = ancestor, parents.get(ancestor)
                raised_func = getattr(getattr(node, "exc", None), "func", None)
                raised_name = ast.unparse(raised_func) if raised_func is not None else None
                # 同一个 try 的 handler/else/finally 内抛出的异常不由其自身 handler 捕获。
                if isinstance(ancestor, ast.Try) and child in ancestor.body and raised_name:
                    for handler in ancestor.handlers:
                        caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                        matches = handler.type is None or raised_name in [ast.unparse(value) for value in caught if value]
                        following = ancestor.body[ancestor.body.index(child) + 1:]
                        skipped_business_path = bool(ancestor.orelse) or any(
                            not isinstance(statement, ast.Pass)
                            and not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
                            for statement in following)
                        if matches and not skipped_business_path and self._swallows_without_business_effect(handler, context):
                            business_relevant = False
                            break
            outcomes = ["true", "false"]
            if isinstance(node, (ast.For, ast.AsyncFor)):
                outcomes = ["nonempty", "empty"]
            elif isinstance(node, ast.ExceptHandler):
                outcomes = ["caught", "propagated"]
            elif isinstance(node, (ast.Return, ast.Raise)):
                outcomes = [ast.unparse(node)]
            elif isinstance(node, ast.Match):
                outcomes = [ast.unparse(case.pattern) for case in node.cases]
            result.append(BranchEvidence(
                evidence_id("B", context, f"{kind}:{condition}", sum(b.condition == condition for b in result)),
                context.source_file, context.start_line + node.lineno - 1,
                condition, outcomes, [ast.unparse(node)], reachability, business_relevant,
            ))
        return result


    @staticmethod
    def _swallows_without_business_effect(handler: ast.ExceptHandler, context: SourceContext) -> bool:
        """只有明确吞掉且没有业务结果/副作用的辅助异常才排除。"""
        for statement in handler.body:
            if isinstance(statement, ast.Pass):
                continue
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                continue
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value.func
                if (isinstance(call, ast.Attribute)
                        and ast.unparse(call.value).split(".")[-1] in {"logger", "log", "logging"}
                        and call.attr in {"debug", "info", "warning", "warn", "error", "exception", "critical"}):
                    continue
            if isinstance(statement, ast.Return) and PythonEvidenceAdapter._ignored_helper_return(context):
                try:
                    ast.literal_eval(statement.value) if statement.value is not None else None
                    continue
                except (ValueError, TypeError):
                    pass
            return False
        return True

    @staticmethod
    def _ignored_helper_return(context: SourceContext) -> bool:
        """仅排除同文件辅助方法的纯字面量回退，且所有源码调用都丢弃返回值。"""
        handler_name = context.entry.handler.rsplit("#", 1)[-1].split("(", 1)[0].rsplit(".", 1)[-1]
        if context.function == handler_name or context.source_file != context.entry.file:
            return False
        for file, text in context.project_sources.items():
            if file != context.source_file and re.search(r"\b" + re.escape(context.function) + r"\s*\(", text):
                return False
        tree = ast.parse(context.project_sources.get(context.source_file, ""))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        definitions = [node for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == context.function]
        if len(definitions) != 1:
            return False
        # return 回退会跳过后续操作；只有顶层 try 之后不再产生业务动作才可排除。
        for node in ast.walk(definitions[0]):
            if not isinstance(node, ast.Return) or not isinstance(parents.get(node), ast.ExceptHandler):
                continue
            try_node = parents.get(parents[node])
            if parents.get(try_node) is not definitions[0]:
                return False
            following = definitions[0].body[definitions[0].body.index(try_node) + 1:]
            if any(not isinstance(statement, ast.Return) for statement in following):
                return False
            for statement in following:
                try:
                    ast.literal_eval(statement.value) if statement.value is not None else None
                except (ValueError, TypeError):
                    return False
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and getattr(node.func, "id", getattr(node.func, "attr", None)) == context.function]
        return bool(calls) and all(isinstance(parents.get(call), ast.Expr) for call in calls)


class JavaEvidenceAdapter:
    """Bounded Java source adapter; complex syntax is a blocking unknown."""

    def can_handle(self, context: SourceContext) -> bool:
        return context.source_file.endswith(".java")

    def branches(self, context: SourceContext) -> list[BranchEvidence]:
        text = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                      lambda m: "\n" * m[0].count("\n") if m[0].startswith(("//", "/*")) else '"literal"',
                      context.text, flags=re.S)
        result = []
        pattern = r"\b(if|for|while|switch|catch)\s*\(|\b(return|throw)\b[^;]*;|\?|&&|\|\|"
        for match in re.finditer(pattern, text):
            end = match.end()
            reachability = "reachable"
            if match[1]:
                depth = 1
                while end < len(text) and depth:
                    depth += (text[end] == "(") - (text[end] == ")")
                    end += 1
                if depth:
                    reachability = "unknown"
            condition = text[match.start():end].strip()
            if condition in {"?", "&&", "||"}:
                reachability = "unknown"
            result.append(BranchEvidence(
                evidence_id("B", context, condition, sum(b.condition == condition for b in result)),
                context.source_file, context.start_line + text[:match.start()].count("\n"),
                condition, ["taken", "not_taken"] if match[1] else [condition], [condition],
                reachability, True if reachability == "reachable" else None,
            ))
        return result


def _declared_outcomes(context: SourceContext) -> list[str]:
    """Extract explicit return/throw outcomes without inventing a result."""
    if context.source_file.endswith(".py"):
        try:
            tree = ast.parse(textwrap.dedent(context.text))
        except SyntaxError:
            return []
        values: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Return):
                values.append(ast.unparse(node.value) if node.value is not None else "return")
            elif isinstance(node, ast.Raise):
                values.append(ast.unparse(node.exc) if node.exc is not None else "raise")
        return values
    if context.source_file.endswith(".java"):
        return [value.strip() for keyword, value in re.findall(
            r"\b(return|throw)\s+([^;{}]+)", context.text
        )]
    return []


BRANCH_ADAPTERS = (PythonEvidenceAdapter(), JavaEvidenceAdapter())
PERSISTENCE_ADAPTERS: tuple[PersistenceEvidenceAdapter, ...] = (LiteralStorageAdapter(),)


def collect_evidence(
    scan: ScanResult,
    *,
    branch_adapters: tuple[BranchEvidenceAdapter, ...] = BRANCH_ADAPTERS,
    persistence_adapters: tuple[PersistenceEvidenceAdapter, ...] = PERSISTENCE_ADAPTERS,
) -> dict[str, dict]:
    inventories = {}
    with source_view(scan.root, scan.git.target) as (root, _):
        sources = {}
        for file in scan.files:
            path = (root / file).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError(f"source escapes project: {file}")
            try:
                sources[file] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
        # 声明索引只建立一次；多入口共享辅助能力时不能反复解析整个项目。
        definitions_by_file = {}
        capability_locations = {}
        bare_locations = {}
        for file, source in sources.items():
            language = "Python" if file.endswith(".py") else "Java" if file.endswith(".java") else None
            if language is None:
                continue
            definitions = _functions(source, language, file)
            _enrich_signatures(definitions, language)
            definitions_by_file[file] = definitions
            for function in definitions:
                capability_locations.setdefault(_capability_id(language, file, function, source), []).append((file, function))
                bare_locations.setdefault(function.name, []).append((file, function.name))
        for entry in scan.entries:
            branches, persistence, unresolved = [], [], []
            participants = [value for value in (entry.caller, entry.module) if value and value != "代码中未确认"]
            calls = list(dict.fromkeys(entry.functions))
            async_actions, external_calls, outcomes = [], [], []
            # Discovery may retain bare helper names for compatibility. Resolve
            # them only when exactly one source definition exists.
            locations = {location for location in entry.functions if ":" in location and "#" not in location}
            if not any("#" in capability for capability in entry.functions):
                locations.add(f"{entry.file}:{entry.handler}")
            qualified_definitions: dict[str, tuple[str, FunctionInfo]] = {}
            for capability in entry.functions:
                if "#" not in capability or ":" not in capability:
                    continue
                candidates = capability_locations.get(capability, [])
                if len(candidates) == 1:
                    qualified_definitions[capability] = candidates[0]
                    locations.add(capability)
                elif len(candidates) > 1:
                    unresolved.append({"code": "SOURCE_SCOPE_AMBIGUOUS", "critical": True, "evidence": capability})
            for bare in {location for location in entry.functions if ":" not in location}:
                candidates = bare_locations.get(bare, [])
                if len(candidates) == 1:
                    locations.add(f"{candidates[0][0]}:{bare}")
                elif len(candidates) > 1:
                    unresolved.append({"code": "SOURCE_SCOPE_AMBIGUOUS", "critical": True, "evidence": bare})
            for location in sorted(locations):
                qualified = qualified_definitions.get(location)
                if qualified:
                    file, definition = qualified
                    function = definition.name
                    text = sources[file]
                    language = "Python" if file.endswith(".py") else "Java"
                else:
                    file, _, function = location.rpartition(":")
                    text = sources.get(file, "")
                    language = "Python" if file.endswith(".py") else "Java" if file.endswith(".java") else None
                if language is not None:
                    definitions = [definition] if qualified else [f for f in definitions_by_file.get(file, []) if f.name == function]
                    if len(definitions) != 1:
                        unresolved.append({"code": "SOURCE_SCOPE_UNRESOLVED", "critical": True, "evidence": location})
                        continue
                    definition = definitions[0]
                    context = SourceContext(entry, file, function, definition.start, definition.body, sources)
                else:
                    # Other languages are intentionally delegated to a project
                    # adapter.  Give it the complete source because the
                    # generic package has no safe parser for that language.
                    context = SourceContext(entry, file, function, 1, text, sources)
                adapter = next((a for a in branch_adapters if a.can_handle(context)), None)
                if adapter is None:
                    unresolved.append({"code": "SOURCE_ADAPTER_UNAVAILABLE", "critical": True, "evidence": location})
                    continue
                try:
                    branch_values = list(adapter.branches(context))
                    branches.extend(asdict(b) for b in branch_values)
                    outcomes.extend(outcome for branch in branch_values for outcome in branch.outcomes)
                    outcomes.extend(_declared_outcomes(context))
                except (SyntaxError, ValueError):
                    unresolved.append({"code": "CRITICAL_UNRESOLVED_BRANCH", "critical": True, "evidence": location})
                actions = [a for adapter in persistence_adapters if adapter.can_handle(context) for a in adapter.analyze(context)]
                persistence.extend(asdict(a) for a in actions)
                if re.search(r"\b(?:async|await|enqueue|publish|send|submit)\b", context.text, re.I):
                    async_actions.append(f"{file}:{context.start_line}")
                if re.search(r"\b(?:requests?|httpx|urllib|grpc|RestTemplate|Feign)\b", context.text, re.I):
                    external_calls.append(f"{file}:{context.start_line}")
                for action in actions:
                    if not action.display_name:
                        unresolved.append({"code": "PERSISTENCE_DISPLAY_NAME_UNRESOLVED", "critical": True,
                                           "evidence": f"{file}:{action.source_line}"})
                # A storage-like call with no resolved object is never silently omitted.
                for number, line in enumerate(context.text.splitlines(), context.start_line):
                    if re.search(r"\b(?:repository|dao|save|persist|execute|executemany|findBy\w*|redis|cache|collection|get_collection|open|Path|put_object|get_object|delete_object)\b", line, re.I):
                        if not any(a.source_line == number for a in actions):
                            unresolved.append({"code": "PERSISTENCE_OBJECT_UNRESOLVED", "critical": True, "evidence": f"{file}:{number}"})
            inventories[entry.entry_id] = {
                "entry_id": entry.entry_id, "source_fingerprint": scan.source_fingerprint,
                "business_name": entry.business_name, "trigger_summary": entry.trigger_summary,
                "source_evidence": list(entry.source_evidence), "scope_status": entry.scope_status,
                "exclusion_reason": entry.exclusion_reason,
                "participants": list(dict.fromkeys(participants)), "calls": calls,
                "async_actions": list(dict.fromkeys(async_actions)),
                "external_calls": list(dict.fromkeys(external_calls)),
                "outcomes": list(dict.fromkeys(outcomes)),
                "source_branch_inventory": branches, "persistence_inventory": persistence,
                "unresolved": unresolved,
            }
            if not outcomes:
                inventories[entry.entry_id]["unresolved"].append({
                    "code": "ENTRY_OUTCOME_UNRESOLVED", "critical": True,
                    "evidence": entry.entry_id,
                    "reason": "入口函数没有可提取的返回、异常或状态结果",
                })
    return inventories
