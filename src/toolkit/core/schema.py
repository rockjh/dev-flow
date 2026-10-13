"""Scoped public command and domain contracts; no runtime plugin discovery."""

from __future__ import annotations

import re
import json
from pathlib import Path
from copy import deepcopy
from typing import Any


BRU_API_SCHEMA_VERSION = "7"
BIZ_FLOW_SCHEMA_VERSION = "6"
E2E_GATE_SCHEMA_VERSION = "11"
SEQUENCE_SCHEMA_VERSION = "4"
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
    "bru-api.worker-start": {"options": {"--qa-root": "path", "--module": "string[]", "--delegate": "boolean",
        "--execution-mode": ["native", "serial"], "--execution-approval": "string",
        "--stage": ["generation", "materialization", "pre-execution", "post-execution"]}, "required": ["--module"]},
    "bru-api.worker-check": {
        "options": {
            "--qa-root": "path",
            "--module": "string",
            "--run-id": "uuid-hex", "--receipt": "path",
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
        "options": {"--project": "path", "--docs-root": "path", "--commit": "string", "--run-id": "string", "--stage": ["entries", "flows"]}
    },
    "biz-flow.verify": {"options": {"--project": "path", "--docs-root": "path", "--run-id": "string"}},
    "biz-flow.prepare": {"options": {"--commit": "string", "--project": "path", "--docs-root": "path", "--module": "string", "--purpose": "string", "--confirm": "boolean", "--resume": "string"}},
    "biz-flow.collect": {"options": {"--project": "path", "--docs-root": "path", "--run-id": "string", "--results": "path"}},
    "biz-flow.accept": {"options": {"--project": "path", "--docs-root": "path", "--run-id": "string"}},
    "biz-flow.clean": {"options": {"--run-id": "string", "--all": "boolean"}},
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
                "host_task": _object({"run_id": NONEMPTY_STRING, "task_id": NONEMPTY_STRING}),
                "serial_approval": _object({"reference": NONEMPTY_STRING, "scope": NONEMPTY_STRING}),
            }, ("mode", "owner", "write_scope", "degradation_reason")
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
                    "data_ref": {"type": "string", "pattern": "^业务数据\\.json#/"},
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
    "path": "scenarios/<scenario>/场景定义.yaml",
    "required": list(SCENARIO_REQUIRED),
    "status": list(E2E_SCENARIO_STATUSES),
    "generation_mode": list(E2E_GENERATION_MODES),
    "control_names": list(E2E_CONTROL_NAMES),
    "control_status": list(E2E_CONTROL_STATUSES),
    "step_status": list(E2E_STEP_STATUSES),
    "candidate_kinds": list(E2E_CANDIDATE_KINDS),
    "candidate_status": list(E2E_CANDIDATE_STATUSES),
    "document": SCENARIO_DOCUMENT_SCHEMA,
    "required_sibling_artifacts": ["业务数据.json", "业务流程图.md", "test_<scenario>.py"],
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
        "scenarios/<scenario>/业务数据.json": {
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

BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA = _array(_object({
    "file": NONEMPTY_STRING, "line": {"type": "integer", "minimum": 1}, "reason": NONEMPTY_STRING,
}))
BIZ_FLOW_HASH_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
BIZ_FLOW_PROOF_SCHEMA = _object({
    "evidence_id": NONEMPTY_STRING, "file": NONEMPTY_STRING,
    "line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1},
    "content_hash": BIZ_FLOW_HASH_SCHEMA, "declaration_id": NONEMPTY_STRING,
})
BIZ_FLOW_FACT_SCHEMA = _object({
    "fact_id": NONEMPTY_STRING, "type": NONEMPTY_STRING, "context_id": NONEMPTY_STRING,
    "phase": {"enum": ["entry", "background"]}, "conditions": _array(NONEMPTY_STRING),
    "evidence_refs": _array(NONEMPTY_STRING, minimum=1),
    "details": {"type": "object", "additionalProperties": True},
})
BIZ_FLOW_OUTCOME_SCHEMA = _object({
    **BIZ_FLOW_FACT_SCHEMA["properties"],
    "type": {"enum": ["entry_response", "normal_completion", "method_return", "background_result", "write_attempt",
        "state_change", "async_submission", "async_rejection", "throw", "raise", "break", "continue"]},
    "details": _object({
        "expression": {"type": "string"}, "observed_by_entry": {"type": "boolean"},
        "meaning": NONEMPTY_STRING, "guarantee": {"const": "conditional static fact"},
        "boundary": {"enum": ["entry", "internal"]}, "propagation": NONEMPTY_STRING, "caught_by": NONEMPTY_STRING,
        "possible_handlers": _array(_object({"branch_id": NONEMPTY_STRING, "handlers": STRING_LIST})),
    }, ("expression", "observed_by_entry", "meaning", "guarantee")),
})
BIZ_FLOW_GAP_SCHEMA = _object({
    "finding_id": NONEMPTY_STRING, "code": NONEMPTY_STRING, "critical": {"type": "boolean"},
    "target_id": NONEMPTY_STRING, "question": NONEMPTY_STRING,
    "evidence_refs": _array(NONEMPTY_STRING, minimum=1), "candidates": _array(NONEMPTY_STRING),
    "controls": _array(NONEMPTY_STRING),
})
BIZ_FLOW_ENTRY_FACTS_SCHEMA = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)}, "entry_id": NONEMPTY_STRING,
    "source_commit": NONEMPTY_STRING, "source_fingerprint": BIZ_FLOW_HASH_SCHEMA, "adapter_version": NONEMPTY_STRING,
    "adapter_dependencies": {"type": "object", "additionalProperties": NONEMPTY_STRING},
    "registration": _object({**{k: {"type": "string"} for k in ("kind", "identifier", "handler", "business_name", "trigger_summary")},
        "source_evidence": BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA}),
    "participants": _array(_object({"participant_id": NONEMPTY_STRING, "identity": NONEMPTY_STRING,
        "evidence_refs": _array(NONEMPTY_STRING, minimum=1),
        "role": {"enum": ["caller", "service", "storage", "external", "executor"]}})),
    "sources": _array(BIZ_FLOW_PROOF_SCHEMA),
    **{k: _array(BIZ_FLOW_FACT_SCHEMA) for k in ("calls", "branches", "persistence_actions", "effects", "outcomes")},
    "outcomes": _array(BIZ_FLOW_OUTCOME_SCHEMA),
    "flow": _array(_object({
        "step_id": NONEMPTY_STRING, "kind": {"enum": ["call", "return", "control_start", "control_else", "control_end",
            "persistence", "submit", "outcome", "state_change", "transaction_start", "transaction_end"]},
        "fact_id": NONEMPTY_STRING, "context_id": NONEMPTY_STRING, "phase": {"enum": ["entry", "background"]},
        "controls": _array(NONEMPTY_STRING),
        "arm": {"type": "string"},
    })),
    "gaps": _array(BIZ_FLOW_GAP_SCHEMA),
    "coverage": _object({"scope": {"const": "selected-entry-reachable"}, "complete": {"type": "boolean"},
        "persistence": {"enum": ["proven", "none_in_verified_scope", "unknown"]}, "limitations": _array(NONEMPTY_STRING)}),
})
BIZ_FLOW_ANNOTATION_SCHEMA = _object({
    "target_id": NONEMPTY_STRING, "text": {"type": "string", "minLength": 1, "maxLength": 200},
    "evidence_refs": _array(NONEMPTY_STRING, minimum=1),
})
BIZ_FLOW_REVIEW_SCHEMA = _object({
    k: _object({"text": {"type": "string", "minLength": 1, "maxLength": 200},
                "evidence_refs": _array(NONEMPTY_STRING, minimum=1)})
    for k in ("trigger", "purpose", "input", "outcome", "failure")
})
BIZ_FLOW_RESOLUTION_SCHEMA = _object({
    "finding": {"type": "string", "pattern": "^(OUTCOME_UNRESOLVED|PERSISTENCE_OBJECT_UNRESOLVED|BRANCH_LINE_UNRESOLVED)\\|.+$"},
    "classification": {"enum": ["normal_completion", "non_persistence", "non_business_decision"]},
    "evidence": _array(BIZ_FLOW_PROOF_SCHEMA, minimum=1), "path": _array(NONEMPTY_STRING, minimum=1),
    "controls": _array(NONEMPTY_STRING, minimum=1), "unknowns": {"type": "array", "maxItems": 0},
    "explanation": {"type": "string", "minLength": 1, "maxLength": 200},
})
BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA = _object({
    "entry_id": NONEMPTY_STRING, "source_fingerprint": BIZ_FLOW_HASH_SCHEMA, "facts_hash": BIZ_FLOW_HASH_SCHEMA,
    "review": BIZ_FLOW_REVIEW_SCHEMA, "annotations": _array(BIZ_FLOW_ANNOTATION_SCHEMA),
    "resolutions": _array(BIZ_FLOW_RESOLUTION_SCHEMA),
}, ("entry_id", "source_fingerprint", "facts_hash", "review", "annotations"))
BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA = _object({
    **{k: NONEMPTY_STRING for k in ("run_id", "task_id", "entry_id", "source_fingerprint", "facts_hash", "target_id")},
    "source_fingerprint": BIZ_FLOW_HASH_SCHEMA, "facts_hash": BIZ_FLOW_HASH_SCHEMA,
    "finding_id": {"type": ["string", "null"]},
    "type": {"enum": ["call_binding", "callback_binding", "behavior_classification", "resource_mapping", "branch_classification", "outcome_fact"]},
    "path": _array(NONEMPTY_STRING, minimum=1), "controls": _array(NONEMPTY_STRING),
    "sources": _array(BIZ_FLOW_PROOF_SCHEMA, minimum=1),
    "binding": _object({"declaration_id": NONEMPTY_STRING, "receiver_type": {"type": "string"},
        "parameter_types": _array(NONEMPTY_STRING), "classification": {"type": "string"}}),
})
BIZ_FLOW_ENTRY_RESULT_SCHEMA = {"oneOf": [
    _object({"kind": {"const": "analysis"}, "analysis": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA}),
    _object({"kind": {"const": "evidence_request"}, "evidence_requests": _array(BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA, minimum=1)}),
]}

