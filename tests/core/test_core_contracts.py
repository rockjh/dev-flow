from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from devflow.core.artifacts import require_lock, write_lock
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

    def test_project_lock_enforces_domain_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_lock(root, tool_version="1", domain="e2e", schema_version="old")
            with self.assertRaisesRegex(DevflowError, "schema"):
                require_lock(root, tool_version="1", domain="e2e", schema_version="new")

    def test_biz_flow_project_lock_is_owned_by_docs_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_lock(root, tool_version="1", domain="biz-flow", schema_version="1")
            self.assertEqual(root / "docs" / "biz-flow" / "biz-flow.json", path)
            self.assertFalse((root / ".devflow.lock.json").exists())
            require_lock(root, tool_version="1", domain="biz-flow", schema_version="1")

    def test_biz_flow_does_not_accept_old_root_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_lock(root, tool_version="1", domain="e2e", schema_version="1")
            with self.assertRaisesRegex(DevflowError, "docs.*biz-flow.*biz-flow.json"):
                require_lock(root, tool_version="1", domain="biz-flow", schema_version="1")

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
