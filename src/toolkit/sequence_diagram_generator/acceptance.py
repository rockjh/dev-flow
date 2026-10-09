"""Ownership checks and journaled multi-file commit/recovery, under the caller's OS lock."""
from dataclasses import replace
from pathlib import Path, PureWindowsPath
import json
import os
import tempfile

from ..core.artifacts import require_version_file, write_json, write_version_file
from ..core.errors import DevflowError, ExitCode
from ..core.redaction import redact
from .models import AcceptedBaseline, CommitFile, CommitJournal, CommitPlan, GeneratedAsset
from .repository import bytes_digest, confined, digest, from_dict, to_dict

VERSION_NAME = "sequence-diagram-generator-version.json"
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


class ArtifactCommitter:
    def __init__(self, repository):
        self.repository = repository

    def baseline(self, context):
        return from_dict(AcceptedBaseline, require_version_file(context.project, context.domain))

    def _target(self, context, relative):
        if PureWindowsPath(relative).is_absolute() or "\\" in relative or any(part in {"..", ".", ""} for part in relative.split("/")):
            raise DevflowError("GATE_FAILED", "unsafe generated asset path", ExitCode.GATE_FAILED)
        target = confined(context.project / relative, context.assets)
        if target.name.casefold() == VERSION_NAME.casefold():
            raise DevflowError("GATE_FAILED", "the version file cannot be a generated business asset", ExitCode.GATE_FAILED)
        for part in Path(relative).parts:
            if any(char in part for char in '<>:"|?*') or part.endswith((".", " ")) or part.split(".")[0].upper() in RESERVED:
                raise DevflowError("GATE_FAILED", "generated asset violates Windows filename rules", ExitCode.GATE_FAILED)
        return target

    def _file_hash(self, path):
        return bytes_digest(path.read_bytes()) if path.is_file() else ""

    def _replace(self, target, content):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".devflow-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(target)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def plan(self, context, manifest, bundle, verification, baseline):
        if digest(baseline) != manifest.expected_baseline_digest:
            raise DevflowError("GATE_FAILED", "parent baseline advanced since prepare", ExitCode.GATE_FAILED)
        owned = {asset.path.casefold(): asset for asset in baseline.generated_assets}
        outputs = [(scene.filename, scene.markdown, scene.filename) for scene in bundle.scenes]
        outputs += [("matrix.md", bundle.matrix, "coverage"), ("overview.md", bundle.overview, "coverage")]
        filenames = [name.casefold() for name, _, _ in outputs]
        if len(set(filenames)) != len(filenames):
            raise DevflowError("TARGET_AMBIGUOUS", "case-insensitive scene filenames collide", ExitCode.AMBIGUOUS)
        files = []
        for name, content, scene in outputs:
            relative = (context.assets / name).relative_to(context.project).as_posix()
            target = self._target(context, relative)
            # Detect same filename with different case on case-sensitive hosts too.
            if target.parent.exists() and any(p.name.casefold() == target.name.casefold() and p.name != target.name for p in target.parent.iterdir()):
                raise DevflowError("GATE_FAILED", "existing asset has a case-conflicting filename", ExitCode.GATE_FAILED)
            owner = owned.get(relative.casefold())
            old_hash = self._file_hash(target)
            if target.exists() and (not target.is_file() or owner is None or old_hash != owner.digest):
                raise DevflowError("GATE_FAILED", f"refusing to overwrite user file or edited asset: {relative}", ExitCode.GATE_FAILED)
            if owner and not target.exists():
                raise DevflowError("GATE_FAILED", f"registered generated asset was removed: {relative}", ExitCode.GATE_FAILED)
            content = redact(content)
            files.append(CommitFile(relative, old_hash, bytes_digest(content.encode("utf-8")), content, scene))
        new_paths = {item.path for item in files}
        for asset in baseline.generated_assets:
            if asset.path not in new_paths:
                target = self._target(context, asset.path)
                if self._file_hash(target) != asset.digest:
                    raise DevflowError("GATE_FAILED", f"old generated asset changed: {asset.path}", ExitCode.GATE_FAILED)
                files.append(CommitFile(asset.path, asset.digest, "", "", asset.scene))
        next_baseline = AcceptedBaseline(baseline.revision + 1, manifest.run_id, manifest.source_fingerprint, manifest.requirement_hash,
            digest(manifest.selected_ids), verification.verified_digest, tuple(GeneratedAsset(item.path, item.new_digest, item.scene) for item in files if item.new_digest))
        return CommitPlan(manifest.run_id, str(context.project), digest(baseline), tuple(files), baseline, next_baseline)

    def _save_journal(self, context, journal):
        self.repository.write_artifact(context, journal.plan.run_id, "commit_journal.json", journal)

    def validate_journal(self, context, manifest, bundle, verification, journal):
        """Bind recovery instructions to frozen candidates, not editable journal claims."""
        plan = journal.plan
        outputs = [(scene.filename, scene.markdown, scene.filename) for scene in bundle.scenes]
        outputs += [("matrix.md", bundle.matrix, "coverage"), ("overview.md", bundle.overview, "coverage")]
        expected = {(context.assets / name).relative_to(context.project).as_posix(): (redact(content), scene)
                    for name, content, scene in outputs}
        parent = {asset.path: asset for asset in plan.parent.generated_assets}
        valid = (plan.run_id == manifest.run_id and plan.project_path == str(context.project)
                 and plan.baseline_digest == manifest.expected_baseline_digest == digest(plan.parent)
                 and plan.next_baseline.accepted_run_id == manifest.run_id
                 and plan.next_baseline.revision == plan.parent.revision + 1
                 and plan.next_baseline.verified_digest == verification.verified_digest
                 and plan.next_baseline.source_fingerprint == manifest.source_fingerprint
                 and plan.next_baseline.requirement_fingerprint == manifest.requirement_hash
                 and plan.next_baseline.scope_fingerprint == digest(manifest.selected_ids)
                 and len({item.path for item in plan.files}) == len(plan.files))
        for item in plan.files:
            self._target(context, item.path)
            owner = parent.get(item.path)
            valid = valid and item.old_digest == (owner.digest if owner else "")
            if item.path in expected:
                content, scene = expected[item.path]
                valid = valid and (item.content, item.scene, item.new_digest) == (content, scene, bytes_digest(content.encode("utf-8")))
            else:
                valid = valid and owner is not None and not item.new_digest and not item.content
        valid = valid and {item.path for item in plan.files} == set(expected) | set(parent)
        valid = valid and plan.next_baseline.generated_assets == tuple(
            GeneratedAsset(item.path, item.new_digest, item.scene) for item in plan.files if item.new_digest)
        if not valid:
            raise DevflowError("GATE_FAILED", "recovery journal does not match frozen verified candidates", ExitCode.GATE_FAILED)

    def commit(self, context, plan, source_check):
        if digest(self.baseline(context)) != plan.baseline_digest:
            raise DevflowError("GATE_FAILED", "baseline changed before transaction", ExitCode.GATE_FAILED)
        root = self.repository.run_path(context, plan.run_id)
        backup = confined(root / "tmp" / "commit-backups", root)
        backup.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(plan.files):
            target = self._target(context, item.path)
            if self._file_hash(target) != item.old_digest:
                raise DevflowError("GATE_FAILED", "asset changed before transaction", ExitCode.GATE_FAILED)
            if item.old_digest:
                self._replace(backup / f"{index}.bin", target.read_bytes())
        self._replace(backup / "baseline.json", (context.assets / VERSION_NAME).read_bytes())
        journal = CommitJournal("prepared", plan, (), False)
        self._save_journal(context, journal)
        try:
            for item in plan.files:
                target = self._target(context, item.path)
                if item.new_digest:
                    self._replace(target, item.content.encode("utf-8"))
                else:
                    target.unlink()
                journal = replace(journal, phase="files_written", files_written=journal.files_written + (item.path,))
                self._save_journal(context, journal)
            source_check()
            if any(self._file_hash(self._target(context, item.path)) != item.new_digest for item in plan.files):
                raise DevflowError("GATE_FAILED", "asset changed during transaction", ExitCode.GATE_FAILED)
            write_version_file(context.project, context.domain, to_dict(plan.next_baseline))
            journal = replace(journal, phase="baseline_written", baseline_written=True)
            self._save_journal(context, journal)
            if digest(self.baseline(context)) != digest(plan.next_baseline):
                raise DevflowError("GATE_FAILED", "written baseline does not match committed assets", ExitCode.GATE_FAILED)
            journal = replace(journal, phase="finalized")
            self._save_journal(context, journal)
            return plan.next_baseline
        except (OSError, ValueError, DevflowError) as exc:
            raise DevflowError("GATE_FAILED", f"commit interrupted; explicit accept retry recovers journal: {exc}", ExitCode.GATE_FAILED,
                               details_path=str(root / "commit_journal.json")) from exc

    def recover(self, context, journal):
        plan = journal.plan
        if plan.project_path != str(context.project):
            raise DevflowError("GATE_FAILED", "journal belongs to another project", ExitCode.GATE_FAILED)
        current = self.baseline(context)
        if journal.phase == "finalized":
            if digest(current) != digest(plan.next_baseline):
                raise DevflowError("GATE_FAILED", "finalized journal is no longer the active baseline", ExitCode.GATE_FAILED)
            return plan.next_baseline
        if digest(current) not in {digest(plan.parent), digest(plan.next_baseline)}:
            raise DevflowError("GATE_FAILED", "newer or manually edited baseline prevents recovery", ExitCode.GATE_FAILED)
        # Also covers a crash between replace and the journal write.
        for item in plan.files:
            actual = self._file_hash(self._target(context, item.path))
            if actual not in {item.old_digest, item.new_digest}:
                raise DevflowError("GATE_FAILED", f"manual changes prevent recovery: {item.path}", ExitCode.GATE_FAILED)
        backup = self.repository.run_path(context, plan.run_id) / "tmp" / "commit-backups"
        for index, item in enumerate(plan.files):
            target = self._target(context, item.path)
            if self._file_hash(target) == item.old_digest:
                continue
            if item.old_digest:
                contents = confined(backup / f"{index}.bin", self.repository.run_path(context, plan.run_id)).read_bytes()
                if bytes_digest(contents) != item.old_digest:
                    raise DevflowError("GATE_FAILED", "transaction backup changed", ExitCode.GATE_FAILED)
                self._replace(target, contents)
            else:
                target.unlink(missing_ok=True)
        write_version_file(context.project, context.domain, to_dict(plan.parent))
        self._save_journal(context, replace(journal, phase="recovered", files_written=(), baseline_written=False))
        return None

    def cleanup(self, context, journal):
        """Delete only transaction backup filenames explicitly derived from this plan."""
        root = self.repository.run_path(context, journal.plan.run_id)
        backup = confined(root / "tmp" / "commit-backups", root)
        for name in ("baseline.json", *(f"{index}.bin" for index in range(len(journal.plan.files)))):
            confined(backup / name, root).unlink(missing_ok=True)
