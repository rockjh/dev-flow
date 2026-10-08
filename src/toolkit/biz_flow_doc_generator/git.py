"""Git metadata and read-only source snapshots for biz-flow analysis."""

from __future__ import annotations

import subprocess
import re
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import GitInfo


def _run(root: Path, *args: str) -> str:
    if sys.platform == "win32":
        # Windows 下 Git 的管道捕获可能成功退出却丢失输出；文件句柄同时保护提交号和工作区状态。
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            result = subprocess.run(["git", *args], cwd=root, stdout=output, stderr=error)
            output.seek(0)
            error.seek(0)
            result.stdout = output.read().decode("utf-8", errors="replace")
            result.stderr = error.read().decode("utf-8", errors="replace")
        result.check_returncode()
        return result.stdout.strip()
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.stdout.strip()


def _status_paths(root: Path) -> list[str]:
    """通过必有的分支表头验证输出完整性，禁止把空输出解释为干净工作区。"""
    lines = _run(root, "status", "--porcelain", "--branch").splitlines()
    if not lines or not lines[0].startswith("## "):
        raise RuntimeError("Git 工作区状态读取失败：缺少分支表头")
    return [line for line in lines[1:] if line.strip()]


def git_info(root: Path, target: str | None = None) -> GitInfo:
    def commit(reference: str) -> str:
        """只接受完整提交号；一次空输出重读，避免误把工作区当历史快照。"""
        for _ in range(2):
            value = _run(root, "rev-parse", "--verify", reference)
            if re.fullmatch(r"[0-9a-f]{40,64}", value):
                return value
        raise RuntimeError(f"Git 提交号读取失败：{reference}")

    head = commit("HEAD")
    branch = _run(root, "branch", "--show-current") or "(detached)"
    dirty = bool(_status_paths(root))
    target_hash = commit(target) if target else head
    return GitInfo(
        branch=branch,
        head=head,
        target=target_hash,
        dirty=dirty,
        includes_uncommitted=dirty and target_hash == head,
        comparison="current" if target_hash == head else "snapshot",
    )


@contextmanager
def source_view(root: Path, target: str | None = None) -> Iterator[tuple[Path, GitInfo]]:
    """Yield the worktree for HEAD, or an extracted read-only target snapshot."""

    info = git_info(root, target)
    if info.target == info.head:
        yield root, info
        return
    with tempfile.TemporaryDirectory(prefix="devflow-biz-flow-") as temporary:
        archive = Path(temporary) / "source.zip"
        subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), info.target], cwd=root, check=True)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(temporary)
        yield Path(temporary), info


def changed_paths(root: Path, old: str, new: str) -> tuple[list[str], str | None]:
    try:
        old_hash = _run(root, "rev-parse", old)
        new_hash = _run(root, "rev-parse", new)
        output = _run(root, "diff", "--name-status", old_hash, new_hash)
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], str(exc)
    return [line for line in output.splitlines() if line.strip()], None


def working_tree_paths(root: Path) -> list[str]:
    """Return porcelain paths so uncommitted business edits affect incremental review."""

    return _status_paths(root)
