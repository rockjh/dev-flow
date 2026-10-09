"""Transactions, stale baselines and user ownership, without redundant render work."""
from dataclasses import replace
import json

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.models import (AcceptRequest, CollectRequest, CommitJournal, DocumentBundle,
    RenderReport, RunState, VerificationRecord, VerifyRequest)
from toolkit.sequence_diagram_generator.repository import to_dict
from test_workflow import context, prepare, submission


def verified(context):
    flow, run_id, package = prepare(context)
    flow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("transaction test does not require renderer",))
    path = context.project.parent / (run_id + ".json")
    path.write_text(json.dumps(to_dict(submission(package))), encoding="utf-8")
    flow.collect(CollectRequest(context, run_id, path))
    flow.verify(VerifyRequest(context, run_id))
    return flow, run_id


def test_only_one_run_can_advance_parent_baseline(context):
    first, run_a = verified(context)
    second, run_b = verified(context)
    first.accept(AcceptRequest(context, run_a))
    with pytest.raises(DevflowError, match="baseline advanced"):
        second.accept(AcceptRequest(context, run_b))
    assert second.repository.load(context, run_b).state == RunState.VERIFIED
    assert second.committer.baseline(context).revision == 1


def test_unowned_user_document_is_preserved(context):
    flow, run_id = verified(context)
    user = context.assets / "matrix.md"
    user.write_text("my own notes", encoding="utf-8")
    with pytest.raises(DevflowError, match="user file"):
        flow.accept(AcceptRequest(context, run_id))
    assert user.read_text(encoding="utf-8") == "my own notes"
    assert flow.committer.baseline(context).revision == 0


@pytest.mark.parametrize("phase", ["prepared", "files_written", "baseline_written", "finalized"])
def test_each_journal_phase_recovers_by_explicit_retry(context, monkeypatch, phase):
    flow, run_id = verified(context)
    original = flow.committer._save_journal
    interrupted = False
    def crash(context, journal):
        nonlocal interrupted
        original(context, journal)
        if journal.phase == phase and not interrupted:
            interrupted = True
            raise OSError("injected interruption after journal write")
    monkeypatch.setattr(flow.committer, "_save_journal", crash)
    with pytest.raises((DevflowError, OSError)):
        flow.accept(AcceptRequest(context, run_id))
    assert flow.repository.load(context, run_id).state == RunState.VERIFIED
    monkeypatch.setattr(flow.committer, "_save_journal", original)
    flow.accept(AcceptRequest(context, run_id))
    assert flow.repository.load(context, run_id).state == RunState.ACCEPTED
    assert flow.committer.baseline(context).revision == 1


def test_recovery_refuses_tampered_plan(context):
    flow, run_id = verified(context)
    manifest = flow.repository.load(context, run_id)
    bundle = flow.repository.read_artifact(context, run_id, "document-bundle.json", DocumentBundle)
    verification = flow.repository.read_artifact(context, run_id, "verification.json", VerificationRecord)
    plan = flow.committer.plan(context, manifest, bundle, verification, flow.committer.baseline(context))
    changed = replace(plan, files=(replace(plan.files[0], content="forged"), *plan.files[1:]))
    with pytest.raises(DevflowError, match="frozen verified"):
        flow.committer.validate_journal(context, manifest, bundle, verification, CommitJournal("prepared", changed, (), False))


@pytest.mark.parametrize("phase", ["files_written", "baseline_written"])
def test_crash_after_replace_before_journal_update_recovers(context, monkeypatch, phase):
    flow, run_id = verified(context)
    original = flow.committer._save_journal
    interrupted = False
    def crash(context, journal):
        nonlocal interrupted
        if journal.phase == phase and not interrupted:
            interrupted = True
            raise OSError("replace completed but journal update did not")
        original(context, journal)
    monkeypatch.setattr(flow.committer, "_save_journal", crash)
    with pytest.raises(DevflowError):
        flow.accept(AcceptRequest(context, run_id))
    assert flow.repository.load(context, run_id).state == RunState.VERIFIED
    monkeypatch.setattr(flow.committer, "_save_journal", original)
    flow.accept(AcceptRequest(context, run_id))
    assert flow.committer.baseline(context).revision == 1
    assert flow.repository.load(context, run_id).state == RunState.ACCEPTED


def test_manual_change_during_interrupted_commit_blocks_recovery(context, monkeypatch):
    flow, run_id = verified(context)
    original = flow.committer._save_journal
    def crash(context, journal):
        original(context, journal)
        if journal.phase == "files_written":
            raise OSError("interrupted")
    monkeypatch.setattr(flow.committer, "_save_journal", crash)
    with pytest.raises(DevflowError):
        flow.accept(AcceptRequest(context, run_id))
    journal = flow.repository.read_artifact(context, run_id, "commit_journal.json", CommitJournal)
    changed = context.project / journal.files_written[0]
    changed.write_text("manual edit", encoding="utf-8")
    monkeypatch.setattr(flow.committer, "_save_journal", original)
    with pytest.raises(DevflowError, match="manual changes"):
        flow.accept(AcceptRequest(context, run_id))
    assert changed.read_text(encoding="utf-8") == "manual edit"


def test_malformed_collect_records_failure(context):
    flow, run_id, _ = prepare(context)
    path = context.project.parent / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(DevflowError):
        flow.collect(CollectRequest(context, run_id, path))
    assert flow.repository.load(context, run_id).state == RunState.FAILED
