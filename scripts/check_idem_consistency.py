#!/usr/bin/env python3
"""Cross-validate ledger/idem_keys.json against ledger/history/*.jsonl.

Two-directional check:
  1. Orphan keys  — idem_key recorded in a financial namespace but no matching
                    history event exists. This indicates the key was written but
                    the operation never completed (crash between key-write and
                    ledger-write). Exit 1.
  2. Keyless events — financial history event with no corresponding idem_key.
                    This suggests the operation predates the idem_key system or
                    was applied manually. Reported as a warning; does NOT cause
                    exit 1, because pre-idem_key history is expected and valid.

Financial payment namespaces checked:
  - String key prefixes: payment, escrow, escrow_return
  - Hash key (dict value) actions: payment

Special handling:
  - escrow_create history events are treated as escrow (alternate type name).
  - escrow_batch history events are expanded per-issue so that individual
    escrow|N|author keys can match.
  - escrow_return_bulk history events are expanded per-issue; they also serve
    as implicit evidence that each issue had an active escrow (covering
    escrow|N|actor orphan keys for issues in the bulk list).
  - Agent aliases from ledger/agent_aliases.json are applied when reading
    history, normalizing old agent names to their canonical replacements.

Usage:
    python scripts/check_idem_consistency.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# String key prefixes that represent financial operations
FINANCIAL_STRING_PREFIXES: frozenset[str] = frozenset(
    {"payment", "escrow", "escrow_return"}
)

# Hash key actions that represent financial operations
FINANCIAL_HASH_ACTIONS: frozenset[str] = frozenset({"payment"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class EventKey(NamedTuple):
    """Normalized (type, issue, actor) triple used for matching."""

    type: str    # payment | escrow | escrow_return
    issue: str   # stringified issue number
    actor: str   # canonical agent or author


# ---------------------------------------------------------------------------
# Agent alias resolution
# ---------------------------------------------------------------------------


def load_aliases(path: Path) -> dict[str, str]:
    """Load ledger/agent_aliases.json → {old_name: canonical_name}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def normalize_actor(actor: str, aliases: dict[str, str]) -> str:
    """Resolve an agent/author name to its canonical form via aliases."""
    return aliases.get(actor, actor)


# ---------------------------------------------------------------------------
# Load & parse idem_keys.json
# ---------------------------------------------------------------------------


