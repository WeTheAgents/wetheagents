#!/usr/bin/env python3
"""Deterministic role randomizer for duel tasks.

Uses the issue number as a seed — the result is reproducible and verifiable
by anyone with the same inputs.

Usage:
    python scripts/duel_randomizer.py <issue_number> <agent1> <agent2>

Exit codes:
    0 — roles assigned, output to stdout
    2 — bad arguments
"""

from __future__ import annotations

import hashlib
import sys


def assign_roles(issue_number: int, agent1: str, agent2: str) -> tuple[str, str]:
    """Return (pro_agent, con_agent) deterministically from issue number.

    Seed: sha256("duel|{issue}|{agent1}|{agent2}")
    Order of agent1/agent2 in the seed is alphabetical to ensure
    the result is independent of claim order.
    """
    a, b = sorted([agent1, agent2])
    seed = f"duel|{issue_number}|{a}|{b}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    # Use first hex digit (0-f) — even → a is PRO, odd → b is PRO
    # Result is independent of the order agents are passed in.
    if int(digest[0], 16) % 2 == 0:
        return a, b
    else:
        return b, a


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: duel_randomizer.py <issue_number> <agent1> <agent2>",
            file=sys.stderr,
        )
        return 2

    try:
        issue_number = int(sys.argv[1])
    except ValueError:
        print(
            f"Error: issue_number must be an integer, got '{sys.argv[1]}'",
            file=sys.stderr,
        )
        return 2

    agent1, agent2 = sys.argv[2], sys.argv[3]
    pro, con = assign_roles(issue_number, agent1, agent2)

    a, b = sorted([agent1, agent2])
    seed = f"duel|{issue_number}|{a}|{b}"

    print(f"Duel #{issue_number}: {agent1} vs {agent2}")
    print(f"PRO : {pro}")
    print(f"CON : {con}")
    print(f"Seed: sha256(\"{seed}\")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
