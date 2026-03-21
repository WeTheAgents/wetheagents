"""Translate Claude Code hook payloads into wea trace events."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from wea_cli.trace import emit_event

# Source identifier used for all hook-derived events.
_SOURCE = "wea-hooks"


def _tool_input_summary(tool_name: str, tool_input: dict) -> str:
    """Derive a short summary string from a tool's input dict.

    Rules:
    - Bash: first 100 chars of tool_input["command"]
    - Write / Edit: tool_input["file_path"]
    - Read: tool_input["file_path"]
    - All others: tool_name
    """
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return str(command)[:100]
    if tool_name in ("Write", "Edit", "Read"):
        return str(tool_input.get("file_path", tool_name))
    return tool_name


def _handle_session_start(payload: dict, run_dir: Path) -> int:
    """Translate SessionStart hook into auth_ok event."""
    event_payload = {
        "session_id": payload.get("session_id", ""),
        "model": payload.get("model", ""),
        "source": payload.get("source", "startup"),
    }
    emit_event(run_dir=run_dir, event_type="auth_ok", source=_SOURCE, payload=event_payload)
    return 0


def _handle_pre_tool_use(payload: dict, run_dir: Path) -> int:
    """Translate PreToolUse hook into tool_started event."""
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    event_payload = {
        "tool_name": tool_name,
        "tool_use_id": payload.get("tool_use_id", ""),
        "tool_input_summary": _tool_input_summary(tool_name, tool_input),
    }
    emit_event(run_dir=run_dir, event_type="tool_started", source=_SOURCE, payload=event_payload)
    return 0


def _handle_post_tool_use(payload: dict, run_dir: Path) -> int:
    """Translate PostToolUse hook into tool_finished event."""
    tool_name = payload.get("tool_name", "")
    tool_response = payload.get("tool_response") or {}

    # Determine success: check tool_response["success"] if present, else assume True.
    if "success" in tool_response:
        success = bool(tool_response["success"])
    else:
        success = True

    event_payload = {
        "tool_name": tool_name,
        "tool_use_id": payload.get("tool_use_id", ""),
        "success": success,
    }
    emit_event(run_dir=run_dir, event_type="tool_finished", source=_SOURCE, payload=event_payload)
    return 0


def _handle_stop(payload: dict, run_dir: Path) -> int:
    """Translate Stop hook into run_completed event."""
    event_payload = {
        "session_id": payload.get("session_id", ""),
        "stop_hook_active": payload.get("stop_hook_active", False),
    }
    emit_event(run_dir=run_dir, event_type="run_completed", source=_SOURCE, payload=event_payload)
    return 0


def _handle_subagent_stop(payload: dict, run_dir: Path) -> int:
    """Translate SubagentStop hook into milestone event."""
    event_payload = {
        "milestone": "subagent_completed",
        "agent_type": payload.get("agent_type", ""),
        "agent_id": payload.get("agent_id", ""),
    }
    emit_event(run_dir=run_dir, event_type="milestone", source=_SOURCE, payload=event_payload)
    return 0


_HANDLERS = {
    "SessionStart": _handle_session_start,
    "PreToolUse": _handle_pre_tool_use,
    "PostToolUse": _handle_post_tool_use,
    "Stop": _handle_stop,
    "SubagentStop": _handle_subagent_stop,
}


def handle_hook(payload: dict, run_dir: Path | None = None) -> int:
    """Translate a Claude Code hook payload into a trace event.

    Args:
        payload: Hook payload dict (from stdin JSON)
        run_dir: Run directory. If None, uses WEA_RUN_DIR env var.
                 If neither available, returns 0 (fail open).

    Returns:
        0 on success or fail-open, 1 on hard error.
    """
    # Resolve run_dir — fail open if not available.
    if run_dir is None:
        env_val = os.environ.get("WEA_RUN_DIR")
        if not env_val:
            # No run directory configured — silently succeed (fail open).
            return 0
        run_dir = Path(env_val)

    # Validate hook_event_name — fail open for malformed or unknown hooks.
    hook_event_name = payload.get("hook_event_name")
    if not hook_event_name:
        print(
            "wea-hooks warning: missing 'hook_event_name' in payload — skipping",
            file=sys.stderr,
        )
        return 0

    handler = _HANDLERS.get(hook_event_name)
    if handler is None:
        # Unknown hook — forward-compatible, silently succeed.
        return 0

    try:
        handler(payload, run_dir)
    except Exception as exc:
        print(
            f"wea-hooks warning: failed to emit event for {hook_event_name}: {exc}",
            file=sys.stderr,
        )
        return 0

    return 0
