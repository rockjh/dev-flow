"""Synthetic receipt behavior tests, never evidence of an online publication."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from toolkit.core.errors import DevflowError
from toolkit.sequence_diagram_generator.cli import build_workflow
from toolkit.sequence_diagram_generator.models import (AcceptRequest, CollectRequest, DiscoverRequest, InitRequest, PrepareRequest,
    PublishRequest, PublicationManifest, RenderReport, TaskPackage, VerifyRequest)
from toolkit.sequence_diagram_generator.repository import to_dict
from test_native_structure import native
from test_workflow import context, submission


@pytest.fixture
def publication(context, native):
    (context.project / "app.py").write_text("def flow(x):\n if x: return True\n return False\n", encoding="utf-8")
    workflow = build_workflow(context)
    workflow.renderer.render = lambda *args: RenderReport("not_run", "", "", (), ("synthetic publication protocol test",))
    workflow.init(InitRequest(context))
    run = workflow.discover(DiscoverRequest(context, "code", "implementation")).data["run_id"]
    workflow.prepare(PrepareRequest(context, run, (), True, True, "serial", "synthetic-test-approval"))
    package = workflow.repository.read_artifact(context, run, "task-package.json", TaskPackage)
    results = context.project.parent / "synthetic-host.json"
    results.write_text(json.dumps(to_dict(submission(package))), encoding="utf-8")
    workflow.collect(CollectRequest(context, run, results))
    workflow.verify(VerifyRequest(context, run))
    workflow.accept(AcceptRequest(context, run))
    workflow.publish(PublishRequest(context, run, "prepare", "synthetic-target", "synthetic-new-board", "synthetic-test-approval"))
    manifest = workflow.repository.read_artifact(context, run, "publication/manifest.json", PublicationManifest)
    receipt = replace(native[3], publication_id=manifest.publication_id, accepted_digest=manifest.accepted_digest,
                      target=manifest.target, write_scope=manifest.write_scope, execution_approval=manifest.execution_approval,
                      layout_digest=manifest.layout_digest)
    path = Path(receipt.exports[0].remote_native_path).parent / "synthetic-receipt.json"
    return workflow, run, manifest, receipt, path


def collect(context, publication, receipt):
    workflow, run, _, _, path = publication
    path.write_text(json.dumps(to_dict(receipt)), encoding="utf-8")
    return workflow.publish(PublishRequest(context, run, "collect", receipt_path=path))


def test_written_then_verified_is_idempotent_without_advancing_local_baseline(context, publication):
    workflow, run, _, receipt, _ = publication
    result = collect(context, publication, replace(receipt, status="written"))
    assert result.summary == "written" and not result.data["online_verified"]
    result = collect(context, publication, receipt)
    assert result.summary == "verified" and result.data["online_verified"]
    assert collect(context, publication, receipt).summary == "verified"
    assert workflow.publish(PublishRequest(context, run, "check")).summary == "verified"
    assert workflow.committer.baseline(context).revision == 1


def test_failed_visual_review_retains_remote_identity_and_retry_reuses_it(context, publication):
    workflow, run, _, receipt, _ = publication
    failed = replace(receipt, status="failed", exports=(replace(receipt.exports[0], visual_review_passed=False),))
    with pytest.raises(DevflowError):
        collect(context, publication, failed)
    manifest = workflow.repository.read_artifact(context, run, "publication/manifest.json", PublicationManifest)
    assert manifest.state == "failed" and manifest.objects == receipt.objects
    assert workflow.committer.baseline(context).revision == 1
    assert collect(context, publication, receipt).summary == "verified"


def test_retry_cannot_replace_remote_objects_or_bind_wrong_node_ids(context, publication):
    _, _, _, receipt, _ = publication
    collect(context, publication, replace(receipt, status="written"))
    changed = replace(receipt, objects=(replace(receipt.objects[0], board_id="different-board"),))
    with pytest.raises(DevflowError, match="remote object identities"):
        collect(context, publication, changed)
    invalid = replace(receipt, objects=(replace(receipt.objects[0], node_ids=("missing-node",)),))
    with pytest.raises(DevflowError):
        collect(context, publication, invalid)


def test_readonly_check_detects_changed_saved_export(context, publication):
    workflow, run, _, receipt, _ = publication
    collect(context, publication, receipt)
    Path(receipt.exports[0].remote_native_path).write_text("{}", encoding="utf-8")
    before = workflow.repository.artifact_path(context, run, "publication/manifest.json").read_bytes()
    with pytest.raises(DevflowError):
        workflow.publish(PublishRequest(context, run, "check"))
    assert workflow.repository.artifact_path(context, run, "publication/manifest.json").read_bytes() == before


def next_accepted(context, workflow, changed=True):
    if changed:
        with (context.project / "app.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# synthetic second source revision\n")
    run = workflow.discover(DiscoverRequest(context, "code", "implementation")).data["run_id"]
    workflow.prepare(PrepareRequest(context, run, (), True, True, "serial", "synthetic-test-approval"))
    package = workflow.repository.read_artifact(context, run, "task-package.json", TaskPackage)
    results = context.project.parent / "synthetic-next-host.json"
    results.write_text(json.dumps(to_dict(submission(package))), encoding="utf-8")
    workflow.collect(CollectRequest(context, run, results))
    workflow.verify(VerifyRequest(context, run))
    workflow.accept(AcceptRequest(context, run))
    return run


def test_next_revision_binds_parent_remote_precondition_and_board_ownership(context, publication):
    workflow, _, parent, receipt, path = publication
    collect(context, publication, receipt)
    run = next_accepted(context, workflow)
    workflow.publish(PublishRequest(context, run, "prepare", receipt.target, receipt.write_scope, receipt.execution_approval))
    manifest = workflow.repository.read_artifact(context, run, "publication/manifest.json", PublicationManifest)
    assert manifest.parent_publication_id == parent.publication_id
    assert manifest.expected_remote_digest == receipt.remote_after_digest
    assert manifest.owned_objects == receipt.objects
    current = replace(receipt, publication_id=manifest.publication_id, accepted_digest=manifest.accepted_digest,
                      layout_digest=manifest.layout_digest, remote_precondition_digest=manifest.expected_remote_digest)
    for damaged in (replace(current, remote_precondition_digest="synthetic-user-edit"),
                    replace(current, objects=(replace(current.objects[0], board_id="synthetic-unowned-board"),))):
        path.write_text(json.dumps(to_dict(damaged)), encoding="utf-8")
        with pytest.raises(DevflowError):
            workflow.publish(PublishRequest(context, run, "collect", receipt_path=path))
    path.write_text(json.dumps(to_dict(current)), encoding="utf-8")
    assert workflow.publish(PublishRequest(context, run, "collect", receipt_path=path)).summary == "verified"


def test_same_publication_identity_reuses_verified_objects_without_host_write(context, publication):
    workflow, _, _, receipt, _ = publication
    collect(context, publication, receipt)
    run = next_accepted(context, workflow, changed=False)
    result = workflow.publish(PublishRequest(context, run, "prepare", receipt.target, receipt.write_scope, receipt.execution_approval))
    assert result.summary == "verified" and result.data["reused"]
    assert not workflow.repository.artifact_path(context, run, "publication/host-task.json").exists()
    assert workflow.publish(PublishRequest(context, run, "check")).summary == "verified"


def test_old_run_cannot_collect_after_another_baseline_is_accepted(context, publication):
    workflow, _, _, receipt, _ = publication
    next_accepted(context, workflow)
    with pytest.raises(DevflowError, match="active accepted baseline"):
        collect(context, publication, receipt)


def test_unfinished_previous_publication_blocks_new_revision_update(context, publication):
    workflow, _, _, receipt, _ = publication
    collect(context, publication, replace(receipt, status="written"))
    run = next_accepted(context, workflow)
    with pytest.raises(DevflowError, match="reconcile"):
        workflow.publish(PublishRequest(context, run, "prepare", receipt.target, receipt.write_scope, receipt.execution_approval))
    # Observation-only final review of the old recorded write remains possible.
    assert collect(context, publication, receipt).summary == "verified"
    assert workflow.publish(PublishRequest(context, run, "prepare", receipt.target, receipt.write_scope, receipt.execution_approval)).summary == "prepared"
