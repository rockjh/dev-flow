"""Pure graph construction for the evidenced structured static scope.

Virtual entry, exit and merge IDs represent relationships, not extra business
steps. Unsupported exception/scheduling semantics remain adapter gaps.
"""
from .models import CallContext, ControlFlowEdge, ControlNode, FlowStep, SequenceBlock
from .repository import stable_id


def terminal_id(context_id: str, exceptional: bool = False) -> str:
    return stable_id("G", context_id, "exception" if exceptional else "return")


def build_control_flow(tree: SequenceBlock, steps: tuple[FlowStep, ...],
                       controls: tuple[ControlNode, ...], contexts: tuple[CallContext, ...]) -> tuple[ControlFlowEdge, ...]:
    by_step = {step.step_id: step for step in steps}
    by_control = {control.control_id: control for control in controls}
    resumed = {context.context_id: step.step_id for context in contexts for step in steps
               if step.kind == "call_return" and context.call_site_id in step.dependencies}
    edges = set()

    def edge(source, target, kind, context, evidence=()):
        edges.add(ControlFlowEdge(source, target, kind, context, tuple(evidence)))

    def sequence(items, following, context, loops=(), tail_kind="next"):
        entry, relation = following, tail_kind
        for item in reversed(items):
            if isinstance(item, SequenceBlock):
                if item.kind == "sequence":
                    entry = sequence(tuple(value for arm in item.arms for value in arm.items), entry, context, loops, relation)
                    relation = "next"
                    continue
                control = by_control[item.block_id]
                own = control.context_id
                edge(control.merge_id, entry, relation, own, control.evidence_ids)
                if item.kind == "opt":
                    edge(control.control_id, control.merge_id, "skip", own, control.evidence_ids)
                break_exit = next((arm.exit_id for arm in item.arms[1:] if "break" in arm.label.lower()), control.merge_id)
                for index, arm in enumerate(item.arms):
                    iteration = item.kind == "loop" and index == 0
                    branch_loops = (*loops, (own, break_exit, control.control_id)) if iteration else loops
                    if control.transfer_boundary == "switch":
                        branch_loops = (*branch_loops, (own, control.merge_id, ""))
                    branch_end = control.control_id if iteration else control.merge_id
                    first = sequence(arm.items, branch_end, own, branch_loops,
                                     "loopback" if iteration else "join" if item.kind == "par" else "merge")
                    edge(control.control_id, arm.exit_id, "fork" if item.kind == "par" else "arm", own, control.evidence_ids)
                    edge(arm.exit_id, first, "enter", own, control.evidence_ids)
                entry, relation = control.control_id, "next"
                continue
            step = by_step[item.step_id]
            own = step.context_id
            if step.kind == "return":
                destination = resumed.get(own, terminal_id(own))
                kind = "resume" if own in resumed else "return"
            elif step.kind in {"raise", "throw", "panic"}:
                destination, kind = terminal_id(own, True), "exception"
            elif step.kind in {"break", "continue"}:
                binding = next((loop for loop in reversed(loops) if loop[0] == own and (step.kind == "break" or loop[2])), None)
                if binding is None:
                    raise ValueError("loop transfer has no enclosing loop in its call context")
                destination, kind = binding[1 if step.kind == "break" else 2], step.kind
            else:
                destination, kind = entry, relation
            edge(step.step_id, destination, kind, own, step.evidence_ids)
            entry, relation = step.step_id, "next"
        return entry

    if not contexts:
        raise ValueError("static graph requires a root call context")
    root = contexts[0].context_id
    first = sequence(tuple(value for arm in tree.arms for value in arm.items), terminal_id(root), root)
    edge(stable_id("G", root, "entry"), first, "entry", root)
    return tuple(sorted(edges, key=lambda item: (item.source_id, item.target_id, item.kind, item.context_id, item.evidence_ids)))
