"""Typed application coordination; only this class decides run transitions."""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path

from .. import __version__
from ..core.artifacts import ProjectDomainLock, require_version_file, write_version_file, version_file
from ..core.errors import DevflowError, ExitCode
from .models import (AcceptedBaseline, CommitJournal, DiscoveryCatalog, DocumentBundle, DomainCommandResult, FlowModel,
                     HostSubmission, RequirementSnapshot, RunManifest, RunState, SemanticAnnotations, SourceSnapshot,
                     TaskPackage, ValidationReport, VerificationRecord, AnalysisScope, PublicationManifest)
from .repository import digest, from_dict, now, to_dict


class SequenceWorkflow:
    def __init__(self, reader, scanner, handoff, mapper, renderer, validator, repository, committer, publisher):
        self.reader, self.scanner, self.handoff, self.mapper = reader, scanner, handoff, mapper
        self.renderer, self.validator, self.repository, self.committer = renderer, validator, repository, committer
        self.publisher = publisher

    def _path(self, context, run_id, name="manifest.json"):
        return str(self.repository.artifact_path(context, run_id, name))

    def _result(self, context, manifest, name="manifest.json", **data):
        return DomainCommandResult(manifest.state.value, {"run_id": manifest.run_id, "state": manifest.state.value,
            "authority": self._path(context, manifest.run_id, name), **data}, self._path(context, manifest.run_id, name))

    def _load(self, context, run_id):
        manifest = self.repository.load(context, run_id)
        if (manifest.skill_version, manifest.schema_version, manifest.tool_version) != ("2.0.0", 2, __version__):
            raise DevflowError("GATE_FAILED", "run was created by a different runtime contract", ExitCode.GATE_FAILED)
        self.repository.validate_artifacts(context, manifest)
        return manifest

    @contextmanager
    def _operation(self, context, run_id, states, *, fail_run=True):
        with ProjectDomainLock(context.project, context.domain):
            manifest = self._load(context, run_id)
            if manifest.state not in states:
                raise DevflowError("GATE_FAILED", f"invalid state: {manifest.state.value}; expected {', '.join(str(s) for s in states)}", ExitCode.GATE_FAILED,
                                   details_path=self._path(context, run_id))
            try:
                yield manifest
            except DevflowError as exc:
                if not exc.details_path:
                    exc.details_path = self._path(context, run_id)
                if fail_run and exc.exit_code not in {ExitCode.ARGUMENT, ExitCode.NOT_FOUND, ExitCode.AMBIGUOUS}:
                    latest = self.repository.load(context, run_id)
                    failed = replace(latest, state=RunState.FAILED, operation_errors=latest.operation_errors + (str(exc),))
                    self.repository.save(context, failed)
                raise

    def _requirements(self, context, manifest):
        if not manifest.input_hash and not manifest.requirement_hash:
            return None
        name = "input.json" if (self.repository.artifact_path(context, manifest.run_id, "input.json")).exists() else "requirements.json"
        return self.repository.read_artifact(context, manifest.run_id, name, RequirementSnapshot)

    def _recheck(self, context, manifest):
        snapshot = self.scanner.snapshot(context)
        requirements = self._requirements(context, manifest)
        report = self.validator.validate_sources(manifest.source_fingerprint, snapshot.fingerprint, manifest.adapter_fingerprint,
                                                 self.scanner.registry.fingerprint(), manifest.requirement_hash, requirements)
        if manifest.input_hash and manifest.input_hash != digest(requirements):
            raise DevflowError("GATE_FAILED", "bound input snapshot changed; start a new discover", ExitCode.GATE_FAILED)
        if not report.passed:
            raise DevflowError("GATE_FAILED", "source, adapter or bound requirement snapshot changed; start a new discover", ExitCode.GATE_FAILED)
        return snapshot, requirements

    def init(self, request):
        context = request.project
        with ProjectDomainLock(context.project, context.domain):
            path = version_file(context.project, context.domain)
            if path.exists():
                baseline = self.committer.baseline(context)
            else:
                baseline = AcceptedBaseline(0, "", "", "", "", "", ())
                write_version_file(context.project, context.domain, {**to_dict(baseline), "generated_root": context.assets.relative_to(context.project).as_posix()})
            return DomainCommandResult("initialized", {"revision": baseline.revision, "skill_version": baseline.skill_version}, str(path))

    def discover(self, request):
        context = request.project
        with ProjectDomainLock(context.project, context.domain):
            baseline = self.committer.baseline(context)
            snapshot = self.scanner.snapshot(context)
            requirements = self.reader.read(request.requirement_input) if request.requirement_input else (self.reader.read(request.description_input) if request.description_input else None)
            if request.intent == "proposal" and request.requirement_input is None:
                raise DevflowError("INVALID_ARGUMENT", "requirement mode requires one explicit requirement input", ExitCode.ARGUMENT)
            if request.intent == "description" and request.description_input is None:
                raise DevflowError("INVALID_ARGUMENT", "description intent requires a description input", ExitCode.ARGUMENT)
            catalog = self.scanner.discover(snapshot)
            selected = []
            for selector in request.entry_selectors:
                matches = [symbol for symbol in catalog.symbols if selector in {symbol.symbol_id, symbol.qualified_name, symbol.qualified_name + symbol.signature}]
                if not matches:
                    raise DevflowError("TARGET_NOT_FOUND", f"entry selector not found: {selector}", ExitCode.NOT_FOUND)
                if len(matches) != 1:
                    raise DevflowError("TARGET_AMBIGUOUS", f"entry selector needs a complete signature: {selector}", ExitCode.AMBIGUOUS)
                selected.append(matches[0].symbol_id)
            if len(selected) != len(set(selected)):
                raise DevflowError("INVALID_ARGUMENT", "entry selectors contain duplicates", ExitCode.ARGUMENT)
            run_id = self.repository.new_id()
            source_kind = "requirement" if request.intent == "proposal" else "description" if request.intent == "description" else "code"
            manifest = RunManifest(run_id, context.identity, str(context.project), request.intent, "", "", RunState.DISCOVERED,
                __version__, "2.0.0", 2, snapshot.fingerprint, digest(requirements) if requirements else "", self.scanner.registry.fingerprint(),
                digest(baseline), tuple(selected), (), (), now(), source_kind, digest(requirements) if requirements else "", tuple(s.segment_id for s in requirements.segments) if requirements else ())
            self.repository.create(context, manifest)
            for name, value in (("source-snapshot.json", snapshot), ("discovery.json", catalog)):
                manifest = self.repository.record(context, manifest, name, value)
            if requirements:
                manifest = self.repository.record(context, manifest, "requirements.json", requirements)
                manifest = self.repository.record(context, manifest, "input.json", requirements)
            self.repository.save(context, manifest)
            return self._result(context, manifest, entries=len(catalog.symbols), registered=sum(s.selection_type == "registered" for s in catalog.symbols),
                                selected_ids=manifest.selected_ids, catalog_path=self._path(context, run_id, "discovery.json"), gaps=len(catalog.gaps))

    def prepare(self, request):
        context = request.project
        if request.execution_mode not in {"native", "serial"}:
            raise DevflowError("INVALID_ARGUMENT", "execution mode must be native or serial", ExitCode.ARGUMENT)
        if not request.confirm or request.all_entries and request.selected_entry_ids or len(set(request.selected_entry_ids)) != len(request.selected_entry_ids):
            raise DevflowError("INVALID_ARGUMENT", "--confirm and an unambiguous entry selection are required", ExitCode.ARGUMENT)
        if request.execution_mode == "serial" and not request.execution_approval.strip():
            raise DevflowError("AUTHORIZATION_REQUIRED", "serial mode needs an existing explicit session authorization reference", ExitCode.UNAUTHORIZED)
        with self._operation(context, request.run_id, (RunState.DISCOVERED,)) as manifest:
            snapshot, requirements = self._recheck(context, manifest)
            catalog = self.repository.read_artifact(context, request.run_id, "discovery.json", DiscoveryCatalog)
            selected_ids = request.selected_entry_ids or manifest.selected_ids
            if manifest.intent in {"proposal", "description"}:
                available = tuple(segment.segment_id for segment in requirements.segments) if requirements else ()
                selected_segments = tuple(request.selected_segment_ids) or manifest.selected_segment_ids
                if request.all_segments:
                    selected_segments = available
                if not selected_segments:
                    raise DevflowError("INVALID_ARGUMENT", "choose --segment-id or --all-segments", ExitCode.ARGUMENT)
                if not set(selected_segments) <= set(available):
                    raise DevflowError("TARGET_NOT_FOUND", "selected segment is not in this input", ExitCode.NOT_FOUND)
            else:
                selected_segments = ()
            if request.all_entries:
                selected_ids = tuple(symbol.symbol_id for symbol in catalog.symbols)
            elif not selected_ids:
                raise DevflowError("INVALID_ARGUMENT", "choose --entry-id or --all-entries; no implicit all-entry selection", ExitCode.ARGUMENT)
            selected = tuple(symbol for symbol in catalog.symbols if symbol.symbol_id in selected_ids)
            if len(selected) != len(selected_ids):
                raise DevflowError("TARGET_NOT_FOUND", "selected entry ID is not in this discovery", ExitCode.NOT_FOUND)
            if not selected and requirements is None:
                raise DevflowError("TARGET_NOT_FOUND", "no code or requirement units selected", ExitCode.NOT_FOUND)
            model = self.scanner.analyze(snapshot, tuple(AnalysisScope(symbol, symbol.symbol_id) for symbol in selected))
            manifest = replace(manifest, selected_ids=tuple(s.symbol_id for s in selected), selected_segment_ids=tuple(selected_segments), execution_mode=request.execution_mode,
                               execution_approval=request.execution_approval, expected_baseline_digest=digest(self.committer.baseline(context)), state=RunState.PREPARED)
            package = self.handoff.prepare(manifest, model, requirements)
            for name, value in (("flow-model.json", model), ("task-package.json", package)):
                manifest = self.repository.record(context, manifest, name, value)
            self.repository.save(context, manifest)
            return self._result(context, manifest, "task-package.json", tasks=len(package.tasks), package_hash=digest(package),
                                execution_mode=manifest.execution_mode, execution_evidence="host_attested", critical_gaps=sum(g.critical for s in model.scopes for g in s.gaps))

    def collect(self, request):
        context = request.project
        with self._operation(context, request.run_id, (RunState.PREPARED, RunState.COLLECTED)) as manifest:
            try:
                if request.results_path.stat().st_size > 10 * 1024 * 1024:
                    raise DevflowError("GATE_FAILED", "host submission exceeds 10MiB", ExitCode.GATE_FAILED)
                value = json.loads(request.results_path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise DevflowError("TARGET_NOT_FOUND", "host results file does not exist", ExitCode.NOT_FOUND) from exc
            except (OSError, ValueError, UnicodeError) as exc:
                raise DevflowError("GATE_FAILED", "host results are not readable UTF-8 JSON", ExitCode.GATE_FAILED) from exc
            submission = from_dict(HostSubmission, value)
            if manifest.state == RunState.COLLECTED:
                previous = self.repository.read_artifact(context, request.run_id, "host-submission.json", HostSubmission)
                if digest(previous) != digest(submission):
                    raise DevflowError("GATE_FAILED", "different host result requires a new run", ExitCode.GATE_FAILED)
                return self._result(context, manifest, "document-bundle.json", idempotent=True)
            self._recheck(context, manifest)
            package = self.repository.read_artifact(context, request.run_id, "task-package.json", TaskPackage)
            annotations = self.handoff.validate(package, submission)
            report = self.mapper.evaluate((package.requirements, annotations.requirements), annotations.links, package.facts,
                                          manifest.intent, annotations.excluded_segments, annotations.proposed_steps, annotations.proposed_controls)
            bundle = self.renderer.build(package.facts, annotations, manifest.intent, report)
            reports = (self.validator.validate_model(package.facts), report.validation,
                       self.validator.validate_bundle(bundle, package.facts, annotations, manifest.intent, self.renderer))
            validation = ValidationReport(tuple(r for report in reports for r in report.rules), tuple(g for report in reports for g in report.gaps))
            render = self.renderer.render(bundle, "mmdc", self.repository.run_path(context, request.run_id) / "tmp" / "render")
            for name, value in (("host-submission.json", submission), ("annotations.json", annotations), ("document-bundle.json", bundle),
                                ("validation.json", validation), ("render-report.json", render)):
                manifest = self.repository.record(context, manifest, name, value)
            self.repository.save(context, manifest)
            if not validation.passed or render.status == "failed":
                raise DevflowError("GATE_FAILED", "model, requirement, document or render gate failed", ExitCode.GATE_FAILED,
                                   details_path=self._path(context, request.run_id, "validation.json"))
            manifest = replace(manifest, state=RunState.COLLECTED)
            self.repository.save(context, manifest)
            return self._result(context, manifest, "document-bundle.json", render_status=render.status, implementation_consistency=report.implementation_consistency)

    def check(self, request):
        context = request.project
        manifest = self._load(context, request.run_id)
        if request.stage == "entries":
            self._recheck(context, manifest)
            catalog = self.repository.read_artifact(context, request.run_id, "discovery.json", DiscoveryCatalog)
            return self._result(context, manifest, catalog=catalog, read_only=True)
        if manifest.state == RunState.PREPARED:
            model = self.repository.read_artifact(context, request.run_id, "flow-model.json", FlowModel)
            return self._result(context, manifest, report=self.validator.validate_model(model), read_only=True)
        if manifest.state in {RunState.COLLECTED, RunState.VERIFIED, RunState.ACCEPTED}:
            package = self.repository.read_artifact(context, request.run_id, "task-package.json", TaskPackage)
            annotations = self.repository.read_artifact(context, request.run_id, "annotations.json", SemanticAnnotations)
            bundle = self.repository.read_artifact(context, request.run_id, "document-bundle.json", DocumentBundle)
            report = self.validator.validate_bundle(bundle, package.facts, annotations, manifest.intent, self.renderer)
            if not report.passed:
                raise DevflowError("GATE_FAILED", "read-only document validation failed", ExitCode.GATE_FAILED, details_path=self._path(context, request.run_id))
            return self._result(context, manifest, report=report, read_only=True)
        return self._result(context, manifest, artifacts=manifest.artifacts, operation_errors=manifest.operation_errors, read_only=True)

    def verify(self, request):
        context = request.project
        with self._operation(context, request.run_id, (RunState.COLLECTED, RunState.VERIFIED)) as manifest:
            snapshot, requirements = self._recheck(context, manifest)
            model = self.repository.read_artifact(context, request.run_id, "flow-model.json", FlowModel)
            annotations = self.repository.read_artifact(context, request.run_id, "annotations.json", SemanticAnnotations)
            bundle = self.repository.read_artifact(context, request.run_id, "document-bundle.json", DocumentBundle)
            rebuilt = self.scanner.analyze(snapshot, tuple(scope.scope for scope in model.scopes))
            report = self.mapper.evaluate((requirements, annotations.requirements), annotations.links, rebuilt, manifest.intent,
                                          annotations.excluded_segments, annotations.proposed_steps, annotations.proposed_controls)
            rebuilt_bundle = self.renderer.build(rebuilt, annotations, manifest.intent, report)
            validation = self.validator.validate_model(rebuilt)
            document_validation = self.validator.validate_bundle(rebuilt_bundle, rebuilt, annotations, manifest.intent, self.renderer)
            reproducible = digest(model) == digest(rebuilt) and digest(bundle) == digest(rebuilt_bundle)
            render = self.renderer.render(rebuilt_bundle, "mmdc", self.repository.run_path(context, request.run_id) / "tmp" / "verify-render")
            if not reproducible or not validation.passed or not document_validation.passed or not report.validation.passed or render.status == "failed":
                raise DevflowError("GATE_FAILED", "independent reconstruction or verification gate failed", ExitCode.GATE_FAILED)
            record = VerificationRecord(digest(rebuilt), digest(rebuilt_bundle), digest(annotations), digest((validation, document_validation, report.validation)),
                                        True, digest((rebuilt, rebuilt_bundle, annotations)), render)
            manifest = self.repository.record(context, manifest, "verification.json", record)
            manifest = replace(manifest, state=RunState.VERIFIED)
            self.repository.save(context, manifest)
            return self._result(context, manifest, "verification.json", reproducible=True, render_status=render.status, verified_digest=record.verified_digest)

    def accept(self, request):
        context = request.project
        with self._operation(context, request.run_id, (RunState.VERIFIED, RunState.ACCEPTED), fail_run=False) as manifest:
            if manifest.state == RunState.ACCEPTED:
                return self._result(context, manifest, idempotent=True)
            journal_path = self.repository.artifact_path(context, request.run_id, "commit_journal.json")
            if journal_path.exists():
                journal = self.repository.read_artifact(context, request.run_id, "commit_journal.json", CommitJournal)
                self.committer.validate_journal(context, manifest,
                    self.repository.read_artifact(context, request.run_id, "document-bundle.json", DocumentBundle),
                    self.repository.read_artifact(context, request.run_id, "verification.json", VerificationRecord), journal)
                if journal.phase != "recovered":
                    recovered = self.committer.recover(context, journal)
                    if recovered:
                        manifest = replace(manifest, state=RunState.ACCEPTED)
                        self.repository.save(context, manifest)
                        self.committer.cleanup(context, journal)
                        return self._result(context, manifest, recovered=True, revision=recovered.revision)
            self._recheck(context, manifest)
            model = self.repository.read_artifact(context, request.run_id, "flow-model.json", FlowModel)
            annotations = self.repository.read_artifact(context, request.run_id, "annotations.json", SemanticAnnotations)
            bundle = self.repository.read_artifact(context, request.run_id, "document-bundle.json", DocumentBundle)
            verification = self.repository.read_artifact(context, request.run_id, "verification.json", VerificationRecord)
            if not verification.reproducible or verification.verified_digest != digest((model, bundle, annotations)):
                raise DevflowError("GATE_FAILED", "verification digest no longer binds candidate assets", ExitCode.GATE_FAILED)
            if not self.validator.validate_model(model).passed or not self.validator.validate_bundle(bundle, model, annotations, manifest.intent, self.renderer).passed:
                raise DevflowError("GATE_FAILED", "accept document gate failed", ExitCode.GATE_FAILED)
            plan = self.committer.plan(context, manifest, bundle, verification, self.committer.baseline(context))
            try:
                baseline = self.committer.commit(context, plan, lambda: self._recheck(context, manifest))
            except OSError as exc:
                raise DevflowError("GATE_FAILED", "commit file operation failed; retry accept explicitly to recover", ExitCode.GATE_FAILED,
                                   details_path=str(journal_path)) from exc
            manifest = replace(manifest, state=RunState.ACCEPTED)
            self.repository.save(context, manifest)
            self.committer.cleanup(context, self.repository.read_artifact(context, request.run_id, "commit_journal.json", CommitJournal))
            return self._result(context, manifest, revision=baseline.revision, assets=str(context.assets), verified_digest=baseline.verified_digest)

    def publish(self, request):
        context = request.project
        if request.stage == "check":
            self._load(context, request.run_id)
            publication = self.repository.read_artifact(context, request.run_id, "publication/manifest.json", PublicationManifest)
            return self.publisher.check(request, publication)
        with ProjectDomainLock(context.project, context.domain):
            manifest = self._load(context, request.run_id)
            baseline = self.committer.baseline(context)
            if request.stage == "prepare":
                return self.publisher.prepare(request, manifest, baseline)
            publication = self.repository.read_artifact(context, request.run_id, "publication/manifest.json", PublicationManifest)
            if request.stage == "collect":
                return self.publisher.collect(request, publication,
                    active_baseline=manifest.state == RunState.ACCEPTED and baseline.accepted_run_id == request.run_id)
            raise DevflowError("INVALID_ARGUMENT", "unknown publish stage", ExitCode.ARGUMENT)

    def clean(self, context, run_id, all_files=False):
        with ProjectDomainLock(context.project, context.domain):
            manifest = self._load(context, run_id)
            root = self.repository.run_path(context, run_id)
            journal_path = root / "commit_journal.json"
            if journal_path.exists() and all_files:
                journal = self.repository.read_artifact(context, run_id, "commit_journal.json", CommitJournal)
                if journal.phase not in {"finalized", "recovered"}:
                    raise DevflowError("GATE_FAILED", "commit recovery evidence must be retained", ExitCode.GATE_FAILED, details_path=str(journal_path))
                self.committer.cleanup(context, journal)
            render = root / "tmp"
            for folder in (render / "render", render / "verify-render"):
                if folder.exists():
                    for path in folder.glob("scene-*.mmd"):
                        path.unlink(missing_ok=True)
                    for path in folder.glob("scene-*.svg"):
                        path.unlink(missing_ok=True)
            return self._result(context, manifest, cleaned=True)
