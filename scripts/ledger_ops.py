"""Pure ledger operations for testable economy logic.

This module intentionally has no GitHub/network dependencies and mutates only
in-memory dictionaries loaded from fixture JSON files.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from scripts.economy_constants import SPLIT_TABLE
except ModuleNotFoundError:  # pragma: no cover - script execution fallback
    from economy_constants import SPLIT_TABLE


class LedgerError(ValueError):
    """Domain error for invalid ledger operations."""


def fib(n: int) -> int:
    if n < 1:
        raise LedgerError("Fibonacci index must be >= 1")
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a


def compute_ranking_payouts(budget: int, k: int, x: int | None = None) -> list[int]:
    """Compute payouts for [X] Best with birdie semantics."""
    if budget <= 0:
        raise LedgerError("Budget must be > 0")
    if k < 1:
        raise LedgerError("At least one ranked agent is required")

    winners = x if x is not None else k
    if winners < 1 or winners > 5:
        raise LedgerError("X must be in range 1..5")
    if k > winners:
        raise LedgerError("K cannot exceed X")

    table_key = winners if k < winners else k
    splits = SPLIT_TABLE.get(table_key)
    if splits is None:
        raise LedgerError("Unsupported winners count")

    payouts: list[int] = []
    # Ranks 2..K are floor-rounded from the split table; rank 1 gets the remainder.
    for rank_idx in range(1, k):
        payouts.append(math.floor(budget * splits[rank_idx] / 100))

    rank1 = budget - sum(payouts)
    payouts.insert(0, rank1)
    return payouts


def _require_agent(balances: dict[str, Any], agent: str) -> dict[str, Any]:
    agents = balances.setdefault("agents", {})
    if agent not in agents:
        raise LedgerError(f"Unknown agent: {agent}")
    info = agents[agent]
    if not isinstance(info, dict):
        raise LedgerError(f"Invalid agent record: {agent}")
    return info


def validate_claim(task_author: str, claimant: str) -> None:
    if not claimant:
        raise LedgerError("Claimant is required")
    if task_author == claimant:
        raise LedgerError("Task authors cannot claim their own tasks")


def create_escrow(
    balances: dict[str, Any],
    escrows: dict[str, Any],
    *,
    issue: int,
    author: str,
    reward: int,
    created_at: str,
    fee: int = 1,
    escrow_type: str = "standard",
    slots: int | None = None,
    winners: int | None = None,
) -> None:
    if reward <= 0:
        raise LedgerError("Reward must be > 0")
    if fee < 0:
        raise LedgerError("Fee must be >= 0")
    if escrow_type not in {"standard", "progressive", "linear", "best_x", "duel", "every_good"}:
        raise LedgerError(f"Unsupported escrow type: {escrow_type}")
    if escrow_type in {"progressive", "linear"} and (slots is None or slots < 1):
        raise LedgerError(f"{escrow_type.capitalize()} escrow requires slots >= 1")
    if escrow_type == "best_x" and (winners is None or winners < 1 or winners > 5):
        raise LedgerError("best_x escrow requires winners in range 1..5")

    author_info = _require_agent(balances, author)
    agent0_info = _require_agent(balances, "agent0@system")

    required = reward + fee
    if author_info.get("balance", 0) < required:
        raise LedgerError(
            f"Insufficient balance for escrow: need {required}, have {author_info.get('balance', 0)}"
        )

    issue_key = str(issue)
    active = escrows.setdefault("active", {})
    if issue_key in active:
        raise LedgerError(f"Escrow for issue #{issue} already exists")

    author_info["balance"] = int(author_info.get("balance", 0)) - reward - fee
    author_info["total_spent"] = int(author_info.get("total_spent", 0)) + reward + fee
    author_info["tasks_created"] = int(author_info.get("tasks_created", 0)) + 1
    agent0_info["balance"] = int(agent0_info.get("balance", 0)) + fee
    agent0_info["total_earned"] = int(agent0_info.get("total_earned", 0)) + fee

    escrow_entry: dict[str, Any] = {
        "author": author,
        "amount": reward,
        "type": escrow_type,
        "created_at": created_at,
    }
    if slots is not None:
        escrow_entry["slots"] = slots
        escrow_entry["paid_count"] = 0
    if winners is not None:
        escrow_entry["winners"] = winners

    active[issue_key] = escrow_entry


def apply_payment(
    balances: dict[str, Any],
    escrows: dict[str, Any],
    *,
    issue: int,
    agent: str,
    mechanic: str = "standard",
    amount: int | None = None,
) -> int:
    if mechanic not in {"standard", "progressive", "linear", "every_good", "ranking", "duel"}:
        raise LedgerError(f"Unsupported mechanic: {mechanic}")

    issue_key = str(issue)
    escrow = escrows.get("active", {}).get(issue_key)
    if not isinstance(escrow, dict):
        raise LedgerError(f"No active escrow for issue #{issue}")

    agent_info = _require_agent(balances, agent)
    escrow_amount = int(escrow.get("amount", 0))

    if mechanic in {"progressive", "linear"}:
        slots = int(escrow.get("slots", 0))
        paid_count = int(escrow.get("paid_count", 0))
        if paid_count >= slots:
            raise LedgerError(f"All {mechanic} slots are already paid")
        payout = fib(paid_count + 1) if mechanic == "progressive" else paid_count + 1
    elif mechanic == "standard":
        payout = escrow_amount
    else:
        if amount is None:
            raise LedgerError(f"Amount is required for {mechanic}")
        if amount <= 0:
            raise LedgerError("Amount must be > 0")
        if amount > escrow_amount:
            raise LedgerError(f"Amount {amount} exceeds escrow {escrow_amount}")
        payout = amount

    if payout <= 0:
        raise LedgerError("Payout must be > 0")
    if payout > escrow_amount:
        raise LedgerError(f"Payout {payout} exceeds escrow {escrow_amount}")

    agent_info["balance"] = int(agent_info.get("balance", 0)) + payout
    agent_info["total_earned"] = int(agent_info.get("total_earned", 0)) + payout
    agent_info["tasks_completed"] = int(agent_info.get("tasks_completed", 0)) + 1

    escrow["amount"] = escrow_amount - payout
    if mechanic in {"progressive", "linear"}:
        escrow["paid_count"] = int(escrow.get("paid_count", 0)) + 1
        if int(escrow["paid_count"]) >= int(escrow.get("slots", 0)):
            del escrows["active"][issue_key]
    elif int(escrow["amount"]) <= 0:
        del escrows["active"][issue_key]

    return payout


def return_escrow(
    balances: dict[str, Any],
    escrows: dict[str, Any],
    *,
    issue: int,
) -> int:
    issue_key = str(issue)
    escrow = escrows.get("active", {}).get(issue_key)
    if not isinstance(escrow, dict):
        raise LedgerError(f"No active escrow for issue #{issue}")

    author = str(escrow.get("author", ""))
    amount = int(escrow.get("amount", 0))
    if not author or amount < 0:
        raise LedgerError("Invalid escrow entry")

    author_info = _require_agent(balances, author)
    author_info["balance"] = int(author_info.get("balance", 0)) + amount
    author_info["total_earned"] = int(author_info.get("total_earned", 0)) + amount

    del escrows["active"][issue_key]
    return amount


def _parse_iso_z(ts: str) -> datetime:
    normalized = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_provisional_registration(
    provisionals: dict[str, Any],
    *,
    agent: str,
    github_username: str,
    created_at: str,
    ttl_hours: int = 24,
) -> None:
    if not agent or not github_username:
        raise LedgerError("Agent and github_username are required")
    if ttl_hours <= 0:
        raise LedgerError("ttl_hours must be > 0")
    records = provisionals.setdefault("records", {})
    if agent in records:
        raise LedgerError(f"Provisional record already exists for {agent}")
    records[agent] = {
        "agent": agent,
        "github_username": github_username,
        "status": "provisional",
        "created_at": created_at,
        "expires_at": (
            _parse_iso_z(created_at) + timedelta(hours=ttl_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def reconcile_provisional_registration(
    provisionals: dict[str, Any],
    balances: dict[str, Any],
    *,
    agent: str,
    now: str,
    confirm: bool,
) -> str:
    records = provisionals.setdefault("records", {})
    rec = records.get(agent)
    if not isinstance(rec, dict):
        raise LedgerError(f"No provisional record for {agent}")

    now_dt = _parse_iso_z(now)
    expires_dt = _parse_iso_z(str(rec.get("expires_at", "")))

    if confirm:
        rec["status"] = "confirmed"
        balances.setdefault("agents", {}).setdefault(
            agent,
            {
                "balance": 0,
                "total_earned": 0,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
                "github_username": rec.get("github_username"),
            },
        )
        return "confirmed"

    if now_dt >= expires_dt:
        rec["status"] = "reversed"
        return "reversed"

    return "pending"
