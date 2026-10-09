from pathlib import Path
from dataclasses import replace

import pytest

from toolkit.sequence_diagram_generator.adapters.registry import AdapterRegistry
from toolkit.sequence_diagram_generator.models import AnalysisScope, SourceFile, SourceSnapshot
from toolkit.sequence_diagram_generator.repository import bytes_digest, digest


FIXTURES = {
    "python": ("app.py", "def helper():\n    print('saved')\ndef flow(x):\n    if x:\n        helper()\n    else:\n        return False\n    helper()\n    return True\n"),
    "java": ("App.java", "class App { static void helper() { System.out.println(1); } static boolean flow(boolean x) { if(x) { helper(); } else { return false; } helper(); return true; } }"),
    "javascript": ("app.js", "function helper(){console.log(1)} function flow(x){if(x){helper()}else{return false}helper();return true}"),
    "typescript": ("app.ts", "function helper():void{console.log(1)} function flow(x:boolean):boolean{if(x){helper()}else{return false}helper();return true}"),
    "go": ("app.go", "package main\nfunc helper() { println(1) }\nfunc flow(x bool) bool { if x { helper() } else { return false }; helper(); return true }"),
    "rust": ("app.rs", "fn helper()->i32 { 1 } fn flow(x:bool)->bool { if x { helper(); } else { return false; } helper(); true }"),
}


def snapshot(language, name, source):
    raw = source.encode()
    return SourceSnapshot((SourceFile(name, bytes_digest(raw), language, len(raw)),), digest(raw.decode()), "", False, "", ((name, raw),))


@pytest.mark.parametrize("language", FIXTURES)
def test_actual_syntax_calls_branches_and_distinct_contexts(language):
    name, source = FIXTURES[language]
    source_snapshot = snapshot(language, name, source)
    adapter = AdapterRegistry().get(language)
    symbols = adapter.discover(source_snapshot)
    entry = next(symbol for symbol in symbols if symbol.qualified_name.endswith((".flow", "::flow")))
    result = adapter.analyze(source_snapshot, AnalysisScope(entry, entry.symbol_id))
    assert result.controls, result
    assert len(result.controls[0].exit_ids) == 2
    assert len({context.context_id for context in result.contexts}) >= 3, result
    assert not result.gaps, result.gaps
    assert any(step.kind == "return" and "false" in step.label.lower() for step in result.steps), result.steps


def test_python_ids_ignore_blank_lines_and_comments():
    name, code = FIXTURES["python"]
    adapter = AdapterRegistry().get("python")
    def analyze(source):
        source_snapshot = snapshot("python", name, source)
        entry = next(symbol for symbol in adapter.discover(source_snapshot) if symbol.qualified_name.endswith(".flow"))
        return adapter.analyze(source_snapshot, AnalysisScope(entry, entry.symbol_id))
    before, after = analyze(code), analyze("# comment\n\n" + code.replace("\n    helper()", "\n    # comment\n    helper()"))
    assert [item.step_id for item in before.steps] == [item.step_id for item in after.steps]
