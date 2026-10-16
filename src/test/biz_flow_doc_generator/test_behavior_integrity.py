"""Regressions for semantic completeness, rather than field presence."""
import json

import pytest

from toolkit.biz_flow_doc_generator.discovery import scan
from toolkit.biz_flow_doc_generator.evidence import collect_evidence
from test_behavior_facts import project


def facts_for(tmp_path, files):
    return next(iter(collect_evidence(scan(project(tmp_path, files))).values()))


def test_java_same_short_type_names_do_not_bind_wrong_package(tmp_path):
    facts = facts_for(tmp_path, {
        "Controller.java": '''import a.Item;
class Controller { Port port;
  @PostMapping("/orders") void receive(Item item) { port.save(item); }
}
''', "Port.java": "import b.Item; class Port { void save(Item item) { missing(); } }",
        "a/Item.java": "package a; public class Item {}",
        "b/Item.java": "package b; public class Item {}",
    })
    assert facts["gaps"]
    assert not any(c["details"]["target"] == "Port.save(b.Item)" for c in facts["calls"])


def test_java_exact_overload_wins_over_object_and_numeric_widening(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''
class Controller {
  @PostMapping("/orders") void receive() { save("order"); count(1); }
  void save(String value) {} void save(Object value) { missing(); }
  void count(int value) {} void count(long value) { missing(); }
}'''})
    assert not facts["gaps"]
    assert [c["details"]["target"] for c in facts["calls"]] == [
        "Controller.save(java.lang.String)", "Controller.count(int)"]


@pytest.mark.parametrize("operator,arm", [("&&", "left_true"), ("||", "left_false")])
def test_short_circuit_only_evaluates_right_under_left_condition(tmp_path, operator, arm):
    facts = facts_for(tmp_path, {"Controller.java": f'''class Controller {{
  @PostMapping("/orders") boolean receive() {{ return first() {operator} second(); }}
  boolean first() {{ return true; }} boolean second() {{ return false; }}
}}'''})
    assert not facts["gaps"]
    branch = next(b for b in facts["branches"] if b["type"] == "short_circuit")
    second = next(c for c in facts["calls"] if c["details"]["method"] == "second")
    assert second["conditions"] == [branch["fact_id"], arm]
    assert any(s["kind"] == "control_else" and s["fact_id"] == branch["fact_id"] for s in facts["flow"])


def test_python_declarations_do_not_execute_callback_bodies(tmp_path):
    facts = facts_for(tmp_path, {"app.py": '''from fastapi import FastAPI
app = FastAPI()
# 接收订单
@app.post('/orders')
def receive():
    unused = lambda: missing_lambda()
    def helper():
        missing_local()
    return 1
'''})
    assert not facts["calls"]
    assert not facts["gaps"]
    assert all(p["evidence_refs"] for p in facts["participants"])


@pytest.mark.parametrize("statement,code", [
    ("await pending()", "ASYNC_SEMANTICS_UNSUPPORTED"),
    ("match values:\n        case [item]: return item", "CONTROL_SEMANTICS_UNSUPPORTED"),
    ("return (work(x) for x in values)", "LAZY_EXECUTION_UNSUPPORTED"),
])
def test_python_unmodeled_semantics_are_explicit_gaps(tmp_path, statement, code):
    facts = facts_for(tmp_path, {"app.py": f'''from fastapi import FastAPI
app = FastAPI()
# 接收订单
@app.post('/orders')
async def receive():
    {statement}
'''})
    assert any(g["code"] == code for g in facts["gaps"])
    assert not facts["coverage"]["complete"]


def test_python_keyword_argument_effect_is_not_skipped(tmp_path):
    facts = facts_for(tmp_path, {"app.py": '''from fastapi import FastAPI
app = FastAPI()
def work(): return 1
def save(value): return value
# 接收订单
@app.post('/orders')
def receive():
    return save(value=work())
'''})
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == ["work", "save"]


def test_python_shadowed_builtin_is_not_classified_as_pure(tmp_path):
    facts = facts_for(tmp_path, {"app.py": '''from fastapi import FastAPI
from unknown import sorted
app = FastAPI()
# 接收订单
@app.post('/orders')
def receive(): return sorted([])
'''})
    assert facts["gaps"]
    assert all(c["type"] != "pure_or_memory" for c in facts["calls"])


def test_executor_continuation_and_entry_completion_require_acceptance(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''import java.util.concurrent.ExecutorService;
class Controller { ExecutorService executor;
  @PostMapping("/orders") void receive() { executor.submit(() -> work()); after(); }
  void work() {} void after() {}
}'''})
    assert {g["code"] for g in facts["gaps"]} == {"EXECUTOR_SCHEDULING_UNRESOLVED"}
    decision = next(b for b in facts["branches"] if b["type"] == "task_submission_result")
    after = next(c for c in facts["calls"] if c["details"]["method"] == "after")
    completion = next(o for o in facts["outcomes"] if o["type"] == "normal_completion")
    for fact in (after, completion):
        assert decision["fact_id"] in fact["conditions"] and "accepted" in fact["conditions"]
    from test_sequence_renderer import analysis
    from toolkit.biz_flow_doc_generator.documents import render_entry
    rendered = render_entry(facts, analysis(facts))
    lines = rendered.splitlines()
    for fact in (after, completion):
        step = next(s for s in facts["flow"] if s["fact_id"] == fact["fact_id"])
        index = next(i for i, line in enumerate(lines) if step["step_id"] in line)
        assert any(line.startswith("opt ") and "任务已提交" in line for line in lines[index:index + 4])


