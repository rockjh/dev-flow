"""Read-only source inventories and static adapter coordination."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..core.errors import DevflowError, ExitCode
from .models import AnalysisScope, CoverageGap, DiscoveryCatalog, FlowModel, ProjectContext, SourceFile, SourceSnapshot
from .repository import bytes_digest, confined, digest
from .adapters._tree import trees, walk

EXTENSIONS = {".py": "python", ".java": "java", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
              ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".go": "go", ".rs": "rust"}
EXCLUDED = frozenset({".git", ".venv", "venv", "env", "node_modules", "target", "dist", "build", "__pycache__",
                      ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".idea"})
CONFIGS = frozenset({"pyproject.toml", "requirements.txt", "requirements.lock", "poetry.lock", "uv.lock", "pom.xml",
                    "build.gradle", "build.gradle.kts", "settings.gradle", "package.json", "package-lock.json", "yarn.lock",
                    "pnpm-lock.yaml", "tsconfig.json", "go.mod", "go.sum", "go.work", "Cargo.toml", "Cargo.lock"})


class ProjectScanner:
    def __init__(self, registry):
        self.registry = registry

    def snapshot(self, context: ProjectContext) -> SourceSnapshot:
        files, contents = [], []
        size = 0
        for parent, directories, names in os.walk(context.project, followlinks=False):
            parent_path = confined(Path(parent), context.project)
            kept = []
            for name in sorted(directories):
                if name in EXCLUDED:
                    continue
                child = confined(parent_path / name, context.project)
                if child == context.assets:
                    continue
                # Junctions within the project still risk cycles: do not traverse aliases.
                if (parent_path / name).is_symlink() or (hasattr(Path, "is_junction") and (parent_path / name).is_junction()):
                    raise DevflowError("GATE_FAILED", f"source directory alias requires explicit scope: {name}", ExitCode.GATE_FAILED)
                kept.append(name)
            directories[:] = kept
            for name in sorted(names):
                path = parent_path / name
                language = EXTENSIONS.get(path.suffix.lower(), "")
                if not language and name not in CONFIGS and not name.startswith("tsconfig."):
                    continue
                resolved = confined(path, context.project)
                if resolved.is_relative_to(context.assets):
                    continue
                if resolved.stat().st_size > 10 * 1024 * 1024:
                    raise DevflowError("GATE_FAILED", f"source file exceeds 10MiB: {name}", ExitCode.GATE_FAILED)
                with resolved.open("rb") as stream:
                    raw = stream.read(10 * 1024 * 1024 + 1)
                size += len(raw)
                if len(raw) > 10 * 1024 * 1024 or size > 100 * 1024 * 1024 or len(files) >= 10000:
                    raise DevflowError("GATE_FAILED", "source inventory resource limit exceeded; narrow the project", ExitCode.GATE_FAILED)
                relative = path.relative_to(context.project).as_posix()
                files.append(SourceFile(relative, bytes_digest(raw), language, len(raw)))
                contents.append((relative, raw))
        files.sort(key=lambda item: item.path)
        contents.sort()
        configs = tuple(item for item in files if not item.language)
        commit, dirty = "", True
        git = shutil.which("git")
        if git and (context.project / ".git").exists():
            arguments = [git, "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", str(context.project)]
            for command in (("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=no")):
                result = subprocess.run([*arguments, *command], capture_output=True, text=True, timeout=10, check=False)
                if result.returncode == 0:
                    if command[0] == "rev-parse":
                        commit = result.stdout.strip()
                    else:
                        dirty = bool(result.stdout.strip())
        return SourceSnapshot(tuple(files), digest(tuple((item.path, item.digest) for item in files)), commit, dirty, digest(configs), tuple(contents))

    def discover(self, snapshot: SourceSnapshot) -> DiscoveryCatalog:
        symbols, gaps, capabilities = [], [], []
        for file, _, root in trees(snapshot, {"java", "javascript", "typescript", "go", "rust"}):
            for node in walk(root):
                if node.type == "ERROR" or node.is_missing:
                    gaps.append(CoverageGap("PARSE_ERROR" if node.type == "ERROR" else "PARSE_MISSING", file.path,
                                           f"line:{node.start_point.row + 1}", "", (), True, "incomplete syntax; declarations may be missing"))
        seen_adapters = set()
        for language in sorted({item.language for item in snapshot.files if item.language}):
            adapter = self.registry.get(language)
            capabilities.append(adapter.capabilities(language) if language in {"javascript", "typescript"} else adapter.capabilities())
            if id(adapter) in seen_adapters:
                continue
            seen_adapters.add(id(adapter))
            try:
                symbols.extend(adapter.discover(snapshot))
            except SyntaxError as exc:
                gaps.append(CoverageGap("PARSE_ERROR", str(exc.filename), f"line:{exc.lineno}", "", (), True, str(exc)))
        ids = [item.symbol_id for item in symbols]
        if len(ids) != len(set(ids)):
            raise DevflowError("TARGET_AMBIGUOUS", "source symbol IDs collide", ExitCode.AMBIGUOUS)
        return DiscoveryCatalog(tuple(sorted(symbols, key=lambda item: (item.path, item.qualified_name, item.signature))), tuple(gaps), tuple(capabilities))

    def analyze(self, snapshot: SourceSnapshot, scopes: tuple[AnalysisScope, ...]) -> FlowModel:
        results = tuple(self.registry.get(scope.symbol.language).analyze(snapshot, scope) for scope in scopes)
        return FlowModel(results, snapshot.fingerprint, self.registry.fingerprint())
