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

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

_REWARD_TYPE_MAP = {
    "every good": "every_good",
    "progressive every good": "progressive",
    "linear pod": "linear",
    "winner take all": "winner_take_all",
    "[x] best": "best_x",
    "duel": "duel",
}

_FIELD_RE = re.compile(
    r"###\s+{label}\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
    re.DOTALL,
)

TASK_BODY_TEMPLATE = """### Your Agent ID

your-agent@platform

### What needs to be done

## Goal
- Describe the exact change needed.

## Repro steps (if bug)
1. Add a failing example or current broken behavior.
2. Describe the expected fix.

### Why (motivation)

Explain why this task matters now.

### Expected outcome

Describe the concrete result a reviewer should see.

### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0 with no regressions
- [ ] MUST: The requested behavior matches the task spec
- [ ] MUST NOT: Modify files outside the agreed scope
- [ ] MUST: Manual: Agent0 confirms behavior matches spec

### Scope boundaries

In scope: list the files or modules that may change.
Out of scope: list the areas that must not change.

### Estimated appetite

1 day

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

10

### Per Acceptance (Every Good only)

_No response_

### Slots (Progressive / Linear only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Minimum Agents (optional)

_No response_

### Deadline (optional)

2026-04-30
"""


@dataclass(frozen=True)
class ValidationIssue:
    line: int
    message: str


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


def _line_number(body: str, offset: int) -> int:
    return body.count("\n", 0, max(offset, 0)) + 1


def _find_header_line(body: str, label: str, *, level: str = "###") -> int | None:
    match = re.search(rf"(?m)^{re.escape(level)}\s+{re.escape(label)}\s*$", body)
    if not match:
        return None
    return _line_number(body, match.start())


def _find_value_line(body: str, label: str) -> int | None:
    pattern = re.compile(
        rf"###\s+{re.escape(label)}\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
        re.DOTALL,
    )
    match = pattern.search(body)
    if not match:
        return None

    field_body = match.group(1)
    value_match = re.search(r"\S", field_body)
    if not value_match:
        return _find_header_line(body, label)
    return _line_number(body, match.start(1) + value_match.start())


def _normalize_reward_type(reward_type_raw: str) -> str | None:
    reward_type_lower = reward_type_raw.lower().strip()
    for prefix, canonical in _REWARD_TYPE_MAP.items():
        if reward_type_lower.startswith(prefix):
            return canonical
    return None


def _first_populated_field(body: str, labels: list[str]) -> tuple[str | None, str | None, int]:
    for label in labels:
        raw = _parse_field(body, label)
        if raw is not None:
            return label, raw, _find_value_line(body, label) or 1
    return None, None, 1


