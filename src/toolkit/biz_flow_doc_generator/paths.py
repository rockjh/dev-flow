"""Filesystem paths for committed snapshots; public artifact pointers stay normal."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def io_path(path: Path) -> Path:
    """Prefix every Windows IO root: its descendants can exceed MAX_PATH."""
    if os.name != "nt":
        return path
    value = os.path.abspath(path)
    if value.startswith("\\\\?\\"):
        return Path(value)
    return Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)


def normal_path(path: Path) -> Path:
    """Git for Windows expects ordinary paths at its process boundary."""
    value = str(path)
    if os.name == "nt" and value.startswith("\\\\?\\"):
        return Path("\\\\" + value[8:] if value.startswith("\\\\?\\UNC\\") else value[4:])
    return path


def is_alias(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", None) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def snapshot_files(root: Path) -> list[Path]:
    """Inspect aliases before opening files, including junctions on Python 3.11."""
    root = io_path(root)
    if is_alias(root):
        raise ValueError("SOURCE_PATH_UNSAFE")
    files = []
    def fail(error):
        raise error
    for directory, children, names in os.walk(root, followlinks=False, onerror=fail):
        paths = [Path(directory) / name for name in [*children, *names]]
        if any(is_alias(path) for path in paths):
            raise ValueError("SOURCE_PATH_UNSAFE")
        files.extend(Path(directory) / name for name in names)
    return sorted(files)
