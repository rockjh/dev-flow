# Verification

`check --project <root> --run-id <id> [--stage entries] [--full]` is strictly read-only. Full reports are returned through the core envelope; check does not write a report or change verification counters.

Collect validates identities, evidence, requirement mapping, model coverage and the structured sequence tree. Mermaid and matrix come from the same tree. Control exits, call contexts and dependencies must agree. Complete IDs do not justify reordered actions, wrong branches, cleanup loss, actions after termination or dispatch portrayed as completion. Critical scanner gaps are independent of diagram coverage and block affected units.

`verify --project <root> --run-id <id>` re-reads unchanged sources and frozen requirements, independently rebuilds using the same validated host annotations and compares normalized digests. It never calls the host again for a fresh semantic interpretation. Reproducibility proves deterministic reconstruction for those inputs, not absolute correctness of business meaning.

Installed absolute-path mmdc is invoked directly without npx download or target npm scripts. `passed` means actual render success; `not_run` means missing renderer and may pass local structure acceptance with disclosure; `failed` blocks. Report code scope, source-section accounting, implementation consistency, parser boundaries, host-attested execution, render and acceptance separately.
