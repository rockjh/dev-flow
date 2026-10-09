"""Rust Result propagation, patterns and explicit unexpanded macro boundaries."""
from dataclasses import replace
from pathlib import PurePosixPath

from ..models import AdapterCapabilities
from .analysis import _Analysis
from ._tree import field, parse_gaps, parser_versions, proof, registration, resolve_unique, symbol, text, trees, walk


def _use_bindings(root, raw):
    bindings = {}
    def visit(node, prefix=""):
        if node is None:
            return
        if node.type == "use_as_clause":
            path = text(field(node, "path"), raw)
            bindings[text(field(node, "alias"), raw)] = prefix + path
        elif node.type == "scoped_use_list":
            visit(field(node, "list"), prefix + text(field(node, "path"), raw) + "::")
        elif node.type == "use_list":
            for child in node.named_children:
                visit(child, prefix)
        elif node.type in {"identifier", "scoped_identifier"}:
            path = text(node, raw)
            bindings[path.rsplit("::", 1)[-1]] = prefix + path
    for node in root.named_children:
        if node.type == "use_declaration":
            visit(field(node, "argument"))
    return bindings


def _is_async(declaration):
    return any(child.type == "async" or child.type == "function_modifiers" and any(token.type == "async" for token in child.children)
               for child in declaration.children)


