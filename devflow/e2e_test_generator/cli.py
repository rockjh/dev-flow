"""Command parser for the Python E2E domain."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.errors import ExitCode
from .assets import initialize
from .contracts import _generate_artifacts
from .discovery import PROTOCOL_SUFFIXES, discover_documents, discover_protocols, read_only_environment_probe
from .document_gate import advance_baseline, initialize_document_state, mark_generated, run_document_gate
from .runner import ORDERED_GATES, check_gate, pytest_arg_errors, run_ordered
from .source_versions import RULES_VERSION, source_version_results


def init_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e init")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--design-root", action="append", type=Path, default=[])
    parser.add_argument("--design-file", action="append", type=Path, default=[])
    parser.add_argument("--openapi-root", action="append", type=Path, default=[])
    parser.add_argument("--openapi-file", action="append", type=Path, default=[])
    parser.add_argument("--runtime-url", "--protocol-url", dest="runtime_urls", action="append", default=[])
    parser.add_argument("--requirement", action="append", default=[])
    parser.add_argument("--requirement-source", action="append", choices=("user", "design", "biz-flow"), default=[])
    parser.add_argument("--biz-flow-ref", action="append", default=[])
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--confirmation-summary", default="")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    report = run_document_gate(project, "init", allow_initial=True)
    print(json.dumps(report.as_dict(), ensure_ascii=False), file=sys.stderr)
    if not report.allowed:
        for issue in report.issues:
            print(issue, file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    if args.requirement_source and len(args.requirement_source) != len(args.requirement):
        print("DOCUMENT_SYNC_BLOCKED: --requirement-source must be supplied once per --requirement", file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    if len(args.biz_flow_ref) > len(args.requirement):
        print("DOCUMENT_SYNC_BLOCKED: --biz-flow-ref cannot exceed --requirement count", file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    sources = None
    if args.requirement_source:
        sources = []
        ref_index = 0
        for requirement, kind in zip(args.requirement, args.requirement_source):
            value = requirement
            if kind == "biz-flow":
                if ref_index >= len(args.biz_flow_ref) or "#" not in args.biz_flow_ref[ref_index]:
                    print("DOCUMENT_SYNC_BLOCKED: each biz-flow requirement needs --biz-flow-ref file#section", file=sys.stderr)
                    return int(ExitCode.GATE_FAILED)
                value = args.biz_flow_ref[ref_index]
                ref_index += 1
            sources.append({"type": kind, "value": value})
    state = initialize_document_state(project, args.requirement, sources=sources, confirm=args.confirm, reject=args.reject, summary=args.confirmation_summary)
    if args.confirm and state.get("status") != "confirmed":
        print("DOCUMENT_CONFIRMATION_REQUIRED: cannot confirm an empty candidate draft", file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    if (args.design_root or args.design_file or args.openapi_root or args.openapi_file or args.runtime_urls) and state.get("status") not in {"confirmed", "generated"}:
        print("DOCUMENT_CONFIRMATION_REQUIRED: formal artifact generation requires confirmed document candidates", file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    changed = initialize(project)
    if args.design_root or args.design_file or args.openapi_root or args.openapi_file or args.runtime_urls:
        result, errors = _generate_artifacts(
            project,
            design_roots=args.design_root,
            design_files=args.design_file,
            openapi_roots=args.openapi_root,
            openapi_files=args.openapi_file,
            runtime_urls=args.runtime_urls,
        )
        print(json.dumps(result, ensure_ascii=False))
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if errors:
            return int(ExitCode.GATE_FAILED)
    else:
        design = discover_documents(project)
        protocol = discover_protocols(project)
        if not design.files:
            print("design documents not found; provide --design-root or --design-file before generation", file=sys.stderr)
        if not protocol.files:
            print("formal protocol documents not found; provide --openapi-root or --openapi-file before generation", file=sys.stderr)
    print(f"initialized {project} ({len(changed)} file(s) changed)")
    if state.get("status") in {"confirmed", "generated"}:
        advance_baseline(project, report)
    return 0


def discover_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e discover")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--design-root", action="append", type=Path, default=[])
    parser.add_argument("--design-file", action="append", type=Path, default=[])
    parser.add_argument("--openapi-root", action="append", type=Path, default=[])
    parser.add_argument("--openapi-file", action="append", type=Path, default=[])
    parser.add_argument("--runtime-url", "--protocol-url", dest="runtime_urls", action="append", default=[])
    args = parser.parse_args(argv)
    project = args.project.resolve()
    design = discover_documents(project, roots=args.design_root, files=args.design_file)
    protocol = discover_protocols(project, roots=args.openapi_root, files=args.openapi_file)
    has_formal_protocol = any(path.suffix.casefold() in PROTOCOL_SUFFIXES for path in protocol.files)
    runtime = read_only_environment_probe(project) if not has_formal_protocol and not (args.openapi_root or args.openapi_file or args.runtime_urls) else {}
    if args.runtime_urls:
        from .discovery import read_only_protocol_probe
        probe = read_only_protocol_probe(
            ({"url": value, "source_type": "user_url", "user_confirmed": True} for value in args.runtime_urls),
            allow_external=True,
        )
        runtime = {
            "protocol_sources": probe.get("sources", []),
            "protocol_candidates": args.runtime_urls,
            "classifications": probe.get("classifications", ["protocol_unknown"]),
            "failure_details": probe.get("failure_details", []),
        }
    runtime_sources = runtime.get("protocol_sources", []) if isinstance(runtime, dict) else []
    print(json.dumps({
        "design": {"files": [str(path) for path in design.files], "candidates": [str(path) for path in design.candidates]},
        "protocol": {"files": [str(path) for path in protocol.files], "candidates": [str(path) for path in protocol.candidates], "runtime_sources": runtime_sources},
        "runtime": {"outcome": runtime.get("classifications", []) if isinstance(runtime, dict) else "not_requested", "protocol_candidates": runtime.get("protocol_candidates", []) if isinstance(runtime, dict) else []},
    }, ensure_ascii=False))
    if not design.files or (not protocol.files and not runtime_sources):
        return int(ExitCode.NOT_FOUND)
    if not (args.design_root or args.design_file) and len(design.candidates) > 1:
        return int(ExitCode.AMBIGUOUS)
    if not (args.openapi_root or args.openapi_file) and len(protocol.candidates) > 1:
        return int(ExitCode.AMBIGUOUS)
    return 0


def generate_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e generate")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--design-root", action="append", type=Path, default=[])
    parser.add_argument("--design-file", action="append", type=Path, default=[])
    parser.add_argument("--openapi-root", action="append", type=Path, default=[])
    parser.add_argument("--openapi-file", action="append", type=Path, default=[])
    parser.add_argument("--runtime-url", "--protocol-url", dest="runtime_urls", action="append", default=[])
    args = parser.parse_args(argv)
    report = run_document_gate(args.project.resolve(), "generate")
    print(json.dumps(report.as_dict(), ensure_ascii=False), file=sys.stderr)
    if not report.allowed:
        for issue in report.issues:
            print(issue, file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    result, errors = _generate_artifacts(
        args.project.resolve(),
        design_roots=args.design_root,
        design_files=args.design_file,
        openapi_roots=args.openapi_root,
        openapi_files=args.openapi_file,
        runtime_urls=args.runtime_urls,
    )
    print(json.dumps(result, ensure_ascii=False))
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if not errors:
        mark_generated(args.project.resolve())
        advance_baseline(args.project.resolve(), report)
    return int(ExitCode.GATE_FAILED) if errors else 0


def check_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e check")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--gate", required=True, choices=(*ORDERED_GATES, "discovery", "contracts", "static", "all"))
    parser.add_argument("--scenario")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    report = run_document_gate(root, "check")
    print(json.dumps(report.as_dict(), ensure_ascii=False), file=sys.stderr)
    if not report.allowed:
        for issue in report.issues:
            print(issue, file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    errors = check_gate(root, args.gate, args.scenario)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"gate passed: {args.gate}")
        advance_baseline(root, report)
    return int(ExitCode.GATE_FAILED) if errors else 0


def source_status_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e source-status")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--scenario")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    report = run_document_gate(root, "source-status")
    print(json.dumps({"document_gate": report.as_dict()}, ensure_ascii=False), file=sys.stderr)
    if not report.allowed:
        for issue in report.issues:
            print(issue, file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    errors, results = source_version_results(root, args.scenario)
    for error in errors:
        print(error, file=sys.stderr)
    print(json.dumps({"schema_version": RULES_VERSION, "results": results}, ensure_ascii=False))
    failing = {"affected", "full_rediscovery_required", "dirty_review_required"}
    code = int(ExitCode.GATE_FAILED) if errors or any(item["outcome"] in failing for item in results) else 0
    if code == 0:
        advance_baseline(root, report)
    return code


def run_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="devflow e2e run")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--scenario")
    parser.add_argument("--static-only", action="store_true")
    args, pytest_args = parser.parse_known_args(argv)
    invalid = pytest_arg_errors(pytest_args)
    if invalid:
        parser.error(f"unsupported pytest arguments: {', '.join(invalid)}")
    report = run_document_gate(args.project.resolve(), "run")
    print(json.dumps(report.as_dict(), ensure_ascii=False), file=sys.stderr)
    if not report.allowed:
        for issue in report.issues:
            print(issue, file=sys.stderr)
        return int(ExitCode.GATE_FAILED)
    code = run_ordered(args.project.resolve(), args.scenario, pytest_args, static_only=args.static_only)
    if code == 0:
        advance_baseline(args.project.resolve(), report)
    return code


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "init": init_command,
        "discover": discover_command,
        "generate": generate_command,
        "check": check_command,
        "source-status": source_status_command,
        "run": run_command,
    }
    parser = argparse.ArgumentParser(prog="devflow e2e")
    parser.add_argument("command", nargs="?", choices=tuple(commands))
    if not argv or argv[0] in {"-h", "--help"}:
        parser.parse_args(argv)
        return 0
    if argv[0] not in commands:
        parser.error(f"invalid choice: {argv[0]!r}")
    return commands[argv[0]](argv[1:])
