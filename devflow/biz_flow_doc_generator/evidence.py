"""Source inventories. Adapters are statically registered, never loaded from projects."""

from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from dataclasses import asdict, dataclass
from typing import Protocol

from .discovery import _functions
from .git import source_view
from .models import BranchEvidence, EntryPoint, PersistenceAction, ScanResult


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
            if isinstance(node, ast.Raise):
                ancestor = parents.get(node)
                while ancestor is not None and not isinstance(ancestor, ast.Try):
                    ancestor = parents.get(ancestor)
                raised_func = getattr(getattr(node, "exc", None), "func", None)
                raised_name = getattr(raised_func, "id", None)
                caught_names = {
                    getattr(handler.type, "id", None)
                    for handler in ancestor.handlers
                    if isinstance(ancestor, ast.Try) and handler.type is not None
                } if isinstance(ancestor, ast.Try) else set()
                if raised_name and raised_name in caught_names:
                    reachability, business_relevant = "unreachable", False
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
        for entry in scan.entries:
            branches, persistence, unresolved = [], [], []
            participants = [value for value in (entry.caller, entry.module) if value and value != "代码中未确认"]
            calls = list(dict.fromkeys(entry.functions))
            async_actions, external_calls, outcomes = [], [], []
            # Discovery may retain bare helper names for compatibility. Resolve
            # them only when exactly one source definition exists.
            locations = {location for location in entry.functions if ":" in location} | {f"{entry.file}:{entry.handler}"}
            # Qualified capability IDs are presentation/identity values. The
            # evidence parser still needs its canonical ``file:function``
            # locator, so resolve the method suffix within the entry source.
            qualified_locations = set()
            for location in locations:
                if "#" in location and ":" in location:
                    match = re.search(r"#([A-Za-z_]\w*)\([^)]*\)", location)
                    if match:
                        qualified_locations.add(f"{entry.file}:{match.group(1)}")
            locations = (locations - {item for item in locations if "#" in item}) | qualified_locations
            for bare in {location for location in entry.functions if ":" not in location}:
                candidates = [
                    (file, function.name)
                    for file, source in sources.items()
                    for function in _functions(source, "Python" if file.endswith(".py") else "Java", file)
                    if function.name == bare
                ]
                if len(candidates) == 1:
                    locations.add(f"{candidates[0][0]}:{bare}")
                elif len(candidates) > 1:
                    unresolved.append({"code": "SOURCE_SCOPE_AMBIGUOUS", "critical": True, "evidence": bare})
            for location in sorted(locations):
                file, _, function = location.rpartition(":")
                text = sources.get(file, "")
                language = "Python" if file.endswith(".py") else "Java" if file.endswith(".java") else None
                if language is not None:
                    definitions = [f for f in _functions(text, language, file) if f.name == function]
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
