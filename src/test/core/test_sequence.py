"""Activation gates shared by all four diagram producers."""
import pytest

from toolkit.core.sequence import Activations, validate_sequence
from toolkit.bru_api_test_generator.parse_openapi import render_case_documentation
from toolkit.sequence_diagram_generator.documents import SequenceRenderer
from toolkit.sequence_diagram_generator.models import FlowStep, SequenceArm, SequenceBlock, SequenceStep


VALID = """sequenceDiagram
autonumber
actor User
participant Service
participant DB
User->>Service: request
activate Service
alt found
Service->>DB: read
activate DB
DB-->>Service: result
deactivate DB
else empty
Note over Service: no record
end
Service-->>User: response
deactivate Service
"""


@pytest.mark.parametrize("diagram", [
    VALID.replace("activate DB\n", "", 1),
    VALID.replace("deactivate DB\n", "", 1),
    VALID.replace("activate Service", "activate User", 1),
    VALID.replace("deactivate Service", "deactivate User", 1),
    VALID.replace("participant DB", "participant Other"),
    VALID.replace("deactivate DB\nelse", "else"),
    VALID.replace("activate Service", "deactivate Service", 1),
    "sequenceDiagram\nautonumber\nactor User\nUser->>User: action",
])
def test_shared_gate_rejects_missing_illegal_and_branch_leaking_activations(diagram):
    assert validate_sequence(diagram)


def test_valid_branches_and_inline_mermaid_activation():
    assert validate_sequence(VALID) == []
    inline = VALID.replace("User->>Service: request\nactivate Service", "User->>+Service: request")
    inline = inline.replace("Service-->>User: response\ndeactivate Service", "Service-->>-User: response")
    assert validate_sequence(inline) == []


def test_same_lifeline_nested_calls_must_return_in_order():
    activations = Activations([], {"Service"})
    activations.open("outer", "Service")
    activations.open("inner", "Service")
    with pytest.raises(ValueError, match="ACTIVATION_RETURN_ORDER_INVALID"):
        activations.close("outer")
    activations.close("inner")
    activations.close("outer")
    assert not activations.active


def test_api_templates_generate_technical_activations_for_each_graph():
    import re
    value = render_case_documentation([{"id": "C1", "endpoint_id": "E1", "flow_required": True}],
                                     [{"id": "E1", "method": "GET", "path": "/items"}])
    diagrams = re.findall(r"```mermaid\n(.*?)```", value, re.S)
    assert len(diagrams) == 2
    assert all(validate_sequence(diagram) == [] for diagram in diagrams)
    assert all("actor C" in diagram and "activate C" not in diagram for diagram in diagrams)


def test_sequence_call_instances_close_inside_each_control_arm():
    steps = {}
    arms = []
    for index in range(2):
        call_id, return_id = f"call{index}", f"return{index}"
        steps[call_id] = FlowStep(call_id, "root", "call", "Service", "DB", "read", "", ("evidence",), receiver_role="database")
        steps[return_id] = FlowStep(return_id, "root", "call_return", "Service", "DB", "result", "", ("evidence",),
                                   (call_id,), "observed", receiver_role="database")
        arms.append(SequenceArm(f"exit{index}", f"condition{index}", (SequenceStep(call_id), SequenceStep(return_id))))
    tree = SequenceBlock("branch", "alt", "condition", tuple(arms))
    diagram, positions = SequenceRenderer()._diagram(tree, steps, {}, "example.md", "implementation", {})
    assert validate_sequence(diagram) == []
    first, second = diagram.split("else condition1")
    assert first.splitlines().count("activate P0") == first.splitlines().count("deactivate P0") == 1
    assert second.splitlines().count("activate P0") == second.splitlines().count("deactivate P0") == 1
    assert {position.target_id for position in positions} >= set(steps)


def test_sequence_proposal_actor_never_activates_and_unobserved_call_does_not_return():
    step = FlowStep("submit", "root", "dispatch", "User", "Queue", "publish", "", ("requirement",),
                    sender_role="actor", receiver_role="middleware")
    tree = SequenceBlock("root", "sequence", "", (SequenceArm("", "", (SequenceStep(step.step_id),)),))
    diagram, _ = SequenceRenderer()._diagram(tree, {step.step_id: step}, {}, "proposal.md", "proposal", {})
    assert validate_sequence(diagram) == []
    assert "actor P1" in diagram and "activate P1" not in diagram
    assert "-->>" not in diagram


def test_domain_document_gates_reject_removed_activations(tmp_path):
    from toolkit.biz_flow_doc_generator.documents import _validate_mermaid
    from toolkit.bru_api_test_generator.check_api_coverage import validate_module_documentation
    from toolkit.e2e_test_generator.document_gate import _parse_mermaid

    diagram = VALID.replace("alt found", "alt 分支1 找到数据").replace("else empty", "else 分支2 无数据")
    diagram = diagram.replace("DB-->>Service: result", "DB-->>Service: 协议成功：落库，未投递消息")
    diagram = diagram.replace("no record", "协议成功：未落库，未投递消息")
    diagram = diagram.replace("response", "协议成功：落库，未投递消息")
    markdown = "```mermaid\n" + diagram + "```"
    path = tmp_path / "CASES.md"
    assert _validate_mermaid(diagram, render=False) == []
    assert _parse_mermaid(markdown, path, "查询", 1) == []
    invalid = diagram.replace("activate DB\n", "", 1)
    assert _validate_mermaid(invalid, render=False)
    assert any("activation" in issue.reason for issue in _parse_mermaid("```mermaid\n" + invalid + "```", path, "查询", 1))
    cases = [{"id": "C1", "endpoint_id": "E1", "flow_required": True}]
    content = "业务范围：查询条目\n\n## 模块内容\n\n## 接口清单\n\n" + render_case_documentation(
        cases, [{"id": "E1", "method": "GET", "path": "/items"}])
    path.write_text(content, encoding="utf-8")
    assert validate_module_documentation(path, cases) == []
    path.write_text(content.replace("activate A\n", "", 1), encoding="utf-8")
    assert any("activation" in error for error in validate_module_documentation(path, cases))


def test_e2e_single_service_has_activation_without_invented_response(tmp_path):
    import re
    from toolkit.e2e_test_generator.materialize import _definition

    _, _, _, content = _definition(tmp_path, {"id": "READ", "participants": ["Service"], "protocol_refs": ["read"]},
                                   {"operations": [{"id": "read", "kind": "http", "method": "GET", "path": "/items"}]}, owner="fixture")
    diagram = re.search(r"```mermaid\n(.*?)```", content, re.S)[1]
    assert validate_sequence(diagram) == []
    assert "-->>" not in diagram
