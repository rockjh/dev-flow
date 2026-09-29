# Bruno Execution Evidence And Results

Static manifests prove intent. Normalized evidence proves what ran, and result reports explain what happened.

The runner keeps Bruno's raw report and normalized evidence only in a process
temporary directory. It removes headers, redacts sensitive keys and
token-shaped values, and limits response size/depth. Temporary evidence is
never written below `qa/`.

```text
%TEMP%/qa-bruno-<run-id>/execution-evidence.json
```

Pass status requires an executed request, successful request status, no runtime error, at least one assertion/test observation, and every observation passing. A top-level Bruno `pass` value alone is insufficient.

Database assertion steps register Bruno `test` observations and fail the owning case on connection, query, expectation, or cleanup errors. Persist only the bounded assertion outcome in Bruno's normalized evidence; do not retain connection strings, credentials, or full database rows/documents.

Normalized evidence contains `executed`, `passed`, and per-case actual HTTP status, redacted response body/shape, and assertion/request failure detail. Successful observations may be written to `observed-rules.yaml` for audit only; they are never reused to change design expectations or generated assertions.

For every design-generated `flows.yaml` entry, normalized evidence also records
ordered step status, capture/use names, absence verification, and cleanup
verification. Capture/use/absence names come only from passing, uniquely named
`devflow:flow:*` Bruno test observations in the raw reporter output; the
materialized case contract supplies only the expected names. Missing events,
duplicate case IDs, failed events, or out-of-order steps fail reconciliation.

## Result Report

Every attempted run overwrites the single human-facing report at
`qa/reports/latest.md`, including static/preflight failures that prevented
requests. No JSON result report is retained.

```json
{
  "summary": {
    "total": 12,
    "executed": 10,
    "passed": 8,
    "failed": 2,
    "not_executed": 2
  },
  "modules": [],
  "failures": [],
  "not_executed": [],
  "manual_confirmation": []
}
```

Every failed or not-executed row contains module, case ID, interface, request summary, expected result/assertions, actual result, failure reason, failure categories, and `needs_manual_confirmation`.

Allowed categories are:

- `generation_failure`
- `insufficient_data`
- `environment_unavailable`
- `endpoint_unreachable`
- `request_failure`
- `assertion_failure`
- `insufficient_source_evidence`
- `manual_confirmation`

Do not replace these with one generic status. Static coverage, OpenAPI obligations, design traceability, and version warnings are supplemental fields.

## Module Evidence

Module runs validate `module-lock.yaml`, write only module-owned logs/evidence/results, and never update global locks or completion state. Generation must reach zero `manual_confirmation` items before a module is runnable; execution reports retain the field only to expose a gate failure, never to waive completion requirements.

The coordinator validates and merges module evidence before the final all-module run.

The coordinator runs all selected modules in one invocation, so no separate
aggregation command or module result directory exists. The shared
post-execution constraints scan contracts, Bruno requests, and the Markdown
report for credentials before completion.

## Mock-data Ledger

Each preparation attempt writes a redacted ledger below the process temporary
run directory. The ledger is deleted after cleanup and is never delivered as a
QA asset.

If preparation is denied or fails, cases with setup steps are reported as `not_executed` with an insufficient-data reason; unrelated cases remain runnable. A retained or interrupted run can be cleaned later by its run ID.
