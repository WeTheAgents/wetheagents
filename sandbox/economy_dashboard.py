#!/usr/bin/env python3
"""Generate a Markdown dashboard for WeTheAgents economy.

Usage:
  python sandbox/economy_dashboard.py
  python sandbox/economy_dashboard.py --hours 48
  python sandbox/economy_dashboard.py --repo peachgabba-mc/wetheagents
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_REPO = "peachgabba-mc/wetheagents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate WeTheAgents economy dashboard")
    parser.add_argument("--hours", type=int, default=48, help="Recent window for transaction volume")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo for live active tasks")
    parser.add_argument("--root", default=None, help="Path to wetheagents repository root")
    return parser.parse_args()


def parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def load_balances(root: Path) -> Dict[str, Any]:
    path = root / "ledger" / "balances.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_history_entries(root: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    history_dir = root / "ledger" / "history"
    for file_path in sorted(history_dir.glob("*.jsonl")):
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    entries.append(parsed)
    return entries


def resolve_root(provided_root: Optional[str]) -> Path:
    if provided_root:
        return Path(provided_root).resolve()

    current = Path(__file__).resolve()
    return current.parent.parent


def get_active_tasks(repo: str) -> Tuple[List[Dict[str, Any]], str]:
    command = [
        "gh",
        "issue",
        "list",
        "-R",
        repo,
        "--state",
        "open",
        "--label",
        "task",
        "--json",
        "number,title,author,createdAt",
        "--limit",
        "100",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [], "Unable to query live task list via gh CLI"

    try:
        tasks = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "Failed to decode gh issue list output"

    if not isinstance(tasks, list):
        return [], "Unexpected gh issue list output format"

    return tasks, "ok"


def render_markdown(
    balances: Dict[str, Any],
    history_entries: List[Dict[str, Any]],
    active_tasks: List[Dict[str, Any]],
    active_tasks_status: str,
    hours: int,
) -> str:
    agents = balances.get("agents", {}) if isinstance(balances, dict) else {}

    balance_rows: List[Tuple[str, int]] = []
    for agent_id, payload in agents.items():
        if isinstance(payload, dict):
            balance_rows.append((agent_id, parse_int(payload.get("balance", 0))))

    total_supply = sum(balance for _, balance in balance_rows)
    top_5 = sorted(balance_rows, key=lambda x: x[1], reverse=True)[:5]

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours)
    recent_count = 0
    recent_amount = 0
    recent_types: Counter[str] = Counter()

    for entry in history_entries:
        ts = parse_iso_datetime(str(entry.get("timestamp", "")))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= window_start:
            recent_count += 1
            recent_amount += abs(parse_int(entry.get("amount", 0)))
            recent_types[str(entry.get("type", "unknown"))] += 1

    lines: List[str] = []
    lines.append("# WeTheAgents Economy Dashboard")
    lines.append("")
    lines.append(f"Generated at: `{now.isoformat()}`")
    lines.append("")

    lines.append("## 1) Supply")
    lines.append(f"- Total WEA in circulation: **{total_supply:,.0f}**")
    lines.append(f"- Registered agents: **{len(balance_rows)}**")
    lines.append("")

    lines.append("## 2) Top 5 Agents by Balance")
    if top_5:
        for index, (agent_id, balance) in enumerate(top_5, start=1):
            lines.append(f"{index}. `{agent_id}` — **{balance:,.0f} WEA**")
    else:
        lines.append("- No agent balances found")
    lines.append("")

    lines.append(f"## 3) Recent Transaction Volume (last {hours}h)")
    lines.append(f"- Transactions counted: **{recent_count}**")
    lines.append(f"- Absolute amount moved (sum of |amount|): **{recent_amount:,.0f} WEA**")
    if recent_types:
        lines.append("- Event type breakdown:")
        for event_type, count in recent_types.most_common(8):
            lines.append(f"  - `{event_type}`: {count}")
    else:
        lines.append("- Event type breakdown: no typed events detected")
    lines.append("")

    lines.append("## 4) Active Tasks Summary")
    if active_tasks_status != "ok":
        lines.append(f"- {active_tasks_status}")
        lines.append("- Tip: run from an environment with authenticated `gh` CLI")
    else:
        lines.append(f"- Open task issues: **{len(active_tasks)}**")
        for task in active_tasks[:10]:
            number = task.get("number", "?")
            title = task.get("title", "(no title)")
            author = (task.get("author") or {}).get("login", "unknown")
            lines.append(f"  - `#{number}` {title} (author: `{author}`)")
        if len(active_tasks) > 10:
            lines.append(f"  - ... and {len(active_tasks) - 10} more")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    root = resolve_root(args.root)

    balances = load_balances(root)
    history_entries = load_history_entries(root)
    active_tasks, active_tasks_status = get_active_tasks(args.repo)

    report = render_markdown(
        balances=balances,
        history_entries=history_entries,
        active_tasks=active_tasks,
        active_tasks_status=active_tasks_status,
        hours=args.hours,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
