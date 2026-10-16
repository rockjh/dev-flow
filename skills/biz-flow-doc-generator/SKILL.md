---
name: biz-flow-doc-generator
description: Inventory registered business entries, then collect source-backed sequence diagrams through native host sub-agents or explicitly authorized serial analysis.
---

Use the installed `devflow` executable and route only through `devflow biz-flow`.
Set the explicit project root with `--project`. Durable project assets are Markdown
under `<project>/docs/biz-flow` and the sole version file
`docs/biz-flow/biz-flow-doc-generator-version.json`. Execution manifests live outside
the project under `~/.local/state/devflow/artifacts/biz-flow/`. The `skill_version`
is `5.2.1` (domain schema 6, host protocol 5.0, adapter 5.2.1). Preserve scope, locks,
ownership, redaction and source fingerprints.

Read [analysis-policy.md](references/analysis-policy.md) for discovery and business
presentation; before every behavior workflow read
[behavior-evidence.md](references/behavior-evidence.md) and
[agent-orchestration.md](references/agent-orchestration.md)
for analysis/delegation. Before acceptance or version changes read
[requirements-matrix.md](references/requirements-matrix.md),
[verification.md](references/verification.md) and
[version-management.md](references/version-management.md).

## 第一步：完整业务入口目录

Run `init` when needed. Older version locks are unsupported; explicitly archive
tool-owned old assets and locks, preserve user content, then initialize a new
5.2.1 project. Do not reinterpret old receipts.
Then run `discover` and `check --stage entries`. The entry
directory gate must pass independently before classification confirmation. Scan the whole project for registered
business triggers, including supported platform receivers such as `doExecute` and
`doServe`. Require registration evidence: ordinary helpers, thread-pool submissions,
Lambda bodies and internal workers are not independent entries. Preserve them for
reachable behavior analysis in step two. Deduplicate registrations and handler
layers belonging to the same trigger; independently registered recovery jobs and
consumers remain entries even when they share business logic.

This step inspects only registration, handler identity, business purpose and module
ownership. It does not expand full call chains, branches or persistence inventories
and requires no agent executor. Every registered candidate must have exactly one
business module or an evidence-backed exclusion. Unsupported/dynamic registration
coverage must be reported; do not claim complete coverage when it is unproven.
Unresolved registration coverage blocks full-scope check/verify/accept even when
known entry counts reconcile. Module acceptance does not prove full delivery.

`discover` puts business scope, the complete entry list, trigger/evidence and
analysis status in the overview. Module Markdown skeletons contain only a title.
Do not put guessed flows or placeholder diagrams in skeletons. Preserve completed
content for unchanged entries when updating. Group by the project's broad business
domains: one domain, one Markdown module. Preserve each entry and channel within
that domain, with one owner per entry. Use source-backed business descriptions and
natural filenames under the naming rules in analysis-policy; project design may
guide naming style but cannot prove current behavior.

Before requesting classification confirmation or ending the turn, directly show
the CLI's entire three-column table (`业务模块文件名`, `业务描述`, `入口数量`),
exclusion categories with counts/reasons, and entry-identification uncertainties
with counts and handling plans. Links or totals cannot replace these tables.
The overview preserves every candidate's ID, trigger, source and disposition;
final module entry sections preserve all included entries. Inventory totals must reconcile.

Ask for classification confirmation once, after resolving facts available in source.
Honor authorization already present in the session; do not ask again. Adjust only
disputed rows and preserve other ownership. Confirmation is recorded with
`<!-- devflow:module-confirmed -->` and bound to the source/mapping fingerprint.
Deep behavior findings do not block inventory delivery or require user classification.

## 第二步：业务分析与时序图

After classification is authorized, run `prepare --project <project> --confirm`.
Analyze only confirmed business entries and their reachable behavior. The CLI
creates frozen read-only entry tasks. The current main Agent must read the package
and `devflow schema biz-flow.submission`, actually start native host child agents,
wait for their results, check scope and evidence, and submit `collect --results`
before `check`, two `verify` calls and `accept`. A prepared package is a normal
handoff requiring continued work. CLI cannot access session tools. Use available
slots, batch independent tasks and reuse idle agents with a separate attempt per
assignment; do not spawn nested agents to bypass slots. CLI merges verified
evidence and writes each module through its unique writer. Coordination owns the inventory and final
gates; it must not fabricate agent results, substitute guessed behavior for failed
agents or let multiple tasks edit one module. Only the current prepare/collect
workflow can submit analysis for source baseline acceptance.

