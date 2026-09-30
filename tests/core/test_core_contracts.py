from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from devflow.core.artifacts import require_version_file, write_version_file
from devflow.core.errors import DevflowError
from devflow.core.redaction import redact
from devflow.core.schema import CONFIG_SCHEMA, validate_schema


class CoreContractTests(unittest.TestCase):
    def test_redaction_covers_headers_schemes_urls_and_structured_keys(self) -> None:
        value = redact({
            "message": (
                "Authorization: Bearer TOPSECRET\n"
                "Cookie: session=COOKIESECRET; theme=dark\n"
                "endpoint=https://user:URLSECRET@example.invalid\n"
                "fallback=Basic BASICSECRET"
            ),
            "client_secret": "STRUCTURED_SECRET",
        })
        rendered = str(value)
        for secret in ("TOPSECRET", "COOKIESECRET", "URLSECRET", "BASICSECRET", "STRUCTURED_SECRET"):
            self.assertNotIn(secret, rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_skill_version_file_enforces_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_version_file(root, "e2e", {"document_baseline": {"git_commit": None}})
            path = root / "analysis" / "e2e-test-generator-version.json"
            path.write_text(path.read_text().replace('"skill_version": "1.0.0"', '"skill_version": "old"'), encoding="utf-8")
            with self.assertRaisesRegex(DevflowError, "skill_version"):
                require_version_file(root, "e2e")

    def test_biz_flow_project_lock_is_owned_by_docs_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_version_file(root, "biz-flow", {"source": {"git_commit": None}})
            self.assertEqual(root / "docs" / "biz-flow" / "biz-flow-doc-generator-version.json", path)
            self.assertFalse((root / ".devflow.lock.json").exists())
            require_version_file(root, "biz-flow")

    def test_biz_flow_does_not_accept_old_root_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_version_file(root, "e2e", {"document_baseline": {"git_commit": None}})
            with self.assertRaisesRegex(DevflowError, "docs.*biz-flow.*version.json"):
                require_version_file(root, "biz-flow")

    def test_relocated_bru_version_file_uses_the_same_metadata_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "quality-assets" / "contracts" / "bru-api-test-generator-version.json"
            write_version_file(root, "bru-api", {"version": 1, "status": "draft"}, path=path)
            self.assertEqual("devflow/bru-api-test-generator", require_version_file(root, "bru-api", path=path)["skill"])
            path.write_text(path.read_text(encoding="utf-8").replace('"artifact_root": "qa/contracts"', '"artifact_root": "other"'), encoding="utf-8")
            with self.assertRaisesRegex(DevflowError, "artifact_root"):
                require_version_file(root, "bru-api", path=path)

    def test_config_schema_matches_runtime_optional_polling_contract(self) -> None:
        document = {
            "active_environment": "test",
            "defaults": {
                "safety": {
                    "database_control_enabled": False,
                    "mutable_configuration_enabled": False,
                    "message_publish_enabled": False,
                }
            },
        }
        schema = CONFIG_SCHEMA["files"]["configuration/config.yaml"]
        self.assertEqual([], validate_schema(schema, document))


if __name__ == "__main__":
    unittest.main()
