---
name: devflow/biz-flow-doc-generator
description: Generate source-backed business-flow Markdown with confirmed ownership, delegated analysis, and executable evidence gates.
---

Use the installed `devflow` executable and route this workflow only through
`devflow biz-flow`. The explicit project root is `--project`; the durable
project surface is `<project>/docs/biz-flow`, which may contain Markdown and
the sole `docs/biz-flow/biz-flow-doc-generator-version.json` file. Execution manifests are
authoritative process records under `~/.local/state/devflow/artifacts/biz-flow/`.

Read only the references needed for the current operation:

- [analysis-policy.md](references/analysis-policy.md) for discovery and evidence boundaries.
- [requirements-matrix.md](references/requirements-matrix.md) for the acceptance matrix.
- [agent-orchestration.md](references/agent-orchestration.md) for the task and JSON protocol.
- [verification.md](references/verification.md) and [version-management.md](references/version-management.md) before acceptance or version changes.

The workflow is `init -> discover -> review and explicitly confirm the module
mapping -> generate -> check -> verify`. Stop on unsafe paths, stale source or
mapping fingerprints, ambiguous ownership, missing evidence, redaction failure,
or any failed gate. Do not guess a business rule, storage object, participant,
branch outcome, or external result.

The `skill_version` is `1.0.0`. Before generation, the overview must contain
the explicit `<!-- devflow:module-confirmed -->` marker. Markdown follows a fixed order of business title,
trigger, function summary, `sequenceDiagram`, and the entry branch matrix.

Scan the whole project, including platform receivers such as `doExecute` and
`doServe`, and preserve `core_capabilities`. Generated diagrams use
`sequenceDiagram` and `autonumber`; every read-only entry role is documented by
the structured execution record.

The coordinator scans the project, proposes entries and modules, obtains the
confirmation marker, creates module tasks, and runs final validation. It does
not analyze entry behavior or write module Markdown. The task tree is exactly:

```text
coordinator_task
└── module_task
    └── entry_task
```

Each module task owns one Markdown file and must submit all of its entry tasks
in one `dispatch_batch`, await that batch, validate the merged results, and
then write its file. Entry tasks are read-only and return the complete
structured result (`entry_id`, `source_fingerprint`, `participants`, `calls`,
`branches`, `persistence_actions`, `async_actions`, `external_calls`,
`outcomes`, `unresolved`). Entry tasks never edit Markdown, source code, or the
module mapping. A failed or missing entry result prevents the module from being
complete.

The Python evidence layer independently inventories candidate business branches
and persistence actions through statically registered project language/framework
adapters; the Skill itself does not bind a language, ORM, or storage product.
Stable branch
and persistence IDs must agree between the inventory, entry result, Mermaid
comments, branch matrix, and execution manifest. Unknown reachable business
branches and unresolved real storage names or Chinese display labels stop the
run. A persistence-free entry has no storage participant requirement. Multiple
Mermaid diagrams are allowed for a complex entry when each diagram remains
inside that entry section and all diagrams are included in coverage checks.

The normal runtime requires a real host executor. If none is available, the
result is `DELEGATION_UNAVAILABLE` and no Markdown is generated. A host may be
selected explicitly with `DEVFLOW_AGENT_EXECUTOR`; it must implement the JSONL
protocol in [agent-orchestration.md](references/agent-orchestration.md). Only
an explicit user request for `--allow-degraded` enables serial evidence-based
execution, and its manifest must retain `degraded=true` and `parallel=false`.
Degraded mode still runs the source evidence adapters and every coverage gate;
it may not invent agent prose or silently omit unresolved facts.

Run `devflow biz-flow check` and `devflow biz-flow verify` after generation.
Return the redacted authoritative manifest/report path, exit status, coverage,
unresolved count, and stability result. Human-facing Markdown and report prose
are Chinese; IDs, paths, schema fields, and Mermaid keywords remain machine
compatible.
