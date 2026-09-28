# Repeatable Verification

Run these commands from the repository root after changing the Skill or the
domain implementation:

```text
python -m pytest -q
python -m compileall -q devflow tests
git diff --check
devflow biz-flow init --project <fixture>
devflow biz-flow discover --project <fixture>
devflow biz-flow generate --project <fixture>
devflow biz-flow check --project <fixture>
devflow biz-flow verify --project <fixture>
```

For an update fixture, repeat `discover`, edit the source to add/change/delete
an entry, run `devflow biz-flow update`, then run `check` and `verify`. Inject
one malformed exclusion, one invalid evidence location, one placeholder step,
one overlong business point, and one malformed Mermaid block; each must fail
with the entry id or source location in the error. Run `verify` twice and
compare its `stable` result and Markdown document count.

