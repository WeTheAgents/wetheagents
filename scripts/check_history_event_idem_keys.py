#!/usr/bin/env python3
"""Verify every history event with an idem_key field has that key in ledger/idem_keys.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_idem_keys(path: Path) -> set[str]:
    """Load all keys from idem_keys.json (top-level and nested under 'keys')."""
    if not path.exists():
        return set()

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: failed to parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except OSError as exc:
        print(f"ERROR: failed to read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if isinstance(payload, list):
        return {str(k) for k in payload}

    if not isinstance(payload, dict):
        return set()

    keys: set[str] = set()

    nested = payload.get("keys")
    if isinstance(nested, dict):
        keys.update(str(k) for k in nested)
    elif isinstance(nested, list):
        keys.update(str(k) for k in nested)

    for k, v in payload.items():
        if k == "keys" and isinstance(v, (dict, list)):
            continue
        if k == "version" and type(v) is int:
            continue
        keys.add(str(k))

    return keys


def scan_history(history_dir: Path) -> list[dict[str, Any]]:
    """Collect all events that have an idem_key field from history JSONL files."""
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events

    for history_file in sorted(history_dir.glob("*.jsonl")):
        try:
            text = history_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(payload, dict):
                continue

            idem_key = payload.get("idem_key")
            if idem_key is not None:
                events.append(
                    {
                        "idem_key": str(idem_key),
                        "op": payload.get("type", ""),
                        "ts": payload.get("timestamp", payload.get("event_at", "")),
                        "file": history_file.name,
                    }
                )

    return events


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    idem_keys = load_idem_keys(root / "ledger" / "idem_keys.json")
    events = scan_history(root / "ledger" / "history")

    violations: list[dict[str, Any]] = [
        e for e in events if e["idem_key"] not in idem_keys
    ]

    report: dict[str, Any] = {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
        "stats": {
            "events_scanned": _count_all_events(root / "ledger" / "history"),
            "idem_keys_checked": len(events),
            "violations_found": len(violations),
        },
    }
    return report, 1 if violations else 0


def _count_all_events(history_dir: Path) -> int:
    """Count total non-empty lines across all history JSONL files."""
    total = 0
    if not history_dir.is_dir():
        return total
    for history_file in sorted(history_dir.glob("*.jsonl")):
        try:
            text = history_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip():
                total += 1
    return total


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify every history event idem_key is registered in idem_keys.json."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root.resolve())
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
