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

The workflow is `init -> discover -> review the module table and suggested
exclusions -> adjust only disputed rows when needed -> confirm once -> generate
-> check -> verify`. The discover overview is the user-facing boundary. It
contains a Chinese module table followed immediately by a suggested exclusion
table. Every module shows its Chinese responsibility, complete readable entry
list, count, and stable Markdown file. Every entry shows a stable ID, Chinese
business name or technical label, adapter-normalized trigger and identifier,
source evidence, scope status (`business`, `excluded`, or `待确认`), and an
exclusion reason when excluded. The list is complete; long lists may use
Markdown details blocks. Names must come from registered source/framework
adapter evidence. Never invent business rules or names: unresolved in-scope
entries display `待确认` and block generation, while technically excluded
candidates may use a technical label when exclusion evidence is complete.
The full structural machine map remains authoritative and each presentation
name stays linked to its stable entry ID. Stop on unsafe paths, stale source or
mapping fingerprints, ambiguous ownership, missing evidence, redaction failure,
or any failed gate. A default confirmation is sufficient when the user has no
adjustment; an adjustment must preserve unaffected entry ownership.

The `skill_version` is `1.1.0`. Before generation, the overview must contain
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
`outcomes`, `unresolved`, `business_name`, `trigger_summary`, `source_evidence`,
`scope_status`, `exclusion_reason`). Entry tasks never edit Markdown, source code, or the
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

The runtime first honors `DEVFLOW_AGENT_EXECUTOR`, then probes the static
built-in Codex/Claude adapters without writing files or changing the
environment. Built-in adapters start one restricted, temporary CLI child
per entry and run the entries in a module batch concurrently; the runtime
merges their structured results and owns Markdown rendering. Each adapter owns
its CLI arguments and translates to the single JSONL protocol in
[agent-orchestration.md](references/agent-orchestration.md);
the Skill never assumes private CLI flags are universal. If no adapter passes
the capability probe, the result is `DELEGATION_UNAVAILABLE` and no Markdown is
generated. Only an explicit user request for `--allow-degraded` enables serial
evidence-based execution, and its manifest must retain `degraded=true` and
`parallel=false`. No command writes shell configuration or user environment
variables.
Degraded mode still runs the source evidence adapters and every coverage gate;
it may not invent agent prose or silently omit unresolved facts.

Run `devflow biz-flow check` and `devflow biz-flow verify` after generation.
Return the redacted authoritative manifest/report path, exit status, coverage,
unresolved count, and stability result. Human-facing Markdown and report prose
are Chinese; IDs, paths, schema fields, and Mermaid keywords remain machine
compatible.
