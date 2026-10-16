"""Generic v1 acceptance: committed inputs, retryable lifecycle and real gates."""
import copy
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from toolkit.biz_flow_doc_generator import cli, documents, host
from toolkit.biz_flow_doc_generator.discovery import scan, _fingerprint_files
from toolkit.biz_flow_doc_generator.evidence import collect_evidence, digest
from toolkit.biz_flow_doc_generator.supplement import fact_path
from toolkit.biz_flow_doc_generator.validation import validate_entry_analysis
from toolkit.biz_flow_doc_generator.paths import io_path
from test_behavior_facts import project as create_project
from test_native_handoff import fixture_submission


SOURCES = {
    "java": {"Controller.java": '''import org.springframework.data.jpa.repository.JpaRepository;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.Column;
class Controller { OrderRepository repository;
  // 查询订单
  @GetMapping("/orders") void orders() { repository.findAll(); }
  // 清理订单
  @Scheduled(cron="0 * * * * *") void tick() {}
}
interface OrderRepository extends JpaRepository<Order, Long> {}
@Entity @Table(name="biz_order") class Order { @Column(name="order_id") long id; }
''', "pom.xml": '''<project><dependencies><dependency><groupId>org.springframework.data</groupId>
<artifactId>spring-data-jpa</artifactId><version>3.3.0</version></dependency></dependencies></project>'''.strip()},
    "python": {"app.py": '''from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import DeclarativeBase, Session
class Base(DeclarativeBase): pass
class Order(Base):
    __tablename__ = "biz_order"
app = FastAPI()
scheduler = BackgroundScheduler()
# 查询订单
@app.get('/orders')
def orders(session: Session): return session.query(Order).all()
# 清理订单
@scheduler.scheduled_job('cron')
def tick(): pass
'''},
    "typescript": {"main.ts": '''import { PrismaClient } from '@prisma/client';
const prisma = new PrismaClient();
@Controller('orders')
class OrderController {
  // 查询订单
  @Get() orders() { return prisma.order.findMany(); }
  // 清理订单
  @Cron('0 * * * *') tick(): void {}
}
''', "schema.prisma": '''model Order {
  id Int @id
  @@map("biz_order")
}
'''},
}


def setup_run(tmp_path, monkeypatch, files):
    root = create_project(tmp_path / "project", files)
    state = tmp_path / "state"
    monkeypatch.setattr(cli, "state_root", lambda: state)
    monkeypatch.setattr(host, "state_root", lambda: state)
    monkeypatch.setattr(documents, "state_root", lambda: state)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    args = ["--project", str(root)]
    assert cli.init_command(args) == cli.discover_command(args) == 0
    assert cli.check_command([*args, "--stage", "entries"]) == 0
    assert cli.prepare_command([*args, "--confirm"]) == 0
    path = next(p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32)
    return root, state, path, json.loads(path.read_text(encoding="utf-8"))


def submit(root, state, manifest, payload):
    path = state / "submission.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cli.collect_command(["--project", str(root), "--run-id", manifest["run_id"], "--results", str(path)])


