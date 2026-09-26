from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


class SkillContractTests(unittest.TestCase):
    def test_every_installable_skill_has_a_domain_specific_prompt_contract(self) -> None:
        skill_files = sorted(SKILLS.glob("*/*/SKILL.md"))
        self.assertTrue(skill_files)

        for skill_file in skill_files:
            skill_dir = skill_file.parent
            relative = skill_dir.relative_to(SKILLS).as_posix()
            expected_name = f"devflow/{relative}"
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
            self.assertIn("installed devflow CLI", prompt, agent_file)
            self.assertIn(expected_name, prompt, agent_file)
            self.assertIn("redacted authoritative", prompt, agent_file)
            self.assertIn("stop when", prompt, agent_file)

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
