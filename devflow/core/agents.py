"""Statically registered CLI backends. Probes read help; execution is ephemeral."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REQUIRED_CAPABILITIES = ("real_child_agents", "read_only_source", "brokered_module_writes")


def _parse_json_text(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("structured response must be an object")
    return parsed


@dataclass(frozen=True)
class CodexAdapter:
    name: str = "codex"

    def help_command(self, executable: str) -> list[str]:
        return [executable, "exec", "--help"]

    def required_flags(self) -> tuple[str, ...]:
        return ("--json", "--sandbox", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check")

    def command(self, executable: str) -> list[str]:
        return [executable, "exec", "--json", "--sandbox", "read-only", "--ephemeral",
                "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "-"]

    def parse(self, output: str) -> dict[str, Any]:
        events = [json.loads(line) for line in output.splitlines() if line.strip()]
        if any(event.get("type") in {"error", "turn.failed"} for event in events):
            raise ValueError("AGENT_EXECUTOR_FAILED")
        if any(event.get("item", {}).get("type") == "file_change" for event in events):
            raise ValueError("WRITE_DENIED")
        messages = [event["item"]["text"] for event in events
                    if event.get("type") == "item.completed"
                    and event.get("item", {}).get("type") == "agent_message"]
        if not messages or not any(event.get("type") == "turn.completed" for event in events):
            raise ValueError("AGENT_EXECUTOR_RESULT_MISSING")
        return _parse_json_text(messages[-1])


@dataclass(frozen=True)
class ClaudeAdapter:
    name: str = "claude"

    def help_command(self, executable: str) -> list[str]:
        return [executable, "--help"]

    def required_flags(self) -> tuple[str, ...]:
        return ("--print", "--output-format", "--tools", "--restricted", "--disallowedTools", "--strict-mcp-config",
                "--mcp-config", "--setting-sources", "--settings", "--no-session-persistence")

    def command(self, executable: str) -> list[str]:
        # Source evidence is supplied on stdin. No filesystem or external tools
        # are available to the agent; project/user hooks are disabled explicitly.
        return [executable, "--print", "--output-format", "json", "--restricted", "--tools", "Read",
                "--disallowedTools", "mcp__*", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                "--no-session-persistence"]

    def parse(self, output: str) -> dict[str, Any]:
        response = json.loads(output)
        if response.get("is_error") is not False or response.get("type") != "result":
            raise ValueError("AGENT_EXECUTOR_FAILED")
        structured = response.get("structured_output")
        if isinstance(structured, dict):
            return structured
        raw = response["result"]
        return raw if isinstance(raw, dict) else _parse_json_text(raw)


# The runtime intentionally has one static backend list. Custom hosts use the
# explicit DEVFLOW_AGENT_EXECUTOR protocol instead of registering extensions.
BUILTIN_AGENT_ADAPTERS = (CodexAdapter(), ClaudeAdapter())


def probe_adapter(adapter: Any) -> tuple[str | None, dict[str, bool]]:
    executable = shutil.which(adapter.name)
    if not executable:
        return None, {}
    try:
        help_result = subprocess.run(adapter.help_command(executable), stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                                     timeout=5, check=False)
        if help_result.returncode or not all(flag in help_result.stdout for flag in adapter.required_flags()):
            return None, {}
    except (OSError, subprocess.SubprocessError):
        return None, {}
    # The runtime starts one isolated CLI process per entry. The adapter's
    # flags constrain source access; only the runtime broker can write Markdown.
    return executable, {"read_only_source": True, "brokered_module_writes": True}


def run_entry(adapter: Any, executable: str, prompt: str, *, cwd: Path | None = None,
              started: Callable[[], None] | None = None,
              finished: Callable[[], None] | None = None) -> dict[str, Any]:
    # A supplied project root is read-only by adapter flags; no alternate
    # project config is loaded. A temp cwd remains the safe default for callers.
    temporary_context = tempfile.TemporaryDirectory(prefix="devflow-agent-") if cwd is None else None
    working_directory = str(cwd or temporary_context.name)
    try:
        try:
            process = subprocess.Popen(adapter.command(executable), cwd=working_directory,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace")
            try:
                if started:
                    started()
                output, _ = process.communicate(prompt, timeout=1800)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            finally:
                if finished:
                    finished()
        except subprocess.TimeoutExpired:
            raise RuntimeError("AGENT_EXECUTOR_TIMEOUT") from None
        if process.returncode:
            # Raw CLI stderr may contain prompts, credentials or source payloads.
            raise RuntimeError(f"AGENT_EXECUTOR_FAILED: {adapter.name} exit {process.returncode}")
        try:
            value = adapter.parse(output)
            if not isinstance(value, dict):
                raise ValueError("result must be an object")
            return value
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("AGENT_EXECUTOR_PROTOCOL_INVALID") from None
    finally:
        if temporary_context is not None:
            temporary_context.cleanup()
