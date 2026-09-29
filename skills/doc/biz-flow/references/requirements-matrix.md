# Biz-flow Requirements Gate Matrix

Use this matrix before declaring a run complete. CLI schemas, generated
reports, and the final Markdown are authoritative; prose analysis must cite
source evidence for every semantic claim.

| Requirement | Required gate | Failure evidence |
| --- | --- | --- |
| R1 Whole scan | Discovery covers source/config registrations, platform bases, HTTP/webhook, messages/topics, events, imports, schedulers/XXL-JOB, async, and CLI; excludes non-business paths | Candidate source location and scanner reason |
| R1 Deduplication | Entry IDs and `core_capabilities` are unique | Duplicate IDs/capabilities in discovery report |
| R2 Module confirmation | Every entry has exactly one responsibility module or explicit `待确认`; exclusions have reason and real `file:line` evidence; user confirmation is recorded | Module map, overview, and confirmation marker |
| R3-R5 Delegation | Main role owns scan/partition; each module has one writer; each entry has one read-only analysis result | Orchestration task boundary, fingerprint, status, and merge record |
| R5 Evidence | Entry result contains function, participants, ordered calls, all reachable branches, loops, async, persistence, external calls, outcomes, source evidence, and unresolved questions | Structured entry review; critical unknowns block generation |
| R6-R8 Diagram fidelity | Concrete participants and actions; `alt`/`else`, `loop`, and `opt` represent source-backed paths; every entry has `sequenceDiagram` and `autonumber` | Final Markdown diagram validation |
| R9 Structure | Business title, trigger, function, diagram appear in fixed order; human text has no source paths/line numbers; markers survive redaction | `check` reports section, marker, or redaction violation |
| R9 Mermaid | Structural syntax is valid; use a renderer when available and report structural-only scope otherwise | Renderer output or structural validator location |
| R10 Stability | Stable IDs, ownership, order, and content for unchanged source/partition; lock advances only after coverage checks | `verify` twice returns `stable=true` |

Never replace an unknown with a guessed rule or a generic participant. Record
the evidence and unresolved reason, and stop generation when it affects entry
existence, ownership, or a key business branch.
