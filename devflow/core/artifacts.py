"""Small helpers for redacted devflow artifacts and version locks."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import DevflowError, ExitCode
from .redaction import redact


LOCK_NAME = ".devflow.lock.json"


def state_root() -> Path:
    return Path.home() / ".local" / "state" / "devflow" / "artifacts"


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except Exception:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def write_lock(project_root: Path, *, tool_version: str, domain: str, schema_version: str) -> Path:
    asset_root = {"bru-api": "qa", "e2e": "test/e2e", "biz-flow": "docs/biz-flow"}[domain]
    return write_json(project_root / LOCK_NAME, {
        "tool": "devflow",
        "tool_version": tool_version,
        "domain": domain,
        "schema_version": schema_version,
        "skill": {"bru-api": "devflow/test/bru-api", "e2e": "devflow/test/e2e", "biz-flow": "devflow/doc/biz-flow"}[domain],
        "asset_root": asset_root,
    })


def require_lock(
    project_root: Path,
    *,
    tool_version: str,
    domain: str,
    schema_version: str,
) -> dict[str, Any]:
    path = project_root / LOCK_NAME
    if not path.is_file():
        raise DevflowError(
            "GATE_FAILED",
            f"devflow lock does not exist: {path}",
            ExitCode.GATE_FAILED,
            "Run the domain init command with the installed devflow version.",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevflowError("GATE_FAILED", f"cannot read devflow lock {path}: {exc}", ExitCode.GATE_FAILED) from exc
    if value.get("tool") != "devflow" or value.get("domain") != domain:
        raise DevflowError("GATE_FAILED", f"devflow lock has the wrong domain: {path}", ExitCode.GATE_FAILED)
    if value.get("tool_version") != tool_version:
        raise DevflowError(
            "GATE_FAILED",
            f"project requires devflow {value.get('tool_version')}, installed version is {tool_version}",
            ExitCode.GATE_FAILED,
            "Use the locked devflow version or explicitly reinitialize the project.",
        )
    if value.get("schema_version") != schema_version:
        raise DevflowError(
            "GATE_FAILED",
            f"project requires {domain} schema {value.get('schema_version')}, installed schema is {schema_version}",
            ExitCode.GATE_FAILED,
            "Use the locked domain schema or explicitly reinitialize the project.",
        )
    expected_asset_root = {"bru-api": "qa", "e2e": "test/e2e", "biz-flow": "docs/biz-flow"}[domain]
    expected_skill = {"bru-api": "devflow/test/bru-api", "e2e": "devflow/test/e2e", "biz-flow": "devflow/doc/biz-flow"}[domain]
    if value.get("asset_root") != expected_asset_root or value.get("skill") != expected_skill:
        raise DevflowError(
            "GATE_FAILED",
            f"devflow lock has the wrong skill or asset root: {path}",
            ExitCode.GATE_FAILED,
            "Reinitialize the project with the installed devflow version.",
        )
    return value
