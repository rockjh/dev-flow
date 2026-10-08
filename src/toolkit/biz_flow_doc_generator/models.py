"""Small value objects shared by biz-flow discovery and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BranchEvidence:
    branch_id: str
    source_file: str
    source_line: int
    condition: str
    outcomes: list[str]
    effects: list[str]
    reachability: str = "reachable"
    business_relevant: bool | None = True


@dataclass(frozen=True, slots=True)
class PersistenceAction:
    persistence_id: str
    resource_type: str
    resource_name: str
    display_name: str
    operation: str
    condition: str | None
    fields: list[str]
    source_file: str
    source_line: int


@dataclass(slots=True)
class TaskRecord:
    run_id: str
    task_id: str
    parent_task_id: str | None
    role: str
    module_id: str | None = None
    entry_id: str | None = None
    batch_id: str | None = None
    status: str = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    result_hash: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskEvent:
    run_id: str
    sequence: int
    kind: str
    task_id: str
    timestamp: str
    batch_id: str | None = None
    task_ids: tuple[str, ...] = ()
    path: str | None = None
    result_hash: str | None = None


@dataclass(slots=True)
class GitInfo:
    branch: str
    head: str
    target: str
    dirty: bool
    includes_uncommitted: bool
    comparison: str = "current"


@dataclass(slots=True)
class ErrorEvidence:
    code: str
    condition: str
    file: str
    line: int
    capture_boundary: str = "代码中未确认"
    propagation: str = "代码中未确认"
    consequence: str = "代码中未确认"
    phase: str = "sync"
    recovery: str = "代码中未确认"


@dataclass(slots=True)
class BehaviorEvidence:
    kind: str
    statement: str
    file: str
    line: int


@dataclass(slots=True)
class FlowStep:
    kind: str
    text: str
    source: str
    participant: str = "当前系统"
    branch_ids: list[str] = field(default_factory=list)
    persistence_ids: list[str] = field(default_factory=list)
    sender: str = ""
    response: bool = False


@dataclass(slots=True)
class EntryReview:
    review_id: str
    trigger: str
    purpose: str
    input: str
    outcome: str
    failure: str
    steps: list[FlowStep] = field(default_factory=list)
    status: str = "draft"
    confirmed_by: str = ""
    title: str = ""


@dataclass(slots=True)
class FunctionInfo:
    name: str
    start: int
    end: int
    body: str
    calls: list[str] = field(default_factory=list)
    errors: list[ErrorEvidence] = field(default_factory=list)
    owner: str = ""
    qualified_calls: list[tuple[str, str]] = field(default_factory=list)
    signature: str = ""
    return_type: str = ""


@dataclass(slots=True)
class EntryPoint:
    entry_id: str
    kind: str
    identifier: str
    handler: str
    file: str
    line: int
    module: str
    source: str
    module_rationale: str = "代码中未确认"
    caller: str = "代码中未确认"
    input_summary: str = "代码中未确认"
    functions: list[str] = field(default_factory=list)
    errors: list[ErrorEvidence] = field(default_factory=list)
    behaviors: list[BehaviorEvidence] = field(default_factory=list)
    has_loop: bool = False
    has_external_call: bool = False
    has_persistence: bool = False
    has_async: bool = False
    review: EntryReview | None = None
    binding_confirmed: bool = True
    handler_confirmed: bool = True
    title: str = ""
    title_unresolved: bool = False
    # Presentation fields are evidence-linked and intentionally separate from
    # the structural trigger/handler fields above.
    business_name: str = ""
    module_label: str = ""
    module_description: str = ""
    trigger_summary: str = ""
    source_evidence: list[dict] = field(default_factory=list)
    scope_status: str = "business"
    exclusion_reason: str | None = None
    parent_entry_id: str = ""
    submit_source: str = ""
    agent_branches: list[dict] = field(default_factory=list)
    agent_persistence: list[dict] = field(default_factory=list)

    def error_codes(self) -> list[str]:
        return list(dict.fromkeys(error.code for error in self.errors))


@dataclass(slots=True)
class ScanResult:
    root: Path
    git: GitInfo
    languages: list[str]
    frameworks: list[str]
    entries: list[EntryPoint]
    files: list[str]
    unresolved: list[str]
    source_fingerprint: str = ""
    source_lines: dict[str, int] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    discovered_entry_count: int = -1
    discovered_binding_count: int = -1
    discovered_handler_count: int = -1
    # Complete source discovery, including candidates later excluded from
    # generation. ``entries`` is the active generation view after the module
    # map is applied; this snapshot keeps the user-facing overview complete.
    all_entries: list[EntryPoint] = field(default_factory=list)
    # 注册覆盖审计独立于行为分析，用于核对注册候选是否全部获得处理结论。
    registration_audit: list[dict] = field(default_factory=list)

    @property
    def candidate_entry_count(self) -> int:
        return len(self.entries) if self.discovered_entry_count < 0 else self.discovered_entry_count

    @property
    def confirmed_binding_count(self) -> int:
        return (
            sum(entry.binding_confirmed and entry.identifier != "代码中未确认" for entry in self.entries)
            if self.discovered_binding_count < 0 else self.discovered_binding_count
        )

    @property
    def confirmed_handler_count(self) -> int:
        return (
            len({entry.handler for entry in self.entries if entry.handler_confirmed and entry.handler != "代码中未确认"})
            if self.discovered_handler_count < 0 else self.discovered_handler_count
        )
