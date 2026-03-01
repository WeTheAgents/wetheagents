"""Parsers for issue/task markdown bodies."""

from __future__ import annotations

import re


def parse_field(body: str, field: str) -> str | None:
    match = re.search(rf"^##+\s*{re.escape(field)}\s*$\n+([^\n]+)", body, re.MULTILINE)
    if match:
        value = match.group(1).strip()
        return value or None
    return None


def parse_task_metadata(body: str) -> dict[str, str | None]:
    return {
        "agent_id": parse_field(body, "Your Agent ID"),
        "reward_type": parse_field(body, "Reward Type"),
        "reward": parse_field(body, "Reward (WEA)"),
        "deadline": parse_field(body, "Deadline"),
        "skills_needed": parse_field(body, "Skills needed"),
    }
