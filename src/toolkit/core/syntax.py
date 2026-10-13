"""Pure tree-sitter helpers shared by source analyzers."""
from importlib.metadata import version
from .errors import DevflowError, ExitCode


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