@pytest.mark.parametrize("stack", SOURCES)
@pytest.mark.parametrize("mode", ["native", "parallel", "serial"])
def test_three_stacks_complete_and_retry_without_losing_mapping(tmp_path, monkeypatch, stack, mode):
    started = time.monotonic()
    root, state, path, manifest = setup_run(tmp_path, monkeypatch, SOURCES[stack])
    assert any(action["details"]["resource_name"] == "biz_order" for facts in manifest["entry_facts"].values() for action in facts["persistence_actions"])
    payload = fixture_submission(manifest)
    if mode == "parallel":
        payload["parallel"] = True
        payload["execution"]["active_observations"] = [{
            "observed_at": "2026-10-13T00:00:00+00:00", "time_source": "coordinator_observed",
            "tool_reference": "fixture://running-snapshot",
            "active_task_ids": [task["task_id"] + ":1" for task in manifest["tasks"]]}]
    if mode == "serial":
        payload.update(mode="serial", completed_child_agents=0,
                       serial_approval={"choice_reference": "fixture://explicit-serial-choice", "scope": list(payload["results"])})
        payload["execution"] = {"receipts": [], "active_observations": []}
    # Void completion is a source-proven resolution, not an invented return value.
    for entry_id, facts in manifest["entry_facts"].items():
        outcome = next((o for o in facts["outcomes"] if o["type"] == "normal_completion" and o["phase"] == "entry"), None)
        if outcome:
            payload["results"][entry_id]["analysis"]["resolutions"] = [{
                "finding": "OUTCOME_UNRESOLVED|" + outcome["fact_id"], "classification": "normal_completion",
                "evidence": [p for p in facts["sources"] if p["evidence_id"] in outcome["evidence_refs"]],
                "path": fact_path(facts, outcome["fact_id"]), "controls": [entry_id, *outcome["conditions"]],
                "unknowns": [], "explanation": "源码处理器正常结束；void 不代表缺少业务结果。"}]
    for receipt in payload["execution"]["receipts"]:
        receipt["result_hash"] = digest(payload["results"][receipt["task_id"].removeprefix("entry:")])
    broken = copy.deepcopy(payload)
    first = next(iter(broken["results"]))
    broken["results"][first]["analysis"]["facts_hash"] = "0" * 64
    assert submit(root, state, manifest, broken) == 8
    assert json.loads(path.read_text(encoding="utf-8"))["mapping"] == manifest["mapping"]
    assert cli.prepare_command(["--project", str(root), "--resume", manifest["run_id"]]) == 0
    assert submit(root, state, manifest, payload) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.check_command(args) == 0
    assert cli.verify_command(args) == cli.verify_command(args) == 0
    assert cli.accept_command(args) == 0
    recorded = json.loads((root / "docs/biz-flow/biz-flow-doc-generator-version.json").read_text(encoding="utf-8"))
    assert recorded["source"]["git_commit"] == manifest["source_commit"]
    assert not (state / "biz-flow" / manifest["run_id"] / "source").exists()
    assert cli.check_command(args) == 0
    module = root / "docs/biz-flow" / manifest["mapping"]["modules"][0]["file"]
    original = module.read_bytes()
    module.write_bytes(original.replace(b"sequenceDiagram", b"invalidDiagram", 1))
    assert cli.check_command(args) == 1
    report = json.loads(path.with_suffix(".check.json").read_text(encoding="utf-8"))
    assert any(g["gate"] == "markdown_structure" and g["executed"] and not g["passed"] for g in report["gates"])
    assert all(set(("gate", "executed", "passed", "errors")) <= set(g) for g in report["gates"])
    module.write_bytes(original)
    assert cli.check_command(args) == 0
    assert time.monotonic() - started < 300


def test_target_is_unchanged_by_dirty_checkout_new_head_and_worktrees(tmp_path, monkeypatch):
    root, state, path, manifest = setup_run(tmp_path, monkeypatch, SOURCES["python"])
    before = scan(root, manifest["source_commit"])
    (root / "app.py").write_text("this is unrelated user work", encoding="utf-8")
    for index in range(32):
        worktree = root / ".worktrees" / str(index)
        worktree.mkdir(parents=True)
        (worktree / "app.py").write_text(SOURCES["python"]["app.py"], encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "parallel work"], cwd=root, check=True)
    (root / "untracked.py").write_text("untracked", encoding="utf-8")
    after = scan(root, manifest["source_commit"])
    assert before.source_fingerprint == after.source_fingerprint == manifest["source_fingerprint"]
    assert before.entries == after.entries and after.git.dirty
    assert not any("worktrees" in file or "untracked" in file for file in after.files)
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0


