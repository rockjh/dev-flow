# Example comparison

The order example follows the publishable shape of `user-login`:

- `app.py` and `README.md` are source evidence and workflow instructions.
- `docs/biz-flow/业务流程覆盖总览.md` records the confirmed module partition.
- `docs/biz-flow/00-业务模块.md` contains one entry section, one Mermaid sequence diagram with `autonumber`, and a branch matrix.
- `docs/biz-flow/biz-flow.yaml` records the successful source revision.
- `check` and `verify` pass; `verify` reports `stable=true`.

The order flow adds idempotent replay, product lookup, stock reservation, payment failure, order persistence, and `orders.created` publication. Its source uses explicit table membership/indexing and slice assignment so discovery reports `unresolved=0`.

Fixes made during the repeated run:

1. Error extraction now prefers the literal attached to `raise`, so `PAID` is not reported as an error code instead of `PAYMENT_FAILED`.
2. Python `if` statements are retained as branch evidence even when localized behavior labels are unavailable.
3. Coverage compares the same normalized Mermaid text that rendering emits and does not require explanatory text on Mermaid `end` markers.

The existing login lock still points at the older repository commit and reports `version_match=false` against the current root HEAD. That is a stale baseline lock, not a failure of the new order flow.
