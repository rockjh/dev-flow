"""Bounded TypeScript/JavaScript/Go syntax facts; unknown contracts fail closed."""
import re
from ..core.syntax import field, parser_for, text, walk
from .evidence import Facts, stable_id


class TreeFacts(Facts):
    def __init__(self, *args):
        super().__init__(*args)
        self.language = "go" if self.entry.file.endswith(".go") else "typescript" if self.entry.file.endswith((".ts", ".tsx")) else "javascript"
        self.raw = self.sources[self.entry.file].encode()
        self.root = parser_for(self.language, self.entry.file.endswith(".tsx")).parse(self.raw).root_node
        self.declarations = []
        self.catch_scopes = []
        for node in walk(self.root):
            if node.type in {"function_declaration", "method_definition", "method_declaration"} and field(node, "body"):
                owner = node.parent
                while owner and owner.type not in {"class_declaration", "class", "program", "source_file"}:
                    owner = owner.parent
                owner_name = text(field(owner, "name"), self.raw) or self.entry.file
                name = text(field(node, "name"), self.raw)
                self.declarations.append((node, owner_name, name))

    def analyze(self):
        self.participant(self.entry.caller, "caller")
        candidates = [d for d in self.declarations if d[2] == self.entry.handler]
        if len(candidates) != 1:
            proof = self.source(self.entry.file, self.root, self.entry.file)
            self.gap("ENTRY_DECLARATION_UNRESOLVED", proof, self.entry.entry_id,
                     "Bind a unique handler declaration in this snapshot")
        else:
            self.expand(candidates[0], self.entry.entry_id, [])
        return self.finish()

    def expand(self, declaration, context, controls):
        node, owner, name = declaration
        identity = self.entry.file + ":" + owner + "." + name
        proof = self.source(self.entry.file, node, identity)
        if node in self.stack:
            self.gap("RECURSION_BOUNDARY", proof, context, "Recursive expansion is outside the static budget", controls=controls)
            return
        if node.has_error:
            self.gap("SOURCE_SYNTAX_UNRESOLVED", proof, context, "Repair an incomplete source expression", controls=controls)
        self.participant(self.entry.file + ":" + owner, "service")
        self.stack.append(node)
        if self.visit(field(node, "body"), declaration, context, controls):
            self.outcome("normal_completion" if len(self.stack) == 1 else "method_return", proof, context, "entry", controls)
        self.stack.pop()

    def visit(self, node, declaration, context, controls):
        if node is None:
            return True
        self.count += 1
        _, owner, name = declaration
        identity = self.entry.file + ":" + owner + "." + name
        proof = self.source(self.entry.file, node, identity)
        kind = node.type
        if self.count > self.budget:
            self.gap("ANALYSIS_BUDGET_EXCEEDED", proof, context, "Increase the explicit expansion budget or split the module", controls=controls)
            return False
        if kind in {"function_declaration", "method_definition", "method_declaration", "arrow_function", "function_expression", "func_literal"}:
            return True
        if kind in {"statement_block", "block", "statement_list"}:
            for child in node.named_children:
                if not self.visit(child, declaration, context, controls):
                    return False
            return True
        if kind == "else_clause":
            return self.visit(node.named_children[-1] if node.named_children else None, declaration, context, controls)
        if kind in {"for_statement", "while_statement", "do_statement"}:
            clause = next((child for child in node.named_children if child.type == "for_clause"), node)
            body = field(node, "body")
            condition = field(clause, "condition")
            if self.language == "go" and clause == node:
                condition = next((c for c in node.named_children if c != body), None)
            self.visit(field(clause, "initializer"), declaration, context, controls)
            branch = self.add("branches", kind, proof, context, "entry", controls,
                {"condition": text(condition, self.raw) or "unconditional", "arms": ["iteration", "empty"]})
            self.step("control_start", branch, controls)
            active = [*controls, branch["fact_id"], "iteration"]
            if kind != "do_statement":
                self.visit(condition, declaration, context, active)
            completed = self.visit(body, declaration, context, active)
            if completed:
                self.visit(field(clause, "update") or field(clause, "increment"), declaration, context, active)
                if kind == "do_statement":
                    self.visit(condition, declaration, context, active)
            self.step("control_end", branch, controls)
            if condition is None or condition.type == "range_clause":
                self.gap("LOOP_TERMINATION_UNRESOLVED", proof, context,
                         "Bind a supported loop condition and exit path", controls=active)
            return completed if kind == "do_statement" else True
        if kind in {"switch_statement", "expression_switch_statement"}:
            condition = field(node, "value") or field(node, "condition")
            self.visit(condition, declaration, context, controls)
            cases = [n for n in walk(node) if n.parent == (field(node, "body") or node)
                     and n.type in {"switch_case", "switch_default", "expression_case", "default_case"}]
            branch = self.add("branches", kind, proof, context, "entry", controls,
                {"condition": text(condition, self.raw), "arms": [text(field(c, "value"), self.raw) or "default" for c in cases]})
            self.step("control_start", branch, controls)
            completed = False
            for i, case in enumerate(cases):
                value = field(case, "value")
                arm = text(value, self.raw) or "default"
                if i:
                    self.step("control_else", branch, controls, arm)
                active = [*controls, branch["fact_id"], arm]
                statements = [child for child in case.named_children if child != value]
                can_continue = True
                for child in statements:
                    if child.type == "break_statement":
                        break
                    can_continue = self.visit(child, declaration, context, active)
                    if not can_continue:
                        break
                if self.language != "go" and can_continue and i + 1 < len(cases) and not any(c.type == "break_statement" for c in statements):
                    self.gap("SWITCH_FALLTHROUGH_UNRESOLVED", proof, context, "Prove the fallthrough path before acceptance", controls=active)
                completed |= can_continue
            if not cases:
                self.gap("SWITCH_CASE_UNRESOLVED", proof, context, "Bind explicit switch arms", controls=controls)
            self.step("control_end", branch, controls)
            return completed or not any("default" in c.type for c in cases)
        if kind in {"if_statement", "try_statement", "ternary_expression", "binary_expression"}:
            operator = text(field(node, "operator"), self.raw)
            short = kind == "binary_expression" and operator in {"&&", "||"}
            if kind == "binary_expression" and not short:
                for child in node.named_children:
                    self.visit(child, declaration, context, controls)
                return True
            condition = field(node, "condition") or field(node, "value") or field(node, "left")
            branch = self.add("branches", "short_circuit" if short else kind, proof, context, "entry", controls,
                {"condition": text(condition, self.raw), "arms": ["left_true" if operator == "&&" else "left_false", "alternative"] if short else ["true", "false"],
                 "reachability": "conditional", "non_decision_connector": short})
            self.visit(condition, declaration, context, controls)
            self.step("control_start", branch, controls)
            nested = [*controls, branch["fact_id"], "left_true" if operator == "&&" else "left_false" if short else "true"]
            if short:
                self.visit(field(node, "right"), declaration, context, nested)
                self.step("control_else", branch, controls, "alternative")
            elif kind in {"if_statement", "ternary_expression"}:
                completed = self.visit(field(node, "consequence"), declaration, context, nested)
                alternative = field(node, "alternative")
                other = True
                if alternative:
                    self.step("control_else", branch, controls, "false")
                    other = self.visit(alternative, declaration, context, [*controls, branch["fact_id"], "false"])
                self.step("control_end", branch, controls)
                if completed != other:
                    self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", proof, context,
                             "Prove the continuation after a conditional exit", controls=nested)
                return completed or other
            elif kind == "try_statement":
                handlers = [child for child in node.named_children if child.type == "catch_clause"]
                if handlers:
                    self.catch_scopes.append(branch["fact_id"])
                completed = self.visit(field(node, "body"), declaration, context, nested)
                if handlers:
                    self.catch_scopes.pop()
                for child in node.named_children:
                    if child.type == "catch_clause":
                        self.step("control_else", branch, controls, "catch " + text(field(child, "parameter"), self.raw))
                        completed = self.visit(field(child, "body"), declaration, context, [*nested, "catch"]) or completed
                    elif child.type == "finally_clause":
                        self.step("control_else", branch, controls, "finally")
                        self.visit(child, declaration, context, [*nested, "finally"])
                        if any(n.type in {"return_statement", "throw_statement"} for n in walk(child)):
                            self.gap("FINALLY_OVERRIDES_OUTCOME", proof, context, "Finally result dominance is unresolved", controls=nested)
                self.step("control_end", branch, controls)
                return completed
            self.step("control_end", branch, controls)
            return True
        if kind == "call_expression":
            self.call(node, declaration, context, controls, proof)
            return True
        if kind in {"return_statement", "throw_statement", "break_statement", "continue_statement"}:
            for child in node.named_children:
                self.visit(child, declaration, context, controls)
            typ = ("entry_response" if len(self.stack) == 1 else "method_return") if kind == "return_statement" else kind.removesuffix("_statement")
            outcome = self.outcome(typ, proof, context, "entry", controls, text(node, self.raw))
            if typ == "throw":
                outcome["details"].update(observed_by_entry=not self.catch_scopes and len(self.stack) == 1,
                    propagation="caught by JavaScript catch" if self.catch_scopes else "uncaught at this declaration")
                if self.catch_scopes:
                    outcome["details"]["caught_by"] = self.catch_scopes[-1]
            if typ in {"break", "continue"}:
                self.gap("CONTROL_EXIT_MERGE_UNSUPPORTED", proof, context, "Loop exit continuation is unresolved", controls=controls)
            return False
        if kind in {"await_expression", "go_statement", "defer_statement", "yield_expression"}:
            self.gap("ASYNC_SEMANTICS_UNSUPPORTED", proof, context,
                     "Suspension/deferred execution requires a source-bound contract", controls=controls)
        if kind in {"new_expression", "for_in_statement", "select_statement", "type_switch_statement", "labeled_statement", "with_statement"}:
            self.gap("CONTROL_SEMANTICS_UNSUPPORTED", proof, context,
                     "Explicit semantics require a registered contract: " + kind, controls=controls)
        for child in node.named_children:
            self.visit(child, declaration, context, controls)
        return True

    def call(self, node, declaration, parent, controls, proof):
        func = field(node, "function")
        args_node = field(node, "arguments")
        args = args_node.named_children if args_node else []
        for arg in args:
            self.visit(arg, declaration, parent, controls)
        expression = text(func, self.raw)
        name = expression.rsplit(".", 1)[-1]
        receiver = expression.rsplit(".", 1)[0] if "." in expression else ""
        owner = declaration[1]
        candidates = [d for d in self.declarations if d[2] == name and (not receiver and d[1] == self.entry.file or receiver == "this" and d[1] == owner)]
        context = stable_id("K", parent, proof, len(self.value["calls"]))
        target = self.entry.file + ":" + candidates[0][1] if len(candidates) == 1 else ""
        call = self.add("calls", "invocation", proof, context, "entry", controls,
            {"method": name, "receiver_type": receiver, "target": target + "." + name if target else "",
             "target_owner": target, "sender_type": self.entry.file + ":" + owner,
             "arguments": [text(a, self.raw) for a in args], "parent_context": parent})
        self.step("call", call, controls)
        if len(candidates) == 1:
            self.expand(candidates[0], context, controls)
        elif self.external(expression, args, call):
            pass
        elif self.persistence(expression, args, proof, context, controls):
            pass
        elif expression in {"console.log", "console.error", "fmt.Println", "fmt.Printf"}:
            call["type"] = "logging"
        else:
            self.gap("CALL_CONTRACT_UNSUPPORTED", proof, context,
                     "Bind the declaration or external contract: " + expression, controls=controls)
        self.step("return", call, controls)

    def persistence(self, expression, args, proof, context, controls):
        # Prisma model names are not physical tables: require @@map in a
        # committed schema and a source import of its generated client.
        source = self.sources[self.entry.file]
        matched = re.fullmatch(r"(?:this\.)?(\w+)\.(\w+)\.(findMany|findUnique|findFirst|create|update|delete|upsert|count)", expression)
        if matched and re.search(r"import\s*\{[^}]*\bPrismaClient\b(?!\s+as\b)[^}]*\}\s*from\s*['\"]@prisma/client['\"]", source):
            variable, model, operation = matched.groups()
            bound = re.search(r"\b" + re.escape(variable) + r"\s*(?::\s*PrismaClient|=\s*new\s+PrismaClient\s*\()", source)
            if len(re.findall(r"\b" + re.escape(variable) + r"\s*[:=]", source)) != 1 or re.search(r"\b(?:class|function|const|let)\s+PrismaClient\b", source):
                bound = None
            mappings = [(file, match) for file, content in self.sources.items() if file.endswith(".prisma")
                        for match in re.finditer(r"^\s*model\s+(\w+)\s*\{([^}]*)\}", re.sub(r"/\*.*?\*/|//[^\n]*", "", content, flags=re.S), re.S | re.M)
                        if match[1][0].lower() + match[1][1:] == model]
            table = re.search(r'@@map\s*\(\s*"([^"]+)"\s*\)', mappings[0][1][2]) if len(mappings) == 1 else None
            if not bound or not table:
                self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context,
                         "Bind PrismaClient and an explicit schema model @@map", controls=controls)
            else:
                extra = self.source_document(mappings[0][0], "prisma-model:" + mappings[0][1][1])
                self.storage(table[1], "read" if operation.startswith("find") or operation == "count" else "write", proof, context, controls, [extra])
            return True
        if self.language == "go" and '"gorm.io/gorm"' in source:
            match = re.fullmatch(r"(\w+)\.(Find|First|Create|Save|Delete)", expression)
            if match and re.search(r"\b" + match[1] + r"\s+\*gorm\.DB\b", source):
                variable = text(args[0], self.raw).removeprefix("&") if args else ""
                typ = re.search(r"\b" + re.escape(variable) + r"\s+(?:\[\])?(\w+)\b", source)
                declaration = next((d for d in self.declarations if d[2] == "TableName"
                    and typ and re.search(r"\(\s*(?:\w+\s+)?\*?" + re.escape(typ[1]) + r"\s*\)", text(d[0], self.raw))), None)
                table = re.fullmatch(r'\{\s*return\s+"([^"\n]+)"\s*;?\s*\}', text(field(declaration[0], "body"), self.raw)) if declaration else None
                if not table:
                    self.gap("PERSISTENCE_OBJECT_UNRESOLVED", proof, context, "Bind GORM entity type and a literal TableName method", controls=controls)
                else:
                    extra = self.source(self.entry.file, declaration[0], self.entry.file + ":TableName")
                    self.storage(table[1], "read" if match[2] in {"Find", "First"} else "write", proof, context, controls, [extra], adapter="gorm")
                return True
        return False

    def storage(self, resource, operation, proof, context, controls, refs=(), adapter="prisma"):
        action = self.add("persistence_actions", adapter, proof, context, "entry", controls,
            {"resource_type": "relational_table", "resource_name": resource, "operation": operation,
             "commit": "not established by repository return"}, refs)
        self.participant(resource, "storage")
        self.step("persistence", action, controls)
        if operation != "read":
            self.outcome("write_attempt", proof, context, "entry", controls, refs=[action["fact_id"]])

    def external(self, expression, args, call):
        import json
        from urllib.parse import urlsplit
        source = self.sources[self.entry.file]
        supported = self.language == "go" and expression in {"http.Get", "http.Post"} and '"net/http"' in source
        supported |= self.language in {"typescript", "javascript"} and expression == "fetch" and not re.search(r"(?:function|const|let|var)\s+fetch\b|\bfetch\s*:", source)
        if not supported:
            return False
        try:
            endpoint = json.loads(text(args[0], self.raw)) if args else ""
            target = urlsplit(endpoint) if isinstance(endpoint, str) else None
        except (ValueError, TypeError):
            target = None
        if not target or target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
            self.gap("EXTERNAL_SYSTEM_UNRESOLVED", call["evidence_refs"][0], call["context_id"],
                     "Provide a literal HTTP endpoint with a resolvable host and no credentials", controls=call["conditions"])
        else:
            self.outbound(call, target.hostname, endpoint)
        return True
