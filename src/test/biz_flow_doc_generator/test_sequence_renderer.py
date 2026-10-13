"""Canonical source order and asset tampering tests."""
import copy
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_behavior_facts import project
from test_native_handoff import fixture_submission
from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.evidence import collect_evidence, digest
from toolkit.biz_flow_doc_generator.documents import render_entry
from toolkit.biz_flow_doc_generator.validation import validate_markdown_structure
from toolkit.biz_flow_doc_generator import documents


def analysis(facts):
    refs = [facts["sources"][0]["evidence_id"]]
    targets = [(f["fact_id"], f["evidence_refs"]) for k in ("calls", "branches", "persistence_actions", "effects", "outcomes") for f in facts[k]]
    targets += [(p["participant_id"], refs) for p in facts["participants"]]
    return {"entry_id": facts["entry_id"], "source_fingerprint": facts["source_fingerprint"], "facts_hash": digest(facts),
        "review": {k: {"text": "按条件处理订单并返回结果", "evidence_refs": refs} for k in ("trigger","purpose","input","outcome","failure")},
        "annotations": [{"target_id": t, "text": "订单处理" + str(i), "evidence_refs": r} for i, (t,r) in enumerate(targets)]}


def test_nested_control_and_repeated_calls_keep_actual_position(tmp_path):
    root = project(tmp_path, {"Controller.java": """
class Controller {
 Service service;
 @PostMapping("/orders") void receive(boolean ready) {
   service.before();
   if (ready) { service.process(); } else { service.recover(); }
   service.before();
 }
}
class Service { void before() {} void process() {} void recover() {} }
"""})
    facts = next(iter(collect_evidence(scan(root)).values()))
    value = analysis(facts)
    rendered = render_entry(facts, value)
    ids = {facts["entry_id"]: value}
    assert validate_markdown_structure(rendered, ids, {facts["entry_id"]: facts}) == []
    calls = [c for c in facts["calls"] if c["details"]["method"] == "before"]
    assert len(calls) == 2 and calls[0]["context_id"] != calls[1]["context_id"]
    lines = rendered.splitlines()
    i = next(i for i,l in enumerate(lines) if "->>" in l)
    j = next(i for i,l in enumerate(lines[i+1:],i+1) if "->>" in l)
    lines[i],lines[j] = lines[j],lines[i]
    assert validate_markdown_structure("\n".join(lines), ids, {facts["entry_id"]: facts})


def test_comment_ids_cannot_hide_deleted_branch_or_result(tmp_path):
    root = project(tmp_path, {"app.py": """from fastapi import FastAPI
app=FastAPI()
# 查询订单
@app.get('/orders')
def orders(ready):
    if ready:
        return []
    return None
"""})
    facts = next(iter(collect_evidence(scan(root)).values()))
    value = analysis(facts)
    rendered = render_entry(facts, value)
    altered = "\n".join(l for l in rendered.splitlines() if not l.startswith("alt "))
    assert validate_markdown_structure(altered, {facts["entry_id"]: value}, {facts["entry_id"]: facts})


def test_repository_actions_and_method_results_keep_the_service_sender(tmp_path):
    root = project(tmp_path, {
        "pom.xml": """<project><dependencies><dependency>
<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa</artifactId>
<version>3.3.0</version></dependency></dependencies></project>""",
        "Controller.java": """
import org.springframework.data.jpa.repository.JpaRepository;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.Column;
class Controller {
 Service service;
 @PostMapping("/orders") void receive(Order order) { service.process(order); }
}
class Service { OrderRepository repository;
 void process(Order order) { repository.save(order); }
}
interface OrderRepository extends JpaRepository<Order, Long> {}
// 订单记录
@Entity @Table(name="order_record") class Order {
 // 订单编号
 @Column(name="order_id") Long id;
}
"""})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    value = analysis(facts)
    call = next(c for c in facts["calls"] if c["details"]["method"] == "save")
    save = facts["persistence_actions"][0]
    method_return = next(o for o in facts["outcomes"] if o["type"] == "method_return")
    labels = {a["target_id"]: a["text"] for a in value["annotations"]}
    aliases = {p["identity"]: f"A{i}" for i, p in enumerate(facts["participants"])}
    service, storage = aliases["Service"], aliases["order_record"]
    rendered = render_entry(facts, value)
    assert f'Note over {service}: {labels[call["fact_id"]]}' in rendered
    assert f'{service}->>{storage}: {labels[save["fact_id"]]}' in rendered
    assert f'Note over {service}: {labels[method_return["fact_id"]]}' in rendered
    assert not any("->>" in line and labels[call["fact_id"]] in line for line in rendered.splitlines())


def test_empty_source_branch_renders_finite_coordinates(tmp_path, monkeypatch):
    if not (shutil.which("mmdc.cmd") or shutil.which("mmdc")):
        pytest.skip("Mermaid CLI is not installed")
    monkeypatch.setattr(documents, "state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(documents, "_MERMAID_CACHE", {})
    root = project(tmp_path, {"Controller.java": """
class Controller {
 @PostMapping("/orders") void receive() { if (false) {} }
}
"""})
    facts = next(iter(collect_evidence(scan(root)).values()))
    assert not facts["gaps"]
    outputs = []
    original = subprocess.run

    def capture(args, **kwargs):
        result = original(args, **kwargs)
        outputs.append(Path(args[args.index("-o") + 1]).read_text(encoding="utf-8"))
        return result

    monkeypatch.setattr(documents.subprocess, "run", capture)
    render_entry(facts, analysis(facts))
    assert outputs and not re.search(r'="[^"]*(?:NaN|Infinity|undefined)', outputs[0])


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><line y1="NaN"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><polygon points="0,0 undefined,-Infinity"/></svg>',
    '<svg',
])
def test_successful_renderer_cannot_pass_broken_svg(svg, monkeypatch):
    monkeypatch.setattr(documents.shutil, "which", lambda _: "mmdc")

    def render(args, **kwargs):
        Path(args[args.index("-o") + 1]).write_text(svg, encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(documents.subprocess, "run", render)
    assert documents._validate_mermaid("sequenceDiagram\nautonumber\nparticipant A as A\nA->>A: process")


def test_cache_trimming_tolerates_concurrent_removal(tmp_path, monkeypatch):
    import os
    from toolkit.biz_flow_doc_generator.evidence import trim_cache

    caches = [tmp_path / (str(index) * 64 + ".json") for index in range(1, 4)]
    for index, path in enumerate(caches, 1):
        path.write_text("{}", encoding="utf-8")
        os.utime(path, (index, index))
    recovery = tmp_path / "recovery.json"
    recovery.write_text("{}", encoding="utf-8")
    original = Path.stat

    def stat(path, *args, **kwargs):
        if path == caches[0]:
            path.unlink(missing_ok=True)
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        trim_cache(tmp_path, limit=1)
    assert not caches[0].exists() and not caches[1].exists()
    assert caches[2].exists() and recovery.exists()
