"""Redact credentials before data reaches stdout or persisted reports."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|passphrase|secret|token|authorization|credential|cookie|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|dsn)$",
    re.IGNORECASE,
)
AUTH_HEADER = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"
)
AUTH_SCHEME = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
URL_USERINFO = re.compile(r"(?i)(://[^/@:\s]+:)[^/@\s]+(@)")
SENSITIVE_TEXT = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|secret|token|credential|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret|dsn)\s*[:=]\s*)([^\s,;]+)"
)
STRUCTURED_MARKER = re.compile(
    r"<!--\s*(?:biz-flow-entry|devflow:(?:module|module-confirmed|exclude)\b).*?-->\s*",
    re.DOTALL | re.IGNORECASE,
)


def redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        markers: list[str] = []
        def hold(match: re.Match[str]) -> str:
            markers.append(match.group(0))
            return f"\x00DEVFLOW_MARKER_{len(markers) - 1}\x00"
        value = STRUCTURED_MARKER.sub(hold, value)
        value = AUTH_HEADER.sub(lambda match: f"{match.group(1)}: [REDACTED]", value)
        value = AUTH_SCHEME.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
        value = URL_USERINFO.sub(r"\1[REDACTED]\2", value)
        value = SENSITIVE_TEXT.sub(r"\1[REDACTED]", value)
        for index, marker in enumerate(markers):
            value = value.replace(f"\x00DEVFLOW_MARKER_{index}\x00", marker)
        return value
    return value
