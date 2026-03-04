#!/usr/bin/env python3
"""Check provisional registrations TTL without mutating ledger state.

Usage examples:
    python scripts/check_provisional.py
    python scripts/check_provisional.py --root .
    python scripts/check_provisional.py --root . --now 2026-03-05T12:30:00Z

Exit codes:
    0 -> no expired provisional agents found
    1 -> one or more provisional agents are expired
    2 -> runtime/input error (files, JSON, timestamp parsing)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_iso_utc(value: str) -> datetime:
    """Parse ISO timestamp and normalize to UTC-aware datetime."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_root(root_arg: str | None) -> Path:
    if root_arg:
        root = Path(root_arg).resolve()
        if (root / "ledger" / "balances.json").exists():
            return root
        raise FileNotFoundError(f"Cannot find ledger/balances.json under: {root}")

    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ledger" / "balances.json").exists():
            return candidate

    raise FileNotFoundError("Cannot auto-detect repository root (ledger/balances.json not found).")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_payment_summary(root: Path, agent_id: str) -> dict[int, dict[str, int]]:
    """Return per-issue payment count/amount for a provisional agent."""
    summary: dict[int, dict[str, int]] = {}
    history_dir = root / "ledger" / "history"
    if not history_dir.exists():
        return summary

    for path in sorted(history_dir.glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # History is append-only; skip malformed lines but keep report working.
                print(f"WARN: malformed JSON in {path.name}:{lineno}", file=sys.stderr)
                continue

            if not isinstance(event, dict):
                continue
            if str(event.get("type", "")) != "payment":
                continue
            if str(event.get("agent", "")) != agent_id:
                continue

            issue_raw = event.get("issue")
            amount_raw = event.get("amount", 0)
            try:
                issue = int(issue_raw)
                amount = int(amount_raw)
            except (TypeError, ValueError):
                continue

            stats = summary.setdefault(issue, {"count": 0, "amount": 0})
            stats["count"] += 1
            stats["amount"] += amount

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check provisional registration TTL in ledger/balances.json")
    parser.add_argument("--root", default=None, help="Repository root (auto-detected if omitted)")
    parser.add_argument("--now", default=None, help="Override current UTC time (ISO format)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        root = resolve_root(args.root)
        balances_payload = load_json(root / "ledger" / "balances.json")
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    try:
        now_dt = parse_iso_utc(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as exc:
        print(f"ERROR: invalid --now value: {exc}")
        return 2

    if not isinstance(balances_payload, dict):
        print("ERROR: balances.json root must be an object")
        return 2

    agents = balances_payload.get("agents", {})
    if not isinstance(agents, dict):
        print("ERROR: balances.json field `agents` must be an object")
        return 2

    provisionals: list[tuple[str, dict[str, Any]]] = []
    for agent_id, info in agents.items():
        if isinstance(info, dict) and bool(info.get("provisional")):
            provisionals.append((str(agent_id), info))

    now_text = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    print("=== Provisional TTL Report ===")
    print(f"Root: {root}")
    print(f"Now (UTC): {now_text}")
    print(f"Provisional agents found: {len(provisionals)}")

    if not provisionals:
        print("\nOK: no provisional agents.")
        return 0

    expired_found = False
    for agent_id, info in sorted(provisionals, key=lambda item: item[0].lower()):
        balance = int(info.get("balance", 0))
        expires_raw = str(info.get("provisional_expires", "")).strip()
        github_username = str(info.get("github_username", "unknown")).strip() or "unknown"

        print("\n---")
        print(f"Agent: {agent_id}")
        print(f"GitHub: {github_username}")
        print(f"Balance: {balance} WEA")
        print(f"Provisional expires: {expires_raw or '(missing)'}")

        if not expires_raw:
            expired_found = True
            print("Status: EXPIRED/INVALID (missing provisional_expires)")
            print("Recommended action: investigate timestamp, then reverse provisional payouts manually.")
            continue

        try:
            expires_dt = parse_iso_utc(expires_raw)
        except ValueError:
            expired_found = True
            print("Status: EXPIRED/INVALID (cannot parse provisional_expires)")
            print("Recommended action: fix malformed timestamp and review provisional payouts.")
            continue

        delta_seconds = int((expires_dt - now_dt).total_seconds())
        if delta_seconds > 0:
            hours_left = delta_seconds / 3600.0
            print(f"Status: ACTIVE ({hours_left:.2f}h left)")
            continue

        expired_found = True
        overdue_hours = abs(delta_seconds) / 3600.0
        print(f"Status: EXPIRED ({overdue_hours:.2f}h overdue)")

        summary = load_payment_summary(root, agent_id)
        if summary:
            print("Payment history to reverse (suggested):")
            for issue in sorted(summary.keys()):
                stats = summary[issue]
                print(f"- issue #{issue}: {stats['count']} payment(s), {stats['amount']} WEA total")
        else:
            print("Payment history to reverse (suggested): none found in ledger/history/*.jsonl")

        print("Recommended reversal actions:")
        print("1. Reverse provisional payments and return WEA to corresponding escrows.")
        print("2. Remove provisional agent from balances.json after reversal is complete.")
        print("3. Append reversal events to ledger/history and idem keys.")
        print("4. Comment on source issue: 24h expired, WEA returned, re-submit after proper onboarding.")

    if expired_found:
        print("\nFAIL: one or more provisional registrations are expired/invalid.")
        return 1

    print("\nOK: all provisional registrations are still within TTL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
