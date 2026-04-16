#!/usr/bin/env python3
"""Idem Keys Schema Validator.

Validates the structure of ledger/idem_keys.json.

Schema enforced for each entry in the keys map:
  - Each key must be a non-empty string.
  - Each value must be either:
    - A string (legacy format — grandfathered, no field validation applied), OR
    - A dict with:
        created_at  required  ISO-8601 datetime ending in Z or ±HH:MM
        op          required  non-empty string
        amount      optional  positive integer (> 0, not 0 or negative)
      No required field may be null.

Top-level structure:
  - The JSON file must be a dict (object).
  - If it contains a "keys" wrapper key whose value is a dict, the entries
    inside that sub-dict are validated (this matches the current on-disk
    format: {"keys": {...}}).
  - Otherwise the top-level dict is treated as the entries map directly.

Output (JSON to stdout):
  {
    "status": "PASS" | "FAIL",
    "violations": [{"key": "...", "field": "...", "issue": "..."}],
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

# ISO-8601 datetime pattern: YYYY-MM-DDTHH:MM:SS followed by Z or ±HH:MM
# Optional fractional seconds are allowed.
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$"
)


def _is_valid_created_at(value: object) -> bool:
    """Return True iff value is an ISO-8601 datetime string ending in Z or ±HH:MM."""
    if not isinstance(value, str):
        return False
    return bool(_ISO8601_RE.match(value))


def _validate_dict_value(key: str, value: dict) -> list[dict]:
    """Validate a single dict-typed entry value. Returns violation dicts."""
    violations: list[dict] = []

    # created_at: required, ISO-8601 with Z or ±HH:MM, not null
    if "created_at" not in value:
        violations.append({"key": key, "field": "created_at", "issue": "missing required field"})
    elif value["created_at"] is None:
        violations.append({"key": key, "field": "created_at", "issue": "must not be null"})
    elif not _is_valid_created_at(value["created_at"]):
        violations.append({
            "key": key,
            "field": "created_at",
            "issue": (
                f"invalid ISO-8601 datetime '{value['created_at']}'; "
                "must end with Z or ±HH:MM"
            ),
        })

    # op: required, non-empty string, not null
    if "op" not in value:
        violations.append({"key": key, "field": "op", "issue": "missing required field"})
    elif value["op"] is None:
        violations.append({"key": key, "field": "op", "issue": "must not be null"})
    elif not isinstance(value["op"], str) or not value["op"].strip():
        violations.append({"key": key, "field": "op", "issue": "must be a non-empty string"})

    # amount: optional — if present, must be a positive integer
    if "amount" in value:
        amt = value["amount"]
        if isinstance(amt, bool) or not isinstance(amt, int):
            violations.append({
                "key": key,
                "field": "amount",
                "issue": f"must be an integer if present, got {type(amt).__name__}",
            })
        elif amt <= 0:
            violations.append({
                "key": key,
                "field": "amount",
                "issue": f"must be a positive integer (> 0), got {amt}",
            })

    return violations


def run(entries: object) -> dict:
    """Validate the idem_keys entries map.

    Args:
        entries: The entries dict to validate.  Typically this is either the
            full idem_keys.json content (flat format) or the value of
            data["keys"] (wrapped format).  A non-dict argument immediately
            produces a FAIL result.

    Returns:
        A result dict with keys: status, violations, summary.
    """
    violations: list[dict] = []

    if not isinstance(entries, dict):
        violations.append({
            "key": "(top-level)",
            "field": "root",
            "issue": (
                f"top-level must be a JSON object (dict), "
                f"got {type(entries).__name__}"
            ),
        })
        return _result(violations)

    for key, value in entries.items():
        # Keys must be non-empty strings.
        if not isinstance(key, str) or not key:
            violations.append({
                "key": repr(key),
                "field": "key",
                "issue": "idem key must be a non-empty string",
            })

        if isinstance(value, str):
            # Legacy format (plain ISO timestamp string) — accepted as-is.
            pass
        elif isinstance(value, dict):
            # Determine format by presence of new-schema sentinel fields.
            # Old-format dicts (pre-schema, e.g. {"action": ..., "timestamp": ...})
            # lack both "created_at" and "op" and are grandfathered in.
            # New-format dicts that include either field are validated fully.
            if "created_at" in value or "op" in value:
                violations.extend(_validate_dict_value(key, value))
            # else: old-format dict — skip validation
        else:
            # Any other type (int, null, list, …) is a schema violation.
            violations.append({
                "key": key,
                "field": "(value)",
                "issue": (
                    f"value must be a dict (new format) or string (legacy format), "
                    f"got {type(value).__name__}"
                ),
            })

    return _result(violations)


def _result(violations: list[dict]) -> dict:
    n = len(violations)
    return {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
        "summary": "No violations" if not violations else f"{n} violation{'s' if n != 1 else ''} found",
    }


def main() -> None:
    idem_keys_path = os.path.join(LEDGER_DIR, "idem_keys.json")

    if not os.path.exists(idem_keys_path):
        result = _result([{
            "key": "(file)",
            "field": "idem_keys.json",
            "issue": "file not found",
        }])
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        with open(idem_keys_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result = _result([{
            "key": "(file)",
            "field": "idem_keys.json",
            "issue": f"invalid JSON: {exc}",
        }])
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Navigate into the "keys" wrapper if present (current on-disk format).
    if isinstance(data, dict) and "keys" in data and isinstance(data["keys"], dict):
        entries = data["keys"]
    else:
        entries = data

    result = run(entries)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
