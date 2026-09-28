---
name: devflow/doc/biz-flow
description: DevFlow biz-flow domain skill.
---

Use the installed `devflow` CLI and the explicitly mapped `devflow/doc/biz-flow` domain. Preserve domain scoped schemas, locks, redaction, ownership and artifact rules.

## Required workflow

Documents live in the project root under `docs/biz-flow`, the only
supported document root. Each business module has exactly one Markdown file. Every
Prefer Swagger/OpenAPI summaries, tags, descriptions, Javadoc, and nearby code
comments for module names. Use the route or source file as a stable fallback
when no explicit description exists. Clearly related entry points sharing that
label belong in the same Markdown file. Every discovered business entry point belongs to exactly one module, including HTTP
and webhook routes, scheduled jobs, XXL-JOB handlers, thread-pool workers,
message consumers, event subscriptions, file/import triggers, and CLI commands.

On first use, run `biz-flow init`, then `biz-flow discover`. Review the
Markdown overview `docs/biz-flow/业务流程覆盖总览.md`, resolve module ownership,
and edit its `devflow:module` directives to merge, split, move, or rename
modules. Record exclusions with `devflow:exclude` directives including a reason
and source evidence. Explicitly confirm the partition (for example with `biz-flow generate
--confirm`). Do not generate documents from an unconfirmed partition. JSON
discovery, progress, and evidence data is process-local and must not remain in
the project.

Use this exact exclusion syntax:
`<!-- devflow:exclude id="<stable-entry-id>" reason="<why excluded>" evidence="<relative/source.java:42>" -->`.
`id` must be discovered, `reason` is required, and `evidence` must be a real
scanned source location in `file:line` form. `evidence="health"` is invalid.
An excluded id must not also appear in a `devflow:module` directive; the CLI
rejects duplicate, unknown, malformed, and overlapping directives.

For Java/Kotlin and other heuristic parsers, record each unresolved finding as
a structured resolution containing source evidence, the confirmed path,
control conditions, and remaining unknowns. Never batch-fill a template or
describe unknown behavior as confirmed. Unknowns affecting entry existence,
ownership, or a key branch block generation; only explicitly marked
non-critical unknowns may remain for human review.

Use `references/requirements-matrix.md` to map each requirement to its code
gate, semantic evidence, and failure behavior before declaring completion.

After a successful generation or update, run `devflow biz-flow verify`. It
executes the durable check twice and fails if Markdown changes between runs or
temporary generation files remain. The verification result is the final
repeatability gate for delivery.

Discover platform-base-class and registry message receivers without requiring
Spring annotations. Resolve topics from constants, configuration, or
registration and trace `serve`, `doServe`, `receive`, and `decode`. Scan
executor `execute`/`submit` independently, including lambdas, method
references, `AsyncContext.wrap`, and custom wrappers; retain an unresolved
finding when a worker cannot be statically resolved.

After module confirmation, orchestration may run one module role per Markdown
file in parallel. Each module role is the sole writer for its file and may
delegate one read-only entry role per entry; entry roles return only structured
steps, branches, evidence, and resolutions. Record input fingerprint, task
boundary, output status, and merge result. Incremental runs skip module
partitioning and schedule only affected module and entry roles.

Each generated module document contains only its entry flow sections. The
confirmed review for every entry must keep each short description field at or
below 200 characters; the CLI rejects longer values. Every entry section has a
Mermaid `sequenceDiagram` with `autonumber`. Preserve branches with
`alt`/`else`, loops with `loop`, and optional interruptions with `opt`. The
generated diagram states protocol success or failure and whether the path
persists data or publishes/sends a message. Use `Note` for non-interrupting
facts such as degraded consistency or an empty snapshot. Never invent
unresolved behavior; resolve it with source evidence or record a structured
resolution.

## Revision-aware updates

Successful generation writes the single-value lock
`biz-flow.yaml` (`git_commit: <commit>`). For `biz-flow update`, read
that commit first, compare it with the target `HEAD`, and inspect all commits in
between. Re-analyze a module when an entry is added, removed, moved, or changed,
or when a shared call, configuration, state rule, persistence, lock, async path,
external integration, or error mapping changes. Remove deleted entries from
their Markdown file, align changed entries, and add new entries to the one
confirmed owning module. If ownership is unclear, the CLI rejects the map until
the caller chooses a new module or an existing module. Update the YAML lock
only after the document and coverage checks pass.

Use `biz-flow check` after generation/update. Its coverage, ownership, source
fingerprint, version, error-evidence, Mermaid, stale-entry, and
description-length checks are the release gate. The durable output is the
Markdown overview, one Markdown file per module, and `biz-flow.yaml`; failed
validation never advances the YAML revision lock.

Module files must use the canonical `NN-中文模块名.md` form. The filename in
each `devflow:module` directive, the `## Module List` row, and the actual file
must match exactly. After `discover`, show the user the proposed module name,
Chinese filename, entry count and IDs, and exclusions with reasons. Generation
and update require the explicit `<!-- devflow:module-confirmed -->` marker
recording that user confirmation; `--confirm` alone is not confirmation.
Mermaid labels are sanitized by the CLI; ASCII semicolons are rejected and
available Mermaid renderers are used for real parsing.
