"""Python AST analysis with explicit control blocks and conservative binding."""
from __future__ import annotations

import ast
import sys

from ..models import AdapterCapabilities, Evidence, SourceSymbol
from ..repository import digest, stable_id
from .analysis import _Analysis

PURE = frozenset({"len", "str", "int", "bool", "float", "range", "list", "tuple", "dict", "set", "enumerate", "zip", "print"})


class PythonAdapter:
    def capabilities(self):
        return AdapterCapabilities("python", "stdlib.ast", sys.version.split()[0], sys.version.split()[0],
            ("if", "conditional-expression", "comprehension-filter", "match-guard", "loop-else", "return", "raise", "try-except-else-finally", "with", "async-await"),
            ("explicit-symbol", "FastAPI direct imported decorators", "argparse direct set_defaults(func=)"),
            ("unsupported-runtime-syntax", "dynamic-import-getattr", "monkey-patch", "unknown-decorator", "lazy-generator"),
            ("test_adapters::python", "test_language_semantics::python-registration", "test_language_semantics::python-finally", "test_boundaries::python-dynamic"))

    def _index(self, snapshot):
        indexed, imports, trees, source = {}, {}, {}, dict(snapshot.contents)
        for file in snapshot.files:
            if file.language != "python":
                continue
            module = file.path[:-3].replace("/", ".")
            text = source[file.path].decode("utf-8-sig")
            tree = ast.parse(text, filename=file.path)
            trees[file.path] = tree
            bindings = {}
            for item in tree.body:
                if isinstance(item, ast.Import):
                    for alias in item.names:
                        bindings[alias.asname or alias.name.split(".")[0]] = alias.name
                elif isinstance(item, ast.ImportFrom):
                    for alias in item.names:
                        prefix = item.module or ""
                        if item.level:
                            parent = module.split(".")[:-item.level]
                            prefix = ".".join((*parent, prefix)).strip(".")
                        bindings[alias.asname or alias.name] = prefix + "." + alias.name
            imports[file.path] = bindings
            def declarations(items, owners=()):
                for item in items:
                    if isinstance(item, ast.ClassDef):
                        declarations(item.body, owners + (item.name,))
                    elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qualified = ".".join((module, *owners, item.name))
                        signature = ast.unparse(item.args) + (" -> " + ast.unparse(item.returns) if item.returns else "")
                        sid = stable_id("F", file.path, qualified, signature)
                        registration = []
                        instances = {n.targets[0].id: n.value.func.id for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                                     and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)}
                        for decorator in item.decorator_list:
                            target = decorator.func if isinstance(decorator, ast.Call) else decorator
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                                cls = instances.get(target.value.id, "")
                                if bindings.get(cls) in {"fastapi.FastAPI", "fastapi.APIRouter"} and target.attr in {"get", "post", "put", "delete", "patch", "options", "head", "api_route"}:
                                    registration.append(Evidence(stable_id("E", sid, ast.dump(decorator, include_attributes=False)), "code", file.path,
                                        f"line:{decorator.lineno}", digest(ast.dump(decorator, include_attributes=False)), sid, "direct FastAPI registration", ast.unparse(decorator)))
                        for candidate in ast.walk(tree):
                            if isinstance(candidate, ast.Call) and isinstance(candidate.func, ast.Attribute) and candidate.func.attr == "set_defaults":
                                receiver = candidate.func.value
                                cls = instances.get(receiver.id, "") if isinstance(receiver, ast.Name) else ""
                                if bindings.get(cls) == "argparse.ArgumentParser" and any(k.arg == "func" and isinstance(k.value, ast.Name) and k.value.id == item.name for k in candidate.keywords):
                                    registration.append(Evidence(stable_id("E", sid, ast.dump(candidate, include_attributes=False)), "code", file.path, f"line:{candidate.lineno}",
                                        digest(ast.dump(candidate, include_attributes=False)), sid, "direct argparse binding", ast.unparse(candidate)))
                        symbol = SourceSymbol(sid, qualified, signature, "python", file.path, item.lineno, item.end_lineno or item.lineno,
                                              "registered" if registration else "symbol", tuple(registration))
                        indexed[sid] = (symbol, item)
                        # Nested functions are declarations, but their binding is lexical.
                        declarations(item.body, owners + (item.name,))
            declarations(tree.body)
        return indexed, imports, trees, source

    def discover(self, snapshot):
        return tuple(symbol for symbol, _ in self._index(snapshot)[0].values())

    def analyze(self, snapshot, scope):
        indexed, imports, trees, source = self._index(snapshot)
        analysis = _Analysis(scope)
        by_name = {symbol.qualified_name: (symbol, node) for symbol, node in indexed.values()}
        def lexical_bindings(declaration):
            args = declaration.args
            names = {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            names.update(arg.arg for arg in (args.vararg, args.kwarg) if arg)
            def visit(node):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                    return
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    names.add(node.id)
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
                for child in ast.iter_child_nodes(node):
                    visit(child)
            for node in declaration.body:
                visit(node)
            return dict.fromkeys(names, "")
        local_bindings = lexical_bindings(indexed[scope.symbol.symbol_id][1])
        finalizers = []

        def control_block(kind, label, arms, evidence):
            # Each arm starts with the same bindings. Only agreement on all
            # continuing paths establishes a receiver after the merge.
            incoming, outcomes = dict(local_bindings), []
            def isolated(build):
                def visit():
                    local_bindings.clear()
                    local_bindings.update(incoming)
                    result = build()
                    if not result[1]:
                        outcomes.append(dict(local_bindings))
                    return result
                return visit
            try:
                result = analysis.block(kind, label, [(name, isolated(build)) for name, build in arms], evidence)
                if kind in {"loop", "opt"}:
                    outcomes.append(incoming)
                names = set(incoming).union(*(set(value) for value in outcomes))
                merged = {name: outcomes[0].get(name, "") if outcomes and all(
                    value.get(name, "") == outcomes[0].get(name, "") for value in outcomes) else "" for name in names}
            finally:
                local_bindings.clear()
                local_bindings.update(incoming)
            local_bindings.update(merged)
            return result

        def proof(node):
            normalized = ast.dump(node, include_attributes=False)
            return analysis.proof(normalized, node.lineno, node.end_lineno or node.lineno, ast.unparse(node))

        def resolve(node):
            symbol = analysis.symbol
            prefix = symbol.qualified_name.rsplit(".", 1)[0]
            module = symbol.path[:-3].replace("/", ".")
            name = ast.unparse(node)
            candidates = []
            if isinstance(node, ast.Name):
                if node.id in local_bindings:
                    return None, "unknown", name
                qualified = imports[symbol.path].get(node.id, "")
                candidates = [prefix + "." + node.id, module + "." + node.id, qualified]
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    receiver = node.value.id
                    if receiver in {"self", "cls"} and any(
                        isinstance(node, ast.ClassDef) and prefix.endswith("." + node.name)
                        for node in ast.walk(trees[symbol.path])):
                        candidates = [prefix + "." + node.attr]
                    elif receiver in local_bindings:
                        candidates = [local_bindings[receiver] + "." + node.attr]
                    elif receiver in imports[symbol.path]:
                        candidates = [imports[symbol.path][receiver] + "." + node.attr]
            matches = [by_name[key] for key in dict.fromkeys(candidates) if key in by_name]
            if len(matches) == 1:
                return matches[0], "project", matches[0][0].qualified_name
            root = name.split(".")[0]
            if isinstance(node, ast.Name) and node.id in PURE:
                return None, "summary", "Python builtin " + name
            if root in local_bindings and not local_bindings[root]:
                return None, "unknown", name
            if root in imports[symbol.path] or root in local_bindings:
                return None, "boundary", imports[symbol.path].get(root, local_bindings.get(root, name))
            return None, "unknown", name

        def expression(node, awaited=False):
            if node is None:
                return []
            if isinstance(node, ast.Lambda):
                analysis.gap("DEFERRED_CALLABLE", node.lineno, "lambda is not executed at declaration")
                return []
            if isinstance(node, ast.Await):
                return expression(node.value, True)
            if isinstance(node, ast.IfExp):
                items = expression(node.test)
                block, _ = control_block("alt", ast.unparse(node.test), [("true", lambda: (expression(node.body), False)),
                    ("false", lambda: (expression(node.orelse), False))], proof(node))
                return items + [block]
            if isinstance(node, ast.BoolOp):
                items = expression(node.values[0])
                for operand in node.values[1:]:
                    label = "truthy" if isinstance(node.op, ast.And) else "falsy"
                    block, _ = control_block("alt", "short circuit", [(label, lambda operand=operand: (expression(operand), False)),
                        ("short-circuit exit", lambda: ([], False))], proof(node))
                    items.append(block)
                return items
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                if isinstance(node, ast.GeneratorExp):
                    analysis.gap("LAZY_GENERATOR", node.lineno, "generator execution depends on consumption; not treated as immediate")
                    return expression(node.generators[0].iter)
                def generator(index):
                    if index == len(node.generators):
                        return expression(node.key) + expression(node.value) if isinstance(node, ast.DictComp) else expression(node.elt)
                    gen = node.generators[index]
                    if gen.is_async:
                        analysis.gap("ASYNC_ITERATION_BOUNDARY", node.lineno, "async iterator producer internals not resolved")
                    def filters(filter_index):
                        if filter_index == len(gen.ifs):
                            return generator(index + 1)
                        condition = gen.ifs[filter_index]
                        block, _ = control_block("alt", ast.unparse(condition), [("filter true", lambda: (filters(filter_index + 1), False)),
                            ("filter false / skip", lambda: ([], False))], proof(condition))
                        return expression(condition) + [block]
                    block, _ = control_block("loop", ast.unparse(gen.iter), [("iteration", lambda: (filters(0), False)), ("exhausted", lambda: ([], False))], proof(node))
                    return expression(gen.iter) + [block]
                return generator(0)
            if isinstance(node, ast.Call):
                items = []
                if isinstance(node.func, ast.Attribute):
                    items.extend(expression(node.func.value))
                elif not isinstance(node.func, ast.Name):
                    items.extend(expression(node.func))
                for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                    items.extend(expression(argument))
                target, resolution, receiver = resolve(node.func)
                evidence = proof(node)
                name = ast.unparse(node.func)
                side_effect = ""
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    binding = local_bindings.get(node.func.value.id, imports[analysis.symbol.path].get(node.func.value.id, ""))
                    if binding == "sqlite3" and node.func.attr == "connect":
                        resolution, receiver = "summary", "stdlib.sqlite3.connect"
                    elif binding == "sqlite3.Connection" and node.func.attr in {"execute", "commit", "rollback", "close"}:
                        resolution, receiver = "summary", "stdlib.sqlite3.Connection." + node.func.attr
                        if node.func.attr == "execute":
                            sql = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else ""
                            keyword = sql.split(None, 1)[0].upper() if sql.strip() else ""
                            if keyword in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
                                side_effect = "persistence: statement issued; execute return is separate from transaction commit"
                            elif keyword != "SELECT":
                                analysis.gap("SQL_STATEMENT_BOUNDARY", node.lineno, "SQL operation category is not bound to a supported literal statement")
                        elif node.func.attr in {"commit", "rollback"}:
                            side_effect = "persistence: transaction " + node.func.attr + " issued; completion only after driver return"
                dynamic = name in {"getattr", "setattr", "__import__", "eval", "exec", "importlib.import_module"}
                if dynamic:
                    analysis.gap("DYNAMIC_PYTHON", node.lineno, name)
                if target:
                    symbol, declaration = target
                    is_async = isinstance(declaration, ast.AsyncFunctionDef)
                    if is_async and not awaited:
                        analysis.gap("UNAWAITED_COROUTINE", node.lineno, "coroutine constructed; body execution not established")
                        return items + analysis.call(name, evidence, receiver, "project", completion="not_observed", kind="construct")
                    def visit():
                        saved_finalizers = tuple(finalizers)
                        saved_bindings = dict(local_bindings)
                        finalizers.clear()
                        local_bindings.clear()
                        local_bindings.update(lexical_bindings(declaration))
                        try:
                            return statements(declaration.body)
                        finally:
                            finalizers.extend(saved_finalizers)
                            local_bindings.clear()
                            local_bindings.update(saved_bindings)
                    items += analysis.call(name, evidence, receiver, resolution, (symbol, visit), "returned")
                else:
                    dispatch = name in {"asyncio.create_task", "asyncio.ensure_future"}
                    if dispatch:
                        analysis.gap("ASYNC_COMPLETION_UNKNOWN", node.lineno, "task dispatch has no established join relationship")
                    items += analysis.call(name, evidence, receiver, resolution, completion="dispatched" if dispatch else "returned",
                                           kind="dispatch" if dispatch else "call", side_effect=side_effect)
                if awaited:
                    items.append(analysis.step("await", "await observed completion", evidence, receiver, "observed"))
                return items
            items = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    items.extend(expression(child))
            return items

        def cleanup():
            items = []
            # Finalizers are executed innermost first. Suppress them while visiting themselves.
            saved = tuple(finalizers)
            finalizers.clear()
            for body in reversed(saved):
                children, terminal = statements(body)
                items.extend(children)
                if terminal:
                    analysis.gap("CLEANUP_OVERRIDES_TERMINATION", body[0].lineno, "cleanup return/raise overrides pending exit")
            finalizers.extend(saved)
            return items

        def statements(body):
            items = []
            for node in body:
                evidence = proof(node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.Pass)):
                    continue
                if isinstance(node, ast.If):
                    items.extend(expression(node.test))
                    block, terminal = control_block("alt", ast.unparse(node.test), [("true", lambda: statements(node.body)),
                        ("false", lambda: statements(node.orelse))], evidence)
                    items.append(block)
                    if terminal:
                        return items, True
                elif isinstance(node, ast.Match):
                    items.extend(expression(node.subject))
                    arms = []
                    for case in node.cases:
                        def visit_case(case=case):
                            if case.guard:
                                block, terminal = control_block("alt", ast.unparse(case.guard), [("guard true", lambda: statements(case.body)),
                                    ("guard false / next pattern", lambda: ([], False))], proof(case.guard))
                                return expression(case.guard) + [block], terminal
                            return statements(case.body)
                        arms.append((ast.unparse(case.pattern), visit_case))
                    if not any(isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None and case.guard is None for case in node.cases):
                        arms.append(("no pattern matched", lambda: ([], False)))
                    block, terminal = control_block("alt", "match " + ast.unparse(node.subject), arms, evidence)
                    items.append(block)
                    if any(case.guard for case in node.cases):
                        analysis.gap("MATCH_GUARD_CONTINUATION", node.lineno, "guard failure resumes pattern selection; relation retained but not expanded")
                    if terminal:
                        return items, True
                elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                    condition = node.test if isinstance(node, ast.While) else node.iter
                    items.extend(expression(condition))
                    block, _ = control_block("loop", ast.unparse(condition), [("iteration", lambda: statements(node.body)),
                        ("normal exhaustion / else", lambda: statements(node.orelse)), ("break exit", lambda: ([], False))], evidence)
                    items.append(block)
                    if isinstance(node, ast.AsyncFor):
                        analysis.gap("ASYNC_ITERATION_BOUNDARY", node.lineno, "iterator scheduling/producer not resolved")
                elif isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    items.extend(expression(getattr(node, "value", None) or getattr(node, "exc", None)))
                    if isinstance(node, (ast.Return, ast.Raise)):
                        items.extend(cleanup())
                    kind = type(node).__name__.lower()
                    items.append(analysis.step(kind, ast.unparse(node), evidence, completion="observed"))
                    return items, True
                elif isinstance(node, (ast.Try, ast.TryStar)):
                    if isinstance(node, ast.TryStar):
                        analysis.gap("EXCEPTION_GROUP", node.lineno, "except* splitting is outside this adapter's exception binding")
                    def normal():
                        finalizers.append(node.finalbody)
                        children, terminal = statements(node.body)
                        if not terminal:
                            more, terminal = statements(node.orelse)
                            children.extend(more)
                        finalizers.pop()
                        if not terminal:
                            children.extend(statements(node.finalbody)[0])
                        return children, terminal
                    arms = [("normal", normal)]
                    for handler in node.handlers:
                        def handle(handler=handler):
                            finalizers.append(node.finalbody)
                            children, terminal = statements(handler.body)
                            finalizers.pop()
                            if not terminal:
                                children.extend(statements(node.finalbody)[0])
                            return children, terminal
                        arms.append(("except " + (ast.unparse(handler.type) if handler.type else "BaseException"), handle))
                    if not node.handlers or all(handler.type is not None for handler in node.handlers):
                        def propagate():
                            children, _ = statements(node.finalbody)
                            children.append(analysis.step("raise", "uncaught exception propagates", evidence))
                            return children, True
                        arms.append(("uncaught exception", propagate))
                    block, terminal = control_block("alt", "try / exception paths", arms, evidence)
                    items.append(block)
                    analysis.gap("EXCEPTION_ORIGIN_UNKNOWN", node.lineno, "exception path can begin inside a call; exact interrupted prefix is not statically established")
                    if terminal:
                        return items, True
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for resource in node.items:
                        items.extend(expression(resource.context_expr, isinstance(node, ast.AsyncWith)))
                    items.append(analysis.step("resource_enter", "context manager enter", evidence))
                    children, terminal = statements(node.body)
                    items.extend(children)
                    items.append(analysis.step("cleanup", "context manager exit; suppression semantics unexpanded", evidence))
                    analysis.gap("CONTEXT_MANAGER_SEMANTICS", node.lineno, "__enter__/__exit__ binding and exception suppression must be resolved")
                    if terminal:
                        return items, True
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr)):
                    value = node.value
                    items.extend(expression(value))
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                        for target in targets:
                            if isinstance(target, ast.Attribute):
                                analysis.gap("OBJECT_MUTATION", node.lineno, "attribute write may alter later dispatch or observable state")
                            if isinstance(target, ast.Name):
                                local_bindings[target.id] = ""
                                if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                                    and value.func.id not in local_bindings
                                    and imports[analysis.symbol.path].get(value.func.id) == "sqlite3.connect"):
                                    local_bindings[target.id] = "sqlite3.Connection"
                                elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "connect"
                                      and isinstance(value.func.value, ast.Name) and value.func.value.id not in local_bindings
                                      and imports[analysis.symbol.path].get(value.func.value.id) == "sqlite3"):
                                    local_bindings[target.id] = "sqlite3.Connection"
                elif isinstance(node, ast.Assert):
                    block, _ = control_block("alt", ast.unparse(node.test), [("true", lambda: ([], False)),
                        ("false", lambda: ([analysis.step("raise", "AssertionError", evidence)], True))], evidence)
                    items.extend(expression(node.test))
                    items.append(block)
                else:
                    analysis.gap("UNSUPPORTED_PYTHON_NODE", node.lineno, type(node).__name__)
            return items, False

        symbol, declaration = indexed[scope.symbol.symbol_id]
        for decorator in declaration.decorator_list:
            if not any(item.digest == digest(ast.dump(decorator, include_attributes=False)) for item in symbol.registration_evidence):
                analysis.gap("UNKNOWN_DECORATOR", decorator.lineno, ast.unparse(decorator))
        items, _ = statements(declaration.body)
        return analysis.finish(items)
