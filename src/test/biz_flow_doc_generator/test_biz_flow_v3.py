from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.evidence import collect_evidence
from toolkit.biz_flow_doc_generator.documents import _validate_mermaid, write_discovery
from toolkit.biz_flow_doc_generator.models import EntryPoint, GitInfo


class BizFlowV3Tests(unittest.TestCase):
    def _git(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

    def test_registration_counts_ignore_comments_and_plain_task_methods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                "# receiver('fake-topic')\n"
                "def task(value): return value\n"
                "@app.get('/resources')\n"
                "def list_resources(): return []\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            self.assertEqual(1, len(result.entries))
            docs = root / "docs"
            write_discovery(result, docs)
            self.assertTrue((docs / "biz-flow-modules.json").is_file())
            mapping = json.loads((docs / "biz-flow-modules.json").read_text(encoding="utf-8"))
            module = mapping["modules"][0]
            self.assertIn("responsibility", module)
            self.assertIn("file", module)
            self.assertEqual(result.entries[0].entry_id, module["entry_ids"][0])


    def test_same_named_definitions_are_not_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "@app.get('/x')\ndef get_x():\n    save()\n    return []\n",
                encoding="utf-8",
            )
            (root / "one.py").write_text("def save(): raise E('ONE_ERROR')\n", encoding="utf-8")
            (root / "two.py").write_text("def save(): raise E('TWO_ERROR')\n", encoding="utf-8")
            self._git(root)
            result = scan(root)
            entry = next(item for item in result.entries if item.identifier == "GET /x")
            self.assertNotIn("ONE_ERROR", json.dumps(collect_evidence(result)[entry.entry_id]["outcomes"]))
            self.assertNotIn("TWO_ERROR", json.dumps(collect_evidence(result)[entry.entry_id]["outcomes"]))
            self.assertTrue(collect_evidence(result)[entry.entry_id]["gaps"])


    def test_java_multi_route_binding_is_counted_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Controller.java").write_text(
                "class Controller {\n"
                "  @GetMapping({\"/one\", \"/two\"})\n"
                "  String read() { return \"ok\"; }\n"
                "}\n",
                encoding="utf-8",
            )
            self._git(root)
            identifiers = {entry.identifier for entry in scan(root).entries}
            self.assertIn("GET /one", identifiers)
            self.assertIn("GET /two", identifiers)
            self.assertFalse(any("parser support for Java is heuristic" in item for item in scan(root).unresolved))

    def test_java_job_template_methods_are_qualified_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "DeviceJob.java").write_text(
                "class DeviceJob extends AbstractJobHandler {\n"
                "  protected void doExecute(String param) throws Exception { saveDevice(); }\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "EventJob.java").write_text(
                "class EventJob extends AbstractJobHandler {\n"
                "  protected void doExecute(String param) throws Exception { saveEvent(); }\n"
                "}\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            entries = [item for item in result.entries if item.kind == "scheduled"]
            self.assertEqual(2, len(entries))
            self.assertEqual(2, len({item.functions[0] for item in entries}))
            self.assertFalse(any("CAPABILITY_ID_CONFLICT" in item for item in result.unresolved))

    def test_feign_mapping_is_outbound_not_an_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Client.java").write_text(
                "@FeignClient(name=\"resource\")\n"
                "interface Client { @GetMapping(\"/resources\") String read(); }\n",
                encoding="utf-8",
            )
            self._git(root)
            self.assertEqual([], scan(root).entries)

    def test_typed_receiver_selects_the_reachable_same_named_method(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "class One:\n    def save(self): raise E('ONE_ERROR')\n"
                "class Two:\n    def save(self): raise E('TWO_ERROR')\n"
                "@app.get('/x')\n"
                "def get_x():\n    service: One = One()\n    service.save()\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            entry = next(item for item in result.entries if item.identifier == "GET /x")
            self.assertIn("ONE_ERROR", json.dumps(collect_evidence(result)[entry.entry_id]["outcomes"]))
            self.assertNotIn("TWO_ERROR", json.dumps(collect_evidence(result)[entry.entry_id]["outcomes"]))




    def test_mermaid_validator_rejects_unbalanced_control_block(self) -> None:
        self.assertTrue(_validate_mermaid("sequenceDiagram\nparticipant A as A\nalt x\nA->>A: y\n"))

    def test_mermaid_validator_requires_autonumber(self) -> None:
        self.assertIn(
            "missing autonumber",
            _validate_mermaid(
                "sequenceDiagram\nparticipant A as A\nA->>A: PROTOCOL_SUCCESS 落库 投递\n"
            ),
        )

    def test_mermaid_validator_accepts_numbered_sequence(self) -> None:
        self.assertEqual([], _validate_mermaid(
            "sequenceDiagram\nautonumber\nparticipant A as A\n"
            "activate A\nA-->>A: PROTOCOL_SUCCESS 落库 投递\ndeactivate A\n"
        ))

    def test_mermaid_validator_checks_note_participants(self) -> None:
        self.assertTrue(_validate_mermaid(
            "sequenceDiagram\nparticipant A as A\nNote over A,B: missing\n"
        ))

    def test_unknown_qualified_receiver_does_not_use_global_method_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "def save(): raise E('UNRELATED')\n"
                "@app.get('/x')\n"
                "def get_x():\n    client.save()\n    return []\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            entry = next(item for item in result.entries if item.identifier == "GET /x")
            self.assertNotIn("UNRELATED", json.dumps(collect_evidence(result)[entry.entry_id]["outcomes"]))
            self.assertTrue(any(g["code"] == "CALL_CONTRACT_UNSUPPORTED" for g in collect_evidence(result)[entry.entry_id]["gaps"]))

    def test_caught_loop_item_error_is_kept_as_partial_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "@app.post('/batch')\n"
                "def batch(items):\n"
                "    for item in items:\n"
                "        try:\n"
                "            raise ValueError('ITEM_FAILED')\n"
                "        except ValueError:\n"
                "            continue\n"
                "    return {'accepted': True}\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            entry = next(item for item in result.entries if item.identifier == "POST /batch")
            facts = collect_evidence(result)[entry.entry_id]
            error = next(o for o in facts["outcomes"] if "ITEM_FAILED" in o["details"]["expression"])
            self.assertTrue(error["conditions"])
            self.assertFalse(error["details"]["observed_by_entry"])
            self.assertTrue(any(o["type"] == "continue" for o in facts["outcomes"]))

    def test_worker_error_is_not_reported_as_sync_response_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "def worker():\n    raise BusinessError('WORKER_FAILED')\n"
                "@app.post('/jobs')\n"
                "def submit_job(executor):\n    executor.submit(worker)\n    return {'accepted': True}\n",
                encoding="utf-8",
            )
            self._git(root)
            result = scan(root)
            entry = next(item for item in result.entries if item.identifier == "POST /jobs")
            facts = collect_evidence(result)[entry.entry_id]
            self.assertTrue(facts["gaps"])
            self.assertFalse(any("WORKER_FAILED" in o["details"]["expression"] for o in facts["outcomes"]))
            self.assertFalse(facts["coverage"]["complete"])


if __name__ == "__main__":
    unittest.main()
