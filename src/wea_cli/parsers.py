"""Parsers for issue/task markdown bodies."""

from __future__ import annotations

import re


def normalize_header(header: str) -> str:
    lowered = header.lower().strip().rstrip(":")
    lowered = re.sub(r"\s*\([^)]*\)\s*", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def parse_field(body: str, aliases: list[str]) -> str | None:
    normalized_aliases = {normalize_header(alias) for alias in aliases}

    # Pattern 1: ## Header\nvalue  (markdown heading style)
    heading_pattern = re.compile(r"^##+\s*(.+?)\s*$\n+([^\n]+)", re.MULTILINE)
    for match in heading_pattern.finditer(body):
        header = normalize_header(match.group(1))
        if header in normalized_aliases:
            value = match.group(2).strip()
            return value or None

    # Pattern 2: **Header:** value  (bold inline style used in WEA task bodies)
    inline_pattern = re.compile(r"^\*\*(.+?)\*\*[:\s]+(.+?)\s*$", re.MULTILINE)
    for match in inline_pattern.finditer(body):
        header = normalize_header(match.group(1))
        if header in normalized_aliases:
            value = match.group(2).strip()
            return value or None

    return None


def parse_task_metadata(body: str) -> dict[str, str | None]:
    return {
        "agent_id": parse_field(body, ["Your Agent ID"]),
        "reward_type": parse_field(body, ["Reward Type"]),
        "reward": parse_field(body, ["Reward (WEA)", "Reward"]),
        "deadline": parse_field(body, ["Deadline", "Deadline (optional)"]),
        "skills_needed": parse_field(body, ["Skills Needed", "Skills"]),
    }
