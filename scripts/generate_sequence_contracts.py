"""Explicit developer command: regenerate static sequence domain schemas.

The runtime imports only the generated core JSON, never domain model discovery.
"""
from __future__ import annotations

import json
import re
import sys
import types
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from toolkit.sequence_diagram_generator import models


def scope(name):
    return "sequence-diagram-generator." + re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def field_schema(kind):
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, types.UnionType):
        return {"anyOf": [field_schema(item) for item in args]}
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": field_schema(args[0])}
        return {"type": "array", "prefixItems": [field_schema(item) for item in args],
                "minItems": len(args), "maxItems": len(args)}
    if is_dataclass(kind):
        return {"$ref": scope(kind.__name__)}
    if isinstance(kind, type) and issubclass(kind, Enum):
        return {"type": "string", "enum": [item.value for item in kind]}
    return {"type": {str: "string", Path: "string", int: "integer", bool: "boolean",
                     float: "number", type(None): "null"}[kind]} if kind is not object else {}


def main():
    contracts = {}
    for name, kind in vars(models).items():
        if not isinstance(kind, type) or not is_dataclass(kind):
            continue
        hints = get_type_hints(kind)
        properties = {f.name: field_schema(hints[f.name]) for f in fields(kind)
                      if not (name == "SourceSnapshot" and f.name == "contents")}
        for field in ("run_id", "accepted_run_id"):
            if field in properties:
                properties[field]["pattern"] = r"^[0-9a-f]{32}$" if field == "run_id" else r"^(|[0-9a-f]{32})$"
        if name == "RunManifest":
            properties["schema_version"] = {"const": 2}
            properties.pop("mode", None)
            properties["intent"]["enum"] = ["implementation", "proposal", "description"]
            properties["execution_mode"]["enum"] = ["", "native", "serial"]
        if name == "Requirement":
            properties["status"]["enum"] = ["implemented", "partially_implemented", "requirement_only", "conflict", "unresolved", "not_applicable"]
            properties["implementation_assessment"]["enum"] = ["checked", "checked_not_found", "not_evaluated"]
        if name == "ExternalOperation":
            properties["resolution"]["enum"] = ["project", "boundary", "summary", "unknown"]
        if name == "SequenceBlock":
            properties["kind"]["enum"] = ["sequence", "alt", "opt", "loop", "par"]
        if name == "RenderReport":
            properties["status"]["enum"] = ["passed", "not_run", "failed"]
        contracts[scope(name)] = {"contract": scope(name), "schema_version": "2",
            "document": {"type": "object", "properties": properties,
                         "required": list(properties), "additionalProperties": False}}
    path = ROOT / "src" / "toolkit" / "core" / "sequence-contracts.json"
    path.write_text(json.dumps(contracts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
