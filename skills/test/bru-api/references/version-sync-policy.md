# API contract version policy

The API Skill keeps `contracts/version-lock.yaml`, `contracts/qa-lock.yaml`,
and the OpenAPI checksum synchronized with the reviewed source and design
inputs. Domain schema versions are independent of the devflow tool version.

Before generation or execution:

1. Read the current OpenAPI contract, source evidence, and Markdown design.
2. Compare the recorded business and OpenAPI revisions with the current
   inputs, including relevant uncommitted changes.
3. Stop when a required revision or anchor cannot be resolved, the source is
   dirty and its impact is ambiguous, or the lock does not match.
4. Regenerate only affected contracts and Bruno cases after the impact is
   understood.
5. Re-run static coverage and lock validation before execution.

Never advance a version lock to hide a mismatch. A draft result must remain
explicitly marked as draft and must not be reported as synchronized. Updating
source or design revisions requires an explicit workflow and the domain's
validation gate.

Use the installed CLI:

```text
devflow bru-api check --qa-root qa --all
devflow bru-api run --qa-root qa
```

Return the redacted `qa/reports/latest.md` report path and exit status.
