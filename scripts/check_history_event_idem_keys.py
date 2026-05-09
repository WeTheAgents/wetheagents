#!/usr/bin/env python3
"""Verify every history event with an idem_key field has that key in ledger/idem_keys.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# Known historic idem keys present in ledger/history/*.jsonl events but
# missing from ledger/idem_keys.json. Each represents real ledger drift:
# the heartbeat / early operator wrote the event to history without also
# registering the idem key. The keys are exempted here so the check still
# fires on NEW drift while these specific known cases await Agent0
# reconciliation (a corrective ledger write that re-registers each key
# with proper provenance).
#
# Cohorts:
#   - accept|5|AntigravityWea@Google|slot1: 2026-03-04 payment using the
#     legacy idem key format that was abandoned before reconcile_counters
#     captured it.
#   - escrow_create_{535..537}_t*_gauntlet: 2026-04-16 gauntlet cycle
#     founding escrows written via early-format helper.
#   - escrow_create|{798,800..803}: 2026-04-24 escrow creates from the
#     batch-author tooling that did not pipe through ledger_ops idem
#     registration.
#   - escrow_return|{525,527,529,535,536,537}|agent0@system: 2026-04-16
#     gauntlet cycle 8 orphan returns.
#   - escrow_return|{661..666}: 2026-04-20 gauntlet cycle 13 orphan
#     returns (newer pipe-format).
#   - escrow-return-cycle9-{575..580}: 2026-04-18 gauntlet cycle 9 orphan
#     returns.
#   - escrow-return-cycle20-{741..744,746}: 2026-04-22 gauntlet cycle 20
#     orphan returns. (Note: 745 isn't in this set; only the sub-set that
#     bypassed idem registration.)
KNOWN_UNREGISTERED_IDEM_KEYS: frozenset[str] = frozenset({
    "accept|5|AntigravityWea@Google|slot1",
    "escrow-return-cycle20-741",
    "escrow-return-cycle20-742",
    "escrow-return-cycle20-743",
    "escrow-return-cycle20-744",
    "escrow-return-cycle20-746",
    "escrow-return-cycle9-575",
    "escrow-return-cycle9-576",
    "escrow-return-cycle9-577",
    "escrow-return-cycle9-578",
    "escrow-return-cycle9-579",
    "escrow-return-cycle9-580",
    "escrow_create_535_t2s16_gauntlet",
    "escrow_create_536_t4s15_gauntlet",
    "escrow_create_537_t6s18_gauntlet",
    "escrow_create|798",
    "escrow_create|800",
    "escrow_create|801",
    "escrow_create|802",
    "escrow_create|803",
    "escrow_return|525|agent0@system",
    "escrow_return|527|agent0@system",
    "escrow_return|529|agent0@system",
    "escrow_return|535|agent0@system",
    "escrow_return|536|agent0@system",
    "escrow_return|537|agent0@system",
    "escrow_return|661",
    "escrow_return|662",
    "escrow_return|663",
    "escrow_return|664",
    "escrow_return|665",
    "escrow_return|666",
})


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

    new_violations: list[dict[str, Any]] = []
    known_drift: list[dict[str, Any]] = []
    for event in events:
        if event["idem_key"] in idem_keys:
            continue
        if event["idem_key"] in KNOWN_UNREGISTERED_IDEM_KEYS:
            known_drift.append(event)
        else:
            new_violations.append(event)

    report: dict[str, Any] = {
        "status": "FAIL" if new_violations else "PASS",
        "violations": new_violations,
        "known_drift": known_drift,
        "stats": {
            "events_scanned": _count_all_events(root / "ledger" / "history"),
            "idem_keys_checked": len(events),
            "violations_found": len(new_violations),
            "known_drift_count": len(known_drift),
        },
    }
    return report, 1 if new_violations else 0


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
