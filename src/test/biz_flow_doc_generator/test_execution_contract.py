"""New protocol rejection gates; no static agent analysis in production."""
import copy
import json
import pytest
from test_native_handoff import prepared, fixture_submission
from toolkit.biz_flow_doc_generator import cli, host
from toolkit.biz_flow_doc_generator.validation import validate_entry_analysis
from toolkit.core.schema import BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, validate_schema
from toolkit.biz_flow_doc_generator.orchestration import FileWriteGuard


def test_file_write_guard_rejects_entry_writer():
    with pytest.raises(PermissionError):
        FileWriteGuard("coordinator", "00-订单查询.md").assert_allowed("entry:orders", "00-订单查询.md")
    with pytest.raises(PermissionError):
        FileWriteGuard("coordinator", "../escape.md").assert_allowed("coordinator", "../escape.md")


@pytest.mark.parametrize("key,value", [
    ("resolutions", [{"finding": "invented"}]), ("outcomes", ["success"]), ("calls", []),
    ("persistence_actions", []), ("unresolved", []),
])
def test_old_fact_copy_and_resolution_protocol_is_rejected(prepared, key, value):
    _, _, manifest = prepared
    result = next(iter(fixture_submission(manifest)["results"].values()))["analysis"]
    result[key] = value
    assert validate_schema(BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA, result)


def test_old_review_steps_and_unbound_annotations_rejected(prepared):
    _, _, manifest = prepared
    response = next(iter(fixture_submission(manifest)["results"].values()))["analysis"]
    facts = manifest["entry_facts"][response["entry_id"]]
    response["review"]["steps"] = []
    assert validate_entry_analysis(response, facts)
    del response["review"]["steps"]
    response["annotations"][0]["evidence_refs"] = ["S-unrelated"]
    assert "ANALYSIS_REFERENCE_OUT_OF_SCOPE" in validate_entry_analysis(response, facts)


def test_unknowns_cannot_be_cleared_by_analysis(prepared):
    _, _, manifest = prepared
    analysis = next(iter(fixture_submission(manifest)["results"].values()))["analysis"]
    facts = copy.deepcopy(manifest["entry_facts"][analysis["entry_id"]])
    facts["gaps"].append({"finding_id": "G-unknown", "code": "UNKNOWN", "critical": True})
    errors = validate_entry_analysis(analysis, facts)
    assert any("CRITICAL_UNRESOLVED" in e for e in errors)


def test_verify_independently_rebuilds_canonical_facts(prepared, monkeypatch):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "submission.json"
    submission.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    monkeypatch.setattr(cli, "rebuild_verified", lambda *_a, **_k: {})
    assert cli.verify_command(["--project", str(project)]) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["verification_runs"] == 1


def test_schema_rejects_old_protocol_before_business_payload(prepared):
    _, _, manifest = prepared
    submission = fixture_submission(manifest)
    submission["protocol_version"] = "4.0"
    assert host.validate_execution(manifest, submission)
