---
name: biz-flow-doc-generator
description: Inventory registered business entries, then collect source-backed sequence diagrams through native host sub-agents or explicitly authorized serial analysis.
---

Use the installed `devflow` executable and route only through `devflow biz-flow`.
Set the explicit project root with `--project`. Durable project assets are Markdown
under `<project>/docs/biz-flow` and the sole version file
`docs/biz-flow/biz-flow-doc-generator-version.json`. Execution manifests live outside
the project under `~/.local/state/devflow/artifacts/biz-flow/`. The `skill_version`
is `3.0.0`. Preserve scope, locks, ownership, redaction and source fingerprints.

Read [analysis-policy.md](references/analysis-policy.md) for discovery and business
presentation; read [agent-orchestration.md](references/agent-orchestration.md) only
for analysis/delegation. Before acceptance or version changes read
[requirements-matrix.md](references/requirements-matrix.md),
[verification.md](references/verification.md) and
[version-management.md](references/version-management.md).

## 绗竴姝ワ細瀹屾暣涓氬姟鍏ュ彛鐩綍

Run `init` when needed. Older version locks are unsupported; archive the old
project and initialize a new 3.0.0 project.
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

`discover` creates the overview and each module's Markdown inventory skeleton:
business title, scope, complete entry list, trigger/evidence and analysis status.
Do not put guessed flows or placeholder diagrams in skeletons. Preserve completed
content for unchanged entries when updating. Group first by the project's broad
business domains: one domain, one Markdown module. Keep different objects, duties,
scenarios, channels and trigger types in entry sections within that domain; never
split files merely by create/query/configuration/callback/recovery actions. Cross-domain
entries have one owner, the domain of their primary business outcome, with collaborators
shown in the sequence diagram. Domain names come from project evidence and user
classification, not a fixed domain dictionary. Module filenames use natural business
objects plus their core responsibility, relationship or lifecycle, so readers can
infer the main contents. Group related functions into meaningful families for a broad
domain; do not concatenate all action verbs or enforce suffixes such as 鈥滃鐞嗏€?
鈥滀笟鍔♀€?or 鈥滄祦绋嬧€? Existing project business-document names may guide style, but
must not become a project-specific naming dictionary. Do not use a bare domain/acronym
or split a domain by function. Business descriptions are independent of filenames:
use Swagger `@Tag.description` and `@Operation.summary/description`, then source
comments for non-HTTP triggers, to summarize the actual business objects and main
capabilities. Merge related interfaces such as list/detail queries and CRUD;
retain distinct actions such as opening and closing a plan. Semicolons and multiple
sentences are allowed. Do not prefix a filename summary with 鈥滆礋璐ｂ€? enumerate
every endpoint or include client/HTML metadata. Limit shared controller descriptions
to entries owned by the module; keep the complete inventory separately.
See analysis-policy for naming and identity rules.

Before requesting classification confirmation or ending the turn, directly show
the CLI's entire three-column table (`涓氬姟妯″潡鏂囦欢鍚峘, `涓氬姟鎻忚堪`, `鍏ュ彛鏁伴噺`),
exclusion categories with counts/reasons, and entry-identification uncertainties
with counts and handling plans. Links or totals cannot replace these tables.
The overview preserves every candidate's ID, trigger, source and disposition;
module files preserve all included entries. Inventory totals must reconcile.

Ask for classification confirmation once, after resolving facts available in source.
Honor authorization already present in the session; do not ask again. Adjust only
disputed rows and preserve other ownership. Confirmation is recorded with
`<!-- devflow:module-confirmed -->` and bound to the source/mapping fingerprint.
Deep behavior findings do not block inventory delivery or require user classification.

## 绗簩姝ワ細骞惰涓氬姟鍒嗘瀽涓庢椂搴忓浘

After classification is authorized, run `prepare --project <project> --confirm`.
Analyze only confirmed business entries and their reachable behavior. The CLI
creates bounded parallel, read-only entry tasks, merges their evidence and commits
each module through its unique writer. Coordination owns the inventory and final
gates; it must not fabricate agent results, substitute guessed behavior for failed
agents or let multiple tasks edit one module. The removed review/generate/update
paths are not compatibility aliases and cannot advance the source baseline.

Keep each reachable `core_capabilities` identity as its complete declaring identity:
fully qualified package/class (including enclosing classes), method and parameter
types, bound to the actual declaration source. Resolve supported `doExecute` and
`doServe` receivers without treating bare method names or caller locations as
capability identities; deduplicate layers of the same registered trigger.

Every entry requires source-backed participants, ordered business actions, all
result-affecting branches/loops, reads/writes, external side effects, outcomes and
async boundaries. Thread pools appear as execution steps, never additional entries.
Findings are scoped per entry/module; excluded candidates and unrelated source
parsing issues do not count as business-analysis unresolved findings. Critical
unknowns block the affected entry/module, while completed modules may be retained;
any incomplete required entry prevents an overall success claim.

Final entry sections use the fixed order: business title, trigger, function summary,
`sequenceDiagram` with `autonumber`, then branch matrix. Participants
and visible actions use business language. Ordered `review.steps` determines real
call/return order and nested controls; bind canonical B/P evidence to those steps,
never sort the inventory into a flat sequence or append unconditional success.
Source-bound sender/destination and response steps determine message arrows; technical paths/IDs belong in inventory
metadata, source evidence or Mermaid comments, not visible diagram prose. All real
storage objects retain their exact names and supported Chinese labels. Complex
entries may use multiple diagrams with complete combined coverage. Do not invent
rules or replace unknown storage objects with generic participants. Follow user's
explicit diagram requirements; Markdown sequence diagrams do not implicitly authorize
Feishu publication or replacing editable boards with SVG.

Do not probe brand CLIs or `DEVFLOW_AGENT_EXECUTOR`; that configuration is removed. prepare only creates a redacted task package. The current host session decides whether native sub-agents are available. If unavailable, ask exactly once whether the current Agent may perform serial read-only analysis or stop with the entry directory. Serial mode requires explicit user choice and is recorded as mode=serial, degraded=true, parallel=false, and zero child agents. Native execution uses host tool records; never fabricate child-agent evidence.

Run `check` and two consecutive `verify` calls. Preserve Git commit plus dirty
state, source fingerprints and incremental added/changed/deleted entry reporting;
advance the source baseline only after acceptance. Stop unsafe paths, stale
fingerprints, ambiguous ownership, redaction failures and failed gates.
Return the complete business overview plus redacted authoritative manifest/report
paths, exit status, coverage, unresolved counts by phase/entry and stability.
Human-facing descriptions and reports are Chinese; IDs and Mermaid keywords stay
machine-compatible.

## Cross-skill routing

When the requested output is a standalone sequence diagram, route to the installed `sequence-diagram-generator` Skill. For this Skill's own documents, inspect project code and registered entries through the biz-flow CLI before writing business diagrams. Keep source-symbol evidence separate from requirement or description segment evidence, and never claim source-backed diagrams without completed code analysis and host-attested receipts.
