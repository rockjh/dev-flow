"""Static registration and cross-language proof boundaries for generic v1."""
import subprocess
from pathlib import Path

import pytest

from toolkit.biz_flow_doc_generator import documents
from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.evidence import collect_evidence
from toolkit.biz_flow_doc_generator.storage import sql_resources
from toolkit.core.schema import BIZ_FLOW_ENTRY_FACTS_SCHEMA, validate_schema
from test_behavior_facts import project
from test_sequence_renderer import analysis


@pytest.mark.parametrize("file,source,kind,identifier", [
    ("Spring.java", 'class Spring {\n @GetMapping("/orders") void handle() {}\n}', "url", "GET /orders"),
    ("Jax.java", '@Path("/orders")\nclass Jax {\n @Path("/active")\n @GET\n void handle() {}\n}', "url", "GET /orders/active"),
    ("app.py", "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/orders')\ndef handle(): return 1", "url", "GET /orders"),
    ("main.ts", "function handle() {return 1;}\napp.get('/orders', handle);", "url", "GET /orders"),
    ("main.ts", "@Controller('/orders')\nclass Orders {\n @Get()\n handle() {return 1;}\n}", "url", "GET /orders"),
    ("Kafka.java", 'class Kafka {\n @KafkaListener(topics="orders") void handle() {}\n}', "message", "orders"),
    ("Rocket.java", '@RocketMQMessageListener(topic="orders")\nclass Rocket {\n void onMessage(String value) {}\n}', "message", "orders"),
    ("Rabbit.java", 'class Rabbit {\n @RabbitListener(queues="orders") void handle() {}\n}', "message", "orders"),
    ("Job.java", 'class Job {\n @XxlJob("orders.cleanup") void handle() {}\n}', "scheduled", "orders.cleanup"),
    ("Job.java", 'class Job {\n @Scheduled(cron="0 * * * * *") void handle() {}\n}', "scheduled", "0 * * * * *"),
    ("jobs.py", "from apscheduler.schedulers.background import BackgroundScheduler\nscheduler=BackgroundScheduler()\n@scheduler.scheduled_job('cron')\ndef handle(): pass", "scheduled", "cron"),
    ("jobs.py", "from apscheduler.schedulers.background import BackgroundScheduler\nscheduler=BackgroundScheduler()\ndef handle(): pass\nscheduler.add_job(handle, 'cron')", "scheduled", "cron"),
    ("cli.py", "def main(): return 1\nif __name__ == '__main__':\n    main()", "cli", "cli.py"),
    ("Events.java", 'class Events {\n @EventListener(OrderCreated.class) void handle() {}\n}', "event", "OrderCreated"),
    ("events.ts", "class Events {\n @OnEvent('order.created')\n handle() {return 1;}\n}", "event", "order.created"),
    ("Import.java", 'class Import {\n @FileListener(path="/imports/orders.csv") void handle() {}\n}', "file", "/imports/orders.csv"),
])
def test_trigger_registration_matrix(tmp_path, file, source, kind, identifier):
    result = scan(project(tmp_path, {file: source}), entry_only=True)
    entries = [e for e in result.entries if e.kind == kind and e.identifier == identifier]
    assert len(entries) == 1 and entries[0].source_evidence
    assert entries[0].handler_confirmed


