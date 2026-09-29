---
name: devflow/test/bru-api
description: Generate and execute Bruno API tests with Markdown documentation and reports.
---

Use the installed `devflow` CLI and route only API test work to
`devflow/test/bru-api`. The project root is `qa/` unless `--qa-root` is
explicitly supplied. Read OpenAPI, source evidence, and these references
before generation: `references/coverage-manifest.md`,
`references/fixture-policy.md`, `references/execution-config.md`,
`references/execution-evidence.md`, `references/version-management.md`, and
`references/version-sync-policy.md`. Read `references/database-access.md` and
`references/integration-policy.md` when selected cases use those integrations.
Stop on missing evidence, unsafe targets, ownership ambiguity, or a failed
validation gate.

Keep executable assets machine-readable: `bruno/**/*.bru`, `fixtures/**/*` in
JSON/CSV/SQL, OpenAPI JSON, contract YAML, `execution/config.yaml`, and Bruno
environment files. Keep human-facing material in Markdown, including
`contracts/README.md`, `contracts/modules/**/CASES.md`, `design/**/*.md`, and
`reports/**/*.md`.

Run initialization, contract generation, Bruno materialization, Markdown
documentation, Mermaid `sequenceDiagram` flows, static checks, execution, and
reporting in that order. Write the single authoritative `qa/reports/latest.md`.
Raw JSON, logs, and temporary files are process-local and must be removed
before completion. Keep history only for an explicit audit request.

Return the redacted `latest.md` path and exit status. Never guess inputs or
bypass a failed gate.
