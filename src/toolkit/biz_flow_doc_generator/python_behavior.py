"""Bounded Python AST behavior facts."""
import ast
from .evidence import Facts, stable_id


class PythonFacts(Facts):
    def __init__(self, *args, index=None):
        super().__init__(*args)
        self.definitions, self.parents, self.environments, self.shadowed = {}, {}, {}, {}
        self.exception_scopes = []
        if index is not None:
            self.definitions, self.parents, self.shadowed = index
            return
        for file, source in self.sources.items():
            if not file.endswith(".py"):
                continue
            try:
                root = ast.parse(source)
            except SyntaxError:
                continue
            self.parents.update({child: node for node in ast.walk(root) for child in ast.iter_child_nodes(node)})
            self.shadowed[file] = {n.id for n in ast.walk(root) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            self.shadowed[file].update(a.asname or a.name.split(".")[0] for n in ast.walk(root)
                                      if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names)
            self.shadowed[file].update(n.name for n in ast.walk(root)
                                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            for node in ast.walk(root):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parent = self.parents.get(node)
                    if not isinstance(parent, (ast.Module, ast.ClassDef)):
                        continue
                    owner = parent.name if isinstance(parent, ast.ClassDef) else ""
                    self.definitions[(file, owner, node.name)] = node

    def analyze(self):
        matches = [(key, node) for key, node in self.definitions.items()
                   if key[0] == self.entry.file and key[2] == self.entry.handler.rsplit(".", 1)[-1]]
        if len(matches) != 1:
            self.gap("ENTRY_DECLARATION_UNRESOLVED", self.entry.entry_id, self.entry.entry_id, "Unique Python entry declaration required")
        else:
            key, node = matches[0]
            self.participant(self.entry.caller, "caller")
            self.expand(key, node, stable_id("K", self.entry.entry_id, key), "entry", [])
        return self.finish()

    def expand(self, key, node, context, phase, controls):
        source = self.source(key[0], node, ":".join(key))
        if key in self.stack:
            self.gap("RECURSION_BOUNDARY", source, context, "Recursive Python call", controls=controls)
            return
        self.stack.append(key)
        self.environments[context] = {"self": key[1], "cls": key[1]}
        self.environments[context].update({arg.arg: ast.unparse(arg.annotation) for arg in
            [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs] if arg.annotation})
        self.participant(self.owner(key), "service")
        if len(self.stack) > 1 and any(not isinstance(d, ast.Name) or d.id not in {"staticmethod", "classmethod"}
                                       for d in node.decorator_list):
            self.gap("DECORATED_CALL_CONTRACT_UNSUPPORTED", source, context,
                     "Decorator may replace/wrap the executable declaration", controls=controls)
        if isinstance(node, ast.AsyncFunctionDef):
            self.gap("ASYNC_SEMANTICS_UNSUPPORTED", source, context,
                     "Coroutine scheduling, awaiting and cancellation need a supported contract", controls=controls)
        if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node)):
            self.gap("LAZY_EXECUTION_UNSUPPORTED", source, context,
                     "Generator body execution cannot be inferred from the call alone", controls=controls)
        if self.block(node.body, key, context, phase, controls):
            self.outcome("normal_completion" if len(self.stack) == 1 else "method_return", source, context, phase, controls)
        self.stack.pop()

    @staticmethod
    def owner(key):
        return key[0] + ":" + key[1]

    def block(self, statements, key, context, phase, controls):
        for node in statements:
            if not self.visit(node, key, context, phase, controls):
                return False
        return True

    def visit(self, node, key, context, phase, controls):
        self.count += 1
        source = self.source(key[0], node, ":".join(key)) if hasattr(node, "lineno") else ""
        if self.count > self.budget:
            self.gap("ANALYSIS_BUDGET_EXCEEDED", source, context, "Python AST expansion budget reached", controls=controls)
            return False
        # A callback/local declaration is a value, not an invocation. Dynamic
        # execution is rejected at the actual call rather than eagerly inlined.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            for expression in getattr(node, "decorator_list", []):
                self.visit(expression, key, context, phase, controls)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for expression in [*node.args.defaults, *[v for v in node.args.kw_defaults if v]]:
                    self.visit(expression, key, context, phase, controls)
            return True
        if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)):
            self.gap("ASYNC_SEMANTICS_UNSUPPORTED", source, context,
                     "Await/async iteration/context cleanup needs an async contract", controls=controls)
        if isinstance(node, (ast.GeneratorExp, ast.Yield, ast.YieldFrom)):
            self.gap("LAZY_EXECUTION_UNSUPPORTED", source, context,
                     "Lazy execution requires consumption and suspension evidence", controls=controls)
            return True
        if isinstance(node, ast.BoolOp):
            self.visit(node.values[0], key, context, phase, controls)
            active = list(controls)
            branches = []
            arm = "left_true" if isinstance(node.op, ast.And) else "left_false"
            for previous, value in zip(node.values, node.values[1:]):
                branch = self.add("branches", "short_circuit", source, context, phase, active,
                    {"condition": ast.unparse(previous), "operator": "and" if isinstance(node.op, ast.And) else "or",
                     "arms": [arm, "alternative"], "non_decision_connector": True})
                self.step("control_start", branch, active)
                branches.append((branch, active))
                active = [*active, branch["fact_id"], arm]
                self.visit(value, key, context, phase, active)
            for branch, outer in reversed(branches):
                self.step("control_else", branch, outer, "alternative")
                self.step("control_end", branch, outer)
            return True
        if isinstance(node, ast.IfExp):
            self.visit(node.test, key, context, phase, controls)
            branch = self.add("branches", "ternary_expression", source, context, phase, controls,
                {"condition": ast.unparse(node.test), "arms": ["true", "false"]})
            self.step("control_start", branch, controls)
            self.visit(node.body, key, context, phase, [*controls, branch["fact_id"], "true"])
            self.step("control_else", branch, controls, "false")
            self.visit(node.orelse, key, context, phase, [*controls, branch["fact_id"], "false"])
            self.step("control_end", branch, controls)
            return True
        if isinstance(node, ast.Match):
            self.visit(node.subject, key, context, phase, controls)
            branch = self.add("branches", "Match", source, context, phase, controls,
                {"condition": ast.unparse(node.subject), "arms": [ast.unparse(case.pattern) for case in node.cases]})
            self.step("control_start", branch, controls)
            completed, exhaustive = False, False
            for i, case in enumerate(node.cases):
                if i:
                    self.step("control_else", branch, controls, ast.unparse(case.pattern))
                active = [*controls, branch["fact_id"], ast.unparse(case.pattern)]
                supported = (isinstance(case.pattern, ast.MatchValue) and isinstance(case.pattern.value, ast.Constant)
                             or isinstance(case.pattern, ast.MatchSingleton)
                             or isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None and case.pattern.name is None)
                if not supported or case.guard:
                    self.gap("CONTROL_SEMANTICS_UNSUPPORTED", source, context,
                             "Only literal match patterns and an unguarded wildcard are supported", controls=active)
                exhaustive |= isinstance(case.pattern, ast.MatchAs) and case.pattern.name is None and not case.guard
                completed |= self.block(case.body, key, context, phase, active)
            self.step("control_end", branch, controls)
            return completed or not exhaustive
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.TryStar, ast.Assert)):
            self.gap("CONTROL_SEMANTICS_UNSUPPORTED", source, context,
                     "Explicit control/exception semantics not supported: " + type(node).__name__, controls=controls)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value:
                self.visit(node.value, key, context, phase, controls)
            typ = ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) else (
                node.value.func.id if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) else "")
            for target in [node.target] if isinstance(node, ast.AnnAssign) else node.targets:
                self.environments[context][ast.unparse(target)] = typ
            return True
        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp)):
            condition = ast.unparse(getattr(node, "test", None) or getattr(node, "iter", None) or node).splitlines()[0]
            b = self.add("branches", type(node).__name__, source, context, phase, controls,
                         {"condition": condition, "arms": ["body", "alternative"], "reachability": "conditional"})
            nested = [*controls, b["fact_id"]]
            for expression in ([node.test] if isinstance(node, (ast.If, ast.While)) else
                    [node.iter] if isinstance(node, ast.For) else node.values if isinstance(node, ast.BoolOp) else []):
                self.visit(expression, key, context, phase, controls)
            self.step("control_start", b, controls)
            if isinstance(node, ast.Try):
                self.exception_scopes.append((b["fact_id"], node.handlers))
            completed = self.block(getattr(node, "body", []), key, context, phase, nested)
            if isinstance(node, ast.Try):
                self.exception_scopes.pop()
            handler_completed = False
            for handler in getattr(node, "handlers", []):
                self.step("control_else", b, controls)
                handler_completed = self.block(handler.body, key, context, phase, [*nested, "catch " + (ast.unparse(handler.type) if handler.type else "all")]) or handler_completed
            other = getattr(node, "orelse", [])
            alternative_completed = True
            if other:
                self.step("control_else", b, controls)
                alternative_completed = self.block(other, key, context, phase, [*nested, "alternative"])
            final = getattr(node, "finalbody", [])
            if final:
                self.step("control_else", b, controls)
                self.block(final, key, context, phase, [*nested, "finally"])
                if any(isinstance(n, (ast.Return, ast.Raise)) for n in ast.walk(ast.Module(body=final, type_ignores=[]))):
                    self.gap("FINALLY_OVERRIDES_OUTCOME", source, context, "Finally result dominance unsupported", controls=nested)
            self.step("control_end", b, controls)
            if isinstance(node, (ast.With, ast.BoolOp)):
                self.gap("CONTROL_SEMANTICS_UNSUPPORTED", source, context, "Context manager/short-circuit needs a supported contract", controls=controls)
            if isinstance(node, ast.Try):
                if node.orelse or any(not self.exception_types(handler.type, key) for handler in node.handlers):
                    self.gap("ERROR_PROPAGATION_UNRESOLVED", source, context,
                             "Only builtin exception handlers without try-else are statically supported", controls=nested)
                return completed or handler_completed
            if isinstance(node, ast.If) and completed != alternative_completed:
                self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", source, context,
                         "Conditional exit requires continuation path evidence", controls=nested)
            return completed or alternative_completed or isinstance(node, (ast.For, ast.While, ast.Try))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                self.visit(node.func.value, key, context, phase, controls)
            for arg in node.args:
                self.visit(arg, key, context, phase, controls)
            for keyword in node.keywords:
                self.visit(keyword.value, key, context, phase, controls)
            if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
                self.gap("DYNAMIC_ARGUMENT_BINDING_UNSUPPORTED", source, context,
                         "Expanded arguments require a source-bound call signature", controls=controls)
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            receiver = self.environments[context].get(ast.unparse(node.func.value), "") if isinstance(node.func, ast.Attribute) else ""
            local_names = {n.name for n in ast.walk(self.definitions[key]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n != self.definitions[key]}
            local_names.update(a.arg for a in [*self.definitions[key].args.posonlyargs, *self.definitions[key].args.args, *self.definitions[key].args.kwonlyargs])
            candidates = [(k, n) for k, n in self.definitions.items() if k[0] == key[0] and k[2] == name
                          and k[1] == receiver and (not isinstance(node.func, ast.Attribute) or receiver)]
            if isinstance(node.func, ast.Name) and name in local_names:
                candidates = []
            ctx = stable_id("K", context, source, self.ordinals[(context, source)])
            self.ordinals[(context, source)] += 1
            c = self.add("calls", "invocation", source, ctx, phase, controls,
                         {"method": name, "receiver_type": receiver, "target": ":".join(candidates[0][0]) if len(candidates) == 1 else "",
                          "sender_type": self.owner(key), "target_owner": self.owner(candidates[0][0]) if len(candidates) == 1 else "",
                          "arguments": [ast.unparse(a) for a in node.args] + [ast.unparse(k) for k in node.keywords], "parent_context": context})
            self.step("call", c, controls)
            if len(candidates) == 1:
                self.expand(*candidates[0], ctx, phase, controls)
            elif receiver == "dict" and name in {"get", "keys", "values", "items", "copy"} and "dict" not in self.shadowed[key[0]]:
                c["type"] = "pure_or_memory"
            elif self.external(node, key, c):
                pass
            elif self.persistence(node, key, source, ctx, phase, controls):
                c["type"] = "storage_api"
            elif isinstance(node.func, ast.Name) and any(k[0] == key[0] and k[1] == name for k in self.definitions):
                initializers = [(k, n) for k, n in self.definitions.items() if k[0] == key[0] and k[1] == name and k[2] == "__init__"]
                if initializers:
                    self.expand(*initializers[0], ctx, phase, controls)
                c["type"] = "construction"
            elif (isinstance(node.func, ast.Name) and name not in self.shadowed[key[0]] | local_names
                  and name in {"len", "str", "int", "bool", "dict", "list", "set", "tuple", "range", "sum", "min", "max", "sorted", "enumerate", "zip", "abs"}):
                c["type"] = "pure_or_memory"
                if any(k.arg == "key" for k in node.keywords):
                    self.gap("CALLBACK_CONTRACT_UNSUPPORTED", source, ctx,
                             "Builtin callback needs executable target and iteration binding", controls=controls)
            elif isinstance(node.func, ast.Name) and isinstance(self.parents.get(node), ast.Raise):
                c["type"] = "exception_construction"
            else:
                self.gap("CALL_BINDING_AMBIGUOUS" if candidates else "CALL_CONTRACT_UNSUPPORTED", source, ctx,
                         "Python declaration or fixed library contract required: " + ast.unparse(node.func),
                         [":".join(k) for k, _ in candidates], controls)
            self.step("return", c, controls)
            return True
        if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            for child in ast.iter_child_nodes(node):
                self.visit(child, key, context, phase, controls)
            typ = ("entry_response" if len(self.stack) == 1 else "method_return") if isinstance(node, ast.Return) else type(node).__name__.lower()
            outcome = self.outcome(typ, source, context, phase, controls, ast.unparse(node))
            if isinstance(node, ast.Raise):
                raised = self.exception_types(node.exc.func, key) if isinstance(node.exc, ast.Call) else []
                caught = next((branch for branch, handlers in reversed(self.exception_scopes) if raised and any(
                    any(issubclass(raised[0], typ) for typ in self.exception_types(handler.type, key)) for handler in handlers)), None)
                outcome["details"].update(observed_by_entry=not caught and len(self.stack) == 1,
                    propagation="caught by source-proven builtin handler" if caught else "uncaught at this declaration")
                if caught:
                    outcome["details"]["caught_by"] = caught
                elif self.exception_scopes or len(self.stack) > 1:
                    self.gap("ERROR_PROPAGATION_UNRESOLVED", source, context,
                             "Bind the raised builtin exception type and its nearest compatible handler", controls=controls)
            if isinstance(node, (ast.Break, ast.Continue)):
                self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", source, context,
                         "Loop exit requires path-specific continuation evidence", controls=controls)
            return False
        for child in ast.iter_child_nodes(node):
            self.visit(child, key, context, phase, controls)
        return True

    def exception_types(self, expression, key):
        import builtins
        if expression is None:
            return [BaseException]
        names = expression.elts if isinstance(expression, ast.Tuple) else [expression]
        result = []
        for name in names:
            typ = getattr(builtins, name.id, None) if isinstance(name, ast.Name) and name.id not in self.shadowed[key[0]] else None
            if not isinstance(typ, type) or not issubclass(typ, BaseException):
                return []
            result.append(typ)
        return result

    def persistence(self, node, key, proof, context, phase, controls):
        from .storage import sql_resources
        source = self.sources[key[0]]
        root = ast.parse(source)
        imports = {a.asname or a.name: ((n.module or "") + "." + a.name if isinstance(n, ast.ImportFrom) else a.name)
                   for n in root.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        expression = ast.unparse(node.func)
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        receiver = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
        typ = self.environments.get(context, {}).get(receiver, "")
        # Call facts use a child context; the variables belong to their caller.
        call = next(c for c in self.value["calls"] if c["context_id"] == context)
        typ = self.environments.get(call["details"]["parent_context"], {}).get(receiver, typ)
        bound = imports.get(typ, typ)
        arg = node.args[0] if node.args else None
        literal = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
        resources = []
        parameter_names = {a.arg for a in ast.walk(self.definitions[key]) if isinstance(a, ast.arg)}
        if expression == "open" and "open" not in self.shadowed[key[0]] | parameter_names:
            mode_node = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), ast.Constant("r"))
            if not literal or not isinstance(mode_node, ast.Constant) or not isinstance(mode_node.value, str):
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Bind a literal file access mode", controls=controls)
                return True
            mode = mode_node.value
            resources = [(literal, "write" if any(flag in str(mode) for flag in "wax+") else "read", "file_resource", [])]
        elif bound in {"redis.Redis", "redis.StrictRedis"} and name in {"get", "set", "setex", "delete", "hget", "hset"}:
            if literal:
                resources = [(literal, "read" if name in {"get", "hget"} else "write", "kv_namespace", [])]
            else:
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Provide a literal KV key", controls=controls)
                return True
        elif bound == "mypy_boto3_s3.S3Client" and name in {"get_object", "put_object", "delete_object", "head_object"}:
            values = {k.arg: k.value.value for k in node.keywords if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)}
            if values.get("Bucket") and values.get("Key"):
                resources = [(values["Bucket"] + "/" + values["Key"], "read" if name in {"get_object", "head_object"} else "write", "object_storage", [])]
            else:
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Bind literal S3 Bucket and Key", controls=controls)
                return True
        elif bound in {"sqlite3.Connection", "sqlite3.Cursor", "sqlalchemy.orm.Session"} and name in {"execute", "executemany", "executescript"}:
            if isinstance(arg, ast.Call) and imports.get(ast.unparse(arg.func)) == "sqlalchemy.text" and arg.args:
                literal = arg.args[0].value if isinstance(arg.args[0], ast.Constant) else None
            resources = [(table, operation, "relational_table", []) for table, operation in sql_resources(literal)]
            if not resources:
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Provide a literal SQL statement with explicit objects", controls=controls)
                return True
        elif expression in imports and imports[expression] == "sqlalchemy.text" and literal:
            return True  # SQL expression construction; the execute call owns IO.
        elif bound == "sqlalchemy.orm.Session" and name == "query":
            return True  # Lazy query construction does not execute IO.
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call) and name in {"all", "first", "one", "count"}:
            inner = node.func.value
            if not isinstance(inner.func, ast.Attribute) or inner.func.attr != "query":
                return False
            inner_type = self.environments.get(call["details"]["parent_context"], {}).get(ast.unparse(inner.func.value), "")
            if imports.get(inner_type, inner_type) != "sqlalchemy.orm.Session":
                return False
            arg = inner.args[0] if len(inner.args) == 1 else None
            if not isinstance(arg, ast.Name):
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Bind one explicit SQLAlchemy model", controls=controls)
                return True
            models = [n for n in root.body if isinstance(n, ast.ClassDef) and n.name == arg.id]
            bases = {n.name for n in root.body if isinstance(n, ast.ClassDef) and any(
                imports.get(ast.unparse(base)) == "sqlalchemy.orm.DeclarativeBase" for base in n.bases)}
            if len(models) == 1 and any(ast.unparse(base) in bases for base in models[0].bases):
                tables = [n.value.value for n in models[0].body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in n.targets)
                          and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
                if len(tables) == 1:
                    model_proof = self.source(key[0], models[0], key[0] + ":" + arg.id)
                    resources = [(tables[0], "read", "relational_table", [model_proof])]
            if not resources:
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Bind a DeclarativeBase model and literal __tablename__", controls=controls)
                return True
        if not resources:
            return False
        for resource, operation, resource_type, refs in resources:
            action = self.add("persistence_actions", "literal_api", proof, context, phase, controls,
                {"resource_type": resource_type, "resource_name": resource, "operation": operation,
                 "commit": "not established by API return"}, refs)
            self.participant(resource, "storage")
            self.step("persistence", action, controls)
            if operation != "read":
                self.outcome("write_attempt", proof, context, phase, controls, refs=[action["fact_id"]])
        return True

    def external(self, node, key, call):
        from urllib.parse import urlsplit
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"get", "post", "put", "patch", "delete", "head", "request"}:
            return False
        root = ast.parse(self.sources[key[0]])
        modules = {a.asname or a.name: a.name for n in root.body if isinstance(n, ast.Import) for a in n.names}
        receiver = ast.unparse(node.func.value)
        if modules.get(receiver) not in {"requests", "httpx"}:
            return False
        if any(isinstance(n, ast.Name) and n.id == receiver and isinstance(n.ctx, ast.Store)
               or isinstance(n, ast.arg) and n.arg == receiver for n in ast.walk(root)):
            return False
        arguments = node.args[1:] if node.func.attr == "request" else node.args
        url = arguments[0] if arguments else next((k.value for k in node.keywords if k.arg == "url"), None)
        endpoint = url.value if isinstance(url, ast.Constant) and isinstance(url.value, str) else ""
        target = urlsplit(endpoint)
        if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
            self.gap("EXTERNAL_SYSTEM_UNRESOLVED", call["evidence_refs"][0], call["context_id"],
                     "Provide a literal HTTP URL with a resolvable host and no credentials", controls=call["conditions"])
        else:
            self.outbound(call, target.hostname, endpoint)
        return True
