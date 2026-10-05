import json
import subprocess
from pathlib import Path

from devflow.core.redaction import redact
from devflow.biz_flow_doc_generator.discovery import scan
from devflow.biz_flow_doc_generator.documents import write_discovery
from devflow.biz_flow_doc_generator.cli import _write_overview_report
from devflow.biz_flow_doc_generator.models import EntryPoint, GitInfo, ScanResult


def _git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


def test_java_platform_entries_and_excluded_sources(tmp_path: Path) -> None:
    (tmp_path / "Handlers.java").write_text(
        '@XxlJob("inventory")\n'
        "class Job extends XxlJobHandler {\n"
        "  public Response\n"
        "  doExecute(Request request) { return ok(); }\n"
        "}\n"
        "class Receiver extends BaseReceiver {\n"
        '  static final String TOPIC = "orders.created";\n'
        "  public void\n"
        "  doServe(Message message) {}\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / ".idea").mkdir()
    (tmp_path / ".idea" / "ignored.java").write_text('@XxlJob("ignored") void execute() {}', encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "ignored.log").write_text('@XxlJob("ignored")', encoding="utf-8")
    _git(tmp_path)

    result = scan(tmp_path)
    assert result.files == ["Handlers.java"]
    assert [(entry.kind, entry.identifier, entry.handler) for entry in result.entries] == [
        ("message", "orders.created", "doServe"),
        ("scheduled", "inventory", "doExecute"),
    ]
    assert [entry.entry_id for entry in scan(tmp_path).entries] == [entry.entry_id for entry in result.entries]


def test_annotation_listener_resolves_constant_topics(tmp_path: Path) -> None:
    (tmp_path / "Listener.java").write_text(
        "class Listener {\n"
        "  private static final String TOPIC = \"device.report\";\n"
        "  @KafkaListener(topics = TOPIC)\n"
        "  public void consume(String message) {}\n"
        "}\n",
        encoding="utf-8",
    )
    _git(tmp_path)

    result = scan(tmp_path)
    assert [(entry.kind, entry.identifier) for entry in result.entries] == [("message", "device.report")]


def test_structured_markers_survive_redaction() -> None:
    value = '<!-- biz-flow-entry: token=ENTRY -->\n<!-- devflow:module name="token" --> token=secret'
    redacted = redact(value)
    assert "biz-flow-entry: token=ENTRY" in redacted
    assert 'devflow:module name="token"' in redacted
    assert "token=[REDACTED]" in redacted


def test_mermaid_success_uses_cleaned_label() -> None:
    from devflow.biz_flow_doc_generator.documents import _diagram
    from devflow.biz_flow_doc_generator.models import EntryPoint, EntryReview

    entry = EntryPoint("url:GET /x:a.py:handler", "url", "GET /x", "handler", "a.py", 1, "a", "a.py")
    entry.review = EntryReview("id", "caller", "purpose", "input", "password: SECRET; outcome", "failure")
    diagram = _diagram(entry)
    assert "SECRET" not in diagram
    assert "password: [REDACTED]" in diagram


def test_error_code_prefers_raised_literal_over_condition_status() -> None:
    from devflow.biz_flow_doc_generator.discovery import _error

    evidence = _error(
        'payment_id not in PAYMENTS or status != "PAID" -> raise OrderError("PAYMENT_FAILED")',
        "app.py",
        10,
    )
    assert evidence.code == "PAYMENT_FAILED"


def test_overview_keeps_excluded_candidates_in_complete_list(tmp_path: Path) -> None:
    (tmp_path / "AcController.py").write_text("# 查询 AC 信息\n", encoding="utf-8")
    (tmp_path / "AcDao.py").write_text("def load(): pass\n", encoding="utf-8")
    business = EntryPoint(
        "url:GET /ac:AcController.py:get", "url", "GET /ac", "get", "AcController.py", 1,
        "ac", "AcController.py", business_name="查询 AC 信息", trigger_summary="HTTP：GET /ac",
        source_evidence=[{"file": "AcController.py", "line": 1, "reason": "路由注释"}],
    )
    excluded = EntryPoint(
        "message:id:AcDao.py:load", "message", "id:ac", "load", "AcDao.py", 1,
        "ac", "AcDao.py", business_name="技术入口：load", trigger_summary="消息：id:ac",
        source_evidence=[{"file": "AcDao.py", "line": 1, "reason": "DAO 注册"}],
        scope_status="excluded", exclusion_reason="DAO 持久化适配器",
    )
    result = ScanResult(
        tmp_path, GitInfo("main", "a" * 40, "a" * 40, False, False), ["Python"], [],
        [business, excluded], ["AcController.py", "AcDao.py"], [], "fingerprint",
        {"AcController.py": 1, "AcDao.py": 1}, all_entries=[business, excluded],
        discovered_entry_count=2,
    )
    docs_root = tmp_path / "docs" / "biz-flow"
    discovery_path, _ = write_discovery(result, docs_root)
    overview = (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    assert overview.index("业务模块划分") < overview.index("建议忽略的入口")
    assert business.entry_id in overview
    assert excluded.entry_id in overview
    assert discovery_path.is_file()

    module_map = docs_root / "biz-flow-modules.json"
    document = json.loads(module_map.read_text(encoding="utf-8"))
    document["confirmed"] = True
    module_map.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    result.entries = [business]
    _write_overview_report(docs_root, result, {})
    rendered = (docs_root / "业务流程覆盖总览.md").read_text(encoding="utf-8")
    assert "| 技术入口：" not in rendered.split("## 完整入口清单", 1)[0]
    assert excluded.entry_id in rendered
