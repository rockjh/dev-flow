"""Typed serialization and bounded, redacted run storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import types
import uuid
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

from ..core.artifacts import state_root, write_json
from ..core.errors import DevflowError, ExitCode
from ..core.redaction import redact
from ..core.schema import get_schema, validate_schema
from .models import ArtifactDigest, ProjectContext, RunManifest


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_dict(value):
    if is_dataclass(value):
        return {f.name: to_dict(getattr(value, f.name)) for f in fields(value)
                if not (type(value).__name__ == "SourceSnapshot" and f.name == "contents")}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, frozenset, list)):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value


def canonical(value) -> bytes:
    return json.dumps(redact(to_dict(value)), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_id(prefix: str, *parts) -> str:
    return prefix + "-" + digest(parts)[:24]


def _decode(annotation, value):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return _decode(candidate, value)
            except (ValueError, TypeError, KeyError):
                continue
        raise ValueError("value does not match the declared union")
    if annotation is type(None):
        if value is not None:
            raise ValueError("expected null")
        return None
    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError("expected array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], item) for item in value)
        if len(value) != len(args):
            raise ValueError("tuple length mismatch")
        return tuple(_decode(kind, item) for kind, item in zip(args, value))
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise ValueError("expected object")
        declared = {f.name for f in fields(annotation)}
        if value.keys() - declared:
            raise ValueError("unexpected model fields: " + ", ".join(value.keys() - declared))
        hints = get_type_hints(annotation)
        return annotation(**{key: _decode(hints[key], item) for key, item in value.items()})
    if annotation is Path:
        if not isinstance(value, str):
            raise ValueError("expected path string")
        return Path(value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if annotation in (str, int, bool, float):
        if type(value) is not annotation:
            raise ValueError(f"expected {annotation.__name__}")
    return value


def from_dict(model_type, value):
    scope = "sequence-diagram-generator." + re.sub(r"(?<!^)(?=[A-Z])", "-", model_type.__name__).lower()
    try:
        errors = validate_schema(get_schema(scope)["document"], value)
        if errors:
            raise ValueError("; ".join(errors[:5]))
        return _decode(model_type, value)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise DevflowError("GATE_FAILED", f"invalid {model_type.__name__}: {exc}", ExitCode.GATE_FAILED) from exc


def confined(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise DevflowError("GATE_FAILED", f"resolved path escapes allowed root: {path}", ExitCode.GATE_FAILED)
    return resolved


def project_context(value: str) -> ProjectContext:
    project = Path(value).resolve(strict=True)
    if not project.is_dir():
        raise DevflowError("INVALID_ARGUMENT", "--project must be a directory", ExitCode.ARGUMENT)
    assets = confined(project / "docs" / "sequence-diagram", project)
    identity = bytes_digest(os.path.normcase(str(project)).encode("utf-8"))
    state = state_root().resolve() / "sequence-diagram"
    return ProjectContext(project, assets, state, identity)


class RunRepository:
    def run_path(self, context: ProjectContext, run_id: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
            raise DevflowError("INVALID_ARGUMENT", "run_id must be 32 lowercase hex characters", ExitCode.ARGUMENT)
        return confined(context.state / "runs" / run_id, context.state)

    def create(self, context: ProjectContext, manifest: RunManifest) -> RunManifest:
        path = self.run_path(context, manifest.run_id)
        path.mkdir(parents=True, exist_ok=False)
        self.save(context, manifest)
        return manifest

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def load(self, context: ProjectContext, run_id: str) -> RunManifest:
        manifest = self.read_artifact(context, run_id, "manifest.json", RunManifest)
        if manifest.project_identity != context.identity or manifest.project_path != str(context.project):
            raise DevflowError("GATE_FAILED", "run belongs to a different project", ExitCode.GATE_FAILED)
        return manifest

    def save(self, context: ProjectContext, manifest: RunManifest) -> Path:
        return self.write_artifact(context, manifest.run_id, "manifest.json", manifest)

    def artifact_path(self, context: ProjectContext, run_id: str, name: str) -> Path:
        if not name or Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
            raise DevflowError("INVALID_ARGUMENT", "invalid run artifact path", ExitCode.ARGUMENT)
        return confined(self.run_path(context, run_id) / name, self.run_path(context, run_id))

    def write_artifact(self, context: ProjectContext, run_id: str, name: str, value) -> Path:
        payload = redact(to_dict(value))
        if is_dataclass(value):
            # Redaction can destroy required types: check the persisted value.
            from_dict(type(value), payload)
        return write_json(self.artifact_path(context, run_id, name), payload)

    def read_artifact(self, context: ProjectContext, run_id: str, name: str, model_type):
        path = self.artifact_path(context, run_id, name)
        try:
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("artifact exceeds 50MiB")
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DevflowError("TARGET_NOT_FOUND", f"missing run artifact: {path}", ExitCode.NOT_FOUND) from exc
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise DevflowError("GATE_FAILED", f"cannot read run artifact: {exc}", ExitCode.GATE_FAILED) from exc
        return from_dict(model_type, value)

    def record(self, context: ProjectContext, manifest: RunManifest, name: str, value) -> RunManifest:
        self.write_artifact(context, manifest.run_id, name, value)
        records = tuple(item for item in manifest.artifacts if item.name != name) + (ArtifactDigest(name, digest(value)),)
        return replace(manifest, artifacts=records)

    def validate_artifacts(self, context: ProjectContext, manifest: RunManifest) -> None:
        for item in manifest.artifacts:
            path = self.artifact_path(context, manifest.run_id, item.name)
            try:
                actual = digest(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                raise DevflowError("GATE_FAILED", f"missing or invalid evidence artifact: {item.name}", ExitCode.GATE_FAILED) from exc
            if actual != item.digest:
                raise DevflowError("GATE_FAILED", f"evidence artifact changed: {item.name}", ExitCode.GATE_FAILED)
