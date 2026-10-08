from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NPM = ROOT / "npm"


class ReleaseContractTests(unittest.TestCase):
    def test_python_and_npm_publish_one_matching_cli(self) -> None:
        python = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        npm = json.loads((NPM / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(python["project"]["version"], npm["version"])
        self.assertEqual("dev-flow", npm["name"])
        self.assertEqual({"devflow": "toolkit.cli:console_main"}, python["project"]["scripts"])
        self.assertEqual({"devflow": "bin/devflow.js"}, npm["bin"])
        self.assertIn("scripts/", npm["files"])
        self.assertIn("dist/", npm["files"])

    def test_npm_payload_excludes_shared_support_directories(self) -> None:
        shared = ROOT / "skills" / "_shared"
        self.assertFalse(shared.is_dir() and any(path.is_file() for path in shared.rglob("*")))

    def test_canonical_skill_payload_contains_one_version_file_per_domain(self) -> None:
        expected = {
            "biz-flow-doc-generator": "biz-flow-doc-generator-version.json",
            "bru-api-test-generator": "bru-api-test-generator-version.json",
            "e2e-test-generator": "e2e-test-generator-version.json",
        }
        for skill, filename in expected.items():
            canonical = ROOT / "skills" / skill
            payload = ROOT / "npm" / "skills" / skill
            self.assertTrue((canonical / "agents" / "openai.yaml").is_file())
            self.assertTrue((payload / "agents" / "openai.yaml").is_file())
            canonical_versions = [path for path in canonical.rglob(filename)]
            if skill == "e2e-test-generator":
                self.assertFalse(any(path.parts[-2] == "example" for path in canonical_versions))
            else:
                self.assertEqual(1, len(canonical_versions))
                relative = canonical_versions[0].relative_to(canonical)
                self.assertEqual(canonical_versions[0].read_bytes(), (payload / relative).read_bytes())

    @unittest.skipUnless(shutil.which("node"), "node is required to verify the npm runtime")
    def test_npm_runtime_resolves_the_pipx_executable_without_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bin_dir = Path(temporary).resolve()
            executable = bin_dir / ("devflow.exe" if os.name == "nt" else "devflow")
            executable.touch()
            script = "console.log(require('./npm/scripts/install').resolveDevflow())"
            environment = {**os.environ, "PIPX_BIN_DIR": str(bin_dir)}
            result = subprocess.run(
                [shutil.which("node") or "node", "-e", script],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(executable, Path(result.stdout.strip()))
        wrapper = (NPM / "bin" / "devflow.js").read_text(encoding="utf-8")
        self.assertIn("resolveDevflow()", wrapper)
        self.assertNotIn('spawnSync("devflow"', wrapper)
        self.assertNotIn("spawnSync('devflow'", wrapper)


if __name__ == "__main__":
    unittest.main()