NULLABLE_STRING = {"type": ["string", "null"]}
HOST_ACTIVE_OBSERVATION_SCHEMA = _object({
    "observed_at": NONEMPTY_STRING,
    "time_source": {"enum": ["host", "coordinator_observed"]},
    "tool_reference": NONEMPTY_STRING,
    "active_task_ids": _array(NONEMPTY_STRING, minimum=2),
})
BIZ_FLOW_TASK_SCHEMA = _object({
    "task_id": NONEMPTY_STRING, "entry_id": NONEMPTY_STRING, "module_id": NONEMPTY_STRING,
    "input_hash": NONEMPTY_STRING, "task_hash": NONEMPTY_STRING,
    "source_commit": NONEMPTY_STRING, "source_snapshot": NONEMPTY_STRING,
    "snapshot_hash": NONEMPTY_STRING, "result_path": NONEMPTY_STRING,
    "registration_evidence": BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA,
    "reachable_analysis": _array(NONEMPTY_STRING), "unresolved_questions": {"type": "array"},
    "permissions": _object({"read_only_source": {"const": True},
        "write_scope": NONEMPTY_STRING, "enforcement": {"const": "coordinator_scope_check"}}),
    "result_schema": {"const": "biz-flow.entry-result"}, "status": {"const": "pending"},
})
BIZ_FLOW_RECEIPT_SCHEMA = _object({
    "run_id": NONEMPTY_STRING, "task_id": NONEMPTY_STRING, "batch_id": NONEMPTY_STRING,
    "task_hash": NONEMPTY_STRING, "input_hash": NONEMPTY_STRING,
    "child_agent_id": {"anyOf": [NONEMPTY_STRING, {"type": "null"}]},
    "attempt": {"type": "integer", "minimum": 1},
    "status": {"enum": ["success", "failed", "interrupted", "timed_out", "evidence_missing", "spawn_failed"]},
    "result_hash": NULLABLE_STRING, "error": NULLABLE_STRING,
    "record_origin": {"enum": ["host-attested", "fixture"]},
    "tool_references": _array(NONEMPTY_STRING, minimum=1),
    "time_source": {"enum": ["host", "coordinator_observed", "unavailable"]},
    "started_at": NULLABLE_STRING, "finished_at": NULLABLE_STRING,
    "reclaim_state": {"enum": ["reclaimed", "unsupported", "not_observed"]},
    "reclaimed_at": NULLABLE_STRING,
})
BIZ_FLOW_EXECUTION_SCHEMA = _object({
    "receipts": _array(BIZ_FLOW_RECEIPT_SCHEMA),
    "active_observations": _array({**HOST_ACTIVE_OBSERVATION_SCHEMA,
        "description": "active_task_ids bind launched receipts as <task_id>:<attempt>; startup failures are excluded."}),
})
BIZ_FLOW_AUTHORIZATION_SCHEMA = _object({
    "choice_reference": NONEMPTY_STRING, "scope": _array(NONEMPTY_STRING, minimum=1),
})
BIZ_FLOW_SUBMISSION_SCHEMA = _object({
    "protocol_version": {"const": "5.0"}, "run_id": NONEMPTY_STRING,
    "source_fingerprint": NONEMPTY_STRING, "mapping_hash": NONEMPTY_STRING,
    "package_hash": NONEMPTY_STRING, "mode": {"enum": ["native", "serial"]},
    "parallel": {"type": "boolean"}, "completed_child_agents": {"type": "integer", "minimum": 0},
    "serial_approval": {"anyOf": [{"type": "null"}, BIZ_FLOW_AUTHORIZATION_SCHEMA]},
    "execution": BIZ_FLOW_EXECUTION_SCHEMA,
    "results": {"type": "object", "additionalProperties": BIZ_FLOW_ENTRY_RESULT_SCHEMA},
})
BIZ_FLOW_HANDOFF_SCHEMA = _object({
    "protocol_version": {"const": "5.0"}, "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "run_id": NONEMPTY_STRING, "project_root": NONEMPTY_STRING, "docs_root": NONEMPTY_STRING,
    "source_commit": NONEMPTY_STRING, "source_fingerprint": NONEMPTY_STRING,
    "source_status": _object({"target_commit": NONEMPTY_STRING, "head_commit": NONEMPTY_STRING,
        "workspace_dirty": {"type": "boolean"}, "includes_uncommitted_changes": {"const": False}}),
    "mapping_hash": NONEMPTY_STRING, "package_hash": NONEMPTY_STRING,
    "mode": {"enum": ["native", "serial", None]},
    "status": {"enum": ["prepared", "collected", "verified", "accepted", "failed", "cancelled", "superseded"]},
    "parallel": {"type": "boolean"}, "degraded": {"type": "boolean"},
    "completed_child_agents": {"type": "integer", "minimum": 0},
    "tasks": _array(BIZ_FLOW_TASK_SCHEMA),
    "adapter_version": NONEMPTY_STRING,
    "entry_facts": {"type": "object", "additionalProperties": BIZ_FLOW_ENTRY_FACTS_SCHEMA},
    "verified_evidence": _array(BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA),
    "supersedes_run_id": NULLABLE_STRING,
    "mapping": {"type": "object"},
    "protected_hashes": {"type": "object", "additionalProperties": NONEMPTY_STRING},
    "document_inputs": {"type": "object", "additionalProperties": BIZ_FLOW_HASH_SCHEMA},
    "version_input_hash": BIZ_FLOW_HASH_SCHEMA,
    "accepted_version_hash": BIZ_FLOW_HASH_SCHEMA,
    "purpose": {"enum": ["generate", "audit"]}, "module_filter": NULLABLE_STRING,
    "host_capability": {"enum": ["unknown", "available", "session_reported_unavailable"]},
    "serial_approval": {"anyOf": [{"type": "null"}, BIZ_FLOW_AUTHORIZATION_SCHEMA]},
    "execution": BIZ_FLOW_EXECUTION_SCHEMA,
    "results": {"type": "object", "additionalProperties": BIZ_FLOW_ENTRY_RESULT_SCHEMA},
    "verification_runs": {"type": "integer", "minimum": 0}, "errors": STRING_LIST,
    "comparison": _object({"baseline_commit": NULLABLE_STRING, "available": {"type": "boolean"},
        "reason": NONEMPTY_STRING, "added_entry_ids": STRING_LIST, "changed_entry_ids": STRING_LIST,
        "deleted_entry_ids": STRING_LIST, "reuse": NONEMPTY_STRING}),
    "result_hashes": {"type": "object", "additionalProperties": BIZ_FLOW_HASH_SCHEMA},
    "document_hashes": {"type": "object", "additionalProperties": BIZ_FLOW_HASH_SCHEMA},
    "submission_hash": BIZ_FLOW_HASH_SCHEMA, "verify_digest": BIZ_FLOW_HASH_SCHEMA,
    "trust_boundary": {"enum": ["host-attested", "coordinator-attested"]},
    "validation_scope": {"const": "source-rebuilt-facts-and-canonical-assets"},
    "collection_errors": STRING_LIST,
    "rejected_submissions": _array({"type": "object"}),
    "superseded_by_run_id": NONEMPTY_STRING,
    "evidence_submission": BIZ_FLOW_SUBMISSION_SCHEMA,
    "verified_output_hashes": {"type": "object", "additionalProperties": BIZ_FLOW_HASH_SCHEMA},
    "snapshot_cleaned": {"type": "boolean"},
}, ("protocol_version", "schema_version", "run_id", "project_root", "docs_root", "source_commit",
    "source_fingerprint", "mapping_hash", "package_hash", "mode", "status", "parallel", "degraded",
    "completed_child_agents", "tasks", "adapter_version", "entry_facts", "verified_evidence", "supersedes_run_id", "source_status",
    "mapping", "protected_hashes", "document_inputs", "version_input_hash", "purpose", "module_filter", "host_capability", "serial_approval",
    "execution", "results", "verification_runs", "errors", "comparison"))

