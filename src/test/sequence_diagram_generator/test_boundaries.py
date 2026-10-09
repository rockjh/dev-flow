"""Behavioral boundaries: binding evidence and honest uncertainty."""
from dataclasses import replace
import json

import pytest

from toolkit.sequence_diagram_generator.adapters.registry import AdapterRegistry
from toolkit.sequence_diagram_generator.models import AnalysisScope, SourceFile, SourceSnapshot
from toolkit.sequence_diagram_generator.repository import bytes_digest, digest
from test_adapters import snapshot


def analyze(language, source, suffix="flow"):
    name = {"python": "app.py", "java": "App.java", "javascript": "app.js", "typescript": "app.ts", "go": "app.go", "rust": "app.rs"}[language]
    facts = snapshot(language, name, source)
    adapter = AdapterRegistry().get(language)
    entry = next(s for s in adapter.discover(facts) if s.qualified_name.endswith(suffix))
    return adapter.analyze(facts, AnalysisScope(entry, entry.symbol_id))


def test_nested_early_return_does_not_terminate_caller():
    result = analyze("python", "def eligible(x):\n if x: return True\n return False\ndef flow(x):\n if eligible(x): return True\n return False\n")
    assert not result.gaps, result.gaps
    assert len([s for s in result.steps if s.kind == "call_return"]) == 1
    assert len([s for s in result.steps if s.kind == "return"]) == 4


def test_throwing_callee_does_not_claim_successful_return():
    result = analyze("python", "def fail():\n raise ValueError('bad')\ndef flow():\n fail()\n print('success')\n")
    assert any(g.reason_code == "CALL_EXCEPTION_PROPAGATION" and g.critical for g in result.gaps)
    assert not any(s.kind == "call_return" and s.receiver.endswith("fail") for s in result.steps)


def test_go_http_alias_requires_actual_import():
    code = 'package main\nimport web "net/http"\nfunc handler() {}\nfunc register(){ web.HandleFunc("/", handler) }'
    adapter = AdapterRegistry().get("go")
    symbols = adapter.discover(snapshot("go", "app.go", code))
    assert next(s for s in symbols if s.qualified_name.endswith("handler")).selection_type == "registered"
    symbols = adapter.discover(snapshot("go", "app.go", code.replace('"net/http"', '"other/http"')))
    assert next(s for s in symbols if s.qualified_name.endswith("handler")).selection_type == "symbol"


def test_typescript_direct_paths_bind_project_not_dependency():
    contents = (("src/app.ts", b'import {helper} from "@lib/helper"; function flow(){helper()}'),
                ("src/lib/helper.ts", b'export function helper(){console.log(1)}'),
                ("tsconfig.json", json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@lib/*": ["src/lib/*"]}}}).encode()))
    facts = SourceSnapshot(tuple(SourceFile(p, bytes_digest(raw), "typescript" if p.endswith(".ts") else "config", len(raw)) for p, raw in contents), digest(tuple((p, bytes_digest(raw)) for p, raw in contents)), "", False, "", contents)
    adapter = AdapterRegistry().get("typescript")
    entry = next(s for s in adapter.discover(facts) if s.qualified_name.endswith("flow"))
    result = adapter.analyze(facts, AnalysisScope(entry, entry.symbol_id))
    assert not result.gaps, result.gaps
    assert any(o.resolution == "project" and o.receiver.endswith("helper") for o in result.external)


@pytest.mark.parametrize("language,path", [("javascript", "app.js"), ("typescript", "app.ts")])
def test_same_stem_js_ts_calls_bind_their_own_file(language, path):
    contents = (("app.js", b"function helper(){console.log('js')} function flow(){helper()}"),
                ("app.ts", b"function helper():void{console.log('ts')} function flow():void{helper()}"))
    facts = SourceSnapshot(tuple(SourceFile(p, bytes_digest(raw), "javascript" if p.endswith(".js") else "typescript", len(raw)) for p, raw in contents),
                           digest(tuple((p, bytes_digest(raw)) for p, raw in contents)), "", False, "", contents)
    adapter = AdapterRegistry().get(language)
    entry = next(s for s in adapter.discover(facts) if s.path == path and s.qualified_name.endswith("flow"))
    result = adapter.analyze(facts, AnalysisScope(entry, entry.symbol_id))
    assert not result.gaps, result.gaps
    assert all(s.path == path for s in result.symbols)
    assert any(o.resolution == "project" and o.receiver.endswith("helper") for o in result.external)


@pytest.mark.parametrize("language,source,reason", [
    ("python", "def flow():\n return getattr(object(), 'save')()\n", "DYNAMIC_PYTHON"),
    ("javascript", "function flow(){setTimeout(()=>console.log(1), 1)}", "JS_ASYNC_DEPENDENCIES"),
    ("go", "package main\nfunc flow(){go work()}\nfunc work(){}", "GO_GOROUTINE_COMPLETION"),
    ("rust", "fn flow(){ unknown!(); }", "RUST_UNEXPANDED_MACRO"),
])
def test_uncertain_runtime_semantics_are_critical(language, source, reason):
    result = analyze(language, source)
    assert any(g.reason_code == reason and g.critical for g in result.gaps)


def test_axum_direct_routing_reference():
    code = 'use axum::routing::get; fn handler(){} fn register(){ router.route("/", get(handler)); }'
    adapter = AdapterRegistry().get("rust")
    symbols = adapter.discover(snapshot("rust", "app.rs", code))
    assert next(s for s in symbols if s.qualified_name.endswith("handler")).selection_type == "registered"


def test_anonymous_registered_callback_ids_do_not_use_line_numbers():
    source = "import express from 'express'; const app=express(); app.get('/ready',function(){return true});"
    adapter = AdapterRegistry().get("javascript")
    before = adapter.discover(snapshot("javascript", "app.js", source))
    after = adapter.discover(snapshot("javascript", "app.js", "// comment\n\n" + source))
    assert {s.symbol_id for s in before} == {s.symbol_id for s in after}


@pytest.mark.parametrize("language,source", [
    ("java", "class App { static void tick() {} static void work() {} static void flow(){ for(int i=0; i<3; tick()){work();} } }"),
    ("javascript", "function tick(){} function work(){} function flow(){for(let i=0;i<3;tick()){work()}}"),
])
def test_iteration_update_calls_stay_inside_loop(language, source):
    result = analyze(language, source)
    from toolkit.sequence_diagram_generator.models import SequenceBlock, SequenceStep
    loop = next(item for item in result.sequence.arms[0].items if isinstance(item, SequenceBlock) and item.kind == "loop")
    iteration_ids = {item.step_id for item in loop.arms[0].items if isinstance(item, SequenceStep)}
    tick = next(step for step in result.steps if step.kind == "call" and step.label == "tick")
    work = next(step for step in result.steps if step.kind == "call" and step.label == "work")
    assert tick.step_id in iteration_ids and work.step_id in iteration_ids
    ids = [item.step_id for item in loop.arms[0].items if isinstance(item, SequenceStep)]
    assert ids.index(work.step_id) < ids.index(tick.step_id)
