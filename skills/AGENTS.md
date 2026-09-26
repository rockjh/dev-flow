# Skill Authoring Rules

These rules apply to every installable Skill below `skills/` and are
in addition to the repository `AGENTS.md`.

## Required shape

Each Skill has exactly this contract:

```text
<category>/<skill-name>/
  SKILL.md
  agents/openai.yaml
  references/            # optional, but every referenced file must exist
```

`SKILL.md` frontmatter must contain a stable `name` matching the full
`devflow/<category>/<skill-name>` path and a short, accurate `description`.
The body must identify the command route, input/project boundaries, required
workflow, validation gates, and authoritative report or artifact returned.

`agents/openai.yaml` must contain one `interface` with the project-required
fields `display_name`, `short_description`, and `default_prompt`. Documented
optional fields such as icons, invocation policy, and tool dependencies are
allowed. The prompt is an instruction supplement, not the sole enforcement
layer. It must:

1. select only this Skill's domain route;
2. use the installed `devflow` executable;
3. read only the references needed for the selected workflow;
4. preserve schemas, locks, ownership, safety, redaction, and artifact rules;
5. stop on missing evidence, ambiguity, unsafe targets, or failed gates; and
6. return the redacted authoritative result or its path and exit status.

Do not claim capabilities that are not implemented by the CLI. Do not put
domain instructions for another Skill in this prompt.

## Reference and change rules

References are loaded deliberately, using paths relative to the Skill. Keep
normative rules in one canonical reference instead of copying conflicting
versions into multiple Skills. Examples must be clearly labeled and must not
look like live project state or contain secrets.

Changes to a Skill must preserve the existing domain's business semantics.
If a change affects a project root, generated file, lock, schema, redaction,
or exit behavior, update the CLI contract and tests with the Skill text.
Never weaken a safety or ownership gate to make a prompt appear successful.

The canonical tree under `skills/` is the source of truth. The npm tree is
generated output under `npm/skills/devflow/` and must be refreshed by
`scripts/release.py`; do not hand-edit only the npm copy. Before release, verify
that each canonical Skill
has one matching npm copy and that no legacy Skill directory remains.

## Acceptance checks

For a new or changed Skill, verify:

- frontmatter, directory name, prompt route, and lock `skill` value match;
- every prompt-referenced file exists and is within the Skill directory;
- unsafe, ambiguous, and validation-failure paths are explicit;
- outputs are redacted and point to the authoritative artifact when large;
- canonical and npm trees are identical after the release staging step; and
- the repository verification commands in the root `AGENTS.md` pass.
