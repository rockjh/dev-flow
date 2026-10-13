"""Supplemental evidence replaces the run; old receipts never complete a new run."""
import copy
import json
import pytest
from test_behavior_facts import project as create_project
from test_native_handoff import fixture_submission
from toolkit.biz_flow_doc_generator import cli, host
from toolkit.biz_flow_doc_generator.evidence import digest
from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.supplement import rebuild_verified, fact_path


@pytest.fixture
def request_run(tmp_path, monkeypatch):
    project = create_project(tmp_path / "project", {"Controller.java": '''
class Controller {
  // 查询订单
  @GetMapping("/orders") String orders() {
    if (false) { unknownService.execute(); }
    return "empty";
  }
}
'''})
    state = tmp_path / "state"
    monkeypatch.setattr(cli, "state_root", lambda: state)
    monkeypatch.setattr(host, "state_root", lambda: state)
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    for command in (cli.init_command, cli.discover_command):
        assert command(["--project", str(project)]) == 0
    assert cli.prepare_command(["--project", str(project), "--confirm"]) == 0
    path = next(p for p in state.glob("biz-flow/*.json") if not p.name.endswith(".tasks.json"))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    task = manifest["tasks"][0]
    facts = manifest["entry_facts"][task["entry_id"]]
    branch = facts["branches"][0]
    proof = next(s for s in facts["sources"] if s["evidence_id"] == branch["evidence_refs"][0])
    request = {"run_id": manifest["run_id"], "task_id": task["task_id"], "entry_id": task["entry_id"],
        "source_fingerprint": manifest["source_fingerprint"], "facts_hash": digest(facts),
        "target_id": branch["fact_id"], "finding_id": None, "type": "branch_classification",
        "path": [branch["fact_id"]], "controls": branch["conditions"], "sources": [copy.deepcopy(proof)],
        "binding": {"declaration_id": proof["declaration_id"], "receiver_type": "Controller",
            "parameter_types": [], "classification": "constant_false"}}
    payload = fixture_submission(manifest)
    response = {"kind": "evidence_request", "evidence_requests": [request]}
    payload["results"][task["entry_id"]] = response
    payload["execution"]["receipts"][0]["result_hash"] = digest(response)
    submission = state / "submission.json"
    return project, path, manifest, payload, submission


def collect(project, manifest, payload, submission):
    submission.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cli.collect_command(["--project", str(project), "--run-id", manifest["run_id"], "--results", str(submission)])


