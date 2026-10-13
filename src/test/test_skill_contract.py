from __future__ import annotations

import re
import runpy
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
SEQUENCE_RULES = runpy.run_path(str(ROOT / "scripts/sync_sequence_conventions.py"))


class SkillContractTests(unittest.TestCase):
    def test_all_sequence_consumers_use_the_owners_current_local_contract(self) -> None:
        self.assertEqual([], SEQUENCE_RULES["sync_conventions"](SKILLS, check=True))
        for skill in SKILLS.iterdir():
            if not (skill / SEQUENCE_RULES["REFERENCE"]).is_file():
                continue
            prompt = yaml.safe_load((skill / "agents/openai.yaml").read_text(encoding="utf-8"))["interface"]["default_prompt"]
            self.assertIn(SEQUENCE_RULES["REFERENCE"], prompt, skill)

    def test_new_sequence_consumers_cannot_skip_routing_or_drift_from_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skills = Path(temporary)
            reference = SEQUENCE_RULES["REFERENCE"]
            owner = skills / SEQUENCE_RULES["OWNER"]
            consumer = skills / "future-diagram-skill"
            for skill in (owner, consumer):
                (skill / "references").mkdir(parents=True)
                (skill / "agents").mkdir()
                (skill / "SKILL.md").write_text(f"sequenceDiagram: read {reference}", encoding="utf-8")
                (skill / "agents/openai.yaml").write_text(f"default_prompt: read {reference}", encoding="utf-8")
            source = owner / reference
            source.write_bytes((SKILLS / SEQUENCE_RULES["OWNER"] / reference).read_bytes())
            route = consumer / "SKILL.md"
            route.write_text("Generate 时序图", encoding="utf-8")
            sync = SEQUENCE_RULES["sync_conventions"]
            self.assertTrue(sync(skills))
            self.assertFalse((consumer / reference).exists())
            route.write_text(f"Read {reference}", encoding="utf-8")
            prompt = consumer / "agents/openai.yaml"
            prompt.write_text("default_prompt: Generate sequence diagrams", encoding="utf-8")
            self.assertTrue(sync(skills))
            prompt.write_text(f"default_prompt: Read {reference}", encoding="utf-8")
            self.assertEqual([], sync(skills))
            self.assertEqual([], sync(skills, check=True))
            frozen = (consumer / reference).read_bytes()
            source.write_bytes(source.read_bytes() + b"\nOwner contract update.\n")
            self.assertTrue(sync(skills, check=True))
            self.assertEqual(frozen, (consumer / reference).read_bytes())
            self.assertEqual([], sync(skills))
            self.assertEqual(SEQUENCE_RULES["GENERATED"] + source.read_bytes(), (consumer / reference).read_bytes())

    def test_all_skill_diagram_examples_pass_the_runtime_gate(self) -> None:
        from toolkit.core.sequence import validate_sequence

        count = 0
        for path in SKILLS.rglob("*.md"):
            for diagram in re.findall(r"```mermaid\s*\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL):
                if "sequenceDiagram" in diagram:
                    count += 1
                    self.assertEqual([], validate_sequence(diagram), path)
        self.assertGreater(count, 0)

    def test_every_installable_skill_has_a_domain_specific_prompt_contract(self) -> None:
        skill_files = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertTrue(skill_files)

        for skill_file in skill_files:
            skill_dir = skill_file.parent
            relative = skill_dir.relative_to(SKILLS).as_posix()
            expected_name = relative
            frontmatter = self._frontmatter(skill_file)
            self.assertEqual(expected_name, frontmatter.get("name"), skill_file)
            self.assertTrue(frontmatter.get("description"), skill_file)

            agent_file = skill_dir / "agents" / "openai.yaml"
            self.assertTrue(agent_file.is_file(), agent_file)
            document = yaml.safe_load(agent_file.read_text(encoding="utf-8"))
            self.assertTrue(set(document) <= {"interface", "policy", "dependencies"}, agent_file)
            self.assertIn("interface", document, agent_file)
            interface = document["interface"]
            self.assertTrue(
                {"display_name", "short_description", "default_prompt"}.issubset(interface),
                agent_file,
            )
            prompt = interface["default_prompt"]
            self.assertNotIn("skill_version", interface, agent_file)
            self.assertNotIn("version_file", interface, agent_file)
            self.assertIn("installed devflow CLI", prompt, agent_file)
            self.assertIn(expected_name, prompt, agent_file)
            self.assertIn("redacted authoritative", prompt, agent_file)
            self.assertIn("stop when", prompt, agent_file)
            for reference in re.findall(r"references/[\w./-]+\.md", skill_file.read_text(encoding="utf-8") + "\n" + prompt):
                target = (skill_dir / reference).resolve()
                self.assertTrue(target.is_relative_to(skill_dir.resolve()), reference)
                self.assertTrue(target.is_file(), target)

    def test_version_file_contract_is_explicit_per_domain(self) -> None:
        expected = {
            "biz-flow-doc-generator": "docs/biz-flow/biz-flow-doc-generator-version.json",
            "bru-api-test-generator": "qa/contracts/bru-api-test-generator-version.json",
            "e2e-test-generator": "analysis/e2e-test-generator-version.json",
            "sequence-diagram-generator": "docs/sequence-diagram/sequence-diagram-generator-version.json",
        }
        for name, path in expected.items():
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            prompt = yaml.safe_load((SKILLS / name / "agents" / "openai.yaml").read_text(encoding="utf-8"))["interface"]["default_prompt"]
            self.assertIn(path, text)
            self.assertIn("skill_version", text)
            self.assertIn(path, prompt)

    def test_biz_flow_prompt_and_skill_cover_revised_workflow(self) -> None:
        skill = SKILLS / "biz-flow-doc-generator"
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        prompt = yaml.safe_load((skill / "agents" / "openai.yaml").read_text(encoding="utf-8"))["interface"]["default_prompt"]
        policy = (skill / "references/analysis-policy.md").read_text(encoding="utf-8")
        behavior = (skill / "references/behavior-evidence.md").read_text(encoding="utf-8")
        for required in ("whole project", "doExecute", "doServe", "read-only entry", "sequenceDiagram", "autonumber"):
            self.assertIn(required, text)
        for value in (text, prompt):
            self.assertNotIn("core_capabilities", value)
            self.assertIn("references/behavior-evidence.md", value)
        self.assertIn("evidence_request", behavior)
        self.assertIn("fixed order", text)
        self.assertIn("module-confirmed", text)
        self.assertIn("references/requirements-matrix.md", text)
        for required in ("@Tag.description", "@Operation.summary/description", "允许使用分号", "HTML"):
            self.assertIn(required, policy)

    @staticmethod
    def _frontmatter(path: Path) -> dict[str, str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            raise AssertionError(f"missing frontmatter: {path}")
        try:
            end = lines.index("---", 1)
        except ValueError as exc:
            raise AssertionError(f"unterminated frontmatter: {path}") from exc
        value = yaml.safe_load("\n".join(lines[1:end]))
        if not isinstance(value, dict):
            raise AssertionError(f"invalid frontmatter: {path}")
        return value


if __name__ == "__main__":
    unittest.main()