@pytest.mark.parametrize("file,source", [
    ("app.py", "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/x')\ndef handle(a,b,c):\n    try:\n        if a and b or c:\n            return 1\n        else:\n            raise ValueError('DECLINED')\n    except ValueError:\n        return 2\n"),
    ("main.ts", "class Events {\n @MessagePattern('orders')\n handle(a: boolean,b: boolean,c: boolean) { try { if(a && b || c) {return 1;} else {throw 'DECLINED';} } catch(e) {return 2;} }\n}"),
    ("Controller.java", "class Controller {\n @KafkaListener(topics=\"orders\") int handle(boolean a,boolean b,boolean c) { try { if(a && b || c) {return 1;} else {throw new IllegalArgumentException(\"DECLINED\");} } catch(IllegalArgumentException e) {return 2;} }\n}"),
    ("main.go", 'package main\nimport "net/http"\nfunc handle(w http.ResponseWriter,r *http.Request) { if true && false || true {return} else {return} }\nfunc main() {http.HandleFunc("/x",handle)}'),
])
def test_branch_connectors_and_converted_results_are_source_facts(tmp_path, file, source):
    facts = next(iter(collect_evidence(scan(project(tmp_path, {file: source}))).values()))
    assert validate_schema(BIZ_FLOW_ENTRY_FACTS_SCHEMA, facts) == []
    assert not facts["gaps"]
    assert len([b for b in facts["branches"] if b["type"] == "short_circuit"]) == 2
    assert len(facts["outcomes"]) >= 2
    documents.render_entry(facts, analysis(facts))


@pytest.mark.parametrize("file,source", [
    ("Controller.java", 'class Controller {\n @GetMapping("/x") int handle(int x) {for(int i=0;i<3;i++){} switch(x){case 1:return 1;default:return 2;}}\n}'),
    ("main.ts", "function handle(x:number) {for(let i=0;i<3;i++){} switch(x){case 1:return 1;default:return 2;}}\napp.get('/x',handle);"),
    ("main.go", 'package main\nimport "net/http"\nfunc handle(w http.ResponseWriter,r *http.Request) {for i:=0; i<3; i++ {} ; switch r.Method {case "GET": return; default: return}}\nfunc main(){http.HandleFunc("/x",handle)}'),
    ("app.py", "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/x')\ndef handle(x):\n    for i in range(3): pass\n    match x:\n        case 1: return 1\n        case _: return 2\n"),
])
def test_static_loop_and_switch_arms_have_complete_proven_results(tmp_path, file, source):
    facts = next(iter(collect_evidence(scan(project(tmp_path, {file: source}))).values()))
    assert not facts["gaps"]
    assert len(facts["branches"]) == 2
    assert len(facts["outcomes"]) == 2
    documents.render_entry(facts, analysis(facts))


def test_sql_literals_do_not_guess_objects_inside_values_or_partial_names():
    assert sql_resources("SELECT id FROM biz_order WHERE note='FROM imaginary'") == [("biz_order", "read")]
    assert sql_resources("UPDATE biz_order SET status='SELECT'") == [("biz_order", "update")]
    for value in ("SELECT * FROM biz-order", 'SELECT * FROM "biz_order"',
                  "SELECT * FROM (SELECT * FROM biz_order) q", "SELECT * FROM a,b", "SELECT * FROM a; DELETE FROM b"):
        assert sql_resources(value) == []


def test_unproven_java_switch_rules_remain_explicit_gaps(tmp_path):
    root = project(tmp_path, {"Controller.java": 'class Controller {\n @GetMapping("/x") void handle(int x) {switch(x){case 1 -> {} default -> {}}}\n}'})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert any(g["code"] == "SWITCH_RULE_UNRESOLVED" for g in facts["gaps"])


@pytest.mark.parametrize("file,source,system", [
    ("app.py", "import requests\nfrom fastapi import FastAPI\napp=FastAPI()\n@app.get('/x')\ndef handle(): return requests.get('https://orders.example.invalid/v1')", "orders.example.invalid"),
    ("main.ts", "function handle() {return fetch(\"https://orders.example.invalid/v1\");}\napp.get('/x',handle);", "orders.example.invalid"),
    ("main.go", 'package main\nimport "net/http"\nfunc handle(w http.ResponseWriter,r *http.Request) {http.Get("https://orders.example.invalid/v1")}\nfunc main() {http.HandleFunc("/x",handle)}', "orders.example.invalid"),
    ("Controller.java", 'import org.springframework.cloud.openfeign.FeignClient;\n@RestController\nclass Controller { Client client;\n @GetMapping("/x") String handle() {return client.orders();}\n}\n@FeignClient(name="order-system")\ninterface Client { @GetMapping("/orders") String orders(); }', "order-system"),
])
def test_literal_external_destination_is_proven_without_claiming_delivery(tmp_path, file, source, system):
    facts = next(iter(collect_evidence(scan(project(tmp_path, {file: source}))).values()))
    assert not facts["gaps"]
    assert validate_schema(BIZ_FLOW_ENTRY_FACTS_SCHEMA, facts) == []
    assert any(p["identity"] == system and p["role"] == "external" for p in facts["participants"])
    assert any(e["details"].get("delivery") == "not established" for e in facts["effects"])


