---
name: devflow/doc/biz-flow
description: DevFlow biz-flow domain skill.
---

Use the installed `devflow` CLI and the explicitly mapped `devflow/doc/biz-flow` domain. Preserve domain scoped schemas, locks, redaction, ownership and artifact rules.

## Required workflow

Documents live in the project root under `docs/biz-flow`, the only
supported document root. Each business module has exactly one Markdown file. Every
discovered business entry point belongs to exactly one module, including HTTP
and webhook routes, scheduled jobs, XXL-JOB handlers, thread-pool workers,
message consumers, event subscriptions, file/import triggers, and CLI commands.

On first use, run `biz-flow init`, then `biz-flow discover`. Review
`biz-flow-modules-draft.json`, move every entry to one module, exclude only
non-business candidates with source evidence, and explicitly confirm the module
map before generation. Do not generate documents from an unconfirmed map.

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

Use `biz-flow check` after generation/update. Its coverage, ownership,
source fingerprint, version, error-evidence, Mermaid, stale-entry, and
description-length checks are the release gate; do not bypass them by editing
generated JSON. The writer records `biz-flow.yaml` only after this gate
passes, so a failed update cannot advance the documented Git revision.
