---
name: devflow/doc/biz-flow
description: Discover source-backed business entry points and generate confirmed business-flow Markdown.
---

Use the installed `devflow` executable and route only to `devflow biz-flow`.
The project root is the explicit `--project` target. Generated artifacts belong
under `<project>/docs/biz-flow`; do not write toolkit source, credentials, or
process-local JSON outside that root. Preserve core schemas, redaction, locks,
ownership, and artifact paths.

## Workflow and ownership

1. Run `devflow biz-flow init`, then `devflow biz-flow discover`.
2. Scan the whole project repository before deciding modules. Include source,
   configuration, registrations, platform base classes, HTTP/webhook routes,
   message consumers and topics resolved from constants/config/registration,
   event listeners, file/import triggers, CLI commands, async workers,
   schedulers, and XXL-JOB `doExecute` handlers. Handle cross-line Java
   signatures and platform receivers such as `doServe`. Ignore `.idea`, logs,
   caches, build output, generated/vendor assets, and other non-business paths;
   they must not become entries or affect source-change decisions.
3. Deduplicate entry IDs and `core_capabilities`. Assign each entry to one
   short business-responsibility module. Keep uncertain ownership as `待确认`;
   never infer ownership from URL, topic, controller, class, or directory
   alone. Exclusions require a reason and real `file:line` evidence:
   `<!-- devflow:exclude id="..." reason="..." evidence="path:line" -->`.
4. Show the user the proposed module names, files, entry IDs/triggers, and
   exclusions before generation. Record the user's confirmation in the module
   map and require `<!-- devflow:module-confirmed -->`; `--confirm` alone is
   insufficient.
5. After confirmation, run one module role per Markdown file. That role is the
   sole writer for its file and must start one read-only entry role for every
   entry. Entry roles return structured analysis only; they never edit files.
   Record entry, function, participants, ordered calls, every reachable branch,
   loops, async work, persistence, external calls, success/failure outcomes,
   source evidence, and unresolved questions. Re-analyze affected entries and
   shared call chains on incremental updates.

Read only the workflow references needed for the operation, beginning with
`references/analysis-policy.md`, `references/requirements-matrix.md`, and
`references/verification.md`.

## Generated document contract

Each module file has a short business title and one section per entry. Every
entry section uses this fixed order:

1. **Business title**: a short business description such as `设备关系同步` or
   `SIM批量导入`, never a URL, topic, class, method, or path.
2. **Entry description**: a concise trigger such as `POST /v0/internal/...`,
   `TOPIC SD-MNO-terminal-device_report`, or `XXL-JOB 每日用量统计`. Do not put
   source paths, line numbers, or full class names here.
3. **Business function**: one sentence for a simple flow, or source-backed
   bullets for normal, empty, duplicate, invalid-state, external-failure,
   asynchronous, and exception cases. Never invent rules.
4. **Business sequence diagram**: a Mermaid `sequenceDiagram` with
   `autonumber` and this default init header:

   ```mermaid
   %%{init: {"sequence": {"actorMargin": 150, "diagramMarginX": 30, "wrap": true}}}%%
   sequenceDiagram
       autonumber
   ```

Use concrete participants known from source (for example XXL-JOB, RCP平台,
RCP数据库, or mno-operator), and name actual actions, conditions, queries,
responses, writes, transactions, message publication/consumption, async
submission, return values, and exception propagation. Use `alt`/`else` for
branches, `loop` for iteration, and `opt` only for genuinely optional paths.
Do not replace known facts with “current system”, “database”, “call service”,
or “process data”. Every analyzed branch must have a diagram path; unresolved
key behavior blocks generation and non-critical unknowns remain explicitly
recorded with evidence.

## Gates and updates

Run `devflow biz-flow check` after generation/update. It must validate unique
ownership, exclusions, business short titles, section order, absence of source
paths/line numbers in human-readable text, one diagram per entry, concrete
participants/actions, branch coverage, Mermaid syntax, and intact structured
`devflow` markers in the final Markdown. Run `devflow biz-flow verify`; it runs
the durable check twice and must report `stable=true`. If no Mermaid renderer is
available, report the structural validation scope explicitly.

Update `biz-flow.yaml` only after document and coverage checks pass. Compare
the locked revision to the target, add/remove/move entries accurately, and
preserve stable IDs, module ownership, order, and content when source and
confirmed partition are unchanged.