def test_lazy_query_is_not_io_and_unmapped_orm_is_unresolved(tmp_path):
    source = "from fastapi import FastAPI\nfrom sqlalchemy.orm import Session\napp=FastAPI()\n@app.get('/x')\ndef handle(session:Session): return session.query(Unknown)"
    facts = next(iter(collect_evidence(scan(project(tmp_path / "lazy", {"app.py": source}))).values()))
    assert not facts["persistence_actions"] and not facts["gaps"]
    source += ".all()"
    facts = next(iter(collect_evidence(scan(project(tmp_path / "io", {"app.py": source}))).values()))
    assert not facts["persistence_actions"]
    assert any(g["code"] == "PERSISTENCE_OBJECT_UNRESOLVED" for g in facts["gaps"])


def test_gorm_requires_entity_table_name_and_records_the_exact_object(tmp_path):
    root = project(tmp_path, {"main.go": '''package main
import "net/http"
import "gorm.io/gorm"
type Order struct { ID int }
func (Order) TableName() string { return "biz_order" }
var db *gorm.DB
func handle(w http.ResponseWriter,r *http.Request) { var orders []Order; db.Find(&orders) }
func main() { http.HandleFunc("/orders",handle) }
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    assert facts["persistence_actions"][0]["details"]["resource_name"] == "biz_order"


def test_python_literal_sql_kv_file_and_object_storage_require_bound_types(tmp_path):
    root = project(tmp_path, {"app.py": '''from fastapi import FastAPI
from sqlite3 import Connection
from redis import Redis
from mypy_boto3_s3 import S3Client
app=FastAPI()
@app.get('/objects')
def handle(db:Connection, cache:Redis, s3:S3Client):
    db.execute("SELECT * FROM biz_order")
    cache.get("orders:index")
    open("orders.csv", mode="r")
    s3.get_object(Bucket="orders", Key="current.json")
    return 1
'''})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    assert {p["details"]["resource_name"] for p in facts["persistence_actions"]} == {"biz_order", "orders:index", "orders.csv", "orders/current.json"}


def test_ninety_diagrams_reuse_persistent_render_cache_and_timeout_is_retryable(tmp_path, monkeypatch):
    monkeypatch.delenv("DEVFLOW_MERMAID_TIMEOUT", raising=False)
    renderer = tmp_path / "mmdc.cmd"
    renderer.write_text("fixture renderer", encoding="utf-8")
    monkeypatch.setattr(documents.shutil, "which", lambda name: str(renderer))
    monkeypatch.setattr(documents, "state_root", lambda: tmp_path / "state")
    calls = []
    def render(command, **kwargs):
        calls.append(command)
        Path(command[command.index("-o") + 1]).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        assert kwargs["timeout"] == 60
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(documents.subprocess, "run", render)
    graphs = [f"sequenceDiagram\nautonumber\nparticipant A as Service\nactivate A\nA->>A: action {i}\ndeactivate A\n" for i in range(90)]
    for graph in graphs:
        assert documents._validate_mermaid(graph) == []
    documents._MERMAID_CACHE.clear()
    for graph in graphs:
        assert documents._validate_mermaid(graph) == []
    assert len(calls) == 90
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)
    monkeypatch.setattr(documents.subprocess, "run", timeout)
    new = graphs[0].replace("action 0", "new action")
    assert documents._validate_mermaid(new)
    monkeypatch.setattr(documents.subprocess, "run", render)
    assert documents._validate_mermaid(new) == []
