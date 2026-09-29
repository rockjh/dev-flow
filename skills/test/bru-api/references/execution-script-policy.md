# Bruno API execution policy

Generated projects contain Bruno requests, fixtures, contracts, execution configuration, and Markdown documentation only. They do not contain a copied runner, checker, or toolkit source. Execute only the installed commands:

Scenario and common business modules import evidence, preflight, polling, and restoration helpers from `devflow.e2e_runtime`; never recreate those helpers under `common/`.

```text
devflow bru-api check --qa-root qa --all
devflow bru-api preflight --qa-root qa
devflow bru-api run --qa-root qa
```

The runner validates contracts, locks, static coverage, the configured environment, and the Bruno collection before sending requests. It writes the single redacted human-facing report to `qa/reports/latest.md`.

Raw Bruno JSON, normalized evidence, logs, and preflight files are temporary process data and are removed after the command finishes. They must not be copied into `qa/` or committed as formal assets.

Stop on missing evidence, unsafe or ambiguous targets, failed validation, version-lock mismatch, or cleanup failure. The project `qa/.devflow.lock.json` binds execution to the installed release and API schema version.