BIZ_FLOW_DISCOVERY_SCHEMA = _object({
    "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
    "source_fingerprint": NONEMPTY_STRING, "source_commit": NONEMPTY_STRING,
    "entries": _array(_object({"entry_id": NONEMPTY_STRING,
        "source_evidence": BIZ_FLOW_SOURCE_EVIDENCE_SCHEMA})),
    "unresolved": STRING_LIST,
})

BIZ_FLOW_MODULE_MAP_SCHEMA: dict[str, Any] = _object(
    {
        "schema_version": {"const": int(BIZ_FLOW_SCHEMA_VERSION)},
        "source_fingerprint": NONEMPTY_STRING,
        "effective_git": NONEMPTY_STRING,
        "confirmed": {"type": "boolean"},
        "exclusions": _array(_object({
            "candidate": NONEMPTY_STRING, "reason": NONEMPTY_STRING, "evidence": NONEMPTY_STRING_LIST,
            "module": NONEMPTY_STRING,
        }, required=("candidate", "reason", "evidence"))),
        "modules": _array(_object({
            "name": NONEMPTY_STRING, "display_name": NONEMPTY_STRING, "rationale": NONEMPTY_STRING,
            "file": NONEMPTY_STRING, "responsibility": NONEMPTY_STRING, "entry_ids": STRING_LIST,
        })),
    }
)

