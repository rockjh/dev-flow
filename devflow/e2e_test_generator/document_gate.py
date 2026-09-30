"""Program enforced documentation gate for E2E scenarios."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..core.schema import E2E_DOCUMENT_BASELINE_SCHEMA, E2E_DOCUMENT_STATE_SCHEMA, SCENARIO_DOCUMENT_SCHEMA, validate_schema


BASELINE_NAME = "e2e.yaml"
STATE_NAME = ".devflow/e2e-document-state.json"
REQUIRED_SECTIONS = (
    "场景名称", "测试目标", "业务入口", "前置条件", "测试数据", "关键步骤",
    "预期结果", "异常和补偿", "biz-flow 引用", "Mermaid 时序图",
)
REQUIRED_EN_SECTIONS = (
    "scenario name", "test objective", "business entry", "preconditions",
    "test data", "key steps", "expected results", "exceptions and compensation",
    "biz-flow references", "mermaid sequence diagram",
)
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_SECRET = re.compile(r"(?i)(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|bearer)\s*[:=]\s*[^<>{}\s]+")
_ENV_VALUE = re.compile(r"(?:\$\{?[A-Z][A-Z0-9_]*\}?|\b(?:DATABASE_URL|REDIS_URL|AWS_[A-Z0-9_]+|[A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY))\s*=\s*[^\s`<>{}]+)")
_SCENARIO_HEADING = re.compile(r"^#{1,3}\s+(?:Scenario\s*:\s*|场景\s*[:：]\s*)?(.+?)\s*$", re.I)

# Keep the required headings in source form that is stable across console encodings.
REQUIRED_SECTIONS = tuple(bytes(value, "ascii").decode("unicode_escape") for value in (
    r"\u573a\u666f\u540d\u79f0", r"\u6d4b\u8bd5\u76ee\u6807", r"\u4e1a\u52a1\u5165\u53e3", r"\u524d\u7f6e\u6761\u4ef6", r"\u6d4b\u8bd5\u6570\u636e", r"\u5173\u952e\u6b65\u9aa4",
    r"\u9884\u671f\u7ed3\u679c", r"\u5f02\u5e38\u548c\u8865\u507f", r"biz-flow \u5f15\u7528", r"Mermaid \u65f6\u5e8f\u56fe",
))
_SCENARIO_HEADING = re.compile(r"^#{1,3}\s+(?:Scenario\s*:\s*|\u573a\u666f\s*[:\uff1a]\s*)?(.+?)\s*$", re.I)


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(slots=True)
class DocumentIssue:
    code: str
    reason: str
    file: str = ""
    scenario: str = ""
    line: int | None = None
    allow_continue: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "file": self.file, "scenario": self.scenario, "line": self.line, "reason": self.reason, "allow_continue": self.allow_continue}

    def __str__(self) -> str:
        location = self.file or "docs/e2e"
        if self.line:
            location += f":{self.line}"
        scope = f" scenario={self.scenario}" if self.scenario else ""
        return f"{self.code}: {self.reason} file={location}{scope} continue={str(self.allow_continue).lower()}"


@dataclass(slots=True)
class GateReport:
    recorded_commit: str | None = None
    current_commit: str | None = None
    clean: bool = True
    state: str = "missing"
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    no_document_impact: list[str] = field(default_factory=list)
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    affected_scenarios: list[str] = field(default_factory=list)
    dirty_source_paths: list[str] = field(default_factory=list)
    impact_analysis: list[dict[str, Any]] = field(default_factory=list)
    issues: list[DocumentIssue] = field(default_factory=list)
    baseline_pending: bool = False

    @property
    def allowed(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "recorded_commit": self.recorded_commit,
            "current_commit": self.current_commit,
            "clean": self.clean,
            "state": self.state,
            "added_requirements": self.added,
            "modified_requirements": self.modified,
            "deleted_requirements": self.deleted,
            "no_document_impact": self.no_document_impact,
            "scenarios": self.scenarios,
            "affected_scenarios": self.affected_scenarios,
            "dirty_source": self.dirty_source_paths,
            "impact_analysis": self.impact_analysis,
            "diagram_checks": [
                {"scenario": item["id"], "status": "failed" if any(issue.scenario == item["name"] and issue.code.startswith("DOCUMENT_DIAGRAM_") for issue in self.issues) else "passed"}
                for item in self.scenarios
            ],
            "unresolved": [issue.as_dict() for issue in self.issues],
            "allow_continue": self.allowed,
            "baseline_pending": self.baseline_pending,
        }


def _git(project: Path, *args: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        return None, str(exc)
    return result.stdout.strip(), None


def _state_path(project: Path) -> Path:
    return project / STATE_NAME


def _save_state(project: Path, state: dict[str, Any]) -> None:
    path = _state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_state(project: Path) -> dict[str, Any]:
    try:
        value = json.loads(_state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _state_issues(project: Path, state: dict[str, Any]) -> list[DocumentIssue]:
    if not state:
        return []
    required = {"status", "requirements", "requirement_sources", "candidates", "candidate_fingerprint", "input_fingerprint", "source_fingerprint"}
    schema_errors = validate_schema(E2E_DOCUMENT_STATE_SCHEMA, state)
    if schema_errors or set(state) - required - {"confirmed_at", "confirmation_summary", "rejected_at", "rejection_summary", "pending_changes"} or not required.issubset(state):
        return [_issue("DOCUMENT_SYNC_BLOCKED", "document state has an invalid shape", _state_path(project))]
    sources = state.get("requirement_sources", [])
    if len(sources) != len(state.get("requirements", [])) or any(item.get("type") not in {"user", "design", "biz-flow"} for item in sources if isinstance(item, dict)):
        return [_issue("DOCUMENT_SYNC_BLOCKED", "every requirement must have an authorized source", _state_path(project))]
    if state.get("status") not in {"draft", "awaiting_confirmation", "confirmed", "generated"}:
        return [_issue("DOCUMENT_SYNC_BLOCKED", "document state has an invalid status", _state_path(project))]
    return []


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _candidate_refs_valid(project: Path, candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        refs = candidate.get("biz_flow_refs") if isinstance(candidate, dict) else None
        if not isinstance(refs, list) or not refs:
            return False
        for ref in refs:
            if not isinstance(ref, dict) or not str(ref.get("file", "")).startswith("docs/biz-flow/"):
                return False
            path = project / str(ref["file"])
            if not path.is_file():
                return False
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return False
            section = str(ref.get("section", "")).strip()
            if not section or not re.search(rf"^\s{{0,3}}#{{1,6}}\s+{re.escape(section)}\s*#?\s*$", text, re.I | re.M):
                return False
    return True


def _issue(code: str, reason: str, path: Path | str = "", scenario: str = "", line: int | None = None) -> DocumentIssue:
    return DocumentIssue(code, reason, str(path), scenario, line)


def validate_baseline(project: Path) -> tuple[str | None, list[DocumentIssue]]:
    path = project / "docs" / "e2e" / BASELINE_NAME
    if not path.is_file():
        return None, [_issue("DOCUMENT_BASELINE_MISSING", "docs/e2e/e2e.yaml does not exist", path)]
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, [_issue("DOCUMENT_BASELINE_INVALID", f"invalid YAML: {exc}", path)]
    if validate_schema(E2E_DOCUMENT_BASELINE_SCHEMA, value) or not isinstance(value, dict) or set(value) != {"git_commit"}:
        return None, [_issue("DOCUMENT_BASELINE_INVALID", "top level must contain only git_commit", path)]
    commit = value.get("git_commit")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        return None, [_issue("DOCUMENT_BASELINE_INVALID", "git_commit must be a complete 40 character SHA", path)]
    _, error = _git(project, "cat-file", "-e", f"{commit}^{{commit}}")
    if error:
        return None, [_issue("DOCUMENT_BASELINE_COMMIT_MISSING", f"recorded commit is not in this repository: {commit}", path)]
    head, error = _git(project, "rev-parse", "HEAD")
    if error or not head:
        return None, [_issue("DOCUMENT_BASELINE_INVALID", f"cannot compare recorded commit: {error or 'HEAD missing'}", path)]
    return commit, []


def _heading_key(value: str) -> str:
    return re.sub(r"[`*_：:]", "", value).strip().casefold()


def _parse_mermaid(text: str, path: Path, scenario: str, start_line: int) -> list[DocumentIssue]:
    issues: list[DocumentIssue] = []
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", text, flags=re.I | re.S)
    if len(blocks) != 1:
        return [_issue("DOCUMENT_DIAGRAM_MISSING", "each scenario must contain exactly one Mermaid diagram", path, scenario, start_line)]
    lines = [line.strip() for line in blocks[0].splitlines() if line.strip()]
    if not lines or lines[0].casefold() != "sequencediagram":
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "diagram must start with sequenceDiagram", path, scenario, start_line))
        return issues
    if not any(line.casefold() == "autonumber" for line in lines):
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "sequence diagram must contain autonumber", path, scenario, start_line))
    stack: list[str] = []
    branch_labels: list[str] = []
    results: list[str] = []
    has_request = False
    has_response = False
    alt_counts: list[list[int]] = []
    for offset, line in enumerate(lines, start_line):
        lower = line.casefold()
        if re.match(r"^(participant|actor)\s+", lower):
            continue
        if re.search(r"\w+\s*-+>>\s*\w+\s*:", line):
            has_request = True
        if re.search(r"\w+\s*-->>\s*\w+\s*:", line):
            has_response = True
        if lower.startswith(("alt ", "loop ", "opt ")):
            stack.append(lower.split()[0])
            alt_counts.append([0] if lower.startswith("alt ") else [])
            if lower.startswith("alt "):
                branch_labels.append(line)
        elif lower.startswith("else"):
            if not stack or stack[-1] != "alt":
                issues.append(_issue("DOCUMENT_DIAGRAM_BRANCH_INVALID", "else must be inside alt", path, scenario, offset))
            elif alt_counts and alt_counts[-1]:
                alt_counts[-1].append(0)
            branch_labels.append(line)
        elif lower == "end":
            if not stack:
                issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "unexpected end", path, scenario, offset))
            else:
                if stack[-1] == "alt" and alt_counts and alt_counts[-1] and not all(alt_counts[-1]):
                    issues.append(_issue("DOCUMENT_DIAGRAM_BRANCH_INVALID", "each alt branch needs a separate result", path, scenario, offset))
                stack.pop()
                if alt_counts:
                    alt_counts.pop()
        if any(token in lower for token in ("协议成功", "协议失败", "protocol success", "protocol failure")):
            results.append(line)
            if alt_counts and alt_counts[-1]:
                alt_counts[-1][-1] += 1
    if stack:
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "unclosed Mermaid block", path, scenario, start_line))
    if not has_request or not has_response:
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "diagram needs request and response messages", path, scenario, start_line))
    if any(line.casefold().startswith(("alt ", "else")) for line in lines):
        if not any(re.search(r"分支\s*[1-9]|branch\s*[1-9]", line, re.I) for line in branch_labels):
            issues.append(_issue("DOCUMENT_DIAGRAM_BRANCH_INVALID", "alt branches need labels such as 分支1/分支2", path, scenario, start_line))
        if any(line.casefold() == "par" or line.casefold().startswith("par ") for line in lines):
            issues.append(_issue("DOCUMENT_DIAGRAM_BRANCH_INVALID", "mutually exclusive paths cannot use par", path, scenario, start_line))
    lower_text = " ".join(lines).casefold()
    if re.search(r"逐条|每条|阈值|明细|逐项|each item|per item", lower_text) and not any(x.startswith("loop ") for x in (line.casefold() for line in lines)):
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "item processing must use loop/end", path, scenario, start_line))
    if re.search(r"异常|容错|中断|exception|timeout", lower_text) and not any(x.startswith("opt ") for x in (line.casefold() for line in lines)):
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "non-blocking exceptions must use opt/end", path, scenario, start_line))
    if not results:
        issues.append(_issue("DOCUMENT_DIAGRAM_RESULT_INCOMPLETE", "key results need protocol success or protocol failure", path, scenario, start_line))
    elif any(
        not re.search(r"落库|未落库|persist|stored|database", line, re.I)
        or not re.search(r"投递|未投递|不发送|不生成|消息|通知|任务|deliver|message|notify|none", line, re.I)
        for line in results
    ):
        issues.append(_issue("DOCUMENT_DIAGRAM_RESULT_INCOMPLETE", "each protocol result needs persistence and delivery semantics", path, scenario, start_line))
    if re.search(r"降级|快照为空|未达到阈值|观察结果缺失|不发送消息|不生成订单|degrad|empty snapshot|below threshold", " ".join(lines), re.I) and not any(line.casefold().startswith("note") for line in lines):
        issues.append(_issue("DOCUMENT_DIAGRAM_INVALID", "degradation and non-interrupting observations must use Note", path, scenario, start_line))
    # Validate Chinese documents using the actual semantic terms as well.
    zh_results = [line for line in lines if any(term in line for term in ("\u534f\u8bae\u6210\u529f", "\u534f\u8bae\u5931\u8d25"))]
    if zh_results:
        issues = [item for item in issues if item.code != "DOCUMENT_DIAGRAM_RESULT_INCOMPLETE"]
        if any(not re.search(r"\u843d\u5e93|\u672a\u843d\u5e93|\u6301\u4e45\u5316|persist|stored|database", line, re.I)
               or not re.search(r"\u6295\u9012|\u672a\u6295\u9012|\u4e0d\u53d1\u9001|\u4e0d\u751f\u6210|\u6d88\u606f|\u901a\u77e5|\u4efb\u52a1|deliver|message|notify|none", line, re.I)
               for line in zh_results):
            issues.append(_issue("DOCUMENT_DIAGRAM_RESULT_INCOMPLETE", "each protocol result needs persistence and delivery semantics", path, scenario, start_line))
    if any(line.casefold().startswith(("alt ", "else")) for line in lines) and any(re.search(r"\u5206\u652f\s*[1-9]|branch\s*[1-9]", line, re.I) for line in lines):
        issues = [item for item in issues if not (item.code == "DOCUMENT_DIAGRAM_BRANCH_INVALID" and "labels" in item.reason)]
        if branch_labels and not all(re.search(r"\u5206\u652f\s*[1-9]|branch\s*[1-9]", line, re.I) for line in branch_labels):
            issues.append(_issue("DOCUMENT_DIAGRAM_BRANCH_INVALID", "every alt/else branch needs an explicit branch label", path, scenario, start_line))
    if any(line.casefold().startswith("loop ") for line in lines):
        issues = [item for item in issues if not (item.code == "DOCUMENT_DIAGRAM_INVALID" and "item processing" in item.reason)]
    if any(line.casefold().startswith("opt ") for line in lines):
        issues = [item for item in issues if not (item.code == "DOCUMENT_DIAGRAM_INVALID" and "non-blocking exceptions" in item.reason)]
    if re.search(r"\u964d\u7ea7|\u5feb\u7167\u4e3a\u7a7a|\u672a\u8fbe\u5230\u9608\u503c|\u89c2\u5bdf\u7ed3\u679c\u7f3a\u5931|\u4e0d\u53d1\u9001\u6d88\u606f|\u4e0d\u751f\u6210\u8ba2\u5355", " ".join(lines), re.I) and any(line.casefold().startswith("note") for line in lines):
        issues = [item for item in issues if not (item.code == "DOCUMENT_DIAGRAM_INVALID" and "Note" in item.reason)]
    return issues


def validate_markdown(project: Path) -> tuple[list[dict[str, Any]], list[DocumentIssue]]:
    root = project / "docs" / "e2e"
    issues: list[DocumentIssue] = []
    scenarios: list[dict[str, Any]] = []
    if not root.is_dir():
        return [], [_issue("DOCUMENT_BASELINE_MISSING", "docs/e2e directory does not exist", root)]
    for path in sorted(root.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", str(exc), path))
            continue
        if _SECRET.search(text) or _ENV_VALUE.search(text):
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "document contains a credential-like value", path))
        section_names = {item.casefold() for item in (*REQUIRED_SECTIONS, *REQUIRED_EN_SECTIONS)}
        headings = [
            (index + 1, match.group(1).strip())
            for index, line in enumerate(text.splitlines())
            if (match := _SCENARIO_HEADING.match(line)) and _heading_key(match.group(1)) not in section_names
        ]
        if not headings:
            issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "Markdown must contain at least one scenario heading", path))
            continue
        for index, (line_no, title) in enumerate(headings):
            end = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(text.splitlines())
            block = "\n".join(text.splitlines()[line_no - 1:end])
            if re.search(r"```(?:python|pytest|javascript|typescript)\b", block, re.I):
                issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "scenario Markdown must not contain copied test code", path, title, line_no))
            metadata_match = re.search(r"```ya?ml\s*\n(.*?)```", block, flags=re.I | re.S)
            metadata: dict[str, Any] = {}
            if metadata_match:
                try:
                    parsed = yaml.load(metadata_match.group(1), Loader=_UniqueLoader)
                    metadata = parsed if isinstance(parsed, dict) else {}
                except yaml.YAMLError:
                    issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario metadata is invalid YAML", path, title, line_no))
            scenario_id = str(metadata.get("id") or metadata.get("scenario_id") or "").strip()
            metadata_name = str(metadata.get("name") or "").strip()
            metadata_document = str(metadata.get("document") or "").strip()
            owner = str(metadata.get("owner") or metadata.get("module") or "").strip()
            refs = metadata.get("biz_flow_refs", metadata.get("biz-flow_refs", []))
            if not scenario_id:
                issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario id is required", path, title, line_no))
            if not metadata_name:
                issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario name is required in metadata", path, title, line_no))
            if not metadata_document:
                issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario document is required in metadata", path, title, line_no))
            elif metadata_document != str(path.relative_to(project)).replace("\\", "/"):
                issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "metadata document does not match Markdown path", path, title, line_no))
            if not owner:
                issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario owner is required", path, title, line_no))
                issues.append(_issue("DOCUMENT_OWNERSHIP_AMBIGUOUS", "scenario ownership cannot be inferred", path, title, line_no))
            if not isinstance(refs, list) or not refs:
                issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", "scenario needs at least one biz-flow reference", path, title, line_no))
            if metadata.get("status", "active") != "active":
                issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "scenario status must be active", path, title, line_no))
            scenarios.append({"id": scenario_id, "name": title, "document": str(path.relative_to(project)), "owner": owner, "status": metadata.get("status", "active"), "biz_flow_refs": refs if isinstance(refs, list) else []})
            normalized = [_heading_key(line.lstrip("# ")) for line in block.splitlines() if line.startswith("##")]
            if normalized and _heading_key(title) == normalized[0]:
                normalized = normalized[1:]
            expected = [*(x.casefold() for x in REQUIRED_SECTIONS), *(x.casefold() for x in REQUIRED_EN_SECTIONS)]
            matched = [item for item in normalized if item in expected]
            target = next((variant for variant in (REQUIRED_SECTIONS, REQUIRED_EN_SECTIONS) if sum(item.casefold() in normalized for item in variant) == len(variant)), None)
            if target is None or [item.casefold() for item in target] != [item for item in normalized if item in {x.casefold() for x in target}]:
                issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "required Markdown sections are missing or out of order", path, title, line_no))
            block_lines = block.splitlines()
            section_positions = [(idx, _heading_key(line.lstrip("# "))) for idx, line in enumerate(block_lines) if line.startswith("##")]
            required_keys = {item.casefold() for item in (target or ())}
            for section_index, (position, section_name) in enumerate(section_positions):
                if section_name not in required_keys:
                    continue
                next_position = section_positions[section_index + 1][0] if section_index + 1 < len(section_positions) else len(block_lines)
                content = "\n".join(block_lines[position + 1:next_position]).strip()
                if not content or content.startswith("```") and content.endswith("```") and not content.strip("`").strip():
                    issues.append(_issue("DOCUMENT_SYNC_BLOCKED", f"section {section_name!r} must not be empty", path, title, line_no + position))
            issues.extend(_parse_mermaid(block, path, title, line_no))
            for ref in refs if isinstance(refs, list) else []:
                if not isinstance(ref, dict) or not ref.get("file") or not ref.get("section"):
                    issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", "biz-flow reference needs file and section", path, title, line_no)); continue
                ref_file = str(ref["file"]).replace("\\", "/")
                if not ref_file.startswith("docs/biz-flow/"):
                    issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", "biz-flow references must be under docs/biz-flow", path, title, line_no)); continue
                ref_path = project / ref_file
                if not ref_path.is_file():
                    issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", "referenced biz-flow file or section does not exist", path, title, line_no))
                    continue
                try:
                    ref_text = ref_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", f"cannot read referenced biz-flow file: {exc}", path, title, line_no))
                    continue
                section = str(ref["section"]).strip()
                heading_pattern = re.compile(rf"^\s{{0,3}}#{{1,6}}\s+{re.escape(section)}\s*#?\s*$", re.I | re.M)
                if not heading_pattern.search(ref_text):
                    issues.append(_issue("DOCUMENT_BIZ_FLOW_REFERENCE_MISSING", "referenced biz-flow section does not exist as a Markdown heading", path, title, line_no))
    if not list(root.glob("*.md")):
        issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "docs/e2e must contain at least one Markdown scenario document", root))
    ids = [item["id"] for item in scenarios if item["id"]]
    for duplicate in {item for item in ids if ids.count(item) > 1}:
        files = ", ".join(sorted({item["document"] for item in scenarios if item["id"] == duplicate}))
        issues.append(_issue("DOCUMENT_SCENARIO_DUPLICATED", f"scenario id is duplicated: {duplicate}", files))
    return scenarios, issues


def validate_scenario_artifacts(project: Path, scenarios: list[dict[str, Any]]) -> list[DocumentIssue]:
    """Cross-check generated scenario YAML against the documented scenario index."""
    root = project / "scenarios"
    if not root.is_dir():
        return [_issue("DOCUMENT_SCENARIO_UNASSIGNED", "generated scenario artifacts are missing", root)] if scenarios else []
    paths = sorted(path for path in root.rglob("*.yaml") if path.name.endswith("场景定义.yaml"))
    if not paths and scenarios:
        return [_issue("DOCUMENT_SCENARIO_UNASSIGNED", "no 场景定义.yaml matches the documented scenarios", root)]
    issues: list[DocumentIssue] = []
    by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in paths:
        try:
            value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", f"invalid scenario YAML: {exc}", path))
            continue
        schema_errors = validate_schema(SCENARIO_DOCUMENT_SCHEMA, value)
        if schema_errors or not isinstance(value, dict):
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "scenario YAML does not satisfy e2e.scenario schema", path))
            continue
        meta = value.get("meta", {})
        scenario_id = str(meta.get("id", "")).strip() if isinstance(meta, dict) else ""
        if not scenario_id:
            issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", "scenario YAML has no meta.id", path))
            continue
        if scenario_id in by_id:
            issues.append(_issue("DOCUMENT_SCENARIO_DUPLICATED", f"scenario YAML id is duplicated: {scenario_id}", path))
        by_id[scenario_id] = (path, value)
    documented = {str(item.get("id")): item for item in scenarios if item.get("id")}
    for scenario_id, item in documented.items():
        artifact = by_id.get(scenario_id)
        if artifact is None:
            issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", f"scenario YAML is missing for documented id: {scenario_id}", item.get("document", ""), item.get("name", "")))
            continue
        path, value = artifact
        meta = value.get("meta", {})
        if str(meta.get("name", "")).strip() != str(item.get("name", "")).strip():
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "scenario YAML name does not match Markdown metadata", path, item.get("name", "")))
        if str(meta.get("status", "")).strip() != str(item.get("status", "active")).strip():
            issues.append(_issue("DOCUMENT_SYNC_BLOCKED", "scenario YAML status does not match Markdown metadata", path, item.get("name", "")))
    for scenario_id, (path, _) in by_id.items():
        if scenario_id not in documented:
            issues.append(_issue("DOCUMENT_SCENARIO_UNASSIGNED", f"scenario YAML is not documented: {scenario_id}", path))
    return issues


def _diff(project: Path, old: str, head: str) -> tuple[list[str], list[DocumentIssue]]:
    output, error = _git(project, "diff", "--name-status", old, head)
    if error:
        return [], [_issue("DOCUMENT_INCREMENTAL_UPDATE_REQUIRED", f"cannot compare commits: {error}")]
    paths = [line for line in (output or "").splitlines() if line.strip()]
    return paths, []


def _analyze_impact(project: Path, changed_paths: list[str], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect source-level evidence for callers, callees and shared flows."""
    tracked, _ = _git(project, "ls-files")
    corpus = [Path(item) for item in (tracked or "").splitlines() if item]
    evidence: list[dict[str, Any]] = []
    for changed in changed_paths:
        path = Path(changed)
        try:
            source = (project / path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            source = ""
        symbols = re.findall(r"\b(?:def|class|function)\s+([A-Za-z_]\w*)", source)
        tokens = {path.stem.casefold(), *[item.casefold() for item in symbols]}
        callers: list[str] = []
        callees: list[str] = []
        shared: list[str] = []
        for candidate in corpus:
            if candidate.as_posix() == path.as_posix():
                continue
            try:
                text = (project / candidate).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(re.search(rf"\b{re.escape(token)}\b", text, re.I) for token in tokens if token):
                target = candidate.as_posix()
                if candidate.parts and candidate.parts[0] == "docs" and "biz-flow" in candidate.parts:
                    shared.append(target)
                elif candidate.suffix.casefold() in {".py", ".js", ".ts", ".java", ".go", ".rs"}:
                    callers.append(target)
                else:
                    callees.append(target)
        joined = source.casefold()
        checked_layers = ["callers", "callees", "shared_services", "state_models", "persistence", "async_chain", "biz_flow"]
        detected_layers = {
            "state_models": bool(re.search(r"\b(status|state|transition|order_status|package_status)\b", joined)),
            "persistence": bool(re.search(r"\b(sql|select|insert|update|delete|database|repository|transaction|lock|idempot)\b", joined)),
            "async_chain": bool(re.search(r"\b(message|queue|event|consumer|producer|retry|task|job|async|schedule)\b", joined)),
            "biz_flow": path.as_posix().startswith("docs/biz-flow/") or bool(shared),
        }
        evidence.append({
            "changed_file": changed,
            "symbols": sorted(symbols),
            "callers": sorted(callers),
            "callees": sorted(callees),
            "shared_services_and_biz_flow": sorted(shared),
            "checked_layers": checked_layers,
            "detected_layers": sorted(layer for layer, detected in detected_layers.items() if detected),
            "affected_scenarios": [item["id"] for item in scenarios],
        })
    return evidence


def run_document_gate(project: Path, command: str, *, allow_initial: bool = False) -> GateReport:
    report = GateReport()
    baseline, issues = validate_baseline(project)
    report.recorded_commit = baseline
    report.clean = not bool(_git(project, "status", "--porcelain")[0] or "")
    scenarios, markdown_issues = validate_markdown(project)
    report.scenarios = scenarios
    report.issues.extend(markdown_issues)
    state = _load_state(project)
    status = state.get("status", "missing")
    report.issues.extend(_state_issues(project, state))
    if command in {"check", "run", "source-status"} and status == "generated":
        report.issues.extend(validate_scenario_artifacts(project, scenarios))
    if issues:
        report.issues.extend(issues)
        can_generate_confirmed = command == "generate" and status == "confirmed" and (project / "docs" / "e2e").is_dir() and any((project / "docs" / "e2e").glob("*.md")) and all(item.code == "DOCUMENT_BASELINE_MISSING" for item in issues)
        if (allow_initial or can_generate_confirmed) and any(item.code == "DOCUMENT_BASELINE_MISSING" for item in issues):
            report.issues = [item for item in report.issues if item.code != "DOCUMENT_BASELINE_MISSING"]
            if allow_initial and not list((project / "docs" / "e2e").glob("*.md")):
                report.issues = [item for item in report.issues if item.code != "DOCUMENT_SCENARIO_UNASSIGNED"]
            report.state = "missing"
        else:
            report.state = "missing"
            if not allow_initial and status in {"draft", "awaiting_confirmation", "missing"}:
                report.issues.append(_issue("DOCUMENT_CONFIRMATION_REQUIRED", f"document state {status} requires confirmation"))
            return report
    report.state = status
    if baseline is None:
        report.current_commit = _git(project, "rev-parse", "HEAD")[0]
        if not allow_initial and status not in {"confirmed" if command == "generate" else "generated"}:
            report.issues.append(_issue("DOCUMENT_CONFIRMATION_REQUIRED", f"document state {status} cannot run {command}"))
            return report
        if command != "generate" or status != "confirmed":
            return report
    if not allow_initial:
        required = {"generate": {"confirmed", "generated"}, "init": {"draft", "awaiting_confirmation", "confirmed", "generated"}}.get(command, {"generated"})
        if status not in required:
            report.issues.append(_issue("DOCUMENT_CONFIRMATION_REQUIRED", f"document state {status} cannot run {command}"))
    report.state = status
    head, head_error = _git(project, "rev-parse", "HEAD")
    report.current_commit = head
    if head_error:
        report.issues.append(_issue("DOCUMENT_BASELINE_INVALID", f"cannot read HEAD: {head_error}")); return report
    if baseline and baseline != head:
        paths, diff_issues = _diff(project, baseline, head)
        report.issues.extend(diff_issues)
        for item in paths:
            status, _, filename = item.partition("\t")
            bucket = report.deleted if status.startswith("D") else report.added if status.startswith("A") else report.modified
            bucket.append(filename or item)
        changed_paths = report.modified + report.deleted + report.added
        state["pending_changes"] = {
            "added": report.added,
            "modified": report.modified,
            "deleted": report.deleted,
            "current_commit": head,
        }
        _save_state(project, state)
        deleted_docs = [path for path in report.deleted if path.startswith("docs/e2e/") and path.endswith(".md")]
        added_docs = [path for path in report.added if path.startswith("docs/e2e/") and path.endswith(".md")]
        if deleted_docs:
            report.issues.append(_issue("DOCUMENT_CONFIRMATION_REQUIRED", f"deleted scenario documents require confirmation: {', '.join(deleted_docs)}"))
        if added_docs and status not in {"confirmed", "generated"}:
            report.issues.append(_issue("DOCUMENT_OWNERSHIP_AMBIGUOUS", f"new scenario documents require ownership confirmation: {', '.join(added_docs)}"))
        report.affected_scenarios = [item["id"] for item in scenarios if any(item["document"] in path for path in changed_paths)]
        impact_terms = ("api", "rpc", "message", "queue", "order", "state", "db", "database", "task", "job", "lock", "transaction", "idempot", "retry", "consumer", "producer")
        source_changes = [
            path for path in changed_paths
            if not path.startswith("docs/e2e/")
            and (path.startswith("docs/biz-flow/") or
                 Path(path).suffix.lower() in {".py", ".js", ".ts", ".java", ".go", ".rs", ".sql"} or any(term in path.casefold() for term in impact_terms))
        ]
        if source_changes and scenarios:
            report.impact_analysis = _analyze_impact(project, source_changes, scenarios)
            report.affected_scenarios = sorted({*report.affected_scenarios, *(item["id"] for item in scenarios)})
            e2e_docs_changed = any(path.startswith("docs/e2e/") and path.endswith(".md") for path in changed_paths)
            if not e2e_docs_changed:
                report.issues.append(_issue("DOCUMENT_INCREMENTAL_UPDATE_REQUIRED", "source changes require updated e2e Markdown and review", project / source_changes[0]))
        if not report.affected_scenarios and not source_changes and not report.issues:
            report.no_document_impact = paths
    dirty, _ = _git(project, "status", "--porcelain")
    dirty_paths = [
        line[3:] for line in (dirty or "").splitlines()
        if len(line) > 3
        and not line[3:].startswith(("docs/e2e/", ".devflow/", ".devflow.lock.json", "artifacts/", "discovery/"))
    ]
    if dirty_paths:
        report.dirty_source_paths = dirty_paths[:20]
        if command != "source-status":
            for dirty_path in dirty_paths[:20]:
                report.issues.append(_issue("DOCUMENT_RELEVANT_DIRTY_SOURCE", "uncommitted source change", project / dirty_path))
    report.baseline_pending = bool(report.allowed and (baseline is None or baseline != head) and not dirty_paths)
    return report


def advance_baseline(project: Path, report: GateReport) -> bool:
    """Advance the lock only after the caller's downstream gate has passed."""
    if not report.allowed or not report.baseline_pending or not report.current_commit:
        return False
    path = project / "docs" / "e2e" / BASELINE_NAME
    path.write_text(f"git_commit: {report.current_commit}\n", encoding="utf-8")
    state = _load_state(project)
    if state:
        state.pop("pending_changes", None)
        _save_state(project, state)
    return True


def _candidate(requirements: list[str], sources: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    sources = sources or []
    refs_by_requirement: list[list[dict[str, str]]] = []
    for index, _ in enumerate(requirements):
        source = sources[index] if index < len(sources) else {}
        value = str(source.get("value", ""))
        if source.get("type") == "biz-flow" and "#" in value:
            file_name, section = value.split("#", 1)
            refs_by_requirement.append([{"file": file_name, "section": section}])
        else:
            refs_by_requirement.append([])
    return [{
        "id": f"E2E_CANDIDATE_{index:03d}",
        "name": requirement,
        "document": "",
        "objective": requirement,
        "business_entry": f"documented entry for requirement: {requirement}",
        "preconditions": ["test environment is available", "required business data is prepared"],
        "test_data": [f"inputs required by: {requirement}"],
        "key_steps": ["invoke the documented business entry", "observe the protocol response", "verify persistence and delivery effects"],
        "expected_results": [f"protocol result satisfies: {requirement}"],
        "exceptions_and_compensation": ["record protocol failure", "apply the documented compensation or retry policy"],
        "biz_flow_refs": refs_by_requirement[index - 1],
        "mermaid": "sequenceDiagram\n    autonumber\n    participant Client\n    participant Service\n    Client->>Service: invoke business entry\n    alt 分支1：协议成功\n        Service-->>Client: 协议成功，结果已落库，通知已投递\n    else 分支2：协议失败\n        Service-->>Client: 协议失败，结果未落库，通知未投递\n    end",
        "owner": "pending_confirmation",
    } for index, requirement in enumerate(requirements, 1)]


def initialize_document_state(project: Path, requirements: list[str] | None = None, *, sources: list[dict[str, str]] | None = None, confirm: bool = False, reject: bool = False, summary: str = "") -> dict[str, Any]:
    state = _load_state(project)
    if requirements:
        fingerprint = _fingerprint(requirements)
        source_head = _git(project, "rev-parse", "HEAD")[0]
        requirement_sources = sources or [{"type": "user", "value": item} for item in requirements]
        candidates = _candidate(requirements, requirement_sources)
        state = {"status": "awaiting_confirmation", "requirements": requirements, "requirement_sources": requirement_sources, "candidates": candidates, "candidate_fingerprint": _fingerprint(candidates), "input_fingerprint": fingerprint, "source_fingerprint": _fingerprint(source_head or requirements)}
    elif not state:
        state = {"status": "draft", "requirements": [], "requirement_sources": [], "candidates": [], "candidate_fingerprint": _fingerprint([]), "input_fingerprint": _fingerprint([]), "source_fingerprint": _fingerprint([])}
    if confirm and state.get("candidates"):
        missing_refs = [item for item in state.get("candidates", []) if not item.get("biz_flow_refs")]
        candidate_fingerprint = _fingerprint(state.get("candidates", []))
        current_head = _git(project, "rev-parse", "HEAD")[0]
        source_fingerprint = _fingerprint(current_head or state.get("requirements", []))
        if missing_refs or not _candidate_refs_valid(project, state.get("candidates", [])):
            state["status"] = "awaiting_confirmation"
            state["rejected_at"] = datetime.now(timezone.utc).isoformat()
            state["rejection_summary"] = "each candidate needs a real confirmed biz-flow file and section"
        elif candidate_fingerprint != state.get("candidate_fingerprint") or source_fingerprint != state.get("source_fingerprint"):
            state["status"] = "awaiting_confirmation"
            state["rejected_at"] = datetime.now(timezone.utc).isoformat()
            state["rejection_summary"] = "candidate or source inputs changed; regenerate draft before confirmation"
        else:
            state["status"] = "confirmed"
            state["confirmed_at"] = datetime.now(timezone.utc).isoformat()
            state["confirmation_summary"] = summary or "user confirmed candidate scenarios"
    if reject:
        state["status"] = "draft"
        state["rejected_at"] = datetime.now(timezone.utc).isoformat()
        state["rejection_summary"] = summary or "candidate scenarios rejected; regenerate before confirmation"
    _save_state(project, state)
    return state


def mark_generated(project: Path) -> dict[str, Any]:
    state = _load_state(project)
    if state.get("status") == "confirmed":
        state["status"] = "generated"
        _save_state(project, state)
    return state


__all__ = ["DocumentIssue", "GateReport", "advance_baseline", "initialize_document_state", "mark_generated", "run_document_gate", "validate_baseline", "validate_markdown"]
