"""Real syntax fixtures for cleanup, errors and registration mechanisms."""
import pytest

from toolkit.sequence_diagram_generator.adapters.registry import AdapterRegistry
from test_adapters import snapshot
from test_boundaries import analyze


def test_python_comprehension_filter_and_match_guard_are_control_points():
    result = analyze("python", "def flow(items):\n values = [x for x in items if x > 0]\n match values:\n  case [x] if x > 1: return True\n  case _: return False\n")
    assert any(c.kind == "loop" for c in result.controls)
    assert len([c for c in result.controls if c.kind == "alt"]) >= 2
    assert all(len(c.exit_ids) >= 2 for c in result.controls)


def test_python_finally_cleanup_is_before_return_with_exception_boundary():
    result = analyze("python", "def flow():\n try:\n  return 1\n finally:\n  print('cleanup')\n")
    call = next(i for i, step in enumerate(result.steps) if step.kind == "call" and step.label == "print")
    returned = next(i for i, step in enumerate(result.steps) if step.kind == "return")
    assert call < returned
    assert result.gaps  # Interrupted exception prefixes remain an explicit capability boundary.


def test_go_deferred_arguments_evaluate_now_calls_run_reverse_on_return():
    result = analyze("go", "package main\nfunc first(x int) {}\nfunc second() {}\nfunc argument() int { return 1 }\nfunc flow(){defer first(argument()); defer second(); return}")
    calls = [step.label for step in result.steps if step.kind == "call"]
    assert calls == ["argument", "second", "first"]
    assert not result.gaps, result.gaps


def test_rust_question_mark_has_error_early_exit():
    result = analyze("rust", "fn work()->Result<i32,i32>{Ok(1)} fn flow()->Result<i32,i32>{let value=work()?; Ok(value)}")
    assert any(c.condition == "Result ?" and len(c.exit_ids) == 2 for c in result.controls)
    assert any(s.kind == "return" and "propagate Err" in s.label for s in result.steps)


def test_java_overloads_remain_distinct_complete_signatures():
    adapter = AdapterRegistry().get("java")
    symbols = adapter.discover(snapshot("java", "App.java", "class App { void save(int x){} void save(String x){} }"))
    assert len(symbols) == 2 and symbols[0].symbol_id != symbols[1].symbol_id
    assert {s.signature for s in symbols} == {"(int):void", "(String):void"}


def test_java_varargs_and_post_name_array_signature():
    adapter = AdapterRegistry().get("java")
    symbols = adapter.discover(snapshot("java", "App.java", "class App { void flow(String... names, int values[]){} }"))
    assert symbols[0].signature == "(String...,int[]):void"


def test_rust_use_alias_binds_local_name_not_intermediate_path_component():
    result = analyze("rust", "use library::store::save as persist; fn flow(){persist(); store::save();}")
    assert next(o for o in result.external if o.receiver == "persist").resolution == "boundary"
    assert next(o for o in result.external if o.receiver == "store::save").resolution == "unknown"


def test_python_sqlite_statement_and_transaction_are_separate_persistence_facts():
    result = analyze("python", "import sqlite3\ndef flow():\n db=sqlite3.connect('example.db')\n db.execute('INSERT INTO orders VALUES (?)', (1,))\n db.commit()\n")
    assert not result.gaps, result.gaps
    persistence = [o for o in result.external if o.operation_id.startswith("P-")]
    assert len(persistence) == 2
    assert "separate from transaction commit" in persistence[0].side_effect
    assert "transaction commit issued" in persistence[1].side_effect
    order = [s.step_id for s in result.steps]
    assert order.index(persistence[0].call_site_id) < order.index(persistence[1].call_site_id)


def test_python_rebound_callable_and_shadowed_parameter_are_unknown():
    result = analyze("python", "def save(): return True\ndef flow(save):\n return save()\n")
    assert any(o.resolution == "unknown" for o in result.external)
    result = analyze("python", "def save(): return True\ndef flow(injected):\n save=injected\n return save()\n")
    assert any(o.resolution == "unknown" for o in result.external)


@pytest.mark.parametrize("source", [
    "def flow(*print):\n print()\n",
    "def flow(**print):\n print()\n",
    "def flow():\n print('before assignment')\n print=1\n",
    "def factory():\n def save(): return True\n return save\ndef flow():\n obj=factory()\n obj.save()\n",
    "import sqlite3\ndef flow(flag):\n if flag: db=sqlite3.connect('a.db')\n db.commit()\n",
    "import sqlite3\ndef flow(flag):\n if flag: db=sqlite3.connect('a.db')\n else: db.commit()\n",
    "import sqlite3\ndef flow(flag):\n while flag: db=sqlite3.connect('a.db')\n db.commit()\n",
    "def save(): return True\ndef flow(self):\n self.save()\n",
])
def test_python_unproved_receiver_or_lexical_shadow_is_critical(source):
    result = analyze("python", source)
    assert any(o.resolution == "unknown" for o in result.external)
    assert any(g.critical and g.reason_code == "UNKNOWN_CALL_TARGET" for g in result.gaps)