Keep each reachable call target as its complete declaring identity:
fully qualified package/class (including enclosing classes), method and parameter
types, bound to the actual declaration source. Resolve supported `doExecute` and
`doServe` receivers without treating bare method names or caller locations as
capability identities; deduplicate layers of the same registered trigger.
Keep receiver evaluation and local constructor delegation/instance initialization
in execution order. A proven throw stops the normal continuation; preserve catch
and cleanup. Unproven external constructors, class initialization and control
merges remain blocking gaps under behavior-evidence.md.

Every entry requires source-backed participants, ordered business actions, all
result-affecting branches/loops, reads/writes, external side effects, outcomes and
async boundaries. Thread pools appear as execution steps, never additional entries.
Findings are scoped per entry/module; excluded candidates and unrelated source
parsing issues do not count as business-analysis unresolved findings. Critical
unknowns block the affected entry/module, while completed modules may be retained;
any incomplete required entry prevents an overall success claim.

Final entry sections use the fixed order: business title, trigger, function summary,
`sequenceDiagram` with `autonumber`, then branch matrix. Before generating,
modifying or verifying diagrams, read the shared
[diagram-conventions](references/diagram-conventions.md), owned by the
sequence-diagram-generator Skill, and the domain supplements in
[analysis-policy.md](references/analysis-policy.md). A common or domain gate
failure blocks delivery.
Participants and visible actions use business language. Frozen `entry_facts.flow` determines
call/return order and nested controls; analysis supplies evidence-bound business
annotations for every fact and participant. Never change frozen facts, sort them
into a flat sequence or append unconditional success. Independently inspect the
committed source. Missing facts require a typed `evidence_request`, adapter
validation and a newly prepared run; prose cannot clear a critical gap.
Source-bound sender/destination and response steps determine message arrows; technical paths/IDs belong in inventory
metadata, source evidence or Mermaid comments, not visible diagram prose. All real
storage objects retain their exact names and supported Chinese labels. The current
renderer emits one ordered diagram per entry. Do not invent
rules or replace unknown storage objects with generic participants. Follow user's
explicit diagram requirements; Markdown sequence diagrams do not implicitly authorize
Feishu publication or replacing editable boards with SVG.

After prepare/resume, read the returned `behavior_report`: it records selected
module/entry status, gap sources, receiver and declaration bindings, dependency
profile and recovery action. Diagnose each exact binding under
[behavior-evidence.md](references/behavior-evidence.md), never an entire gap code.
Zero gaps still require actual source analysis. Unknown executor scheduling or
rejection policy remains critical, including declared ExecutorService/pool types.

Determine capability from the actual session tools and their responses. Do not
probe brand CLIs or use `DEVFLOW_AGENT_EXECUTOR`; that removed configuration does
not describe session capability. Distinguish unknown, prepared, available but not
started, occupied slots, absent/forbidden tools, launch errors and task failures.
Wait for occupied slots. When tools are absent or launch cannot recover, use an
existing explicit serial choice for this scope, or ask serial/stop once. “Generate
directly” does not authorize serial fallback. Serial requires `serial_approval`
with a choice reference and exact entry scope, and records mode=serial,
degraded=true, parallel=false, completed_child_agents=0. Main Agent must actually
analyze the committed source; static inventory is not an analysis result.

Native mode is valid with parallel=false, including one available slot. Claim
parallel=true only with host intervals or a referenced snapshot observing distinct
children running together. Read the mandatory execution and receipt details in
[agent-orchestration.md](references/agent-orchestration.md). Analysis agents may
write only their exclusive state result path, never source, module documents,
mapping or version locks. Shared workspace plus prompt restrictions is not an OS
sandbox. Preserve actual failures and retries; never take over a failed analysis
while retaining its child ID. Receipts are host-attested: CLI validates binding
and consistency, while the main Agent confirms actual tool calls in this session.
Missing internal times or reclaim tools stay unavailable/unsupported, not invented.

Run `check` and two consecutive `verify` calls. Preserve Git commit plus dirty
state, source fingerprints and incremental added/changed/deleted entry reporting;
advance the source baseline only after acceptance. Stop unsafe paths, stale
fingerprints, ambiguous ownership, redaction failures and failed gates.
Before acceptance, a failed `verify` resets the consecutive pass count; repair
the failure and run both checks again. Verifying an accepted run preserves its
accepted status and validates the fixed commit without restoring extracted source.
Return the complete business overview plus redacted authoritative manifest/report
paths, exit status, coverage, unresolved counts by phase/entry and stability.
Human-facing descriptions and reports are Chinese; IDs and Mermaid keywords stay
machine-compatible.

