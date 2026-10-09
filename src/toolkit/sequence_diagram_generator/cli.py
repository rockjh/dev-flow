"""Parse once and assemble concrete workflow dependencies."""
import argparse
import json
from pathlib import Path

from ..core.errors import DevflowError, ExitCode
from .acceptance import ArtifactCommitter
from .adapters.registry import AdapterRegistry
from .documents import SequenceRenderer
from .feishu import FeishuLayoutBuilder, FeishuPublisher, FeishuStructureValidator
from .host import HostHandoff
from .inputs import SourceReader
from .models import AcceptRequest, CheckRequest, CollectRequest, DiscoverRequest, InitRequest, PrepareRequest, PublishRequest, RequirementInput, VerifyRequest
from .repository import RunRepository, project_context, to_dict
from .requirements import RequirementMapper
from .scanner import ProjectScanner
from .validation import FlowValidator
from .workflow import SequenceWorkflow


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DevflowError("INVALID_ARGUMENT", message, ExitCode.ARGUMENT)


def build_workflow(context):
    repository, validator = RunRepository(), FlowValidator()
    return SequenceWorkflow(SourceReader(context), ProjectScanner(AdapterRegistry()), HostHandoff(validator),
                            RequirementMapper(), SequenceRenderer(), validator, repository, ArtifactCommitter(repository),
                            FeishuPublisher(repository, FeishuLayoutBuilder(), FeishuStructureValidator()))


def _parser():
    parser = _Parser(prog="devflow sequence-diagram-generator")
    sub = parser.add_subparsers(dest="command", required=True)
    def common(command, run=True):
        item = sub.add_parser(command)
        item.add_argument("--project", required=True)
        if run:
            item.add_argument("--run-id", required=True)
        return item
    common("init", False)
    discover = common("discover", False)
    discover.add_argument("--mode", choices=("code", "requirement"), required=True)
    discover.add_argument("--intent", choices=("implementation", "proposal"))
    discover.add_argument("--entry", action="append", default=[])
    group = discover.add_mutually_exclusive_group()
    group.add_argument("--requirement-file")
    group.add_argument("--requirement-url")
    group.add_argument("--requirement-text")
    discover.add_argument("--source-anchor", default="")
    prepare = common("prepare")
    selection = prepare.add_mutually_exclusive_group()
    selection.add_argument("--entry-id", action="append", default=[])
    selection.add_argument("--all-entries", action="store_true")
    prepare.add_argument("--confirm", action="store_true")
    prepare.add_argument("--execution-mode", choices=("native", "serial"), default="native")
    prepare.add_argument("--execution-approval", default="")
    collect = common("collect")
    collect.add_argument("--results", required=True)
    check = common("check")
    check.add_argument("--stage", choices=("entries", "delivery"), default="delivery")
    check.add_argument("--full", action="store_true")
    common("verify")
    common("accept")
    publish = common("publish")
    publish.add_argument("--stage", choices=("prepare", "collect", "check"), required=True)
    publish.add_argument("--target", default="")
    publish.add_argument("--write-scope", default="")
    publish.add_argument("--execution-approval", default="")
    publish.add_argument("--reference-bundle")
    publish.add_argument("--receipt")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        context = project_context(args.project)
    except FileNotFoundError as exc:
        raise DevflowError("TARGET_NOT_FOUND", "project directory does not exist", ExitCode.NOT_FOUND) from exc
    workflow = build_workflow(context)
    if args.command == "init":
        result = workflow.init(InitRequest(context))
    elif args.command == "discover":
        requirement = None
        for kind in ("file", "url", "text"):
            value = getattr(args, "requirement_" + kind)
            if value is not None:
                requirement = RequirementInput(kind, value, args.source_anchor)
        result = workflow.discover(DiscoverRequest(context, args.mode, args.intent or ("proposal" if args.mode == "requirement" else "implementation"), tuple(args.entry), requirement))
    elif args.command == "prepare":
        result = workflow.prepare(PrepareRequest(context, args.run_id, tuple(args.entry_id), args.all_entries, args.confirm, args.execution_mode, args.execution_approval))
    elif args.command == "collect":
        original = Path(args.results).absolute()
        if original.is_relative_to(context.project) and not original.resolve().is_relative_to(context.project):
            raise DevflowError("GATE_FAILED", "results link escapes project", ExitCode.GATE_FAILED)
        result = workflow.collect(CollectRequest(context, args.run_id, original.resolve()))
    elif args.command == "check":
        result = workflow.check(CheckRequest(context, args.run_id, args.stage, args.full))
    elif args.command == "verify":
        result = workflow.verify(VerifyRequest(context, args.run_id))
    elif args.command == "publish":
        result = workflow.publish(PublishRequest(context, args.run_id, args.stage, args.target, args.write_scope, args.execution_approval,
                                                 Path(args.reference_bundle).resolve() if args.reference_bundle else None,
                                                 Path(args.receipt).resolve() if args.receipt else None))
    else:
        result = workflow.accept(AcceptRequest(context, args.run_id))
    print(json.dumps(to_dict(result), ensure_ascii=False, separators=(",", ":")))
    return 0