def test_executor_interface_does_not_prove_deferred_execution(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''import java.util.concurrent.Executor;
class Controller { Executor executor;
  @PostMapping("/orders") void receive() { executor.execute(() -> work()); }
  void work() {}
}'''})
    assert any(g["code"] == "EXECUTOR_SCHEDULING_UNRESOLVED" for g in facts["gaps"])
    assert not facts["coverage"]["complete"]


def test_constructor_arguments_execute_before_constructor_body(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { Task task = new Task(input()); }
  String input() { return "order"; }
}
class Task { Task(String value) { initialize(); } void initialize() {} }
'''})
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == ["input", "Task", "initialize"]


def test_unresolved_constructor_and_initializer_are_not_silent(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task("order"); }
}
class Task { String value = load(); Task(long value) {} String load() { return "x"; } }
'''})
    assert any(g["code"] == "CONSTRUCTOR_BINDING_UNRESOLVED" for g in facts["gaps"])


def test_inherited_template_dispatches_override_on_actual_receiver(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Base {
  void template() { hook(); }
  void hook() { missing(); }
}
class Controller extends Base {
  @PostMapping("/orders") void receive() { template(); }
  void hook() { save(); } void save() {}
}'''})
    assert not facts["gaps"]
    assert [c["details"]["target"] for c in facts["calls"]] == [
        "Base.template()", "Controller.hook()", "Controller.save()"]
    assert facts["calls"][0]["details"]["receiver_type"] == "Controller"
    assert facts["calls"][0]["details"]["target_owner"] == "Base"


def test_receiver_construction_runs_before_argument_and_invocation(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task().accept(input()); }
  String input() { return "order"; }
}
class Task { Task() { initialize(); } void initialize() {} void accept(String value) {} }
'''})
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == [
        "Task", "initialize", "input", "accept"]


def test_local_constructor_chain_runs_parent_then_initializers_once(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task(input()); }
  int input() { return 1; }
}
class Base { int base = baseValue(); Base(int x) { baseBody(); }
  int baseValue() { return 1; } void baseBody() {}
}
class Task extends Base {
  int value = initialValue(); { initialize(); }
  Task(int value) { this(value, true); outerBody(); }
  Task(int value, boolean enabled) { super(value); innerBody(); }
  int initialValue() { return 2; }
  void initialize() {} void innerBody() {} void outerBody() {}
}'''})
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == [
        "input", "Task", "Task", "Base", "baseValue", "baseBody",
        "initialValue", "initialize", "innerBody", "outerBody"]
    initialized = [e["details"]["field"] for e in facts["effects"] if e["type"] == "memory_state_change"]
    assert initialized == ["base", "value"]


def test_implicit_constructor_includes_parent_and_instance_initializers(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task(); }
}
class Base { Base() { before(); } void before() {} }
class Task extends Base { { initialize(); } void initialize() {} }
'''})
    assert not facts["gaps"]
    assert [c["details"]["method"] for c in facts["calls"]] == ["Task", "Base", "before", "initialize"]


def test_unknown_parent_constructor_is_not_silent(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task(); }
}
class Task extends ExternalBase {}
'''})
    assert any(g["code"] == "CONSTRUCTOR_CONTRACT_UNSUPPORTED" for g in facts["gaps"])
    assert not facts["coverage"]["complete"]


@pytest.mark.parametrize("annotation", ["Data", "NoArgsConstructor", "Value"])
def test_lombok_generation_is_not_replaced_by_implicit_default_constructor(tmp_path, annotation):
    facts = facts_for(tmp_path, {"Controller.java": "import lombok." + annotation + ''';
class Controller { @PostMapping("/orders") void receive() { new Task(); } }
@''' + annotation + " class Task { String value; }"})
    assert any(g["code"] == "CONSTRUCTOR_BINDING_UNRESOLVED" for g in facts["gaps"])