## Cross-skill routing

When the requested output is a standalone sequence diagram, route to the installed `sequence-diagram-generator` Skill. For this Skill's own documents, inspect project code and registered entries through the biz-flow CLI before writing business diagrams. Keep source-symbol evidence separate from requirement or description segment evidence, and never claim source-backed diagrams without completed code analysis and host-attested receipts.

## Git source snapshot gate

Read only the task's target commit snapshot (`--commit`, or committed HEAD at discovery/prepare). The accepted baseline is used for comparison, not as a substitute for the target. Never read modified or untracked source files as evidence. Source/mapping/task hashes and the version lock are frozen during analysis; accept alone may advance the baseline after passing every gate. Stop on missing or invalid Git evidence.
After successful completion, delete process-only temporary artifacts and retain only owned business assets, the version lock, and authoritative reports or recovery evidence.

## Fixed targets, retries and gates

Use `discover --commit <commit>` and `prepare --commit <commit>` to select a target;
both default to committed HEAD. Every later stage uses the manifest target through
`git archive`; dirty files, untracked files and newer HEAD never become evidence.
Ignore build/dependency/tool directories, committed gitignore rules and repository
info/exclude. A committed `.devflow-biz-flow.json` may add only `exclude: string[]`.
Do not use a project business dictionary. Source labels seed the proposal; user
module names, filenames, descriptions and ownership persist in overview blocks.
Confirmation binds commit, source fingerprint and mapping signature. A changed
binding requires reviewing the overview and one `prepare --confirm`.

All run commands, including resume, require the current domain schema, host
protocol and adapter. Task packages must also declare this domain and protocol.
Reject unsupported records with a new-prepare diagnostic; never convert stored
versions or silently select an older run when the project's latest run is
unsupported. Delivery summaries count only valid current-contract accepted runs.

`prepare --module <name>` scopes delivery; `check`, `verify` and `accept` select that
run with `--run-id`. Partial acceptance reports accepted and blocked modules and
does not advance the whole-project baseline, even when the selected module contains
every entry. `prepare --resume <run-id>` retains
the same task package and reports reusable and pending entry IDs. Reuse validated
results and their original receipts from the manifest/rejected submissions; retry
pending tasks with new attempts and submit complete scope to collect. Failed
collection preserves mapping and recovery evidence. resolutions explain proven
void completion, memory/submit false positives and conditional connectors under
[behavior-evidence.md](references/behavior-evidence.md); they cannot waive unknowns.

Check/verify return authoritative report paths and per-gate
`{gate, executed, passed, errors}`. Missing Mermaid explicitly means structural
validation only. Renderer timeout defaults to 60 seconds and is configurable with
`DEVFLOW_MERMAID_TIMEOUT`; successful rendering is cached by diagram and renderer.
Registration and behavior caches are bound to target, fingerprint and adapter.
Progress goes to stderr. Budget: scan stage 300 seconds, full fixture lifecycle
1800 seconds; report measured elapsed time, never assume a budget passed.
`clean` lists shared runs, `clean --run-id <id>` removes one run and
`clean --all` removes runs and caches. Accepted runs remove extracted source while
retaining source proofs and manifests. Snapshot paths must stay under the run's
state directory without symlink/junction aliases; cleanup failure blocks baseline
advancement. Clean old runs explicitly when no longer
needed; cleaning recovery evidence means a new prepare is required.
Missing rendering blocks document check/verify/accept; install the renderer and
repeat both verify passes. Adjust the Mermaid timeout only after an actual timeout.
Windows snapshot IO and recursive cleanup prefix even short roots, because their
children may exceed MAX_PATH; internal aliases are rejected before hashing.

The host coordination contract has three requirements:

- Record actual child_agent_id, batch_id, task/attempt bindings and status; never
  invent tools, child identities, timestamps or parallel overlap.
- When parallel execution is unavailable, native sequential execution is valid;
  when native agents are unavailable, retain explicit serial approval and its scope.
- Use a declared per-task timeout; record timed_out or launch failure with tool
  evidence, retain history and reassign only pending tasks with the next attempt.
