"""Static graph behavior, including call instances and loop transfer paths."""
from dataclasses import replace

import pytest

from toolkit.sequence_diagram_generator.models import FlowModel
from toolkit.sequence_diagram_generator.control_flow import terminal_id
from toolkit.sequence_diagram_generator.validation import FlowValidator
from test_boundaries import analyze
from test_adapters import FIXTURES


@pytest.mark.parametrize("language", FIXTURES)
def test_actual_all_language_flows_freeze_non_placeholder_edges(language):
    scope = analyze(language, FIXTURES[language][1])
    assert scope.control_flow
    assert FlowValidator().validate_model(FlowModel((scope,), "", "")).passed
    for control in scope.controls:
        assert control.predecessors and control.successors
        assert control.predecessors != (control.parent_id,)


def test_callee_return_resumes_its_exact_call_instance():
    scope = analyze("python", "def helper(): return True\ndef flow():\n helper()\n helper()\n return False\n")
    child_returns = [step for step in scope.steps if step.kind == "return" and step.context_id != scope.contexts[0].context_id]
    assert len(child_returns) == 2
    edges = {edge.source_id: edge for edge in scope.control_flow if edge.kind == "resume"}
    targets = [edges[step.step_id].target_id for step in child_returns]
    assert len(set(targets)) == 2
    for step in child_returns:
        ctx = next(ctx for ctx in scope.contexts if ctx.context_id == step.context_id)
        resumed = next(item for item in scope.steps if item.step_id == edges[step.step_id].target_id)
        assert resumed.kind == "call_return" and resumed.dependencies == (ctx.call_site_id,)


def test_loop_break_bypasses_else_and_continue_returns_to_condition():
    scope = analyze("python", "def flow(items):\n for x in items:\n  if x: break\n  else: continue\n else: print('exhausted')\n print('after')\n")
    loop = next(control for control in scope.controls if control.kind == "loop")
    transfer = {edge.kind: edge for edge in scope.control_flow if edge.kind in {"break", "continue"}}
    assert transfer["continue"].target_id == loop.control_id
    assert transfer["break"].target_id == loop.exit_ids[-1]
    assert any(edge.kind == "enter" and edge.source_id == loop.exit_ids[-1] and edge.target_id == loop.merge_id for edge in scope.control_flow)


def test_return_has_no_edge_to_later_business_step():
    scope = analyze("python", "def flow(x):\n if x: return True\n print('only other path')\n return False\n")
    returned = next(step for step in scope.steps if step.kind == "return" and "True" in step.label)
    assert [edge.target_id for edge in scope.control_flow if edge.source_id == returned.step_id] == [terminal_id(returned.context_id)]
    damaged = replace(scope, control_flow=scope.control_flow[1:])
    assert not FlowValidator().validate_model(FlowModel((damaged,), "", "")).passed
    control = scope.controls[0]
    assert not FlowValidator().validate_model(FlowModel((replace(scope, controls=(replace(control, predecessors=(control.parent_id,)),)),), "", "")).passed


@pytest.mark.parametrize("language,source", [
    ("java", "class App { static void flow(int x){switch(x){case 1: System.out.println(1);break;default:System.out.println(2);}System.out.println(3);} }"),
    ("javascript", "function flow(x){switch(x){case 1: console.log(1);break;default:console.log(2)}console.log(3)}"),
    ("go", "package main\nfunc flow(x int){switch x {case 1:println(1);break;default:println(2)};println(3)}"),
])
def test_switch_break_targets_switch_merge_not_enclosing_loop(language, source):
    scope = analyze(language, source)
    switch = next(control for control in scope.controls if control.transfer_boundary == "switch")
    edges = [edge for edge in scope.control_flow if edge.kind == "break"]
    assert edges and all(edge.target_id == switch.merge_id for edge in edges)
    assert not any(gap.reason_code == "CONTROL_FLOW_TRANSFER" for gap in scope.gaps)


def test_go_all_switch_breaks_keep_following_business_action():
    scope = analyze("go", "package main\nfunc flow(x int){switch x {case 1:break;default:break};println(3)}")
    assert any(step.kind == "call" and step.label == "println" for step in scope.steps)
    switch = scope.controls[0]
    assert any(edge.source_id == switch.merge_id and edge.target_id in {s.step_id for s in scope.steps if s.kind == "call"} for edge in scope.control_flow)
