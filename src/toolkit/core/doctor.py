"""Installation diagnostics for the shared runtime."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from typing import Any


def diagnose() -> tuple[dict[str, Any], bool]:
    checks = {
        "python": {"ok": sys.version_info >= (3, 11), "value": sys.version.split()[0], "required": ">=3.11"},
        "PyYAML": {"ok": importlib.util.find_spec("yaml") is not None},
        "pytest": {"ok": importlib.util.find_spec("pytest") is not None},
        "git": {"ok": shutil.which("git") is not None},
        "bruno": {"ok": shutil.which("bru") is not None, "required_for": "bru-api.run"},
    }
    required = ("python", "PyYAML", "pytest", "git")
    import ast
    from ..sequence_diagram_generator.adapters._tree import parser_for
    fixtures = {
        "java": b"class A { int f(){ return 1; } }",
        "javascript": b"function f(){ return 1; }",
        "typescript": b"function f(x:number):number { return x; }",
        "go": b"package main\nfunc f() int { return 1 }",
        "rust": b"fn f()->i32 { 1 }",
    }
    try:
        ast.parse("async def f(x):\n    if x:\n        return x\n")
        checks["sequence.python"] = {"ok": True, "required_for": "sequence-diagram-generator"}
    except SyntaxError:
        checks["sequence.python"] = {"ok": False, "required_for": "sequence-diagram-generator"}
    for language, source in fixtures.items():
        try:
            root = parser_for(language).parse(source).root_node
            checks[f"sequence.{language}"] = {"ok": not root.has_error, "required_for": "sequence-diagram-generator"}
        except Exception as exc:
            checks[f"sequence.{language}"] = {"ok": False, "required_for": "sequence-diagram-generator", "diagnostic": str(exc)}
    checks["mermaid"] = {"ok": shutil.which("mmdc") is not None, "required_for": "sequence-diagram-generator.render"}
    checks["feishu"] = {"ok": shutil.which("lark-cli") is not None, "required_for": "sequence-diagram-generator.publish (host authentication and double export also required)"}
    return {"checks": checks}, all(checks[name]["ok"] for name in required)
