"""Tree-sitter parsing primitives, not a language-independent CFG guesser."""
from __future__ import annotations

from importlib.metadata import version

from ...core.errors import DevflowError, ExitCode
from ..models import CoverageGap, Evidence, SourceSymbol
from ..repository import digest, stable_id


def parser_for(language, tsx=False):
    try:
        from tree_sitter import Language, Parser
        if language == "java":
            from tree_sitter_java import language as grammar
        elif language == "javascript":
            from tree_sitter_javascript import language as grammar
        elif language == "typescript":
            from tree_sitter_typescript import language_tsx, language_typescript
            grammar = language_tsx if tsx else language_typescript
        elif language == "go":
            from tree_sitter_go import language as grammar
        elif language == "rust":
            from tree_sitter_rust import language as grammar
        else:
            raise ValueError(language)
        return Parser(Language(grammar()))
    except (ImportError, OSError, ValueError) as exc:
        raise DevflowError("EXTERNAL_UNAVAILABLE", f"缺少解析依赖或语法包不兼容: {language}", ExitCode.UNAVAILABLE) from exc


def parser_versions(language):
    try:
        return version("tree-sitter"), version("tree-sitter-" + language)
    except Exception as exc:
        raise DevflowError("EXTERNAL_UNAVAILABLE", f"缺少解析依赖: {language}", ExitCode.UNAVAILABLE) from exc


def walk(node):
    yield node
    for child in node.named_children:
        yield from walk(child)


def text(node, raw):
    return raw[node.start_byte:node.end_byte].decode("utf-8") if node is not None else ""


def normalized(node, raw):
    if node is None:
        return ""
    if node.type in {"comment", "line_comment", "block_comment"}:
        return ""
    if not node.children:
        return (node.type, text(node, raw))
    return (node.type, tuple(normalized(child, raw) for child in node.children if child.type not in {"comment", "line_comment", "block_comment"}))


def field(node, name):
    return node.child_by_field_name(name) if node else None


def proof(analysis, node, raw):
    return analysis.proof(normalized(node, raw), node.start_point.row + 1, node.end_point.row + 1, text(node, raw))


def registration(symbol_id, node, raw, path, boundary):
    return Evidence(stable_id("E", symbol_id, normalized(node, raw)), "code", path, f"line:{node.start_point.row + 1}",
                    digest(normalized(node, raw)), symbol_id, boundary, text(node, raw))


def symbol(path, language, node, qualified, signature, registrations=()):
    sid = stable_id("F", path, qualified, signature)
    return SourceSymbol(sid, qualified, signature, language, path, node.start_point.row + 1, node.end_point.row + 1,
                        "registered" if registrations else "symbol", tuple(registrations))


def trees(snapshot, languages):
    contents = dict(snapshot.contents)
    for file in snapshot.files:
        if file.language in languages:
            raw = contents[file.path]
            tree = parser_for(file.language, file.path.endswith(".tsx")).parse(raw)
            yield file, raw, tree.root_node


def parse_gaps(analysis, tree):
    for node in walk(tree):
        if node.type == "ERROR" or node.is_missing:
            analysis.gap("PARSE_ERROR", node.start_point.row + 1, "Tree-sitter ERROR/MISSING node")


def resolve_unique(index, qualified, signature_arity=None):
    matches = [(symbol, node, raw, root) for symbol, node, raw, root in index.values()
               if symbol.qualified_name == qualified]
    if signature_arity is not None:
        matches = [item for item in matches if len([child for child in (field(item[1], "parameters").named_children if field(item[1], "parameters") else ())
                   if child.type not in {"comment"}]) == signature_arity]
    return matches[0] if len(matches) == 1 else None
