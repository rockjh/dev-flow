# devflow Repository Rules

These rules apply to the whole repository. A deeper `AGENTS.md` may add
constraints but may not relax them.

## Architecture

- The repository, Python package, public CLI, and npm installer are `devflow`;
  the npm package is `dev-flow`.
- The only console entry point is `devflow = devflow.cli:console_main`.
  `python -m devflow` calls that same entry point.
- Shared contracts live in `devflow/core/`; domain modules live in
  `devflow/bru_api/`, `devflow/test_e2e/`, and `devflow/doc_biz_flow/`.
  The installable Skills live under `skills/<category>/<skill-name>/`; they are
  installed under `~/.agents/skills/devflow/<category>/<skill-name>/`.
- Commands use static registration. Do not add dynamic plugin discovery,
  runtime scanning, compatibility facades, placeholder modules, or a second
  extension mechanism.
- Do not restore legacy package/command names, the old Skill directories, old
  npm wrappers, a second `pyproject.toml`, or copied toolkit source in generated
  projects.

## Contracts

`devflow/core/envelope.py`, `errors.py`, `schema.py`, `redaction.py`, and
`artifacts.py` are authoritative for envelopes, exit codes, scoped schemas,
redaction, artifacts, and locks. All domains route results through this core.
Pipelines default to JSON, TTYs to Markdown, progress goes to stderr, and
large results return a summary plus an authoritative path unless `--full` is
requested. Domain schema versions are independent of the tool version.

The active domains are `bru-api`, `e2e`, and `biz-flow`. Preserve their
existing business, safety, ownership, and report semantics while changing only
the package, CLI, Skill, state, install, and release structure.

## Generated assets and release

Generated projects contain business assets and thin launchers that call an
installed `devflow`. They must not contain toolkit source. The project lock is
`.devflow.lock.json`; shared state is `~/.local/state/devflow/`; the Skill target is
`DEVFLOW_SKILL_HOME` or `~/.agents/skills/devflow/`.

The npm flow is embedded wheel in `npm/dist/`, pipx, one Skill directory, then
`devflow doctor`. The wrapper resolves the pipx-installed absolute path and never
recursively starts itself through `PATH`. `npx dev-flow install` is the
explicit recovery command when npm postinstall is disabled.

Legacy state migration is an explicit operator task outside runtime startup.
Runtime code reads only the new state directory and never falls back to a
legacy path.

## Skill authoring

Every installable Skill is a versioned product surface and must follow the
rules in this section. The nested `skills/AGENTS.md` is a convenience
for work started inside that directory; it is not a replacement for these
repository-level rules. A new Skill is complete only when
its runtime domain, prompt, references, generated assets, npm payload, and
verification are all updated together.

Codex's project instruction chain is built from `AGENTS.md` files found from
the project root to the current directory. `SKILL.md` is loaded when a Skill
is selected; `agents/openai.yaml` supplies optional Skill UI, invocation, and
tool-dependency metadata. Keep these layers consistent: a narrower
`AGENTS.md` or Skill instruction may add constraints, but must not weaken
repository contracts or authorize an unsafe operation. Required behavior
must live in `AGENTS.md`, `SKILL.md`, or an executable gate, not only in
optional UI metadata.

For every new or changed Skill:

- Use one canonical directory under `skills/<category>/<skill-name>/`.
  The directory name, `SKILL.md` frontmatter `name`, lock `skill` value, and
  generated npm payload must agree exactly. Do not add aliases, legacy paths,
  or a second copy maintained by hand.
- Keep `SKILL.md` concise and operational. It must state the CLI route, the
  allowed project roots and artifacts, the safety/ownership gates, the
  authoritative output, and the references that must be read for each
  workflow. Never tell the model to guess missing evidence or silently bypass
  a failed gate.
- Give each Skill one `agents/openai.yaml` interface with the project-required
  `display_name`, `short_description`, and domain-specific `default_prompt`.
  Other documented metadata such as icons, invocation policy, and tool
  dependencies is allowed when needed. The default prompt supplements
  `SKILL.md`; it must route only to that Skill, require the installed
  `devflow` CLI, preserve core contracts, require redacted authoritative
  output, and name the stopping conditions for unsafe, ambiguous, or failed
  validation. Do not use a generic prompt that routes among unrelated Skills.
- Put detailed procedures, schemas, examples, and policy in `references/`.
  Reference paths must be relative to the Skill, stable, and explicitly
  routed from `SKILL.md` or the default prompt. Keep generated business data
  separate from reusable instructions and never embed secrets or credentials.
- Preserve deterministic behavior: do not add runtime prompt discovery,
  network-only instructions, hidden tool fallbacks, dynamic plugin loading,
  or instructions that mutate source, state, locks, or history without an
  explicit workflow and the domain's validation gate.
- Update the canonical Skill first, then regenerate or copy the npm payload
  through `scripts/release.py`. Review the resulting tree for path/name
  mismatches and run the full verification commands below.

When reviewing a Skill change, check prompt precedence, domain isolation,
evidence requirements, redaction, artifact paths, failure behavior, and
canonical/npm parity in addition to ordinary code correctness.

## Verification

For code/schema/template changes run the relevant tests, then:

```text
python -m pytest -q
python -m compileall -q devflow tests
git diff --check
```

Release changes additionally run `python scripts/release.py`, verify one wheel
with only the `devflow` entry point, one npm Skill payload, synchronized versions,
and the isolated npm -> pipx -> Skill sync -> `doctor` flow. Do not commit
`dist/`, npm wheel/vendor/tgz artifacts, caches, or local state.
