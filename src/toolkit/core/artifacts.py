"""Small helpers for redacted devflow artifacts and version locks."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import DevflowError, ExitCode
from .redaction import redact


SKILL_VERSION = "1.0.0"
DOMAIN_SKILL_VERSIONS = {"biz-flow": "2.0.0", "bru-api": "1.0.0", "e2e": "1.0.0"}
VERSION_FILES = {
    "biz-flow": "docs/biz-flow/biz-flow-doc-generator-version.json",
    "bru-api": "qa/contracts/bru-api-test-generator-version.json",
    "e2e": "analysis/e2e-test-generator-version.json",
}
SKILL_NAMES = {
    "biz-flow": "biz-flow-doc-generator",
    "bru-api": "bru-api-test-generator",
    "e2e": "e2e-test-generator",
}
ARTIFACT_ROOTS = {"biz-flow": "docs/biz-flow", "bru-api": "qa/contracts", "e2e": "analysis"}


def version_file(project_root: Path, domain: str) -> Path:
    relative = VERSION_FILES[domain]
    return project_root / relative


def version_metadata(domain: str) -> dict[str, str]:
    return {"skill": SKILL_NAMES[domain], "skill_version": DOMAIN_SKILL_VERSIONS[domain], "artifact_root": ARTIFACT_ROOTS[domain]}


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


def _validate_version_metadata(value: Any, domain: str, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict) or any(value.get(key) != expected for key, expected in version_metadata(domain).items()):
        raise DevflowError(
            "GATE_FAILED",
            f"skill version file has mismatched skill, skill_version, or artifact_root: {path}",
            ExitCode.GATE_FAILED,
            "Reinitialize the project with the installed skill version.",
        )
    return value


def write_version_file(project_root: Path, domain: str, business: dict[str, Any], *, path: Path | None = None) -> Path:
    target = path or version_file(project_root, domain)
    return write_json(target, {**business, **version_metadata(domain)})


def require_version_file(project_root: Path, domain: str, *, path: Path | None = None) -> dict[str, Any]:
    path = path or version_file(project_root, domain)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevflowError("GATE_FAILED", f"cannot read skill version file {path}: {exc}", ExitCode.GATE_FAILED) from exc
    return _validate_version_metadata(value, domain, path)
