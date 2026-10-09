"""One fixed adapter table; no plugins or scanning at runtime."""
from pathlib import Path

from ... import __version__
from ...core.errors import DevflowError, ExitCode
from .. import SCHEMA_VERSION, SKILL_VERSION
from ..repository import bytes_digest, digest
from .go import GoAdapter
from .java import JavaAdapter
from .javascript import JavaScriptAdapter
from .python import PythonAdapter
from .rust import RustAdapter

IMPLEMENTATIONS = ("__init__.py", "base.py", "registry.py", "analysis.py", "_tree.py", "python.py", "java.py", "javascript.py", "go.py", "rust.py")


class AdapterRegistry:
    def __init__(self):
        javascript = JavaScriptAdapter()
        self._adapters = {"python": PythonAdapter(), "java": JavaAdapter(), "javascript": javascript,
                          "typescript": javascript, "go": GoAdapter(), "rust": RustAdapter()}

    def get(self, language):
        try:
            return self._adapters[language]
        except KeyError as exc:
            raise DevflowError("EXTERNAL_UNAVAILABLE", f"unsupported language: {language}", ExitCode.UNAVAILABLE) from exc

    def fingerprint(self):
        root = Path(__file__).parent
        implementations = tuple((name, bytes_digest((root / name).read_bytes())) for name in IMPLEMENTATIONS)
        implementations += (("control_flow.py", bytes_digest((root.parent / "control_flow.py").read_bytes())),)
        capabilities = tuple(adapter.capabilities(language) if language in {"javascript", "typescript"} else adapter.capabilities()
                             for language, adapter in self._adapters.items())
        return digest((__version__, SKILL_VERSION, SCHEMA_VERSION, implementations, capabilities))
