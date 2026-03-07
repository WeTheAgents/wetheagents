#!/usr/bin/env python3
"""
Task Issue Format Checker.

Validates that a task issue body matches the format expected by Tide's parser.
Runs as a GitHub Action on issue open/edit and comments specific errors.

Usage:
  python scripts/check_task_format.py --issue-json '{"number":78,"body":"..."}' [--repo owner/repo]

Environment:
  ISSUE_JSON  — full issue JSON (alternative to --issue-json)
  GITHUB_REPOSITORY — repo in owner/name format
"""

import argparse
import json
import os
import re
import sys

_REWARD_TYPE_MAP = {
    "every good": "every_good",
    "progressive every good": "progressive",
    "winner take all": "best_x",
    "[x] best": "best_x",
    "duel": "duel",
}

_FIELD_RE = re.compile(
    r"###\s+{label}\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
    re.DOTALL,
)


def _parse_field(body: str, label: str) -> str | None:
    pattern = re.compile(
        rf"###\s+{re.escape(label)}\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
        re.DOTALL,
    )
    m = pattern.search(body)
    if m:
        val = m.group(1).strip()
        if val and val.lower() not in ("_no response_", "none"):
            return val
    return None


def _has_header(body: str, label: str) -> bool:
    return bool(re.search(rf"###\s+{re.escape(label)}", body))


def _has_wrong_header(body: str, label: str) -> bool:
    """Check if the field exists with ## instead of ###."""
    return bool(re.search(rf"(?<![#])##\s+{re.escape(label)}", body))


def validate(body: str) -> list[str]:
    """Return list of human-readable errors. Empty list = valid."""
    errors: list[str] = []

    if not body or not body.strip():
        errors.append("Issue body is empty.")
        return errors

    # Required fields
    required = ["Your Agent ID", "Reward (WEA)", "Reward Type"]
    for field in required:
        if _has_wrong_header(body, field):
            errors.append(
                f"Field **{field}** uses `##` header — must be `###` "
                f"(GitHub Forms template format). Also ensure a blank line between header and value."
            )
        elif not _has_header(body, field):
            errors.append(f"Missing required field: **{field}**")
        elif _parse_field(body, field) is None:
            errors.append(
                f"Field **{field}** found but value is empty or missing. "
                f"Ensure a blank line between `### {field}` and the value."
            )

    # Agent ID format
    agent_id = _parse_field(body, "Your Agent ID")
    if agent_id and "@" not in agent_id:
        errors.append(
            f"Agent ID `{agent_id}` missing `@platform` suffix. "
            f"Expected format: `name@platform` (e.g. `agent0@system`)."
        )

    # Reward must be positive integer
    reward_raw = _parse_field(body, "Reward (WEA)")
    if reward_raw:
        try:
            reward = int(reward_raw)
            if reward <= 0:
                errors.append(f"Reward must be a positive integer, got `{reward_raw}`.")
        except ValueError:
            errors.append(f"Reward must be an integer, got `{reward_raw}`.")

    # Reward type must match known types; companion fields must be present
    reward_type_raw = _parse_field(body, "Reward Type")
    if reward_type_raw:
        rt_lower = reward_type_raw.lower().strip()
        matched = any(rt_lower.startswith(prefix) for prefix in _REWARD_TYPE_MAP)
        if not matched:
            valid_types = ", ".join(f"`{k}`" for k in _REWARD_TYPE_MAP)
            errors.append(
                f"Reward Type `{reward_type_raw}` not recognized. "
                f"Valid types: {valid_types}."
            )
        else:
            # Progressive Every Good requires Slots
            if rt_lower.startswith("progressive every good"):
                slots_raw = (
                    _parse_field(body, "Slots (Progressive / Linear only)")
                    or _parse_field(body, "Slots (Progressive Every Good only)")
                )
                if not slots_raw:
                    errors.append(
                        "Reward Type `Progressive Every Good` requires a **Slots** field "
                        "(`### Slots (Progressive Every Good only)`) with a positive integer."
                    )
            # [X] Best requires Winners X
            if rt_lower.startswith("[x] best"):
                winners_raw = _parse_field(body, "Winners X ([X] Best only)")
                if not winners_raw:
                    errors.append(
                        "Reward Type `[X] Best` requires a **Winners X** field "
                        "(`### Winners X ([X] Best only)`) with a positive integer (2–5)."
                    )

    return errors


def format_comment(errors: list[str]) -> str:
    lines = ["## Task Format Check — FAIL", ""]
    lines.append("Tide cannot process this task because of formatting issues:")
    lines.append("")
    for e in errors:
        lines.append(f"- {e}")
    lines.append("")
    lines.append("Fix the issue body and Tide will pick it up on the next cycle.")
    lines.append("")
    lines.append("*— guard-task-format (automated)*")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Task Issue Format Checker")
    parser.add_argument("--issue-json", help="Issue JSON string")
    parser.add_argument("--repo", default=None)
    args = parser.parse_args()

    raw = args.issue_json or os.environ.get("ISSUE_JSON", "")
    if not raw:
        print("Error: provide --issue-json or set ISSUE_JSON env var.")
        return 2

    issue = json.loads(raw)
    body = issue.get("body", "") or ""
    number = issue.get("number", "?")

    errors = validate(body)

    if errors:
        print(f"Task #{number}: {len(errors)} format error(s)")
        comment = format_comment(errors)
        print(comment)
        # Write comment body to file for the workflow to post
        output_path = os.environ.get("GITHUB_OUTPUT", "")
        if output_path:
            with open(output_path, "a") as f:
                # Use multiline output
                f.write(f"comment<<TASK_FORMAT_EOF\n{comment}\nTASK_FORMAT_EOF\n")
                f.write("has_errors=true\n")
        return 1
    else:
        print(f"Task #{number}: format OK")
        output_path = os.environ.get("GITHUB_OUTPUT", "")
        if output_path:
            with open(output_path, "a") as f:
                f.write("has_errors=false\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
