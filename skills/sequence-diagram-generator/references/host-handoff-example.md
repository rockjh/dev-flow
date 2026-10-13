# Native session handoff example

This example is a field conversion guide, not an execution receipt. It neither launches an agent from Python nor invents an agent ID. Use the installed schema and actual current-session tool results.

For an authorized local project with two independent source entries:

```text
devflow sequence-diagram-generator init --project <absolute-project>
devflow sequence-diagram-generator discover --project <absolute-project> --intent implementation --entry <complete-symbol-1> --entry <complete-symbol-2>
devflow sequence-diagram-generator prepare --project <absolute-project> --run-id <returned-run-id> --confirm
devflow schema sequence-diagram-generator.host-task-result
devflow schema sequence-diagram-generator.host-submission
```

Read the returned package. In this session's actual host tools, start the first task using its frozen questions, scope, facts, package hash, committed-source identity and result location. If a free slot remains, start the second task. Retain actual returned identities and call/message references. Wait for results, checking them against task ownership. If status tools actually show both running in one snapshot, retain that snapshot; otherwise keep `parallel=false`. One native slot is valid.

The following Python only converts already collected tool records to the installed typed schema. `actual_results`, `actual_children`, `actual_tool_refs` and `actual_permission_enforcement` must come from this session; do not populate them with sample IDs or assumed capabilities. Results must be the children's own HostTaskResult documents. When precise times and reclamation tools are unavailable, empty times and `unsupported` are honest. If a host provides release tools but release was not observed, use `not_observed` instead. This simple example has one successful attempt per task; retain real failed attempts when they occur.

```python
import json
from pathlib import Path
from toolkit.sequence_diagram_generator.models import HostReceipt, HostSubmission, HostTaskResult, TaskPackage
from toolkit.sequence_diagram_generator.repository import digest, from_dict, to_dict

package = from_dict(TaskPackage, json.loads(Path(authoritative_package_path).read_text(encoding="utf-8")))
results = tuple(from_dict(HostTaskResult, actual_results[task.task_id]) for task in package.tasks)
receipts = tuple(
    HostReceipt(
        task_id=task.task_id,
        package_hash=digest(package),
        result_hash=digest(result),
        status="success",
        child_agent_id=actual_children[task.task_id],
        tool_references=tuple(actual_tool_refs[task.task_id]),
        started_at="", ended_at="", reclaimed_at="",
        execution_approval="", scope_ids=task.scope_ids,
        degraded=False, parallel=False, child_count=1,
        attempt=result.attempt, time_source="unavailable",
        reclaim_state="unsupported", record_origin="host-attested", error="",
    )
    for task, result in zip(package.tasks, results)
)
submission = HostSubmission(
    run_id=package.run_id, package_hash=digest(package), receipts=receipts, results=results,
    completed_child_agents=len({receipt.child_agent_id for receipt in receipts}),
    active_observations=(), permission_enforcement=actual_permission_enforcement,
)
# Run repository serialization redacts authoritative output; scrub raw child material
# and session references before writing this explicit handoff file as well.
from toolkit.core.redaction import redact
output = Path(package.handoff_root).parent / "submission.json"
output.write_text(json.dumps(redact(to_dict(submission)), ensure_ascii=False, indent=2), encoding="utf-8")
```

Submit that state file, then perform the existing domain gates:

```text
devflow sequence-diagram-generator collect --project <absolute-project> --run-id <returned-run-id> --results <absolute-state-submission>
devflow sequence-diagram-generator check --project <absolute-project> --run-id <returned-run-id>
devflow sequence-diagram-generator verify --project <absolute-project> --run-id <returned-run-id>
devflow sequence-diagram-generator accept --project <absolute-project> --run-id <returned-run-id>
```

Preserve `manifest.json`, `host-submission.json`, `host-execution-report.json`, domain validation/verification and actual session references. Report preparation, child execution, result collection and acceptance independently. A missing renderer is disclosed as `not_run`; fixture tests and local structure verification are not actual native host execution evidence.
