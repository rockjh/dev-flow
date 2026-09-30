import subprocess
from pathlib import Path

from devflow.core.redaction import redact
from devflow.biz_flow_doc_generator.discovery import scan


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
