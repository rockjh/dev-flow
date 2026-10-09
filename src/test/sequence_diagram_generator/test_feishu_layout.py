"""Local native layout tests. These are not online publishing evidence."""
from toolkit.sequence_diagram_generator.feishu import FeishuLayoutBuilder
from toolkit.sequence_diagram_generator.models import FlowModel, ReferenceBundle, SemanticAnnotations
from test_boundaries import analyze


def test_inline_return_joins_back_to_caller_in_correct_lane():
    scope = analyze("python", "def eligible(x):\n if x: return True\n return False\ndef flow(x):\n if eligible(x): return True\n return False\n")
    reference = ReferenceBundle("synthetic-local-layout", "", "", "", "", "", "test-only")
    board = FeishuLayoutBuilder().build(FlowModel((scope,), "", ""), reference, SemanticAnnotations((), (), (), (), ()), "accepted-test").scenes[0]
    nodes = {node.node_id: node for node in board.nodes}
    by_step = {step.step_id: step for step in scope.steps}
    returned = next(step for step in scope.steps if step.kind == "call_return")
    incoming = [c for c in board.connectors if c.end_id == returned.step_id]
    assert len(incoming) == 2
    assert all(by_step[c.start_id].kind == "return" and by_step[c.start_id].context_id != scope.contexts[0].context_id for c in incoming)
    assert all(n.text != "控制合流" for n in board.nodes)
    callee_condition = next(c for c in scope.controls if c.context_id != scope.contexts[0].context_id)
    assert nodes[callee_condition.control_id].x != nodes[returned.step_id].x


def test_layout_keeps_every_control_exit_and_source_step():
    scope = analyze("javascript", "function flow(x){if(x){console.log(1)}else{console.log(2)}return x}")
    reference = ReferenceBundle("synthetic-local-layout", "", "", "", "", "", "test-only")
    builder = FeishuLayoutBuilder()
    scene = builder.build(FlowModel((scope,), "", ""), reference, SemanticAnnotations((), (), (), (), ()), "accepted-test").scenes[0]
    expected = {s.step_id for s in scope.steps} | {c.control_id for c in scope.controls} | {e for c in scope.controls for e in c.exit_ids}
    assert expected <= {p.target_id for p in scene.positions}
    dsl = builder.dsl(scene)
    assert all(n["connector"]["lineShape"] == "polyline" and n["connector"]["endArrow"] == "arrow" for n in dsl["nodes"] if n["type"] == "connector")