def test_java_construction_and_caught_failure_survive_full_fixture_lifecycle(tmp_path, monkeypatch):
    root, state, path, manifest = setup_run(tmp_path, monkeypatch, {"Controller.java": '''class Controller {
  // 接收订单
  @PostMapping("/orders") void receive() {
    try { new Task().process(); unreachable(); }
    catch (RuntimeException error) { recover(); } finally { cleanup(); }
  }
  void unreachable() { missing(); } void recover() {} void cleanup() {}
}
class Base { Base() { initialize(); } void initialize() {} }
class Task extends Base { int attempts = initialAttempts();
  int initialAttempts() { return 1; }
  void process() { throw new IllegalArgumentException("failed"); }
}'''})
    facts = next(iter(manifest["entry_facts"].values()))
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == [
        "Task", "Base", "initialize", "initialAttempts", "process", "recover", "cleanup"]
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.check_command(args) == cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
    accepted = json.loads(path.read_text(encoding="utf-8"))
    assert accepted["status"] == "accepted" and accepted["snapshot_cleaned"]


def test_delivery_summary_requires_same_source_fingerprint(tmp_path, monkeypatch):
    files = {**SOURCES["python"], "unused.py": "def helper(): return 0\n"}
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, files)
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
    assert cli._delivery_summary(manifest)["overall_status"] == "success"
    # The fixed commit and entry mapping stay the same, but the evidence scope changes.
    (root / ".git/info/exclude").write_text("unused.py\n", encoding="utf-8")
    current = copy.deepcopy(manifest)
    current["source_fingerprint"] = scan(root, manifest["source_commit"]).source_fingerprint
    assert current["source_fingerprint"] != manifest["source_fingerprint"]
    result = cli._delivery_summary(current)
    assert result["overall_status"] == "partial" and not result["full_scope_accepted"]
    assert not result["accepted_modules"]


def test_text_fingerprints_normalize_line_endings(tmp_path):
    file = tmp_path / "a.py"
    file.write_bytes(b"first\nsecond\n")
    expected = _fingerprint_files(tmp_path, [file])
    file.write_bytes(b"first\r\nsecond\r\n")
    assert _fingerprint_files(tmp_path, [file]) == expected


