#!/usr/bin/env python3
"""Verify every history-payment recipient exists in balances.json.

Scans ledger/history/*.jsonl for all agents that received WEA via payment,
accept, or trajectory_mint events.  Compares against ledger/balances.json
(the registered agent set).

Classification
--------------
VIOLATION — unregistered agent received amount > 0 and cannot be attributed
            to a known rename or T1 bootstrap economy reset.
WARNING   — unregistered agent:
              * appears only in zero-amount events, OR
              * is a known former ID via registration_confirmed.previous_id, OR
              * was listed in economy_reset.agents_zeroed, OR
              * idem_keys contains a payment/accept entry for the same issue
                under a registered agent (inferred rename).

Exit code 0 if no violations (warnings are allowed); 1 on any violation or
fatal error.  Output: JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{path.name} not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc


def iter_events(history_dir: Path) -> list[dict[str, Any]]:
    """Load all JSONL events from history in filename order."""
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                events.append(entry)
    return events


def collect_payment_recipients(
    events: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return {agent_id: [receipt_info, ...]} for all payment-recipient events.

    Qualifying event types and recipient fields:
      payment/accept  — agent field
      trajectory_mint — each entry in agents[], amount from per_agent[i]
    """
    recipients: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        t = e.get("type", "")
        if t in ("payment", "accept"):
            agent = e.get("agent", "")
            if agent:
                recipients[agent].append(
                    {
                        "type": t,
                        "amount": int(e.get("amount", 0)),
                        "issue": e.get("issue"),
                    }
                )
        elif t == "trajectory_mint":
            agents = e.get("agents", [])
            per_agent = e.get("per_agent", [])
            for i, agent in enumerate(agents):
                if not agent:
                    continue
                amount = int(per_agent[i]) if i < len(per_agent) else 0
                recipients[agent].append(
                    {
                        "type": t,
                        "amount": amount,
                        "issue": e.get("issue"),
                    }
                )
    return dict(recipients)


def collect_former_ids(events: list[dict[str, Any]]) -> set[str]:
    """Collect all known former agent IDs from history.

    Sources:
      registration_confirmed.previous_id — provisional-ID-to-canonical rename
      economy_reset.agents_zeroed[]      — T1 Bootstrap reset
    """
    former: set[str] = set()
    for e in events:
        t = e.get("type", "")
        if t == "registration_confirmed":
            prev = e.get("previous_id", "")
            if prev:
                former.add(str(prev))
        elif t == "economy_reset":
            for agent in e.get("agents_zeroed", []):
                if agent:
                    former.add(str(agent))
    return former


def idem_key_implies_rename(
    unregistered_id: str,
    events: list[dict[str, Any]],
    registered_ids: set[str],
    idem_keys: dict[str, Any],
) -> bool:
    """Return True if idem_keys link payment issues to a registered agent.

    For each issue where unregistered_id received a payment or accept, checks
    whether any idem_key starting with payment|{issue}|{reg} or
    accept|{issue}|{reg} exists for a registered agent reg.  A match means
    the same task was processed under a registered ID — strong evidence of rename.

    idem_key format: prefix|issue|agent[|extra...]
    """
    paid_issues: set[str] = set()
    for e in events:
        if e.get("type") in ("payment", "accept") and e.get("agent") == unregistered_id:
            issue = e.get("issue")
            if issue is not None:
                paid_issues.add(str(issue))

    if not paid_issues:
        return False

    for key in idem_keys:
        parts = key.split("|")
        if len(parts) >= 3 and parts[0] in ("payment", "accept"):
            if parts[1] in paid_issues and parts[2] in registered_ids:
                return True
    return False


def classify_unregistered(
    agent_id: str,
    agent_events: list[dict[str, Any]],
    former_ids: set[str],
    all_events: list[dict[str, Any]],
    registered_ids: set[str],
    idem_keys: dict[str, Any],
) -> tuple[str, str]:
    """Classify an unregistered recipient as 'violation' or 'warning'.

    Returns (classification, reason).
    """
    total_received = sum(e["amount"] for e in agent_events)

    if total_received == 0:
        return "warning", "unregistered agent; all events have zero amount"

    if agent_id in former_ids:
        return "warning", "known former agent ID (renamed or economy-reset)"

    if idem_key_implies_rename(agent_id, all_events, registered_ids, idem_keys):
        return "warning", (
            "idem_keys link this ID's paid issues to a registered agent (inferred rename)"
        )

    return (
        "violation",
        f"received {total_received} WEA but not present in balances.json",
    )


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    """Run the check for repo root.  Returns (report, exit_code)."""
    balances_path = root / "ledger" / "balances.json"
    idem_keys_path = root / "ledger" / "idem_keys.json"
    history_dir = root / "ledger" / "history"

    try:
        balances_data = _load_json(balances_path)
    except ValueError as exc:
        return {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": str(exc),
        }, 1

    try:
        idem_data = _load_json(idem_keys_path)
    except ValueError as exc:
        return {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": str(exc),
        }, 1

    if not isinstance(balances_data, dict) or not isinstance(
        balances_data.get("agents"), dict
    ):
        return {
            "status": "FAIL",
            "violations": [],
            "warnings": [],
            "summary": "balances.json must contain an 'agents' object",
        }, 1

    registered_ids: set[str] = set(balances_data["agents"].keys())
    idem_keys: dict[str, Any] = {}
    if isinstance(idem_data, dict) and isinstance(idem_data.get("keys"), dict):
        idem_keys = idem_data["keys"]

    all_events = iter_events(history_dir)
    recipients = collect_payment_recipients(all_events)
    former_ids = collect_former_ids(all_events)

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for agent_id in sorted(recipients):
        if agent_id in registered_ids:
            continue
        agent_events = recipients[agent_id]
        classification, reason = classify_unregistered(
            agent_id, agent_events, former_ids, all_events, registered_ids, idem_keys
        )
        total = sum(e["amount"] for e in agent_events)
        issues = sorted(
            {e["issue"] for e in agent_events if e["issue"] is not None},
            key=lambda x: (isinstance(x, str), x),
        )
        entry: dict[str, Any] = {
            "agent": agent_id,
            "total_received": total,
            "event_count": len(agent_events),
            "issues": issues,
            "reason": reason,
        }
        if classification == "violation":
            violations.append(entry)
        else:
            warnings.append(entry)

    n_registered = len(registered_ids)
    n_history = len(recipients)
    n_unregistered = sum(1 for a in recipients if a not in registered_ids)
    status = "PASS" if not violations else "FAIL"
    summary = (
        f"{n_history} history-payment recipient(s); "
        f"{n_registered} registered; "
        f"{n_unregistered} unregistered "
        f"({len(violations)} violation(s), {len(warnings)} warning(s))."
    )

    return {
        "status": status,
        "violations": violations,
        "warnings": warnings,
        "summary": summary,
    }, 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every history-payment recipient exists in balances.json."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from this script's location).",
    )
    args = parser.parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