BIZ_FLOW_DISCOVERY_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_HANDOFF_SCHEMA["properties"]["mapping"] = BIZ_FLOW_MODULE_MAP_SCHEMA
BIZ_FLOW_DISCOVERY_SCHEMA["contract"] = "biz-flow.discovery"
BIZ_FLOW_MODULE_MAP_SCHEMA["schema_version"] = int(BIZ_FLOW_SCHEMA_VERSION)
BIZ_FLOW_MODULE_MAP_SCHEMA["contract"] = "biz-flow.module-map"

BRU_WORKER_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
BRU_WORKER_TASK = _object({
    "task_id": NONEMPTY_STRING, "module": NONEMPTY_STRING, "directory": NONEMPTY_STRING,
    "write_scope": NONEMPTY_STRING_LIST, "result_path": NONEMPTY_STRING, "questions": NONEMPTY_STRING_LIST,
}, ("task_id", "module", "directory", "write_scope", "result_path", "questions"))
BRU_WORKER_TASK_PACKAGE = _object({
    "protocol_version": {"const": 1}, "domain": {"const": "bru-api"},
    "run_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "qa_root": NONEMPTY_STRING,
    "execution_mode": {"type": "string", "enum": ["native", "serial"]}, "execution_approval": {"type": "string"},
    "validation_stage": {"type": "string", "enum": ["generation", "materialization", "pre-execution", "post-execution"]},
    "input_hash": BRU_WORKER_HASH, "tasks": _array(BRU_WORKER_TASK, minimum=1),
    "protected_files": {"type": "object", "additionalProperties": NONEMPTY_STRING},
    "baseline_files": {"type": "object", "additionalProperties": NONEMPTY_STRING},
    "handoff_root": NONEMPTY_STRING, "submission_contract": {"const": "bru-api.worker-submission"}, "stop_conditions": NONEMPTY_STRING_LIST,
}, ("protocol_version", "domain", "run_id", "qa_root", "execution_mode", "execution_approval", "validation_stage", "input_hash", "tasks",
    "protected_files", "baseline_files", "handoff_root", "submission_contract", "stop_conditions"))
