"""Actual snapshot IO and standard-library cleanup, including Windows aliases."""
import os
import subprocess
from pathlib import Path

import pytest

from toolkit.biz_flow_doc_generator import cli, host
from toolkit.biz_flow_doc_generator.git import source_view
from toolkit.biz_flow_doc_generator.paths import io_path, normal_path, snapshot_files
from test_generic_acceptance import setup_run, submit
from test_native_handoff import prepared, fixture_submission


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length paths")
@pytest.mark.parametrize("raw,expected", [
    (r"C:\short\root", "\\\\?\\C:\\short\\root"),
    (r"\\server\share\root", "\\\\?\\UNC\\server\\share\\root"),
    (r"\\?\C:\root", "\\\\?\\C:\\root"),
    (r"\\?\UNC\server\share\root", "\\\\?\\UNC\\server\\share\\root"),
])
def test_extended_paths_cover_short_roots_unc_and_already_prefixed_paths(raw, expected):
    assert str(io_path(Path(raw))) == expected
    assert io_path(normal_path(io_path(Path(raw)))) == io_path(Path(raw))


@pytest.mark.skipif(os.name == "nt", reason="POSIX path behavior")
def test_non_windows_paths_are_unchanged(tmp_path):
    assert io_path(tmp_path) == normal_path(tmp_path) == tmp_path


@pytest.mark.parametrize("alias", ["symlink", "junction"])
def test_internal_snapshot_alias_is_rejected_before_reading_target(prepared, monkeypatch, tmp_path, alias):
    _, _, manifest = prepared
    snapshot = Path(manifest["tasks"][0]["source_snapshot"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("outside evidence", encoding="utf-8")
    link = snapshot / "alias"
    if alias == "junction":
        if os.name != "nt":
            pytest.skip("Windows directory junction")
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        assert created.returncode == 0
    else:
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")
    read = Path.read_bytes
    def read_without_outside(path):
        assert path.name != "secret.py", "outside target must never be read"
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", read_without_outside)
    try:
        with pytest.raises(ValueError, match="SOURCE_PATH_UNSAFE"):
            host.validate_package(manifest)
        with pytest.raises(ValueError, match="SOURCE_PATH_UNSAFE"):
            host.snapshot_sources(Path(manifest["project_root"]), manifest["source_commit"], ["app.py"], manifest["run_id"])
        assert cli.clean_command(["--run-id", manifest["run_id"]]) == 0
    finally:
        if link.exists() or link.is_symlink():
            link.rmdir() if alias == "junction" else link.unlink()
    assert (outside / "secret.py").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path lifecycle")
def test_long_descendants_survive_archive_hashing_accept_and_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.longpaths")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    relative = "/".join(["business" * 5] * 6 + ["app.py"])
    code = "from fastapi import FastAPI\napp=FastAPI()\n# 查询订单\n@app.get('/orders')\ndef orders(): return []\n"
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, {relative: code})
    snapshot = Path(manifest["tasks"][0]["source_snapshot"])
    assert len(str(snapshot)) < 260 < len(str(snapshot / relative))
    assert (io_path(snapshot) / relative).read_text(encoding="utf-8") == code
    assert not host.validate_package(manifest)
    with source_view(root, manifest["source_commit"]) as (view, _):
        assert (view / relative).read_text(encoding="utf-8") == code
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
    assert not io_path(snapshot).exists()
    # clean must prefix a short root too, before rmtree visits a long child.
    host.snapshot_sources(root, manifest["source_commit"], [relative], manifest["run_id"])
    assert snapshot_files(snapshot)
    assert cli.clean_command(["--run-id", manifest["run_id"]]) == 0
    assert not (state / "biz-flow" / manifest["run_id"]).exists()
