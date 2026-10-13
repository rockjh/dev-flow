from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from toolkit.cli import console_main
from toolkit.core.schema import BIZ_FLOW_SCHEMA_VERSION, get_schema, validate_schema
from toolkit.core.artifacts import ProjectDomainLock
from toolkit.biz_flow_doc_generator.evidence import collect_evidence
from toolkit.biz_flow_doc_generator.discovery import scan


class BizFlowContractTests(unittest.TestCase):

    def invoke(self, *arguments: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = console_main([*arguments, "--json"])
        return code, json.loads(output.getvalue())

    def project(self, root: Path) -> None:
        (root / "app.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "# 查询资源\n"
            "@app.get('/resources')\n"
            "def list_resources():\n"
            "    raise BusinessError('RESOURCE_NOT_FOUND', 'missing')\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)

    def initialize_and_confirm(self, root: Path) -> Path:
        code, result = self.invoke("biz-flow", "init", "--project", str(root))
        self.assertEqual(0, code, result)
        self.assertTrue((root / "docs" / "biz-flow" / "biz-flow-doc-generator-version.json").is_file())
        self.assertFalse((root / ".devflow.lock.json").exists())
        code, result = self.invoke("biz-flow", "discover", "--project", str(root))
        self.assertEqual(0, code, result)
        overview = root / "docs" / "biz-flow" / "业务流程覆盖总览.md"
        text = overview.read_text(encoding="utf-8")
        overview.write_text(text + "\n<!-- devflow:module-confirmed -->\n", encoding="utf-8")
        return overview



    def test_writer_lock_rejects_overlapping_process_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.project(root)
            with ProjectDomainLock(root, "biz-flow"):
                code, result = self.invoke("biz-flow", "init", "--project", str(root))
            self.assertEqual(8, code, result)
            self.assertIn("concurrent project/domain operation", result["error"]["message"])

    def test_missing_lock_is_a_gate_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.project(root)
            code, result = self.invoke("biz-flow", "generate", "--project", str(root))
            self.assertEqual(8, code)
            self.assertEqual("GATE_FAILED", result["error"]["code"])

    def test_protected_production_path_blocks_document_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "prod"
            root.mkdir()
            self.project(root)
            code, result = self.invoke("biz-flow", "init", "--project", str(root))
            self.assertEqual(8, code, result)
            self.assertEqual("GATE_FAILED", result["error"]["code"])
            self.assertIn("protected production paths", result["error"]["message"])


















    def test_discovery_covers_protocol_graphql_jobs_messages_and_cli_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "service.proto").write_text(
                "service Resource {\n  rpc Allocate (Request) returns (Reply);\n}\n",
                encoding="utf-8",
            )
            (root / "schema.graphql").write_text(
                "type Query {\n  resource(id: ID!): Resource\n}\n",
                encoding="utf-8",
            )
            (root / "Jobs.java").write_text(
                "class Jobs {\n"
                "  @XxlJob(\"inventory-check\")\n"
                "  public void inventory() { throw new BizException(\"NO_STOCK\"); }\n"
                "  @KafkaListener(topics = {\"created\", \"updated\"})\n"
                "  public void consume() { return; }\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "ResourceController.kt").write_text(
                "@Controller(\"/resource\")\n"
                "class ResourceController {\n"
                "  @Get(\"/one\")\n"
                "  fun one(): String { return \"ok\" }\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "commands.py").write_text("def reconcile():\n    return 0\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\nname='sample'\nversion='1'\n[project.scripts]\nreconcile='commands:reconcile'\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "entry matrix"], cwd=root, check=True)

            result = scan(root)
            identifiers = {entry.identifier for entry in result.entries}
            self.assertTrue({
                "Resource/Allocate", "Query/resource", "inventory-check", "created", "updated", "reconcile",
                "GET /resource/one",
            }.issubset(identifiers))
            self.assertIn("NO_STOCK", json.dumps(collect_evidence(result)))
            self.assertTrue(result.source_fingerprint)

    def test_domain_and_subcommand_help_are_statically_registered(self) -> None:
        docs = Path.cwd() / "docs" / "biz-flow"
        for arguments, expected in (
            (["biz-flow", "--help"], "discover"),
            (["biz-flow", "discover", "--help"], "--commit"),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                code = console_main(arguments)
            self.assertEqual(0, code)
            self.assertIn(expected, output.getvalue())
        self.assertFalse(docs.exists())

    def test_invalid_init_does_not_create_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, result = self.invoke("biz-flow", "init", "--project", str(root))
            self.assertNotEqual(0, code, result)
            self.assertFalse((root / "docs").exists())


if __name__ == "__main__":
    unittest.main()
