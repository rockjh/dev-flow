"""Scoped public command and domain contracts; no runtime plugin discovery."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


BRU_API_SCHEMA_VERSION = "6.2"
BIZ_FLOW_SCHEMA_VERSION = "4"
E2E_GATE_SCHEMA_VERSION = "10"
E2E_RUNTIME_CLASSIFICATIONS = (
    "protocol_available",
    "service_not_found",
    "protocol_unknown",
    "incomplete_protocol",
    "authentication_missing",
    "read_only_failed",
    "environment_invalid",
)
E2E_RULE_STATUSES = (
    "confirmed",
    "manual_confirmation",
    "conflict",
    "not_applicable",
    "missing_evidence",
)

E2E_SCENARIO_STATUSES = ("ready", "pending_environment", "contract_blocked")
E2E_GENERATION_MODES = ("delegated", "main_agent", "sequential_degraded")
E2E_CONTROL_NAMES = (
    "public_api",
    "test_or_admin_api",
    "mocks_and_faults",
    "dynamic_configuration",
    "scheduled_jobs",
    "messages",
    "database_read",
    "database_control",
    "observability",
)
E2E_CONTROL_STATUSES = ("usable", "unusable", "not_found", "not_applicable")
E2E_CANDIDATE_STATUSES = ("usable", "unusable", "not_found")
E2E_STEP_STATUSES = (
    "executable",
    "environment_missing",
    "authorization_missing",
    "control_gap",
    "product_gap",
    "runtime_failure",
)
E2E_CANDIDATE_KINDS = (
    "public_api",
    "test_or_admin_api",
    "database_control",
    "messages",
    "scheduled_jobs",
    "mocks_and_faults",
    "dynamic_configuration",
    "existing_test_data",
    "database_read",
    "observability",
)
E2E_ORDERED_GATES = (
    "workspace_inventory",
    "dependency_topology",
    "initial_configuration",
    "runtime_probe",
    "control_matrix",
    "scenario_split",
    "scenario_ownership",
    "shared_integration",
)
E2E_ORDERED_GATE_SEQUENCE = (*E2E_ORDERED_GATES, "static")
E2E_RUN_STAGES = (
    *E2E_ORDERED_GATES,
    "static",
    "environment_tests",
    "source_versions",
    "collect",
    "read_only_smoke",
    "business",
    "restoration",
    "summary",
)


COMMAND_SCHEMAS: dict[str, dict[str, Any]] = {
    "bru-api.init": {
        "options": {"--qa-root": "path"}
    },
    "bru-api.understand": {
        "options": {
            "--qa-root": "path", "--openapi": "path",
        }
    },
    "bru-api.generate": {
        "options": {
            "--qa-root": "path",
            "--openapi": "path",
            "--module-map": "path",
            "--incremental": "boolean",
            "--no-seed-cases": "boolean",
            "--source-root": "path[]",
            "--coverage-profile": ["contract-draft", "full-matrix"],
            "--base-url": "loopback-url[]",
            "--port": "integer[]",
            "--path": "string[]",
            "--timeout": "number",
        }
    },
    "bru-api.materialize": {
        "options": {"--qa-root": "path", "--module": "string", "--check": "boolean"}
    },
    "bru-api.check": {
        "options": {
            "--qa-root": "path",
            "--all": "boolean",
            "--module": "string",
            "--results": "path",
            "--preflight-results": "path",
            "--write-status": "boolean",
        },
        "one_of": ["--all", "--module"],
    },
    "bru-api.preflight": {
        "options": {
            "--qa-root": "path",
            "--public-path": "string",
            "--public-method": "string",
            "--public-status": "http-status-range",
            "--require-public-route": "boolean",
            "--admin-path": "string",
            "--admin-method": "string",
            "--admin-status": "http-status-range",
            "--admin-code": "string",
            "--require-admin-baseline": "boolean",
            "--openapi": "path",
            "--expected-openapi-sha256": "sha256",
            "--execution-config": "path",
            "--env-file": "path",
            "--require-env": "string[]",
            "--fixture": "path[]",
            "--timeout": "number",
            "--bruno-cli": "path-or-command",
            "--cli-timeout": "number",
        }
    },
    "bru-api.run": {
        "options": {
            "--qa-root": "path",
            "--module": "string",
            "--bruno-cli": "path-or-command",
            "--cli-timeout": "number",
            "--write-mock-data": "boolean",
            "--clean-mock-data": "boolean",
        }
    },
    "bru-api.mock-data-generate": {
        "options": {
            "--qa-root": "path", "--module": "string[]", "--run-id": "string", "--allow-write": "boolean",
        }
    },
    "bru-api.mock-data-clean": {
        "options": {
            "--qa-root": "path", "--module": "string[]", "--run-id": "string", "--allow-cleanup": "boolean",
        }
    },
    "bru-api.reconcile": {
        "options": {
            "--qa-root": "path",
            "--all": "boolean",
            "--module": "string",
            "--results": "path",
            "--preflight-results": "path",
            "--write-status": "boolean",
        },
        "one_of": ["--all", "--module"],
        "required": ["--results", "--preflight-results"],
    },
    "bru-api.worker-start": {"options": {"--qa-root": "path", "--module": "string"}, "required": ["--module"]},
    "bru-api.worker-check": {
        "options": {
            "--qa-root": "path",
            "--module": "string",
            "--stage": ["generation", "materialization", "pre-execution", "post-execution"],
        },
        "required": ["--module"],
    },
    "bru-api.scripts": {
        "arguments": {"action": ["status", "version-init", "version-check", "version-complete"]},
        "options": {
            "--qa-root": "path",
            "--business-repo": "path",
            "--phase": ["before-generate", "before-execute"],
            "--completion-report": "path",
            "--tests-adapted": "boolean",
            "--rules": "path",
        },
    },
    "e2e.init": {
        "options": {
            "--project": "path", "--design-root": "path[]", "--design-file": "path[]",
            "--openapi-root": "path[]", "--openapi-file": "path[]", "--runtime-url": "url[]", "--protocol-url": "url[]",
            "--requirement": "string[]", "--requirement-source": ["user", "design", "biz-flow"], "--biz-flow-ref": "string[]", "--confirm": "boolean", "--reject": "boolean", "--confirmation-summary": "string",
        }
    },
    "e2e.discover": {
        "options": {
            "--project": "path", "--design-root": "path[]", "--design-file": "path[]",
            "--openapi-root": "path[]", "--openapi-file": "path[]", "--runtime-url": "url[]", "--protocol-url": "url[]",
        }
    },
    "e2e.generate": {
        "options": {
            "--project": "path", "--design-root": "path[]", "--design-file": "path[]",
            "--openapi-root": "path[]", "--openapi-file": "path[]", "--runtime-url": "url[]", "--protocol-url": "url[]",
        }
    },
    "e2e.check": {
        "options": {
            "--project": "path",
            "--gate": [*E2E_ORDERED_GATES, "discovery", "contracts", "static", "all"],
            "--scenario": "string",
        },
        "required": ["--gate"],
    },
    "e2e.source-status": {"options": {"--project": "path", "--scenario": "string"}},
    "e2e.run": {
        "options": {
            "--project": "path",
            "--scenario": "string",
            "--static-only": "boolean",
            "pytest_args": "restricted-string[]",
        }
    },
    "biz-flow.init": {"options": {"--project": "path", "--docs-root": "path"}},
    "biz-flow.discover": {
        "options": {"--project": "path", "--docs-root": "path", "--commit": "string"}
    },
    "biz-flow.check": {
        "options": {"--project": "path", "--docs-root": "path", "--module": "string", "--commit": "string", "--stage": "string"}
    },
    "biz-flow.prepare": {"options": {"--project": "path", "--docs-root": "path", "--module": "string", "--purpose": "string", "--confirm": "boolean"}},
    "biz-flow.collect": {"options": {"--project": "path", "--docs-root": "path", "--run-id": "string", "--results": "path"}},
    "biz-flow.accept": {"options": {"--project": "path", "--docs-root": "path", "--run-id": "string"}},
}


def _object(properties: dict[str, Any], required: tuple[str, ...] | None = None, *, additional: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required or properties),
        "additionalProperties": additional,
        "properties": properties,
    }


def _array(items: dict[str, Any], *, minimum: int = 0, unique: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": items}
    if minimum:
        schema["minItems"] = minimum
    if unique:
        schema["uniqueItems"] = True
    return schema


NONEMPTY_STRING = {"type": "string", "minLength": 1}
STRING_LIST = _array(NONEMPTY_STRING, unique=True)
NONEMPTY_STRING_LIST = _array(NONEMPTY_STRING, minimum=1, unique=True)

E2E_DOCUMENT_BASELINE_SCHEMA = _object(
    {"git_commit": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"}},
    ("git_commit",),
    additional=False,
)
E2E_DOCUMENT_STATE_SCHEMA = _object(
    {
        "status": {"type": "string", "enum": ["missing", "draft", "awaiting_confirmation", "confirmed", "generated"]},
        "requirements": _array(NONEMPTY_STRING),
        "requirement_sources": _array(_object({
            "type": {"type": "string", "enum": ["user", "design", "biz-flow"]},
            "value": NONEMPTY_STRING,
        }), unique=False),
        "candidates": {"type": "array", "items": _object({
            "id": NONEMPTY_STRING,
            "name": NONEMPTY_STRING,
            "document": {"type": "string"},
            "objective": NONEMPTY_STRING,
            "business_entry": NONEMPTY_STRING,
            "preconditions": NONEMPTY_STRING_LIST,
            "test_data": NONEMPTY_STRING_LIST,
            "key_steps": NONEMPTY_STRING_LIST,
            "expected_results": NONEMPTY_STRING_LIST,
            "exceptions_and_compensation": NONEMPTY_STRING_LIST,
            "biz_flow_refs": {"type": "array"},
            "mermaid": NONEMPTY_STRING,
            "owner": NONEMPTY_STRING,
        })},
        "confirmed_at": {"type": "string"},
        "confirmation_summary": {"type": "string"},
        "rejected_at": {"type": "string"},
        "rejection_summary": {"type": "string"},
        "candidate_fingerprint": {"type": "string", "minLength": 1},
        "input_fingerprint": {"type": "string", "minLength": 1},
        "source_fingerprint": {"type": "string", "minLength": 1},
        "pending_changes": {"type": "object", "additionalProperties": True},
    },
    ("status", "requirements", "requirement_sources", "candidates", "candidate_fingerprint", "input_fingerprint", "source_fingerprint"),
    additional=False,
)


def _control_schema(name: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "status": {"type": "string", "enum": list(E2E_CONTROL_STATUSES)},
        "assessment": NONEMPTY_STRING,
        "evidence": STRING_LIST,
        "planned_use": STRING_LIST,
        "component": NONEMPTY_STRING,
        "trigger": NONEMPTY_STRING,
        "impact": NONEMPTY_STRING,
        "observation": NONEMPTY_STRING,
        "isolation": NONEMPTY_STRING,
        "cleanup": STRING_LIST,
        "recovery": STRING_LIST,
    }
    if name == "database_control":
        operation_schema = _object(
            {
                "id": NONEMPTY_STRING,
                "depends_on": STRING_LIST,
                "consumer_source": NONEMPTY_STRING,
                "exact_selector": NONEMPTY_STRING,
                "expected_rows": {"const": 1},
                "snapshot": NONEMPTY_STRING,
                "mutation": NONEMPTY_STRING,
                "verification": NONEMPTY_STRING,
                "restoration": NONEMPTY_STRING,
                "restoration_verification": NONEMPTY_STRING,
            },
            (
                "id", "depends_on", "consumer_source", "exact_selector", "expected_rows",
                "snapshot", "mutation", "verification", "restoration", "restoration_verification",
            ),
        )
        common = {
            "authorization_required": {"const": True},
            "target_environment": NONEMPTY_STRING,
            "purpose": {
                "type": "string",
                "enum": ["preparation", "time_advance", "expiry_simulation", "state_trigger"],
            },
        }
        single = {
            **common,
            "consumer_source": NONEMPTY_STRING,
            "exact_selector": NONEMPTY_STRING,
            "expected_rows": {"const": 1},
            "snapshot": NONEMPTY_STRING,
            "mutation": NONEMPTY_STRING,
            "trigger": NONEMPTY_STRING,
            "verification": NONEMPTY_STRING,
            "restoration": NONEMPTY_STRING,
            "restoration_verification": NONEMPTY_STRING,
        }
        multi = {
            **common,
            "trigger": NONEMPTY_STRING,
            "verification": NONEMPTY_STRING,
            "operations": _array(operation_schema, minimum=1),
        }
        properties["safety"] = {
            "oneOf": [
                {"type": "null"},
                _object(single, (
                    "authorization_required", "target_environment", "purpose", "consumer_source", "exact_selector",
                    "expected_rows", "snapshot", "mutation", "trigger", "verification", "restoration",
                    "restoration_verification",
                )),
                _object(multi),
            ]
        }
    if name == "observability":
        properties.update(
            {
                "correlation_keys": STRING_LIST,
                "business_evidence": STRING_LIST,
                "recovery": STRING_LIST,
            }
        )
    return _object(properties)


def _candidate_schema() -> dict[str, Any]:
    return _object(
        {
            "kind": {"type": "string", "enum": list(E2E_CANDIDATE_KINDS)},
            "status": {"type": "string", "enum": list(E2E_CANDIDATE_STATUSES)},
            "component": NONEMPTY_STRING,
            "consumer_source": NONEMPTY_STRING,
            "control": NONEMPTY_STRING,
            "side_effect": {"type": "string", "enum": ["none", "read", "write"]},
            "trigger": NONEMPTY_STRING,
            "observation": NONEMPTY_STRING,
            "isolation": NONEMPTY_STRING,
            "cleanup": NONEMPTY_STRING,
            "impact": NONEMPTY_STRING,
            "recovery": NONEMPTY_STRING,
            "evidence": NONEMPTY_STRING_LIST,
        }
    )


SCENARIO_REQUIRED = (
    "meta",
    "generation",
    "readiness",
    "preconditions",
    "constructability",
    "integrations",
    "controls",
    "isolation",
    "steps",
    "cleanup",
    "source",
)

SCENARIO_DOCUMENT_SCHEMA = _object(
    {
        "meta": _object(
            {
                "id": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]+$"},
                "name": NONEMPTY_STRING,
                "status": {"type": "string", "enum": list(E2E_SCENARIO_STATUSES)},
                "actor": NONEMPTY_STRING,
                "participants": STRING_LIST,
                "context": {"type": "object", "additionalProperties": True},
            },
            ("id", "name", "status", "actor"),
        ),
        "generation": _object(
            {
                "mode": {"type": "string", "enum": list(E2E_GENERATION_MODES)},
                "owner": NONEMPTY_STRING,
                "write_scope": {"type": "string", "pattern": "^scenarios/[^/]+$"},
                "degradation_reason": {"type": ["string", "null"]},
            }
        ),
        "readiness": _object(
            {
                "source_contract": {"type": "string", "enum": ["confirmed", "blocked"]},
                "safe_control": {"type": "string", "enum": ["confirmed", "blocked"]},
                "runtime_configuration": {"type": "string", "enum": ["confirmed", "missing"]},
                "test_data": {"type": "string", "enum": ["confirmed", "missing"]},
                "blockers": STRING_LIST,
            }
        ),
        "constructability": _object(
            {
                "preconditions": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "data_ownership": {"type": "string", "enum": ["test_owned", "environment_owned", "not_data"]},
                            "constructible": {"type": "boolean"},
                            "candidates": _array(_candidate_schema(), minimum=1),
                        },
                        ("id", "data_ownership", "constructible", "candidates"),
                    ),
                    unique=False,
                ),
                "steps": _array(
                    _object(
                        {
                            "step_id": NONEMPTY_STRING,
                            "candidates": _array(_candidate_schema(), minimum=1),
                        },
                        ("step_id", "candidates"),
                    ),
                    unique=False,
                ),
            },
            ("preconditions", "steps"),
        ),
        "preconditions": NONEMPTY_STRING_LIST,
        "integrations": _object(
            {
                "services": STRING_LIST,
                "components": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "type": NONEMPTY_STRING,
                            "required": {"type": "boolean"},
                        }
                    )
                ),
            }
        ),
        "controls": _object(
            {
                **{name: _control_schema(name) for name in E2E_CONTROL_NAMES},
                "decision": _object(
                    {"safe_control_path": {"type": "boolean"}, "blockers": STRING_LIST}
                ),
            }
        ),
        "isolation": _object(
            {
                "namespace": NONEMPTY_STRING,
                "correlation_keys": NONEMPTY_STRING_LIST,
                "owned_resources": _array(
                    _object(
                        {
                            "kind": NONEMPTY_STRING,
                            "identity": NONEMPTY_STRING,
                            "cleanup": NONEMPTY_STRING,
                            "restore": NONEMPTY_STRING,
                            "verify": NONEMPTY_STRING,
                        }
                    )
                ),
                "mutable_controls": STRING_LIST,
                "serial_lock": {"type": "null"},
            }
        ),
        "steps": _array(
            _object(
                {
                    "id": NONEMPTY_STRING,
                    "action": NONEMPTY_STRING,
                    "control": {"type": "string", "enum": list(E2E_CONTROL_NAMES)},
                    "side_effect": {"type": "string", "enum": ["none", "read", "write"]},
                    "data_ref": {"type": "string", "pattern": "^涓氬姟鏁版嵁\\.json#/"},
                    "expect": NONEMPTY_STRING_LIST,
                    "status": {"type": "string", "enum": list(E2E_STEP_STATUSES)},
                    "status_reason": NONEMPTY_STRING,
                    "evidence": STRING_LIST,
                    "design_rule_id": NONEMPTY_STRING,
                    "protocol_ref": NONEMPTY_STRING,
                    "phase": {"type": "string", "enum": ["request", "message_acceptance", "processing", "final_business", "side_effect"]},
            "async": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "trigger": NONEMPTY_STRING,
                            "correlation_key": NONEMPTY_STRING,
                            "expected_status": NONEMPTY_STRING,
                            "acceptance_status": NONEMPTY_STRING,
                            "final_status": NONEMPTY_STRING,
                            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                            "interval_seconds": {"type": "number", "exclusiveMinimum": 0},
                            "retries": {"type": "integer", "minimum": 0},
                            "repeat_detection": NONEMPTY_STRING,
                            "final_failure": NONEMPTY_STRING,
                        },
                        "required": ["trigger", "correlation_key", "expected_status", "timeout_seconds", "interval_seconds", "retries", "repeat_detection", "final_failure"],
                    },
                },
                ("id", "action", "control", "side_effect", "expect", "status", "status_reason", "evidence"),
            ),
            minimum=1,
        ),
        "cleanup": _object(
            {
                "strategy": NONEMPTY_STRING,
                "actions": NONEMPTY_STRING_LIST,
                "verifies": NONEMPTY_STRING_LIST,
            }
        ),
        "source": _array(
            _object(
                {
                    "repo": NONEMPTY_STRING,
                    "commit": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"},
                    "anchors": NONEMPTY_STRING_LIST,
                }
            ),
            minimum=1,
        ),
    },
    SCENARIO_REQUIRED,
)

SCENARIO_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.scenario",
    "path": "scenarios/<scenario>/鍦烘櫙瀹氫箟.yaml",
    "required": list(SCENARIO_REQUIRED),
    "status": list(E2E_SCENARIO_STATUSES),
    "generation_mode": list(E2E_GENERATION_MODES),
    "control_names": list(E2E_CONTROL_NAMES),
    "control_status": list(E2E_CONTROL_STATUSES),
    "step_status": list(E2E_STEP_STATUSES),
    "candidate_kinds": list(E2E_CANDIDATE_KINDS),
    "candidate_status": list(E2E_CANDIDATE_STATUSES),
    "document": SCENARIO_DOCUMENT_SCHEMA,
    "required_sibling_artifacts": ["涓氬姟鏁版嵁.json", "涓氬姟娴佺▼鍥?md", "test_<scenario>.py"],
    "machine_gate": "devflow e2e check --gate contracts",
}


CONFIG_VALUE_SCHEMA = _object(
    {
        "value": {},
        "effective_source": NONEMPTY_STRING,
        "resolution": {"type": "string", "enum": ["resolved", "unresolved"]},
        "source_key": NONEMPTY_STRING,
    }
)
CONFIG_REFERENCE_SCHEMA = _object(
    {
        "reference": {
            "type": "string",
            "pattern": "^(\\$\\{[A-Z][A-Z0-9_]*\\}|(?:environment|env|secret-store|vault|config|config-center|file-key|provider):.+)$",
        },
        "effective_source": NONEMPTY_STRING,
        "resolution": {"type": "string", "enum": ["resolved", "unresolved"]},
        "source_key": NONEMPTY_STRING,
    }
)
SEARCH_SCHEMA = _object(
    {"queries": NONEMPTY_STRING_LIST, "evidence": STRING_LIST, "conclusion": NONEMPTY_STRING}
)

WORKSPACE_DOCUMENT_SCHEMA = _object(
    {
        "schema_version": {"const": 1},
        "inventory": _object(
            {
                "roots": NONEMPTY_STRING_LIST,
                "repositories": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "root": NONEMPTY_STRING,
                            "commit": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"},
                            "build_files": STRING_LIST,
                            "modules": _array(
                                _object(
                                    {
                                        "id": NONEMPTY_STRING,
                                        "path": NONEMPTY_STRING,
                                        "kind": {
                                            "type": "string",
                                            "enum": ["application", "sdk", "starter", "client", "facade", "library", "e2e", "other"],
                                        },
                                    }
                                ),
                                minimum=1,
                            ),
                        }
                    ),
                    minimum=1,
                ),
                "existing_e2e": STRING_LIST,
            }
        ),
        "topology": _object(
            {
                "nodes": _array(_object({"id": NONEMPTY_STRING, "relevant": {"type": "boolean"}})),
                "edges": _array(
                    _object(
                        {
                            "from": NONEMPTY_STRING,
                            "to": NONEMPTY_STRING,
                            "mechanism": {
                                "type": "string",
                                "enum": ["build", "http", "rpc", "message", "database", "cache", "job", "configuration", "embedded"],
                            },
                            "evidence": NONEMPTY_STRING_LIST,
                        }
                    )
                ),
                "searches": _object(
                    {name: SEARCH_SCHEMA for name in ("http_rpc", "messages", "database", "cache", "jobs", "configuration")}
                ),
            }
        ),
        "configuration": _object(
            {
                "sources": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "owner": NONEMPTY_STRING,
                            "kind": {
                                "type": "string",
                                "enum": ["file", "profile", "environment", "config-center", "command-line", "local-override", "other"],
                            },
                            "location": NONEMPTY_STRING,
                            "profile": {"type": ["string", "null"]},
                            "overrides": STRING_LIST,
                            "evidence": NONEMPTY_STRING_LIST,
                        }
                    ),
                    minimum=1,
                ),
                "precedence": NONEMPTY_STRING_LIST,
                "services": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "owner": NONEMPTY_STRING,
                            "port": CONFIG_VALUE_SCHEMA,
                            "context_path": CONFIG_VALUE_SCHEMA,
                            "health": CONFIG_VALUE_SCHEMA,
                            "openapi": CONFIG_VALUE_SCHEMA,
                        }
                    )
                ),
                "data_sources": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "owner": NONEMPTY_STRING,
                            "type": NONEMPTY_STRING,
                            "name": CONFIG_VALUE_SCHEMA,
                            "connection_source": CONFIG_REFERENCE_SCHEMA,
                        }
                    )
                ),
                "middleware": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "owner": NONEMPTY_STRING,
                            "capability": {"type": "string", "enum": ["messages", "cache"]},
                            "type": NONEMPTY_STRING,
                            "logical_name": CONFIG_VALUE_SCHEMA,
                            "connection_source": CONFIG_REFERENCE_SCHEMA,
                        }
                    )
                ),
                "controls": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "owner": NONEMPTY_STRING,
                            "capability": {
                                "type": "string",
                                "enum": ["jobs", "test_or_admin_api", "mocks_and_faults", "dynamic_configuration", "scheduled_jobs"],
                            },
                            "type": NONEMPTY_STRING,
                            "source": NONEMPTY_STRING,
                        }
                    )
                ),
            }
        ),
        "runtime_probe": _object(
            {
                "requested": {"type": "boolean"},
                "outcome": {"type": "string", "enum": ["completed", "blocked", "not_requested"]},
                "blockers": STRING_LIST,
                "listeners": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "host": NONEMPTY_STRING,
                            "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                            "protocol": NONEMPTY_STRING,
                            "evidence": NONEMPTY_STRING_LIST,
                        }
                    )
                ),
                "processes": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "pid": {"type": "integer", "minimum": 1},
                            "command_reference": NONEMPTY_STRING,
                            "startup_arguments": STRING_LIST,
                            "working_directory": NONEMPTY_STRING,
                            "profile": {"type": ["string", "null"]},
                            "evidence": NONEMPTY_STRING_LIST,
                        },
                        ("id", "pid", "command_reference", "evidence"),
                    )
                ),
                "associations": _array(
                    _object({"process": NONEMPTY_STRING, "listener": NONEMPTY_STRING, "node": NONEMPTY_STRING})
                ),
                "read_only_smoke": _array(
                    _object(
                        {
                            "node": NONEMPTY_STRING,
                            "method": {"type": "string", "enum": ["GET", "HEAD", "READ"]},
                            "target_ref": NONEMPTY_STRING,
                            "result": NONEMPTY_STRING,
                        }
                    )
                ),
                "component_probes": _array({"type": "object", "additionalProperties": True}),
                "protocol_candidates": _array({"type": "object", "additionalProperties": True}),
                "protocol_sources": _array({"type": "object", "additionalProperties": True}),
                "classifications": _array({"type": "string", "enum": list(E2E_RUNTIME_CLASSIFICATIONS)}),
                "failure_details": _array({"type": "object", "additionalProperties": True}),
                "configuration_checks": _array(
                    _object(
                        {
                            "id": NONEMPTY_STRING,
                            "node": NONEMPTY_STRING,
                            "profile": {"type": ["string", "null"]},
                            "sources": NONEMPTY_STRING_LIST,
                            "effective": {"type": "string", "enum": ["confirmed", "unconfirmed"]},
                            "evidence": NONEMPTY_STRING_LIST,
                        }
                    )
                ),
            },
            ("requested", "outcome", "blockers", "listeners", "processes", "associations", "read_only_smoke"),
        ),
        "design": {"type": "object", "additionalProperties": True},
        "protocol": {"type": "object", "additionalProperties": True},
        "gates": _object(
            {
                "inventory_complete": {"const": True},
                "topology_complete": {"const": True},
                "configuration_complete": {"const": True},
                "runtime_probe_complete": {"const": True},
            }
        ),
    },
    ("schema_version", "inventory", "topology", "configuration", "runtime_probe", "gates"),
)

WORKSPACE_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.workspace",
    "path": "analysis/workspace.yaml",
    "document": WORKSPACE_DOCUMENT_SCHEMA,
    "machine_gate": "devflow e2e check --gate discovery",
}


CONFIG_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.config",
    "files": {
        "configuration/config.yaml": _object(
            {
                "active_environment": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
                "defaults": _object(
                    {
                        "polling": _object(
                            {
                                "interval_seconds": {"type": "number", "exclusiveMinimum": 0},
                                "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                            }
                        ),
                        "safety": _object(
                            {
                                "database_control_enabled": {"const": False},
                                "mutable_configuration_enabled": {"const": False},
                                "message_publish_enabled": {"const": False},
                            }
                        ),
                    },
                    ("safety",),
                ),
            }
        ),
        "configuration/environments/<active_environment>.yaml": _object(
            {
                "services": {"type": "object", "additionalProperties": {"type": "object"}},
                "components": {"type": "object", "additionalProperties": {"type": "object"}},
                "safety": _object(
                    {
                        "test_environment": {"type": "boolean"},
                        "side_effects_allowed": {"type": "boolean"},
                        "protected": {"type": "boolean"},
                    }
                ),
            },
            additional=True,
        ),
        "scenarios/<scenario>/涓氬姟鏁版嵁.json": {
            "type": "object",
            "additionalProperties": {"type": "object"},
            "description": "Top-level keys are exact environment names; data_ref resolves only inside the active environment.",
        },
    },
    "runtime_authorization": {
        "environment": "E2E_CONTROL_ENVIRONMENT",
        "database_control": ["E2E_ENABLE_DATABASE_CONTROL", "E2E_CONTROL_AUTHORIZATION_REF"],
        "mutable_configuration": ["E2E_ENABLE_MUTABLE_CONFIGURATION", "E2E_MUTABLE_CONFIGURATION_AUTHORIZATION_REF"],
        "message_publish": ["E2E_ENABLE_MESSAGE_PUBLISH", "E2E_MESSAGE_PUBLISH_AUTHORIZATION_REF"],
        "other_dangerous_control": ["E2E_ENABLE_DANGEROUS_CONTROL", "E2E_DANGEROUS_CONTROL_AUTHORIZATION_REF"],
    },
    "machine_gate": "devflow e2e check --gate static",
}


CONTROL_EVENT_SCHEMA = _object(
    {
        "control_kind": {"type": "string", "enum": list(E2E_CONTROL_NAMES)},
        "action": NONEMPTY_STRING,
        "correlation_ref": NONEMPTY_STRING,
        "side_effect": {"type": "string", "enum": ["read", "write"]},
        "step_id": NONEMPTY_STRING,
        "protocol_ref": NONEMPTY_STRING,
        "protocol_path": {"type": ["string", "null"]},
    },
    ("control_kind", "action", "correlation_ref", "side_effect"),
)
ENDPOINT_EVENT_SCHEMA = _object(
    {
        "phase": {"type": "string", "enum": ["smoke", "business"]},
        "method": NONEMPTY_STRING,
        "target_ref": NONEMPTY_STRING,
        "status": {},
        "summary": {},
        "verified": {"const": True},
        "step_id": {"type": ["string", "null"]},
        "protocol_ref": {"type": ["string", "null"]},
        "protocol_path": {"type": ["string", "null"]},
    }
)
RESTORATION_EVENT_SCHEMA = _object(
    {
        "status": {"type": "string", "enum": ["passed", "failed"]},
        "resources": STRING_LIST,
        "error": NONEMPTY_STRING,
    },
    ("status", "resources"),
)
SOURCE_VERSION_SCHEMA = _object(
    {
        "scenario": NONEMPTY_STRING,
        "repository": NONEMPTY_STRING,
        "recorded_commit": NONEMPTY_STRING,
        "current_commit": {"type": ["string", "null"]},
        "dirty": {"type": "boolean"},
        "dirty_files": STRING_LIST,
        "changed_files": STRING_LIST,
        "unresolved_anchors": STRING_LIST,
        "outcome": {
            "type": "string",
            "enum": ["unchanged", "affected", "dirty_review_required", "full_rediscovery_required"],
        },
        "reason": NONEMPTY_STRING,
    }
)

REPORT_SCENARIO_SCHEMA = _object(
    {
        "name": NONEMPTY_STRING,
        "owner": {"type": ["string", "null"]},
        "generation_mode": {"type": ["string", "null"], "enum": [*E2E_GENERATION_MODES, None]},
        "degradation_reason": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"], "enum": [*E2E_SCENARIO_STATUSES, None]},
        "participants": STRING_LIST,
        "integrations": _object({
            "services": STRING_LIST,
            "components": _array(_object({"id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "required": {"type": "boolean"}})),
        }),
        "design_rule_ids": STRING_LIST,
        "protocol_refs": STRING_LIST,
        "planned_controls": _array({"type": "string", "enum": list(E2E_CONTROL_NAMES)}, unique=True),
        "used_controls": _array(CONTROL_EVENT_SCHEMA),
        "endpoint_calls": _array(ENDPOINT_EVENT_SCHEMA),
        "business_entered": {"type": "boolean"},
        "smoke": {"type": "string", "enum": ["N/A", "passed", "failed"]},
        "business": _object(
            {
                "status": {"type": "string", "enum": ["N/A", "passed", "failed"]},
                "exit_code": {"type": ["integer", "null"]},
                "reason": NONEMPTY_STRING,
            }
        ),
        "restoration": _array(RESTORATION_EVENT_SCHEMA),
        "step_results": _array(
            _object(
                {
                    "id": NONEMPTY_STRING,
                    "status": {"type": "string", "enum": list(E2E_STEP_STATUSES)},
                    "reason": NONEMPTY_STRING,
                    "evidence": STRING_LIST,
                    "design_rule_id": {"type": ["string", "null"]},
                    "protocol_ref": {"type": ["string", "null"]},
                    "phase": {"type": ["string", "null"], "enum": ["request", "message_acceptance", "processing", "final_business", "side_effect", None]},
                    "expected": STRING_LIST,
                    "actual": {},
                },
                ("id", "status", "reason", "evidence"),
            )
        ),
        "execution_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "coverage_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "business_correctness": {"type": "string", "enum": ["unknown", "passed", "failed"]},
        "classification": {"type": "string", "enum": ["static_complete", "executed", "partially_covered", "business_failure", "blocked"]},
    }
)

REPORT_DESIGN_SCHEMA = _object({
    "documents": _array(_object({
        "path": NONEMPTY_STRING, "sha256": NONEMPTY_STRING,
        "version": {"type": ["string", "null"]}, "sections": {"type": "integer", "minimum": 0},
    }, ("path", "sha256", "version"))),
    "rules": _array(_object({"id": NONEMPTY_STRING, "section": NONEMPTY_STRING, "source": {"type": "object", "additionalProperties": True}})),
    "manual_confirmation": STRING_LIST,
})
REPORT_PROTOCOL_SCHEMA = _object({
    "documents": _array(_object({
        "path": NONEMPTY_STRING, "sha256": NONEMPTY_STRING, "version": {"type": ["string", "null"]},
        "source_type": {"type": "string"}, "service": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]}, "format": {"type": ["string", "null"]},
        "fetched_at": {"type": ["string", "null"]}, "content_sha256": {"type": ["string", "null"]},
        "user_confirmed": {"type": "boolean"},
    }, ("path", "sha256", "version"))),
    "operations": _array(_object({
        "id": NONEMPTY_STRING, "kind": NONEMPTY_STRING, "method": {"type": ["string", "null"]},
        "path": {"type": ["string", "null"]}, "source": {"type": "object", "additionalProperties": True},
    })),
})
REPORT_COVERAGE_SCHEMA = _object({
    "design_to_scenario": _object({
        "rule_count": {"type": "integer", "minimum": 0}, "rule_ids": STRING_LIST,
        "scenario_references": {"type": "integer", "minimum": 0}, "unreferenced_rules": STRING_LIST,
    }),
    "protocol_to_call": _object({
        "operation_count": {"type": "integer", "minimum": 0}, "operation_ids": STRING_LIST,
        "calls": {"type": "integer", "minimum": 0}, "unused_operations": STRING_LIST,
    }),
})
REPORT_DIFFERENCE_SCHEMA = _object({
    "scenario": NONEMPTY_STRING, "step": NONEMPTY_STRING,
    "design_rule_id": {"type": ["string", "null"]}, "protocol_ref": {"type": ["string", "null"]},
    "expected": STRING_LIST, "actual": {}, "status": NONEMPTY_STRING, "reason": NONEMPTY_STRING,
})

REPORT_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.report",
    "path": "artifacts/e2e-run.json",
    "gate_order": list(E2E_RUN_STAGES),
    "stage_status": ["N/A", "passed", "failed"],
    "document": _object(
        {
            "schema_version": {"const": 1},
            "run_id": NONEMPTY_STRING,
            "started_at": NONEMPTY_STRING,
            "finished_at": {"type": ["string", "null"]},
            "selected_scenario": {"type": ["string", "null"]},
            "static_only": {"type": "boolean"},
            "stages": _object(
                {
                    name: _object(
                        {
                            "status": {"type": "string", "enum": ["N/A", "passed", "failed"]},
                            "exit_code": {"type": ["integer", "null"]},
                        }
                    )
                    for name in E2E_RUN_STAGES
                }
            ),
            "discovery": _object(
                {
                    "repositories": {
                        "anyOf": [
                            WORKSPACE_DOCUMENT_SCHEMA["properties"]["inventory"]["properties"]["repositories"],
                            {"type": "array", "maxItems": 0},
                        ]
                    },
                    "existing_e2e": STRING_LIST,
                    "topology": {
                        "anyOf": [
                            WORKSPACE_DOCUMENT_SCHEMA["properties"]["topology"],
                            {"type": "object", "maxProperties": 0},
                        ]
                    },
                    "configuration": {
                        "anyOf": [
                            WORKSPACE_DOCUMENT_SCHEMA["properties"]["configuration"],
                            {"type": "object", "maxProperties": 0},
                        ]
                    },
                    "runtime_probe": {
                        "anyOf": [
                            WORKSPACE_DOCUMENT_SCHEMA["properties"]["runtime_probe"],
                            {"type": "object", "maxProperties": 0},
                        ]
                    },
                    "active_runtime_probe": WORKSPACE_DOCUMENT_SCHEMA["properties"]["runtime_probe"],
                    "diagnostics": STRING_LIST,
                }
            ),
            "design": REPORT_DESIGN_SCHEMA,
            "protocol": REPORT_PROTOCOL_SCHEMA,
            "coverage": REPORT_COVERAGE_SCHEMA,
            "exclusions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "support_only": _object({
                "repository_versions": _array(_object({"repo": NONEMPTY_STRING, "commit": NONEMPTY_STRING})),
                "configuration": {"type": "object", "additionalProperties": True},
                "value_resolution": {"type": "object", "additionalProperties": True},
            }),
            "differences": _array(REPORT_DIFFERENCE_SCHEMA),
            "source_versions": _array(SOURCE_VERSION_SCHEMA),
            "scenarios": _array(REPORT_SCENARIO_SCHEMA),
            "evidence_diagnostics": STRING_LIST,
        }
    ),
}

BRU_API_EVIDENCE_SCHEMA = _object({
    "source_kind": {"type": "string", "enum": ["design", "openapi", "config", "fixture", "support-source"]},
    "file": NONEMPTY_STRING,
    "symbol": NONEMPTY_STRING,
    "line": {"type": "integer", "minimum": 1},
    "endpoint_scope": NONEMPTY_STRING_LIST,
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "quote": {"type": "string"},
    "evidence_level": {"type": "string", "enum": ["explicit", "derived", "unknown"]},
}, ("source_kind", "file", "symbol", "line", "endpoint_scope", "confidence"))
BRU_API_DESIGN_DOCUMENT_SCHEMA = _object({
    "path": NONEMPTY_STRING,
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "sections": {"type": "integer", "minimum": 0},
    "understanding": {"type": "string", "enum": ["marker", "semantic", "unknown"]},
    "semantic_rules": {"type": "integer", "minimum": 0},
    "parser_gap": {"type": "boolean"},
    "marker_operations": STRING_LIST,
    "semantic_operations": STRING_LIST,
    "semantic_only_operations": STRING_LIST,
    "design_version": {"type": ["string", "null"]},
}, ("path", "sha256", "sections", "semantic_rules", "parser_gap"))
BRU_API_FLOW_STEP_SCHEMA = _object({
    "rule_id": NONEMPTY_STRING,
    "operation": NONEMPTY_STRING,
    "capture": NONEMPTY_STRING_LIST,
    "capture_paths": {
        "type": "object",
        "minProperties": 1,
        "additionalProperties": NONEMPTY_STRING,
    },
    "uses": NONEMPTY_STRING_LIST,
    "assert_absent": {},
    "business_assertions": _array({"type": "object", "additionalProperties": True}),
}, ("rule_id", "operation", "business_assertions"))
BRU_API_FLOW_SCHEMA = _object({
    "id": NONEMPTY_STRING,
    "mode": {"const": "sequential"},
    "source": {"const": "design"},
    "design_rule_ids": NONEMPTY_STRING_LIST,
    "steps": _array(BRU_API_FLOW_STEP_SCHEMA, minimum=2),
    "business_assertions": _array({"type": "object", "additionalProperties": True}),
    "data_transfer": _array({"type": "object", "additionalProperties": True}),
    "final_status": {"type": "string"},
    "cleanup": NONEMPTY_STRING,
}, ("id", "mode", "source", "design_rule_ids", "steps", "business_assertions", "data_transfer", "final_status"))
BRU_API_DESIGN_RULE_SCHEMA = _object(
    {
        "id": NONEMPTY_STRING,
        "method": NONEMPTY_STRING,
        "path": NONEMPTY_STRING,
        "title": NONEMPTY_STRING,
        "content": {"type": "string"},
        "scenario": {"type": "string", "enum": [
            "success", "authentication", "authorization", "query", "business_error", "safety",
        ]},
        "condition": {"type": "string"},
        "business_codes": {"type": "array", "items": {}},
        "http_statuses": _array({"type": "integer", "minimum": 100, "maximum": 599}),
        "states": STRING_LIST,
        "transitions": STRING_LIST,
        "side_effects": STRING_LIST,
        "negative_constraints": STRING_LIST,
        "idempotency": STRING_LIST,
        "retries": STRING_LIST,
        "concurrency": STRING_LIST,
        "external_failures": STRING_LIST,
        "async": {"type": "boolean"},
        "acceptance_statuses": STRING_LIST,
        "final_statuses": STRING_LIST,
        "assertions": _array(_object({
            "path": NONEMPTY_STRING, "equals": {}, "exists": {"type": "boolean"},
            "is_null": {"type": "boolean"}, "contains": {}, "matches": {"type": "string"},
        }, ("path",))),
        "candidate_assertions": _array({"type": "object", "additionalProperties": True}),
        "request": {"type": ["object", "null"], "additionalProperties": True},
        "request_declared": {"type": "boolean"},
        "marker_errors": STRING_LIST,
        "section_line": {"type": "integer", "minimum": 1},
        "section_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "evidence": BRU_API_EVIDENCE_SCHEMA,
        "endpoint_id": {"type": ["string", "null"]},
        "evidence_level": {"type": "string", "enum": ["explicit", "derived", "unknown"]},
        "derivation": {"type": "string"},
        "understanding": {"type": "object", "additionalProperties": True},
        "mapping_category": {"type": "string", "enum": [
            "exact", "parameter_alias", "semantic_candidate", "design_without_openapi", "multiple_candidates",
        ]},
        "matched_operation": {"type": ["string", "null"]},
        "parameter_aliases": {"type": "object", "additionalProperties": {"type": "string"}},
        "manual_confirmation": _object({
            "required": {"const": True},
            "reasons": NONEMPTY_STRING_LIST,
            "related_interface": NONEMPTY_STRING,
            "business_rule": NONEMPTY_STRING,
            "design_quote": NONEMPTY_STRING,
            "current_derivation": NONEMPTY_STRING,
            "ambiguity": NONEMPTY_STRING,
            "impact": NONEMPTY_STRING,
            "options": NONEMPTY_STRING_LIST,
        }, ("required", "reasons")),
    },
    (
        "id", "method", "path", "title", "content", "scenario", "condition", "business_codes",
        "http_statuses", "states", "transitions", "side_effects", "idempotency", "retries",
        "concurrency", "external_failures", "async", "acceptance_statuses", "final_statuses", "negative_constraints",
        "assertions", "request", "request_declared", "marker_errors", "section_line", "section_sha256",
        "evidence", "endpoint_id",
        "evidence_level", "derivation", "understanding", "mapping_category", "matched_operation", "parameter_aliases",
        "candidate_assertions",
    ),
)
BRU_API_DESIGN_RULES_SCHEMA: dict[str, Any] = {
    "schema_version": BRU_API_SCHEMA_VERSION,
    "contract": "bru-api.design-rules",
    "path": "qa/constraints/design-rules.yaml",
    "document": _object({
        "version": {"const": 1},
        "source": {"const": "design"},
        "documents": _array(BRU_API_DESIGN_DOCUMENT_SCHEMA),
        "parser_diagnostics": _array({"type": "object", "additionalProperties": True}),
        "rules": _array(BRU_API_DESIGN_RULE_SCHEMA),
        "flows": _array(BRU_API_FLOW_SCHEMA),
        "flow_candidates": _array({"type": "object", "additionalProperties": True}),
        "exclusions": _array({"type": "object", "additionalProperties": True}),
        "manual_confirmations": _array(_object({
            "rule_id": NONEMPTY_STRING,
            "reasons": NONEMPTY_STRING_LIST,
            "evidence": BRU_API_EVIDENCE_SCHEMA,
            "related_interface": NONEMPTY_STRING,
            "business_rule": NONEMPTY_STRING,
            "design_quote": NONEMPTY_STRING,
            "current_derivation": NONEMPTY_STRING,
            "ambiguity": NONEMPTY_STRING,
            "impact": NONEMPTY_STRING,
            "options": NONEMPTY_STRING_LIST,
        }, ("rule_id", "reasons", "evidence", "related_interface", "business_rule", "design_quote", "current_derivation", "ambiguity", "impact", "options"))),
        "coverage": _object({
            "openapi_endpoints": {"type": "integer", "minimum": 0},
            "documented_endpoints": {"type": "integer", "minimum": 0},
            "excluded_endpoints": {"type": "integer", "minimum": 0},
            "mapped_endpoints": {"type": "integer", "minimum": 0},
        }, ("openapi_endpoints", "documented_endpoints", "excluded_endpoints")),
        "understanding": _array(_object({
            "rule_id": NONEMPTY_STRING,
            "business_name": NONEMPTY_STRING,
            "design_source": BRU_API_EVIDENCE_SCHEMA,
            "design_summary": {"type": "string"},
            "candidate_http_method": {"type": ["string", "null"]},
            "candidate_url_path": {"type": ["string", "null"]},
            "matched_openapi_operation": {"type": ["string", "null"]},
            "preconditions": {"type": "array", "items": {}},
            "request_meaning": {"type": "array", "items": {}},
            "success_result": {"type": "array", "items": {}},
            "state_changes": {"type": "array", "items": {}},
            "business_errors": {"type": "array", "items": {}},
            "side_effects": {"type": "array", "items": {}},
            "idempotency": {"type": "array", "items": {}},
            "retries": {"type": "array", "items": {}},
            "concurrency": {"type": "array", "items": {}},
            "async": {"type": "array", "items": {}},
            "consistency": {"type": "array", "items": {}},
            "negative_constraints": {"type": "array", "items": {}},
            "candidate_assertions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "evidence_level": {"type": "string", "enum": ["explicit", "derived", "unknown"]},
            "derivation": {"type": "string"},
            "unknown": STRING_LIST,
            "can_generate": {"type": "boolean"},
        }, (
            "rule_id", "business_name", "design_source", "design_summary", "candidate_http_method",
            "candidate_url_path", "matched_openapi_operation", "preconditions", "request_meaning",
            "success_result", "state_changes", "business_errors", "side_effects", "idempotency", "retries",
            "concurrency", "async", "consistency", "negative_constraints", "candidate_assertions",
            "evidence_level", "derivation", "unknown", "can_generate",
        ))),
        "mapping": _object({
            "items": _array(_object({
                "rule_id": {"type": ["string", "null"]},
                "category": {"type": "string", "enum": ["exact", "parameter_alias", "semantic_candidate", "design_without_openapi", "openapi_without_design", "multiple_candidates"]},
                "design_operation": {"type": ["string", "null"]},
                "openapi_operation": {"type": ["string", "null"]},
                "endpoint_id": {"type": ["string", "null"]},
                "parameter_aliases": {"type": "object", "additionalProperties": {"type": "string"}},
                "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "note": {"type": "string"},
            }, ("category", "design_operation", "openapi_operation", "endpoint_id", "parameter_aliases"))),
            "counts": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
        }, ("items", "counts")),
        "understanding_status": {"type": "string", "enum": ["incomplete", "blocked", "complete"]},
        "design_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "openapi_fingerprint": {"type": "string"},
    }, ("version", "source", "documents", "parser_diagnostics", "rules", "flows", "flow_candidates", "exclusions", "manual_confirmations", "coverage", "understanding", "mapping", "understanding_status", "design_fingerprint", "openapi_fingerprint")),
}
BRU_API_DESIGN_REPORT_SCHEMA: dict[str, Any] = {
    "schema_version": BRU_API_SCHEMA_VERSION,
    "contract": "bru-api.design-generation-report",
    "path": "qa/reports/latest.md",
    "document": _object({
        "version": {"const": 1},
        "source": {"const": "design"},
        "status": {"type": "string", "enum": ["complete", "blocked", "failed"]},
        "execution": {"type": "string"},
        "matrix_path": NONEMPTY_STRING,
        "formal_tests": _array({"type": "object", "additionalProperties": True}),
        "protocol_tests": _array({"type": "object", "additionalProperties": True}),
        "pending_cases": _array({"type": "object", "additionalProperties": True}),
        "pending_confirmations": _array({"type": "object", "additionalProperties": True}),
        "pending_flow_candidates": _array({"type": "object", "additionalProperties": True}),
        "unsupported": _array({"type": "object", "additionalProperties": True}),
        "uncovered_mapping": _array({"type": "object", "additionalProperties": True}),
        "unexecuted": _array({"type": "object", "additionalProperties": True}),
        "gate_failures": STRING_LIST,
    }, (
        "version", "source", "status", "execution", "matrix_path", "formal_tests", "protocol_tests",
        "pending_cases", "pending_confirmations", "pending_flow_candidates", "unsupported",
        "uncovered_mapping", "unexecuted", "gate_failures",
    )),
}
BRU_API_LOGIC_SCHEMA: dict[str, Any] = {
    "schema_version": BRU_API_SCHEMA_VERSION,
    "contract": "bru-api.logic",
    "path": "qa/contracts/modules/<module>/logic.yaml",
    "document": _object({
        "version": {"const": 1},
        "module": NONEMPTY_STRING,
        "swagger_tag": {"type": ["string", "null"]},
        "logic": _array(_object({
            "id": NONEMPTY_STRING,
            "status": {"const": "confirmed"},
            "source": {"const": "design"},
            "endpoint_id": NONEMPTY_STRING,
            "openapi_operation": NONEMPTY_STRING,
            "source_symbol": NONEMPTY_STRING,
            "condition": NONEMPTY_STRING,
            "expected_http_status": {"type": ["integer", "null"]},
            "expected_business_code": {},
            "expected_state": {},
            "transitions": STRING_LIST,
            "side_effects": STRING_LIST,
            "idempotency": STRING_LIST,
            "retries": STRING_LIST,
            "concurrency": STRING_LIST,
            "external_failures": STRING_LIST,
            "async": {"type": "boolean"},
            "acceptance_status": {"type": ["string", "null"]},
            "final_status": {"type": ["string", "null"]},
            "design_rule_id": NONEMPTY_STRING,
            "evidence_level": {"type": "string", "enum": ["explicit", "derived", "unknown"]},
            "evidence_quote": {"type": "string"},
            "derivation": {"type": "string"},
            "business_assertions": _array({"type": "object", "additionalProperties": True}),
            "evidence": _array(BRU_API_EVIDENCE_SCHEMA, minimum=1),
            "case_ids": NONEMPTY_STRING_LIST,
        }, (
            "id", "status", "source", "endpoint_id", "openapi_operation", "source_symbol", "condition", "expected_http_status",
            "expected_business_code", "expected_state", "transitions", "side_effects", "idempotency",
            "retries", "concurrency", "external_failures", "async", "acceptance_status", "final_status",
            "design_rule_id", "evidence_level", "evidence_quote", "derivation", "business_assertions", "evidence", "case_ids",
        ))),
    }, ("version", "module", "logic")),
}
BRU_API_VALUE_RESOLUTION_SCHEMA: dict[str, Any] = {
    "schema_version": BRU_API_SCHEMA_VERSION,
    "contract": "bru-api.value-resolution",
    "path": "qa/contracts/modules/<module>/value-resolution.yaml",
    "document": _object({
        "version": {"const": 1},
        "module": NONEMPTY_STRING,
        "fields": _array(_object({
            "endpoint_id": NONEMPTY_STRING,
            "field_path": NONEMPTY_STRING,
            "status": {"const": "resolved"},
            "value": {},
            "value_source": {"type": "string", "enum": ["config", "fixture", "support-source"]},
            "evidence": BRU_API_EVIDENCE_SCHEMA,
        })),
    }),
}
BRU_API_VERSION_LOCK_SCHEMA: dict[str, Any] = {
    "schema_version": BRU_API_SCHEMA_VERSION,
    "contract": "bru-api.version-lock",
    "path": "qa/contracts/bru-api-test-generator-version.json",
    "document": _object({
        "skill": {"const": "bru-api-test-generator"},
        "skill_version": NONEMPTY_STRING,
        "artifact_root": {"const": "qa/contracts"},
        "version": {"const": 1},
        "status": NONEMPTY_STRING,
        "business": {"type": "object", "additionalProperties": True},
        "openapi": _object({
            "file": NONEMPTY_STRING,
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }),
        "design": _object({
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "documents": _array(_object({
                "path": NONEMPTY_STRING,
                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            })),
            "rule_count": {"type": "integer", "minimum": 0},
            "mapping_counts": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            "unknown_count": {"type": "integer", "minimum": 0},
            "understanding_status": {"type": "string", "enum": ["incomplete", "blocked", "complete"]},
            "design_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "openapi_fingerprint": {"type": "string"},
        }, ("sha256", "documents", "rule_count")),
    }, ("skill", "skill_version", "artifact_root", "version", "status", "business")),
}

E2E_INPUT_DOCUMENT_SCHEMA = _object({
    "path": NONEMPTY_STRING,
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "version": {"type": ["string", "null"]},
    "sections": {"type": "integer", "minimum": 0},
    "source_type": {"type": "string", "enum": ["file", "runtime_url", "user_url", "service_config", "source_definition"]},
    "service": {"type": ["string", "null"]},
    "url": {"type": ["string", "null"]},
    "format": {"type": ["string", "null"]},
    "fetched_at": {"type": ["string", "null"]},
    "content_sha256": {"type": ["string", "null"]},
    "user_confirmed": {"type": "boolean"},
}, ("path", "sha256", "version"))
E2E_EVIDENCE_SOURCE_SCHEMA = _object({
    "source_kind": {"type": "string", "enum": ["design", "protocol"]},
    "file": NONEMPTY_STRING,
    "section": NONEMPTY_STRING,
    "line": {"type": "integer", "minimum": 1},
    "operation": NONEMPTY_STRING,
}, ("source_kind", "file"))
E2E_DESIGN_RULE_SCHEMA = _object({
    "id": NONEMPTY_STRING,
    "title": NONEMPTY_STRING,
    "type": {"type": "string", "enum": ["cross_service", "business"]},
    "manual_confirmation": {"type": "boolean"},
    "status": {"type": "string", "enum": list(E2E_RULE_STATUSES)},
    "context": {"type": "object", "additionalProperties": True},
    "method": {"type": ["string", "null"]},
    "path": {"type": ["string", "null"]},
    "event": {"type": ["string", "null"]},
    "task": {"type": ["string", "null"]},
    "calls": _array(_object({
        "kind": {"type": "string", "enum": ["http", "message", "task"]},
        "method": NONEMPTY_STRING,
        "path": NONEMPTY_STRING,
        "event": NONEMPTY_STRING,
        "task": NONEMPTY_STRING,
    }, ("kind",))),
    "participants": STRING_LIST,
    "states": STRING_LIST,
    "transitions": STRING_LIST,
    "acceptance_statuses": STRING_LIST,
    "final_statuses": STRING_LIST,
    "preconditions": STRING_LIST,
    "business_codes": STRING_LIST,
    "exceptions": STRING_LIST,
    "branches": STRING_LIST,
    "assertions": STRING_LIST,
    "final_result": STRING_LIST,
    "side_effects": STRING_LIST,
    "idempotency": STRING_LIST,
    "retries": STRING_LIST,
    "concurrency": STRING_LIST,
    "async_behavior": STRING_LIST,
    "cleanup": STRING_LIST,
    "recovery": STRING_LIST,
    "async": {"type": "boolean"},
    "section": NONEMPTY_STRING,
    "line": {"type": "integer", "minimum": 1},
    "section_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "protocol_refs": STRING_LIST,
    "source": E2E_EVIDENCE_SOURCE_SCHEMA,
}, (
    "id", "title", "type", "manual_confirmation", "method", "path", "event", "task", "calls",
    "participants", "states", "transitions", "acceptance_statuses", "final_statuses", "preconditions",
    "business_codes", "exceptions", "branches", "assertions", "final_result", "side_effects",
    "idempotency", "retries", "concurrency", "async_behavior", "cleanup", "recovery", "async",
    "section", "line", "section_sha256", "protocol_refs", "source",
))
E2E_PROTOCOL_OPERATION_SCHEMA = _object({
    "id": NONEMPTY_STRING,
    "kind": {"type": "string", "enum": ["http", "message", "rpc", "graphql", "task"]},
    "method": NONEMPTY_STRING,
    "path": NONEMPTY_STRING,
    "status_codes": STRING_LIST,
    "parameters": _array({"type": "object", "additionalProperties": True}),
    "request_body": {"type": "object", "additionalProperties": True},
    "request_fields": _array({"type": "object", "additionalProperties": True}),
    "response_fields": _array({"type": "object", "additionalProperties": True}),
    "responses": {"type": "object", "additionalProperties": True},
    "channel": NONEMPTY_STRING,
    "direction": {"type": "string", "enum": ["publish", "subscribe"]},
    "event": NONEMPTY_STRING,
    "message_version": {"type": ["string", "null"]},
    "message_fields": _array({"type": "object", "additionalProperties": True}),
    "header_fields": _array({"type": "object", "additionalProperties": True}),
    "message_schema": {"type": "object", "additionalProperties": True},
    "service": NONEMPTY_STRING,
    "request_type": NONEMPTY_STRING,
    "response_type": NONEMPTY_STRING,
    "operation_type": {"type": "string", "enum": ["query", "mutation", "subscription"]},
    "arguments": _array({"type": "object", "additionalProperties": True}),
    "source": E2E_EVIDENCE_SOURCE_SCHEMA,
    "sources": _array({"type": "object", "additionalProperties": True}),
    "conflicts": _array({"type": "object", "additionalProperties": True}),
    "merge_classification": {"type": "string", "enum": ["auto_merge", "supplement", "needs_manual_confirmation", "unusable"]},
}, ("id", "kind", "source"))

E2E_DESIGN_RULES_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.design-rules",
    "path": "analysis/design-rules.yaml",
    "document": _object({
        "version": {"const": 1}, "source": {"const": "design"},
        "documents": _array(E2E_INPUT_DOCUMENT_SCHEMA, minimum=1),
        "rules": _array(E2E_DESIGN_RULE_SCHEMA, minimum=1),
        "errors": STRING_LIST,
    }),
}
E2E_PROTOCOL_RULES_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.protocol-rules",
    "path": "analysis/protocol-rules.yaml",
    "document": _object({
        "version": {"const": 1}, "source": {"const": "protocol"},
        "documents": _array(E2E_INPUT_DOCUMENT_SCHEMA, minimum=1),
        "operations": _array(E2E_PROTOCOL_OPERATION_SCHEMA, minimum=1),
        "sources": _array({"type": "object", "additionalProperties": True}),
        "conflicts": _array({"type": "object", "additionalProperties": True}),
        "runtime_sources": _array({"type": "object", "additionalProperties": True}),
        "runtime_errors": STRING_LIST,
        "runtime_classifications": _array({"type": "string", "enum": list(E2E_RUNTIME_CLASSIFICATIONS)}),
        "runtime_failure_details": _array({"type": "object", "additionalProperties": True}),
        "errors": STRING_LIST,
    }, ("version", "source", "documents", "operations", "sources", "conflicts", "errors")),
}
E2E_LOGIC_ITEM_SCHEMA = _object({
    "id": NONEMPTY_STRING, "source": {"const": "design"}, "design_rule_id": NONEMPTY_STRING,
    "title": NONEMPTY_STRING, "participants": STRING_LIST, "protocol_refs": STRING_LIST,
    "status": {"type": "string", "enum": list(E2E_RULE_STATUSES)},
    "context": {"type": "object", "additionalProperties": True},
    "preconditions": STRING_LIST, "states": STRING_LIST, "transitions": STRING_LIST,
    "branches": STRING_LIST, "exceptions": STRING_LIST, "assertions": STRING_LIST,
    "final_result": STRING_LIST, "side_effects": STRING_LIST, "idempotency": STRING_LIST,
    "retries": STRING_LIST, "concurrency": STRING_LIST, "async_behavior": STRING_LIST,
    "async": {"type": "boolean"}, "acceptance_status": {"type": ["string", "null"]},
    "final_status": {"type": ["string", "null"]}, "evidence": _array(E2E_EVIDENCE_SOURCE_SCHEMA, minimum=1),
}, (
    "id", "source", "design_rule_id", "title", "participants", "protocol_refs", "preconditions", "states",
    "transitions", "branches", "exceptions", "assertions", "final_result", "side_effects", "idempotency",
    "retries", "concurrency", "async_behavior", "async", "acceptance_status", "final_status", "evidence",
))
E2E_LOGIC_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.logic",
    "path": "analysis/logic.yaml",
    "document": _object({
        "version": {"const": 1}, "source": {"const": "design"},
        "logic": _array(E2E_LOGIC_ITEM_SCHEMA, minimum=1),
    }),
}
E2E_VALUE_ITEM_SCHEMA = _object({
    "id": NONEMPTY_STRING,
    "source": {"type": "string", "enum": ["config", "fixture", "support-source", "runtime-preparation"]},
    "target": NONEMPTY_STRING,
    "value_ref": NONEMPTY_STRING,
    "evidence": STRING_LIST,
    "cleanup_ref": {"type": ["string", "null"]},
}, ("id", "source", "target", "value_ref"))
E2E_VALUE_RESOLUTION_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.value-resolution",
    "path": "configuration/value-resolution.yaml",
    "document": _object({
        "version": {"const": 1}, "source": {"const": "support-only"},
        "values": _array(E2E_VALUE_ITEM_SCHEMA),
        "business_expectations": {"type": "array", "maxItems": 0},
    }),
}
E2E_INPUT_SUMMARY_SCHEMA = _object({
    "documents": _array(E2E_INPUT_DOCUMENT_SCHEMA, minimum=1),
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "rule_count": {"type": "integer", "minimum": 0},
    "operation_count": {"type": "integer", "minimum": 0},
}, ("documents", "sha256"))
E2E_VERSION_LOCK_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.version-lock",
    "path": "analysis/e2e-test-generator-version.json",
    "document": _object({
        "version": {"const": 1},
        "skill": {"const": "e2e-test-generator"},
        "skill_version": NONEMPTY_STRING,
        "artifact_root": {"const": "analysis"},
        "document_baseline": _object({"git_commit": {"type": ["string", "null"]}}),
        "design": E2E_INPUT_SUMMARY_SCHEMA,
        "protocol": E2E_INPUT_SUMMARY_SCHEMA,
        "source": _array(_object({"repo": NONEMPTY_STRING, "commit": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"}}), unique=True),
        "support": _object({
            "workspace_sha256": {"type": ["string", "null"]},
            "value_resolution_sha256": {"type": ["string", "null"]},
        }),
        "scenario_generation": _object({"version": {"const": 1}, "generated_at": NONEMPTY_STRING}),
        "changes": _object({
            "design_changed": {"type": "boolean"}, "protocol_changed": {"type": "boolean"},
            "source_changed": {"type": "boolean"}, "support_changed": {"type": "boolean"},
            "scenario_data_changed": {"type": "boolean"}, "cleanup_changed": {"type": "boolean"},
        }),
        "scenarios": _object({"data_sha256": NONEMPTY_STRING, "cleanup_sha256": NONEMPTY_STRING}),
    }, (
        "version", "skill", "skill_version", "artifact_root", "document_baseline",
        "design", "protocol", "source", "support", "scenario_generation", "changes", "scenarios",
    )),
}
E2E_SCENARIO_PLAN_SCHEMA: dict[str, Any] = {
    "schema_version": E2E_GATE_SCHEMA_VERSION,
    "contract": "e2e.scenario-plan",
    "path": "analysis/scenario-plan.yaml",
    "document": _object({
        "version": {"const": 1}, "source": {"const": "design"},
        "scenarios": _array(_object({
            "id": NONEMPTY_STRING, "title": NONEMPTY_STRING, "participants": NONEMPTY_STRING_LIST,
            "design_rule_ids": NONEMPTY_STRING_LIST, "protocol_refs": NONEMPTY_STRING_LIST,
            "status": {"type": "string", "enum": list(E2E_SCENARIO_STATUSES)},
            "blockers": STRING_LIST,
            "context": {"type": "object", "additionalProperties": True},
            "required_coverage": _object({
                "preconditions": STRING_LIST, "transitions": STRING_LIST, "branches": STRING_LIST,
                "exceptions": STRING_LIST, "final_result": STRING_LIST, "side_effects": STRING_LIST,
            }),
        }, ("id", "title", "participants", "design_rule_ids", "protocol_refs", "required_coverage")), minimum=1),
    }),
}

BIZ_FLOW_BRANCH_SCHEMA = _object({
    "branch_id": {"type": "string", "minLength": 1},
    "source_file": {"type": "string", "minLength": 1},
    "source_line": {"type": "integer", "minimum": 1},
    "condition": {"type": "string", "minLength": 1},
    "outcomes": _array({"type": "string"}, minimum=1),
    "effects": _array({"type": "string"}),
    "reachability": {"enum": ["reachable", "unreachable", "unknown"]},
    "business_relevant": {"type": ["boolean", "null"]},
})
BIZ_FLOW_PERSISTENCE_SCHEMA = _object({
    "persistence_id": {"type": "string", "minLength": 1},
    "resource_type": {"enum": ["relational_table", "document_collection", "kv_namespace", "search_index", "object_storage", "file_resource", "external_resource"]},
    "resource_name": {"type": "string", "minLength": 1},
    "display_name": {"type": "string"},
    "operation": {"type": "string", "minLength": 1},
    "condition": {"type": ["string", "null"]},
    "fields": _array({"type": "string"}),
    "source_file": {"type": "string", "minLength": 1},
    "source_line": {"type": "integer", "minimum": 1},
})
BIZ_FLOW_UNRESOLVED_SCHEMA = _object({
    "code": {"type": "string", "minLength": 1},
    "critical": {"type": "boolean"},
    "evidence": {"type": "string", "minLength": 1},
    "reason": {"type": "string"},
}, required=("code", "critical", "evidence"))
BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA = _array(_object({
    "file": {"type": "string", "minLength": 1},
    "line": {"type": "integer", "minimum": 1},
    "reason": {"type": "string", "minLength": 1},
}, required=("file", "line", "reason")))
BIZ_FLOW_STEP_SCHEMA = _object({
    "kind": {"enum": ["action", "alt", "else", "opt", "loop", "end"]},
    "text": NONEMPTY_STRING, "source": NONEMPTY_STRING, "participant": NONEMPTY_STRING,
    "branch_ids": _array(NONEMPTY_STRING), "persistence_ids": _array(NONEMPTY_STRING),
    "sender": {"type": "string"}, "response": {"type": "boolean"},
}, required=("kind", "text", "source", "participant"))
BIZ_FLOW_REVIEW_SCHEMA = _object({
    "id": NONEMPTY_STRING, "trigger": NONEMPTY_STRING, "purpose": NONEMPTY_STRING,
    "input": NONEMPTY_STRING, "outcome": NONEMPTY_STRING, "failure": NONEMPTY_STRING,
    "status": {"type": "string", "enum": ["draft", "confirmed"]},
    "confirmed_by": {"type": "string"},
    "steps": _array(BIZ_FLOW_STEP_SCHEMA, minimum=1),
}, ("id", "trigger", "purpose", "input", "outcome", "failure", "status", "confirmed_by", "steps"))
BIZ_FLOW_RESOLUTION_SCHEMA = _object({
    "finding": NONEMPTY_STRING, "resolution": NONEMPTY_STRING, "evidence": _array(NONEMPTY_STRING, minimum=1),
    "path": _array(NONEMPTY_STRING), "controls": _array(NONEMPTY_STRING), "unknowns": _array(NONEMPTY_STRING),
}, ("finding", "resolution", "evidence"))
BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA = _object({
    "entry_id": {"type": "string", "minLength": 1},
    "source_fingerprint": {"type": "string", "minLength": 1},
    "business_name": {"type": "string", "minLength": 1},
    "trigger_summary": {"type": "string", "minLength": 1},
    "source_evidence": BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA,
    "scope_status": {"enum": ["business", "excluded", "待确认"]},
    "exclusion_reason": {"type": ["string", "null"]},
    "participants": _array({"type": "string", "minLength": 1}, minimum=1),
    "calls": _array({"type": "string", "minLength": 1}),
    "branches": _array(_object({**BIZ_FLOW_BRANCH_SCHEMA["properties"],
        "label": {"type": "string", "minLength": 1},
        "outcome_labels": _array({"type": "string", "minLength": 1}),
        "exclusion_reason": {"type": "string"},
    }, required=(*BIZ_FLOW_BRANCH_SCHEMA["required"], "label", "outcome_labels"))),
    "persistence_actions": _array(_object({**BIZ_FLOW_PERSISTENCE_SCHEMA["properties"],
        "operation_label": {"type": "string", "minLength": 1},
    })),
    "async_actions": _array({"type": "string", "minLength": 1}),
    "external_calls": _array({"type": "string", "minLength": 1}),
    "outcomes": _array({"type": "string", "minLength": 1}, minimum=1),
    "unresolved": _array(BIZ_FLOW_UNRESOLVED_SCHEMA),
    "review": BIZ_FLOW_REVIEW_SCHEMA,
    "resolutions": _array(BIZ_FLOW_RESOLUTION_SCHEMA),
    }, required=("entry_id", "source_fingerprint", "business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason", "participants", "calls", "branches", "persistence_actions", "async_actions", "external_calls", "outcomes", "unresolved"))
BIZ_FLOW_RUN_MANIFEST_SCHEMA = _object({
    "schema_version": {"const": BIZ_FLOW_SCHEMA_VERSION},
    "run_id": {"type": "string", "minLength": 1},
    "source_fingerprint": {"type": "string", "minLength": 1},
    "mapping_hash": {"type": "string", "minLength": 1},
    "project_root": {"type": "string", "minLength": 1},
    "docs_root": {"type": "string", "minLength": 1},
    "status": {"enum": ["pending", "running", "reviewed", "success", "failed"]},
    "parallel": {"type": "boolean"}, "degraded": {"type": "boolean"},
    "allow_degraded": {"type": "boolean"},
    "executor": _object({
        "type": {"type": "string", "minLength": 1},
        "adapter": {"type": "string"},
        "probed": {"type": "boolean"},
        "capabilities": {"type": "object", "additionalProperties": {"type": "boolean"}},
    }, ("type", "adapter", "probed", "capabilities")),
    "modules": {"type": "object", "additionalProperties": _object({
        "file": {"type": "string", "minLength": 1},
        "entry_ids": _array({"type": "string", "minLength": 1}, minimum=1, unique=True),
    })},
    "tasks": _array(_object({
        "run_id": {"type": "string"}, "task_id": {"type": "string"},
        "parent_task_id": {"type": ["string", "null"]},
        "role": {"enum": ["coordinator", "module", "entry"]},
        "module_id": {"type": ["string", "null"]}, "entry_id": {"type": ["string", "null"]},
        "batch_id": {"type": ["string", "null"]},
        "status": {"enum": ["pending", "running", "success", "failed"]},
        "started_at": {"type": ["string", "null"]}, "finished_at": {"type": ["string", "null"]},
        "result_hash": {"type": ["string", "null"]}, "error": {"type": ["string", "null"]},
    }), minimum=1),
    "events": _array(_object({
        "run_id": {"type": "string"}, "sequence": {"type": "integer", "minimum": 1},
        "kind": {"enum": ["dispatch_batch", "join_batch", "started", "ready", "success", "failed", "write", "write_denied", "reused", "process_finished"]},
        "task_id": {"type": "string"}, "timestamp": {"type": "string"},
        "batch_id": {"type": ["string", "null"]},
        "task_ids": _array({"type": "string"}),
        "path": {"type": ["string", "null"]}, "result_hash": {"type": ["string", "null"]},
    })),
    "inventories": {"type": "object", "additionalProperties": _object({
        "entry_id": {"type": "string"}, "source_fingerprint": {"type": "string"},
        "business_name": {"type": "string"}, "trigger_summary": {"type": "string"},
        "source_evidence": BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA,
        "scope_status": {"enum": ["business", "excluded", "待确认"]},
        "exclusion_reason": {"type": ["string", "null"]},
        "participants": _array({"type": "string"}), "calls": _array({"type": "string"}),
        "async_actions": _array({"type": "string"}), "external_calls": _array({"type": "string"}),
        "outcomes": _array({"type": "string"}),
        "source_branch_inventory": _array(BIZ_FLOW_BRANCH_SCHEMA),
        "persistence_inventory": _array(BIZ_FLOW_PERSISTENCE_SCHEMA),
        "unresolved": _array(BIZ_FLOW_UNRESOLVED_SCHEMA),
    }, required=("entry_id", "source_fingerprint", "business_name", "trigger_summary", "source_evidence", "scope_status", "exclusion_reason", "participants", "calls", "async_actions", "external_calls", "outcomes", "source_branch_inventory", "persistence_inventory", "unresolved"))},
    "entry_analyses": {"type": "object", "additionalProperties": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA},
    "agent_resolutions": _array(BIZ_FLOW_RESOLUTION_SCHEMA),
    "module_results": {"type": "object", "additionalProperties": _object({
        "module_id": {"type": "string", "minLength": 1},
        "entry_analyses": {"type": "object", "additionalProperties": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA},
        "markdown": {"type": "string", "minLength": 1},
    })},
    "document_hashes": {"type": "object", "additionalProperties": {"type": "string"}},
    "report": _object({
        "module_count": {"type": "integer", "minimum": 0},
        "entry_count": {"type": "integer", "minimum": 0},
        "module_tasks": {"type": "integer", "minimum": 0},
        "entry_tasks": {"type": "integer", "minimum": 0},
        "parallel": {"type": "boolean"},
        "degraded": {"type": "boolean"},
        "branch_coverage": {"type": "number", "minimum": 0, "maximum": 1},
        "persistence_coverage": {"type": "number", "minimum": 0, "maximum": 1},
        "critical_unresolved": {"type": "integer", "minimum": 0},
        "stable": {"type": "boolean"},
        # Final generation reports carry the complete readable-entry audit.
        # These fields are optional while a run is still in progress so the
        # initial manifest remains a valid progress record.
        "module_entry_lists": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
        "business_name_unresolved_count": {"type": "integer", "minimum": 0},
        "excluded_business_name_unresolved_count": {"type": "integer", "minimum": 0},
        "excluded_entry_details": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "entry_reconciliation": {"type": "object", "additionalProperties": True},
        "adapter_evidence_coverage": {"type": "object", "additionalProperties": True},
        "git_commit": {"type": "string"},
        "verification_runs": {"type": "integer", "minimum": 0},
    }, required=(
        "module_count", "entry_count", "module_tasks", "entry_tasks", "parallel", "degraded",
        "branch_coverage", "persistence_coverage", "critical_unresolved", "stable",
    )),
    "errors": _array({"type": "string"}),
}, (
    "schema_version", "run_id", "source_fingerprint", "mapping_hash", "project_root", "docs_root",
    "status", "parallel", "degraded", "allow_degraded", "modules", "tasks", "events", "inventories",
    "entry_analyses", "module_results", "document_hashes", "report", "errors",
))

# 3.x host handoff contract. Legacy run manifests remain separate and are
# rejected by the new prepare/collect lifecycle.
BIZ_FLOW_HANDOFF_SCHEMA = _object({
    "protocol_version": {"const": "3.0"},
    "run_id": NONEMPTY_STRING, "project_root": NONEMPTY_STRING,
    "source_fingerprint": NONEMPTY_STRING, "mapping_hash": NONEMPTY_STRING,
    "mode": {"enum": ["native", "serial", None]},
    "status": {"enum": ["prepared", "awaiting_serial_choice", "analyzing", "collected", "accepted", "failed", "cancelled"]},
    "parallel": {"type": "boolean"}, "degraded": {"type": "boolean"},
    "completed_child_agents": {"type": "integer", "minimum": 0},
    "tasks": _array(_object({"task_id": NONEMPTY_STRING, "entry_id": NONEMPTY_STRING, "module_id": NONEMPTY_STRING}, ("task_id", "entry_id", "module_id"), additional=True)),
}, ("protocol_version", "run_id", "project_root", "source_fingerprint", "mapping_hash", "mode", "status", "parallel", "degraded", "completed_child_agents", "tasks"), additional=True)

BIZ_FLOW_ERROR_SCHEMA = _object({
    "code": NONEMPTY_STRING,
    "condition": NONEMPTY_STRING,
    "source": NONEMPTY_STRING,
    "capture_boundary": NONEMPTY_STRING,
    "propagation": NONEMPTY_STRING,
    "consequence": NONEMPTY_STRING,
    "phase": NONEMPTY_STRING,
    "recovery": NONEMPTY_STRING,
}, ("code", "condition", "source", "capture_boundary", "propagation", "consequence", "phase", "recovery"))
BIZ_FLOW_BEHAVIOR_SCHEMA = _object({
    "kind": NONEMPTY_STRING, "statement": NONEMPTY_STRING, "source": NONEMPTY_STRING,
})
BIZ_FLOW_DISCOVERY_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
        "source_fingerprint": NONEMPTY_STRING,
        "effective_git": _object({
            "commit": NONEMPTY_STRING, "branch": NONEMPTY_STRING, "workspace_dirty": {"type": "boolean"},
            "includes_uncommitted_changes": {"type": "boolean"},
        }),
        "languages": STRING_LIST,
        "frameworks": STRING_LIST,
        "source_files": STRING_LIST,
        "entries": _array(_object({
            "id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "identifier": NONEMPTY_STRING,
            "handler": NONEMPTY_STRING, "source": NONEMPTY_STRING, "suggested_module": NONEMPTY_STRING,
            "business_name": NONEMPTY_STRING, "trigger_summary": NONEMPTY_STRING,
            "source_evidence": _array(_object({"file": NONEMPTY_STRING, "line": {"type": "integer", "minimum": 1}, "reason": NONEMPTY_STRING}, ("file", "line", "reason")), minimum=1),
            "scope_status": {"enum": ["business", "excluded", "待确认"]},
            "exclusion_reason": {"type": ["string", "null"]},
            "non_business_candidate": {"type": "boolean"}, "core_capabilities": STRING_LIST,
            "errors": _array(BIZ_FLOW_ERROR_SCHEMA),
        })),
        "candidate_entry_count": {"type": "integer", "minimum": 0},
        "confirmed_binding_count": {"type": "integer", "minimum": 0},
        "confirmed_handler_count": {"type": "integer", "minimum": 0},
        "unresolved": STRING_LIST,
        "module_suggestions": _array(_object({
            "name": NONEMPTY_STRING, "entry_ids": STRING_LIST, "basis": NONEMPTY_STRING,
        }, ("name", "entry_ids", "basis"))),
    }
)

BIZ_FLOW_MODULE_MAP_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
        "source_fingerprint": NONEMPTY_STRING,
        "effective_git": NONEMPTY_STRING,
        "confirmed": {"type": "boolean"},
        "entry_reviews": _array(BIZ_FLOW_REVIEW_SCHEMA),
        "migrations": _array(_object({
            "from": NONEMPTY_STRING, "to": NONEMPTY_STRING, "reason": NONEMPTY_STRING,
        })),
        "resolutions": _array(_object({
            "finding": NONEMPTY_STRING, "resolution": NONEMPTY_STRING, "evidence": NONEMPTY_STRING_LIST,
            "path": STRING_LIST, "controls": STRING_LIST, "unknowns": STRING_LIST,
        }, ("finding", "resolution", "evidence"))),
        "entry_overrides": _array(_object({
            "id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "identifier": NONEMPTY_STRING,
            "handler": NONEMPTY_STRING, "caller": NONEMPTY_STRING,
            "input_summary": NONEMPTY_STRING, "title": NONEMPTY_STRING, "core_capabilities": STRING_LIST,
            "errors": _array(BIZ_FLOW_ERROR_SCHEMA), "behaviors": _array(BIZ_FLOW_BEHAVIOR_SCHEMA),
        }, ("id",))),
        "additional_entries": _array(_object({
            "id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "identifier": NONEMPTY_STRING,
            "handler": NONEMPTY_STRING, "source": NONEMPTY_STRING, "caller": NONEMPTY_STRING,
            "input_summary": NONEMPTY_STRING, "core_capabilities": STRING_LIST,
            "errors": _array(BIZ_FLOW_ERROR_SCHEMA), "behaviors": _array(BIZ_FLOW_BEHAVIOR_SCHEMA),
        })),
        "exclusions": _array(_object({
            "candidate": NONEMPTY_STRING, "reason": NONEMPTY_STRING, "evidence": NONEMPTY_STRING_LIST,
            "module": NONEMPTY_STRING,
        }, required=("candidate", "reason", "evidence"))),
        "modules": _array(_object({
            "name": NONEMPTY_STRING, "display_name": NONEMPTY_STRING, "rationale": NONEMPTY_STRING,
            "file": NONEMPTY_STRING, "responsibility": NONEMPTY_STRING, "objects": STRING_LIST,
            "partners": STRING_LIST, "questions": STRING_LIST, "entry_ids": STRING_LIST,
        })),
    }
)

BIZ_FLOW_INDEX_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
        "source_fingerprint": NONEMPTY_STRING,
        "effective_git": _object({
            "commit": NONEMPTY_STRING,
            "branch": NONEMPTY_STRING,
            "workspace_dirty": {"type": "boolean"},
            "includes_uncommitted_changes": {"type": "boolean"},
        }),
        "comparison": NONEMPTY_STRING,
        "old_commit": {"type": ["string", "null"]},
        "languages": STRING_LIST,
        "frameworks": STRING_LIST,
        "modules": _array(_object({
            "name": NONEMPTY_STRING, "file": NONEMPTY_STRING, "rationale": NONEMPTY_STRING,
            "entry_ids": STRING_LIST,
        })),
        "migrations": BIZ_FLOW_MODULE_MAP_SCHEMA["properties"]["migrations"],
        "entries": _array(_object({
            "id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "identifier": NONEMPTY_STRING,
            "handler": NONEMPTY_STRING, "module": NONEMPTY_STRING, "source": NONEMPTY_STRING,
            "business_name": NONEMPTY_STRING, "trigger_summary": NONEMPTY_STRING,
            "source_evidence": _array(_object({"file": NONEMPTY_STRING, "line": {"type": "integer", "minimum": 1}, "reason": NONEMPTY_STRING}, ("file", "line", "reason")), minimum=1),
            "scope_status": {"enum": ["business", "excluded", "待确认"]},
            "exclusion_reason": {"type": ["string", "null"]},
            "caller": NONEMPTY_STRING, "input_summary": NONEMPTY_STRING, "core_capabilities": STRING_LIST,
            "error_codes": STRING_LIST,
            "errors": _array(BIZ_FLOW_ERROR_SCHEMA),
            "behaviors": _array(BIZ_FLOW_BEHAVIOR_SCHEMA),
            "review": BIZ_FLOW_REVIEW_SCHEMA,
        })),
        "counts": _object({
            "entries": {"type": "integer", "minimum": 0},
            "modules": {"type": "integer", "minimum": 0},
            "error_codes": {"type": "integer", "minimum": 0},
            "by_type": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
        }),
        "unresolved": STRING_LIST,
    }
)

BIZ_FLOW_REPORT_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
        "source_fingerprint": NONEMPTY_STRING,
        "effective_git": BIZ_FLOW_INDEX_SCHEMA["properties"]["effective_git"],
        "project": NONEMPTY_STRING,
        "scope": {"type": ["string", "null"]},
        "languages": STRING_LIST,
        "frameworks": STRING_LIST,
        "module_count": {"type": "integer", "minimum": 0},
        "document_count": {"type": "integer", "minimum": 0},
        "url_entry_count": {"type": "integer", "minimum": 0},
        "scheduled_task_count": {"type": "integer", "minimum": 0},
        "message_consumer_count": {"type": "integer", "minimum": 0},
        "other_entry_count": {"type": "integer", "minimum": 0},
        "active_error_code_count": {"type": "integer", "minimum": 0},
        "entry_count": {"type": "integer", "minimum": 0},
        "candidate_entry_count": {"type": "integer", "minimum": 0},
        "confirmed_binding_count": {"type": "integer", "minimum": 0},
        "confirmed_handler_count": {"type": "integer", "minimum": 0},
        "completed_entry_count": {"type": "integer", "minimum": 0},
        "excluded_entry_count": {"type": "integer", "minimum": 0},
        "pending_review_count": {"type": "integer", "minimum": 0},
        "added_entries": STRING_LIST,
        "updated_entries": STRING_LIST,
        "deleted_entries": STRING_LIST,
        "version_only_documents": STRING_LIST,
        "business_changed_documents": STRING_LIST,
        "comparison": NONEMPTY_STRING,
        "comparison_error": {"type": ["string", "null"]},
        "exclusions": STRING_LIST,
        "unresolved": STRING_LIST,
        "module_entry_lists": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
        "business_name_unresolved_count": {"type": "integer", "minimum": 0},
        "excluded_business_name_unresolved_count": {"type": "integer", "minimum": 0},
        "excluded_entry_details": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "entry_reconciliation": {"type": "object", "additionalProperties": True},
        "adapter_evidence_coverage": {"type": "object", "additionalProperties": True},
        "coverage": _object({
            "code_entry_count": {"type": "integer", "minimum": 0},
            "documented_entry_count": {"type": "integer", "minimum": 0},
            "missing_entries": STRING_LIST,
            "stale_entries": STRING_LIST,
            "code_error_code_count": {"type": "integer", "minimum": 0},
            "documented_error_code_count": {"type": "integer", "minimum": 0},
            "missing_error_codes": STRING_LIST,
            "stale_error_codes": STRING_LIST,
            "missing_error_evidence": STRING_LIST,
            "stale_error_evidence": STRING_LIST,
            "unique_module_count": {"type": "integer", "minimum": 0},
            "markdown_document_count": {"type": "integer", "minimum": 0},
            "markdown_entry_count": {"type": "integer", "minimum": 0},
            "markdown_missing_documents": STRING_LIST,
            "markdown_missing_entries": STRING_LIST,
            "markdown_stale_entries": STRING_LIST,
            "markdown_missing_error_codes": STRING_LIST,
            "markdown_missing_error_evidence": STRING_LIST,
            "markdown_stale_error_evidence": STRING_LIST,
            "markdown_diagram_mismatches": STRING_LIST,
            "markdown_fact_mismatches": STRING_LIST,
            "markdown_version_mismatches": STRING_LIST,
        }),
        "index_path": NONEMPTY_STRING,
    }
)

# Auxiliary artifacts are deliberately small contracts rather than opaque JSON
# blobs.  They let ``check`` detect stale or truncated supporting evidence too.
BIZ_FLOW_OWNERSHIP_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING,
    "confirmed": {"type": "boolean"},
    "entries": _array(_object({
        "id": NONEMPTY_STRING, "module": NONEMPTY_STRING, "file": NONEMPTY_STRING,
    })),
})

BIZ_FLOW_MIGRATIONS_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING,
    "migrations": BIZ_FLOW_MODULE_MAP_SCHEMA["properties"]["migrations"],
})

BIZ_FLOW_COMPARISON_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING,
    "comparison": NONEMPTY_STRING,
    "entry_alignment": _object({
        "added": STRING_LIST, "updated": STRING_LIST, "deleted": STRING_LIST,
    }),
    "version_only_documents": STRING_LIST,
    "business_changed_documents": STRING_LIST,
    "changed_paths": STRING_LIST,
    "comparison_error": {"type": ["string", "null"]},
    "fact_diffs": _array(_object({"id": NONEMPTY_STRING, "changes": STRING_LIST})),
    "semantic_diffs": _array(_object({
        "id": NONEMPTY_STRING,
        "category": NONEMPTY_STRING,
        "status": {"type": "string", "enum": ["added", "missing", "contradictory", "unknown"]},
        "old": STRING_LIST,
        "new": STRING_LIST,
        "reason": NONEMPTY_STRING,
    })),
})

BIZ_FLOW_EVIDENCE_CACHE_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING,
    "root": NONEMPTY_STRING,
    "git": {"type": "object", "additionalProperties": True},
    "languages": STRING_LIST,
    "frameworks": STRING_LIST,
    "files": STRING_LIST,
    "source_lines": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
    "unresolved": STRING_LIST,
    "exclusions": STRING_LIST,
    "candidate_entry_count": {"type": "integer", "minimum": 0},
    "confirmed_binding_count": {"type": "integer", "minimum": 0},
    "confirmed_handler_count": {"type": "integer", "minimum": 0},
    "entries": {"type": "object", "additionalProperties": True},
})

BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING,
    "nodes": _array(_object({"entry": NONEMPTY_STRING, "functions": STRING_LIST})),
    "shared_sources": STRING_LIST,
})

BIZ_FLOW_PROGRESS_SCHEMA: dict[str, Any] = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "run_id": NONEMPTY_STRING,
    "run_handle": NONEMPTY_STRING,
    "phase": NONEMPTY_STRING,
    "stage": NONEMPTY_STRING,
    "status": {"type": "string", "enum": ["running", "completed", "failed"]},
    "source_fingerprint": {"type": "string"},
    "updated_at": NONEMPTY_STRING,
    "error": {"type": ["string", "null"]},
    "failure_log": {"type": ["string", "null"]},
    "resumed": {"type": "boolean"},
    "cache_entries": {"type": "integer", "minimum": 0},
})

BIZ_FLOW_DISCOVERY_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_DISCOVERY_SCHEMA["contract"] = "biz-flow.discovery"
BIZ_FLOW_MODULE_MAP_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_MODULE_MAP_SCHEMA["contract"] = "biz-flow.module-map"
BIZ_FLOW_INDEX_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_INDEX_SCHEMA["contract"] = "biz-flow.index"
BIZ_FLOW_REPORT_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_REPORT_SCHEMA["contract"] = "biz-flow.report"
for _schema in (
    BIZ_FLOW_OWNERSHIP_SCHEMA,
    BIZ_FLOW_MIGRATIONS_SCHEMA,
    BIZ_FLOW_COMPARISON_SCHEMA,
    BIZ_FLOW_EVIDENCE_CACHE_SCHEMA,
    BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA,
    BIZ_FLOW_PROGRESS_SCHEMA,
):
    _schema["schema_version"] = BIZ_FLOW_SCHEMA_VERSION
BIZ_FLOW_OWNERSHIP_SCHEMA["contract"] = "biz-flow.ownership"
BIZ_FLOW_MIGRATIONS_SCHEMA["contract"] = "biz-flow.migrations"
BIZ_FLOW_COMPARISON_SCHEMA["contract"] = "biz-flow.comparison"
BIZ_FLOW_EVIDENCE_CACHE_SCHEMA["contract"] = "biz-flow.evidence-cache"
BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA["contract"] = "biz-flow.dependency-graph"
BIZ_FLOW_PROGRESS_SCHEMA["contract"] = "biz-flow.progress"

CONTRACT_SCHEMAS = {
    "e2e.document-baseline": E2E_DOCUMENT_BASELINE_SCHEMA,
    "e2e.document-state": E2E_DOCUMENT_STATE_SCHEMA,
    "bru-api.design-rules": BRU_API_DESIGN_RULES_SCHEMA,
    "bru-api.design-generation-report": BRU_API_DESIGN_REPORT_SCHEMA,
    "bru-api.logic": BRU_API_LOGIC_SCHEMA,
    "bru-api.value-resolution": BRU_API_VALUE_RESOLUTION_SCHEMA,
    "bru-api.version-lock": BRU_API_VERSION_LOCK_SCHEMA,
    "biz-flow.discovery": BIZ_FLOW_DISCOVERY_SCHEMA,
    "biz-flow.run-manifest": BIZ_FLOW_RUN_MANIFEST_SCHEMA,
    "biz-flow.handoff": BIZ_FLOW_HANDOFF_SCHEMA,
    "biz-flow.entry-analysis": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA,
    "biz-flow.module-map": BIZ_FLOW_MODULE_MAP_SCHEMA,
    "biz-flow.index": BIZ_FLOW_INDEX_SCHEMA,
    "biz-flow.report": BIZ_FLOW_REPORT_SCHEMA,
    "biz-flow.ownership": BIZ_FLOW_OWNERSHIP_SCHEMA,
    "biz-flow.migrations": BIZ_FLOW_MIGRATIONS_SCHEMA,
    "biz-flow.comparison": BIZ_FLOW_COMPARISON_SCHEMA,
    "biz-flow.evidence-cache": BIZ_FLOW_EVIDENCE_CACHE_SCHEMA,
    "biz-flow.dependency-graph": BIZ_FLOW_DEPENDENCY_GRAPH_SCHEMA,
    "biz-flow.progress": BIZ_FLOW_PROGRESS_SCHEMA,
    "e2e.scenario": SCENARIO_SCHEMA,
    "e2e.workspace": WORKSPACE_SCHEMA,
    "e2e.config": CONFIG_SCHEMA,
    "e2e.report": REPORT_SCHEMA,
    "e2e.design-rules": E2E_DESIGN_RULES_SCHEMA,
    "e2e.protocol-rules": E2E_PROTOCOL_RULES_SCHEMA,
    "e2e.logic": E2E_LOGIC_SCHEMA,
    "e2e.scenario-plan": E2E_SCENARIO_PLAN_SCHEMA,
    "e2e.value-resolution": E2E_VALUE_RESOLUTION_SCHEMA,
    "e2e.version-lock": E2E_VERSION_LOCK_SCHEMA,
}


def get_schema(scope: str | None = None) -> dict[str, Any]:
    if scope is None:
        return {
            "domains": {
                "bru-api": {
                    "schema_version": BRU_API_SCHEMA_VERSION,
                    "commands": [name.split(".", 1)[1] for name in COMMAND_SCHEMAS if name.startswith("bru-api.")],
                },
                "e2e": {
                    "schema_version": E2E_GATE_SCHEMA_VERSION,
                    "commands": [name.split(".", 1)[1] for name in COMMAND_SCHEMAS if name.startswith("e2e.")],
                },
                "biz-flow": {
                    "schema_version": BIZ_FLOW_SCHEMA_VERSION,
                    "commands": [name.split(".", 1)[1] for name in COMMAND_SCHEMAS if name.startswith("biz-flow.")],
                },
            }
        }
    if scope in CONTRACT_SCHEMAS:
        return deepcopy(CONTRACT_SCHEMAS[scope])
    if scope not in COMMAND_SCHEMAS:
        raise KeyError(scope)
    schema = deepcopy(COMMAND_SCHEMAS[scope])
    if scope.startswith("bru-api."):
        schema["schema_version"] = BRU_API_SCHEMA_VERSION
    elif scope.startswith("biz-flow."):
        schema["schema_version"] = BIZ_FLOW_SCHEMA_VERSION
    else:
        schema["schema_version"] = E2E_GATE_SCHEMA_VERSION
    return schema


def validate_schema(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """Validate the JSON Schema subset emitted by this module."""

    errors: list[str] = []
    if not schema:
        return errors
    if "anyOf" in schema:
        if not any(not validate_schema(branch, value, path) for branch in schema["anyOf"]):
            errors.append(f"{path}: does not match any allowed schema")
        return errors
    if "oneOf" in schema:
        matches = sum(not validate_schema(branch, value, path) for branch in schema["oneOf"])
        if matches != 1:
            errors.append(f"{path}: must match exactly one allowed schema")
        return errors

    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected_types and not any(type_checks[name](value) for name in expected_types):
        return [f"{path}: expected {' or '.join(expected_types)}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the allowed enum")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required property {name}")
        for name, child in value.items():
            if name in properties:
                errors.extend(validate_schema(properties[name], child, f"{path}.{name}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {name}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate_schema(schema["additionalProperties"], child, f"{path}.{name}"))
        if len(value) > schema.get("maxProperties", len(value)):
            errors.append(f"{path}: too many properties")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{path}: too many items")
        if schema.get("uniqueItems") and any(item in value[:index] for index, item in enumerate(value)):
            errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema(item_schema, item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is too short")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: string does not match required pattern")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: number is above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: number must be greater than the exclusive minimum")
    return errors