class RustAdapter:
    def capabilities(self):
        parser, grammar = parser_versions("rust")
        return AdapterCapabilities("rust", "tree-sitter", parser, grammar,
            ("if-let", "let-else", "match-guard", "result-question-mark", "return", "panic", "async-await", "explicit-spawn", "std-thread-direct-function-join"),
            ("main", "explicit-symbol", "axum imported routing get/post direct handler references"),
            ("unexpanded-macro", "proc-macro", "cfg", "dynamic-trait", "macro-registration", "spawn-completion"),
            ("test_adapters::rust", "test_language_semantics::rust-question-mark", "test_boundaries::axum-direct-routing", "test_boundaries::rust-unexpanded-macro", "test_thread_completion::rust-direct-join"))

    def _index(self, snapshot):
        indexed = {}
        for file, raw, root in trees(snapshot, {"rust"}):
            module = str(PurePosixPath(file.path).with_suffix("")).replace("/", "::")
            def visit(node, owners=()):
                if node.type == "impl_item":
                    owners += (text(field(node, "type"), raw),)
                if node.type == "mod_item":
                    owners += (text(field(node, "name"), raw),)
                if node.type == "function_item":
                    name = text(field(node, "name"), raw)
                    item = symbol(file.path, "rust", node, "::".join((module, *owners, name)),
                                  text(field(node, "parameters"), raw) + "->" + text(field(node, "return_type"), raw))
                    registrations = []
                    if name == "main" and not owners:
                        registrations.append(registration(item.symbol_id, node, raw, file.path, "Rust main"))
                    direct_routes = set()
                    for declaration in root.named_children:
                        if declaration.type == "use_declaration":
                            imported = text(field(declaration, "argument"), raw)
                            if imported in {"axum::routing::get", "axum::routing::post"}:
                                direct_routes.add(imported.rsplit("::", 1)[-1])
                    if not owners:
                        for call in walk(root):
                            if call.type == "call_expression" and text(field(call, "function"), raw) in direct_routes:
                                args = field(call, "arguments")
                                outer = call.parent.parent if call.parent else None
                                fn = field(outer, "function") if outer and outer.type == "call_expression" else None
                                if args and len(args.named_children) == 1 and text(args.named_children[0], raw) == name and fn and fn.type == "field_expression" and text(field(fn, "field"), raw) == "route":
                                    registrations.append(registration(item.symbol_id, call, raw, file.path, "axum direct routing handler reference"))
                    if registrations:
                        item = replace(item, selection_type="registered", registration_evidence=tuple(registrations))
                    indexed[item.symbol_id] = (item, node, raw, root)
                for child in node.named_children:
                    visit(child, owners)
            visit(root)
        return indexed

    def discover(self, snapshot):
        return tuple(item[0] for item in self._index(snapshot).values())

    def analyze(self, snapshot, scope):
        index = self._index(snapshot)
        analysis = _Analysis(scope)
        joined_handles = {}
        def body(node, raw):
            if node is None:
                return [], False
            if node.type == "block":
                return statements(node.named_children, raw)
            return expression(node, raw), node.type == "return_expression"

        def expression(node, raw, awaited=False):
            if node is None:
                return []
            evidence = proof(analysis, node, raw)
            if node.type == "await_expression":
                return expression(node.named_children[0], raw, True) + [analysis.step("await", "await observed completion", evidence, completion="observed")]
            if node.type == "try_expression":
                children = expression(node.named_children[0], raw)
                block, _ = analysis.block("alt", "Result ?", [("Ok / continue", lambda: ([], False)),
                    ("Err / early return", lambda: ([analysis.step("return", "propagate Err via ?", evidence, completion="observed")], True))], evidence)
                return children + [block]
            if node.type == "if_expression":
                block, _ = analysis.block("alt", text(field(node, "condition"), raw), [("matched / true", lambda: body(field(node, "consequence"), raw)),
                    ("unmatched / false", lambda: body(field(node, "alternative"), raw))], evidence)
                return expression(field(node, "condition"), raw) + [block]
            if node.type == "match_expression":
                arms_node = field(node, "body")
                arms = []
                for arm in arms_node.named_children if arms_node else ():
                    if arm.type != "match_arm":
                        continue
                    pattern = field(arm, "pattern")
                    value = field(arm, "value")
                    guard = next((child for child in walk(pattern) if child.type == "match_pattern" and any(c.type == "if" for c in child.children)), None) if pattern else None
                    if guard:
                        analysis.gap("RUST_MATCH_GUARD_CONTINUATION", arm.start_point.row + 1, "guard failure resumes later arm selection")
                    arms.append((text(pattern, raw), lambda value=value: body(value, raw)))
                block, _ = analysis.block("alt", "match " + text(field(node, "value"), raw), arms, evidence)
                return expression(field(node, "value"), raw) + [block]
            if node.type in {"loop_expression", "while_expression", "for_expression"}:
                block, _ = analysis.block("loop", text(field(node, "condition") or field(node, "value"), raw),
                    [("iteration", lambda: body(field(node, "body"), raw)), ("loop exit", lambda: ([], False))], evidence)
                return [block]
            if node.type in {"return_expression", "break_expression", "continue_expression"}:
                items = []
                for child in node.named_children:
                    items.extend(expression(child, raw))
                return items + [analysis.step(node.type.removesuffix("_expression"), text(node, raw), evidence, completion="observed")]
            if node.type == "macro_invocation":
                name = text(field(node, "macro"), raw)
                if name in {"panic", "unreachable", "todo"}:
                    analysis.gap("RUST_PANIC_UNWIND", node.start_point.row + 1, "panic strategy/Drop unwinding not established")
                    return [analysis.step("panic", text(node, raw), evidence)]
                analysis.gap("RUST_UNEXPANDED_MACRO", node.start_point.row + 1, "macro not executed or expanded: " + name)
                return [analysis.step("macro_boundary", "unexpanded macro " + name, evidence)]
            if node.type in {"closure_expression", "async_block"}:
                analysis.gap("RUST_DEFERRED_BODY", node.start_point.row + 1, "closure/future body execution requires bound invoker")
                return []
            if node.type == "call_expression":
                fn = field(node, "function")
                name = text(fn, raw)
                join_dispatch = joined_handles.get((analysis.context.context_id, name, analysis.exit_id))
                if join_dispatch:
                    evidence = proof(analysis, node, raw)
                    items = analysis.call("JoinHandle.join observes thread completion (Result may be Err)", evidence,
                                          "std::thread::JoinHandle.join", "summary", completion="returned", kind="wait")
                    waiting = next(s for s in analysis.steps if s.step_id == items[0].step_id)
                    analysis.steps[analysis.steps.index(waiting)] = replace(waiting, completion="observed", dependencies=(join_dispatch,))
                    return items
                prefix = analysis.symbol.qualified_name.rsplit("::", 1)[0]
                target = resolve_unique(index, prefix + "::" + name)
                resolution = "project" if target else "unknown"
                if name in {"Ok", "Err", "Some", "None", "String::new", "Vec::new"}:
                    resolution = "summary"
                source_root = index[analysis.symbol.symbol_id][3]
                imports = _use_bindings(source_root, index[analysis.symbol.symbol_id][2])
                if not target and name.split("::")[0] in imports:
                    resolution = "boundary"
                dispatch = name in {"std::thread::spawn", "tokio::spawn", "async_std::task::spawn"}
                if dispatch:
                    resolution = "boundary"
                    analysis.gap("RUST_SPAWN_COMPLETION", node.start_point.row + 1, "spawn dispatch; join/await relation unproven")
                arguments = field(node, "arguments")
                items = []
                for argument in arguments.named_children if arguments else ():
                    items.extend(expression(argument, raw))
                build = None
                if target:
                    target_symbol, declaration, target_raw, _ = target
                    asynchronous = _is_async(declaration)
                    if asynchronous and not awaited:
                        analysis.gap("RUST_UNAWAITED_FUTURE", node.start_point.row + 1, "future constructed; body execution not established")
                        dispatch = True
                    else:
                        build = (target_symbol, lambda: body(field(declaration, "body"), target_raw))
                return items + analysis.call(name, evidence, target[0].qualified_name if target else name, resolution, build,
                                              "dispatched" if dispatch else "returned", "dispatch" if dispatch else "call")
            if node.type == "binary_expression" and text(field(node, "operator"), raw) in {"&&", "||"}:
                block, _ = analysis.block("alt", "short circuit", [("evaluate right", lambda: (expression(field(node, "right"), raw), False)),
                    ("short-circuit exit", lambda: ([], False))], evidence)
                return expression(field(node, "left"), raw) + [block]
            if node.type == "block":
                return body(node, raw)[0]
            items = []
            for child in node.named_children:
                items.extend(expression(child, raw))
            return items

        def thread_region(nodes, offset, raw):
            """Bind one direct function-item spawn and a same-block join.

            The worker and intervening caller statements execute in par; the
            worker is never depicted as executing synchronously at dispatch.
            Captures, escaping handles and conditional joins remain gaps.
            """
            declaration = nodes[offset]
            spawn, pattern = field(declaration, "value"), field(declaration, "pattern")
            if declaration.type != "let_declaration" or not spawn or spawn.type != "call_expression" or not pattern or pattern.type != "identifier":
                return None
            function = text(field(spawn, "function"), raw)
            imports = _use_bindings(index[analysis.symbol.symbol_id][3], index[analysis.symbol.symbol_id][2])
            if function != "std::thread::spawn" and imports.get(function) != "std::thread::spawn":
                return None
            prefix = analysis.symbol.qualified_name.rsplit("::", 1)[0]
            if resolve_unique(index, prefix + "::" + function):
                return None
            arguments = field(spawn, "arguments")
            if not arguments or len(arguments.named_children) != 1 or arguments.named_children[0].type not in {"identifier", "scoped_identifier"}:
                return None
            worker_name = text(arguments.named_children[0], raw)
            worker = resolve_unique(index, prefix + "::" + worker_name)
            if not worker or text(field(worker[1], "parameters"), worker[2]) != "()":
                return None
            if _is_async(worker[1]):
                analysis.gap("RUST_SPAWN_COMPLETION", declaration.start_point.row + 1, "async worker requires await/join completion proof")
                return None
            handle = text(pattern, raw)
            join_offset = None
            for candidate_offset in range(offset + 1, len(nodes)):
                candidate = nodes[candidate_offset]
                value = field(candidate, "value") if candidate.type == "let_declaration" else candidate.named_children[0] if candidate.type == "expression_statement" and candidate.named_children else candidate
                if value and value.type == "try_expression":
                    value = value.named_children[0]
                if value and value.type == "call_expression" and text(field(value, "function"), raw) == handle + ".join" and not (field(value, "arguments") and field(value, "arguments").named_children):
                    join_offset = candidate_offset
                    break
                if any(n.type == "identifier" and text(n, raw) == handle or n.type in {"return_expression", "break_expression", "continue_expression", "await_expression"} for n in walk(candidate)):
                    return None
            if join_offset is None:
                return None
            evidence = proof(analysis, spawn, raw)
            dispatch = analysis.call("std::thread::spawn " + worker_name, evidence, "std::thread::spawn", "boundary",
                                     completion="dispatched", kind="dispatch")
            worker_symbol, worker_declaration, worker_raw, _ = worker
            def worker_arm():
                return analysis.call(worker_name, evidence, worker_symbol.qualified_name, "project",
                                     (worker_symbol, lambda: body(field(worker_declaration, "body"), worker_raw))), False
            block, _ = analysis.block("par", "spawned worker and caller before join", [
                ("worker thread", worker_arm),
                ("caller until join", lambda: statements(nodes[offset + 1:join_offset], raw))], evidence)
            key = (analysis.context.context_id, handle + ".join", analysis.exit_id)
            joined_handles[key] = dispatch[0].step_id
            try:
                observed, terminal = statements((nodes[join_offset],), raw)
            finally:
                joined_handles.pop(key, None)
            return dispatch + [block] + observed, join_offset, terminal

        def statements(nodes, raw):
            items = []
            consumed = -1
            for offset, node in enumerate(nodes):
                if offset <= consumed:
                    continue
                region = thread_region(nodes, offset, raw)
                if region:
                    children, consumed, terminal = region
                    items.extend(children)
                    if terminal:
                        return items, True
                    continue
                evidence = proof(analysis, node, raw)
                if node.type == "let_declaration":
                    items.extend(expression(field(node, "value"), raw))
                    alternative = field(node, "alternative")
                    if alternative:
                        block, _ = analysis.block("alt", "let " + text(field(node, "pattern"), raw), [("matched", lambda: ([], False)),
                            ("else / diverge", lambda: body(alternative, raw))], evidence)
                        items.append(block)
                elif node.type == "expression_statement":
                    child = node.named_children[0] if node.named_children else None
                    items.extend(expression(child, raw))
                    if child and child.type in {"return_expression", "break_expression", "continue_expression"}:
                        return items, True
                elif node.type in {"line_comment", "block_comment", "empty_statement"}:
                    continue
                elif node.type.endswith("expression") or node.type in {"block", "macro_invocation", "integer_literal", "boolean_literal", "string_literal", "identifier", "tuple_expression"}:
                    items.extend(expression(node, raw))
                    if node.type in {"return_expression", "break_expression", "continue_expression"}:
                        return items, True
                    if node == nodes[-1] and node.type in {"integer_literal", "boolean_literal", "string_literal", "identifier", "tuple_expression", "call_expression"}:
                        items.append(analysis.step("return", "tail expression: " + text(node, raw), evidence, completion="observed"))
                elif node.type in {"attribute_item", "inner_attribute_item"}:
                    analysis.gap("RUST_ATTRIBUTE_CFG", node.start_point.row + 1, text(node, raw))
                else:
                    analysis.gap("UNSUPPORTED_RUST_NODE", node.start_point.row + 1, node.type)
            return items, False

        _, declaration, raw, root = index[scope.symbol.symbol_id]
        parse_gaps(analysis, root)
        for node in root.named_children:
            if node.type in {"attribute_item", "inner_attribute_item"}:
                analysis.gap("RUST_ATTRIBUTE_CFG", node.start_point.row + 1, text(node, raw))
        return analysis.finish(body(field(declaration, "body"), raw)[0])
