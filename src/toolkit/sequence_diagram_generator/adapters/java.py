"""Java declarations, overload binding and structured execution syntax."""
from dataclasses import replace

from ..models import AdapterCapabilities
from ..repository import digest
from .analysis import _Analysis
from ._tree import field, normalized, parse_gaps, parser_versions, proof, registration, resolve_unique, symbol, text, trees, walk

ROUTES = frozenset({"RequestMapping", "GetMapping", "PostMapping", "PutMapping", "DeleteMapping", "PatchMapping", "Scheduled", "KafkaListener", "RabbitListener"})
KNOWN_ANNOTATIONS = frozenset({"Override", "SuppressWarnings", "Deprecated", "SafeVarargs"})


class JavaAdapter:
    def capabilities(self):
        parser, grammar = parser_versions("java")
        return AdapterCapabilities("java", "tree-sitter", parser, grammar,
            ("if", "switch-fallthrough", "loop", "overload-signature", "return-throw", "try-catch-finally", "executor-dispatch-wait"),
            ("main", "Spring direct imported route annotations", "Scheduled", "KafkaListener", "RabbitListener"),
            ("reflection", "unknown-proxy-DI", "annotation-alias", "generated-declarations", "overload-types"),
            ("test_adapters::java", "test_language_semantics::java-overloads", "test_language_semantics::java-registration", "test_boundaries::java-loop-update", "test_language_semantics::java-executor-future"))

    def _index(self, snapshot):
        indexed = {}
        for file, raw, root in trees(snapshot, {"java"}):
            package = ""
            for candidate in root.named_children:
                if candidate.type == "package_declaration":
                    package = text(candidate, raw).removeprefix("package").strip().rstrip(";")
            def visit(node, owners=()):
                if node.type in {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}:
                    owners += (text(field(node, "name"), raw),)
                if node.type in {"method_declaration", "constructor_declaration"}:
                    name = text(field(node, "name"), raw)
                    params = field(node, "parameters")
                    def parameter_type(child):
                        typ = field(child, "type")
                        if typ is None and child.type == "spread_parameter":
                            typ = next((part for part in child.named_children if part.type not in {"modifiers", "variable_declarator"}), None)
                        return text(typ, raw) + ("..." if child.type == "spread_parameter" else text(field(child, "dimensions"), raw))
                    signature = "(" + ",".join(parameter_type(child)
                                                for child in params.named_children if child.type in {"formal_parameter", "spread_parameter", "receiver_parameter"}) + ")"
                    signature += ":" + text(field(node, "type"), raw)
                    qualified = ".".join(filter(None, (package, *owners, name)))
                    item = symbol(file.path, "java", node, qualified, signature)
                    registrations = []
                    modifiers = next((child for child in node.named_children if child.type == "modifiers"), None)
                    imports = [text(child, raw) for child in root.named_children if child.type == "import_declaration"]
                    for annotation in walk(modifiers) if modifiers else ():
                        if annotation.type not in {"annotation", "marker_annotation"}:
                            continue
                        annotation_name = text(field(annotation, "name"), raw)
                        simple = annotation_name.rsplit(".", 1)[-1]
                        if simple in ROUTES and (annotation_name.startswith("org.springframework.") or any("org.springframework." in value and value.rstrip(";").endswith("." + simple) for value in imports)):
                            registrations.append(registration(item.symbol_id, annotation, raw, file.path, "direct framework annotation binding"))
                    if name == "main" and "static" in text(modifiers, raw) and signature == "(String[]):void":
                        registrations.append(registration(item.symbol_id, node, raw, file.path, "Java main"))
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
        deferred = []
        futures, dispatches, observed_dispatches = {}, {}, set()

        def receiver_type(receiver, call_node, raw):
            declaration = index[analysis.symbol.symbol_id][1]
            parameters = field(declaration, "parameters")
            for parameter in parameters.named_children if parameters else ():
                if text(field(parameter, "name"), raw) == receiver:
                    return text(field(parameter, "type"), raw)
            # Only declarations in enclosing lexical blocks and preceding this call
            # can bind a receiver. An unrelated method's parameter is not evidence.
            parent = call_node.parent
            while parent and parent != declaration:
                if parent.type in {"block", "constructor_body"}:
                    for candidate in reversed(parent.named_children):
                        if candidate.end_byte > call_node.start_byte or candidate.type != "local_variable_declaration":
                            continue
                        if any(child.type == "variable_declarator" and text(field(child, "name"), raw) == receiver for child in candidate.named_children):
                            return text(field(candidate, "type"), raw)
                parent = parent.parent
            return ""

        def imported_type(typ, imports, qualified=None):
            base = typ.split("<", 1)[0].strip()
            if qualified and base == qualified:
                return True
            return any(value.rstrip(";").endswith("." + base) and (qualified is None or value.removeprefix("import ").rstrip(";").strip() == qualified) for value in imports)

        def body(node, raw):
            return statements(node.named_children if node and node.type in {"block", "constructor_body"} else (node,) if node else (), raw)

        def expression(node, raw):
            if node is None:
                return []
            if node.type == "lambda_expression":
                analysis.gap("JAVA_CALLBACK_EXECUTION", node.start_point.row + 1, "lambda execution depends on explicit invoker")
                return []
            if node.type == "ternary_expression":
                items = expression(field(node, "condition"), raw)
                block, _ = analysis.block("alt", text(field(node, "condition"), raw), [("true", lambda: (expression(field(node, "consequence"), raw), False)),
                    ("false", lambda: (expression(field(node, "alternative"), raw), False))], proof(analysis, node, raw))
                return items + [block]
            if node.type == "binary_expression" and text(field(node, "operator"), raw) in {"&&", "||"}:
                operator = text(field(node, "operator"), raw)
                block, _ = analysis.block("alt", "short circuit " + operator, [("evaluate right", lambda: (expression(field(node, "right"), raw), False)),
                    ("short-circuit exit", lambda: ([], False))], proof(analysis, node, raw))
                return expression(field(node, "left"), raw) + [block]
            if node.type in {"method_invocation", "object_creation_expression"}:
                name = text(field(node, "name"), raw) or text(field(node, "type"), raw)
                receiver = text(field(node, "object"), raw)
                arguments = field(node, "arguments")
                items = expression(field(node, "object"), raw)
                for argument in arguments.named_children if arguments else ():
                    items.extend(expression(argument, raw))
                qualified = analysis.symbol.qualified_name.rsplit(".", 1)[0] + "." + name
                candidates = [item for item in index.values() if item[0].qualified_name == qualified]
                target = resolve_unique(index, qualified, len(arguments.named_children) if arguments else 0) if not receiver or receiver == "this" else None
                # Same-arity overloads require type resolution; never choose one arbitrarily.
                evidence = proof(analysis, node, raw)
                resolution = "project" if target else "unknown"
                if candidates and not target and not receiver:
                    analysis.gap("JAVA_OVERLOAD_AMBIGUOUS", node.start_point.row + 1, "overload argument types cannot be uniquely bound")
                root = index[analysis.symbol.symbol_id][3]
                imports = [text(child, index[analysis.symbol.symbol_id][2]) for child in root.named_children if child.type == "import_declaration"]
                imported = any(value.rstrip(";").endswith("." + receiver.split(".")[0]) for value in imports)
                if receiver == "System.out" and name == "println":
                    resolution = "summary"
                elif imported or node.type == "object_creation_expression" and any(value.rstrip(";").endswith("." + name) for value in imports):
                    resolution = "boundary"
                if receiver and receiver not in {"this", "System.out"}:
                    # Receiver fields/parameters require a declared type; names alone are not evidence.
                    typ = receiver_type(receiver, node, raw)
                    if typ and imported_type(typ, imports):
                        resolution = "boundary"
                dispatch = name in {"submit", "execute", "start"} and resolution == "boundary"
                typ = receiver_type(receiver, node, raw)
                exact_submit = (name == "submit" and imported_type(typ, imports, "java.util.concurrent.ExecutorService")
                                and arguments is not None and len(arguments.named_children) == 1
                                and arguments.named_children[0].type == "identifier"
                                and any(imported_type(receiver_type(text(arguments.named_children[0], raw), node, raw), imports, task_type)
                                        for task_type in ("java.util.concurrent.Callable", "java.lang.Runnable")))
                if exact_submit:
                    resolution, dispatch = "summary", True
                future_key = (analysis.context.context_id, receiver)
                waiting = (name == "get" and imported_type(typ, imports, "java.util.concurrent.Future")
                           and arguments is not None and not arguments.named_children and future_key in futures)
                if dispatch:
                    if not exact_submit:
                        analysis.gap("JAVA_ASYNC_COMPLETION", node.start_point.row + 1, "dispatch and future/thread completion must be bound")
                build = None
                if target:
                    target_symbol, declaration, target_raw, _ = target
                    def visit():
                        saved = tuple(deferred)
                        deferred.clear()
                        try:
                            return body(field(declaration, "body"), target_raw)
                        finally:
                            deferred.extend(saved)
                    build = (target_symbol, visit)
                called = analysis.call((receiver + "." if receiver else "") + name, evidence, target[0].qualified_name if target else receiver or name,
                                       resolution, build, "dispatched" if dispatch else "returned", "dispatch" if dispatch else "call")
                items += called
                if exact_submit:
                    dispatches[called[0].step_id] = node.start_point.row + 1
                    owner = node.parent
                    if owner and owner.type == "variable_declarator" and field(owner, "value") == node:
                        variable_type = text(field(owner.parent, "type"), raw)
                        if imported_type(variable_type, imports, "java.util.concurrent.Future"):
                            futures[(analysis.context.context_id, text(field(owner, "name"), raw))] = (called[0].step_id, analysis.exit_id)
                if waiting:
                    dependency, dispatch_exit = futures[future_key]
                    items.append(analysis.step("wait", "completion observed by Future.get", evidence, receiver, "observed", (dependency,)))
                    if dispatch_exit == analysis.exit_id:
                        observed_dispatches.add(dependency)
                    else:
                        analysis.gap("JAVA_CONDITIONAL_COMPLETION", node.start_point.row + 1, "future completion is not observed on every dispatch path")
                if name in {"forName", "getMethod", "invoke", "newInstance"}:
                    analysis.gap("JAVA_REFLECTION", node.start_point.row + 1, name)
                return items
            items = []
            for child in node.named_children:
                if child.type not in {"comment", "line_comment", "block_comment"}:
                    items.extend(expression(child, raw))
            return items

        def statements(nodes, raw):
            items = []
            for node in nodes:
                if node is None:
                    continue
                evidence = proof(analysis, node, raw)
                if node.type == "if_statement":
                    items.extend(expression(field(node, "condition"), raw))
                    block, terminal = analysis.block("alt", text(field(node, "condition"), raw), [("true", lambda: body(field(node, "consequence"), raw)),
                        ("false", lambda: body(field(node, "alternative"), raw))], evidence)
                    items.append(block)
                    if terminal:
                        return items, True
                elif node.type in {"for_statement", "enhanced_for_statement", "while_statement", "do_statement"}:
                    items.extend(expression(field(node, "init"), raw))
                    def iteration():
                        children, terminal = body(field(node, "body"), raw)
                        if not terminal:
                            children.extend(expression(field(node, "update"), raw))
                        elif field(node, "update"):
                            analysis.gap("LOOP_CONTROL_TRANSFER", node.start_point.row + 1, "update timing after break/continue/return requires exit-specific binding")
                        return children, terminal
                    if node.type == "do_statement":
                        arms = [("first mandatory iteration", iteration), ("condition false / exit", lambda: ([], False))]
                        analysis.gap("JAVA_DO_LOOP", node.start_point.row + 1, "mandatory first iteration cannot be represented as a zero-or-more loop")
                    else:
                        arms = [("iteration", iteration), ("condition false / exit", lambda: ([], False))]
                    block, _ = analysis.block("loop", text(field(node, "condition") or field(node, "value"), raw), arms, evidence)
                    items.append(block)
                    if any(child.type == "method_invocation" for child in walk(field(node, "condition"))) if field(node, "condition") else False:
                        analysis.gap("LOOP_CONDITION_SIDE_EFFECT", node.start_point.row + 1, "repeated condition call must retain per-iteration ordering")
                elif node.type in {"switch_expression", "switch_statement"}:
                    items.extend(expression(field(node, "condition"), raw))
                    switch_body = field(node, "body")
                    groups = [child for child in switch_body.named_children if child.type in {"switch_block_statement_group", "switch_rule"}]
                    arms = []
                    for offset, group in enumerate(groups):
                        labels = [child for child in group.named_children if child.type == "switch_label"]
                        def branch(offset=offset, group=group):
                            children = []
                            for subsequent in groups[offset:]:
                                commands = [child for child in subsequent.named_children if child.type != "switch_label"]
                                more, terminal = statements(commands, raw)
                                children.extend(more)
                                if terminal or subsequent.type == "switch_rule":
                                    return children, terminal and bool(more) and analysis.steps[-1].kind not in {"break"}
                            return children, False
                        arms.append((" / ".join(text(label, raw) for label in labels) or "switch rule", branch))
                    if not any("default" in text(group, raw).split(":", 1)[0] for group in groups):
                        arms.append(("no matching case", lambda: ([], False)))
                    block, terminal = analysis.block("alt", "switch", arms, evidence, transfer_boundary="switch")
                    items.append(block)
                    if terminal:
                        return items, True
                elif node.type in {"return_statement", "throw_statement", "break_statement", "continue_statement"}:
                    for child in node.named_children:
                        items.extend(expression(child, raw))
                    if node.type in {"return_statement", "throw_statement"}:
                        saved = tuple(deferred)
                        deferred.clear()
                        for cleanup_node, cleanup_raw in reversed(saved):
                            items.extend(body(cleanup_node, cleanup_raw)[0])
                        deferred.extend(saved)
                    items.append(analysis.step(node.type.removesuffix("_statement"), text(node, raw), evidence, completion="observed"))
                    return items, True
                elif node.type in {"try_statement", "try_with_resources_statement"}:
                    finally_node = next((child for child in node.named_children if child.type == "finally_clause"), None)
                    cleanup_node = next((child for child in finally_node.named_children if child.type == "block"), None) if finally_node else None
                    def branch(block, normal=False):
                        if cleanup_node:
                            deferred.append((cleanup_node, raw))
                        result, terminal = body(block, raw)
                        if cleanup_node:
                            deferred.pop()
                            if not terminal:
                                result.extend(body(cleanup_node, raw)[0])
                        return result, terminal
                    arms = [("normal", lambda: branch(field(node, "body"), True))]
                    for catch in node.named_children:
                        if catch.type == "catch_clause":
                            arms.append((text(next((child for child in catch.named_children if child.type == "catch_formal_parameter"), catch), raw),
                                         lambda catch=catch: branch(field(catch, "body"))))
                    block, terminal = analysis.block("alt", "try / catch", arms, evidence)
                    items.append(block)
                    analysis.gap("EXCEPTION_ORIGIN_UNKNOWN", node.start_point.row + 1, "interrupted prefixes and exception types require additional resolution")
                    if node.type == "try_with_resources_statement":
                        analysis.gap("JAVA_RESOURCE_CLOSE", node.start_point.row + 1, "close/suppressed exceptions are not expanded")
                    if terminal:
                        return items, True
                elif node.type == "synchronized_statement":
                    analysis.gap("JAVA_MONITOR_INTERLEAVING", node.start_point.row + 1, "monitor ordering only; concurrent schedules unproven")
                    items.extend(body(field(node, "body"), raw)[0])
                elif node.type in {"expression_statement", "local_variable_declaration", "block", "switch_rule"}:
                    if node.type == "block":
                        children, terminal = body(node, raw)
                        items.extend(children)
                        if terminal:
                            return items, True
                    else:
                        items.extend(expression(node, raw))
                elif node.type in {"line_comment", "block_comment", "empty_statement"}:
                    continue
                else:
                    analysis.gap("UNSUPPORTED_JAVA_NODE", node.start_point.row + 1, node.type)
            return items, False

        _, declaration, raw, root = index[scope.symbol.symbol_id]
        parse_gaps(analysis, root)
        modifiers = next((child for child in declaration.named_children if child.type == "modifiers"), None)
        for annotation in walk(modifiers) if modifiers else ():
            if annotation.type in {"annotation", "marker_annotation"}:
                name = text(field(annotation, "name"), raw).rsplit(".", 1)[-1]
                bound = any(e.digest == digest(normalized(annotation, raw)) for e in scope.symbol.registration_evidence)
                if name not in KNOWN_ANNOTATIONS and not bound:
                    analysis.gap("UNKNOWN_JAVA_ANNOTATION", annotation.start_point.row + 1, name)
        items = body(field(declaration, "body"), raw)[0]
        for identifier, line in dispatches.items():
            if identifier not in observed_dispatches:
                analysis.gap("JAVA_ASYNC_COMPLETION", line, "submitted task has no bound Future.get observation")
        return analysis.finish(items)
