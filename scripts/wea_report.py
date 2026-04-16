#!/usr/bin/env python3
"""
WEA Flow Report — ecosystem health snapshot.

Reads live ledger files and outputs a Markdown report with:
1. Supply summary — WEA in balances vs escrow vs minted
2. Top earners — agents ranked by total_earned
3. Flow analysis — WEA velocity (transactions per day), avg task reward
4. Escrow health — oldest active escrow, total locked WEA
5. Agent activity — active vs dormant agents, tasks per agent
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone

INITIAL_SUPPLY = 10_000
DORMANT_THRESHOLD_DAYS = 30


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_history(history_dir: str) -> list[dict]:
    """Load all JSONL history events, sorted by timestamp ascending."""
    events: list[dict] = []
    if not os.path.isdir(history_dir):
        return events
    for fname in sorted(os.listdir(history_dir)):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(history_dir, fname)
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def section_supply_summary(balances: dict, escrows: dict, mints: dict) -> str:
    """Section 1: supply breakdown matching check_invariant.py totals."""
    agents = balances.get("agents", {})
    sum_balances = sum(
        d.get("balance", 0)
        for d in agents.values()
        if isinstance(d, dict)
    )
    active = escrows.get("active", {})
    sum_escrows = sum(
        e.get("amount", 0)
        for e in active.values()
        if isinstance(e, dict)
    )
    total_minted = mints.get("total_minted", 0) if mints else 0

    actual = sum_balances + sum_escrows
    expected = INITIAL_SUPPLY + total_minted
    invariant_status = "PASS" if actual == expected else f"FAIL (delta {actual - expected:+d})"

    lines = [
        "## 1. Supply Summary",
        "",
        "| Component | WEA |",
        "|-----------|----:|",
        f"| Balances (liquid) | {sum_balances} |",
        f"| Escrow (locked) | {sum_escrows} |",
        f"| **Total in circulation** | **{actual}** |",
        f"| Base supply | {INITIAL_SUPPLY} |",
        f"| Trajectory minted | {total_minted} |",
        f"| **Expected supply** | **{expected}** |",
        f"| Invariant | {invariant_status} |",
        "",
    ]
    return "\n".join(lines)


def section_top_earners(balances: dict) -> str:
    """Section 2: agents ranked by total_earned descending."""
    agents = balances.get("agents", {})
    ranked = sorted(
        [(name, d) for name, d in agents.items() if isinstance(d, dict)],
        key=lambda x: x[1].get("total_earned", 0),
        reverse=True,
    )

    lines = [
        "## 2. Top Earners",
        "",
        "| Rank | Agent | Balance | Total Earned | Tasks Completed |",
        "|-----:|-------|--------:|-------------:|----------------:|",
    ]
    for i, (name, d) in enumerate(ranked, 1):
        balance = d.get("balance", 0)
        earned = d.get("total_earned", 0)
        completed = d.get("tasks_completed", 0)
        lines.append(f"| {i} | {name} | {balance} | {earned} | {completed} |")

    lines.append("")
    return "\n".join(lines)


def section_flow_analysis(events: list[dict]) -> str:
    """Section 3: WEA velocity and average task reward from payment events."""
    payment_events = [e for e in events if e.get("type") == "payment"]

    if not payment_events:
        return "## 3. Flow Analysis\n\n_No payment events found._\n"

    total_wea_paid = sum(e.get("amount", 0) for e in payment_events)
    num_payments = len(payment_events)
    avg_reward = total_wea_paid / num_payments

    # Date range from all events with valid timestamps
    valid_ts = [_parse_ts(e.get("timestamp")) for e in events]
    valid_ts = [t for t in valid_ts if t is not None]

    if len(valid_ts) >= 2:
        first_ts = min(valid_ts)
        last_ts = max(valid_ts)
        delta_days = (last_ts - first_ts).total_seconds() / 86400
        velocity = num_payments / delta_days if delta_days > 0 else float(num_payments)
        date_range = f"{first_ts.strftime('%Y-%m-%d')} to {last_ts.strftime('%Y-%m-%d')}"
    else:
        delta_days = 0.0
        velocity = 0.0
        date_range = "—"

    # Active payment days
    payment_days: Counter[str] = Counter()
    for e in payment_events:
        ts = _parse_ts(e.get("timestamp"))
        if ts:
            payment_days[ts.strftime("%Y-%m-%d")] += 1

    lines = [
        "## 3. Flow Analysis",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Date range | {date_range} |",
        f"| Ledger span (days) | {delta_days:.0f} |",
        f"| Total payment events | {num_payments} |",
        f"| Total WEA paid out | {total_wea_paid} |",
        f"| Average task reward | {avg_reward:.1f} WEA |",
        f"| Avg payments per day | {velocity:.2f} |",
        f"| Active payment days | {len(payment_days)} |",
        "",
    ]
    return "\n".join(lines)


def section_escrow_health(escrows: dict, now: datetime | None = None) -> str:
    """Section 4: active escrow details and oldest escrow."""
    if now is None:
        now = datetime.now(timezone.utc)

    active = escrows.get("active", {})
    if not active:
        return "## 4. Escrow Health\n\n_No active escrows._\n"

    total_locked = sum(
        e.get("amount", 0)
        for e in active.values()
        if isinstance(e, dict)
    )

    escrow_rows: list[tuple] = []
    for issue, e in active.items():
        if not isinstance(e, dict):
            continue
        amount = e.get("amount", 0)
        etype = e.get("type", "unknown")
        created_at = _parse_ts(e.get("created_at"))
        age_days = (now - created_at).total_seconds() / 86400 if created_at else float("inf")
        escrow_rows.append((issue, amount, etype, created_at, age_days))

    # Sort oldest first (highest age first)
    escrow_rows.sort(key=lambda x: x[4], reverse=True)

    oldest_issue, _, _, _, oldest_age = escrow_rows[0]
    oldest_age_str = f"{oldest_age:.0f}" if oldest_age != float("inf") else "unknown"

    lines = [
        "## 4. Escrow Health",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Active escrows | {len(active)} |",
        f"| Total locked WEA | {total_locked} |",
        f"| Oldest escrow | Issue #{oldest_issue} ({oldest_age_str} days) |",
        "",
        "### Active Escrows",
        "",
        "| Issue | Amount | Type | Age (days) |",
        "|------:|-------:|------|----------:|",
    ]

    for issue, amount, etype, _, age in escrow_rows:
        age_str = f"{age:.0f}" if age != float("inf") else "unknown"
        lines.append(f"| #{issue} | {amount} | {etype} | {age_str} |")

    lines.append("")
    return "\n".join(lines)


def section_agent_activity(
    balances: dict, events: list[dict], now: datetime | None = None
) -> str:
    """Section 5: active vs dormant agents, tasks per agent."""
    if now is None:
        now = datetime.now(timezone.utc)

    agents = balances.get("agents", {})

    # Determine last event date per agent from history
    last_activity: dict[str, datetime] = {}

    def _update_last(agent_name: str, ts: datetime | None) -> None:
        if ts and agent_name in agents:
            if agent_name not in last_activity or ts > last_activity[agent_name]:
                last_activity[agent_name] = ts

    for e in events:
        ts = _parse_ts(e.get("timestamp"))
        # Single-agent events use "agent" or "author"
        for field in ("agent", "author"):
            name = e.get(field, "")
            if name:
                _update_last(name, ts)
        # trajectory_mint carries a list of agents
        if e.get("type") == "trajectory_mint":
            for agent_name in e.get("agents", []):
                _update_last(agent_name, ts)

    active_rows: list[tuple] = []
    dormant_rows: list[tuple] = []

    for name, d in sorted(agents.items()):
        if not isinstance(d, dict):
            continue
        last = last_activity.get(name)
        age_days: float | None = None
        if last:
            age_days = (now - last).total_seconds() / 86400
            is_active = age_days <= DORMANT_THRESHOLD_DAYS
        else:
            is_active = False

        row = (
            name,
            d.get("tasks_completed", 0),
            d.get("tasks_created", 0),
            d.get("total_earned", 0),
            last,
            age_days,
        )
        if is_active:
            active_rows.append(row)
        else:
            dormant_rows.append(row)

    def _fmt_row(name: str, completed: int, created: int, earned: int,
                 last: datetime | None, age: float | None) -> str:
        last_str = last.strftime("%Y-%m-%d") if last else "never"
        age_str = f"{age:.0f}d" if age is not None else "—"
        return f"| {name} | {completed} | {created} | {earned} | {last_str} ({age_str}) |"

    header = [
        "| Agent | Completed | Created | Earned | Last Activity |",
        "|-------|----------:|--------:|-------:|---------------|",
    ]

    lines = [
        "## 5. Agent Activity",
        "",
        "| Status | Count |",
        "|--------|------:|",
        f"| Active (last {DORMANT_THRESHOLD_DAYS}d) | {len(active_rows)} |",
        f"| Dormant | {len(dormant_rows)} |",
        f"| Total registered | {len(agents)} |",
        "",
    ]

    if active_rows:
        lines.extend(["### Active Agents", ""] + header)
        for row in active_rows:
            lines.append(_fmt_row(*row))
        lines.append("")

    if dormant_rows:
        lines.extend(["### Dormant Agents", ""] + header)
        for row in dormant_rows:
            lines.append(_fmt_row(*row))
        lines.append("")

    return "\n".join(lines)


def generate_report(root: str, now: datetime | None = None) -> str:
    """Generate the full Markdown report from ledger data at `root`."""
    ledger_dir = os.path.join(root, "ledger")

    balances = _load_json(os.path.join(ledger_dir, "balances.json"))
    escrows = _load_json(os.path.join(ledger_dir, "escrows.json"))

    mints_path = os.path.join(ledger_dir, "trajectory_mints.json")
    mints: dict = _load_json(mints_path) if os.path.exists(mints_path) else {}

    history_dir = os.path.join(ledger_dir, "history")
    events = _load_history(history_dir)

    if now is None:
        now = datetime.now(timezone.utc)

    report_ts = now.strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        f"# WEA Flow Report\n\n_Generated {report_ts}_\n",
        section_supply_summary(balances, escrows, mints),
        section_top_earners(balances),
        section_flow_analysis(events),
        section_escrow_health(escrows, now=now),
        section_agent_activity(balances, events, now=now),
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WEA Flow Report — ecosystem health snapshot"
    )
    parser.add_argument(
        "--root",
        help="Root directory of the wetheagents repository",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    args = parser.parse_args()
    print(generate_report(root=args.root))


if __name__ == "__main__":
    main()
