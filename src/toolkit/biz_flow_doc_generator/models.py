"""Small value objects shared by biz-flow discovery and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class GitInfo:
    branch: str
    head: str
    target: str
    dirty: bool
    includes_uncommitted: bool
    comparison: str = "current"


@dataclass(slots=True)
class FunctionInfo:
    name: str
    start: int
    end: int
    body: str
    owner: str = ""
    signature: str = ""


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
    functions: list[str] = field(default_factory=list)
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
    coverage_gaps: list[dict] = field(default_factory=list)

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
