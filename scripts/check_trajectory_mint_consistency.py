#!/usr/bin/env python3
"""Cross-validate ledger/trajectory_mints.json against trajectory_mint events
in ledger/history/*.jsonl.

Five checks:
  1. Bidirectional match  — every history event has a matching mints entry and
                            vice versa (by trajectory+slot).
  2. Amount agreement     — for each matched pair, history amount == mints amount.
  3. total_minted         — top-level total_minted equals sum of all mint amounts.
  4. next_slot integrity  — per-trajectory slots must be {1..n} with no gaps;
                            next_slot must equal n+1.
  5. per_agent sum        — for each mints entry, sum(per_agent) must equal amount.

Exits 0 on clean, 1 on any inconsistency with a report naming the exact conflict.

Usage:
    python scripts/check_trajectory_mint_consistency.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_history_events(root: Path) -> list[dict]:
    """Return all trajectory_mint events from ledger/history/*.jsonl."""
    events: list[dict] = []
    history_dir = root / "ledger" / "history"
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "trajectory_mint":
                    events.append(event)
    return events


def load_mints_file(root: Path) -> dict:
    """Return parsed ledger/trajectory_mints.json."""
    path = root / "ledger" / "trajectory_mints.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_bidirectional_match(
    history_events: list[dict],
    mints_entries: list[dict],
) -> list[str]:
    """Check 1 + 2: bidirectional coverage and amount agreement."""
    errors: list[str] = []

    # Index history by (trajectory, slot)
    history_index: dict[tuple[str, int], dict] = {}
    for ev in history_events:
        traj = ev.get("trajectory")
        slot = ev.get("slot")
        if traj is None or slot is None:
            errors.append(
                f"history event missing trajectory or slot: {ev}"
            )
            continue
        key = (traj, slot)
        if key in history_index:
            errors.append(
                f"duplicate history event for {traj} slot {slot}"
            )
        history_index[key] = ev

    # Index mints by (trajectory, slot)
    mints_index: dict[tuple[str, int], dict] = {}
    for entry in mints_entries:
        traj = entry.get("trajectory")
        slot = entry.get("slot")
        if traj is None or slot is None:
            errors.append(
                f"mints entry missing trajectory or slot: {entry}"
            )
            continue
        key = (traj, slot)
        if key in mints_index:
            errors.append(
                f"duplicate mints entry for {traj} slot {slot}"
            )
        mints_index[key] = entry

    # Orphan history events (in history but not in mints)
    for key in sorted(history_index):
        if key not in mints_index:
            traj, slot = key
            errors.append(
                f"orphan history event: {traj} slot {slot} has no matching mints entry"
            )

    # Orphan mints entries (in mints but not in history)
    for key in sorted(mints_index):
        if key not in history_index:
            traj, slot = key
            errors.append(
                f"orphan mints entry: {traj} slot {slot} has no matching history event"
            )

    # Amount agreement for matched pairs
    for key in sorted(set(history_index) & set(mints_index)):
        traj, slot = key
        h_amount = history_index[key].get("amount")
        m_amount = mints_index[key].get("amount")
        if h_amount != m_amount:
            errors.append(
                f"amount mismatch for {traj} slot {slot}: "
                f"history={h_amount} mints={m_amount}"
            )

    return errors


def check_total_minted(
    history_events: list[dict],
    declared_total: int,
) -> list[str]:
    """Check 3: top-level total_minted matches sum of history event amounts."""
    computed = sum(ev.get("amount", 0) for ev in history_events)
    if computed != declared_total:
        return [
            f"total_minted mismatch: declared={declared_total} "
            f"computed from history={computed}"
        ]
    return []


def check_next_slot(
    mints_entries: list[dict],
    trajectories: dict[str, dict],
) -> list[str]:
    """Check 4: per-trajectory next_slot integrity and no slot gaps."""
    errors: list[str] = []

    # Group slots by trajectory from mints
    slots_by_traj: dict[str, list[int]] = {}
    for entry in mints_entries:
        traj = entry.get("trajectory")
        slot = entry.get("slot")
        if traj is None or slot is None:
            continue
        slots_by_traj.setdefault(traj, []).append(slot)

    for traj, slots in slots_by_traj.items():
        sorted_slots = sorted(slots)
        n = len(sorted_slots)
        expected = list(range(1, n + 1))
        if sorted_slots != expected:
            errors.append(
                f"slot gap in {traj}: have slots {sorted_slots}, expected {expected}"
            )
        expected_next = n + 1
        declared_next = trajectories.get(traj, {}).get("next_slot")
        if declared_next != expected_next:
            errors.append(
                f"next_slot wrong for {traj}: declared={declared_next} "
                f"expected={expected_next}"
            )

    # Also check trajectories that appear in trajectories dict but have no mints
    for traj, info in trajectories.items():
        if traj not in slots_by_traj:
            declared_next = info.get("next_slot")
            if declared_next != 1:
                errors.append(
                    f"next_slot wrong for {traj} (no mints): "
                    f"declared={declared_next} expected=1"
                )

    return errors


def check_per_trajectory_total_minted(
    mints_entries: list[dict],
    trajectories: dict[str, dict],
) -> list[str]:
    """Check 6: per-trajectory total_minted in trajectories dict matches sum of mints."""
    errors: list[str] = []

    # Sum amounts per trajectory from mints entries
    computed: dict[str, int] = {}
    for entry in mints_entries:
        traj = entry.get("trajectory")
        amount = entry.get("amount", 0)
        if traj is None:
            continue
        computed[traj] = computed.get(traj, 0) + amount

    for traj, info in trajectories.items():
        declared = info.get("total_minted", 0)
        actual = computed.get(traj, 0)
        if declared != actual:
            errors.append(
                f"per-trajectory total_minted wrong for {traj}: "
                f"declared={declared} computed={actual}"
            )

    return errors


def check_per_agent_sums(mints_entries: list[dict]) -> list[str]:
    """Check 5: per each mints entry, sum(per_agent) must equal amount."""
    errors: list[str] = []
    for entry in mints_entries:
        traj = entry.get("trajectory", "?")
        slot = entry.get("slot", "?")
        amount = entry.get("amount")
        per_agent = entry.get("per_agent")
        if not isinstance(per_agent, list):
            errors.append(
                f"per_agent is not a list for {traj} slot {slot}: {per_agent!r}"
            )
            continue
        total = sum(per_agent)
        if total != amount:
            errors.append(
                f"per_agent sum mismatch for {traj} slot {slot}: "
                f"sum(per_agent)={total} amount={amount}"
            )
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_checks(root: Path) -> tuple[bool, list[str]]:
    """Run all consistency checks. Returns (ok, error_lines)."""
    history_events = load_history_events(root)
    data = load_mints_file(root)

    mints_entries: list[dict] = data.get("mints", [])
    total_minted: int = data.get("total_minted", 0)
    trajectories: dict[str, dict] = data.get("trajectories", {})

    errors: list[str] = []
    errors.extend(check_bidirectional_match(history_events, mints_entries))
    errors.extend(check_total_minted(history_events, total_minted))
    errors.extend(check_next_slot(mints_entries, trajectories))
    errors.extend(check_per_agent_sums(mints_entries))
    errors.extend(check_per_trajectory_total_minted(mints_entries, trajectories))

    return (len(errors) == 0, errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-validate trajectory_mints.json against history events."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    ok, errors = run_checks(root)

    if ok:
        print("PASS: trajectory_mints.json is consistent with ledger history.")
        return 0
    else:
        print("FAIL: trajectory_mint inconsistencies detected:")
        for err in errors:
            print(f"  - {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
