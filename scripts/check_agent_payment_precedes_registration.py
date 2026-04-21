#!/usr/bin/env python3
"""Verify no agent receives a payment before their registration date.

Usage:
    python scripts/check_agent_payment_precedes_registration.py [--root PATH]

Scans all JSONL files in ledger/history/ in chronological order (filename =
date). Tracks the first registration event date for each agent across event
types ``registration``, ``agent_registration``, and ``register``. For each
payment, accept, or trajectory_mint event, verifies that the recipient agent
was registered on an earlier or same date.

Only agents that have at least one registration event in history are checked.
Agents paid without any history registration event are not flagged (they may
have been registered before event-logging began).

Output schema:
    {
      "status": "pass" | "fail",
      "violations": [
        {
          "agent": "...",
          "payment_date": "YYYY-MM-DD",
          "registration_date": "YYYY-MM-DD",
          "issue": N,
          "amount": N
        }
      ],
      "stats": {
        "agents_checked": N,
        "payments_checked": N,
        "violations_found": N
      }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REGISTRATION_TYPES: frozenset[str] = frozenset(
    {"registration", "agent_registration", "register", "registration_confirmed"}
)
_PAYMENT_TYPES: frozenset[str] = frozenset({"payment", "accept", "trajectory_mint"})


def _repo_root(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def _load_jsonl_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return events


def collect_registration_dates(history_dir: Path) -> dict[str, str]:
    """Return the first file-date on which each agent has a registration event."""
    reg_dates: dict[str, str] = {}
    for path in sorted(history_dir.glob("*.jsonl")):
        file_date = path.stem
        for event in _load_jsonl_events(path):
            if event.get("type") not in _REGISTRATION_TYPES:
                continue
            agent = str(event.get("agent", "")).strip()
            if agent and agent not in reg_dates:
                reg_dates[agent] = file_date
    return reg_dates


def check_payments(
    history_dir: Path,
    reg_dates: dict[str, str],
) -> tuple[list[dict[str, Any]], set[str], int]:
    """Scan payment events and return (violations, checked_agents, payments_checked)."""
    violations: list[dict[str, Any]] = []
    checked_agents: set[str] = set()
    payments_checked = 0

    for path in sorted(history_dir.glob("*.jsonl")):
        file_date = path.stem
        for event in _load_jsonl_events(path):
            event_type = event.get("type")
            if event_type not in _PAYMENT_TYPES:
                continue

            if event_type == "trajectory_mint":
                agents = [str(a).strip() for a in event.get("agents", []) if a]
                per_agent = event.get("per_agent", [])
                issue = event.get("issue")
                for idx, agent in enumerate(agents):
                    if agent not in reg_dates:
                        continue
                    amount = per_agent[idx] if idx < len(per_agent) else None
                    payments_checked += 1
                    checked_agents.add(agent)
                    if file_date < reg_dates[agent]:
                        violations.append(
                            {
                                "agent": agent,
                                "payment_date": file_date,
                                "registration_date": reg_dates[agent],
                                "issue": issue,
                                "amount": amount,
                            }
                        )
            else:
                agent = str(event.get("agent", "")).strip()
                if not agent or agent not in reg_dates:
                    continue
                payments_checked += 1
                checked_agents.add(agent)
                if file_date < reg_dates[agent]:
                    violations.append(
                        {
                            "agent": agent,
                            "payment_date": file_date,
                            "registration_date": reg_dates[agent],
                            "issue": event.get("issue"),
                            "amount": event.get("amount"),
                        }
                    )

    return violations, checked_agents, payments_checked


def build_report(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"

    if not history_dir.is_dir():
        return {
            "status": "pass",
            "violations": [],
            "stats": {
                "agents_checked": 0,
                "payments_checked": 0,
                "violations_found": 0,
            },
        }

    reg_dates = collect_registration_dates(history_dir)
    violations, checked_agents, payments_checked = check_payments(history_dir, reg_dates)

    return {
        "status": "fail" if violations else "pass",
        "violations": violations,
        "stats": {
            "agents_checked": len(checked_agents),
            "payments_checked": payments_checked,
            "violations_found": len(violations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify no agent is paid before their registration date"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_repo_root(Path(__file__)),
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    report = build_report(args.root.resolve())
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