def test_verified_classification_rebuilds_and_refreezes_then_accepts(request_run):
    project, path, old, payload, submission = request_run
    before = path.read_bytes()
    assert collect(project, old, payload, submission) == 0
    superseded = json.loads(path.read_text(encoding="utf-8"))
    assert superseded["status"] == "superseded"
    replacement_path = path.with_name(superseded["superseded_by_run_id"] + ".json")
    new = json.loads(replacement_path.read_text(encoding="utf-8"))
    assert new["supersedes_run_id"] == old["run_id"]
    assert new["source_fingerprint"] == old["source_fingerprint"] and new["mapping_hash"] == old["mapping_hash"]
    assert new["package_hash"] != old["package_hash"] and new["results"] == {}
    facts = next(iter(new["entry_facts"].values()))
    assert facts["coverage"]["complete"] and not facts["gaps"]
    assert not any(c["details"]["method"] == "execute" for c in facts["calls"])
    assert collect(project, old, payload, submission) == 8
    assert host.validate_execution(new, payload, allow_fixture=True)
    duplicate = copy.deepcopy(next(iter(payload["results"].values()))["evidence_requests"][0])
    duplicate.update(run_id=new["run_id"], facts_hash=digest(facts))
    with pytest.raises(ValueError, match="EVIDENCE_REQUEST_NO_PROGRESS"):
        rebuild_verified(scan(project), [*new["verified_evidence"], duplicate])
    assert collect(project, new, fixture_submission(new), submission) == 0
    assert cli.check_command(["--project", str(project)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    assert cli.verify_command(["--project", str(project)]) == 0
    assert cli.accept_command(["--project", str(project), "--run-id", new["run_id"]]) == 0
    comparison = cli._source_comparison(project, scan(project), new["entry_facts"])
    assert comparison["available"]
    assert comparison["changed_entry_ids"] == comparison["added_entry_ids"] == comparison["deleted_entry_ids"] == []


@pytest.mark.parametrize("mutation", [
    lambda r: r["sources"][0].update(content_hash="forged"),
    lambda r: r.update(path=["C-unreachable"]),
    lambda r: r.update(controls=["invented"]),
    lambda r: r["binding"].update(classification="constant_true"),
    lambda r: r.update(type="resource_mapping"),
])
def test_forged_or_unsupported_request_keeps_gaps_and_assets(request_run, mutation):
    project, path, old, payload, submission = request_run
    before = {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")}
    response = next(iter(payload["results"].values()))
    mutation(response["evidence_requests"][0])
    payload["execution"]["receipts"][0]["result_hash"] = digest(response)
    assert collect(project, old, payload, submission) == 8
    current = json.loads(path.read_text(encoding="utf-8"))
    assert current["status"] == "prepared" and current["entry_facts"] == old["entry_facts"]
    assert {p.name: p.read_bytes() for p in (project / "docs/biz-flow").glob("*.md")} == before


def test_primary_binding_is_proven_by_candidate_declaration_and_replayed(tmp_path):
    project = create_project(tmp_path, {"Controller.java": '''
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;
interface Port { void process(); }
@Primary @Service class One implements Port { public void process() {} }
@Service class Two implements Port { public void process() {} }
class Wrapper { void execute(Runnable task) { task.run(); } }
class Controller { Port port; Wrapper wrapper;
  // 接收订单
  @PostMapping("/orders") void orders() { port.process(); wrapper.execute(port::process); }
}
'''})
    result = scan(project)
    facts = next(iter(rebuild_verified(result, []).values()))
    call = facts["calls"][0]
    finding = next(g for g in facts["gaps"] if g["code"] == "CALL_BINDING_AMBIGUOUS")
    request = {"run_id": "a" * 32, "task_id": "entry:" + facts["entry_id"],
        "entry_id": facts["entry_id"], "source_fingerprint": facts["source_fingerprint"],
        "facts_hash": digest(facts), "target_id": call["fact_id"], "finding_id": finding["finding_id"],
        "type": "call_binding", "path": fact_path(facts, call["fact_id"]),
        "controls": call["conditions"], "sources": [s for s in facts["sources"] if
            s["evidence_id"] in call["evidence_refs"] or s["declaration_id"] in {"One", "One.process()"}],
        "binding": {"declaration_id": "One.process()", "receiver_type": "One",
                    "parameter_types": [], "classification": "spring_primary"}}
    callback = next(c for c in facts["calls"] if c["type"] == "method_reference")
    callback_request = request_for(facts, callback, "callback_binding", copy.deepcopy(request["binding"]))
    callback_request["run_id"] = request["run_id"]
    rebuilt = rebuild_verified(result, [request, callback_request])[facts["entry_id"]]
    assert not rebuilt["gaps"]
    assert rebuilt["calls"][0]["details"]["target"] == "One.process()"
    assert rebuild_verified(result, [request, callback_request])[facts["entry_id"]] == rebuilt
    forged = copy.deepcopy(request)
    forged["binding"].update(declaration_id="Two.process()", receiver_type="Two")
    with pytest.raises(ValueError, match="CALL_BINDING_NOT_PROVEN"):
        rebuild_verified(result, [forged])


def request_for(facts, target, request_type, binding):
    finding = next((g for g in facts["gaps"] if g["target_id"] == target["context_id"]), None)
    return {"run_id": "b" * 32, "task_id": "entry:" + facts["entry_id"], "entry_id": facts["entry_id"],
        "source_fingerprint": facts["source_fingerprint"], "facts_hash": digest(facts),
        "target_id": target["fact_id"], "finding_id": finding["finding_id"] if finding else None,
        "type": request_type, "path": fact_path(facts, target["fact_id"]), "controls": target["conditions"],
        "sources": copy.deepcopy(facts["sources"]), "binding": binding}


def test_path_construction_is_verified_as_memory_not_persistence(tmp_path):
    root = create_project(tmp_path, {"Controller.java": '''
import java.nio.file.Path;
class Controller {
  // 查询订单文件名
  @GetMapping("/orders") void orders() { Path.of("orders"); }
}
'''})
    result = scan(root)
    facts = next(iter(rebuild_verified(result, []).values()))
    call = facts["calls"][0]
    request = request_for(facts, call, "behavior_classification", {
        "declaration_id": "java.nio.file.Path.of(java.lang.String,java.lang.String[])",
        "receiver_type": "java.nio.file.Path", "parameter_types": ["java.lang.String", "java.lang.String[]"],
        "classification": "java_se17_path_construction"})
    rebuilt = rebuild_verified(result, [request])[facts["entry_id"]]
    assert not rebuilt["gaps"] and not rebuilt["persistence_actions"]
    assert rebuilt["coverage"]["persistence"] == "none_in_verified_scope"
    request["binding"]["receiver_type"] = "java.nio.file.Files"
    with pytest.raises(ValueError, match="BEHAVIOR_CLASSIFICATION_NOT_PROVEN"):
        rebuild_verified(result, [request])


@pytest.mark.parametrize("explicit_table", [False, True])
def test_default_jpa_resource_is_rebuilt_from_explicit_naming_configuration(tmp_path, explicit_table):
    root = create_project(tmp_path, {"pom.xml": '''<project><dependencies><dependency>
<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa</artifactId><version>3.3.0</version>
</dependency></dependencies></project>''', "application.properties": '''
spring.jpa.hibernate.naming.physical-strategy=org.hibernate.boot.model.naming.PhysicalNamingStrategyStandardImpl
spring.jpa.hibernate.naming.implicit-strategy=org.hibernate.boot.model.naming.ImplicitNamingStrategyJpaCompliantImpl
''', "Controller.java": '''
import org.springframework.data.jpa.repository.JpaRepository;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
class Controller { Orders repository;
  // 保存订单
  @PostMapping("/orders") void orders(Order order) { repository.save(order); }
}
interface Orders extends JpaRepository<Order, Long> {}
/** 订单记录 */
@Entity TABLE_MAPPING class Order { long id; }
'''.replace("TABLE_MAPPING", '@Table(name="order_record")' if explicit_table else "")})
    result = scan(root)
    facts = next(iter(rebuild_verified(result, []).values()))
    request = request_for(facts, facts["calls"][0], "resource_mapping", {"declaration_id": "Order", "receiver_type": "Order",
        "parameter_types": [], "classification": "jpa_standard_default_columns" if explicit_table else "jpa_standard_default_table"})
    rebuilt = rebuild_verified(result, [request])[facts["entry_id"]]
    assert not rebuilt["gaps"]
    assert rebuilt["persistence_actions"][0]["details"]["resource_name"] == ("order_record" if explicit_table else "Order")
    assert rebuilt["persistence_actions"][0]["details"]["fields"] == ["id"]
    request["binding"]["declaration_id"] = "InventedTable"
    with pytest.raises(ValueError, match="RESOURCE_MAPPING_NOT_PROVEN"):
        rebuild_verified(result, [request])


def test_caught_error_outcome_requires_source_handler_and_exception_type(tmp_path):
    root = create_project(tmp_path, {"Controller.java": '''
class Controller {
  // 接收订单
  @PostMapping("/orders") void orders() {
    try { work(); } catch (RuntimeException e) { recover(); }
  }
  void work() { throw new IllegalArgumentException("invalid"); }
  void recover() {}
}
'''})
    result = scan(root)
    facts = next(iter(rebuild_verified(result, []).values()))
    outcome = next(o for o in facts["outcomes"] if o["type"] == "throw")
    proof = next(s for s in facts["sources"] if s["evidence_id"] == outcome["evidence_refs"][0])
    request = request_for(facts, outcome, "outcome_fact", {"declaration_id": proof["declaration_id"],
        "receiver_type": "java.lang.IllegalArgumentException", "parameter_types": [], "classification": "caught_error"})
    assert not facts["gaps"]
    assert outcome["details"]["caught_by"] and not outcome["details"]["observed_by_entry"]
    with pytest.raises(ValueError, match="EVIDENCE_REQUEST_NO_PROGRESS"):
        rebuild_verified(result, [request])
    request["binding"]["receiver_type"] = "java.lang.IllegalStateException"
    with pytest.raises(ValueError, match="OUTCOME_FACT_NOT_PROVEN"):
        rebuild_verified(result, [request])
