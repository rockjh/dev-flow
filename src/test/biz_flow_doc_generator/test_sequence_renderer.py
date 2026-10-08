"""业务图必须保留入口及辅助调用的真实顺序与分支范围。"""
from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.biz_flow_doc_generator.documents import _diagram, _branch_matrix, _validate_mermaid, _review_dict, _review_from_dict
from toolkit.biz_flow_doc_generator.models import EntryPoint, EntryReview, FlowStep
from toolkit.biz_flow_doc_generator.validation import validate_branch_coverage, validate_persistence_coverage


def entry(steps, branches=(), persistence=()):
    value = EntryPoint("e", "url", "POST /login", "oauth2_login", "app.py", 99, "用户认证", "app.py", caller="登录客户端", business_name="授权登录")
    value.review = EntryReview("e", "登录请求", "授权登录", "授权信息", "登录成功", "返回错误", steps, "confirmed", "agent:codex")
    value.agent_branches = list(branches)
    value.agent_persistence = list(persistence)
    return value


def branch(identifier, line, label, outcomes):
    return {"branch_id": identifier, "source_file": "app.py", "source_line": line,
            "condition": label, "label": label, "outcomes": outcomes, "outcome_labels": outcomes,
            "business_relevant": True, "reachability": "reachable", "effects": []}


def success(line=120):
    return FlowStep("action", "登录成功", f"app.py:{line}", "登录客户端", sender="用户认证", response=True)


def test_nested_helper_control_preserves_call_order_and_outcome_scope():
    branches = [branch("B-entry", 101, "校验状态", ["状态有效", "状态无效"]),
                branch("B-helper", 42, "校验回调", ["回调有效", "回调无效"])]
    steps = [FlowStep("action", "接收授权请求", "app.py:99", "用户认证"),
             FlowStep("alt", "校验状态", "app.py:101", "用户认证", branch_ids=["B-entry"]),
             FlowStep("action", "状态有效", "app.py:107", "用户认证"),
             FlowStep("alt", "校验回调", "app.py:42", "用户认证", branch_ids=["B-helper"]),
             FlowStep("action", "回调有效", "app.py:44", "用户认证"),
             FlowStep("else", "回调无效", "app.py:43", "用户认证"),
             FlowStep("action", "返回回调错误", "app.py:43", "登录客户端", response=True),
             FlowStep("end", "结束回调校验", "app.py:44", "用户认证"),
             FlowStep("else", "状态无效", "app.py:102", "用户认证"),
             FlowStep("action", "返回状态错误", "app.py:102", "登录客户端", response=True),
             FlowStep("end", "结束状态校验", "app.py:108", "用户认证"), success()]
    value = entry(steps, branches)
    diagram = _diagram(value)
    assert diagram.index("接收授权请求") < diagram.index("alt 校验状态") < diagram.index("alt 校验回调")
    assert "进入 oauth2_login" not in diagram
    assert "alt B-" not in diagram and "else B-" not in diagram
    assert _validate_mermaid(diagram.removeprefix("```mermaid\n").removesuffix("\n```")) == []
    assert validate_branch_coverage({"branches": branches}, diagram + "\n" + _branch_matrix(value)) == []


def test_persistence_is_rendered_inside_its_actual_branch_and_external_parties_are_preserved():
    persistence = [{"persistence_id": "P-account", "resource_name": "accounts", "display_name": "账户表",
                    "operation_label": "保存账户", "operation": "insert", "fields": [],
                    "source_file": "app.py", "source_line": 37}]
    branches = [branch("B-save", 35, "账户不存在", ["新增账户", "复用账户"])]
    steps = [FlowStep("action", "查询授权信息", "app.py:110", "授权服务"),
             FlowStep("action", "返回授权信息", "app.py:110", "用户认证", sender="授权服务", response=True),
             FlowStep("alt", "账户不存在", "app.py:35", "用户认证", branch_ids=["B-save"]),
             FlowStep("action", "新增账户并保存账户", "app.py:37", "用户认证", persistence_ids=["P-account"]),
             FlowStep("else", "复用账户", "app.py:38", "用户认证"),
             FlowStep("end", "账户就绪", "app.py:39", "用户认证"), success()]
    value = entry(steps, branches, persistence)
    diagram = _diagram(value)
    assert "participant P3 as 授权服务" in diagram
    assert "P1->>P3: 查询授权信息" in diagram
    assert "P3-->>P1: 返回授权信息" in diagram
    assert diagram.index("alt 账户不存在") < diagram.index('%% devflow:persistence id="P-account"') < diagram.index("else 复用账户")
    assert validate_persistence_coverage({"persistence_actions": persistence}, diagram + "\n" + _branch_matrix(value)) == []


def test_unplaced_helper_branch_fails_instead_of_appending_inventory():
    value = entry([FlowStep("action", "接收请求", "app.py:99", "用户认证"), success()],
                  [branch("B-helper", 42, "校验回调", ["有效", "无效"])])
    with pytest.raises(ValueError, match="FLOW_EVIDENCE_UNPLACED.*B-helper"):
        _diagram(value)


def test_unplaced_persistence_and_wrong_source_bindings_fail():
    action = {"persistence_id": "P-account", "resource_name": "accounts", "display_name": "账户表",
              "operation_label": "保存账户", "source_file": "app.py", "source_line": 37}
    with pytest.raises(ValueError, match="FLOW_EVIDENCE_UNPLACED.*P-account"):
        _diagram(entry([success()], persistence=[action]))
    with pytest.raises(ValueError, match="FLOW_PERSISTENCE_BINDING_INVALID"):
        _diagram(entry([FlowStep("action", "保存账户", "app.py:38", "用户认证", persistence_ids=["P-account"]), success()], persistence=[action]))


