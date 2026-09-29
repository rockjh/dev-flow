from pathlib import Path

from devflow.doc_biz_flow.models import EntryPoint, GitInfo, ScanResult
from devflow.doc_biz_flow.orchestration import build_agent_plan, complete_agent_plan, validate_agent_plan


def test_incremental_agent_plan_validates_only_affected_modules() -> None:
    entries = [
        EntryPoint(f"url:GET /{name}:app.py:handle", "url", f"GET /{name}", "handle", "app.py", 1, name, "app.py")
        for name in ("orders", "billing")
    ]
    scan = ScanResult(Path("."), GitInfo("main", "abc", "abc", False, False), [], [], entries, [], [], "fingerprint")

    plan = build_agent_plan(scan, incremental=True, affected_modules={"orders"})

    assert validate_agent_plan(plan, scan) == []
    assert {task["task_id"] for task in plan["tasks"]} == {
        "module:orders", f"entry:{entries[0].entry_id}"
    }
    assert set(plan["entry_analyses"]) == {entries[0].entry_id}
    assert plan["entry_analyses"][entries[0].entry_id]["evidence"] == ["app.py:1"]
    completed = complete_agent_plan(plan, {"orders"})
    assert completed["status"] == "completed"
    assert all(task["status"] == "completed" for task in completed["tasks"])