BRU_WORKER_ATTEMPT = _object({
    "attempt": {"type": "integer", "minimum": 1},
    "status": {"type": "string", "enum": ["success", "failed", "timeout", "interrupted", "spawn_failed"]},
    "child_agent_id": {"type": "string"}, "tool_references": STRING_LIST,
    "time_source": {"type": "string", "enum": ["host", "coordinator_observed", "unavailable"]},
    "started_at": {"type": "string"}, "ended_at": {"type": "string"}, "reclaimed_at": {"type": "string"},
    "reclaim_state": {"type": "string", "enum": ["reclaimed", "unsupported", "not_observed"]}, "error": {"type": "string"},
}, ("attempt", "status", "child_agent_id", "tool_references", "time_source", "started_at", "ended_at", "reclaimed_at", "reclaim_state", "error"))
BRU_WORKER_RESULT = _object({
    "attempt": {"type": "integer", "minimum": 1},
    "artifact_hashes": {"type": "object", "additionalProperties": BRU_WORKER_HASH},
    "changed_paths": STRING_LIST, "diagnostics": NONEMPTY_STRING_LIST,
}, ("attempt", "artifact_hashes", "changed_paths", "diagnostics"))
BRU_WORKER_SUBMISSION = _object({
    "run_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "task_id": NONEMPTY_STRING,
    "package_hash": BRU_WORKER_HASH, "task_hash": BRU_WORKER_HASH, "input_hash": BRU_WORKER_HASH,
    "record_origin": {"type": "string", "enum": ["host-attested", "fixture"]},
    "permission_enforcement": {"type": "string", "enum": ["shared_workspace_instructions", "host_sandbox", "worktree", "staging_patch"]},
    "attempts": _array(BRU_WORKER_ATTEMPT, minimum=1), "result": BRU_WORKER_RESULT, "result_hash": BRU_WORKER_HASH,
    "active_observations": _array(_object({
        "observed_at": NONEMPTY_STRING, "active_task_ids": NONEMPTY_STRING_LIST,
        "active_child_agent_ids": NONEMPTY_STRING_LIST, "active_attempts": _array({"type": "integer", "minimum": 1}, minimum=2),
        "tool_reference": NONEMPTY_STRING, "time_source": {"type": "string", "enum": ["host", "coordinator_observed"]},
    }, ("observed_at", "active_task_ids", "active_child_agent_ids", "active_attempts", "tool_reference", "time_source"))),
}, ("run_id", "task_id", "package_hash", "task_hash", "input_hash", "record_origin", "permission_enforcement", "attempts", "result", "result_hash", "active_observations"))

