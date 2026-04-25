#!/usr/bin/env python3
"""Verify that ledger file version fields are not regressed relative to write-event history.

Checks three mutable ledger files (balances.json, escrows.json, idem_keys.json):

1. Each file must have a top-level ``version`` field that is a positive integer
   (not null, not a string, not zero or negative, not absent).

2. Each file's version must be >= the count of history write events associated
   with that file.  Because history events do not carry their own version field
   (option 2 from the spec), the simpler lower-bound check (option 3) is used:
   count write-type events per file and verify version >= count.

   Per-file event type mapping:
     balances.json  — payment, accept, registration
     escrows.json   — escrow_create
     idem_keys.json — registration, gauntlet_mint

   Note: ``escrow_return`` is deliberately excluded from all per-file counts.
   It removes an entry from escrows.json and credits balances.json, but
   including it in either file's count produces a false-positive failure on
   a healthy ledger (there are more return events than version bumps per file).

Exit codes:
  0 — all checks passed
  1 — at least one violation detected
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


LEDGER_FILES = {
    "balances": "ledger/balances.json",
    "escrows": "ledger/escrows.json",
    "idem_keys": "ledger/idem_keys.json",
}

# Write event types counted per file as a lower-bound regression guard.
FILE_WRITE_TYPES: dict[str, frozenset[str]] = {
    "balances": frozenset({"payment", "accept", "registration"}),
    "escrows": frozenset({"escrow_create"}),
    "idem_keys": frozenset({"registration", "gauntlet_mint"}),
}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load_ledger_versions(root: Path) -> dict[str, dict[str, Any]]:
    """Load version info from all three ledger files."""
    results: dict[str, dict[str, Any]] = {}
    for key, rel_path in LEDGER_FILES.items():
        path = root / rel_path
        entry: dict[str, Any] = {"path": rel_path, "version": None, "error": None}
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except FileNotFoundError:
            entry["error"] = f"file not found: {path}"
        except json.JSONDecodeError as exc:
            entry["error"] = f"JSON parse error: {exc}"
        else:
            if not isinstance(data, dict):
                entry["error"] = "top-level value is not a JSON object"
            else:
                entry["version"] = data.get("version")
        results[key] = entry
    return results


def count_write_events(root: Path) -> dict[str, int]:
    """Scan ledger/history/*.jsonl and return write-event counts per file key."""
    counts: dict[str, int] = {key: 0 for key in FILE_WRITE_TYPES}
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return counts
    for jsonl_path in sorted(history_dir.glob("*.jsonl")):
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type", "")
            for file_key, types in FILE_WRITE_TYPES.items():
                if event_type in types:
                    counts[file_key] += 1
    return counts


def check(root: Path) -> tuple[dict[str, Any], bool]:
    """Run all checks; return (report, passed)."""
    versions = load_ledger_versions(root)
    event_counts = count_write_events(root)

    violations: list[dict[str, Any]] = []
    file_reports: list[dict[str, Any]] = []

    for key in LEDGER_FILES:
        info = versions[key]
        event_count = event_counts[key]
        version_val = info["version"]

        file_report: dict[str, Any] = {
            "file": info["path"],
            "version": version_val,
            "write_event_count": event_count,
            "status": "PASS",
        }

        if info["error"]:
            file_report["status"] = "FAIL"
            violations.append({
                "file": info["path"],
                "reason": info["error"],
            })
        elif not _is_positive_int(version_val):
            file_report["status"] = "FAIL"
            violations.append({
                "file": info["path"],
                "version": version_val,
                "reason": (
                    "version field is missing, null, non-integer, or not a positive integer"
                ),
            })
        elif version_val < event_count:
            file_report["status"] = "FAIL"
            violations.append({
                "file": info["path"],
                "version": version_val,
                "write_event_count": event_count,
                "reason": (
                    f"version ({version_val}) < write-event count ({event_count}); "
                    "indicates a silent rollback or manual version regression"
                ),
            })

        file_reports.append(file_report)

    passed = not violations
    report: dict[str, Any] = {
        "status": "PASS" if passed else "FAIL",
        "violations": violations,
        "files": file_reports,
        "summary": (
            f"Checked {len(LEDGER_FILES)} ledger files; "
            f"{len(violations)} violation(s) found."
        ),
    }
    return report, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify ledger version fields are never regressed below write-event counts."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)

    root = _repo_root(args.root)
    report, passed = check(root)
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