def load_idem_keys(path: Path) -> dict[str, object]:
    """Load ledger/idem_keys.json; return empty dict if missing or malformed."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    keys = data.get("keys", {})
    return keys if isinstance(keys, dict) else {}


def _parse_string_key(raw_key: str) -> EventKey | None:
    """Parse a pipe-separated string key → EventKey, or None if non-financial."""
    parts = raw_key.split("|")
    if len(parts) < 3:
        return None
    namespace = parts[0]
    if namespace not in FINANCIAL_STRING_PREFIXES:
        return None
    return EventKey(namespace, parts[1], parts[2])


def _parse_hash_key(value: object) -> EventKey | None:
    """Parse a hash-based idem_key (dict value) → EventKey, or None."""
    if not isinstance(value, dict):
        return None
    action = value.get("action", "")
    if action not in FINANCIAL_HASH_ACTIONS:
        return None
    return EventKey(action, str(value.get("issue", "")), str(value.get("agent", "")))


def classify_idem_keys(
    keys: dict[str, object],
) -> dict[EventKey, list[str]]:
    """Return EventKey → [raw_key, ...] for all financial idem_keys."""
    financial: dict[EventKey, list[str]] = defaultdict(list)
    for raw_key, value in keys.items():
        ek = _parse_hash_key(value) if isinstance(value, dict) else _parse_string_key(raw_key)
        if ek is not None:
            financial[ek].append(raw_key)
    return dict(financial)


# ---------------------------------------------------------------------------
# Load & index history events
# ---------------------------------------------------------------------------


def load_history_events(history_dir: Path) -> list[dict]:
    """Load all events from history/*.jsonl in filename (date) order."""
    events: list[dict] = []
    if not history_dir.is_dir():
        return events
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def build_event_index(
    events: list[dict],
    aliases: dict[str, str],
) -> tuple[dict[EventKey, list[dict]], set[str], set[str]]:
    """Build event index and covered-issue sets.

    Returns:
        index: EventKey → [event, ...] for individual financial events
        escrow_covered: issue numbers implicitly covered by escrow_batch or
            escrow_return_bulk (escrow existence is proven even without an
            individual escrow history entry)
        return_covered: issue numbers covered by escrow_return_bulk (return
            was performed even without an individual escrow_return entry)
    """
    index: dict[EventKey, list[dict]] = defaultdict(list)
    escrow_covered: set[str] = set()
    return_covered: set[str] = set()

    for event in events:
        t = event.get("type", "")
        issue = str(event.get("issue", ""))
        raw_actor = event.get("agent") or event.get("author") or ""
        actor = normalize_actor(str(raw_actor), aliases)

        if t in ("escrow", "escrow_create"):
            # escrow_create is an alternate type name for the same operation
            index[EventKey("escrow", issue, actor)].append(event)

        elif t == "escrow_return":
            index[EventKey("escrow_return", issue, actor)].append(event)

        elif t == "payment":
            index[EventKey("payment", issue, actor)].append(event)

        elif t == "escrow_batch":
            # Batch escrow: each issue had an individual escrow key written.
            # Mark issues as covered without adding to the individual index.
            for issue_n in event.get("issues", []):
                escrow_covered.add(str(issue_n))

        elif t == "escrow_return_bulk":
            # Bulk escrow return: each issue had an active escrow that was
            # returned. Both escrow and escrow_return are implicitly covered.
            for issue_n in event.get("issues", []):
                s = str(issue_n)
                escrow_covered.add(s)
                return_covered.add(s)

    return dict(index), escrow_covered, return_covered


# ---------------------------------------------------------------------------
# Consistency check
# ---------------------------------------------------------------------------


def check_consistency(
    financial_keys: dict[EventKey, list[str]],
    event_index: dict[EventKey, list[dict]],
    escrow_covered: set[str],
    return_covered: set[str],
) -> tuple[list[str], list[str]]:
    """Return (orphan_keys, keyless_events).

    orphan_keys: idem_key in financial namespace with no evidence of the
        corresponding operation in history.
    keyless_events: individual financial history event with no idem_key
        (informational; does not drive the exit code).
    """
    orphan_keys: list[str] = []
    keyless_events: list[str] = []

    # Direction 1: every financial idem_key must have supporting evidence in history.
    for ek, raw_keys in financial_keys.items():
        found = ek in event_index
        if not found:
            if ek.type == "escrow" and ek.issue in escrow_covered:
                found = True
            elif ek.type == "escrow_return" and ek.issue in return_covered:
                found = True
        if not found:
            for k in raw_keys:
                orphan_keys.append(
                    f"{k!r}  (no {ek.type} event: issue={ek.issue} actor={ek.actor})"
                )

    # Direction 2: individual financial events should have a matching idem_key
    # (warning only — pre-idem_key history is expected and valid).
    for ek, evts in event_index.items():
        if ek not in financial_keys:
            for ev in evts:
                ts = ev.get("timestamp", ev.get("event_at", "?"))
                keyless_events.append(
                    f"{ek.type} issue={ek.issue} actor={ek.actor} ts={ts}"
                )

    return orphan_keys, keyless_events


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cross-validate ledger/idem_keys.json against history/*.jsonl"
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root directory (default: two levels up from this script)",
    )
    return p.parse_args(argv)


def run_check(repo_root: Path) -> tuple[int, str]:
    """Run the consistency check and return (exit_code, report_text).

    Exit 0 if no orphan keys are found. Keyless events are reported as
    informational warnings and do not affect the exit code.
    """
    idem_path = repo_root / "ledger" / "idem_keys.json"
    history_dir = repo_root / "ledger" / "history"
    aliases_path = repo_root / "ledger" / "agent_aliases.json"

    aliases = load_aliases(aliases_path)
    raw_keys = load_idem_keys(idem_path)
    events = load_history_events(history_dir)

    financial_keys = classify_idem_keys(raw_keys)
    event_index, escrow_covered, return_covered = build_event_index(events, aliases)

    orphan_keys, keyless_events = check_consistency(
        financial_keys, event_index, escrow_covered, return_covered
    )

    total_keys = len(financial_keys)
    total_events = sum(len(v) for v in event_index.values())

    lines: list[str] = [
        f"Financial idem_keys: {total_keys}  |  Financial history events: {total_events}"
    ]

    if orphan_keys:
        lines.append(
            f"\nORPHAN KEYS ({len(orphan_keys)}) — key recorded, no matching event:"
        )
        for entry in sorted(orphan_keys):
            lines.append(f"  orphan_key: {entry}")

    if keyless_events:
        lines.append(
            f"\nKEYLESS EVENTS ({len(keyless_events)}) — event has no idem_key"
            " (pre-key era or manual, informational):"
        )
        for entry in sorted(keyless_events):
            lines.append(f"  keyless_event: {entry}")

    if orphan_keys:
        lines.append(f"\nFAIL: {len(orphan_keys)} orphan key(s) found")
        exit_code = 1
    else:
        lines.append("\nOK: no orphan keys — idem_keys.json is consistent with history")
        exit_code = 0

    return exit_code, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.root or Path(__file__).resolve().parent.parent
    exit_code, report = run_check(repo_root)
    print(report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
