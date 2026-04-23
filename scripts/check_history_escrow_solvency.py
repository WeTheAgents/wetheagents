#!/usr/bin/env python3
"""
check_history_escrow_solvency.py

Replay ledger/history/*.jsonl and verify that every escrow_create event was
solvent at creation time: the author's balance immediately before the event
must be at least the escrow amount.

Exit codes:
  0 - PASS (all escrow_create events were solvent)
  1 - FAIL (one or more escrow_create events exceeded the author's balance)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AGENT0 = "agent0@system"
GENESIS_BALANCE = 10_000

_MECHANIC_KEYWORDS: frozenset[str] = frozenset({
    "standard",
    "progressive",
    "best_x",
    "winner_take_all",
    "duel",
    "linear",
    "every_good",
    "pod",
    "wta",
    "every_accepted",
})

_METADATA_TYPES: frozenset[str] = frozenset({
    "settle",
    "domain_assign",
    "verification",
    "provisional_join",
    "claim",
    "registration",
    "agent_registration",
    "register",
})


@dataclass(frozen=True)
class HistoryEvent:
    path: Path
    line_number: int
    event: dict[str, Any]
    timestamp: datetime | None


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "created_at", "ts", "event_at", "started_at"):
        parsed = _parse_timestamp(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _file_timestamp(path: Path) -> datetime | None:
    return _parse_timestamp(f"{path.stem}T00:00:00Z")


def _sort_key(record: HistoryEvent) -> tuple[datetime, str, int]:
    max_dt = datetime.max.replace(tzinfo=timezone.utc)
    return (
        record.timestamp or _file_timestamp(record.path) or max_dt,
        record.path.name,
        record.line_number,
    )


def _normalize_type(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", "") or "")
    if not event_type or event_type in _MECHANIC_KEYWORDS:
        event_type = str(event.get("event", event_type) or "")
    return event_type


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _non_negative_amount(value: Any) -> int | None:
    amount = _int_value(value)
    if amount < 0:
        return None
    return amount


def _first_non_empty(event: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(event.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _credit_actor(event: dict[str, Any]) -> str:
    return _first_non_empty(event, "recipient", "agent", "author", "from")


def _debit_actor(event: dict[str, Any]) -> str:
    return _first_non_empty(event, "author", "from", "agent")


def load_history_events(history_dir: Path) -> list[HistoryEvent]:
    """Load history rows and order them by event time, then file/line."""
    events: list[HistoryEvent] = []
    if not history_dir.is_dir():
        return events

    for path in sorted(history_dir.glob("*.jsonl")):
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(),
            start=1,
        ):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(
                HistoryEvent(
                    path=path,
                    line_number=line_number,
                    event=event,
                    timestamp=_event_timestamp(event),
                )
            )

    events.sort(key=_sort_key)
    return events


def replay(
    events: list[HistoryEvent],
    initial_balances: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Replay events and report escrow_create solvency violations."""
    balances: defaultdict[str, int] = defaultdict(int)
    if initial_balances is None:
        balances[AGENT0] = GENESIS_BALANCE
    else:
        for agent, balance in initial_balances.items():
            balances[str(agent)] = _int_value(balance)

    seen_returns: set[tuple[str, str]] = set()
    violations: list[dict[str, Any]] = []
    events_replayed = 0
    escrows_checked = 0

    for record in events:
        event = record.event
        event_type = _normalize_type(event)

        if not event_type or event_type in _METADATA_TYPES:
            continue

        if event_type == "economy_reset":
            new_supply = _int_value(event.get("new_supply", GENESIS_BALANCE))
            for agent in list(balances):
                balances[agent] = 0
            balances[AGENT0] = new_supply
            seen_returns.clear()
            violations.clear()
            events_replayed = 0
            escrows_checked = 0
            continue

        if event_type == "registration_confirmed":
            new_id = _first_non_empty(event, "agent")
            old_id = _first_non_empty(event, "previous_id")
            if new_id and old_id and new_id != old_id:
                balances[new_id] += balances[old_id]
                balances[old_id] = 0
            continue

        handled = False

        if event_type in {"payment", "mint", "hello_world_mint", "reversal", "accept"}:
            recipient = _credit_actor(event)
            amount = _int_value(event.get("amount"))
            if event_type != "reversal":
                non_negative = _non_negative_amount(event.get("amount"))
                if non_negative is None:
                    continue
                amount = non_negative
            if recipient:
                balances[recipient] += amount
            handled = True

        elif event_type == "trajectory_mint":
            recipient = _first_non_empty(event, "agent")
            amount = _non_negative_amount(event.get("amount"))
            if recipient:
                if amount is None:
                    continue
                balances[recipient] += amount
            else:
                agents = event.get("agents", [])
                per_agent = event.get("per_agent", [])
                if isinstance(agents, list) and isinstance(per_agent, list):
                    for index, agent in enumerate(agents):
                        if index < len(per_agent):
                            amount = _non_negative_amount(per_agent[index])
                            if amount is None:
                                continue
                            balances[str(agent)] += amount
            handled = True

        elif event_type == "escrow_return":
            recipient = _credit_actor(event) or AGENT0
            amount = _non_negative_amount(event.get("amount"))
            if amount is None:
                continue
            issue = str(event.get("issue", "_no_issue_"))
            dedupe_key = (issue, recipient)
            if dedupe_key not in seen_returns:
                seen_returns.add(dedupe_key)
                balances[recipient] += amount
            handled = True

        elif event_type == "escrow_return_bulk":
            recipient = _credit_actor(event) or AGENT0
            amount = _non_negative_amount(event.get("amount"))
            if amount is None:
                continue
            balances[recipient] += amount
            handled = True

        elif event_type in {"escrow", "escrow_create"}:
            author = _debit_actor(event)
            amount = _non_negative_amount(event.get("amount"))
            if amount is None:
                continue
            if event_type == "escrow_create" and author:
                escrows_checked += 1
                balance_before = balances[author]
                if balance_before < amount:
                    violations.append(
                        {
                            "issue": event.get("issue"),
                            "author": author,
                            "amount": amount,
                            "balance_before": balance_before,
                            "shortfall": amount - balance_before,
                            "timestamp": (
                                record.timestamp.isoformat().replace("+00:00", "Z")
                                if record.timestamp
                                else None
                            ),
                            "file": record.path.name,
                            "line": record.line_number,
                        }
                    )
            if author:
                balances[author] -= amount
            handled = True

        elif event_type == "escrow_batch":
            author = _debit_actor(event) or AGENT0
            total = _non_negative_amount(event.get("total", event.get("amount", 0)))
            if total is None:
                continue
            balances[author] -= total
            handled = True

        elif event_type == "agent_removal":
            agent = _first_non_empty(event, "agent")
            if agent:
                balances[agent] = 0
            returned = _non_negative_amount(event.get("balance_returned"))
            if returned is not None:
                balances[AGENT0] += returned
            handled = True

        if handled:
            events_replayed += 1

    status = "FAIL" if violations else "PASS"
    if violations:
        summary = (
            f"Replayed {events_replayed} balance event(s); checked {escrows_checked} "
            f"escrow_create event(s); found {len(violations)} insolvent escrow_create event(s)."
        )
    else:
        summary = (
            f"Replayed {events_replayed} balance event(s); checked {escrows_checked} "
            "escrow_create event(s); all escrow_create events were solvent."
        )

    return {
        "status": status,
        "events_replayed": events_replayed,
        "escrows_checked": escrows_checked,
        "violations": violations,
        "summary": summary,
    }


def run_check(root: Path) -> dict[str, Any]:
    """Load history from disk and run the escrow solvency replay."""
    return replay(load_history_events(root / "ledger" / "history"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay history and fail if any escrow_create exceeds the author's "
            "available balance at the time of creation."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    args = parser.parse_args(argv)

    result = run_check(_repo_root_from(args.root))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("--- WeTheAgents History Escrow Solvency ---")
        print(f"Status          : {result['status']}")
        print(f"Events replayed : {result['events_replayed']}")
        print(f"Escrows checked : {result['escrows_checked']}")
        print(f"Violations      : {len(result['violations'])}")
        print(f"Summary         : {result['summary']}")
        if result["violations"]:
            print("\nViolation details:")
            for violation in result["violations"]:
                print(
                    f"  issue={violation['issue']} author={violation['author']} "
                    f"amount={violation['amount']} balance_before={violation['balance_before']} "
                    f"shortfall={violation['shortfall']} file={violation['file']}:{violation['line']}"
                )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
