#!/usr/bin/env python3
"""Verify trajectory_mint events appear in strictly increasing slot order in the history stream.

Replays ledger/history/*.jsonl files in chronological order (sorted by filename).
For each trajectory, the slot numbers seen in the stream must be strictly
increasing — every new mint must carry a higher slot than the previous one
recorded for that trajectory.  An out-of-order slot signals a retroactive
insert or replay attack.

Two checks are performed:

  1. Ordering violations — any trajectory_mint event whose slot is not strictly
     greater than the last slot seen for that trajectory in the stream.

  2. next_slot drift — after replaying the full stream, the declared next_slot
     in trajectory_mints.json must equal max(history_slots) + 1 for each
     trajectory (or 1 if no events exist).

How this differs from check_trajectory_slot_uniqueness.py
----------------------------------------------------------
Uniqueness only asks "does the same (trajectory, slot) pair appear twice?"
Timeline asks "does each new slot appear *after* a higher-numbered slot?"
A slot can be unique yet still out of order (slot 3 appears in a January file
after slot 5 appeared in a February file).

Output: JSON to stdout with keys:
  status               — "PASS" or "FAIL"
  ordering_violations  — list of out-of-order or duplicate-slot events
  next_slot_drift      — list of trajectories whose next_slot disagrees with history

Exits 0 on PASS, 1 on FAIL.

Usage:
    python scripts/check_trajectory_mint_timeline.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_history_mint_events(root: Path) -> list[dict[str, Any]]:
    """Return trajectory_mint events from history in stream order.

    Files are processed in ascending filename order (YYYY-MM-DD.jsonl).
    Within each file, lines are processed top to bottom.  Each returned dict
    has the original event fields plus injected metadata:
      _file    — basename of the source file
      _line    — 1-based line number within that file
    """
    events: list[dict[str, Any]] = []
    history_dir = root / "ledger" / "history"
    for path in sorted(history_dir.glob("*.jsonl")):
        fname = path.name
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "trajectory_mint":
                    continue
                event["_file"] = fname
                event["_line"] = lineno
                events.append(event)
    return events


def load_trajectory_mints_json(root: Path) -> dict[str, Any]:
    """Return parsed ledger/trajectory_mints.json."""
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def find_ordering_violations(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a record for each event whose slot is not strictly greater than
    the previous slot seen for the same trajectory.

    Both out-of-order slots (new_slot < prev_slot) and duplicate slots
    (new_slot == prev_slot) are violations because "strictly increasing" means
    each slot must be *greater than* the previous one.

    Each violation record contains:
      trajectory      — trajectory identifier
      slot            — the offending slot number
      position        — "<file>:line <N>" for the offending event
      prev_slot       — the last slot seen before this event for this trajectory
      prev_position   — "<file>:line <N>" of the event that set prev_slot
    """
    last_seen: dict[str, dict[str, Any]] = {}  # traj → {slot, file, line}
    violations: list[dict[str, Any]] = []

    for ev in events:
        traj = ev.get("trajectory")
        slot = ev.get("slot")
        if traj is None or slot is None:
            continue
        traj = str(traj)
        slot = int(slot)
        position = f"{ev['_file']}:line {ev['_line']}"

        if traj in last_seen:
            prev = last_seen[traj]
            if slot <= prev["slot"]:
                violations.append(
                    {
                        "trajectory": traj,
                        "slot": slot,
                        "position": position,
                        "prev_slot": prev["slot"],
                        "prev_position": f"{prev['file']}:line {prev['line']}",
                    }
                )
                # Update last_seen only when the violation is a true duplicate
                # so subsequent out-of-order events are still caught correctly.
                # If new slot > prev slot we always advance; here slot <= prev,
                # so we do NOT advance — the last valid slot remains the anchor.
                continue

        last_seen[traj] = {"slot": slot, "file": ev["_file"], "line": ev["_line"]}

    return violations


def find_next_slot_drift(
    events: list[dict[str, Any]],
    trajectories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return records for every trajectory whose declared next_slot disagrees
    with what the history stream implies.

    Expected next_slot = max(history_slots) + 1.
    If no history events exist for a trajectory, expected next_slot = 1.
    """
    max_slot: dict[str, int] = {}
    for ev in events:
        traj = ev.get("trajectory")
        slot = ev.get("slot")
        if traj is None or slot is None:
            continue
        traj = str(traj)
        slot = int(slot)
        if traj not in max_slot or slot > max_slot[traj]:
            max_slot[traj] = slot

    drift: list[dict[str, Any]] = []

    # Trajectories present in history
    for traj in sorted(max_slot):
        expected = max_slot[traj] + 1
        if traj not in trajectories:
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": max_slot[traj],
                    "expected_next_slot": expected,
                    "declared_next_slot": None,
                }
            )
            continue
        declared = trajectories[traj].get("next_slot")
        if declared != expected:
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": max_slot[traj],
                    "expected_next_slot": expected,
                    "declared_next_slot": declared,
                }
            )

    # Trajectories in JSON with no history yet
    for traj in sorted(trajectories):
        if traj in max_slot:
            continue
        declared = trajectories[traj].get("next_slot")
        if declared != 1:
            drift.append(
                {
                    "trajectory": traj,
                    "history_max_slot": None,
                    "expected_next_slot": 1,
                    "declared_next_slot": declared,
                }
            )

    return drift


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_check(root: Path) -> dict[str, Any]:
    """Run both checks and return a JSON-serialisable result dict."""
    events = load_history_mint_events(root)
    mints_data = load_trajectory_mints_json(root)
    trajectories: dict[str, dict[str, Any]] = mints_data.get("trajectories", {})

    ordering_violations = find_ordering_violations(events)
    next_slot_drift = find_next_slot_drift(events, trajectories)

    status = "PASS" if not ordering_violations and not next_slot_drift else "FAIL"
    return {
        "status": status,
        "ordering_violations": ordering_violations,
        "next_slot_drift": next_slot_drift,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify trajectory_mint events appear in strictly increasing slot order"
            " in the history stream."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        payload = run_check(root)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        payload = {
            "status": "FAIL",
            "ordering_violations": [],
            "next_slot_drift": [],
            "error": str(exc),
        }
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
