"""New protocol rejection gates; no static agent analysis in production."""
import copy
import json
import os
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
    assert json.loads(path.read_text(encoding="utf-8"))["verification_runs"] == 0


def test_schema_rejects_old_protocol_before_business_payload(prepared):
    _, _, manifest = prepared
    submission = fixture_submission(manifest)
    submission["protocol_version"] = "4.0"
    assert host.validate_execution(manifest, submission)


@pytest.mark.parametrize("field,value,error", [
    ("protocol_version", "4.0", "UNSUPPORTED_PROTOCOL_SCHEMA"), ("protocol_version", None, "UNSUPPORTED_PROTOCOL_SCHEMA"),
    ("schema_version", 5, "UNSUPPORTED_PROTOCOL_SCHEMA"), ("schema_version", None, "UNSUPPORTED_PROTOCOL_SCHEMA"),
    ("adapter_version", "old-adapter", "ADAPTER_VERSION_CHANGED"),
])
def test_every_run_command_rejects_unsupported_manifest_without_rewriting_it(prepared, capsys, field, value, error):
    project, path, manifest = prepared
    manifest[field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    original = path.read_bytes()
    version = project / "docs/biz-flow/biz-flow-doc-generator-version.json"
    version_bytes = version.read_bytes()
    args = ["--project", str(project), "--run-id", manifest["run_id"]]
    capsys.readouterr()
    commands = [
        (cli.prepare_command, ["--project", str(project), "--resume", manifest["run_id"]]),
        (cli.collect_command, [*args, "--results", str(path.parent / "missing-submission.json")]),
        (cli.check_command, args), (cli.verify_command, args), (cli.accept_command, args),
    ]
    for command, arguments in commands:
        assert command(arguments) != 0
        assert error in capsys.readouterr().err
        assert path.read_bytes() == original
        assert version.read_bytes() == version_bytes


def test_current_run_never_falls_back_past_a_newer_unsupported_run(prepared):
    project, path, manifest = prepared
    latest = copy.deepcopy(manifest)
    latest.update(run_id="0" * 32, protocol_version="4.0")
    latest_path = path.parent / (latest["run_id"] + ".json")
    latest_path.write_text(json.dumps(latest), encoding="utf-8")
    newer = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(latest_path, ns=(newer, newer))
    with pytest.raises(ValueError, match="UNSUPPORTED_PROTOCOL_SCHEMA"):
        cli._current_manifest(project)
    with pytest.raises(ValueError, match="CURRENT_RUN_MISSING"):
        cli._current_manifest(project.parent / "unrelated-project")


@pytest.mark.parametrize("field,value", [("protocol_version", "4.0"), ("domain", "e2e")])
def test_task_package_contract_is_checked_even_when_its_hash_matches(prepared, field, value):
    _, path, manifest = prepared
    package_path = path.with_suffix(".tasks.json")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package[field] = value
    package_path.write_text(json.dumps(package), encoding="utf-8")
    manifest["package_hash"] = cli.digest(package)
    assert any("UNSUPPORTED_TASK_PACKAGE" in error for error in host.validate_package(manifest))


@pytest.mark.parametrize("field,value", [
    ("protocol_version", "4.0"), ("schema_version", 5),
    ("adapter_version", "old-adapter"), ("tasks", None),
])
def test_delivery_summary_excludes_unsupported_or_invalid_accepted_runs(prepared, monkeypatch, field, value):
    project, path, manifest = prepared
    payload = fixture_submission(manifest)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    submission = path.parent / "submission.json"
    submission.write_text(json.dumps(payload), encoding="utf-8")
    args = ["--project", str(project), "--run-id", manifest["run_id"]]
    assert cli.collect_command([*args, "--results", str(submission)]) == 0
    assert cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
    assert cli._delivery_summary(manifest)["overall_status"] == "success"
    accepted = json.loads(path.read_text(encoding="utf-8"))
    accepted[field] = value
    path.write_text(json.dumps(accepted), encoding="utf-8")
    assert cli._delivery_summary(manifest)["accepted_modules"] == []
    assert cli._delivery_summary(manifest)["overall_status"] == "partial"
