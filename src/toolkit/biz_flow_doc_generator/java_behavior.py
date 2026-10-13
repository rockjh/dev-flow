"""Java declaration binding and ordered AST expansion, independent of rendering."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
import posixpath
from dataclasses import dataclass, field as dc_field
from ..core.syntax import parser_for, walk, text, field
from .evidence import Facts, stable_id


@dataclass
class JavaType:
    name: str
    file: str
    node: object
    raw: bytes
    package: str
    imports: dict
    parents: list
    fields: dict = dc_field(default_factory=dict)
    methods: list = dc_field(default_factory=list)


@dataclass
class JavaMethod:
    owner: JavaType
    name: str
    parameters: list
    returns: str
    node: object
    body: object

    @property
    def identity(self):
        return self.owner.name + "." + self.name + "(" + ",".join(self.parameter_types) + ")"

    @property
    def parameter_types(self):
        def qualify(typ):
            base = re.sub(r"<.*>", "", typ).removesuffix("[]")
            qualified = (base if "." in base or base in {"byte", "short", "int", "long", "float", "double", "char", "boolean"}
                else self.owner.imports.get(base) or ("java.lang." + base if base in {
                    "String", "Object", "Runnable", "Integer", "Long", "Boolean", "Double", "Float", "Character"}
                    else ".".join(p for p in (self.owner.package, base) if p)))
            return qualified + ("[]" if typ.endswith("[]") else "")
        return [qualify(t) for _, t in self.parameters]


class JavaIndex:
    def __init__(self, sources):
        self.sources, self.types, self.trees, self.conflicts = sources, {}, {}, set()
        for file, source in sorted(sources.items()):
            if not file.endswith(".java"):
                continue
            raw = source.encode()
            root = parser_for("java").parse(raw).root_node
            self.trees[file] = root
            package = next((text(n, raw).removeprefix("package").strip().rstrip(";") for n in root.named_children if n.type == "package_declaration"), "")
            imports = {}
            for n in root.named_children:
                if n.type == "import_declaration":
                    name = text(n, raw).removeprefix("import").replace("static ", "").strip().rstrip(";")
                    imports[name.rsplit(".", 1)[-1]] = name

            def declarations(node, enclosing=""):
                for n in node.named_children:
                    if n.type not in {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}:
                        continue
                    short = text(field(n, "name"), raw)
                    qualified = ".".join(p for p in (enclosing or package, short) if p)
                    parents = []
                    for p in n.named_children:
                        if p.type in {"superclass", "super_interfaces", "extends_interfaces"}:
                            parents.extend(text(v, raw) for v in walk(p) if v.type in {"type_identifier", "generic_type"} and v.parent.type in {"superclass", "type_list", "extends_interfaces"})
                    owner = JavaType(qualified, file, n, raw, package, imports, parents)
                    if qualified in self.types:
                        self.conflicts.add(qualified)
                    self.types[qualified] = owner
                    body = field(n, "body")
                    for member in body.named_children if body else ():
                        if member.type == "field_declaration":
                            typ = text(field(member, "type"), raw)
                            for v in member.named_children:
                                if v.type == "variable_declarator":
                                    owner.fields[text(field(v, "name"), raw)] = (typ, member)
                        elif member.type in {"method_declaration", "constructor_declaration"}:
                            params = field(member, "parameters")
                            parameters = [(text(field(p, "name"), raw), text(field(p, "type"), raw)) for p in params.named_children if p.type in {"formal_parameter", "spread_parameter"}] if params else []
                            owner.methods.append(JavaMethod(owner, text(field(member, "name"), raw), parameters,
                                text(field(member, "type"), raw), member, field(member, "body")))
                    if body:
                        declarations(body, qualified)
            declarations(root)

    def resolve_type(self, name, owner):
        name = re.sub(r"<.*>", "", name).replace("[]", "").strip()
        qualified = owner.imports.get(name, ".".join(p for p in (owner.package, name) if p))
        return self.types.get(qualified) or self.types.get(name)

    def methods(self, owner, name, seen=None):
        seen = set() if seen is None else seen
        if owner.name in seen:
            return []
        seen.add(owner.name)
        own = [m for m in owner.methods if m.name == name]
        inherited = [m for p in owner.parents if (base := self.resolve_type(p, owner)) for m in self.methods(base, name, seen)]
        signatures = {tuple(m.parameter_types) for m in own}
        return own + [m for m in inherited if tuple(m.parameter_types) not in signatures]

    def fields(self, owner, seen=None):
        seen = set() if seen is None else seen
        if owner.name in seen:
            return {}
        seen.add(owner.name)
        inherited = {}
        for parent in owner.parents:
            base = self.resolve_type(parent, owner)
            if base:
                inherited.update(self.fields(base, seen))
        inherited.update({name: (typ, node, owner) for name, (typ, node) in owner.fields.items()})
        return inherited

    def implementations(self, owner):
        def inherits(candidate, target, seen):
            if candidate.name in seen:
                return False
            seen.add(candidate.name)
            return any((base := self.resolve_type(p, candidate)) and
                       (base.name == target or inherits(base, target, seen)) for p in candidate.parents)
        return [t for t in self.types.values() if t.node.type != "interface_declaration" and inherits(t, owner.name, set())]

    def entry(self, entry):
        methods = [m for t in self.types.values() if t.file == entry.file for m in t.methods
                   if m.name == entry.handler.rsplit("#", 1)[-1].split("(", 1)[0].rsplit(".", 1)[-1]]
        following = [m for m in methods if m.node.start_point.row + 1 >= entry.line]
        if following:
            first = min(m.node.start_point.row for m in following)
            methods = [m for m in following if m.node.start_point.row == first]
        return methods[0] if len(methods) == 1 else None

    def repository_entities(self, candidate, substitutions=None, seen=None):
        substitutions, seen = substitutions or {}, seen or set()
        if candidate is None or candidate.name in seen:
            return []
        results = []
        for parent in candidate.parents:
            base = re.sub(r"<.*>", "", parent)
            generic = re.search(r"<([^<>]+)>", parent)
            arguments = []
            for argument in generic[1].split(",") if generic else []:
                argument = argument.strip()
                resolved = self.resolve_type(argument, candidate)
                arguments.append(substitutions.get(argument, resolved.name if resolved else candidate.imports.get(argument, argument)))
            if candidate.imports.get(base, base) in JPA_REPOSITORIES and arguments:
                results.append((candidate, arguments[0]))
            elif parent_type := self.resolve_type(base, candidate):
                params = field(parent_type.node, "type_parameters")
                names = [text(p, parent_type.raw).split()[0] for p in params.named_children] if params else []
                results.extend(self.repository_entities(parent_type, dict(zip(names, arguments)), {*seen, candidate.name}))
        return results


# Fixed API summaries are versioned with the adapter and identify qualified types.
JAVA_PURE = {
    "java.lang.String": {"length", "isEmpty", "equals", "equalsIgnoreCase", "trim", "substring", "split", "valueOf", "format"},
    "java.util.Map": {"get", "put", "remove", "containsKey", "isEmpty", "size", "values", "keySet", "entrySet", "getOrDefault"},
    "java.util.List": {"get", "add", "remove", "isEmpty", "size", "contains", "iterator"},
    "java.util.Set": {"add", "remove", "isEmpty", "size", "contains", "iterator"},
    "java.util.Objects": {"requireNonNull", "isNull", "nonNull", "equals"},
    "java.lang.Math": {"min", "max", "abs", "round"},
}
JPA_REPOSITORIES = {"org.springframework.data.jpa.repository.JpaRepository", "org.springframework.data.repository.CrudRepository",
                    "org.springframework.data.repository.PagingAndSortingRepository"}


class JavaFacts(Facts):
    def __init__(self, *args, index):
        super().__init__(*args)
        self.index = index
        self.exception_scopes = []
        self.row_results = {}
        self.library_proofs = {}
        self.normal_conditions = {}

    def analyze(self):
        method = self.index.entry(self.entry)
        if not method:
            self.gap("ENTRY_DECLARATION_UNRESOLVED", self.entry.entry_id, self.entry.entry_id, "Bind registration to a unique method signature")
            return self.finish()
        self.participant(self.entry.caller, "caller")
        self.expand(method, stable_id("K", self.entry.entry_id, method.identity), "entry", [], {}, {})
        while self.background and self.count < self.budget:
            callback, context, controls = self.background.pop(0)
            self.callback(callback, context, "background", controls, 0)
        if self.background:
            self.gap("ANALYSIS_BUDGET_EXCEEDED", self.entry.entry_id, self.entry.entry_id, "Background expansion budget reached")
        return self.finish()

    def type_name(self, name, owner):
        found = self.index.resolve_type(name, owner)
        if found:
            return found.name
        base = re.sub(r"<.*>", "", name).strip()
        return owner.imports.get(base, "java.lang." + base if base in {"String", "Math", "Object", "Runnable", "Integer", "Long", "Boolean", "RuntimeException", "IllegalArgumentException", "IllegalStateException", "Exception", "Throwable"} else base)

    def infer(self, node, method, env):
        if node is None:
            return ""
        raw, kind = method.owner.raw, node.type
        val = text(node, raw)
        if kind in {"string_literal", "text_block"}:
            return "java.lang.String"
        if kind in {"decimal_integer_literal", "hex_integer_literal"}:
            return "long" if val.lower().endswith("l") else "int"
        if kind in {"true", "false"}:
            return "boolean"
        if kind == "null_literal":
            return ""
        if kind == "identifier":
            return env.get(val, self.type_name(val, method.owner))
        if kind == "this":
            return env.get("this", method.owner.name)
        if kind in {"object_creation_expression", "cast_expression"}:
            return self.type_name(text(field(node, "type"), raw), method.owner)
        if kind == "field_access":
            owner = self.index.types.get(self.infer(field(node, "object"), method, env))
            name = text(field(node, "field"), raw)
            if owner and name in self.index.fields(owner):
                typ, _, declaring = self.index.fields(owner)[name]
                return self.type_name(typ, declaring)
        if kind == "method_invocation":
            receiver = field(node, "object")
            typ = self.infer(receiver, method, env) if receiver else method.owner.name
            target = self.index.types.get(typ)
            name = text(field(node, "name"), raw)
            methods = self.candidates(target, name, field(node, "arguments").named_children, method, env) if target else []
            if len(methods) == 1:
                return self.type_name(methods[0].returns, methods[0].owner)
            summaries = {
                "com.querydsl.jpa.impl.JPAQueryFactory": {"update": "com.querydsl.jpa.impl.JPAUpdateClause", "delete": "com.querydsl.jpa.impl.JPADeleteClause"},
                "com.querydsl.jpa.impl.JPAUpdateClause": {"set": typ, "where": typ},
                "com.querydsl.jpa.impl.JPADeleteClause": {"where": typ},
            }
            if name in summaries.get(typ, {}):
                return summaries[typ][name]
        return ""

    def candidates(self, target, name, args, method, env):
        values = [m for m in self.index.methods(target, name) if len(m.parameters) == len(args)]
        actual = [self.infer(a, method, env) for a in args]
        widening = {"byte": ["short", "int", "long", "float", "double"], "short": ["int", "long", "float", "double"],
                    "char": ["int", "long", "float", "double"], "int": ["long", "float", "double"],
                    "long": ["float", "double"], "float": ["double"]}
        def distance(a, arg, typ, owner):
            expected = self.type_name(typ, owner)
            if a == expected:
                return 0
            if not a or arg.type in {"lambda_expression", "method_reference"}:
                return 0
            if expected in widening.get(a, []):
                return 1 + widening[a].index(expected)
            base = self.index.types.get(expected)
            if base and self.index.types.get(a) in self.index.implementations(base):
                return 10
            if expected == "java.lang.Object" and a not in widening and a not in {"double", "boolean"}:
                return 100
            return None
        ranked = []
        for candidate in values:
            ranks = [distance(a, arg, typ, candidate.owner) for a, arg, (_, typ) in zip(actual, args, candidate.parameters)]
            if all(rank is not None for rank in ranks):
                ranked.append((candidate, ranks))
        # Keep incomparable overloads ambiguous. Never select by short type name
        # or by whichever declaration happened to be indexed first.
        return [m for m, ranks in ranked if not any(
            all(b <= a for a, b in zip(ranks, other)) and any(b < a for a, b in zip(ranks, other))
            for _, other in ranked)]

    def expand(self, method, context, phase, controls, bindings, argument_types):
        source = self.source(method.owner.file, method.node, method.identity, method.owner.raw)
        if method.owner.name in self.index.conflicts:
            self.gap("DECLARATION_ID_CONFLICT", source, context, "Qualified type has multiple source declarations", controls=controls)
            return
        if method.identity in self.stack:
            self.gap("RECURSION_BOUNDARY", source, context, "Recursive invocation requires a bounded contract", controls=controls)
            return
        if method.body is None:
            self.gap("DECLARATION_WITHOUT_IMPLEMENTATION", source, context, "No executable implementation", controls=controls)
            return
        self.stack.append(method.identity)
        self.normal_conditions[context] = []
        self.participant(method.owner.name, "service")
        env = {name: self.type_name(t, owner) for name, (t, _, owner) in self.index.fields(method.owner).items()}
        env.update({name: self.type_name(t, method.owner) for name, t in method.parameters})
        env.update({k: v for k, v in argument_types.items() if v})
        transactional = bool(re.search(r"@Transactional\b", text(method.node, method.owner.raw).split("{", 1)[0])
                             or re.search(r"@Transactional\b", text(method.owner.node, method.owner.raw).split("{", 1)[0]))
        transaction = None
        if transactional:
            transaction = self.add("effects", "transaction_declaration", source, context, phase, controls,
                                   {"operation": "declared transaction", "commit_observed": False,
                                    "activation": "proxy/container boundary not established by annotation"})
            self.gap("TRANSACTION_ACTIVATION_UNRESOLVED", source, context,
                     "Prove proxy/container activation, propagation and rollback rules before claiming a transaction boundary", controls=controls)
            self.step("transaction_start", transaction, controls)
        falls_through = self.visit(method.body, method, env, bindings, context, phase, controls)
        completion_controls = list(dict.fromkeys([*controls, *self.normal_conditions[context]]))
        if falls_through and (method.returns == "void" or phase == "background"):
            self.outcome("background_result" if phase == "background" and len(self.stack) == 1 else
                         "normal_completion" if len(self.stack) == 1 else "method_return", source, context, phase, completion_controls)
        if transaction:
            self.step("transaction_end", transaction, controls)
        self.stack.pop()

    def visit(self, node, method, env, bindings, context, phase, controls):
        if node is None:
            return True
        self.count += 1
        controls = list(dict.fromkeys([*controls, *self.normal_conditions.get(context, [])]))
        raw, kind = method.owner.raw, node.type
        source = self.source(method.owner.file, node, method.identity, raw)
        if self.count > self.budget:
            self.gap("ANALYSIS_BUDGET_EXCEEDED", source, context, "AST expansion budget reached", controls=controls)
            return False
        if kind in {"line_comment", "block_comment", "lambda_expression", "method_reference", "class_declaration"}:
            return True
        if kind == "ERROR" or node.is_missing:
            self.gap("SOURCE_PARSE_ERROR", source, context, "Tree-sitter error in reachable declaration", controls=controls)
        if kind in {"assert_statement", "explicit_constructor_invocation", "yield_statement"}:
            self.gap("CONTROL_SEMANTICS_UNSUPPORTED", source, context,
                     "Control/constructor contract not supported: " + kind, controls=controls)
        if kind == "block":
            env, bindings = env.copy(), bindings.copy()
            for child in node.named_children:
                if not self.visit(child, method, env, bindings, context, phase, controls):
                    return False
            return True
        if kind == "local_variable_declaration":
            typ = self.type_name(text(field(node, "type"), raw), method.owner)
            for declaration in node.named_children:
                if declaration.type == "variable_declarator":
                    name, value = text(field(declaration, "name"), raw), field(declaration, "value")
                    if value:
                        self.visit(value, method, env, bindings, context, phase, controls)
                    env[name] = self.infer(value, method, env) if typ == "var" else typ
                    if value and value.type == "object_creation_expression":
                        env[name] = self.infer(value, method, env)
                    if value and value.type in {"lambda_expression", "method_reference"}:
                        bindings[name] = (value, method, env.copy(), bindings.copy())
            return True
        if kind == "switch_expression" and node.parent.type == "block":
            condition, body = field(node, "condition"), field(node, "body")
            self.visit(condition, method, env, bindings, context, phase, controls)
            groups = body.named_children if body else []
            if any(group.type != "switch_block_statement_group" for group in groups):
                self.gap("SWITCH_RULE_UNRESOLVED", source, context,
                         "Only explicit statement groups have proven switch semantics", controls=controls)
            labels = [text(group.named_children[0], raw) if group.named_children else "" for group in groups]
            branch = self.add("branches", "switch_statement", source, context, phase, controls,
                              {"condition": text(condition, raw), "arms": labels})
            self.step("control_start", branch, controls)
            completed = False
            for i, group in enumerate(groups):
                arm = labels[i]
                if i:
                    self.step("control_else", branch, controls, arm)
                active = [*controls, branch["fact_id"], arm]
                can_continue, stopped = True, False
                for statement in group.named_children[1:]:
                    if statement.type == "break_statement":
                        proof = self.source(method.owner.file, statement, method.identity)
                        self.outcome("break", proof, context, phase, active, text(statement, raw))
                        stopped = True
                        break
                    can_continue = self.visit(statement, method, env.copy(), bindings.copy(), context, phase, active)
                    if not can_continue:
                        stopped = True
                        break
                if not stopped and i + 1 < len(groups):
                    self.gap("SWITCH_FALLTHROUGH_UNRESOLVED", source, context,
                             "Prove a switch arm's fallthrough continuation", controls=active)
                completed |= can_continue
            self.step("control_end", branch, controls)
            if not groups:
                self.gap("SWITCH_CASE_UNRESOLVED", source, context, "Bind explicit switch cases", controls=controls)
            return completed or not any(label == "default" for label in labels)
        if kind in {"if_statement", "while_statement", "for_statement", "enhanced_for_statement", "do_statement", "try_statement", "try_with_resources_statement", "switch_expression", "synchronized_statement", "ternary_expression"}:
            condition = field(node, "condition") or field(node, "value")
            branch = self.add("branches", kind, source, context, phase, controls,
                              {"condition": text(condition, raw) or kind, "arms": [], "reachability": "conditional"})
            if condition:
                branch["evidence_refs"].extend(p for (ctx, variable), p in self.row_results.items()
                    if ctx == context and re.search(r"\b" + re.escape(variable) + r"\b", text(condition, raw)))
            nested = [*controls, branch["fact_id"]]
            loops = {"for_statement", "enhanced_for_statement", "while_statement", "do_statement"}
            if kind == "for_statement":
                self.visit(field(node, "init"), method, env, bindings, context, phase, controls)
            if kind == "enhanced_for_statement":
                self.visit(field(node, "value"), method, env, bindings, context, phase, controls)
            elif condition and kind not in loops:
                self.visit(condition, method, env, bindings, context, phase, controls)
            self.step("control_start", branch, controls)
            if kind == "if_statement":
                before_conditions = list(self.normal_conditions.get(context, []))
                hint = self.hints.get(branch["fact_id"])
                classification = hint["binding"]["classification"] if hint else ""
                yes = self.visit(field(node, "consequence"), method, env, bindings, context, phase, [*nested, "true"]) if classification != "constant_false" else False
                yes_conditions = list(self.normal_conditions.get(context, []))
                self.normal_conditions[context] = list(before_conditions)
                self.step("control_else", branch, controls, "false")
                no = self.visit(field(node, "alternative"), method, env, bindings, context, phase, [*nested, "false"]) if classification != "constant_true" else False
                no_conditions = list(self.normal_conditions.get(context, []))
                self.normal_conditions[context] = (yes_conditions if classification == "constant_true" else no_conditions
                    if classification == "constant_false" else yes_conditions if yes_conditions == no_conditions else before_conditions)
                if not classification and yes_conditions != no_conditions:
                    self.gap("CONTROL_CONTINUATION_MERGE_UNSUPPORTED", source, context,
                             "Conditional submission requires a disjunctive continuation contract", controls=nested)
                branch["details"]["arms"] = ["true", "false"]
                if classification:
                    branch["details"]["proven_constant"] = classification
                completed = yes or no
                if yes != no and not classification:
                    self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", source, context,
                             "Continuation after conditional return/throw needs path-specific exit evidence", controls=nested)
            elif kind in {"try_statement", "try_with_resources_statement"}:
                if kind == "try_with_resources_statement":
                    self.visit(field(node, "resources"), method, env, bindings, context, phase, controls)
                    self.gap("TRY_RESOURCE_CONTRACT_UNSUPPORTED", source, context,
                             "Automatic close and suppressed exceptions need an explicit resource contract", controls=nested)
                catches = [text(c, raw).split("{", 1)[0].strip() for c in node.named_children if c.type == "catch_clause"]
                types = []
                for handler in catches:
                    declaration = re.search(r"\(\s*([\w.| ]+)\s+\w+\s*\)", handler)
                    types.append([self.type_name(t.strip(), method.owner) for t in declaration[1].split("|")] if declaration else [])
                self.exception_scopes.append({"branch_id": branch["fact_id"], "handlers": catches, "types": types})
                completed = self.visit(field(node, "body"), method, env, bindings, context, phase, [*nested, "try"])
                self.exception_scopes.pop()
                arms = ["try"]
                for child in node.named_children:
                    if child.type == "catch_clause":
                        arm = text(child, raw).split("{", 1)[0].strip()
                        arms.append(arm)
                        self.step("control_else", branch, controls, arm)
                        result = self.visit(child, method, env, bindings, context, phase, [*nested, arm])
                        completed = completed or result
                branch["details"]["arms"] = arms
                self.step("control_end", branch, controls)
                for child in node.named_children:
                    if child.type == "finally_clause":
                        cleanup_source = self.source(method.owner.file, child, method.identity)
                        cleanup = self.add("branches", "finally", cleanup_source, context, phase, controls,
                            {"condition": "regardless of try/catch result", "arms": ["always"], "reachability": "unconditional after try/catch"})
                        self.step("control_start", cleanup, controls)
                        result = self.visit(child, method, env, bindings, context, phase, [*controls, cleanup["fact_id"]])
                        self.step("control_end", cleanup, controls)
                        completed = completed and result
                if any(c.type == "finally_clause" and any(n.type in {"return_statement", "throw_statement"} for n in walk(c)) for c in node.named_children):
                    self.gap("FINALLY_OVERRIDES_OUTCOME", source, context, "Finally return/throw dominance unsupported", controls=nested)
                return completed
            elif kind in loops:
                before_conditions = list(self.normal_conditions.get(context, []))
                if kind != "do_statement" and condition:
                    self.visit(condition, method, env, bindings, context, phase, nested)
                self.visit(field(node, "body"), method, env, bindings, context, phase, nested)
                if kind == "for_statement":
                    self.visit(field(node, "update"), method, env, bindings, context, phase, nested)
                if kind == "do_statement" and condition:
                    self.visit(condition, method, env, bindings, context, phase, nested)
                branch["details"]["arms"] = ["iteration", "empty"] if kind != "do_statement" else ["iteration"]
                completed = True
                if self.normal_conditions.get(context, []) != before_conditions:
                    self.gap("CONTROL_CONTINUATION_MERGE_UNSUPPORTED", source, context,
                             "Loop submission requires iteration-specific continuation evidence", controls=nested)
                    self.normal_conditions[context] = before_conditions
            else:
                for child in node.named_children:
                    if child != condition:
                        self.visit(child, method, env, bindings, context, phase, nested)
                branch["details"]["arms"] = ["iteration", "empty"] if "for" in kind or "while" in kind else ["body"]
                completed = True
                if kind in {"switch_expression", "ternary_expression"}:
                    self.gap("CONTROL_SEMANTICS_UNSUPPORTED", source, context, "Switch/ternary requires explicit arm semantics", controls=nested)
            self.step("control_end", branch, controls)
            return completed
        if kind == "binary_expression" and text(field(node, "operator"), raw) in {"&&", "||"}:
            operator = text(field(node, "operator"), raw)
            branch = self.add("branches", "short_circuit", source, context, phase, controls,
                              {"condition": text(field(node, "left"), raw), "expression": text(node, raw), "operator": operator,
                               "arms": ["left_true", "left_false"] if operator == "&&" else ["left_false", "left_true"],
                               "reachability": "conditional"})
            self.visit(field(node, "left"), method, env, bindings, context, phase, controls)
            self.step("control_start", branch, controls)
            before_conditions = list(self.normal_conditions.get(context, []))
            self.visit(field(node, "right"), method, env, bindings, context, phase, [*controls, branch["fact_id"], branch["details"]["arms"][0]])
            if self.normal_conditions.get(context, []) != before_conditions:
                self.gap("CONTROL_CONTINUATION_MERGE_UNSUPPORTED", source, context,
                         "Short-circuit submission needs disjunctive continuation evidence", controls=controls)
                self.normal_conditions[context] = before_conditions
            self.step("control_else", branch, controls, branch["details"]["arms"][1])
            self.step("control_end", branch, controls)
            return True
        if kind == "method_invocation":
            self.invocation(node, method, env, bindings, context, phase, controls)
            return True
        if kind in {"assignment_expression", "update_expression"}:
            left = field(node, "left") or (node.named_children[0] if node.named_children else None)
            name = text(left, raw).removeprefix("this.")
            declarations = self.index.fields(method.owner)
            shadowed = any(param == name for param, _ in method.parameters) or any(
                n.type == "variable_declarator" and text(field(n, "name"), raw) == name
                for n in walk(method.body))
            if name in declarations and (left.type != "identifier" or not shadowed):
                _, declaration, declaring = declarations[name]
                mutation = self.add("effects", "memory_state_change", source, context, phase, controls,
                    {"receiver_type": method.owner.name, "field": name, "expression": text(node, raw),
                     "storage": "in-process field; no durability guarantee"},
                    [self.source(declaring.file, declaration, declaring.name + "." + name)])
                for child in node.named_children:
                    self.visit(child, method, env, bindings, context, phase, controls)
                self.step("state_change", mutation, controls)
                self.outcome("state_change", source, context, phase, controls, text(node, raw), refs=[mutation["fact_id"]])
                return True
        if kind in {"return_statement", "throw_statement", "break_statement", "continue_statement"}:
            for child in node.named_children:
                self.visit(child, method, env, bindings, context, phase, controls)
            controls = list(dict.fromkeys([*controls, *self.normal_conditions.get(context, [])]))
            typ = ("entry_response" if phase == "entry" and len(self.stack) == 1 else "background_result" if phase == "background" and len(self.stack) == 1 else "method_return") if kind == "return_statement" else kind.removesuffix("_statement")
            linked = [p for (ctx, variable), p in self.row_results.items()
                      if ctx == context and re.search(r"\b" + re.escape(variable) + r"\b", text(node, raw))]
            outcome = self.outcome(typ, source, context, phase, controls, text(node, raw), refs=linked)
            if kind == "throw_statement":
                outcome["details"].update(boundary="internal" if len(self.stack) > 1 else "entry",
                    possible_handlers=[{"branch_id": scope["branch_id"], "handlers": scope["handlers"]} for scope in self.exception_scopes], observed_by_entry=False,
                    propagation="handler type matching not established" if self.exception_scopes else "uncaught at this declaration")
                hint = self.hints.get(outcome["fact_id"])
                expression = node.named_children[0] if node.named_children else None
                thrown = self.type_name(text(field(expression, "type"), raw), method.owner) if expression and expression.type == "object_creation_expression" else ""
                parents = {"java.lang.IllegalArgumentException": {"java.lang.RuntimeException", "java.lang.Exception", "java.lang.Throwable"},
                           "java.lang.IllegalStateException": {"java.lang.RuntimeException", "java.lang.Exception", "java.lang.Throwable"},
                           "java.lang.RuntimeException": {"java.lang.Exception", "java.lang.Throwable"},
                           "java.lang.Exception": {"java.lang.Throwable"}}
                caught = None
                if thrown in parents:
                    for scope in reversed(self.exception_scopes):
                        handlers = [typ for group in scope.get("types", []) for typ in group]
                        if any(typ not in {*parents, "java.lang.Throwable"} for typ in handlers):
                            break
                        if any(typ in {thrown, *parents[thrown]} for typ in handlers):
                            caught = scope["branch_id"]
                            break
                if caught or hint and hint["type"] == "outcome_fact" and hint["binding"]["classification"] == "caught_error":
                    caught = caught or self.exception_scopes[-1]["branch_id"]
                    outcome["details"].update(propagation="caught by source-proven handler", caught_by=caught)
                    branch = next(b for b in self.value["branches"] if b["fact_id"] == caught)
                    outcome["evidence_refs"].extend(ref for ref in branch["evidence_refs"] if ref not in outcome["evidence_refs"])
                elif self.exception_scopes or len(self.stack) > 1:
                    self.gap("ERROR_PROPAGATION_UNRESOLVED", source, context,
                             "Prove exception matching/propagation before declaring the entry result", controls=controls)
                else:
                    outcome["details"]["observed_by_entry"] = phase == "entry"
            if kind in {"break_statement", "continue_statement"}:
                self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", source, context,
                         "Loop exit requires path-specific continuation and update evidence", controls=controls)
            return False
        if kind == "object_creation_expression":
            typ = self.type_name(text(field(node, "type"), raw), method.owner)
            args_node = field(node, "arguments")
            args = list(args_node.named_children) if args_node else []
            for argument in args:
                if argument.type not in {"lambda_expression", "method_reference"}:
                    self.visit(argument, method, env, bindings, context, phase, controls)
            if typ in self.index.types:
                owner = self.index.types[typ]
                constructors = self.candidates(owner, typ.rsplit(".", 1)[-1], args, method, env)
                implicit = not args and not any(m.node.type == "constructor_declaration" for m in owner.methods)
                if len(constructors) != 1 and not implicit:
                    self.gap("CONSTRUCTOR_BINDING_UNRESOLVED", source, context,
                             "Constructor overload/arguments are not uniquely bound", [m.identity for m in constructors], controls)
                    return True
                initializer = field(owner.node, "body")
                if any(n.type in {"block", "static_initializer"} or n.type == "field_declaration" and any(
                        e.type in {"method_invocation", "object_creation_expression", "assignment_expression"}
                        for e in walk(n)) for n in initializer.named_children):
                    self.gap("OBJECT_INITIALIZATION_UNSUPPORTED", source, context,
                             "Instance/static initializer effects need constructor lifecycle binding", controls=controls)
                child_context = stable_id("K", context, source, self.ordinals[(context, source)])
                self.ordinals[(context, source)] += 1
                proof = self.source(owner.file, owner.node, owner.name)
                self.participant(owner.name, "service")
                call = self.add("calls", "construction", source, child_context, phase, controls,
                    {"method": owner.name.rsplit(".", 1)[-1], "receiver_type": owner.name,
                     "target": constructors[0].identity if constructors else owner.name + ".<init>()",
                     "sender_type": method.owner.name, "target_owner": owner.name, "parent_context": context,
                     "arguments": [text(a, raw) for a in args]}, [proof])
                self.step("call", call, controls)
                if constructors:
                    bound, types = {}, {"this": typ}
                    for (param, _), argument in zip(constructors[0].parameters, args):
                        types[param] = self.infer(argument, method, env)
                        if argument.type in {"lambda_expression", "method_reference"}:
                            bound[param] = (argument, method, env.copy(), bindings.copy())
                    self.expand(constructors[0], child_context, phase, controls, bound, types)
                self.step("return", call, controls)
            elif typ not in {"java.lang.String", "java.lang.RuntimeException", "java.lang.IllegalArgumentException", "java.lang.IllegalStateException", "java.lang.Exception",
                             "java.util.ArrayList", "java.util.HashMap", "java.util.HashSet", "java.util.LinkedHashMap", "java.util.LinkedHashSet"}:
                self.gap("CONSTRUCTOR_CONTRACT_UNSUPPORTED", source, context, "Unknown external constructor: " + typ, controls=controls)
            if any(c.type == "class_body" for c in node.named_children):
                self.gap("ANONYMOUS_CLASS_EXECUTION_UNSUPPORTED", source, context,
                         "Anonymous class initializers and callback dispatch need a binding contract", controls=controls)
            return True
        for child in node.named_children:
            self.visit(child, method, env, bindings, context, phase, controls)
        return True

    def callback(self, callback, context, phase, controls, arity=None):
        node, original, env, bindings = callback
        if node.type == "lambda_expression":
            self.stack.append("lambda:" + context)
            completed = self.visit(field(node, "body"), original, env, bindings, context, phase, controls)
            self.stack.pop()
            if phase == "background" and completed:
                self.outcome("background_result", self.source(original.owner.file, node, original.identity),
                             context, phase, controls)
        elif node.type == "method_reference":
            raw, parts = original.owner.raw, node.named_children
            owner = self.index.types.get(self.infer(parts[0], original, env))
            name = text(parts[-1], raw)
            candidates = [m for m in self.index.methods(owner, name) if arity is None or len(m.parameters) == arity] if owner else []
            if candidates and all(m.body is None for m in candidates):
                candidates = [m for implementation in self.index.implementations(owner)
                              for m in self.index.methods(implementation, name) if arity is None or len(m.parameters) == arity]
            source = self.source(original.owner.file, node, original.identity)
            callback_context = stable_id("K", context, source, "callback")
            call = self.add("calls", "method_reference", source, callback_context, phase, controls,
                {"method": name, "receiver_type": owner.name if owner else "", "target": candidates[0].identity if len(candidates) == 1 else "",
                 "arguments": ["callback argument"] * (arity or 0), "parent_context": context,
                 "sender_type": original.owner.name, "target_owner": candidates[0].owner.name if len(candidates) == 1 else ""})
            hint = self.hints.get(call["fact_id"])
            if hint and hint["type"] == "callback_binding":
                candidates = [m for m in candidates if m.identity == hint["binding"]["declaration_id"]]
                call["details"].update(target=candidates[0].identity if len(candidates) == 1 else "",
                                      target_owner=candidates[0].owner.name if len(candidates) == 1 else "")
            self.step("call", call, controls)
            if len(candidates) == 1:
                self.expand(candidates[0], callback_context, phase, controls, {}, {})
            else:
                for candidate in candidates:
                    self.source(candidate.owner.file, candidate.node, candidate.identity)
                    self.source(candidate.owner.file, candidate.owner.node, candidate.owner.name)
                self.gap("CALLBACK_BINDING_UNRESOLVED", source, callback_context,
                         "Method reference needs unique receiver/signature", [m.identity for m in candidates], controls)
            self.step("return", call, controls)
        else:
            name = text(node, original.owner.raw)
            if name in bindings:
                self.callback(bindings[name], context, phase, controls, arity)
            else:
                self.gap("CALLBACK_TARGET_UNSUPPORTED", self.source(original.owner.file, node, original.identity), context,
                         "Task target cannot be bound to an executable callback", controls=controls)

    def invocation(self, node, method, env, bindings, parent, phase, controls):
        raw = method.owner.raw
        source = self.source(method.owner.file, node, method.identity, raw)
        name = text(field(node, "name"), raw)
        receiver = field(node, "object")
        receiver_text = text(receiver, raw)
        args_node = field(node, "arguments")
        args = list(args_node.named_children) if args_node else []
        typ = self.infer(receiver, method, env) if receiver else env.get("this", method.owner.name)
        if typ in {"com.querydsl.jpa.impl.JPAUpdateClause", "com.querydsl.jpa.impl.JPADeleteClause"} and name == "execute":
            self.querydsl(node, method, env, parent, phase, controls, typ)
            return
        if receiver and receiver.type == "method_invocation":
            self.visit(receiver, method, env, bindings, parent, phase, controls)
        for arg in args:
            if arg.type not in {"lambda_expression", "method_reference"}:
                self.visit(arg, method, env, bindings, parent, phase, controls)
        context = stable_id("K", parent, source, self.ordinals[(parent, source)])
        self.ordinals[(parent, source)] += 1
        target = self.index.types.get(typ)
        candidates = self.candidates(target, name, args, method, env) if target else []
        if candidates and all(m.body is None for m in candidates):
            implementations = self.index.implementations(target)
            if len(implementations) > 1:
                field_name = receiver_text.removeprefix("this.")
                declaration_info = self.index.fields(method.owner).get(field_name)
                declaration, declaring = (declaration_info[1], declaration_info[2]) if declaration_info else (None, method.owner)
                qualifier = re.search(r'@Qualifier\s*\(\s*"([^"]+)"\s*\)', text(declaration, declaring.raw)) if declaration and declaring.imports.get("Qualifier") == "org.springframework.beans.factory.annotation.Qualifier" else None
                if qualifier is None:
                    qualifiers = []
                    for constructor in declaring.methods:
                        if (declaring.name != env.get("this", method.owner.name)
                                or constructor.name != declaring.name.rsplit(".", 1)[-1] or constructor.body is None):
                            continue
                        for assignment in walk(constructor.body):
                            if assignment.type != "assignment_expression" or text(field(assignment, "left"), declaring.raw) != "this." + field_name:
                                continue
                            parameter = text(field(assignment, "right"), declaring.raw)
                            params = field(constructor.node, "parameters")
                            for param in params.named_children if params else []:
                                if text(field(param, "name"), declaring.raw) == parameter and declaring.imports.get("Qualifier") == "org.springframework.beans.factory.annotation.Qualifier":
                                    match = re.search(r'@Qualifier\s*\(\s*"([^"]+)"\s*\)', text(param, declaring.raw))
                                    if match:
                                        qualifiers.append(match)
                                        self.source(declaring.file, constructor.node, constructor.identity)
                    if qualifiers and len({q[1] for q in qualifiers}) == 1:
                        qualifier = qualifiers[0]
                if qualifier:
                    implementations = [t for t in implementations if any(t.imports.get(a) == "org.springframework.stereotype." + a and re.search(r'@' + a + r'\s*\(\s*"' + re.escape(qualifier[1]) + r'"\s*\)', text(t.node, t.raw).split("{", 1)[0]) for a in ("Service", "Component"))]
            if implementations:
                candidates = [m for t in implementations for m in self.candidates(t, name, args, method, env)]
        call = self.add("calls", "invocation", source, context, phase, controls,
                        {"method": name, "receiver_type": typ, "target": candidates[0].identity if len(candidates) == 1 else "",
                         "arguments": [text(a, raw) for a in args], "parent_context": parent,
                         "sender_type": method.owner.name, "target_owner": candidates[0].owner.name if len(candidates) == 1 else typ})
        call["details"]["argument_types"] = [self.infer(a, method, env) for a in args]
        hint = self.hints.get(call["fact_id"])
        if hint and hint["type"] == "call_binding":
            candidates = [m for m in candidates if m.identity == hint["binding"]["declaration_id"]]
            call["details"]["target"] = candidates[0].identity if len(candidates) == 1 else ""
            call["details"]["target_owner"] = candidates[0].owner.name if len(candidates) == 1 else typ
        self.step("call", call, controls)
        if receiver_text in bindings and name in {"run", "accept", "apply", "get", "call"}:
            self.callback(bindings[receiver_text], context, phase, controls, len(args))
            self.normal_conditions.setdefault(parent, []).extend(self.normal_conditions.get(context, []))
        elif len(candidates) == 1 and candidates[0].body is not None:
            bound, types = {}, {"this": typ}
            for (param, _), arg in zip(candidates[0].parameters, args):
                types[param] = self.infer(arg, method, env)
                if arg.type in {"lambda_expression", "method_reference"}:
                    bound[param] = (arg, method, env.copy(), bindings.copy())
                elif text(arg, raw) in bindings:
                    bound[param] = bindings[text(arg, raw)]
            outcome_start = len(self.value["outcomes"])
            self.expand(candidates[0], context, phase, controls, bound, types)
            self.normal_conditions.setdefault(parent, []).extend(self.normal_conditions.get(context, []))
            call["details"]["may_throw"] = any(o["type"] == "throw" for o in self.value["outcomes"][outcome_start:])
        elif len(candidates) > 1:
            for candidate in candidates:
                self.source(candidate.owner.file, candidate.node, candidate.identity)
                self.source(candidate.owner.file, candidate.owner.node, candidate.owner.name)
            self.gap("CALL_BINDING_AMBIGUOUS", source, context, "Bind receiver/overload with declaration and wiring evidence",
                     [m.identity for m in candidates], controls)
        elif target and len(candidates) == 1 and self.feign(target, candidates[0], call):
            pass
        elif self.persistence(typ, name, args, method, source, context, phase, controls, target):
            pass
        elif typ in JAVA_PURE and name in JAVA_PURE[typ]:
            call["details"]["target"] = typ + "." + name
            call["type"] = "pure_or_memory"
        elif hint and hint["type"] == "behavior_classification" and hint["binding"]["classification"] == "java_se17_path_construction":
            call["type"] = "pure_path_construction"
            call["details"]["target"] = hint["binding"]["declaration_id"]
            self.value["adapter_dependencies"]["java-se-api-profile"] = "17"
        elif typ in {"java.util.List", "java.util.Set", "java.util.Collection"} and name == "forEach" and len(args) == 1:
            branch = self.add("branches", "synchronous_iteration", source, context, phase, controls,
                              {"condition": receiver_text + " elements", "arms": ["nonempty", "empty"], "reachability": "conditional"})
            self.step("control_start", branch, controls)
            self.callback((args[0], method, env, bindings), context, phase, [*controls, branch["fact_id"]], 1)
            self.step("control_end", branch, controls)
        elif typ in {"java.util.concurrent.Executor", "java.util.concurrent.ExecutorService", "java.util.concurrent.ThreadPoolExecutor",
                     "org.springframework.core.task.TaskExecutor", "org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor"} and name in {"submit", "execute"} and args:
            if typ in {"java.util.concurrent.Executor", "org.springframework.core.task.TaskExecutor"}:
                self.gap("EXECUTOR_SCHEDULING_UNRESOLVED", source, context,
                         "Executor/TaskExecutor may invoke inline; bind the implementation before classifying a background boundary", controls=controls)
            effect = self.add("effects", "task_submission", source, context, phase, controls,
                              {"executor_type": typ, "operation": name, "wait_observed": False, "task_call": call["fact_id"],
                               "execution_order": "task may overlap entry; listing task phase last does not prove it starts after entry return"})
            self.step("submit", effect, controls)
            decision = self.add("branches", "task_submission_result", source, context, phase, controls,
                {"condition": "executor submission", "arms": ["accepted", "rejected"], "reachability": "conditional"})
            self.step("control_start", decision, controls)
            self.outcome("async_submission", source, context, phase, [*controls, decision["fact_id"], "accepted"], refs=[effect["fact_id"], decision["fact_id"]])
            self.step("control_else", decision, controls, "rejected")
            rejected = self.outcome("async_rejection", source, context, phase, [*controls, decision["fact_id"], "rejected"], refs=[effect["fact_id"], decision["fact_id"]])
            rejected["details"].update(possible_handlers=list(self.exception_scopes),
                observed_by_entry=phase == "entry" and len(self.stack) == 1 and not self.exception_scopes,
                boundary="entry" if len(self.stack) == 1 else "internal")
            if self.exception_scopes:
                self.gap("ERROR_PROPAGATION_UNRESOLVED", source, context,
                         "Executor rejection requires catch type matching and continuation evidence", controls=controls)
            self.step("control_end", decision, controls)
            self.background.append(((args[0], method, env.copy(), bindings.copy()), context, [*controls, effect["fact_id"], decision["fact_id"], "accepted"]))
            self.normal_conditions.setdefault(parent, []).extend([decision["fact_id"], "accepted"])
        elif receiver_text in {"log", "logger"} and typ in {"org.slf4j.Logger", "java.util.logging.Logger"}:
            call["type"] = "logging"
        else:
            self.gap("CALL_CONTRACT_UNSUPPORTED", source, context, "Unresolved declaration or external contract: " + typ + "." + name,
                     [m.identity for m in candidates], controls)
        self.step("return", call, list(dict.fromkeys([*controls, *self.normal_conditions.get(parent, [])])))

    def feign(self, owner, method, call):
        if owner.imports.get("FeignClient") != "org.springframework.cloud.openfeign.FeignClient":
            return False
        declaration = text(owner.node, owner.raw).split("{", 1)[0]
        client = re.search(r'@FeignClient\s*\(\s*(?:name\s*=\s*|value\s*=\s*)?"([^"${}]+)"', declaration)
        mapping = re.search(r'@(Get|Post|Put|Patch|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"${}]+)"', text(method.node, owner.raw))
        if not client or not mapping:
            self.gap("EXTERNAL_SYSTEM_UNRESOLVED", call["evidence_refs"][0], call["context_id"],
                     "Bind literal FeignClient name and mapped endpoint", controls=call["conditions"])
        else:
            refs = [self.source(owner.file, owner.node, owner.name), self.source(owner.file, method.node, method.identity)]
            self.outbound(call, client[1], mapping[1].upper() + " " + mapping[2], refs)
        return True

    def persistence(self, typ, name, args, method, source, context, phase, controls, target):
        from .storage import sql_resources
        import ast
        sql_types = {"org.springframework.jdbc.core.JdbcTemplate", "java.sql.Statement"}
        kv_types = {"redis.clients.jedis.Jedis", "org.springframework.data.redis.core.StringRedisTemplate"}
        resources = []
        if typ in sql_types and name in {"query", "queryForList", "queryForObject", "update", "execute", "executeQuery", "executeUpdate"}:
            literal = text(args[0], method.owner.raw) if args else ""
            try:
                sql = ast.literal_eval(literal) if args and args[0].type == "string_literal" else None
            except (ValueError, SyntaxError):
                sql = None
            resources = [(resource, operation, "relational_table") for resource, operation in sql_resources(sql)]
        elif typ in kv_types and name in {"get", "set", "setex", "del", "hget", "hset"}:
            try:
                key = ast.literal_eval(text(args[0], method.owner.raw)) if args and args[0].type == "string_literal" else None
            except (ValueError, SyntaxError):
                key = None
            if isinstance(key, str) and key:
                resources = [(key, "read" if name in {"get", "hget"} else "write", "kv_namespace")]
        if resources:
            for resource, operation, resource_type in resources:
                action = self.add("persistence_actions", "literal_api", source, context, phase, controls,
                    {"resource_type": resource_type, "resource_name": resource, "operation": operation,
                     "commit": "not established by API return"})
                self.participant(resource, "storage")
                self.step("persistence", action, controls)
                if operation != "read":
                    self.outcome("write_attempt", source, context, phase, controls, refs=[action["fact_id"]])
            return True
        if typ in kv_types:
            self.gap("PERSISTENCE_OBJECT_UNRESOLVED", source, context,
                     "Provide a literal KV key at this call or source-proven non-persistence resolution", controls=controls)
            return True
        repository, entity_name = None, ""
        choices = self.index.repository_entities(target)
        if len(choices) == 1:
            repository, entity_name = choices[0]
        if repository and name in {"save", "saveAndFlush", "findById", "findAll", "delete", "deleteById", "existsById", "count"}:
            arity = {"findAll": 0, "count": 0}.get(name, 1)
            if len(args) != arity or target and any(m.name == name for m in target.methods):
                self.gap("PERSISTENCE_METHOD_CONTRACT_UNSUPPORTED", source, context,
                         "Custom repository declaration/overload needs its own query contract", controls=controls)
                return True
            if not self.library_contract("org.springframework.data", "spring-data-jpa", "3.3.0", source, context, controls,
                                         location=repository.file):
                return True
            entity = self.index.resolve_type(entity_name, repository)
            if not entity:
                self.gap("PERSISTENCE_ENTITY_UNRESOLVED", source, context, "Resolve repository generic entity", controls=controls)
                return True
            mapping = self.entity_mapping(entity, source, context, controls)
            if mapping is None:
                return True
            resource, label, columns, proofs = mapping
            operation = "save" if name.startswith("save") else "delete" if name.startswith("delete") else "read"
            p = self.add("persistence_actions", "jpa", source, context, phase, controls,
                         {"resource_type": "relational_table", "resource_name": resource,
                          "display_name": label, "operation": operation,
                          "fields": list(columns.values()), "predicate": [text(a, method.owner.raw) for a in args],
                          "affected_rows": "not observed", "commit": "not established by repository return"},
                         [*proofs, *self.library_proofs.get("spring-data-jpa", [])])
            self.participant(resource, "storage")
            self.step("persistence", p, controls)
            if operation != "read":
                self.outcome("write_attempt", source, context, phase, controls, refs=[p["fact_id"]])
            return True
        if typ in {"jakarta.persistence.EntityManager", "javax.persistence.EntityManager",
                   "com.querydsl.jpa.impl.JPAUpdateClause", "com.querydsl.jpa.impl.JPADeleteClause", "com.querydsl.jpa.impl.JPAQueryFactory",
                   "org.springframework.jdbc.core.JdbcTemplate", "java.sql.Statement", "java.sql.PreparedStatement"}:
            self.gap("PERSISTENCE_OBJECT_UNRESOLVED", source, context, "Bound storage API needs a literal query or explicit entity/resource mapping: " + typ + "." + name, controls=controls)
            return True
        return False

    def library_contract(self, group, artifact, supported, source, context, controls, *, location=None):
        def children(node, name):
            return [n for n in node if n.tag.rsplit("}", 1)[-1] == name]
        def value(node, name):
            return next((n.text or "" for n in children(node, name)), "").strip()
        location = location or next(p["file"] for p in self.value["sources"] if p["evidence_id"] == source)
        directory = posixpath.dirname(location)
        nearest = ""
        while True:
            candidate = posixpath.join(directory, "pom.xml")
            if candidate in self.sources:
                nearest = candidate
                break
            if not directory:
                break
            directory = posixpath.dirname(directory)
        chain, seen = [], set()
        file = nearest
        unresolved_parent = False
        while file and file not in seen:
            seen.add(file)
            try:
                root = ET.fromstring(self.sources[file])
            except ET.ParseError:
                break
            chain.append((file, root))
            parents = children(root, "parent")
            if not parents:
                break
            parent = parents[0]
            relative = value(parent, "relativePath") if children(parent, "relativePath") else "../pom.xml"
            candidate = posixpath.normpath(posixpath.join(posixpath.dirname(file), relative))
            if not relative or candidate.startswith("../") or candidate not in self.sources:
                unresolved_parent = True
                break
            try:
                parent_root = ET.fromstring(self.sources[candidate])
            except ET.ParseError:
                unresolved_parent = True
                break
            if any(value(parent, key) != value(parent_root, key) for key in ("groupId", "artifactId", "version")):
                unresolved_parent = True
                break
            file = candidate
        properties, managed = {}, {}
        for _, root in reversed(chain):
            properties.update({n.tag.rsplit("}", 1)[-1]: (n.text or "").strip()
                               for p in children(root, "properties") for n in p})
            for management in children(root, "dependencyManagement"):
                for deps in children(management, "dependencies"):
                    for dependency in deps:
                        managed[value(dependency, "groupId"), value(dependency, "artifactId")] = value(dependency, "version")
        def interpolate(version):
            visited = set()
            while re.search(r"\$\{([^}]+)\}", version) and version not in visited:
                visited.add(version)
                version = re.sub(r"\$\{([^}]+)\}", lambda m: properties.get(m[1], m[0]), version)
            return version
        versions = []
        # The child declaration overrides the inherited dependency. Management
        # supplies a version only for a dependency actually present in the chain.
        for _, root in chain:
            for deps in children(root, "dependencies"):
                for dependency in children(deps, "dependency"):
                    if value(dependency, "groupId") != group or value(dependency, "artifactId") != artifact:
                        continue
                    versions.append(interpolate(value(dependency, "version") or managed.get((group, artifact), "")))
            if versions:
                break
        if any(children(root, "profiles") for _, root in chain):
            versions = []  # Active profile selection has not been established.
        if not versions or set(versions) != {supported}:
            self.gap("LIBRARY_CONTRACT_VERSION_UNSUPPORTED", source, context,
                f"Resolve owning Maven module dependency {group}:{artifact}:{supported}; local parents/properties/management supported, external BOM/profiles/other versions unproven"
                + ("; external parent unavailable" if unresolved_parent else ""), controls=controls)
            return False
        proofs = [self.source_document(file, group + ":" + artifact) for file, _ in chain]
        self.value["adapter_dependencies"][group + ":" + artifact] = supported
        self.library_proofs[artifact] = proofs
        return True

    def entity_mapping(self, entity, source, context, controls):
        declaration = text(entity.node, entity.raw)
        declaration = re.sub(r"@(jakarta|javax)\.persistence\.", "@", declaration)
        proof = self.source(entity.file, entity.node, entity.name)
        def bound_annotation(name, content):
            match = re.search(r"@([\w.]*\b" + name + r")\b", content)
            return bool(match and self.type_name(match[1], entity) in {"jakarta.persistence." + name, "javax.persistence." + name})
        original_header = text(entity.node, entity.raw).split("{", 1)[0]
        if not bound_annotation("Entity", original_header):
            self.gap("PERSISTENCE_ENTITY_UNRESOLVED", source, context, "Repository entity must have a bound JPA Entity annotation", controls=controls)
            return None
        if re.search(r"@(?:[\w.]+\.)?Table\b", original_header) and not bound_annotation("Table", original_header):
            self.gap("PERSISTENCE_ANNOTATION_UNRESOLVED", source, context,
                     "Table annotation must bind to JPA, not a matching short name", controls=controls)
            return None
        if any(re.search(r"@(?:Id|Column|Access)\b", text(m.node, entity.raw).split("{", 1)[0]) for m in entity.methods):
            self.gap("PERSISTENCE_PROPERTY_ACCESS_UNSUPPORTED", source, context, "JPA getter/property access needs a mapping adapter", controls=controls)
            return None
        table = re.search(r'@Table\s*\([^)]*\bname\s*=\s*"([^"]+)"', declaration.split("{", 1)[0])
        configurations = [(p, s) for p, s in self.sources.items() if p.endswith((".properties", ".yml", ".yaml", ".xml"))
                          and re.search(r"physical.naming|physical-strategy|PhysicalNamingStrategy", s)]
        config_proofs = [self.source_document(p, "jpa-naming-configuration") for p, _ in configurations]
        call = next((c for c in self.value["calls"] if c["context_id"] == context), None)
        hint = self.hints.get(call["fact_id"]) if call else None
        default_table = ""
        standard_columns = bool(hint and hint["type"] == "resource_mapping" and hint["binding"]["classification"] in {
            "jpa_standard_default_table", "jpa_standard_default_columns"})
        if not table:
            if hint and hint["type"] == "resource_mapping" and hint["binding"]["classification"] == "jpa_standard_default_table":
                entity_name = re.search(r'@Entity\s*\(\s*name\s*=\s*"([^"]+)"', declaration.split("{", 1)[0])
                default_table = entity_name[1] if entity_name else entity.name.rsplit(".", 1)[-1]
            else:
                self.gap("PERSISTENCE_NAMING_UNRESOLVED", source, context, "Default/custom JPA physical naming needs configuration evidence", controls=controls)
                return None
        if any("PhysicalNamingStrategyStandardImpl" not in s for _, s in configurations):
            self.gap("PERSISTENCE_NAMING_STRATEGY_UNSUPPORTED", source, context, "Custom naming may transform explicit table names", controls=controls)
            return None
        columns, proofs = {}, [proof, *config_proofs]
        for prop, (_, declaration_node) in entity.fields.items():
            field_source = text(declaration_node, entity.raw)
            if re.search(r"@(?:[\w.]+\.)?Column\b", field_source) and not bound_annotation("Column", field_source):
                self.gap("PERSISTENCE_ANNOTATION_UNRESOLVED", source, context,
                         "Column annotation must bind to JPA: " + prop, controls=controls)
                return None
            field_source = re.sub(r"@(jakarta|javax)\.persistence\.", "@", field_source)
            if re.search(r"\bstatic\b", field_source) or (re.search(r"@Transient\b", field_source) and self.type_name("Transient", entity) in {"jakarta.persistence.Transient", "javax.persistence.Transient"}):
                continue
            if re.search(r"@(?:OneToMany|ManyToOne|OneToOne|ManyToMany|Embedded|ElementCollection)\b", field_source):
                self.gap("PERSISTENCE_ASSOCIATION_UNSUPPORTED", source, context, "Association/embedded field requires explicit mapping support: " + prop, controls=controls)
                return None
            annotation = re.search(r'@Column\s*\([^)]*\bname\s*=\s*"([^"]+)"', field_source)
            if annotation:
                columns[prop] = annotation[1]
                proofs.append(self.source(entity.file, declaration_node, entity.name + "." + prop))
            elif standard_columns:
                columns[prop] = prop
                proofs.append(self.source(entity.file, declaration_node, entity.name + "." + prop))
            else:
                self.gap("PERSISTENCE_COLUMN_UNRESOLVED", source, context, "Default physical column requires naming evidence: " + prop, controls=controls)
                return None
        previous = entity.node.prev_named_sibling
        label_source = text(previous, entity.raw) if previous and previous.type in {"block_comment", "line_comment"} else ""
        label = re.search(r"[\u3400-\u9fff][^\n*]+", label_source)
        if label:
            proofs.append(self.source(entity.file, previous, entity.name + ":business-name"))
        schema = re.search(r'@Table\s*\([^)]*\bschema\s*=\s*"([^"]+)"', declaration.split("{", 1)[0])
        if not schema and any(re.search(r"default_schema|default-schema", content) for file, content in self.sources.items()
                              if file.endswith((".properties", ".yml", ".yaml", ".xml"))):
            self.gap("PERSISTENCE_SCHEMA_UNRESOLVED", source, context,
                     "Configured default schema must be resolved before claiming a physical resource", controls=controls)
            return None
        return (schema[1] + "." if schema else "") + (table[1] if table else default_table), label[0].strip() if label else "", columns, proofs

    def querydsl(self, node, method, env, parent, phase, controls, typ):
        raw = method.owner.raw
        source = self.source(method.owner.file, node, method.identity)
        if not self.library_contract("com.querydsl", "querydsl-jpa", "5.1.0", source, parent, controls):
            return
        chain, root = [], field(node, "object")
        while root is not None and root.type == "method_invocation":
            chain.append((text(field(root, "name"), raw), list(field(root, "arguments").named_children)))
            root = field(root, "object")
        entity_node = None
        if root is not None and root.type == "object_creation_expression":
            args = field(root, "arguments").named_children
            entity_node = args[1] if len(args) == 2 else None
            if args and self.infer(args[0], method, env) not in {"jakarta.persistence.EntityManager", "javax.persistence.EntityManager"}:
                self.gap("QUERYDSL_ENTITY_MANAGER_UNRESOLVED", source, parent, "Update/delete constructor must bind EntityManager", controls=controls)
                return
        else:
            entity_node = next((args[0] for name, args in chain if name in {"update", "delete"} and len(args) == 1), None)
        if entity_node is None:
            self.gap("QUERYDSL_RESOURCE_UNRESOLVED", source, parent, "Query root must bind to an EntityPath declaration", controls=controls)
            return
        query_type = self.infer(entity_node, method, env)
        query = self.index.types.get(query_type)
        if query is None and entity_node.type == "field_access":
            query = self.index.types.get(self.infer(field(entity_node, "object"), method, env))
        entity = None
        if query:
            for base in query.parents:
                match = re.search(r"EntityPathBase<\s*([\w.]+)\s*>", base)
                if match and self.type_name("EntityPathBase", query) == "com.querydsl.core.types.dsl.EntityPathBase":
                    entity = self.index.resolve_type(match[1], query)
        if entity is None:
            self.gap("QUERYDSL_RESOURCE_UNRESOLVED", source, parent, "Generated path generic entity is unavailable or ambiguous", controls=controls)
            return
        mapping = self.entity_mapping(entity, source, parent, controls)
        if mapping is None:
            return
        resource, label, columns, proofs = mapping
        fields, predicates, assignments = [], [], []
        def query_column(expression):
            if expression.type != "field_access" or text(field(expression, "object"), raw) != text(entity_node, raw):
                return None
            prop = text(field(expression, "field"), raw)
            declaration = query.fields.get(prop)
            if prop not in columns or declaration is None:
                return None
            path_type, path_node = declaration
            if self.type_name(re.sub(r"<.*>", "", path_type), query) not in {
                    "com.querydsl.core.types.dsl.StringPath", "com.querydsl.core.types.dsl.NumberPath", "com.querydsl.core.types.dsl.BooleanPath",
                    "com.querydsl.core.types.dsl.DatePath", "com.querydsl.core.types.dsl.DateTimePath", "com.querydsl.core.types.dsl.EnumPath"}:
                return None
            creation = re.search(r'\bcreate(?:String|Number|Boolean|Date|DateTime|Enum)\s*\(\s*"([^"]+)"', text(path_node, query.raw))
            if not creation or creation[1] != prop:
                return None
            if any(m.name == creation[0].split("(", 1)[0].strip() for m in query.methods):
                return None
            proofs.append(self.source(query.file, path_node, query.name + "." + prop))
            return columns[prop]

        for name, args in reversed(chain):
            if name == "where":
                for arg in args:
                    for expression in walk(arg):
                        if expression.type == "method_invocation" and text(field(expression, "name"), raw) not in {
                                "eq", "ne", "lt", "loe", "gt", "goe", "in", "notIn", "isNull", "isNotNull", "and", "or", "not"}:
                            self.gap("QUERYDSL_PREDICATE_UNSUPPORTED", source, parent,
                                     "Predicate contains an unsupported call", controls=controls)
                            return
                        if expression.type == "field_access" and not query_column(expression):
                            self.gap("QUERYDSL_PREDICATE_UNRESOLVED", source, parent,
                                     "Every predicate path must bind to this query entity and a mapped column", controls=controls)
                            return
                    if not any(n.type == "field_access" for n in walk(arg)):
                        self.gap("QUERYDSL_PREDICATE_UNRESOLVED", source, parent,
                                 "Predicate must have a source-bound query path", controls=controls)
                        return
                    predicates.append(text(arg, raw))
            elif name == "set" and len(args) == 2:
                column = query_column(args[0])
                if column is None:
                    self.gap("PERSISTENCE_COLUMN_UNRESOLVED", source, parent, "Query path and explicit physical column are required", controls=controls)
                    return
                self.visit(args[1], method, env, {}, parent, phase, controls)
                fields.append(column)
                assignments.append({"field": column, "value": text(args[1], raw)})
            elif name not in {"update", "delete"}:
                self.gap("QUERYDSL_OPERATION_UNSUPPORTED", source, parent, "Unsupported QueryDSL chain operation: " + name, controls=controls)
                return
        context = stable_id("K", parent, source, self.ordinals[(parent, source)])
        self.ordinals[(parent, source)] += 1
        result_usage = text(node.parent, raw)
        action = self.add("persistence_actions", "querydsl", source, context, phase, controls,
            {"resource_type": "relational_table", "resource_name": resource, "display_name": label,
             "operation": "update" if typ.endswith("JPAUpdateClause") else "delete", "fields": fields,
             "assignments": assignments, "predicate": predicates, "affected_rows": result_usage,
             "commit": "not established by execute return"}, proofs + self.library_proofs.get("querydsl-jpa", []) + [self.source(query.file, query.node, query.name)])
        if node.parent.type == "variable_declarator":
            variable = text(field(node.parent, "name"), raw)
            self.row_results[parent, variable] = action["fact_id"]
            action["details"]["result_variable"] = variable
        self.participant(resource, "storage")
        self.step("persistence", action, controls)
        self.outcome("write_attempt", source, context, phase, controls, refs=[action["fact_id"]])
