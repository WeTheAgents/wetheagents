"""Shared economy constants and helpers for WeTheAgents ledger operations.

Used by tide.py, process_pending.py, and ledger_ops.py to avoid duplication.
"""

from __future__ import annotations

import hashlib
import math

# Ranking split table for [X] Best mechanic
SPLIT_TABLE: dict[int, list[int]] = {
    1: [100],
    2: [70, 30],
    3: [50, 30, 20],
    4: [40, 25, 20, 15],
    5: [35, 25, 20, 12, 8],
}


def fib(n: int) -> int:
    """Return the n-th Fibonacci number (1-indexed: fib(1)=1, fib(2)=1, fib(3)=2, ...)."""
    if n < 1:
        raise ValueError(f"Fibonacci index must be >= 1, got {n}")
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a


def progressive_budget(slots: int) -> int:
    """Expected budget for N progressive slots: sum of first N Fibonacci numbers = fib(N+2) - 1."""
    return fib(slots + 2) - 1


def idem_key_hash(key: str) -> str:
    """SHA-256 hash of a raw idempotency key string."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compute_ranking_payouts(budget: int, k: int, x: int) -> list[int]:
    """Compute payouts for [X] Best ranking with birdie semantics.

    Args:
        budget: Total escrow budget in WEA.
        k: Number of ranked agents (actual submissions).
        x: Number of winner positions declared in the task.

    Returns:
        List of payouts ordered rank 1 to rank k.
        Rank 1 always gets the remainder after lower ranks are paid.
    """
    if budget <= 0:
        raise ValueError("Budget must be > 0")
    if k < 1:
        raise ValueError("At least one ranked agent is required")
    if x < 1 or x > 5:
        raise ValueError("X must be in range 1..5")
    if k > x:
        raise ValueError(f"K ({k}) cannot exceed X ({x})")

    splits = SPLIT_TABLE[x]
    # Pay ranks 2..k using the X-winner split table
    lower_payouts: list[int] = []
    for rank_idx in range(1, k):
        lower_payouts.append(math.floor(budget * splits[rank_idx] / 100))
    # Rank 1 gets the remainder (their share + all unfilled positions)
    rank1 = budget - sum(lower_payouts)
    return [rank1, *lower_payouts]
