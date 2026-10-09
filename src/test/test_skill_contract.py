from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"


class SkillContractTests(unittest.TestCase):
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
        for value in (text, prompt):
            for required in ("whole project", "doExecute", "doServe", "core_capabilities", "read-only entry", "sequenceDiagram", "autonumber"):
                self.assertIn(required, value)
        self.assertIn("fixed order", text)
        self.assertIn("module-confirmed", text)
        self.assertIn("references/requirements-matrix.md", text)
        for value in (text, prompt):
            value = " ".join(value.split())
            for required in ("@Tag.description", "@Operation.summary/description", "multiple sentences", "client/HTML"):
                self.assertIn(required, value)
            self.assertNotIn("one concise sentence", value)

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