@pytest.mark.parametrize("steps", [
    [FlowStep("else", "无效", "app.py:1"), success()],
    [FlowStep("alt", "有效", "app.py:1"), success()],
    [FlowStep("end", "结束", "app.py:1"), success()],
])
def test_malformed_review_control_structure_fails(steps):
    with pytest.raises(ValueError, match="FLOW_CONTROL_INVALID"):
        _diagram(entry(steps))


def test_multioutcome_decision_cannot_be_hidden_in_plain_action():
    value = entry([FlowStep("action", "校验状态", "app.py:101", "用户认证", branch_ids=["B-entry"]), success()],
                  [branch("B-entry", 101, "校验状态", ["有效", "无效"])])
    with pytest.raises(ValueError, match="FLOW_BRANCH_CONTROL_MISSING"):
        _diagram(value)


def test_actual_response_stays_inside_failure_branch_and_no_blanket_success_is_added():
    branches = [branch("B-fail", 91, "返回账号错误", ["返回账号错误"])]
    value = entry([FlowStep("alt", "账号不存在", "app.py:90", "用户认证"),
                   FlowStep("action", "返回账号错误", "app.py:91", "登录客户端", branch_ids=["B-fail"], response=True),
                   FlowStep("end", "结束请求", "app.py:94", "用户认证")], branches)
    diagram = _diagram(value)
    assert diagram.index("P1-->>P0: 返回账号错误") < diagram.index("\nend")
    assert "登录成功" not in diagram


def test_optional_step_bindings_survive_review_roundtrip():
    value = entry([FlowStep("action", "返回结果", "app.py:91", "登录客户端", ["B-fail"], ["P-account"], "用户认证", True)])
    restored = _review_from_dict(_review_dict(value.review), value)
    assert restored.steps == value.review.steps


def test_agent_requires_source_positioned_caller_response():
    with pytest.raises(ValueError, match="FLOW_RESPONSE_UNPLACED"):
        _diagram(entry([FlowStep("action", "处理登录", "app.py:99", "用户认证")]))


def test_markdown_gate_rejects_reordered_messages_even_when_all_labels_remain(tmp_path: Path):
    from toolkit.biz_flow_doc_generator.documents import _entry_text, _markdown_coverage
    from toolkit.biz_flow_doc_generator.models import GitInfo, ScanResult

    value = entry([FlowStep("action", "校验入口状态", "app.py:101", "用户认证"),
                   FlowStep("action", "兑换授权信息", "app.py:42", "用户认证"), success()])
    scan = ScanResult(tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False),
                      ["Python"], [], [value], ["app.py"], [], "source")
    index = {"modules": [{"name": "用户认证", "file": "00-用户认证.md"}],
             "entries": [{"id": "e", "module": "用户认证", "source": "app.py:99", "identifier": "POST /login",
                          "review": _review_dict(value.review), "errors": [], "error_codes": []}]}
    path = tmp_path / "00-用户认证.md"
    text = "# 用户认证\n\n" + _entry_text(value)
    path.write_text(text, encoding="utf-8")
    assert _markdown_coverage(scan, index, tmp_path)["markdown_diagram_mismatches"] == []
    path.write_text(text.replace("P1->>P1: 校验入口状态\nP1->>P1: 兑换授权信息",
                                 "P1->>P1: 兑换授权信息\nP1->>P1: 校验入口状态"), encoding="utf-8")
    assert "e:mermaid:review-execution-order" in _markdown_coverage(scan, index, tmp_path)["markdown_diagram_mismatches"]


def test_explicit_agent_binding_does_not_claim_prior_action_at_same_source():
    branches = [branch("B-password", 92, "密码匹配", ["密码有效", "密码无效"])]
    persistence = [{"persistence_id": "P-session", "resource_name": "sessions", "display_name": "会话表",
                    "operation_label": "保存会话", "operation": "insert", "fields": [],
                    "source_file": "app.py", "source_line": 94}]
    steps = [FlowStep("action", "计算密码校验结果", "app.py:92", "用户认证"),
             FlowStep("alt", "密码匹配", "app.py:92", "用户认证", branch_ids=["B-password"]),
             FlowStep("action", "密码有效并准备会话", "app.py:94", "用户认证"),
             FlowStep("action", "保存会话", "app.py:94", "用户认证", persistence_ids=["P-session"]),
             FlowStep("else", "密码无效", "app.py:93", "用户认证"),
             FlowStep("action", "返回密码错误", "app.py:93", "登录客户端", response=True),
             FlowStep("end", "校验结束", "app.py:95", "用户认证"), success()]
    value = entry(steps, branches, persistence)
    diagram = _diagram(value)
    assert diagram.index("计算密码校验结果") < diagram.index('%% devflow:branch id="B-password"')
    assert diagram.index("密码有效并准备会话") < diagram.index('%% devflow:persistence id="P-session"')
    assert validate_branch_coverage({"branches": branches}, diagram + "\n" + _branch_matrix(value)) == []
    assert validate_persistence_coverage({"persistence_actions": persistence}, diagram + "\n" + _branch_matrix(value)) == []


def test_explicit_initial_caller_request_is_rendered_once_for_agent_and_legacy_is_preserved():
    value = entry([FlowStep("action", "提交授权登录请求", "app.py:99", "用户认证", sender="登录客户端"), success()])
    diagram = _diagram(value)
    assert diagram.count("P0->>P1:") == 1
    assert "P0->>P1: 提交授权登录请求" in diagram
    assert "P0->>P1: 授权登录" not in diagram
    value.review.confirmed_by = "human"
    assert _diagram(value).count("P0->>P1:") == 2