CONTRACT_SCHEMAS = {
    "e2e.document-baseline": E2E_DOCUMENT_BASELINE_SCHEMA,
    "e2e.document-state": E2E_DOCUMENT_STATE_SCHEMA,
    "bru-api.design-rules": BRU_API_DESIGN_RULES_SCHEMA,
    "bru-api.design-generation-report": BRU_API_DESIGN_REPORT_SCHEMA,
    "bru-api.logic": BRU_API_LOGIC_SCHEMA,
    "bru-api.value-resolution": BRU_API_VALUE_RESOLUTION_SCHEMA,
    "bru-api.version-lock": BRU_API_VERSION_LOCK_SCHEMA,
    "bru-api.worker-task-package": {"contract": "bru-api.worker-task-package", "schema_version": BRU_API_SCHEMA_VERSION, "document": BRU_WORKER_TASK_PACKAGE},
    "bru-api.worker-result": {"contract": "bru-api.worker-result", "schema_version": BRU_API_SCHEMA_VERSION, "document": BRU_WORKER_RESULT},
    "bru-api.worker-submission": {"contract": "bru-api.worker-submission", "schema_version": BRU_API_SCHEMA_VERSION, "document": BRU_WORKER_SUBMISSION},
    "biz-flow.discovery": BIZ_FLOW_DISCOVERY_SCHEMA,
    "biz-flow.handoff": BIZ_FLOW_HANDOFF_SCHEMA,
    "biz-flow.submission": BIZ_FLOW_SUBMISSION_SCHEMA,
    "biz-flow.task": BIZ_FLOW_TASK_SCHEMA,
    "biz-flow.receipt": BIZ_FLOW_RECEIPT_SCHEMA,
    "biz-flow.entry-analysis": BIZ_FLOW_ENTRY_ANALYSIS_SCHEMA,
    "biz-flow.entry-facts": BIZ_FLOW_ENTRY_FACTS_SCHEMA,
    "biz-flow.entry-result": BIZ_FLOW_ENTRY_RESULT_SCHEMA,
    "biz-flow.evidence-request": BIZ_FLOW_EVIDENCE_REQUEST_SCHEMA,
    "biz-flow.module-map": BIZ_FLOW_MODULE_MAP_SCHEMA,
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


E2E_SERIAL_APPROVAL_SCHEMA = _object({
    "decision": {"const": "serial"},
    "reference": NONEMPTY_STRING, "scopes": _array(NONEMPTY_STRING, minimum=1, unique=True),
    "native_status": {"enum": ["tool_missing", "host_forbidden", "spawn_failed_unrecoverable"]},
    "reason": NONEMPTY_STRING, "diagnostic_reference": NONEMPTY_STRING,
    "prior_run_ids": _array(NONEMPTY_STRING, unique=True),
})
E2E_HOST_TASK_SCHEMA = _object({
    "protocol_version": {"const": 1}, "domain": {"const": "e2e"},
    **{key: NONEMPTY_STRING for key in ("run_id", "task_id", "scenario_id", "project_root", "write_scope",
        "input_sha256", "starter_sha256", "result_path", "instructions", "permission_enforcement", "task_sha256")},
    "inputs": {"type": "object", "additionalProperties": True},
    "source": _array({"type": "object", "additionalProperties": True}),
    "design_rule_ids": _array(NONEMPTY_STRING),
    "mode": {"const": "serial"}, "serial_approval": E2E_SERIAL_APPROVAL_SCHEMA,
}, ("protocol_version", "domain", "run_id", "task_id", "scenario_id", "project_root", "write_scope",
    "input_sha256", "starter_sha256", "result_path", "instructions", "permission_enforcement", "task_sha256",
    "inputs", "source", "design_rule_ids"))
E2E_HOST_RECEIPT_SCHEMA = _object({
    **{key: NONEMPTY_STRING for key in ("run_id", "task_id", "task_sha256", "input_sha256", "write_scope")},
    "child_agent_id": {"anyOf": [NONEMPTY_STRING, {"type": "null"}]},
    "attempt": {"type": "integer", "minimum": 1},
    "status": {"enum": ["success", "failed", "interrupted", "timeout", "spawn_failed"]},
    "result_sha256": NULLABLE_STRING, "tool_records": _array(NONEMPTY_STRING, minimum=1),
    "written_paths": _array(NONEMPTY_STRING),
    "analysis_summary": NONEMPTY_STRING, "source_evidence": _array(NONEMPTY_STRING), "error": NONEMPTY_STRING,
}, ("run_id", "task_id", "task_sha256", "input_sha256", "write_scope", "child_agent_id", "attempt",
    "status", "result_sha256", "tool_records", "written_paths"))
E2E_HOST_RESULTS_SCHEMA = _object({
    "protocol_version": {"const": 1}, "domain": {"const": "e2e"}, "run_id": NONEMPTY_STRING,
    "mode": {"enum": ["native", "serial"]}, "degraded": {"type": "boolean"}, "parallel": {"type": "boolean"},
    "completed_child_agents": {"type": "integer", "minimum": 0},
    "receipts": _array(E2E_HOST_RECEIPT_SCHEMA, minimum=1), "observations": _array(HOST_ACTIVE_OBSERVATION_SCHEMA),
    "fixture": {"type": "boolean"},
    "serial_approval": E2E_SERIAL_APPROVAL_SCHEMA,
}, ("protocol_version", "domain", "run_id", "mode", "degraded", "parallel", "completed_child_agents", "receipts", "observations"))
E2E_HOST_RUN_SCHEMA = _object({
    "protocol_version": {"const": 1}, "domain": {"const": "e2e"}, "run_id": NONEMPTY_STRING,
    "project_root": NONEMPTY_STRING, "input_sha256": NONEMPTY_STRING,
    "status": {"enum": ["tasks_prepared", "results_collected"]}, "mode": {"enum": ["native", "serial"]},
    "parallel": {"type": "boolean"}, "degraded": {"type": "boolean"},
    "completed_child_agents": {"type": "integer", "minimum": 0}, "tasks": _array(E2E_HOST_TASK_SCHEMA),
    "readonly_snapshot": {"type": "object", "additionalProperties": NONEMPTY_STRING},
    "source_workspaces": {"type": "object", "additionalProperties": {"type": "object"}},
    "receipts": _array(E2E_HOST_RECEIPT_SCHEMA), "observations": _array(HOST_ACTIVE_OBSERVATION_SCHEMA),
    "trust_boundary": NONEMPTY_STRING,
    "serial_approval": E2E_SERIAL_APPROVAL_SCHEMA,
}, ("protocol_version", "domain", "run_id", "project_root", "input_sha256", "status", "mode", "parallel", "degraded",
    "completed_child_agents", "tasks", "readonly_snapshot", "source_workspaces", "receipts", "observations", "trust_boundary"), additional=True)
# These are two explicit execution modes, not interchangeable flags. Runtime
# validation additionally binds their authorization and receipts to the tasks.
_e2e_execution_schemas = []
for _document in (E2E_HOST_RESULTS_SCHEMA, E2E_HOST_RUN_SCHEMA):
    _native = deepcopy(_document)
    _native["properties"].update({"mode": {"const": "native"}, "degraded": {"const": False}})
    _native["properties"].pop("serial_approval")
    _serial = deepcopy(_document)
    _serial["properties"].update({"mode": {"const": "serial"}, "degraded": {"const": True},
        "parallel": {"const": False}, "completed_child_agents": {"const": 0},
        "observations": {"type": "array", "maxItems": 0}})
    _serial["required"].append("serial_approval")
    _e2e_execution_schemas.append({"oneOf": [_native, _serial]})
E2E_HOST_RESULTS_SCHEMA, E2E_HOST_RUN_SCHEMA = _e2e_execution_schemas
for _name, _document in {"host-task": E2E_HOST_TASK_SCHEMA, "host-receipt": E2E_HOST_RECEIPT_SCHEMA,
                        "host-results": E2E_HOST_RESULTS_SCHEMA, "host-run": E2E_HOST_RUN_SCHEMA,
                        "serial-approval": E2E_SERIAL_APPROVAL_SCHEMA}.items():
    CONTRACT_SCHEMAS[f"e2e.{_name}"] = {"contract": f"e2e.{_name}", "schema_version": E2E_GATE_SCHEMA_VERSION, "document": _document}
COMMAND_SCHEMAS["e2e.generate"]["options"]["--delegate"] = "boolean"
for _command in ("e2e.init", "e2e.generate"):
    COMMAND_SCHEMAS[_command]["options"]["--serial-approval"] = "path"
COMMAND_SCHEMAS["e2e.check"]["options"]["--host-results"] = "path"

CONTRACT_SCHEMAS.update(json.loads(Path(__file__).with_name("sequence-contracts.json").read_text(encoding="utf-8")))
CONTRACT_SCHEMAS["sequence-diagram-generator.domain-command-result"] = {
    "contract": "sequence-diagram-generator.domain-command-result", "schema_version": SEQUENCE_SCHEMA_VERSION,
    "document": {"type": "object", "properties": {
        "summary": {"type": "string"}, "data": {"type": "object"}, "artifact_path": {"type": "string"}},
        "required": ["summary", "data", "artifact_path"], "additionalProperties": False}}
for _command, _options in {
    "init": {"--out": "path"},
    "discover": {"--intent": "implementation|proposal|description", "--entry": "string[]", "--out": "path",
                 "--requirement-file": "path", "--requirement-url": "url", "--requirement-text": "string",
                 "--description-file": "path", "--description-url": "url", "--description-text": "string", "--source-anchor": "string"},
    "prepare": {"--run-id": "uuid-hex", "--entry-id": "string[]", "--segment-id": "string[]", "--all-entries": "boolean", "--all-segments": "boolean", "--out": "path", "--confirm": "boolean",
                "--execution-mode": "native|serial", "--execution-approval": "string"},
    "collect": {"--run-id": "uuid-hex", "--results": "path"},
    "check": {"--run-id": "uuid-hex", "--stage": "entries|delivery", "--full": "boolean"},
    "verify": {"--run-id": "uuid-hex"},
    "accept": {"--run-id": "uuid-hex"},
    "clean": {"--run-id": "uuid-hex", "--all": "boolean"},
    "publish": {"--run-id": "uuid-hex", "--stage": "prepare|collect|check", "--target": "url-or-id", "--write-scope": "string",
                "--execution-approval": "string", "--reference-bundle": "path", "--receipt": "path"},
}.items():
    COMMAND_SCHEMAS[f"sequence-diagram-generator.{_command}"] = {
        "options": {"--project": "path", **_options}, "schema_version": SEQUENCE_SCHEMA_VERSION,
        "required": ["--project"] + ([] if _command in {"init", "discover"} else ["--run-id"]),
    }


def get_schema(scope: str | None = None) -> dict[str, Any]:
    if scope is None:
        return {
            "domains": {
                "sequence-diagram-generator": {
                    "schema_version": SEQUENCE_SCHEMA_VERSION,
                    "commands": [name.split(".", 1)[1] for name in COMMAND_SCHEMAS if name.startswith("sequence-diagram-generator.")],
                },
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
    if scope.startswith("sequence-diagram-generator."):
        schema["schema_version"] = SEQUENCE_SCHEMA_VERSION
    elif scope.startswith("bru-api."):
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
    if "$ref" in schema:
        reference = CONTRACT_SCHEMAS.get(schema["$ref"])
        if reference is None:
            return [f"{path}: unknown contract reference"]
        return validate_schema(reference["document"], value, path)
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
        for index, item_schema in enumerate(schema.get("prefixItems", [])):
            if index < len(value):
                errors.extend(validate_schema(item_schema, value[index], f"{path}[{index}]"))
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
        if len(value) > schema.get("maxLength", len(value)):
            errors.append(f"{path}: string is too long")
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
