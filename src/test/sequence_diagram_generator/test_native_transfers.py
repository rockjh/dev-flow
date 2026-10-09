"""Native business connectors preserve the same frozen transfer graph."""
from toolkit.sequence_diagram_generator.feishu import FeishuLayoutBuilder
from toolkit.sequence_diagram_generator.models import FlowModel, ReferenceBundle, SemanticAnnotations
from test_boundaries import analyze


def test_native_loop_break_and_continue_follow_frozen_targets():
    scope = analyze("python", "def flow(xs):\n for x in xs:\n  if x: break\n  continue\n else:\n  print('normal exit')\n return True\n")
    scene = FeishuLayoutBuilder().build(FlowModel((scope,), "", ""), ReferenceBundle("builtin", "", "", "", "", "", "test"),
                                       SemanticAnnotations((), (), (), (), ()), "test").scenes[0]
    pairs = {(c.start_id, c.end_id) for c in scene.connectors}
    for step in scope.steps:
        if step.kind in {"break", "continue"}:
            expected = next(e.target_id for e in scope.control_flow if e.source_id == step.step_id)
            assert (step.step_id, expected) in pairs
            assert len([c for c in scene.connectors if c.start_id == step.step_id]) == 1


def test_native_callee_early_return_resumes_exact_call_instance():
    scope = analyze("python", "def helper(x):\n if x: return True\n return False\ndef flow(x):\n helper(x)\n helper(False)\n return True\n")
    scene = FeishuLayoutBuilder().build(FlowModel((scope,), "", ""), ReferenceBundle("builtin", "", "", "", "", "", "test"),
                                       SemanticAnnotations((), (), (), (), ()), "test").scenes[0]
    pairs = {(c.start_id, c.end_id) for c in scene.connectors}
    resumes = [e for e in scope.control_flow if e.kind == "resume"]
    assert len({e.target_id for e in resumes}) == 2
    assert all((e.source_id, e.target_id) in pairs for e in resumes)
    positions = {p.target_id: p for p in scene.positions}
    assert all(positions[o.operation_id].tree_path == o.call_site_id for o in scope.external)
