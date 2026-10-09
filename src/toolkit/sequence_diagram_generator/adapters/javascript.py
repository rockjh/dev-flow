"""Separate JS/TS grammars, lexical declarations and asynchronous boundaries."""
from dataclasses import replace
from pathlib import PurePosixPath
import json

from ..models import AdapterCapabilities
from ..repository import digest
from .analysis import _Analysis
from ._tree import field, normalized, parse_gaps, parser_versions, proof, registration, resolve_unique, symbol, text, trees, walk

FUNCTIONS = frozenset({"function_declaration", "generator_function_declaration", "method_definition", "arrow_function", "function_expression"})


class JavaScriptAdapter:
    def capabilities(self, language="javascript"):
        parser, grammar = parser_versions(language)
        return AdapterCapabilities(language, "tree-sitter", parser, grammar,
            ("if", "switch-fallthrough", "loop", "short-circuit", "optional-chain", "return-throw", "promise-await", "callback-event", "try-finally"),
            ("explicit-symbol", "Express direct app/router binding", "Node imported EventEmitter direct registration", "tsconfig direct path mapping"),
            ("dynamic-require-eval", "unknown-middleware", "unresolved-alias", "callback-schedule", "runtime-types"),
            ("test_adapters::javascript", "test_adapters::typescript", "test_language_semantics::javascript-registration", "test_language_semantics::javascript-project-async", "test_language_semantics::node-synchronous-event"))

    def _index(self, snapshot):
        indexed = {}
        for file, raw, root in trees(snapshot, {"javascript", "typescript"}):
            module = str(PurePosixPath(file.path).with_suffix("")).replace("/", ".")
            declarations = []
            anonymous_counts = {}
            def visit(node, owners=()):
                if node.type in {"class_declaration", "class"}:
                    owners += (text(field(node, "name"), raw),)
                if node.type in FUNCTIONS:
                    name = text(field(node, "name"), raw)
                    if not name and node.parent and node.parent.type == "variable_declarator":
                        name = text(field(node.parent, "name"), raw)
                    if not name:
                        # Anonymous callbacks are selected through their registered call site.
                        key = (owners, digest(normalized(node, raw)))
                        ordinal = anonymous_counts.get(key, 0)
                        anonymous_counts[key] = ordinal + 1
                        name = "callback@" + key[1][:12] + ":" + str(ordinal)
                    params = field(node, "parameters") or field(node, "parameter")
                    signature = text(params, raw) + text(field(node, "return_type"), raw)
                    item = symbol(file.path, file.language, node, ".".join((module, *owners, name)), signature)
                    declarations.append((item, node))
                    owners += (name,)
                for child in node.named_children:
                    visit(child, owners)
            visit(root)
            # Recognize only receivers directly constructed from imported framework types.
            imports = {}
            for child in root.named_children:
                if child.type == "import_statement":
                    module_name = text(field(child, "source"), raw).strip("\"'")
                    for descendant in walk(child):
                        if descendant.type == "identifier":
                            imports[text(descendant, raw)] = module_name
                if child.type in {"lexical_declaration", "variable_declaration"}:
                    for descendant in walk(child):
                        if descendant.type == "variable_declarator":
                            value = field(descendant, "value")
                            if value and value.type == "call_expression" and text(field(value, "function"), raw) == "require":
                                arguments = field(value, "arguments")
                                if arguments and len(arguments.named_children) == 1 and arguments.named_children[0].type == "string":
                                    imports[text(field(descendant, "name"), raw)] = text(arguments.named_children[0], raw).strip("\"'")
            receivers = {}
            for descendant in walk(root):
                if descendant.type == "variable_declarator":
                    value = field(descendant, "value")
                    if value and value.type in {"call_expression", "new_expression"}:
                        creator = text(field(value, "function") or field(value, "constructor"), raw)
                        imported = imports.get(creator.split(".")[0], "")
                        if imported in {"express", "events", "node:events"}:
                            receivers[text(field(descendant, "name"), raw)] = imported
            for item, node in declarations:
                registrations = []
                for call in walk(root):
                    if call.type != "call_expression":
                        continue
                    fn = field(call, "function")
                    if not fn or fn.type != "member_expression":
                        continue
                    receiver = text(field(fn, "object"), raw)
                    method = text(field(fn, "property"), raw)
                    args = field(call, "arguments")
                    arguments = args.named_children if args else ()
                    valid = (receivers.get(receiver) == "express" and method in {"get", "post", "put", "delete", "patch", "use", "all"}
                             or receivers.get(receiver) in {"events", "node:events"} and method in {"on", "once", "addListener"})
                    if not valid or not arguments:
                        continue
                    handler = arguments[-1]
                    matches = handler == node or handler.type == "identifier" and text(handler, raw) == item.qualified_name.rsplit(".", 1)[-1]
                    if matches:
                        registrations.append(registration(item.symbol_id, call, raw, file.path, "direct framework event/route binding"))
                if registrations:
                    item = replace(item, selection_type="registered", registration_evidence=tuple(registrations))
                indexed[item.symbol_id] = (item, node, raw, root)
        return indexed

    def discover(self, snapshot):
        return tuple(item[0] for item in self._index(snapshot).values())

    def analyze(self, snapshot, scope):
        index = self._index(snapshot)
        analysis = _Analysis(scope)
        cleanup = []
        event_receivers, listeners = {}, {}
        snapshot_contents = dict(snapshot.contents)
        configs = []
        for path, config in snapshot_contents.items():
            if path.endswith("tsconfig.json"):
                try:
                    parsed = json.loads(config)
                    if "extends" in parsed or "references" in parsed:
                        analysis.gap("TS_CONFIG_INHERITANCE", scope.symbol.start_line, "inherited/project-reference mappings are not expanded")
                    options = parsed.get("compilerOptions", {})
                    configs.append((PurePosixPath(path).parent, options))
                except (ValueError, UnicodeError):
                    analysis.gap("TS_CONFIG_UNREADABLE", scope.symbol.start_line, "tsconfig must be readable JSON")

        def module_target(module, imported):
            parts = []
            for part in PurePosixPath(module).parts:
                if part == "..":
                    if not parts:
                        return None
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            path = PurePosixPath(*parts)
            if path.suffix in {".js", ".ts", ".jsx", ".tsx"}:
                path = path.with_suffix("")
            names = {str(path).replace("/", ".") + "." + imported,
                     str(path / "index").replace("/", ".") + "." + imported}
            matches = [value for value in index.values() if value[0].qualified_name in names]
            return matches[0] if len(matches) == 1 else None

        def body(node, raw):
            if node is None:
                return [], False
            if node.type == "statement_block":
                return statements(node.named_children, raw)
            if node.type == "else_clause":
                return statements(node.named_children, raw)
            if node.type.endswith("statement"):
                return statements((node,), raw)
            return expression(node, raw), False

        def imports_for(path):
            source_symbol = next(value for value in index.values() if value[0].path == path)
            raw, root = source_symbol[2:]
            imports = {}
            for item in root.named_children:
                if item.type == "import_statement":
                    module = text(field(item, "source"), raw).strip("\"'")
                    for child in walk(item):
                        if child.type == "import_specifier":
                            imported = text(field(child, "name"), raw)
                            local = text(field(child, "alias"), raw) or imported
                            imports[local] = (module, imported)
                        elif child.type == "identifier" and child.parent.type in {"import_clause", "namespace_import"}:
                            imports[text(child, raw)] = (module, "default")
            return imports

        def resolve(name):
            owner = analysis.symbol.qualified_name.rsplit(".", 1)[0]
            # JS and TS modules with the same stem remain distinct lexical
            # scopes. A direct local name must bind within its own file.
            local_index = {key: value for key, value in index.items() if value[0].path == analysis.symbol.path}
            target = resolve_unique(local_index, owner + "." + name)
            if target:
                return target, "project", target[0].qualified_name
            bindings = imports_for(analysis.symbol.path)
            root_name = name.split(".")[0]
            if root_name in bindings:
                module, imported = bindings[root_name]
                if module.startswith("."):
                    target = module_target(str(PurePosixPath(analysis.symbol.path).parent / module), imported)
                    if target:
                        return target, "project", target[0].qualified_name
                    return None, "unknown", name
                applicable = [(base, options) for base, options in configs
                              if PurePosixPath(analysis.symbol.path).is_relative_to(base)]
                if applicable:
                    base, options = max(applicable, key=lambda item: len(item[0].parts))
                    candidates, matched = [], False
                    for pattern, paths in options.get("paths", {}).items():
                        if pattern.count("*") > 1 or not isinstance(paths, list):
                            analysis.gap("TS_MODULE_ALIAS", analysis.symbol.start_line, "unsupported path mapping")
                            continue
                        before, _, after = pattern.partition("*")
                        if module == pattern or "*" in pattern and module.startswith(before) and module.endswith(after):
                            matched = True
                            captured = module[len(before):len(module)-len(after) if after else len(module)] if "*" in pattern else ""
                            for mapped in paths:
                                if isinstance(mapped, str):
                                    found = module_target(str(base / options.get("baseUrl", ".") / mapped.replace("*", captured)), imported)
                                    if found:
                                        candidates.append(found)
                    if matched:
                        unique = {candidate[0].symbol_id: candidate for candidate in candidates}
                        if len(unique) == 1:
                            target = next(iter(unique.values()))
                            return target, "project", target[0].qualified_name
                        return None, "unknown", name
                return None, "boundary", module + ":" + name
            if name in {"console.log", "JSON.parse", "JSON.stringify", "Math.abs", "Math.max", "Math.min", "Number", "String", "Boolean", "Promise.resolve", "Promise.reject"}:
                return None, "summary", name
            return None, "unknown", name

        def expression(node, raw, awaited=False):
            if node is None:
                return []
            if node.type in FUNCTIONS:
                analysis.gap("JS_CALLBACK_SCHEDULE", node.start_point.row + 1, "callback declared; invocation and ordering not established")
                return []
            if node.type == "await_expression":
                items = expression(node.named_children[0], raw, True)
                items.append(analysis.step("await", "await observed settlement", proof(analysis, node, raw), completion="observed"))
                return items
            if node.type == "ternary_expression":
                block, _ = analysis.block("alt", text(field(node, "condition"), raw), [("true", lambda: (expression(field(node, "consequence"), raw), False)),
                    ("false", lambda: (expression(field(node, "alternative"), raw), False))], proof(analysis, node, raw))
                return expression(field(node, "condition"), raw) + [block]
            if node.type == "binary_expression" and text(field(node, "operator"), raw) in {"&&", "||", "??"}:
                block, _ = analysis.block("alt", "short circuit " + text(field(node, "operator"), raw), [("evaluate right", lambda: (expression(field(node, "right"), raw), False)),
                    ("short-circuit exit", lambda: ([], False))], proof(analysis, node, raw))
                return expression(field(node, "left"), raw) + [block]
            if node.type in {"call_expression", "new_expression"}:
                function = field(node, "function") or field(node, "constructor")
                args = field(node, "arguments")
                name = text(function, raw)
                target, resolution, receiver = resolve(name)
                binding = imports_for(analysis.symbol.path).get(name)
                if node.type == "new_expression" and binding and binding[0] in {"events", "node:events"} and binding[1] in {"EventEmitter", "default"}:
                    owner = node.parent
                    if owner and owner.type == "variable_declarator":
                        event_receivers[(analysis.context.context_id, text(field(owner, "name"), raw))] = analysis.exit_id
                event_object = text(field(function, "object"), raw) if function and function.type == "member_expression" else ""
                method = text(field(function, "property"), raw) if function and function.type == "member_expression" else ""
                event_key = (analysis.context.context_id, event_object)
                arguments = args.named_children if args else ()
                if event_key in event_receivers and method in {"on", "once", "emit"}:
                    same_path = event_receivers[event_key] == analysis.exit_id
                    if not same_path or not arguments or arguments[0].type != "string":
                        analysis.gap("JS_EVENT_BINDING", node.start_point.row + 1, "conditional event instance or dynamic event name")
                    else:
                        event = text(arguments[0], raw)
                        listener_key = (*event_key, event)
                        evidence = proof(analysis, node, raw)
                        if method in {"on", "once"} and len(arguments) == 2:
                            handler = arguments[1]
                            callback = resolve(text(handler, raw))[0] if handler.type == "identifier" else next((v for v in index.values() if v[1] == handler), None)
                            if callback:
                                listeners.setdefault(listener_key, []).append((callback, method, analysis.exit_id))
                                return analysis.call(name, evidence, "node:events.EventEmitter." + method, "summary")
                        elif method == "emit" and listener_key in listeners:
                            items = []
                            for argument in arguments[1:]:
                                items.extend(expression(argument, raw))
                            dispatch = analysis.call(name, evidence, "node:events.EventEmitter.emit", "summary", completion="not_observed")
                            items.extend(dispatch)
                            retained = []
                            complete = True
                            for callback, registration_method, exit_id in tuple(listeners[listener_key]):
                                target_symbol, declaration, target_raw, _ = callback
                                if exit_id != analysis.exit_id or any(child.type == "async" for child in declaration.children):
                                    analysis.gap("JS_EVENT_COMPLETION", node.start_point.row + 1, "conditional or asynchronous listener cannot prove synchronous completion")
                                    complete = False
                                    continue
                                def visit(declaration=declaration, target_raw=target_raw):
                                    saved = tuple(cleanup)
                                    cleanup.clear()
                                    try:
                                        return body(field(declaration, "body"), target_raw)
                                    finally:
                                        cleanup.extend(saved)
                                items.extend(analysis.call("listener " + event, evidence, target_symbol.qualified_name, "project", (target_symbol, visit)))
                                if registration_method != "once":
                                    retained.append((callback, registration_method, exit_id))
                            listeners[listener_key] = retained
                            if complete:
                                items.append(analysis.step("call_return", "EventEmitter.emit returned after synchronous listeners", evidence,
                                                           "node:events.EventEmitter.emit", "observed", (dispatch[0].step_id,)))
                            return items
                def invoke():
                    items = expression(field(function, "object"), raw) if function and function.type == "member_expression" else []
                    for argument in args.named_children if args else ():
                        items.extend(expression(argument, raw))
                    dispatch = name in {"setTimeout", "setImmediate", "queueMicrotask", "Promise.all", "Promise.race"} or name.endswith((".then", ".catch", ".finally", ".emit"))
                    if dispatch:
                        analysis.gap("JS_ASYNC_DEPENDENCIES", node.start_point.row + 1, "promise/callback/event completion graph requires explicit binding")
                    build = None
                    if target:
                        target_symbol, declaration, target_raw, _ = target
                        asynchronous = any(child.type == "async" for child in declaration.children)
                        if asynchronous and not awaited:
                            analysis.gap("JS_ASYNC_COMPLETION", node.start_point.row + 1, "async invocation starts; completion not awaited")
                            dispatch = True
                        def visit():
                            saved = tuple(cleanup)
                            cleanup.clear()
                            try:
                                return body(field(declaration, "body"), target_raw)
                            finally:
                                cleanup.extend(saved)
                        build = (target_symbol, visit)
                    items += analysis.call(name, proof(analysis, node, raw), receiver, resolution, build,
                                           "dispatched" if dispatch else "returned", "dispatch" if dispatch else "call")
                    if name in {"eval", "Function", "require"} and (not args or not args.named_children or args.named_children[0].type != "string"):
                        analysis.gap("JS_DYNAMIC_MODULE_EXECUTION", node.start_point.row + 1, name)
                    return items, False
                optional = any(child.type == "optional_chain" for child in walk(node))
                if optional:
                    block, _ = analysis.block("alt", "optional chain", [("receiver present", invoke), ("nullish receiver / skip", lambda: ([], False))], proof(analysis, node, raw))
                    return [block]
                return invoke()[0]
            items = []
            for child in node.named_children:
                items.extend(expression(child, raw))
            return items

        def statements(nodes, raw):
            items = []
            for node in nodes:
                evidence = proof(analysis, node, raw)
                if node.type == "if_statement":
                    block, terminal = analysis.block("alt", text(field(node, "condition"), raw), [("true", lambda: body(field(node, "consequence"), raw)),
                        ("false", lambda: body(field(node, "alternative"), raw))], evidence)
                    items.extend(expression(field(node, "condition"), raw))
                    items.append(block)
                    if terminal:
                        return items, True
                elif node.type in {"for_statement", "for_in_statement", "while_statement", "do_statement"}:
                    items.extend(expression(field(node, "initializer"), raw))
                    def iteration():
                        children, terminal = body(field(node, "body"), raw)
                        if not terminal:
                            children.extend(expression(field(node, "increment"), raw))
                        elif field(node, "increment"):
                            analysis.gap("JS_LOOP_CONTROL_TRANSFER", node.start_point.row + 1, "increment timing after break/continue/return needs exit-specific binding")
                        return children, terminal
                    block, _ = analysis.block("loop", text(field(node, "condition") or field(node, "right"), raw),
                        [("iteration", iteration), ("loop exit", lambda: ([], False))], evidence)
                    items.append(block)
                    if node.type == "do_statement" or any(child.type == "call_expression" for child in walk(field(node, "condition"))) if field(node, "condition") else node.type == "do_statement":
                        analysis.gap("JS_LOOP_EVALUATION", node.start_point.row + 1, "mandatory/repeated condition evaluation not fully bound")
                elif node.type == "switch_statement":
                    clauses = field(node, "body").named_children
                    arms = []
                    for offset, clause in enumerate(clauses):
                        def branch(offset=offset):
                            children = []
                            for item in clauses[offset:]:
                                commands = [child for child in item.named_children if child != field(item, "value")]
                                more, terminal = statements(commands, raw)
                                children.extend(more)
                                if terminal:
                                    return children, analysis.steps[-1].kind != "break"
                            return children, False
                        arms.append((text(field(clause, "value"), raw) or "default", branch))
                    if not any(item.type == "switch_default" for item in clauses):
                        arms.append(("no matching case", lambda: ([], False)))
                    block, terminal = analysis.block("alt", "switch", arms, evidence, transfer_boundary="switch")
                    items.extend(expression(field(node, "value"), raw))
                    items.append(block)
                    if terminal:
                        return items, True
                elif node.type in {"return_statement", "throw_statement", "break_statement", "continue_statement"}:
                    for child in node.named_children:
                        items.extend(expression(child, raw))
                    saved = tuple(cleanup)
                    cleanup.clear()
                    if node.type in {"return_statement", "throw_statement"}:
                        for block, cleanup_raw in reversed(saved):
                            items.extend(body(block, cleanup_raw)[0])
                    cleanup.extend(saved)
                    items.append(analysis.step(node.type.removesuffix("_statement"), text(node, raw), evidence, completion="observed"))
                    return items, True
                elif node.type == "try_statement":
                    finalizer = field(node, "finalizer")
                    final_body = field(finalizer, "body")
                    def branch(block):
                        if final_body:
                            cleanup.append((final_body, raw))
                        children, terminal = body(block, raw)
                        if final_body:
                            cleanup.pop()
                            if not terminal:
                                children.extend(body(final_body, raw)[0])
                        return children, terminal
                    arms = [("normal", lambda: branch(field(node, "body")))]
                    handler = field(node, "handler")
                    if handler:
                        arms.append(("caught exception", lambda: branch(field(handler, "body"))))
                    block, terminal = analysis.block("alt", "try / catch", arms, evidence)
                    items.append(block)
                    analysis.gap("JS_EXCEPTION_ORIGIN", node.start_point.row + 1, "exception interrupted prefixes and propagation need further binding")
                    if terminal:
                        return items, True
                elif node.type in {"expression_statement", "lexical_declaration", "variable_declaration"}:
                    items.extend(expression(node, raw))
                elif node.type in {"statement_block", "else_clause"}:
                    more, terminal = statements(node.named_children, raw)
                    items.extend(more)
                    if terminal:
                        return items, True
                elif node.type in FUNCTIONS or node.type in {"comment", "empty_statement"}:
                    continue
                else:
                    analysis.gap("UNSUPPORTED_JS_NODE", node.start_point.row + 1, node.type)
            return items, False

        _, declaration, raw, root = index[scope.symbol.symbol_id]
        parse_gaps(analysis, root)
        return analysis.finish(body(field(declaration, "body"), raw)[0])
