"""Tree-sitter parsing primitives, not a language-independent CFG guesser."""
from __future__ import annotations

from ..models import CoverageGap, Evidence, SourceSymbol
from ..repository import digest, stable_id


from ...core.syntax import parser_for, parser_versions, walk, text, normalized, field


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
