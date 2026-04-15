#!/usr/bin/env python3
"""Task Index Schema Validator.

Validates the structure of ledger/task_index.json.

Schema enforced per task entry:

  NEW-FORMAT entries (identified by the presence of the ``reward_wea`` field)
  are validated strictly against all required and optional fields:

    issue_number   — derived from the entry key; must be a string repr of int > 0
    reward_wea     required  integer > 0
    reward_type    required  one of VALID_REWARD_TYPES
    status         required  one of VALID_STATUSES
    created_at     required  ISO-8601 datetime ending in Z or ±HH:MM, not null
    accepted_agents required  list (may be empty)
    min_agents     required  integer ≥ 1

  Optional fields (validated only when present):
    claimed_by    string or null
    claimed_at    ISO-8601 datetime or null
    deadline      ISO-8601 date (YYYY-MM-DD) or null

  LEGACY entries (no ``reward_wea`` field) are grandfathered — only the entry
  key (issue_number) is checked.

All entry keys must be string representations of positive integers.

Output (JSON to stdout):
  {
    "status": "PASS" | "FAIL",
    "violations": [{"issue": "...", "field": "...", "issue_detail": "..."}],
    "summary": "N violations found" | "No violations"
  }

Exit codes:
  0 — PASS (no violations)
  1 — FAIL (one or more violations)
"""

from __future__ import annotations

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(BASE_DIR, "ledger")

VALID_REWARD_TYPES: frozenset[str] = frozenset(
    {"pod", "progressive", "wta", "best", "duel", "linear"}
)
VALID_STATUSES: frozenset[str] = frozenset(
    {"open", "claimed", "submitted", "accepted", "paid", "rejected", "expired", "closed"}
)

# ISO-8601 datetime: YYYY-MM-DDTHH:MM:SS[.frac](Z|±HH:MM)
_ISO8601_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$"
)

# ISO-8601 date: YYYY-MM-DD
_ISO8601_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_iso8601_datetime(value: object) -> bool:
    """Return True iff value is an ISO-8601 datetime string ending in Z or ±HH:MM."""
    if not isinstance(value, str):
        return False
    return bool(_ISO8601_DATETIME_RE.match(value))


def _is_iso8601_date(value: object) -> bool:
    """Return True iff value is an ISO-8601 date string (YYYY-MM-DD)."""
    if not isinstance(value, str):
        return False
    return bool(_ISO8601_DATE_RE.match(value))


def _v(issue: str, field: str, detail: str) -> dict:
    """Build a violation dict."""
    return {"issue": issue, "field": field, "issue_detail": detail}


