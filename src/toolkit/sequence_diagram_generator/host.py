"""Typed tasks and host-attested receipts; child IDs are never proof of real execution."""
from datetime import datetime
import re

from ..core.errors import DevflowError, ExitCode
from .models import HostTask, SemanticAnnotations, SequenceBlock, TaskPackage
from .repository import digest, stable_id
from .validation import target_evidence


class HostHandoff:
    def __init__(self, validator):
        self.validator = validator

    def prepare(self, manifest, model, requirements):
        tasks = [HostTask(stable_id("T", manifest.run_id, scope.scope.entry_id), (scope.scope.entry_id,), (),
                          ("Explain only the frozen source facts; report missing facts as evidence_queries.",)) for scope in model.scopes]
        if requirements:
            tasks.append(HostTask(stable_id("T", manifest.run_id, "requirements"), tuple(scope.scope.entry_id for scope in model.scopes),
                                  tuple(segment.segment_id for segment in requirements.segments),
                                  ("Reconcile every candidate source segment or document its exclusion.", "Link code facts only with evidence; mark requirement-only proposals explicitly.")))
        return TaskPackage(manifest.run_id, tuple(tasks), digest(model), digest(requirements) if requirements else "",
                           manifest.execution_mode, manifest.execution_approval, digest(manifest.selected_ids), model, requirements)

    def validate(self, package, submission):
        report = self.validator.validate_submission(package, submission)
        if not report.passed:
            raise DevflowError("GATE_FAILED", "host submission identity or task set is invalid", ExitCode.GATE_FAILED)
        results = {r.task_id: r for r in submission.results}
        tasks = {t.task_id: t for t in package.tasks}
        for receipt in submission.receipts:
            result, task = results[receipt.task_id], tasks[receipt.task_id]
            if receipt.package_hash != digest(package) or receipt.result_hash != digest(result) or receipt.scope_ids != task.scope_ids or receipt.status != "success":
                raise DevflowError("GATE_FAILED", "receipt hash, status or scope mismatch", ExitCode.GATE_FAILED)
            try:
                times = [datetime.fromisoformat(value) for value in (receipt.started_at, receipt.ended_at, receipt.reclaimed_at)]
                if any(value.tzinfo is None for value in times) or not times[0] <= times[1] <= times[2]:
                    raise ValueError("invalid lifecycle ordering")
            except (ValueError, TypeError) as exc:
                raise DevflowError("GATE_FAILED", "host lifecycle record is missing or invalid", ExitCode.GATE_FAILED) from exc
            if package.execution_mode == "native":
                if not receipt.child_agent_id or receipt.child_count != 1 or receipt.degraded or not receipt.tool_references:
                    raise DevflowError("GATE_FAILED", "native receipt lacks host-attested child/tool evidence", ExitCode.GATE_FAILED)
            elif not (package.execution_approval and receipt.degraded and not receipt.parallel and receipt.child_count == 0
                      and not receipt.child_agent_id and receipt.execution_approval == package.execution_approval):
                raise DevflowError("AUTHORIZATION_REQUIRED", "serial receipt lacks bound authorization or zero-child record", ExitCode.UNAUTHORIZED)
            if result.evidence_queries:
                raise DevflowError("GATE_FAILED", "host reported unverified facts; start a new discover after adapter verification", ExitCode.GATE_FAILED)
            allowed_scopes = [scope for scope in package.facts.scopes if scope.scope.entry_id in task.scope_ids]
            targets = {step.step_id for scope in allowed_scopes for step in scope.steps}
            targets.update(symbol.symbol_id for scope in allowed_scopes for symbol in scope.symbols)
            targets.update(control.control_id for scope in allowed_scopes for control in scope.controls)
            bindings = target_evidence(allowed_scopes)
            for label in result.annotations.labels:
                if label.target_id not in targets or not label.evidence_ids or not set(label.evidence_ids) <= bindings.get(label.target_id, set()) or not label.explanation.strip() or "[REDACTED]" in label.label:
                    raise DevflowError("GATE_FAILED", "business label lacks evidence or exceeds task scope", ExitCode.GATE_FAILED)
            if not task.segment_ids and (result.annotations.requirements or result.annotations.links or result.annotations.proposed_steps or result.annotations.excluded_segments or result.annotations.proposed_controls or result.annotations.proposed_sequence):
                raise DevflowError("GATE_FAILED", "code-only task submitted requirement proposals outside its scope", ExitCode.GATE_FAILED)
            requirement_ids = {item.requirement_id for item in result.annotations.requirements}
            for item in result.annotations.requirements:
                if not re.fullmatch(r"R-[0-9a-f]{24}", item.requirement_id) or not set(item.segment_ids) <= set(task.segment_ids):
                    raise DevflowError("GATE_FAILED", "requirement identity or source scope is invalid", ExitCode.GATE_FAILED)
            proposed_ids = set()
            for step in result.annotations.proposed_steps:
                refs = set(step.source_ids) or set(step.requirement_ids)
                if not re.fullmatch(r"S-[0-9a-f]{24}", step.step_id) or step.step_id in proposed_ids or not refs or not refs <= set(task.segment_ids) | requirement_ids or not all((step.sender.strip(), step.receiver.strip(), step.label.strip())):
                    raise DevflowError("GATE_FAILED", "proposal step lacks requirement evidence or unique identity", ExitCode.GATE_FAILED)
                proposed_ids.add(step.step_id)
            control_ids = {control.control_id for control in result.annotations.proposed_controls}
            if len(control_ids) != len(result.annotations.proposed_controls):
                raise DevflowError("GATE_FAILED", "duplicate proposal control identity", ExitCode.GATE_FAILED)
            for control in result.annotations.proposed_controls:
                refs = set(control.source_ids) or set(control.requirement_ids)
                if (not re.fullmatch(r"B-[0-9a-f]{24}", control.control_id) or control.kind not in {"alt", "opt", "loop", "par"}
                    or not refs or not refs <= set(task.segment_ids) | requirement_ids
                    or not control.exit_ids or len(set(control.exit_ids)) != len(control.exit_ids)):
                    raise DevflowError("GATE_FAILED", "proposal control is missing requirement evidence", ExitCode.GATE_FAILED)
            if result.annotations.proposed_sequence:
                used_steps, used_controls = [], []
                def visit(block):
                    if block.kind != "sequence":
                        used_controls.append(block.block_id)
                        control = next((c for c in result.annotations.proposed_controls if c.control_id == block.block_id), None)
                        if control is None or control.kind != block.kind or control.exit_ids != tuple(arm.exit_id for arm in block.arms):
                            raise DevflowError("GATE_FAILED", "proposal control tree does not bind its declared exits", ExitCode.GATE_FAILED)
                    for arm in block.arms:
                        for item in arm.items:
                            if isinstance(item, SequenceBlock):
                                visit(item)
                            else:
                                used_steps.append(item.step_id)
                visit(result.annotations.proposed_sequence)
                if set(used_steps) != proposed_ids or set(used_controls) != control_ids or len(used_steps) != len(proposed_ids) or len(used_controls) != len(control_ids):
                    raise DevflowError("GATE_FAILED", "proposal tree has missing or unknown steps/controls", ExitCode.GATE_FAILED)
        annotations = SemanticAnnotations(tuple(x for r in submission.results for x in r.annotations.labels),
            tuple(x for r in submission.results for x in r.annotations.requirements), tuple(x for r in submission.results for x in r.annotations.links),
            tuple(x for r in submission.results for x in r.annotations.proposed_steps), tuple(x for r in submission.results for x in r.annotations.excluded_segments),
            tuple(x for r in submission.results for x in r.annotations.proposed_controls),
            next((r.annotations.proposed_sequence for r in submission.results if r.annotations.proposed_sequence), None))
        if len({label.target_id for label in annotations.labels}) != len(annotations.labels):
            raise DevflowError("GATE_FAILED", "multiple tasks supplied conflicting labels for one target", ExitCode.GATE_FAILED)
        return annotations