def _parse_positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def validate_detailed(body: str) -> list[ValidationIssue]:
    """Return validation issues with approximate line numbers."""
    errors: list[ValidationIssue] = []

    if not body or not body.strip():
        errors.append(ValidationIssue(line=1, message="Issue body is empty."))
        return errors

    # Required fields
    required = ["Your Agent ID", "Reward (WEA)", "Reward Type"]
    for field in required:
        wrong_line = _find_header_line(body, field, level="##")
        if wrong_line is not None:
            errors.append(
                ValidationIssue(
                    line=wrong_line,
                    message=(
                        f"Field **{field}** uses `##` header — must be `###` "
                        f"(GitHub Forms template format). Also ensure a blank line between header and value."
                    ),
                )
            )
        elif not _has_header(body, field):
            errors.append(ValidationIssue(line=1, message=f"Missing required field: **{field}**"))
        elif _parse_field(body, field) is None:
            errors.append(
                ValidationIssue(
                    line=_find_header_line(body, field) or 1,
                    message=(
                        f"Field **{field}** found but value is empty or missing. "
                        f"Ensure a blank line between `### {field}` and the value."
                    ),
                )
            )

    # Agent ID format
    agent_id = _parse_field(body, "Your Agent ID")
    if agent_id and "@" not in agent_id:
        errors.append(
            ValidationIssue(
                line=_find_value_line(body, "Your Agent ID") or 1,
                message=(
                    f"Agent ID `{agent_id}` missing `@platform` suffix. "
                    f"Expected format: `name@platform` (e.g. `agent0@system`)."
                ),
            )
        )

    # Reward must be positive integer
    reward_raw = _parse_field(body, "Reward (WEA)")
    reward_val = None
    if reward_raw:
        try:
            reward = int(reward_raw)
            reward_val = reward
            if reward <= 0:
                errors.append(
                    ValidationIssue(
                        line=_find_value_line(body, "Reward (WEA)") or 1,
                        message=f"Reward must be a positive integer, got `{reward_raw}`.",
                    )
                )
        except ValueError:
            errors.append(
                ValidationIssue(
                    line=_find_value_line(body, "Reward (WEA)") or 1,
                    message=f"Reward must be an integer, got `{reward_raw}`.",
                )
            )

    # Reward type must match known types; companion fields must be present
    reward_type_raw = _parse_field(body, "Reward Type")
    if reward_type_raw:
        reward_type = _normalize_reward_type(reward_type_raw)
        if reward_type is None:
            valid_types = ", ".join(f"`{k}`" for k in _REWARD_TYPE_MAP)
            errors.append(
                ValidationIssue(
                    line=_find_value_line(body, "Reward Type") or 1,
                    message=(
                        f"Reward Type `{reward_type_raw}` not recognized. "
                        f"Valid types: {valid_types}."
                    ),
                )
            )
        else:
            slots_label, slots_raw, slots_line = _first_populated_field(
                body,
                ["Slots (Progressive / Linear only)", "Slots (Progressive Every Good only)"],
            )
            winners_label, winners_raw, winners_line = _first_populated_field(
                body,
                ["Winners X ([X] Best only)"],
            )
            rounds_label, rounds_raw, rounds_line = _first_populated_field(
                body,
                ["Rounds (Duel only)"],
            )
            per_acceptance_label, per_acceptance_raw, per_acceptance_line = _first_populated_field(
                body,
                ["Per Acceptance (Every Good only)"],
            )

            slots = None
            if slots_raw is not None:
                slots = _parse_positive_int(slots_raw)
                if slots is None:
                    errors.append(
                        ValidationIssue(
                            line=slots_line,
                            message=f"Slots must be a positive integer, got `{slots_raw}`.",
                        )
                    )

            winners = None
            if winners_raw is not None:
                winners = _parse_positive_int(winners_raw)
                if winners is None:
                    errors.append(
                        ValidationIssue(
                            line=winners_line,
                            message=f"Winners X must be a positive integer, got `{winners_raw}`.",
                        )
                    )

            rounds = None
            if rounds_raw is not None:
                rounds = _parse_positive_int(rounds_raw)
                if rounds is None:
                    errors.append(
                        ValidationIssue(
                            line=rounds_line,
                            message=f"Rounds must be a positive integer, got `{rounds_raw}`.",
                        )
                    )

            per_acceptance = None
            if per_acceptance_raw is not None:
                per_acceptance = _parse_positive_int(per_acceptance_raw)
                if per_acceptance is None:
                    errors.append(
                        ValidationIssue(
                            line=per_acceptance_line,
                            message=(
                                f"Per Acceptance must be a positive integer, got `{per_acceptance_raw}`."
                            ),
                        )
                    )

            if reward_type in {"progressive", "linear"}:
                reward_label = "Linear PoD" if reward_type == "linear" else "Progressive Every Good"
                if slots_raw is None:
                    errors.append(
                        ValidationIssue(
                            line=_find_value_line(body, "Reward Type") or 1,
                            message=(
                                f"Reward Type `{reward_label}` requires a **Slots** field "
                                "(`### Slots (Progressive / Linear only)` or "
                                "`### Slots (Progressive Every Good only)`) with a positive integer."
                            ),
                        )
                    )
                elif reward_raw and slots is not None:
                    expected_reward = (
                        slots * (slots + 1) // 2 if reward_type == "linear" else _progressive_budget(slots)
                    )
                    if reward_val is not None and reward_val != expected_reward:
                        errors.append(
                            ValidationIssue(
                                line=_find_value_line(body, "Reward (WEA)") or 1,
                                message=(
                                    f"Reward `{reward_val}` does not match {reward_label} budget for {slots} slot(s); "
                                    f"expected `{expected_reward}`."
                                ),
                            )
                        )

            if reward_type == "best_x":
                if winners_raw is None:
                    errors.append(
                        ValidationIssue(
                            line=_find_value_line(body, "Reward Type") or 1,
                            message=(
                                "Reward Type `[X] Best` requires a **Winners X** field "
                                "(`### Winners X ([X] Best only)`) with a positive integer (2–5)."
                            ),
                        )
                    )
                elif winners is not None and not 2 <= winners <= 5:
                    errors.append(
                        ValidationIssue(
                            line=winners_line,
                            message=(
                                "Winners X must be in range `2..5` for `[X] Best`. "
                                "Use `Winner Take All` for a single winner."
                            ),
                        )
                    )

            if reward_type == "winner_take_all" and winners_raw is not None:
                errors.append(
                    ValidationIssue(
                        line=winners_line,
                        message=(
                            "Winner Take All must leave **Winners X** blank. "
                            "Use `[X] Best` when multiple ranks should share the budget."
                        ),
                    )
                )

            if reward_type == "every_good" and per_acceptance is not None and reward_val is not None:
                if per_acceptance > reward_val:
                    errors.append(
                        ValidationIssue(
                            line=per_acceptance_line,
                            message=(
                                f"Per Acceptance `{per_acceptance}` exceeds total reward `{reward_val}`."
                            ),
                        )
                    )
                elif reward_val % per_acceptance != 0:
                    errors.append(
                        ValidationIssue(
                            line=per_acceptance_line,
                            message=(
                                f"Reward `{reward_val}` is not divisible by Per Acceptance `{per_acceptance}`. "
                                "Every Good budgets must split into whole acceptances."
                            ),
                        )
                    )

            if reward_type != "every_good" and per_acceptance_raw is not None:
                errors.append(
                    ValidationIssue(
                        line=per_acceptance_line,
                        message=(
                            f"Field **{per_acceptance_label}** only applies to `Every Good` tasks. "
                            f"Leave it blank for `{reward_type_raw}`."
                        ),
                    )
                )

            if reward_type not in {"progressive", "linear"} and slots_raw is not None:
                errors.append(
                    ValidationIssue(
                        line=slots_line,
                        message=(
                            f"Field **{slots_label}** only applies to `Progressive Every Good` or `Linear PoD` tasks. "
                            f"Leave it blank for `{reward_type_raw}`."
                        ),
                    )
                )

            if reward_type not in {"best_x", "winner_take_all"} and winners_raw is not None:
                errors.append(
                    ValidationIssue(
                        line=winners_line,
                        message=(
                            f"Field **{winners_label}** only applies to `[X] Best` tasks. "
                            f"Leave it blank for `{reward_type_raw}`."
                        ),
                    )
                )

            if reward_type != "duel" and rounds_raw is not None:
                errors.append(
                    ValidationIssue(
                        line=rounds_line,
                        message=(
                            f"Field **{rounds_label}** only applies to `Duel` tasks. "
                            f"Leave it blank for `{reward_type_raw}`."
                        ),
                    )
                )

    # Verification criteria — required for tasks >= 10 WEA
    verification_raw = _parse_field(body, "Verification Criteria")
    has_criteria = bool(verification_raw and verification_raw.strip())
    if reward_val is not None and reward_val >= 10 and not has_criteria:
        errors.append(
            ValidationIssue(
                line=_find_value_line(body, "Reward (WEA)") or 1,
                message=(
                    "Tasks with reward >= 10 WEA require **Verification Criteria**. "
                    "Add a `### Verification Criteria` section with concrete checks "
                    "that prove the problem is solved (use checkboxes)."
                ),
            )
        )

    return errors


def _progressive_budget(slots: int) -> int:
    return _fib(slots + 2) - 1


def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a


def validate(body: str) -> list[str]:
    """Return list of human-readable errors. Empty list = valid."""
    return [issue.message for issue in validate_detailed(body)]


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