def test_python_agreeing_branch_bindings_preserve_sqlite_contract():
    result = analyze("python", "import sqlite3\ndef flow(flag):\n if flag: db=sqlite3.connect('a.db')\n else: db=sqlite3.connect('b.db')\n db.commit()\n")
    assert not result.gaps, result.gaps
    assert any(o.operation_id.startswith("P-") and "transaction commit" in o.side_effect for o in result.external)


def test_java_executor_future_observation_is_bound_to_dispatch():
    source = """import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.Callable;
class App { static void flow(ExecutorService executor, Callable<String> task) {
 Future<String> future = executor.submit(task);
 future.get();
} }"""
    result = analyze("java", source)
    assert not result.gaps, result.gaps
    dispatched = next(step for step in result.steps if step.kind == "dispatch")
    waited = next(step for step in result.steps if step.kind == "wait")
    assert waited.dependencies == (dispatched.step_id,)
    from toolkit.sequence_diagram_generator.models import FlowModel
    from toolkit.sequence_diagram_generator.validation import FlowValidator
    assert FlowValidator().validate_model(FlowModel((result,), "", "")).passed
    result = analyze("java", source.replace("future.get();", ""))
    assert any(g.reason_code == "JAVA_ASYNC_COMPLETION" for g in result.gaps)


def test_java_same_receiver_name_in_another_method_does_not_bind():
    source = "import api.Store; class App { void other(Store store){} void flow(){store.save();} }"
    result = analyze("java", source)
    assert any(o.resolution == "unknown" for o in result.external)


def test_java_imported_arbitrary_get_is_not_async_completion():
    result = analyze("java", "import api.Store; class App { void flow(Store store){store.get();} }")
    assert not any(step.kind == "wait" for step in result.steps)


def test_java_registered_method_does_not_hide_second_unknown_annotation():
    result = analyze("java", 'import org.springframework.web.bind.annotation.GetMapping; class App { @GetMapping("/") @Unknown boolean flow(){return true;} }')
    assert any(g.reason_code == "UNKNOWN_JAVA_ANNOTATION" and g.basis == "Unknown" for g in result.gaps)
    assert not any(g.basis == "GetMapping" for g in result.gaps)


def test_javascript_project_async_call_requires_actual_await():
    result = analyze("javascript", "async function work(){return 1} async function flow(){return await work()}")
    assert any(s.kind == "await" for s in result.steps)
    assert not result.gaps, result.gaps
    result = analyze("javascript", "async function work(){return 1} function flow(){work()}")
    assert any(g.reason_code == "JS_ASYNC_COMPLETION" for g in result.gaps)


@pytest.mark.parametrize("language", ["javascript", "typescript"])
def test_node_event_listener_runs_after_emit_before_emit_return(language):
    result = analyze(language, "import {EventEmitter} from 'node:events'; function listener(){console.log('handled')} function flow(){const bus=new EventEmitter(); bus.on('ready',listener); bus.emit('ready');}")
    assert not result.gaps, result.gaps
    labels = [s.label for s in result.steps]
    emit = labels.index("bus.emit")
    invoked = labels.index("listener 'ready'")
    log = labels.index("console.log")
    done = labels.index("EventEmitter.emit returned after synchronous listeners")
    assert emit < invoked < log < done


def test_async_event_listener_never_claims_observed_completion():
    result = analyze("javascript", "import {EventEmitter} from 'node:events'; async function listener(){console.log('handled')} function flow(){const bus=new EventEmitter();bus.on('ready',listener);bus.emit('ready');}")
    assert any(g.reason_code == "JS_EVENT_COMPLETION" and g.critical for g in result.gaps)
    assert not any(s.label == "EventEmitter.emit returned after synchronous listeners" for s in result.steps)


@pytest.mark.parametrize("language,name,code,qualified", [
    ("python", "app.py", "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/ready')\ndef ready(): return True\n", ".ready"),
    ("java", "App.java", "import org.springframework.web.bind.annotation.GetMapping; class App { @GetMapping(\"/ready\") boolean ready(){return true;} }", ".ready"),
    ("javascript", "app.js", "import express from 'express'; const app=express(); function ready(){return true} app.get('/ready',ready);", ".ready"),
    ("typescript", "app.ts", "import express from 'express'; const app=express(); function ready():boolean{return true} app.get('/ready',ready);", ".ready"),
])
def test_import_bound_framework_registration(language, name, code, qualified):
    symbols = AdapterRegistry().get(language).discover(snapshot(language, name, code))
    entry = next(s for s in symbols if s.qualified_name.endswith(qualified))
    assert entry.selection_type == "registered" and entry.registration_evidence