def test_preflight_gate_failures_are_explicit(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    monkeypatch.setattr(cli, "state_root", lambda: state)
    monkeypatch.setattr(host, "state_root", lambda: state)
    root = create_project(tmp_path / "project", {"app.py": "x = 1\n"})
    args = ["--project", str(root)]
    for command in (cli.check_command, cli.verify_command):
        assert command(args) != 0
        report = json.loads(capsys.readouterr().out)
        assert any(g["gate"] == "input_contract" and g["executed"] and not g["passed"] for g in report["gates"])
        assert all(g["executed"] or g["warning"] for g in report["gates"])
    assert cli.init_command(args) == 0
    capsys.readouterr()
    for command in (cli.check_command, cli.verify_command):
        assert command([*args, "--run-id", "0" * 32]) != 0
        report = json.loads(capsys.readouterr().out)
        assert report["gates"][0]["executed"]
        assert "RUN_MANIFEST_UNAVAILABLE" in report["errors"][0]
    from toolkit.cli import _run_domain
    for command in ("check", "verify"):
        response, code = _run_domain("biz-flow", [command, *args, "--run-id", "0" * 32], full=False)
        assert code and not response["ok"]
        assert response["data"]["gates"][0]["executed"]


def test_shared_run_cleanup_is_scoped_and_removes_caches(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_root", lambda: tmp_path)
    monkeypatch.setattr(host, "state_root", lambda: tmp_path)
    root = tmp_path / "biz-flow"
    root.mkdir()
    for run_id in ("0" * 32, "1" * 32):
        (root / run_id).mkdir()
        (root / (run_id + ".json")).write_text('{"status":"prepared"}', encoding="utf-8")
        (root / (run_id + ".tasks.json")).write_text("{}", encoding="utf-8")
    (root / "unrelated.txt").write_text("preserve", encoding="utf-8")
    (root / "facts-cache").mkdir()
    assert cli.clean_command([]) == 0
    assert len(json.loads(capsys.readouterr().out)["runs"]) == 2
    assert cli.clean_command(["--run-id", "0" * 32]) == 0
    assert not (root / ("0" * 32)).exists()
    assert (root / ("1" * 32)).is_dir() and (root / "facts-cache").is_dir()
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        cli.clean_command(["--run-id", "../escape"])
    assert cli.clean_command(["--all"]) == 0
    assert list(root.iterdir()) == [root / "unrelated.txt"]


def test_resolution_cannot_waive_unknown_call_or_forge_source(tmp_path):
    root = create_project(tmp_path, {"Controller.java": '''class Controller {
 @GetMapping("/work") void work() { if (true && false) {} }
}'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    from test_sequence_renderer import analysis
    value = analysis(facts)
    target = next(b for b in facts["branches"] if b["type"] == "short_circuit")
    value["resolutions"] = [{"finding": "BRANCH_LINE_UNRESOLVED|" + target["fact_id"],
        "classification": "non_business_decision", "evidence": copy.deepcopy([p for p in facts["sources"] if p["evidence_id"] in target["evidence_refs"]]),
        "path": fact_path(facts, target["fact_id"]), "controls": [facts["entry_id"], *target["conditions"]],
        "unknowns": [], "explanation": "条件连接符控制求值顺序，不单列为业务决策。"}]
    assert validate_entry_analysis(value, facts) == []
    value["resolutions"][0]["evidence"][0]["content_hash"] = "0" * 64
    assert any("RESOLUTION_EVIDENCE_INVALID" in error for error in validate_entry_analysis(value, facts))


def test_user_names_descriptions_and_confirmation_survive_two_collections(tmp_path, monkeypatch):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, SOURCES["java"])
    overview = root / "docs/biz-flow/业务流程覆盖总览.md"
    old_file = manifest["mapping"]["modules"][0]["file"]
    text = overview.read_text(encoding="utf-8").replace('file="' + old_file + '"', 'file="00-已确认订单.md"')
    text = text.replace("| " + old_file.removesuffix(".md") + " |", "| 00-已确认订单 |")
    rows = text.splitlines()
    row = next(i for i, line in enumerate(rows) if line.startswith("| 00-已确认订单 |"))
    cells = rows[row].split("|")
    cells[2] = " 用户保留的业务描述 "
    rows[row] = "|".join(cells)
    overview.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert cli.prepare_command(["--project", str(root)]) == 8
    for iteration in range(2):
        args = ["--project", str(root), *(["--confirm"] if iteration == 0 else [])]
        assert cli.prepare_command(args) == 0
        paths = [p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32]
        path = max(paths, key=lambda p: p.stat().st_mtime_ns)
        current = json.loads(path.read_text(encoding="utf-8"))
        assert current["mapping"]["modules"][0]["file"] == "00-已确认订单.md"
        assert current["mapping"]["modules"][0]["responsibility"] == "用户保留的业务描述"
        assert submit(root, state, current, fixture_submission(current)) == 0
    assert not (root / "docs/biz-flow" / old_file).exists()
    assert len(list((root / "docs/biz-flow").glob("[0-9]*.md"))) == 1


def test_three_resolution_types_are_source_proven_persisted_and_visible(tmp_path, monkeypatch):
    root, state, path, manifest = setup_run(tmp_path, monkeypatch, {"app.py": '''from fastapi import FastAPI
app=FastAPI()
@app.get('/orders')
def handle(cache:dict, enabled:bool, ready:bool):
    if enabled and ready:
        cache.get('orders')
'''})
    entry_id, facts = next(iter(manifest["entry_facts"].items()))
    payload = fixture_submission(manifest)
    selected = [("OUTCOME_UNRESOLVED", "normal_completion", next(o for o in facts["outcomes"] if o["type"] == "normal_completion")),
        ("BRANCH_LINE_UNRESOLVED", "non_business_decision", next(b for b in facts["branches"] if b["type"] == "short_circuit")),
        ("PERSISTENCE_OBJECT_UNRESOLVED", "non_persistence", next(c for c in facts["calls"] if c["type"] == "pure_or_memory"))]
    payload["results"][entry_id]["analysis"]["resolutions"] = [{"finding": code + "|" + target["fact_id"],
        "classification": classification, "path": fact_path(facts, target["fact_id"]),
        "controls": [entry_id, *target["conditions"]], "unknowns": [], "explanation": "本次快照中有静态类型与控制流证据。",
        "evidence": copy.deepcopy([p for p in facts["sources"] if p["evidence_id"] in target["evidence_refs"]])}
        for code, classification, target in selected]
    payload["execution"]["receipts"][0]["result_hash"] = digest(payload["results"][entry_id])
    assert submit(root, state, manifest, payload) == 0
    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert len(recorded["results"][entry_id]["analysis"]["resolutions"]) == 3
    module = root / "docs/biz-flow" / manifest["mapping"]["modules"][0]["file"]
    content = module.read_text(encoding="utf-8")
    assert all(caption in content for caption in ("正常完成说明", "非业务决策行", "误判说明"))


def test_blocked_module_does_not_prevent_other_module_acceptance(tmp_path, monkeypatch, capsys):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, {"app.py": '''from fastapi import FastAPI
app = FastAPI()
@app.get('/ready')
def ready(): return 1
@app.get('/blocked')
def blocked(): return dynamic_call()
app.get(dynamic_path, blocked)
'''})
    assert any(f["gaps"] for f in manifest["entry_facts"].values())
    ready = next(m for m in manifest["mapping"]["modules"] if any("/ready:" in i for i in m["entry_ids"]))
    assert cli.prepare_command(["--project", str(root), "--module", ready["name"]]) == 0
    path = max([p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32], key=lambda p: p.stat().st_mtime_ns)
    selected = json.loads(path.read_text(encoding="utf-8"))
    assert submit(root, state, selected, fixture_submission(selected)) == 0
    args = ["--project", str(root), "--run-id", selected["run_id"]]
    assert cli.check_command(args) == cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
    output = capsys.readouterr().out
    assert '"overall_status": "partial"' in output and '"blocked_modules"' in output
    lock = json.loads((root / "docs/biz-flow/biz-flow-doc-generator-version.json").read_text(encoding="utf-8"))
    assert lock["source"]["git_commit"] is None


def test_module_filter_never_advances_baseline_even_when_it_covers_all_entries(tmp_path, monkeypatch):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, {
        "app.py": "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/orders')\ndef orders(): return 1\n"})
    assert len(manifest["mapping"]["modules"]) == 1
    args = ["--project", str(root)]
    assert cli.prepare_command([*args, "--module", manifest["mapping"]["modules"][0]["name"]]) == 0
    path = max((p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32),
               key=lambda p: p.stat().st_mtime_ns)
    selected = json.loads(path.read_text(encoding="utf-8"))
    assert submit(root, state, selected, fixture_submission(selected)) == 0
    selected_args = [*args, "--run-id", selected["run_id"]]
    assert cli.verify_command(selected_args) == cli.verify_command(selected_args) == cli.accept_command(selected_args) == 0
    lock = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    assert json.loads(lock.read_text(encoding="utf-8"))["source"]["git_commit"] is None
    summary = cli._delivery_summary(selected)
    assert summary["overall_status"] == "partial" and not summary["full_scope_accepted"]


@pytest.mark.parametrize("partial", [False, True])
def test_registration_gap_blocks_full_acceptance_but_keeps_module_delivery(tmp_path, monkeypatch, partial):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, {
        "app.py": "from fastapi import FastAPI\napp=FastAPI()\n# 查询订单\n@app.get('/orders')\ndef orders(): return []\n",
        "registrations.yaml": "jobs: ${runtime.jobs}\n",
    })
    assert scan(root, entry_only=True).coverage_gaps
    if partial:
        assert cli.prepare_command(["--project", str(root), "--module", manifest["mapping"]["modules"][0]["name"]]) == 0
        path = max((p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32), key=lambda p: p.stat().st_mtime_ns)
        manifest = json.loads(path.read_text(encoding="utf-8"))
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.check_command(args) == (0 if partial else 1)
    assert cli.verify_command(args) == cli.verify_command(args) == (0 if partial else 1)
    assert cli.accept_command(args) == (0 if partial else 8)
    lock = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    assert json.loads(lock.read_text(encoding="utf-8"))["source"]["git_commit"] is None


def test_prepare_diagnostics_bind_blocked_entries_to_sources_and_receiver(tmp_path, monkeypatch):
    root, _, path, manifest = setup_run(tmp_path, monkeypatch, {"Controller.java": '''
import java.util.concurrent.ExecutorService;
class Controller { ExecutorService executor;
  // 后台处理订单
  @PostMapping("/orders") void orders() {
    try { executor.submit(() -> work()); } catch (RuntimeException e) {}
  }
  void work() {}
}'''})
    package = path.with_suffix(".tasks.json").read_bytes()
    output = cli._prepared_output(path, manifest)
    report = json.loads(Path(output["behavior_report"]).read_text(encoding="utf-8"))
    assert report["package_hash"] == manifest["package_hash"] and report["source_commit"] == manifest["source_commit"]
    module = report["modules"][0]
    assert module["blocked_entries"] == 1 and module["zero_gap_entries"] == 0
    entry = module["entries"][0]
    assert entry["status"] == "blocked" and entry["entry_id"] in manifest["entry_facts"]
    gap = next(g for g in entry["gaps"] if g["code"] == "EXECUTOR_SCHEDULING_UNRESOLVED")
    assert gap["sources"][0]["file"] == "Controller.java"
    assert gap["call_bindings"][0]["receiver_type"] == "java.util.concurrent.ExecutorService"
    assert gap["call_bindings"][0]["method"] == "submit"
    assert cli.prepare_command(["--project", str(root), "--resume", manifest["run_id"]]) == 0
    assert path.with_suffix(".tasks.json").read_bytes() == package


def test_missing_renderer_blocks_verification_and_baseline(tmp_path, monkeypatch, capsys):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, SOURCES["python"])
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == 0
    capsys.readouterr()
    with monkeypatch.context() as patch:
        patch.setattr(cli.shutil, "which", lambda name: None)
        assert cli.verify_command(args) == 1
        report = json.loads(capsys.readouterr().out)
        gate = next(g for g in report["gates"] if g["gate"] == "mermaid_render")
        assert not gate["executed"] and not gate["passed"]
        assert "MERMAID_RENDERER_UNAVAILABLE" in gate["errors"][0]
        assert cli.accept_command(args) == 8
    lock = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    assert json.loads(lock.read_text(encoding="utf-8"))["source"]["git_commit"] is None
    assert cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0


@pytest.mark.parametrize("damaged", ["document", "package"])
def test_failed_verify_requires_two_new_passes_and_accepted_runs_remain_checkable(tmp_path, monkeypatch, damaged):
    root, state, path, manifest = setup_run(tmp_path, monkeypatch, SOURCES["python"])
    payload = fixture_submission(manifest)
    assert submit(root, state, manifest, payload) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == 0
    target = (path.with_suffix(".tasks.json") if damaged == "package" else
              root / "docs/biz-flow" / manifest["mapping"]["modules"][0]["file"])
    original = target.read_bytes()
    if damaged == "package":
        target.unlink()
    else:
        target.write_bytes(original.replace(b"sequenceDiagram", b"invalidDiagram", 1))
    assert cli.verify_command(args) == 1
    invalidated = json.loads(path.read_text(encoding="utf-8"))
    assert invalidated["verification_runs"] == 0 and invalidated["status"] == "collected"
    target.write_bytes(original)
    assert cli.accept_command(args) == 8
    assert cli.verify_command(args) == 0
    assert cli.accept_command(args) == 8
    assert cli.verify_command(args) == cli.accept_command(args) == 0
    version = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    accepted_version = version.read_bytes()
    assert cli.verify_command(args) == cli.verify_command(args) == cli.check_command(args) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "accepted"
    assert submit(root, state, manifest, payload) == 0
    assert version.read_bytes() == accepted_version


@pytest.mark.parametrize("alias", ["symlink", "junction"])
def test_accept_rejects_run_directory_alias_without_changing_baseline(tmp_path, monkeypatch, alias):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, SOURCES["python"])
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == 0
    run_root = state / "biz-flow" / manifest["run_id"]
    outside = tmp_path / "outside"
    assert run_root.resolve().is_relative_to(tmp_path.resolve())
    assert outside.resolve().is_relative_to(tmp_path.resolve())
    run_root.rename(outside)
    if alias == "junction":
        if os.name != "nt":
            pytest.skip("Windows junction regression")
        created = subprocess.run(["cmd", "/c", "mklink", "/J", str(run_root), str(outside)], capture_output=True)
        assert created.returncode == 0, created.stderr.decode(errors="replace")
    else:
        try:
            run_root.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlink unavailable: {exc}")
    try:
        version = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
        original = version.read_bytes()
        assert cli.accept_command(args) == 8
        assert version.read_bytes() == original
        assert (outside / "source/app.py").is_file()
    finally:
        if alias == "junction":
            run_root.rmdir()
        else:
            run_root.unlink()


@pytest.mark.parametrize("partial", [False, True])
def test_snapshot_cleanup_failure_does_not_advance_baseline(tmp_path, monkeypatch, partial):
    root, state, _, manifest = setup_run(tmp_path, monkeypatch, SOURCES["python"])
    assert submit(root, state, manifest, fixture_submission(manifest)) == 0
    args = ["--project", str(root), "--run-id", manifest["run_id"]]
    assert cli.verify_command(args) == cli.verify_command(args) == 0
    source = Path(manifest["tasks"][0]["source_snapshot"])
    remove = cli.shutil.rmtree
    def fail_cleanup(target, *positional, **kwargs):
        if Path(target) == io_path(source):
            if partial:
                (source / "app.py").unlink()
            raise PermissionError("fixture: source cleanup denied")
        return remove(target, *positional, **kwargs)
    version = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    original = version.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(cli.shutil, "rmtree", fail_cleanup)
        assert cli.accept_command(args) == 8
    assert version.read_bytes() == original
    assert cli.accept_command(args) == 0


def test_gitignore_exclude_and_tool_trees_are_never_evidence(tmp_path):
    code = "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/x')\ndef handle(): return 1\n"
    root = create_project(tmp_path, {"app.py": code, ".gitignore": "ignored/*\n!ignored/keep.py\n",
        "ignored/drop.py": code, "ignored/keep.py": code, "local.py": code,
        ".devflow-biz-flow.json": '{"exclude":["extra"]}', "extra/drop.py": code,
        **{f".worktrees/{i}/app.py": code for i in range(32)}})
    (root / ".git/info/exclude").write_text("local.py\n", encoding="utf-8")
    result = scan(root)
    assert set(result.files) == {".gitignore", ".devflow-biz-flow.json", "app.py", "ignored/keep.py"}
    assert len(result.entries) == 2


def test_1500_file_lifecycle_budget_and_ten_byte_identical_documents(tmp_path, monkeypatch):
    started = time.monotonic()
    files = {f"module{i}/app.py": f"from fastapi import FastAPI\napp=FastAPI()\n@app.get('/m{i}')\ndef handle(): return {i}\n" for i in range(10)}
    files.update({f"assets/file{i}.txt": "committed fixture evidence\n" for i in range(1490)})
    root, state, _, _ = setup_run(tmp_path, monkeypatch, files)
    original = None
    for iteration in range(2):
        if iteration:
            assert cli.prepare_command(["--project", str(root)]) == 0
        path = max([p for p in (state / "biz-flow").glob("*.json") if len(p.stem) == 32], key=lambda p: p.stat().st_mtime_ns)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert submit(root, state, manifest, fixture_submission(manifest)) == 0
        args = ["--project", str(root), "--run-id", manifest["run_id"]]
        assert cli.check_command(args) == cli.verify_command(args) == cli.verify_command(args) == cli.accept_command(args) == 0
        current = {p.name: p.read_bytes() for p in (root / "docs/biz-flow").glob("[0-9]*.md")}
        assert len(current) == 10
        if original is not None:
            assert current == original
        original = current
    elapsed = time.monotonic() - started
    print(f"BENCHMARK files=1500 modules=10 lifecycles=2 elapsed_seconds={elapsed:.3f} budget_seconds=1800")
    assert elapsed < 1800
