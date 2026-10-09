"""Private evidence/sequence primitives shared by the concrete adapters.

Language binding and execution order remain in each adapter; this module never
interprets syntax or resolves a method by its name alone.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from ...core.redaction import redact
from ..models import (CallContext, ControlNode, CoverageGap, Evidence, ExternalOperation, FlowStep,
                      ScopeAnalysis, SequenceArm, SequenceBlock, SequenceStep, SourceOrder)
from ..repository import digest, stable_id
from ..control_flow import build_control_flow


class _Analysis:
    def __init__(self, scope):
        self.scope = scope
        self.symbols = [scope.symbol]
        self.evidence = []
        self.contexts = []
        self.controls = []
        self.steps = []
        self.external = []
        self.gaps = []
        self.counts = Counter()
        self.context = self.new_context(scope.symbol.symbol_id, (), False)
        self.symbol = scope.symbol
        self.exit_id = ""
        self.parent = ""

    def new_context(self, site, path, recursive):
        context = CallContext(stable_id("C", self.scope.entry_id, path, site), site, tuple(path) + (site,), recursive)
        self.contexts.append(context)
        return context

    def identifier(self, prefix, normalized):
        key = (prefix, self.context.context_id, normalized)
        index = self.counts[key]
        self.counts[key] += 1
        return stable_id(prefix, self.scope.entry_id, self.symbol.path, self.symbol.qualified_name,
                         self.symbol.signature, self.context.context_id, normalized, index)

    def proof(self, normalized, line, end_line, text):
        evidence = Evidence(self.identifier("E", normalized), "code", self.symbol.path,
                            f"line:{line}-{end_line}", digest(normalized), self.symbol.symbol_id,
                            "selected static scope", redact(text))
        self.evidence.append(evidence)
        if "[REDACTED]" in evidence.text:
            self.gap("REDACTION_SEMANTIC_LOSS", line, "required source evidence contains redacted business semantics")
        return evidence

    def step(self, kind, label, evidence, receiver=None, completion="not_observed", dependencies=()):
        step = FlowStep(self.identifier("S", (kind, label, evidence.digest)), self.context.context_id, kind,
                        self.symbol.qualified_name, receiver or self.symbol.qualified_name, redact(label),
                        self.exit_id, (evidence.evidence_id,), tuple(dependencies), completion)
        self.steps.append(step)
        return SequenceStep(step.step_id)

    def gap(self, reason, line, basis, critical=True):
        self.gaps.append(CoverageGap(reason, self.symbol.path, f"line:{line}", self.scope.entry_id,
                                     (self.exit_id,) if self.exit_id else (), critical, redact(basis)))

    def block(self, kind, label, arms, evidence, termination="", transfer_boundary=""):
        identifier = self.identifier("B", (kind, label, evidence.digest))
        parent, exit_id = self.parent, self.exit_id
        self.parent = identifier
        results = []
        terminated = []
        for index, (arm_label, build) in enumerate(arms):
            self.exit_id = stable_id("B", identifier, "exit", index)
            items, terminal = build()
            results.append(SequenceArm(self.exit_id, redact(arm_label), tuple(items)))
            terminated.append(terminal)
        self.parent, self.exit_id = parent, exit_id
        node = ControlNode(identifier, kind, parent, tuple(arm.exit_id for arm in results), (), (), redact(label),
                           stable_id("B", identifier, "merge"), termination, self.context.context_id, (evidence.evidence_id,),
                           "loop" if kind == "loop" else transfer_boundary)
        self.controls.append(node)
        return SequenceBlock(identifier, kind, redact(label), tuple(results)), bool(terminated) and all(terminated)

    def call(self, label, evidence, target, resolution, build=None, completion="returned", kind="call", side_effect=""):
        call_step = self.step(kind, label, evidence, target, completion="dispatched" if kind == "dispatch" else "not_observed")
        operation = ExternalOperation(stable_id("P" if side_effect.startswith("persistence:") else "O", call_step.step_id), call_step.step_id, target,
                                      (evidence.evidence_id,), resolution, "project declaration" if resolution == "project" else "dependency internals not expanded",
                                      side_effect or ("external operation" if resolution in {"boundary", "unknown"} else "supported syntax only"), completion)
        self.external.append(operation)
        items = [call_step]
        if resolution == "unknown":
            self.gap("UNKNOWN_CALL_TARGET", int(evidence.anchor.split(":")[1].split("-")[0]), label)
        if build is not None:
            saved_context, saved_symbol, saved_parent, saved_exit = self.context, self.symbol, self.parent, self.exit_id
            symbol, visitor = build
            recursive = symbol.symbol_id in tuple(context.call_site_id for context in self.contexts if context.context_id == saved_context.context_id)
            # The active declaration stack is explicit, rather than inferred from bare names.
            declaration_path = getattr(self, "declaration_path", (self.scope.symbol.symbol_id,))
            recursive = symbol.symbol_id in declaration_path
            self.context = self.new_context(call_step.step_id, saved_context.path, recursive)
            self.symbol = symbol
            if symbol not in self.symbols:
                self.symbols.append(symbol)
            if recursive:
                items.append(self.step("recursion_boundary", "recursive call; stack not expanded", evidence, symbol.qualified_name))
            elif len(self.contexts) > 256:
                self.gap("CALL_EXPANSION_LIMIT", symbol.start_line, "256 call contexts; analysis truncated")
            else:
                self.declaration_path = declaration_path + (symbol.symbol_id,)
                nested, _ = visitor()
                nested = self._normalize(nested, self.context.context_id)
                items.extend(nested)
                nested_steps = {step.step_id: step for step in self.steps}
                def exceptional(values):
                    for value in values:
                        if isinstance(value, SequenceStep) and nested_steps[value.step_id].kind in {"raise", "throw", "panic"}:
                            return True
                        if isinstance(value, SequenceBlock) and any(exceptional(arm.items) for arm in value.arms):
                            return True
                    return False
                if exceptional(nested):
                    self.gap("CALL_EXCEPTION_PROPAGATION", symbol.start_line, "callee has exceptional exits; caller continuation is not proven")
                    completion = "not_observed"
                    operation_index = self.external.index(operation)
                    self.external[operation_index] = replace(operation, completion=completion)
                self.declaration_path = declaration_path
            self.context, self.symbol, self.parent, self.exit_id = saved_context, saved_symbol, saved_parent, saved_exit
        if completion == "returned" and kind != "dispatch":
            items.append(self.step("call_return", "call returned (dependency internals unexpanded)" if resolution == "boundary" else "call returned",
                                   evidence, target, completion="observed", dependencies=(call_step.step_id,)))
        return items

    def _normalize(self, items, active_context):
        def ends(values, context):
            for item in values:
                if isinstance(item, SequenceStep):
                    step = next(s for s in self.steps if s.step_id == item.step_id)
                    if step.context_id == context and step.kind in {"return", "raise", "throw", "panic"}:
                        return True
                elif item.kind != "loop" and item.arms and all(ends(arm.items, context) for arm in item.arms):
                    return True
            return False
        def place(values, context, parent="", exit_id=""):
            results = []
            for index, item in enumerate(values):
                if isinstance(item, SequenceStep):
                    for offset, step in enumerate(self.steps):
                        if step.step_id == item.step_id and step.context_id == context:
                            self.steps[offset] = replace(step, control_exit=exit_id)
                    results.append(item)
                    continue
                control = next((c for c in self.controls if c.control_id == item.block_id), None)
                own_context = control.context_id if control else context
                if control and control.parent_id != parent:
                    self.controls[self.controls.index(control)] = replace(control, parent_id=parent)
                arms = tuple(replace(arm, items=tuple(place(arm.items, own_context, item.block_id, arm.exit_id))) for arm in item.arms)
                block = replace(item, arms=arms)
                terminated = [ends(arm.items, own_context) for arm in arms]
                tail = values[index + 1:]
                if block.kind != "loop" and terminated and all(terminated) and tail and own_context == context:
                    self.gap("TERMINATED_CONTROL_CONTINUATION", self.symbol.start_line,
                             "all control arms terminate but a following action was extracted")
                if block.kind == "alt" and not (control and control.transfer_boundary == "switch") and any(terminated) and not all(terminated) and tail:
                    survivors = [i for i, terminal in enumerate(terminated) if not terminal]
                    if len(survivors) == 1 and own_context == context:
                        arm_index = survivors[0]
                        new_arms = list(arms)
                        arm = arms[arm_index]
                        new_arms[arm_index] = replace(arm, items=tuple(place((*arm.items, *tail), context, block.block_id, arm.exit_id)))
                        results.append(replace(block, arms=tuple(new_arms)))
                        return results
                    self.gap("EARLY_EXIT_MERGE", self.symbol.start_line, "multiple surviving arms require a shared continuation graph")
                results.append(block)
            return results
        return place(tuple(items), active_context)

    def finish(self, items):
        items = self._normalize(items, self.context.context_id)
        root = SequenceBlock(stable_id("B", self.scope.entry_id, "sequence"), "sequence", self.scope.symbol.qualified_name,
                             (SequenceArm("", "", tuple(items)),))
        try:
            graph = build_control_flow(root, tuple(self.steps), tuple(self.controls), tuple(self.contexts))
        except ValueError as exc:
            self.gap("CONTROL_FLOW_TRANSFER", self.symbol.start_line, str(exc))
            graph = ()
        self.controls = [replace(control,
            predecessors=tuple(sorted({edge.source_id for edge in graph if edge.target_id == control.control_id})),
            successors=tuple(sorted({edge.target_id for edge in graph if edge.source_id == control.control_id})))
            for control in self.controls]
        ordering = []
        def record(block):
            for arm in block.arms:
                ordering.append(SourceOrder(block.block_id, arm.exit_id, tuple(
                    item.block_id if isinstance(item, SequenceBlock) else item.step_id for item in arm.items), arm.label))
                for item in arm.items:
                    if isinstance(item, SequenceBlock):
                        record(item)
        record(root)
        return ScopeAnalysis(self.scope, tuple(self.symbols), tuple(self.evidence), tuple(self.contexts), tuple(self.controls),
                             tuple(self.steps), tuple(self.external), tuple(self.gaps), root, tuple(ordering), graph)