def test_private_and_static_methods_keep_lexical_owner(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Base {
  void template() { privateHook(); staticHook(); }
  private void privateHook() {} static void staticHook() {}
}
class Controller extends Base {
  @PostMapping("/orders") void receive() { template(); }
  void privateHook() { missing(); } static void staticHook() { missing(); }
}'''})
    assert not facts["gaps"]
    assert [c["details"]["target"] for c in facts["calls"]] == [
        "Base.template()", "Base.privateHook()", "Base.staticHook()"]


def test_super_call_keeps_receiver_for_virtual_hook_inside_parent(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Base {
  void template() { hook(); } void hook() { missing(); }
}
class Controller extends Base {
  @PostMapping("/orders") void receive() { super.template(); }
  void template() { missing(); } void hook() {}
}'''})
    assert not facts["gaps"]
    assert [c["details"]["target"] for c in facts["calls"]] == ["Base.template()", "Controller.hook()"]
    assert facts["calls"][0]["details"]["receiver_type"] == "Controller"


def test_inherited_callback_keeps_actual_receiver(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Base {
  void template() { hook(); } void hook() { missing(); }
}
class Controller extends Base {
  @PostMapping("/orders") void receive() { execute(this::template); }
  void execute(Runnable action) { action.run(); } void hook() {}
}'''})
    assert not facts["gaps"]
    assert any(c["details"]["target"] == "Controller.hook()" for c in facts["calls"])


def test_private_callback_keeps_lexical_owner(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Base {
  void template() { execute(this::hook); } private void hook() {}
  void execute(Runnable action) { action.run(); }
}
class Controller extends Base {
  @PostMapping("/orders") void receive() { template(); }
  void hook() { missing(); }
}'''})
    assert not facts["gaps"]
    assert any(c["details"]["target"] == "Base.hook()" for c in facts["calls"])
    assert not any(c["details"]["target"] == "Controller.hook()" for c in facts["calls"])


@pytest.mark.parametrize("initializer", ["static { missing(); }", "static int value = missing();"])
def test_class_initialization_stays_blocked(tmp_path, initializer):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") void receive() { new Task(); }
}
class Task { ''' + initializer + " }"})
    assert any(g["code"] == "OBJECT_INITIALIZATION_UNSUPPORTED" for g in facts["gaps"])


@pytest.mark.parametrize("statement", [
    "work(); after();", "boolean value = work(); after();", "recorded = work(); after();",
    "new Task(work()); after();", "return work();", "if (work()) { after(); }",
    "while (work()) { after(); }", "execute(() -> work()); after();",
])
def test_proven_throw_stops_normal_continuation_but_keeps_catch_and_cleanup(tmp_path, statement):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller { boolean recorded;
  @PostMapping("/orders") boolean receive() {
    try { ''' + statement + ''' } catch (RuntimeException error) { recover(); }
    finally { cleanup(); }
    return false;
  }
  boolean work() { throw new IllegalArgumentException("failed"); }
  void after() { missing(); } void recover() {} void cleanup() {}
  void execute(Runnable action) { action.run(); }
}
class Task { Task(boolean value) { missing(); } }
'''})
    assert not facts["gaps"]
    names = [c["details"]["method"] for c in facts["calls"]]
    assert "after" not in names and "Task" not in names
    assert "recover" in names and "cleanup" in names
    assert not facts["effects"]
    assert [o["details"]["expression"] for o in facts["outcomes"] if o["type"] == "entry_response"] == ["return false;"]


def test_short_circuit_throw_cannot_claim_unguarded_success(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") boolean receive(boolean ready) {
    try { boolean value = ready && work(); } catch (RuntimeException error) {}
    return true;
  }
  boolean work() { throw new IllegalArgumentException("failed"); }
}'''})
    assert any(g["code"] == "CONTROL_EXIT_MERGE_UNSUPPORTED" for g in facts["gaps"])


def test_mixed_switch_exit_cannot_claim_unguarded_success(tmp_path):
    facts = facts_for(tmp_path, {"Controller.java": '''class Controller {
  @PostMapping("/orders") int receive(int value) {
    switch (value) { case 1: return 1; default: break; }
    return 2;
  }
}'''})
    assert any(g["code"] == "CONTROL_EXIT_MERGE_UNSUPPORTED" for g in facts["gaps"])


@pytest.mark.parametrize("annotation", ["Table", "Column"])
def test_custom_annotations_do_not_prove_jpa_resource(tmp_path, annotation):
    files = jpa_files()
    files["module/Controller.java"] = files["module/Controller.java"].replace(
        "import jakarta.persistence." + annotation + ";", "import custom." + annotation + ";")
    facts = facts_for(tmp_path, files)
    assert facts["gaps"] and not facts["persistence_actions"]


def jpa_files():
    return {"module/pom.xml": '''<project><dependencies><dependency>
