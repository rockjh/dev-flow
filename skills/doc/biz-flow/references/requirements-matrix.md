# Biz-flow Requirements Gate Matrix

This matrix is the review index for requirements 1-16. The CLI and document
layer enforce the machine column; the resolution column remains explicit human
evidence and is rejected when it is missing or stale.

| Requirement | Machine gate | Semantic evidence / failure location |
| --- | --- | --- |
| 1 | `discover` registers `message` entries and async parent/worker edges | source `file:line`, topic/registration and handler; unresolved blocks key paths |
| 2 | parser validates `devflow:exclude` fields, `file:line`, and overlap | CLI reports directive and evidence |
| 3 | overview and artifacts use atomic replacement; reviews are never promoted | failed run retains prior Markdown and prints recovery path |
| 4 | unresolved/resolution schema requires evidence, path, controls, unknowns | critical unresolved findings block `generate` |
| 5 | placeholder and skeleton text are rejected by `check` | review status and evidence identify missing business semantics |
| 6 | discovery writes `module_suggestions` grouped by source path | human confirms module boundaries in overview |
| 7 | title must come from source description or explicit override | generated skeleton is marked `title_unresolved`; durable `check` rejects delivery |
| 8 | each section starts with an objective `入口类型` paragraph | coverage reports `missing-entry-introduction` |
| 9 | business points are bullets and each is at most 50 characters | apply/check report entry ID and field |
| 10 | Mermaid structural validator reports line and syntax point; `mmdc` is used when present | renderer output is preserved as failure evidence |
| 11 | controls, errors, and evidence are compared against source-derived facts | unresolved branches require structured resolution |
| 12 | `orchestration.py` creates module single-writer and entry read-only tasks with fingerprint/status/merge fields | scheduler records task boundary and merge result |
| 13 | overview table includes stable ID, description, trigger, module file, kind, source | check compares table IDs to discovered IDs and directives |
| 14 | uniqueness, coverage, ownership, evidence, status, placeholders and diagrams are code gates | semantic gaps remain unresolved with evidence |
| 15 | `biz-flow verify` repeats durable `check`, compares Markdown hashes, and rejects temp files | final verify JSON is the repeatable record |
| 16 | executor `execute`/`submit` wrappers are scanned independently, including lambdas and method references | unresolved wrapper keeps submit source and blocks silent omission |
