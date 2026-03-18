"""Step validator — detects agent loops (repeated tool calls).

Purely deterministic: no LLM calls, no extra latency.
Injects warnings into tool results when the agent re-reads the same file,
re-lists the same directory, or re-searches the same pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models import (
    ListTool,
    OutlineTool,
    ReadTool,
    SearchTool,
    ToolAction,
)


def _tool_key(tool: ToolAction) -> str:
    """Dedup key: tool_name + primary argument."""
    match tool:
        case ReadTool(path=p):
            return f"read:{p}"
        case ListTool(path=p):
            return f"list:{p}"
        case OutlineTool(path=p):
            return f"outline:{p}"
        case SearchTool(pattern=pat, path=path):
            return f"search:{pat}@{path}"
        case _:
            # Write, Delete, ReportCompletion — never flag as loops
            return ""


@dataclass
class StepValidator:
    """Tracks tool call history and detects loops.

    Only read-type calls (read, list, outline, search) are tracked.
    Write/delete are intentional actions and not flagged.
    """

    call_counts: dict[str, int] = field(default_factory=dict)

    def check(self, tool: ToolAction) -> str | None:
        """Return a warning string if loop detected, None otherwise."""
        key = _tool_key(tool)
        if not key:
            return None  # skip write/delete/report

        self.call_counts[key] = self.call_counts.get(key, 0) + 1
        count = self.call_counts[key]

        if count == 2:
            return (
                f"DUPLICATE: You already called {key}. "
                f"Use the information you already have."
            )
        if count >= 3:
            return (
                f"LOOP ({count}x): {key}. "
                f"STOP re-reading. Act on what you know. "
                f"If ready, call report_completion NOW."
            )
        return None