<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa</artifactId><version>3.3.0</version>
</dependency></dependencies></project>''', "module/Controller.java": '''
import org.springframework.data.jpa.repository.JpaRepository;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.Column;
class Controller { Repo repository;
  @PostMapping("/orders") void receive(Order order) { repository.save(order); }
}
interface Repo extends JpaRepository<Order, Long> {}
@Entity @Table(name="order_record") class Order { @Column(name="order_id") Long id; }
'''}


def test_dependency_profile_uses_owning_module_not_unrelated_pom(tmp_path):
    files = jpa_files()
    files["other/pom.xml"] = files["module/pom.xml"].replace("3.3.0", "0.0.1")
    facts = facts_for(tmp_path, files)
    assert not facts["gaps"]
    assert not any(s["file"].startswith("other/") for s in facts["sources"])


def test_dependency_profile_resolves_local_parent_management_and_properties(tmp_path):
    files = jpa_files()
    files["pom.xml"] = '''<project><groupId>demo</groupId><artifactId>parent</artifactId><version>1</version>
<properties><jpa.version>3.3.0</jpa.version></properties><dependencyManagement><dependencies><dependency>
<groupId>org.springframework.data</groupId><artifactId>spring-data-jpa</artifactId><version>${jpa.version}</version>
</dependency></dependencies></dependencyManagement></project>'''
    files["module/pom.xml"] = '''<project><parent><groupId>demo</groupId><artifactId>parent</artifactId>
<version>1</version></parent><dependencies><dependency><groupId>org.springframework.data</groupId>
<artifactId>spring-data-jpa</artifactId></dependency></dependencies></project>'''
    facts = facts_for(tmp_path, files)
    assert not facts["gaps"]
    assert {"pom.xml", "module/pom.xml"} <= {s["file"] for s in facts["sources"]}


def test_unresolved_parent_cannot_prove_effective_dependency_profile(tmp_path):
    files = jpa_files()
    files["module/pom.xml"] = files["module/pom.xml"].replace("<project>", """<project><parent>
<groupId>external</groupId><artifactId>parent</artifactId><version>1</version>
<relativePath/></parent>""")
    facts = facts_for(tmp_path, files)
    assert any(g["code"] == "LIBRARY_CONTRACT_VERSION_UNSUPPORTED" for g in facts["gaps"])
    assert not facts["persistence_actions"]


def test_version_lock_edit_during_task_is_rejected(prepared, monkeypatch):
    from toolkit.biz_flow_doc_generator import cli, host
    from test_native_handoff import fixture_submission
    root, path, manifest = prepared
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    lock = root / "docs/biz-flow/biz-flow-doc-generator-version.json"
    value = json.loads(lock.read_text(encoding="utf-8"))
    value["source"]["git_commit"] = manifest["source_commit"]
    lock.write_text(json.dumps(value), encoding="utf-8")
    submission = path.parent / "submission.json"
    submission.write_text(json.dumps(fixture_submission(manifest)), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in lock.parent.glob("*.md")}
    assert cli.collect_command(["--project", str(root), "--run-id", manifest["run_id"], "--results", str(submission)]) == 8
    assert {p.name: p.read_bytes() for p in lock.parent.glob("*.md")} == before


def test_non_markdown_user_asset_inside_docs_is_read_only(prepared, monkeypatch):
    from toolkit.biz_flow_doc_generator import cli, host
    from test_native_handoff import fixture_submission
    root, path, manifest = prepared
    monkeypatch.setattr(cli, "validate_execution", lambda m, p: host.validate_execution(m, p, allow_fixture=True))
    user_asset = root / "docs/biz-flow/notes/data.json"
    user_asset.parent.mkdir()
    user_asset.write_text('{"changed": true}', encoding="utf-8")
    submission = path.parent / "submission.json"
    submission.write_text(json.dumps(fixture_submission(manifest)), encoding="utf-8")
    assert cli.collect_command(["--project", str(root), "--run-id", manifest["run_id"], "--results", str(submission)]) == 8


from test_native_handoff import prepared  # shared committed-project fixture
