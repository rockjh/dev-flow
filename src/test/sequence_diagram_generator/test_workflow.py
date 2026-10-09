"""Receipts here are synthetic test inputs, never real host execution evidence."""
import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from toolkit.cli import console_main
from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.cli import build_workflow
from toolkit.sequence_diagram_generator.models import (AcceptRequest, CheckRequest, CollectRequest, DiscoverRequest, HostReceipt,
    HostSubmission, HostTaskResult, InitRequest, PrepareRequest, ProjectContext, Requirement, RequirementInput, ProposedStep,
    SemanticAnnotations, TaskPackage, VerifyRequest)
from toolkit.sequence_diagram_generator.repository import digest, now, stable_id, to_dict
from test_adapters import FIXTURES


@pytest.fixture
def context(tmp_path, monkeypatch):
    root, state = tmp_path / "project", tmp_path / "state"
    root.mkdir()
    monkeypatch.setattr("toolkit.core.artifacts.state_root", lambda: state)
    return ProjectContext(root, root / "docs" / "sequence-diagram", state / "sequence-diagram", digest(str(root)))


def prepare(context, language="python", requirements=None):
    if language:
        name, code = FIXTURES[language]
        (context.project / name).write_text(code, encoding="utf-8")
    flow = build_workflow(context)
    flow.init(InitRequest(context))
    found = flow.discover(DiscoverRequest(context, "requirement" if requirements else "code", "proposal" if requirements else "implementation",
        (), RequirementInput("text", requirements) if requirements else None))
    run_id = found.data["run_id"]
    flow.prepare(PrepareRequest(context, run_id, (), True, True, "serial", "test-session-explicit-serial-approval"))
    return flow, run_id, flow.repository.read_artifact(context, run_id, "task-package.json", TaskPackage)


def submission(package):
    annotations = SemanticAnnotations((), (), (), (), ())
    results = []
    for task in package.tasks:
        if task.segment_ids:
            reqs = tuple(Requirement(stable_id("R", segment.segment_id), (segment.segment_id,), segment.text, "requirement_only",
                                     "not_evaluated", "仅需求方案，本次未评估实现") for segment in package.requirements.segments)
            proposed = tuple(ProposedStep(stable_id("S", r.requirement_id), (r.requirement_id,), "用户", "服务", r.text) for r in reqs)
            annotations = SemanticAnnotations((), reqs, (), proposed, ())
        results.append(HostTaskResult(task.task_id, annotations, (), ("synthetic test receipt",)))
    receipts = tuple(HostReceipt(result.task_id, digest(package), digest(result), "success", "", (), now(), now(), now(),
        package.execution_approval, next(task.scope_ids for task in package.tasks if task.task_id == result.task_id), True, False, 0) for result in results)
    return HostSubmission(package.run_id, digest(package), receipts, tuple(results))


@pytest.mark.parametrize("language", FIXTURES)
def test_local_workflow_all_syntaxes_and_readonly_check(context, language):
    flow, run_id, package = prepare(context, language)
    results = context.project.parent / "result.json"
    results.write_text(json.dumps(to_dict(submission(package)), ensure_ascii=False), encoding="utf-8")
    collected = flow.collect(CollectRequest(context, run_id, results))
    assert collected.data["state"] == "collected"
    before = {p: p.read_bytes() for p in flow.repository.run_path(context, run_id).rglob("*.json")}
    flow.check(CheckRequest(context, run_id))
    assert before == {p: p.read_bytes() for p in flow.repository.run_path(context, run_id).rglob("*.json")}
    verified = flow.verify(VerifyRequest(context, run_id))
    assert verified.data["reproducible"]
    accepted = flow.accept(AcceptRequest(context, run_id))
    assert accepted.data["revision"] == 1
    assert list(context.assets.glob("*.md"))
    assert flow.accept(AcceptRequest(context, run_id)).data["idempotent"]


def test_requirement_only_proposal(context):
    flow, run_id, package = prepare(context, None, "收到订单后通知用户。")
    results = context.project.parent / "result.json"
    results.write_text(json.dumps(to_dict(submission(package)), ensure_ascii=False), encoding="utf-8")
    result = flow.collect(CollectRequest(context, run_id, results))
    assert result.data["implementation_consistency"] == "not_evaluated"
    flow.verify(VerifyRequest(context, run_id))
    flow.accept(AcceptRequest(context, run_id))
    assert "requirement_only" in (context.assets / "proposal.md").read_text(encoding="utf-8")


def test_host_hash_and_native_receipt_not_silently_downgraded(context):
    flow, run_id, package = prepare(context)
    with pytest.raises(DevflowError):
        flow.handoff.validate(package, replace(submission(package), package_hash="foreign"))
    with pytest.raises(DevflowError):
        flow.handoff.validate(replace(package, execution_mode="native"), submission(package))


def test_structured_cli_chinese_dependency_error_keeps_code_and_subcommand():
    stream = io.StringIO()
    with patch("toolkit.sequence_diagram_generator.cli.build_workflow", side_effect=DevflowError("EXTERNAL_UNAVAILABLE", "缺少解析依赖", 6, details_path="existing-manifest.json")), redirect_stdout(stream):
        code = console_main(["sequence-diagram-generator", "verify", "--project", ".", "--run-id", "a" * 32, "--json"])
    value = json.loads(stream.getvalue())
    assert code == 6
    assert value["command"] == "sequence-diagram-generator.verify"
    assert value["error"]["details_path"] == "existing-manifest.json"
