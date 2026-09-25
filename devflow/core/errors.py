"""Stable process exit codes and structured command errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import re


class ExitCode(IntEnum):
    OK = 0
    INTERNAL = 1
    ARGUMENT = 2
    CREDENTIAL = 3
    NOT_FOUND = 4
    AMBIGUOUS = 5
    UNAVAILABLE = 6
    UNAUTHORIZED = 7
    GATE_FAILED = 8
    TEST_FAILED = 10


@dataclass(slots=True)
class DevflowError(Exception):
    code: str
    message: str
    exit_code: ExitCode = ExitCode.INTERNAL
    hint: str = ""
    details_path: str = ""

    def __str__(self) -> str:
        return self.message


def classify_failure(command: str, message: str, return_code: int) -> DevflowError:
    """Map legacy domain failures to the public semantic exit contract."""

    text = message.lower()
    document_code = re.search(r"\b(DOCUMENT_[A-Z_]+)\b", message)
    if document_code:
        return DevflowError(document_code.group(1), message, ExitCode.GATE_FAILED)
    if return_code == int(ExitCode.ARGUMENT) and ("usage:" in text or "error:" in text):
        return DevflowError("INVALID_ARGUMENT", message, ExitCode.ARGUMENT)
    if any(token in text for token in ("credential", "credentials", "secret is missing", "token is missing")):
        return DevflowError("CREDENTIAL_INVALID", message, ExitCode.CREDENTIAL)
    if any(token in text for token in ("does not exist", "not found", "no such file", "missing target")):
        return DevflowError("TARGET_NOT_FOUND", message, ExitCode.NOT_FOUND)
    if any(token in text for token in ("ambiguous", "cannot be uniquely", "multiple matches")):
        return DevflowError("TARGET_AMBIGUOUS", message, ExitCode.AMBIGUOUS)
    if any(token in text for token in ("unavailable", "connection refused", "timed out", "executable was not found")):
        return DevflowError("EXTERNAL_UNAVAILABLE", message, ExitCode.UNAVAILABLE)
    if any(token in text for token in ("authorization", "not authorized", "permission denied", "requires approval")):
        return DevflowError("AUTHORIZATION_REQUIRED", message, ExitCode.UNAUTHORIZED)
    if return_code == int(ExitCode.GATE_FAILED):
        return DevflowError("GATE_FAILED", message, ExitCode.GATE_FAILED)
    if return_code == int(ExitCode.TEST_FAILED):
        return DevflowError("TEST_FAILED", message, ExitCode.TEST_FAILED)
    if command.endswith((".run", ".reconcile", ".aggregate")):
        return DevflowError("TEST_FAILED", message, ExitCode.TEST_FAILED)
    return DevflowError("GATE_FAILED", message, ExitCode.GATE_FAILED)
