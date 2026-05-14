#!/usr/bin/env python3
"""Idem Keys Schema Validator.

Validates the structure of ledger/idem_keys.json.

Schema enforced for each entry in the keys map:
  - Each key must be a non-empty string.
  - Each value must be either:
    - A string (legacy format — grandfathered, no field validation applied), OR
    - A known legacy sentinel (`true`) for escrow-create/return cycle keys, OR
    - A known legacy metadata dict for escrow-create/return keys, OR
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

_LEGACY_TRUE_SENTINEL_RE = re.compile(
    r"^(escrow-return-cycle\d+-\d+|escrow_create\|\d+)$"
)
_LEGACY_METADATA_RE = re.compile(
    r"^(escrow_create_\d+_[A-Za-z0-9_-]+_gauntlet|escrow_return\|\d+\|[A-Za-z0-9@._-]+|escrow-return-cycle\d+-\d+)$"
)
_LEGACY_METADATA_FIELDS = frozenset({"amount", "created_at", "issue", "note", "op", "ts"})


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


def _is_legacy_true_sentinel(key: str, value: object) -> bool:
    """Return True for historical presence-only idem entries."""
    return value is True and bool(_LEGACY_TRUE_SENTINEL_RE.match(key))


def _matches_legacy_metadata_shape(key: str, value: dict) -> bool:
    """Return True if key+fields match the legacy-escrow metadata shape.

    Used to route legacy-shaped entries into ``_validate_legacy_metadata_dict``
    instead of the new-format validator (which would falsely demand op /
    created_at to be present).
    """
    if not _LEGACY_METADATA_RE.match(key):
        return False
    return set(value).issubset(_LEGACY_METADATA_FIELDS)


def _validate_legacy_metadata_dict(key: str, value: dict) -> list[dict]:
    """Validate constrained fields on a legacy-shaped metadata entry.

    Grandfathers only the *absence* of fields, never *present-but-invalid*
    fields. Required-presence checks (op / created_at must exist) do NOT apply
    to legacy entries — they predate that rule. But any constrained field that
    IS present must satisfy its constraint.
    """
    violations: list[dict] = []

    # Timestamps: if a timestamp key is present at all, its value must be valid.
    # A null or malformed timestamp is a real defect, not a historical absence.
    for ts_field in ("created_at", "ts"):
        if ts_field not in value:
            continue
        if value[ts_field] is None:
            violations.append({
                "key": key,
                "field": ts_field,
                "issue": "must not be null",
            })
        elif not _is_valid_created_at(value[ts_field]):
            violations.append({
                "key": key,
                "field": ts_field,
                "issue": (
                    f"invalid ISO-8601 datetime '{value[ts_field]}'; "
                    "must end with Z or ±HH:MM"
                ),
            })

    # Amount: if present, must be a positive integer (bool excluded).
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

    # op: if present, must be a non-empty string (legacy entries may omit op
    # entirely — that's grandfathered — but a present blank/null op is invalid).
    if "op" in value:
        op = value["op"]
        if op is None:
            violations.append({"key": key, "field": "op", "issue": "must not be null"})
        elif not isinstance(op, str) or not op.strip():
            violations.append({"key": key, "field": "op", "issue": "must be a non-empty string"})

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
        elif _is_legacy_true_sentinel(key, value):
            # Legacy presence-only sentinel for a few historical escrow keys.
            pass
        elif isinstance(value, dict):
            if _matches_legacy_metadata_shape(key, value):
                # Legacy escrow metadata pattern — only validate present-but-invalid
                # fields. Required-presence checks don't apply (predates rule).
                violations.extend(_validate_legacy_metadata_dict(key, value))
            elif "created_at" in value or "op" in value:
                # New-format dicts that include sentinel fields are validated fully.
                violations.extend(_validate_dict_value(key, value))
            # else: old-format dict (no sentinel fields, non-legacy pattern) — skip
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