def _validate_new_format(key: str, entry: dict) -> list[dict]:
    """Validate a new-format entry (one that contains `reward_wea`)."""
    violations: list[dict] = []

    # reward_wea: required, int > 0, not bool, not null
    if "reward_wea" not in entry:
        violations.append(_v(key, "reward_wea", "missing required field"))
    else:
        rw = entry["reward_wea"]
        if rw is None:
            violations.append(_v(key, "reward_wea", "must not be null"))
        elif isinstance(rw, bool) or not isinstance(rw, int):
            violations.append(_v(key, "reward_wea", f"must be an integer, got {type(rw).__name__}"))
        elif rw <= 0:
            violations.append(_v(key, "reward_wea", f"must be > 0, got {rw}"))

    # reward_type: required, enum
    if "reward_type" not in entry:
        violations.append(_v(key, "reward_type", "missing required field"))
    else:
        rt = entry["reward_type"]
        if rt is None:
            violations.append(_v(key, "reward_type", "must not be null"))
        elif rt not in VALID_REWARD_TYPES:
            violations.append(_v(
                key, "reward_type",
                f"invalid value '{rt}'; must be one of {sorted(VALID_REWARD_TYPES)}",
            ))

    # status: required, enum
    if "status" not in entry:
        violations.append(_v(key, "status", "missing required field"))
    else:
        st = entry["status"]
        if st is None:
            violations.append(_v(key, "status", "must not be null"))
        elif st not in VALID_STATUSES:
            violations.append(_v(
                key, "status",
                f"invalid value '{st}'; must be one of {sorted(VALID_STATUSES)}",
            ))

    # created_at: required, ISO-8601 datetime, not null
    if "created_at" not in entry:
        violations.append(_v(key, "created_at", "missing required field"))
    else:
        ca = entry["created_at"]
        if ca is None:
            violations.append(_v(key, "created_at", "must not be null"))
        elif not _is_iso8601_datetime(ca):
            violations.append(_v(
                key, "created_at",
                f"invalid ISO-8601 datetime '{ca}'; must end with Z or ±HH:MM",
            ))

    # accepted_agents: required, must be a list
    if "accepted_agents" not in entry:
        violations.append(_v(key, "accepted_agents", "missing required field"))
    else:
        aa = entry["accepted_agents"]
        if not isinstance(aa, list):
            violations.append(_v(
                key, "accepted_agents",
                f"must be a list, got {type(aa).__name__}",
            ))

    # min_agents: required, int >= 1, not bool
    if "min_agents" not in entry:
        violations.append(_v(key, "min_agents", "missing required field"))
    else:
        ma = entry["min_agents"]
        if ma is None:
            violations.append(_v(key, "min_agents", "must not be null"))
        elif isinstance(ma, bool) or not isinstance(ma, int):
            violations.append(_v(key, "min_agents", f"must be an integer, got {type(ma).__name__}"))
        elif ma < 1:
            violations.append(_v(key, "min_agents", f"must be >= 1, got {ma}"))

    # Optional: claimed_by — string or null
    if "claimed_by" in entry:
        cb = entry["claimed_by"]
        if cb is not None and not isinstance(cb, str):
            violations.append(_v(
                key, "claimed_by",
                f"must be a string or null, got {type(cb).__name__}",
            ))

    # Optional: claimed_at — ISO-8601 datetime or null
    if "claimed_at" in entry:
        cat = entry["claimed_at"]
        if cat is not None and not _is_iso8601_datetime(cat):
            violations.append(_v(
                key, "claimed_at",
                f"invalid ISO-8601 datetime or null '{cat}'",
            ))

    # Optional: deadline — ISO-8601 date or null
    if "deadline" in entry:
        dl = entry["deadline"]
        if dl is not None and not _is_iso8601_date(dl):
            violations.append(_v(
                key, "deadline",
                f"invalid ISO-8601 date or null '{dl}'",
            ))

    return violations


def _validate_key(key: str) -> list[dict]:
    """Validate that the entry key is a string representation of int > 0."""
    violations: list[dict] = []
    try:
        n = int(key)
    except (ValueError, TypeError):
        violations.append(_v(key, "issue_number", f"key '{key}' is not a valid integer string"))
        return violations
    if n <= 0:
        violations.append(_v(key, "issue_number", f"key '{key}' must represent an integer > 0"))
    return violations


def run(tasks: object) -> dict:
    """Validate the task_index tasks dict.

    Args:
        tasks: The value of ``data["tasks"]`` from task_index.json.
               A non-dict argument immediately produces a FAIL result.

    Returns:
        A result dict with keys: status, violations, summary.
    """
    violations: list[dict] = []

    if not isinstance(tasks, dict):
        violations.append(_v(
            "(top-level)", "tasks",
            f"'tasks' must be a JSON object (dict), got {type(tasks).__name__}",
        ))
        return _result(violations)

    for key, entry in tasks.items():
        # Always validate the key format.
        violations.extend(_validate_key(key))

        if not isinstance(entry, dict):
            violations.append(_v(
                key, "(entry)",
                f"task entry must be a JSON object, got {type(entry).__name__}",
            ))
            continue

        # Detect format: new-format entries carry `reward_wea`.
        if "reward_wea" in entry:
            violations.extend(_validate_new_format(key, entry))
        # else: legacy entry — key already validated above, no further checks.

    return _result(violations)


def _result(violations: list[dict]) -> dict:
    n = len(violations)
    return {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
        "summary": "No violations" if not violations else f"{n} violation{'s' if n != 1 else ''} found",
    }


def main() -> None:
    task_index_path = os.path.join(LEDGER_DIR, "task_index.json")

    if not os.path.exists(task_index_path):
        result = _result([_v("(file)", "task_index.json", "file not found")])
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        with open(task_index_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result = _result([_v("(file)", "task_index.json", f"invalid JSON: {exc}")])
        print(json.dumps(result, indent=2))
        sys.exit(1)

    if not isinstance(data, dict):
        result = _result([_v("(file)", "task_index.json", "top-level must be a JSON object")])
        print(json.dumps(result, indent=2))
        sys.exit(1)

    tasks = data.get("tasks", {})
    result = run(tasks)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
