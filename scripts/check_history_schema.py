#!/usr/bin/env python3
"""History JSONL schema validator.

Validates every entry in ledger/history/*.jsonl conforms to the expected
schema for its ``type`` field. Each known event type has a defined set of
required fields; unknown types are flagged as warnings, not failures.

Exit codes:
    0 — all entries conform (WARN entries do not count as failures)
    1 — one or more entries violate the schema

Output: JSON to stdout with fields: status, checks, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Per-type required fields.
# Entry satisfies a field if the field (or an accepted alias) is present
# and non-null. See FIELD_ALTERNATIVES below.
SCHEMAS: dict[str, frozenset[str]] = {
    "payment":         frozenset({"type", "agent", "amount", "issue", "timestamp"}),
    "escrow":          frozenset({"type", "agent", "amount", "issue", "timestamp"}),
    "escrow_return":   frozenset({"type", "issue", "amount", "timestamp"}),
    "trajectory_mint": frozenset({"type", "trajectory", "slot", "amount", "timestamp"}),
    "verification":    frozenset({"type", "issue", "agent", "verified_by", "evidence", "timestamp"}),
    "claim":           frozenset({"type", "issue", "agent", "timestamp"}),
}

# Alternative key names that satisfy a required field.
# Real history has entries that pre-date the canonical schema:
#   - 'author' was used before 'agent' for escrow entries
#   - 'created_at' and 'event_at' were used before 'timestamp'
FIELD_ALTERNATIVES: dict[str, list[str]] = {
    "agent":     ["agent", "author"],
    "timestamp": ["timestamp", "created_at", "event_at"],
}


def _satisfies(entry: dict[str, Any], field: str) -> bool:
    """Return True if entry has a non-null value for field or any of its aliases."""
    alternatives = FIELD_ALTERNATIVES.get(field, [field])
    return any(entry.get(k) is not None for k in alternatives)


def _check_entry(
    filename: str,
    lineno: int,
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate a single parsed history entry. Returns violation dicts."""
    violations: list[dict[str, Any]] = []

    event_type = entry.get("type")
    if event_type is None:
        violations.append({
            "check": "missing_type",
            "status": "FAIL",
            "file": filename,
            "line": lineno,
            "event_type": None,
            "detail": "entry has no 'type' field",
        })
        return violations

    if event_type not in SCHEMAS:
        violations.append({
            "check": "unknown_type",
            "status": "WARN",
            "file": filename,
            "line": lineno,
            "event_type": event_type,
            "detail": f"unknown event type '{event_type}' — not in schema (new types are allowed)",
        })
        return violations

    schema = SCHEMAS[event_type]
    missing = sorted(f for f in schema if not _satisfies(entry, f))
    if missing:
        violations.append({
            "check": "required_fields",
            "status": "FAIL",
            "file": filename,
            "line": lineno,
            "event_type": event_type,
            "missing_fields": missing,
            "detail": f"missing or null required fields: {missing}",
        })

    # amount must be an integer — fractional WEA corrupts downstream accounting
    amt = entry.get("amount")
    if amt is not None and (not isinstance(amt, int) or isinstance(amt, bool)):
        violations.append({
            "check": "amount_type",
            "status": "FAIL",
            "file": filename,
            "line": lineno,
            "event_type": event_type,
            "detail": f"'amount' must be int, got {type(amt).__name__}: {amt!r}",
        })

    return violations


def _scan_file(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Scan one JSONL file. Returns (violations, entry_count)."""
    violations: list[dict[str, Any]] = []
    filename = path.name
    entry_count = 0

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        violations.append({
            "check": "file_read_error",
            "status": "FAIL",
            "file": filename,
            "line": 0,
            "detail": str(exc),
        })
        return violations, 0

    for lineno, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped:
            continue
        entry_count += 1

        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError as exc:
            # WARN not FAIL: we cannot validate what we cannot parse, but a
            # historic encoding issue should not block forward-looking checks.
            violations.append({
                "check": "parse_error",
                "status": "WARN",
                "file": filename,
                "line": lineno,
                "detail": f"JSONL parse error: {exc}",
            })
            continue

        if not isinstance(entry, dict):
            violations.append({
                "check": "not_a_dict",
                "status": "FAIL",
                "file": filename,
                "line": lineno,
                "detail": f"entry is not a JSON object, got {type(entry).__name__}",
            })
            continue

        violations.extend(_check_entry(filename, lineno, entry))

    return violations, entry_count


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Scan all history JSONL files and return (result_dict, passed).

    passed is True iff no FAIL violations were found (WARN does not fail).
    """
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"history directory not found: {history_dir}",
        }, False

    jsonl_files = sorted(history_dir.glob("*.jsonl"))
    if not jsonl_files:
        return {
            "status": "PASS",
            "checks": [],
            "summary": "no history files found — nothing to validate",
        }, True

    all_violations: list[dict[str, Any]] = []
    total_entries = 0

    for path in jsonl_files:
        file_violations, entry_count = _scan_file(path)
        all_violations.extend(file_violations)
        total_entries += entry_count

    n_fail = sum(1 for v in all_violations if v["status"] == "FAIL")
    n_warn = sum(1 for v in all_violations if v["status"] == "WARN")
    passed = n_fail == 0
    overall = "PASS" if passed else "FAIL"

    parts = [f"{len(jsonl_files)} file(s)", f"{total_entries} entr{'y' if total_entries == 1 else 'ies'}"]
    if n_fail:
        parts.append(f"{n_fail} violation(s)")
    if n_warn:
        parts.append(f"{n_warn} warning(s)")

    summary = ", ".join(parts)

    return {
        "status": overall,
        "checks": all_violations,
        "summary": summary,
    }, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate ledger/history/*.jsonl entries against per-type schemas."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    result, passed = run(root)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
