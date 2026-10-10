"""Pure evidence, control, ordering and document gates."""
from .models import RuleResult, SequenceBlock, ValidationReport
from .repository import digest
from .control_flow import build_control_flow


def target_evidence(scopes):
    """Bind a proof to the fact it supports, not merely its containing scope."""
    targets = {}
    for scope in scopes:
        for item in (*scope.steps, *scope.controls, *scope.external):
            identifier = getattr(item, "step_id", None) or getattr(item, "control_id", None) or item.operation_id
            targets[identifier] = set(item.evidence_ids)
        for control in scope.controls:
            for exit_id in control.exit_ids:
                targets[exit_id] = set(control.evidence_ids)
        for symbol in scope.symbols:
            targets.setdefault(symbol.symbol_id, set()).update(
                item.evidence_id for item in scope.evidence if item.symbol_id == symbol.symbol_id)
    return targets


class FlowValidator:
    def validate_model(self, model):
        rules, gaps = [], []
        scope_ids = [scope.scope.entry_id for scope in model.scopes]
        rules.append(RuleResult("model.unique_scopes", len(scope_ids) == len(set(scope_ids)), "unique selected units"))
        for scope in model.scopes:
            evidence = {item.evidence_id: item for item in scope.evidence}
            steps = {item.step_id: item for item in scope.steps}
            controls = {item.control_id: item for item in scope.controls}
            contexts = {item.context_id for item in scope.contexts}
            rules.append(RuleResult("model.unique_ids", len(steps) == len(scope.steps) and len(evidence) == len(scope.evidence) and len(controls) == len(scope.controls) and len(contexts) == len(scope.contexts), scope.scope.entry_id))
            observed_steps, observed_controls, observed_exits = [], [], []
            order = {(item.block_id, item.exit_id): item.item_ids for item in scope.ordering}
            exit_labels = {(item.block_id, item.exit_id): item.label for item in scope.ordering}
            observed_order = set()
            rules.append(RuleResult("control.unique_order", len(order) == len(scope.ordering), scope.scope.entry_id))
            try:
                graph = build_control_flow(scope.sequence, scope.steps, scope.controls, scope.contexts)
                valid_graph = bool(scope.control_flow) and scope.control_flow == graph
            except (ValueError, KeyError):
                graph, valid_graph = (), False
            rules.append(RuleResult("control.flow_graph", valid_graph, scope.scope.entry_id))
            for control in scope.controls:
                incoming = tuple(sorted({edge.source_id for edge in graph if edge.target_id == control.control_id}))
                outgoing = tuple(sorted({edge.target_id for edge in graph if edge.source_id == control.control_id}))
                rules.append(RuleResult("control.adjacency", control.predecessors == incoming and control.successors == outgoing, control.control_id))
            def visit(block, parent="", incoming_terminated=frozenset(), incoming_previous=frozenset()):
                if block.kind != "sequence":
                    observed_controls.append(block.block_id)
                    control = controls.get(block.block_id)
                    rules.append(RuleResult("control.parent_exits", control is not None and control.parent_id == parent and control.kind == block.kind and control.condition == block.label and control.exit_ids == tuple(arm.exit_id for arm in block.arms), block.block_id))
                    current_parent = block.block_id
                else:
                    current_parent = parent
                outcomes = []
                for arm in block.arms:
                    key = (block.block_id, arm.exit_id)
                    observed_order.add(key)
                    actual = tuple(item.block_id if isinstance(item, SequenceBlock) else item.step_id for item in arm.items)
                    rules.append(RuleResult("control.source_order", key in order and order[key] == actual, block.block_id + ":" + arm.exit_id))
                    rules.append(RuleResult("control.exit_label", exit_labels.get(key) == arm.label, block.block_id + ":" + arm.exit_id))
                    if arm.exit_id:
                        observed_exits.append(arm.exit_id)
                    terminated, previous = set(incoming_terminated), set(incoming_previous)
                    for item in arm.items:
                        if isinstance(item, SequenceBlock):
                            terminated, previous = visit(item, current_parent, terminated, previous)
                        else:
                            step = steps.get(item.step_id)
                            observed_steps.append(item.step_id)
                            rules.append(RuleResult("step.reference", step is not None, item.step_id))
                            if step is None:
                                continue
                            rules.append(RuleResult("step.evidence_context", bool(step.evidence_ids) and set(step.evidence_ids) <= evidence.keys() and step.context_id in contexts, step.step_id))
                            control_context = controls.get(block.block_id)
                            rules.append(RuleResult("step.control_exit", step.control_exit == arm.exit_id if control_context and step.context_id == control_context.context_id else True, step.step_id))
                            rules.append(RuleResult("step.after_termination", step.context_id not in terminated or step.kind in {"cleanup", "call_return"}, step.step_id))
                            if step.kind in {"return", "raise", "throw", "panic"}:
                                terminated.add(step.context_id)
                            rules.append(RuleResult("step.dependencies", set(step.dependencies) <= previous, step.step_id))
                            previous.add(step.step_id)
                    outcomes.append((terminated, previous))
                if not outcomes or block.kind in {"loop", "opt"}:
                    return set(incoming_terminated), set(incoming_previous)
                return set.intersection(*(outcome[0] for outcome in outcomes)), set.intersection(*(outcome[1] for outcome in outcomes))
            visit(scope.sequence)
            rules.append(RuleResult("coverage.order", observed_order == order.keys(), scope.scope.entry_id))
            rules.append(RuleResult("coverage.steps", len(observed_steps) == len(set(observed_steps)) and set(observed_steps) == steps.keys(), scope.scope.entry_id))
            rules.append(RuleResult("coverage.controls", len(observed_controls) == len(set(observed_controls)) and set(observed_controls) == controls.keys(), scope.scope.entry_id))
            rules.append(RuleResult("coverage.exits", len(observed_exits) == len(set(observed_exits)) and set(observed_exits) == {e for c in scope.controls for e in c.exit_ids}, scope.scope.entry_id))
            for operation in scope.external:
                rules.append(RuleResult("operation.resolution", operation.resolution != "unknown", operation.operation_id))
                if operation.completion == "dispatched":
                    rules.append(RuleResult("operation.dispatch", operation.call_site_id in steps and steps[operation.call_site_id].kind == "dispatch", operation.operation_id))
            gaps.extend(scope.gaps)
        return ValidationReport(tuple(rules), tuple(gaps))

    def validate_submission(self, package, submission):
        expected = {task.task_id for task in package.tasks}
        results, receipts = [r.task_id for r in submission.results], [r.task_id for r in submission.receipts]
        return ValidationReport((RuleResult("host.identity", submission.run_id == package.run_id and submission.package_hash == digest(package), "bound package identity"),
            RuleResult("host.results", len(results) == len(set(results)) and set(results) == expected, "complete unique results"),
            RuleResult("host.receipts", len(receipts) == len(set(receipts)) and set(receipts) == expected, "complete unique receipts")))

    def validate_bundle(self, bundle, model, annotations, intent, renderer):
        rebuilt = renderer.build(model, annotations, intent, bundle.requirement_report)
        rules = [RuleResult("document.tree_and_order", digest(bundle) == digest(rebuilt), "tree, Mermaid, matrix and coverage reproduce from frozen facts")]
        for scope in model.scopes:
            scenes = [s for s in bundle.scenes if s.view == "implementation" and s.scope_id == scope.scope.entry_id]
            expected = {s.step_id for s in scope.steps} | {c.control_id for c in scope.controls} | {e for c in scope.controls for e in c.exit_ids} | {o.operation_id for o in scope.external}
            actual = {p.target_id for s in scenes for p in s.positions}
            rules.append(RuleResult("document.actual_positions", expected <= actual and bool(scenes), scope.scope.entry_id))
        for scene in bundle.scenes:
            stack = []
            lines = scene.mermaid.splitlines()
            valid = lines[:3] == [lines[0], "sequenceDiagram", "autonumber"] and lines[0].startswith("%%{init:") and ";" not in scene.mermaid
            for line in lines[3:]:
                if line.startswith(("alt ", "opt ", "loop ", "par ")):
                    stack.append(line.split()[0])
                elif line == "end":
                    valid = valid and bool(stack)
                    if stack:
                        stack.pop()
                elif line.startswith("else "):
                    valid = valid and bool(stack) and stack[-1] == "alt"
                elif line.startswith("and "):
                    valid = valid and bool(stack) and stack[-1] == "par"
            rules.append(RuleResult("document.mermaid_structure", valid and not stack, scene.filename))
            rules.append(RuleResult("document.layout", '"wrap": true' in scene.mermaid and '"activationWidth": 14' in scene.mermaid, scene.filename))
        return ValidationReport(tuple(rules))

    def validate_sources(self, expected, actual, adapter, current_adapter, requirement_hash, requirements):
        return ValidationReport((RuleResult("sources.fingerprint", expected == actual, "raw source fingerprint"),
            RuleResult("sources.adapter", adapter == current_adapter, "adapter implementation and grammar versions"),
            RuleResult("sources.requirement", requirement_hash == (digest(requirements) if requirements else ""), "offline bound snapshot; no implicit network refresh")))
