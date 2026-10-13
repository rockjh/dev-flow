"""Source resolution and module write guards; execution belongs to the host session."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileWriteGuard:
    owner_task_id: str
    writable_file: str
    docs_root: str | None = None

    def assert_allowed(self, task_id, path):
        raw = str(path).replace("\\", "/")
        if (task_id != self.owner_task_id or raw != self.writable_file or Path(raw).name != raw
                or ":" in raw or ".." in raw or not raw.endswith(".md")):
            raise PermissionError("MODULE_FILE_INVALID: WRITE_DENIED")
        if self.docs_root and (Path(self.docs_root) / raw).resolve().parent != Path(self.docs_root).resolve():
            raise PermissionError("MODULE_FILE_INVALID: WRITE_DENIED")
