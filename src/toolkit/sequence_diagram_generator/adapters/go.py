"""Go syntax including returned errors, defers and channel boundaries."""
from dataclasses import replace
from pathlib import PurePosixPath

from ..models import AdapterCapabilities
from .analysis import _Analysis
from ._tree import field, parse_gaps, parser_versions, proof, registration, resolve_unique, symbol, text, trees, walk


def import_bindings(root, raw):
    bindings = {}
    for node in walk(root):
        if node.type == "import_spec":
            path = text(field(node, "path"), raw).strip('"')
            alias = text(field(node, "name"), raw) or path.rsplit("/", 1)[-1]
            if alias not in {"_", "."}:
                bindings[alias] = path
    return bindings


class GoAdapter:
    def capabilities(self):
        parser, grammar = parser_versions("go")
        return AdapterCapabilities("go", "tree-sitter", parser, grammar,
            ("if", "switch", "type-switch", "error-return", "defer", "panic-recover", "select", "goroutine-channel", "direct-channel-send-receive"),
            ("main", "net/http direct Handle/HandleFunc", "explicit-symbol"),
            ("interface-dispatch", "generated-code", "build-tags", "channel-completion", "panic-origin"),
            ("test_adapters::go", "test_language_semantics::go-defer", "test_boundaries::go-http-alias", "test_boundaries::go-goroutine", "test_thread_completion::go-direct-channel"))

    def _index(self, snapshot):
        indexed = {}
        for file, raw, root in trees(snapshot, {"go"}):
            package = text(next((child.named_children[0] for child in root.named_children if child.type == "package_clause"), None), raw)
            module = str(PurePosixPath(file.path).parent).replace("/", ".")
            for node in walk(root):
                if node.type not in {"function_declaration", "method_declaration"}:
                    continue
                name = text(field(node, "name"), raw)
                receiver = text(field(node, "receiver"), raw)
                owner = ""
                receiver_node = field(node, "receiver")
                if receiver_node:
                    param = next((child for child in receiver_node.named_children if child.type == "parameter_declaration"), None)
                    owner = text(field(param, "type"), raw).lstrip("*")
                qualified = ".".join(filter(None, (module if module != "." else package, owner, name)))
                signature = receiver + text(field(node, "parameters"), raw) + text(field(node, "result"), raw)
                item = symbol(file.path, "go", node, qualified, signature)
                bindings = {alias for alias, path in import_bindings(root, raw).items() if path == "net/http"}
                registrations = []
                if package == "main" and name == "main" and not receiver and text(field(node, "parameters"), raw) == "()":
                    registrations.append(registration(item.symbol_id, node, raw, file.path, "Go main"))
                for call in walk(root):
                    if call.type != "call_expression":
                        continue
                    function = field(call, "function")
                    if text(function, raw) not in {binding + "." + method for binding in bindings for method in ("Handle", "HandleFunc")}:
                        continue
                    arguments = field(call, "arguments")
                    if arguments and len(arguments.named_children) == 2 and text(arguments.named_children[-1], raw) == name:
                        registrations.append(registration(item.symbol_id, call, raw, file.path, "net/http direct handler"))
                if registrations:
                    item = replace(item, selection_type="registered", registration_evidence=tuple(registrations))
                indexed[item.symbol_id] = (item, node, raw, root)
        return indexed

    def discover(self, snapshot):
        return tuple(value[0] for value in self._index(snapshot).values())

    def analyze(self, snapshot, scope):
        index = self._index(snapshot)
        analysis = _Analysis(scope)
        deferred = []
        bound_channels = {}
        observed_channels = {}
        def body(node, raw):
            if node is None:
                return [], False
            return statements(node.named_children if node.type in {"block", "statement_list"} else (node,), raw)

        def expression(node, raw, dispatch=False, evaluate_arguments=True):
            if node is None:
                return []
            if node.type == "func_literal":
                analysis.gap("GO_CALLBACK_BINDING", node.start_point.row + 1, "closure execution must be bound to an explicit invocation")
                return []
            if node.type == "call_expression":
                function = field(node, "function")
                name = text(function, raw)
                items = []
                arguments = field(node, "arguments")
                for argument in arguments.named_children if arguments and evaluate_arguments else ():
                    items.extend(expression(argument, raw))
                qualified = analysis.symbol.qualified_name.rsplit(".", 1)[0] + "." + name
                target = resolve_unique(index, qualified)
                resolution = "project" if target else "unknown"
                imports = import_bindings(index[analysis.symbol.symbol_id][3], index[analysis.symbol.symbol_id][2])
                if name in {"len", "cap", "append", "copy", "delete", "make", "new", "close", "print", "println", "panic", "recover"}:
                    resolution = "summary"
                elif name.split(".")[0] in imports:
                    resolution = "boundary"
                evidence = proof(analysis, node, raw)
                if name in {"panic", "recover"}:
                    analysis.gap("GO_PANIC_RECOVERY", node.start_point.row + 1, "panic stack unwinding/recover relation is not fully resolved")
                build = None
                if target and not dispatch:
                    target_symbol, declaration, target_raw, _ = target
                    def visit():
                        saved = tuple(deferred)
                        deferred.clear()
                        try:
                            children, terminal = body(field(declaration, "body"), target_raw)
                            if not terminal:
                                for call, cleanup_raw in reversed(deferred):
                                    children.extend(expression(call, cleanup_raw, evaluate_arguments=False))
                            return children, terminal
                        finally:
                            deferred.clear()
                            deferred.extend(saved)
                    build = (target_symbol, visit)
                if dispatch:
                    analysis.gap("GO_GOROUTINE_COMPLETION", node.start_point.row + 1, "goroutine dispatch; completion/channel happens-before requires explicit relation")
                return items + analysis.call(name, evidence, target[0].qualified_name if target else name, resolution, build,
                                              "dispatched" if dispatch else "returned", "dispatch" if dispatch else "call")
            if node.type == "binary_expression" and text(field(node, "operator"), raw) in {"&&", "||"}:
                block, _ = analysis.block("alt", "short circuit", [("evaluate right", lambda: (expression(field(node, "right"), raw), False)),
                    ("short-circuit exit", lambda: ([], False))], proof(analysis, node, raw))
                return expression(field(node, "left"), raw) + [block]
            if node.type == "unary_expression" and text(field(node, "operator"), raw) == "<-":
                evidence = proof(analysis, node, raw)
                receiver = text(field(node, "operand"), raw)
                binding = observed_channels.get((analysis.context.context_id, receiver, analysis.exit_id))
                if binding:
                    dispatch, send_evidence = binding
                    item = analysis.step("wait", "channel value received; consumer processing and goroutine exit not claimed", evidence,
                                         receiver, "observed", (dispatch,))
                    step = next(s for s in analysis.steps if s.step_id == item.step_id)
                    analysis.steps[analysis.steps.index(step)] = replace(step, evidence_ids=step.evidence_ids + (send_evidence,))
                    return [item]
                analysis.gap("GO_CHANNEL_RECEIVE", node.start_point.row + 1, "producer/close and receive success relation must be bound")
                return [analysis.step("wait", "channel receive", evidence, text(field(node, "operand"), raw), "observed")]
            items = []
            for child in node.named_children:
                items.extend(expression(child, raw))
            return items

        def channel_region(nodes, offset, raw):
            statement = nodes[offset]
            if statement.type != "go_statement" or not statement.named_children:
                return None
            call = statement.named_children[0]
            if call.type != "call_expression":
                return None
            name = text(field(call, "function"), raw)
            target = resolve_unique(index, analysis.symbol.qualified_name.rsplit(".", 1)[0] + "." + name)
            args = field(call, "arguments")
            if not target or not args or len(args.named_children) != 1 or args.named_children[0].type != "identifier":
                return None
            channel = text(args.named_children[0], raw)
            declarations = [n for n in nodes[:offset] if n.type == "short_var_declaration" and text(field(n, "left"), raw) == channel]
            if len(declarations) != 1:
                return None
            assigned = field(declarations[0], "right")
            construction = assigned.named_children[0] if assigned and len(assigned.named_children) == 1 else None
            construction_args = field(construction, "arguments")
            if not construction or construction.type != "call_expression" or text(field(construction, "function"), raw) != "make" or not construction_args or not construction_args.named_children or construction_args.named_children[0].type != "channel_type":
                return None
            prefix = analysis.symbol.qualified_name.rsplit(".", 1)[0]
            source_parameters = field(index[analysis.symbol.symbol_id][1], "parameters")
            if resolve_unique(index, prefix + ".make") or source_parameters and any(n.type == "identifier" and text(n, raw) == "make" for n in walk(source_parameters)):
                return None
            if any(n.type == "identifier" and text(n, raw) == "make" for previous in nodes[:nodes.index(declarations[0])] for n in walk(previous)):
                return None
            start = nodes.index(declarations[0])
            if any(n.type == "identifier" and text(n, raw) == channel for prior in nodes[start + 1:offset] for n in walk(prior)):
                return None
            parameters = field(target[1], "parameters")
            if not parameters or len(parameters.named_children) != 1:
                return None
            parameter = parameters.named_children[0]
            parameter_type = field(parameter, "type")
            parameter_name = text(field(parameter, "name"), target[2])
            if not parameter_type or parameter_type.type != "channel_type" or not parameter_name:
                return None
            target_body = field(target[1], "body")
            commands = next((n.named_children for n in target_body.named_children if n.type == "statement_list"), ())
            if not commands or commands[-1].type != "send_statement" or text(field(commands[-1], "channel"), target[2]) != parameter_name:
                return None
            if any(n.type == "identifier" and text(n, target[2]) == parameter_name for n in walk(field(commands[-1], "value"))):
                return None
            if any(n.type in {"return_statement", "defer_statement", "go_statement", "send_statement"} or n.type == "identifier" and text(n, target[2]) == parameter_name
                   for command in commands[:-1] for n in walk(command)):
                return None
            receive_offset = None
            for candidate_offset in range(offset + 1, len(nodes)):
                candidate = nodes[candidate_offset]
                receives = [n for n in walk(candidate) if n.type == "unary_expression" and text(field(n, "operator"), raw) == "<-" and text(field(n, "operand"), raw) == channel]
                if candidate.type in {"short_var_declaration", "assignment_statement", "expression_statement"} and len(receives) == 1:
                    receive_offset = candidate_offset
                    break
                if any(n.type in {"return_statement", "break_statement", "continue_statement"} or n.type == "identifier" and text(n, raw) == channel for n in walk(candidate)):
                    return None
            if receive_offset is None:
                return None
            evidence = proof(analysis, statement, raw)
            dispatched = analysis.call("go " + name + "; completion not yet observed", evidence, target[0].qualified_name,
                                       "project", completion="dispatched", kind="dispatch")[0]
            send = []
            def worker():
                def visit():
                    key = (analysis.context.context_id, parameter_name)
                    bound_channels[key] = channel
                    try:
                        children, terminal = body(target_body, target[2])
                        send.extend(s.evidence_ids[0] for s in analysis.steps if s.context_id == analysis.context.context_id and s.kind == "dispatch")
                        return children, terminal
                    finally:
                        bound_channels.pop(key, None)
                return analysis.call("goroutine body " + name, evidence, target[0].qualified_name, "project", (target[0], visit),
                                     completion="not_observed", kind="call"), False
            parallel, _ = analysis.block("par", "goroutine send and caller before receive", [
                ("producer goroutine; send initiated", worker),
                ("caller until receive", lambda: statements(nodes[offset + 1:receive_offset], raw))], evidence)
            if not send:
                analysis.gap("GO_CHANNEL_RECEIVE", statement.start_point.row + 1, "bound producer send was not found")
                return [dispatched, parallel], receive_offset - 1, False
            key = (analysis.context.context_id, channel, analysis.exit_id)
            observed_channels[key] = (dispatched.step_id, send[-1])
            try:
                observed, terminal = statements((nodes[receive_offset],), raw)
            finally:
                observed_channels.pop(key, None)
            return [dispatched, parallel] + observed, receive_offset, terminal

        def statements(nodes, raw):
            items = []
            consumed = -1
            for offset, node in enumerate(nodes):
                if offset <= consumed:
                    continue
                region = channel_region(nodes, offset, raw)
                if region:
                    children, consumed, terminal = region
                    items.extend(children)
                    if terminal:
                        return items, True
                    continue
                evidence = proof(analysis, node, raw)
                if node.type in {"block", "statement_list"}:
                    more, terminal = body(node, raw)
                    items.extend(more)
                    if terminal:
                        return items, True
                elif node.type == "if_statement":
                    items.extend(expression(field(node, "initializer"), raw))
                    items.extend(expression(field(node, "condition"), raw))
                    block, terminal = analysis.block("alt", text(field(node, "condition"), raw), [("true", lambda: body(field(node, "consequence"), raw)),
                        ("false", lambda: body(field(node, "alternative"), raw))], evidence)
                    items.append(block)
                    if terminal:
                        return items, True
                elif node.type == "for_statement":
                    block, _ = analysis.block("loop", text(next((child for child in node.named_children if child.type in {"for_clause", "range_clause"}), field(node, "condition")), raw),
                        [("iteration", lambda: body(field(node, "body"), raw)), ("loop exit", lambda: ([], False))], evidence)
                    items.append(block)
                    clause = next((child for child in node.named_children if child.type in {"for_clause", "range_clause"}), None)
                    if clause and any(child.type == "call_expression" for child in walk(clause)):
                        analysis.gap("GO_LOOP_CLAUSE_EFFECT", node.start_point.row + 1, "range/loop evaluation timing requires explicit ordering")
                elif node.type in {"expression_switch_statement", "type_switch_statement", "select_statement"}:
                    clauses = [child for child in node.named_children if child.type in {"expression_case", "type_case", "communication_case", "default_case"}]
                    arms = []
                    for clause in clauses:
                        def branch(clause=clause):
                            statements_node = next((child for child in clause.named_children if child.type == "statement_list"), None)
                            children, terminal = body(statements_node, raw)
                            return children, terminal and bool(children) and analysis.steps[-1].kind != "break"
                        condition = next((child for child in clause.named_children if child.type != "statement_list"), None)
                        arms.append((text(condition, raw) or "default", branch))
                    if not any(child.type == "default_case" for child in clauses):
                        arms.append(("no matching case" if node.type != "select_statement" else "blocked / no ready channel", lambda: ([], False)))
                    block, terminal = analysis.block("alt", node.type, arms, evidence, transfer_boundary="switch")
                    items.extend(expression(field(node, "value"), raw))
                    items.append(block)
                    if node.type == "select_statement":
                        analysis.gap("GO_SELECT_RELATIONS", node.start_point.row + 1, "channel readiness and producer completion unexpanded")
                    if terminal:
                        return items, True
                elif node.type == "defer_statement":
                    call = node.named_children[0]
                    # Arguments evaluate now; invocation happens in reverse order on exit.
                    args = field(call, "arguments")
                    for argument in args.named_children if args else ():
                        items.extend(expression(argument, raw))
                    deferred.append((call, raw))
                    items.append(analysis.step("defer_register", "defer registered; arguments evaluated", evidence))
                elif node.type == "go_statement":
                    items.extend(expression(node.named_children[0], raw, True))
                elif node.type == "return_statement":
                    for child in node.named_children:
                        items.extend(expression(child, raw))
                    for call, cleanup_raw in reversed(deferred):
                        items.extend(expression(call, cleanup_raw, evaluate_arguments=False))
                    result_type = text(field(index[analysis.symbol.symbol_id][1], "result"), index[analysis.symbol.symbol_id][2])
                    items.append(analysis.step("return", "return values" + (" (error is a returned value)" if "error" in result_type else "") + ": " + text(node, raw), evidence, completion="observed"))
                    return items, True
                elif node.type in {"break_statement", "continue_statement", "fallthrough_statement"}:
                    items.append(analysis.step(node.type.removesuffix("_statement"), text(node, raw), evidence))
                    if node.type == "fallthrough_statement":
                        analysis.gap("GO_FALLTHROUGH", node.start_point.row + 1, "next case continuation is explicit but not expanded")
                    return items, True
                elif node.type == "send_statement":
                    channel = text(field(node, "channel"), raw)
                    binding = bound_channels.get((analysis.context.context_id, channel))
                    if binding:
                        items.extend(expression(field(node, "value"), raw))
                        items.extend(analysis.call("channel send initiated; receiver processing not claimed", evidence, binding, "summary",
                                                  completion="dispatched", kind="dispatch"))
                        continue
                    analysis.gap("GO_CHANNEL_SEND", node.start_point.row + 1, "channel send does not prove consumer processing or completion")
                    items.append(analysis.step("dispatch", text(node, raw), evidence, completion="dispatched"))
                elif node.type in {"short_var_declaration", "var_declaration", "assignment_statement", "expression_statement", "inc_statement", "dec_statement"}:
                    items.extend(expression(node, raw))
                elif node.type == "comment":
                    continue
                else:
                    analysis.gap("UNSUPPORTED_GO_NODE", node.start_point.row + 1, node.type)
            return items, False

        _, declaration, raw, root = index[scope.symbol.symbol_id]
        parse_gaps(analysis, root)
        for node in root.named_children:
            if node.type == "comment" and ("go:build" in text(node, raw) or "+build" in text(node, raw) or "Code generated" in text(node, raw)):
                analysis.gap("GO_BUILD_OR_GENERATED", node.start_point.row + 1, text(node, raw))
        items, terminal = body(field(declaration, "body"), raw)
        if not terminal:
            for call, cleanup_raw in reversed(deferred):
                items.extend(expression(call, cleanup_raw, evaluate_arguments=False))
        return analysis.finish(items)
