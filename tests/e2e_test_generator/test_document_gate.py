from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from devflow.e2e_test_generator.document_gate import initialize_document_state, run_document_gate, validate_baseline, validate_markdown, validate_scenario_artifacts
from devflow.e2e_test_generator.contracts import generate_artifacts


class DocumentGateTests(unittest.TestCase):
    def test_baseline_requires_only_a_real_full_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs" / "e2e").mkdir(parents=True)
            (root / "docs" / "e2e" / "e2e.yaml").write_text("git_commit: latest\n", encoding="utf-8")
            commit, errors = validate_baseline(root)
            self.assertIsNone(commit)
            self.assertEqual("DOCUMENT_BASELINE_INVALID", errors[0].code)

    def test_confirmation_state_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            flow = root / "docs" / "biz-flow" / "orders.md"
            flow.parent.mkdir(parents=True)
            flow.write_text("# Checkout\n", encoding="utf-8")
            state = initialize_document_state(root, ["checkout success"], sources=[{"type": "biz-flow", "value": "docs/biz-flow/orders.md#Checkout"}])
            self.assertEqual("awaiting_confirmation", state["status"])
            confirmed = initialize_document_state(root, confirm=True)
            self.assertEqual("confirmed", confirmed["status"])
            self.assertTrue((root / ".devflow" / "e2e-document-state.json").is_file())
            self.assertTrue(confirmed["candidates"][0]["key_steps"])
            self.assertEqual(64, len(confirmed["candidate_fingerprint"]))

    def test_confirmation_is_rejected_when_candidate_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            flow = root / "docs" / "biz-flow" / "orders.md"
            flow.parent.mkdir(parents=True)
            flow.write_text("# Checkout\n", encoding="utf-8")
            initialize_document_state(root, ["checkout success"], sources=[{"type": "biz-flow", "value": "docs/biz-flow/orders.md#Checkout"}])
            state_path = root / ".devflow" / "e2e-document-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["candidates"][0]["name"] = "changed"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            confirmed = initialize_document_state(root, confirm=True)
            self.assertEqual("awaiting_confirmation", confirmed["status"])

    def test_markdown_requires_sequence_diagram(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs" / "e2e"
            docs.mkdir(parents=True)
            (docs / "checkout.md").write_text(
                """## Scenario: checkout\n\n```yaml\nid: CHECKOUT\nowner: orders\nbiz_flow_refs:\n  - file: docs/biz-flow/orders.md\n    section: Checkout\n```\n\n### Scenario Name\nCheckout\n### Test Objective\nSuccess\n### Business Entry\nAPI\n### Preconditions\nReady\n### Test Data\nOrder\n### Key Steps\nSubmit\n### Expected Results\nCreated\n### Exceptions and Compensation\nRetry\n### Biz-flow References\nCheckout\n### Mermaid Sequence Diagram\nNo diagram\n""",
                encoding="utf-8",
            )
            _, errors = validate_markdown(root)
            self.assertTrue(any(error.code == "DOCUMENT_DIAGRAM_MISSING" for error in errors))

    def test_awaiting_confirmation_blocks_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_document_state(root, ["checkout"])
            report = run_document_gate(root, "generate")
            self.assertFalse(report.allowed)
            self.assertTrue(any(error.code == "DOCUMENT_CONFIRMATION_REQUIRED" for error in report.issues))

    def test_generated_documents_require_matching_scenario_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            issues = validate_scenario_artifacts(root, [{"id": "CHECKOUT", "name": "checkout", "status": "active", "document": "docs/e2e/checkout.md"}])
            self.assertTrue(any(issue.code == "DOCUMENT_SCENARIO_UNASSIGNED" for issue in issues))

    def test_public_generation_api_cannot_bypass_document_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result, errors = generate_artifacts(Path(temporary))
            self.assertIn("document_gate", result)
            self.assertTrue(any("DOCUMENT_BASELINE_MISSING" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
