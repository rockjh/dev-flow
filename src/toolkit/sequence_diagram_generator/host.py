"""Typed tasks and host-attested receipts; child IDs are never proof of real execution."""
from dataclasses import replace
import re

from ..core.agents import parse_timestamp, validate_active_observations
from ..core.errors import DevflowError, ExitCode
from .models import HostExecutionReport, HostTask, SemanticAnnotations, SequenceBlock, TaskPackage
from .repository import digest, stable_id, to_dict
from .validation import target_evidence


class HostHandoff:
    def __init__(self, validator, *, allow_fixtures=False):
        self.validator = validator
        self.allow_fixtures = allow_fixtures

    def prepare(self, manifest, model, requirements, *, source_commit="", handoff_root=""):
        tasks = [HostTask(stable_id("T", manifest.run_id, scope.scope.entry_id), (scope.scope.entry_id,), (),
                          ("Explain only the frozen source facts; report missing facts as evidence_queries.",)) for scope in model.scopes]
        if requirements:
            tasks.append(HostTask(stable_id("T", manifest.run_id, "requirements"), tuple(scope.scope.entry_id for scope in model.scopes),
                                  tuple(segment.segment_id for segment in requirements.segments if segment.segment_id in manifest.selected_segment_ids),
                                  ("Reconcile every candidate source segment or document its exclusion.", "Link code facts only with evidence; mark requirement-only proposals explicitly.")))
        tasks = tuple(replace(task, result_path=f"{task.task_id}/result.json") for task in tasks)
        return TaskPackage(manifest.run_id, tasks, digest(model), digest(requirements) if requirements else "",
                           manifest.execution_mode, manifest.execution_approval, digest(manifest.selected_ids), model, requirements,
                           manifest.project_path, source_commit, handoff_root)

    def execution_report(self, package, submission):
        """Validate declared observations; JSON alone cannot prove a host tool ran."""
        def fail(message):
            raise DevflowError("GATE_FAILED", message, ExitCode.GATE_FAILED)

        def timestamp(value):
            try:
                return parse_timestamp(value)
            except (ValueError, TypeError) as exc:
                raise DevflowError("GATE_FAILED", "invalid execution observation time", ExitCode.GATE_FAILED) from exc

        successful = {r.task_id: r for r in submission.receipts if r.status == "success"}
        results = {r.task_id: r for r in submission.results}
        tasks = {t.task_id: t for t in package.tasks}
        if package.execution_mode == "native" and package.execution_approval:
            fail("native task package cannot carry serial execution approval")
        intervals, previous, host_attempt_intervals = {}, {}, {}
        for receipt in submission.receipts:
            if receipt.record_origin not in {"host-attested", "fixture"} or receipt.record_origin == "fixture" and not self.allow_fixtures:
                fail("fixture or unrecognized receipts are not host execution evidence")
            if receipt.task_id not in tasks or receipt.package_hash != digest(package) or receipt.scope_ids != tasks[receipt.task_id].scope_ids or receipt.attempt < 1:
                fail("receipt package, attempt or scope mismatch")
            if receipt.status not in {"success", "failed", "interrupted", "timeout", "spawn_failed"}:
                fail("receipt has an unsupported execution status")
            earlier = previous.setdefault(receipt.task_id, [])
            if earlier and (earlier[-1].status == "success" or receipt.attempt != earlier[-1].attempt + 1) or not earlier and receipt.attempt != 1:
                fail("task attempts must be consecutive and end at the first success")
            earlier.append(receipt)
            if receipt.status == "success":
                result = results.get(receipt.task_id)
                if result is None or result.attempt != receipt.attempt or receipt.result_hash != digest(result) or receipt.error:
                    fail("successful receipt does not bind its result attempt and hash")
            elif not receipt.error.strip() or receipt.result_hash:
                fail("failed execution attempt lacks its diagnostic or claims an unbound result")
            if receipt.time_source not in {"host", "coordinator_observed", "unavailable"}:
                fail("execution time source is invalid")
            times = tuple(timestamp(value) for value in (receipt.started_at, receipt.ended_at) if value)
            if receipt.time_source == "unavailable" and times or len(times) == 2 and times[0] > times[1]:
                fail("execution observation times contradict their source or order")
            if len(earlier) > 1:
                prior = earlier[-2]
                if receipt.started_at and prior.ended_at and receipt.time_source == prior.time_source and timestamp(receipt.started_at) < timestamp(prior.ended_at):
                    fail("retry observation starts before its preceding attempt ended")
            if receipt.reclaim_state not in {"reclaimed", "unsupported", "not_observed"} or bool(receipt.reclaimed_at) != (receipt.reclaim_state == "reclaimed"):
                fail("reclamation state contradicts observed reclamation")
            if receipt.status == "spawn_failed" and (receipt.reclaim_state == "reclaimed" or receipt.reclaimed_at):
                fail("failed startup cannot claim a reclaimed child")
            if receipt.reclaimed_at:
                reclaimed = timestamp(receipt.reclaimed_at)
                if not receipt.ended_at or reclaimed < timestamp(receipt.ended_at) or not receipt.tool_references:
                    fail("reclamation lacks a completed task or observed tool reference")
            if package.execution_mode == "native":
                spawned = receipt.status != "spawn_failed"
                if receipt.execution_approval or receipt.degraded or receipt.child_count != int(spawned) or bool(receipt.child_agent_id.strip()) != spawned or not receipt.tool_references or any(not ref.strip() for ref in receipt.tool_references):
                    fail("native receipt lacks host-attested child/tool evidence")
            elif package.execution_mode != "serial" or not (package.execution_approval and receipt.status != "spawn_failed"
                      and receipt.degraded and not receipt.parallel and receipt.child_count == 0
                      and not receipt.child_agent_id and receipt.execution_approval == package.execution_approval):
                raise DevflowError("AUTHORIZATION_REQUIRED", "serial receipt lacks bound authorization or zero-child record", ExitCode.UNAUTHORIZED)
            if package.execution_mode == "native" and receipt.status != "spawn_failed" and receipt.time_source == "host" and len(times) == 2:
                owned = host_attempt_intervals.setdefault(receipt.child_agent_id, [])
                if any(max(prior[0], times[0]) < min(prior[1], times[1]) for prior in owned):
                    fail("one child agent cannot own overlapping host task intervals")
                owned.append(times)
            if receipt.status != "spawn_failed" and len(times) == 2:
                intervals[receipt.task_id, receipt.attempt] = times
        launched = {(r.task_id, r.attempt): r for r in submission.receipts
                    if package.execution_mode == "native" and r.status != "spawn_failed"}
        parallel_attempts = set()
        for left_id, left in launched.items():
            for right_id, right in launched.items():
                if left_id < right_id and left.task_id != right.task_id and left.time_source == right.time_source == "host" and left_id in intervals and right_id in intervals:
                    if max(intervals[left_id][0], intervals[right_id][0]) < min(intervals[left_id][1], intervals[right_id][1]):
                        parallel_attempts.update((left_id, right_id))
        for observation in submission.active_observations:
            active = observation.active_task_ids
            observed = timestamp(observation.observed_at)
            active_attempts = tuple(zip(active, observation.active_attempts))
            if (len(observation.active_attempts) != len(active) or not set(active_attempts) <= launched.keys()
                    or package.execution_mode != "native"):
                fail("active observation does not bind simultaneous independent native tasks")
            bindings = {task: launched[task, attempt].child_agent_id for task, attempt in active_attempts}
            if (validate_active_observations([to_dict(observation)], bindings)
                    or observation.active_child_agent_ids != tuple(bindings[task] for task in active)):
                fail("active observation does not bind simultaneous independent native tasks")
            for identity in active_attempts:
                receipt = launched[identity]
                if receipt.time_source == observation.time_source and (
                    receipt.started_at and observed < timestamp(receipt.started_at)
                    or receipt.ended_at and observed > timestamp(receipt.ended_at)
                ):
                    fail("active observation falls outside the declared task observations")
            parallel_attempts.update(active_attempts)
        if any(receipt.parallel and (receipt.task_id, receipt.attempt) not in parallel_attempts for receipt in submission.receipts):
            fail("parallel claim lacks an overlapping host interval or active observation")
        child_ids = tuple(sorted({r.child_agent_id for r in successful.values() if r.child_agent_id}))
        if submission.completed_child_agents != len(child_ids):
            fail("completed child count differs from the unique successful child agent set")
        if submission.permission_enforcement not in {"shared_workspace_instructions", "host_sandbox", "staging_patch", "worktree"}:
            fail("missing or unsupported permission enforcement description")
        return HostExecutionReport(package.run_id, digest(package), package.execution_mode, package.execution_mode == "serial", bool(parallel_attempts),
                                   len(child_ids), child_ids, len(successful), len(submission.receipts),
                                   "fixture" if any(r.record_origin == "fixture" for r in submission.receipts) else "host-attested",
                                   "structure-and-consistency-only", submission.permission_enforcement)

    def validate_attempt_history(self, package, submission, previous):
        """Keep only valid, bound failure prefixes from rejected submissions."""
        package_hash = digest(package)
        if previous.run_id != package.run_id or previous.package_hash != package_hash:
            return
        tasks = {task.task_id: task for task in package.tasks}
        current = {(receipt.task_id, receipt.attempt): receipt for receipt in submission.receipts}
        prefixes = {}
        for receipt in previous.receipts:
            if (receipt.status not in {"failed", "interrupted", "timeout", "spawn_failed"}
                or receipt.task_id not in tasks or receipt.package_hash != package_hash
                or receipt.scope_ids != tasks[receipt.task_id].scope_ids):
                continue
            prefix = prefixes.get(receipt.task_id, ()) + (receipt,)
            try:
                # A per-task failure prefix cannot reproduce aggregate overlap;
                # validate its execution identity, then retain the original record.
                self.execution_report(package, replace(previous, receipts=tuple(replace(item, parallel=False) for item in prefix),
                                      results=(), completed_child_agents=0, active_observations=()))
            except DevflowError:
                continue
            prefixes[receipt.task_id] = prefix
            retained = current.get((receipt.task_id, receipt.attempt))
            if retained is None or digest(retained) != digest(receipt):
                raise DevflowError("GATE_FAILED", "previous failed attempt must be retained unchanged before retry", ExitCode.GATE_FAILED)

    def validate(self, package, submission):
        report = self.validator.validate_submission(package, submission)
        if not report.passed:
            raise DevflowError("GATE_FAILED", "host submission identity or task set is invalid", ExitCode.GATE_FAILED)
        self.execution_report(package, submission)
        results = {r.task_id: r for r in submission.results}
        tasks = {t.task_id: t for t in package.tasks}
        for receipt in submission.receipts:
            if receipt.status != "success":
                continue
            result, task = results[receipt.task_id], tasks[receipt.task_id]
            if result.evidence_queries:
                raise DevflowError("GATE_FAILED", "host reported unverified facts; start a new discover after adapter verification", ExitCode.GATE_FAILED)
            if any(not diagnostic.strip() for diagnostic in result.diagnostics) or not task.segment_ids and (not result.annotations.labels or not result.diagnostics):
                raise DevflowError("GATE_FAILED", "source analysis requires evidence-linked annotations and an independent analysis diagnostic", ExitCode.GATE_FAILED)
            allowed_scopes = [scope for scope in package.facts.scopes if scope.scope.entry_id in task.scope_ids]
            targets = {step.step_id for scope in allowed_scopes for step in scope.steps}
            targets.update(symbol.symbol_id for scope in allowed_scopes for symbol in scope.symbols)
            targets.update(control.control_id for scope in allowed_scopes for control in scope.controls)
            bindings = target_evidence(allowed_scopes)
            for label in result.annotations.labels:
                if label.target_id not in targets or not label.label.strip() or not label.evidence_ids or not set(label.evidence_ids) <= bindings.get(label.target_id, set()) or not label.explanation.strip() or "[REDACTED]" in label.label:
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
