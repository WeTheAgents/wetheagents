from __future__ import annotations

import math
import subprocess
import sys

import pytest

from scripts.tide import TideProcessor
from scripts.tide_parser import TideEvent
from scripts.tide_ops import SPLIT_TABLE, compute_ranking_payouts, fib, progressive_budget

SUITE_VERSION = "0.1.1"


def test_protocol_vector2_progressive_pod_3_slots() -> None:
    assert (
        progressive_budget(3) == 4
    ), "PROTOCOL.md §12 Vector 2: expected progressive_budget(3) == 4"
    assert fib(1) == 1, "PROTOCOL.md §12 Vector 2: expected fib(1) == 1"
    assert fib(2) == 1, "PROTOCOL.md §12 Vector 2: expected fib(2) == 1"
    assert fib(3) == 2, "PROTOCOL.md §12 Vector 2: expected fib(3) == 2"


def test_protocol_vector3_best3_full_field_budget100() -> None:
    assert compute_ranking_payouts(100, 3, 3) == [
        50,
        30,
        20,
    ], "PROTOCOL.md §12 Vector 3: expected [50, 30, 20]"


def test_protocol_vector4_birdie_x3_k2_budget100() -> None:
    assert compute_ranking_payouts(100, 2, 3) == [
        70,
        30,
    ], "PROTOCOL.md §12 Vector 4: expected [70, 30]"


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, 1), (2, 1), (3, 2), (4, 3), (5, 5), (6, 8)],
)
def test_protocol_fibonacci_sequence_section_6_1(n: int, expected: int) -> None:
    assert fib(n) == expected, f"PROTOCOL.md §6.1: expected fib({n}) == {expected}"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_protocol_progressive_budget_identity_section_6_1(n: int) -> None:
    expected = fib(n + 2) - 1
    assert (
        progressive_budget(n) == expected
    ), f"PROTOCOL.md §6.1: expected progressive_budget({n}) == fib({n}+2)-1 == {expected}"


@pytest.mark.parametrize("x", [1, 2, 3, 4, 5])
def test_protocol_split_table_rows_sum_to_100_section_6_2(x: int) -> None:
    row = SPLIT_TABLE[x]
    assert sum(row) == 100, f"PROTOCOL.md §6.2: SPLIT_TABLE row X={x} must sum to 100"


@pytest.mark.parametrize(
    ("x", "expected"),
    [
        (1, [100]),
        (2, [70, 30]),
        (3, [50, 30, 20]),
        (4, [40, 25, 20, 15]),
        (5, [35, 25, 20, 12, 8]),
    ],
)
def test_protocol_ranking_full_field_exact_percentages_section_6_2(
    x: int, expected: list[int]
) -> None:
    result = compute_ranking_payouts(100, x, x)
    assert result == expected, f"PROTOCOL.md §6.2: K==X=={x} expected {expected}, got {result}"


@pytest.mark.parametrize("x", [1, 2, 3, 4, 5])
def test_protocol_rank1_gets_remainder_no_wei_loss_section_6_2(x: int) -> None:
    budget = 137
    payouts = compute_ranking_payouts(budget, x, x)
    assert sum(payouts) == budget, f"PROTOCOL.md §6.2: payouts must sum to budget for X={x}"

    expected_lower = [
        math.floor(budget * SPLIT_TABLE[x][rank_idx] / 100)
        for rank_idx in range(1, x)
    ]
    assert payouts[1:] == expected_lower, f"PROTOCOL.md §6.2: lower ranks mismatch for X={x}"
    assert payouts[0] == budget - sum(
        expected_lower
    ), f"PROTOCOL.md §6.2: rank 1 must get remainder for X={x}"


@pytest.mark.parametrize(
    ("budget", "winner_expected", "runner_expected"),
    [(100, 90, 10), (33, 29, 4)],
)
def test_protocol_duel_split_section_6_4(
    budget: int, winner_expected: int, runner_expected: int
) -> None:
    winner = math.floor(budget * 0.9)
    runner_up = budget - winner
    assert (
        winner == winner_expected
    ), f"PROTOCOL.md §6.4: winner expected {winner_expected} for budget={budget}, got {winner}"
    assert (
        runner_up == runner_expected
    ), f"PROTOCOL.md §6.4: runner_up expected {runner_expected} for budget={budget}, got {runner_up}"


def test_protocol_invariant_formula_section_4_on_live_ledger() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_invariant.py", "--root", "."],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        pytest.fail(
            "PROTOCOL.md §4: invariant check failed on live ledger.\n"
            f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
        )


def _mk_processor_for_behavior_tests() -> TideProcessor:
    balances = {
        "agents": {
            "author@x": {
                "balance": 1000,
                "github_username": "author-gh",
                "total_earned": 1000,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
            },
            "alice@y": {
                "balance": 10,
                "github_username": "alice-gh",
                "total_earned": 10,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
            },
            "bob@z": {
                "balance": 20,
                "github_username": "bob-gh",
                "total_earned": 20,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
            },
        }
    }
    escrows = {
        "active": {
            "1": {"author": "author@x", "amount": 77, "type": "standard", "created_at": "2026-03-05T00:00:00Z"},
            "2": {
                "author": "author@x",
                "amount": 4,
                "type": "progressive",
                "slots": 3,
                "paid_count": 0,
                "created_at": "2026-03-05T00:00:00Z",
            },
            "3": {"author": "author@x", "amount": 20, "type": "every_good", "created_at": "2026-03-05T00:00:00Z"},
        }
    }
    idem_keys = {"keys": {}}
    task_index = {"version": 1, "tasks": {}}
    return TideProcessor(
        balances=balances,
        escrows=escrows,
        idem_keys=idem_keys,
        task_index=task_index,
    )


def _mk_event(
    *,
    event_type: str,
    issue: int,
    author_github: str,
    agent: str | None = None,
    comment_id: int = 1,
    created_at: str = "2026-03-05T12:00:00Z",
) -> TideEvent:
    return TideEvent(
        type=event_type,
        issue=issue,
        created_at=created_at,
        author_github=author_github,
        source="comment",
        comment_id=comment_id,
        agent=agent,
    )


def test_protocol_v011_standard_is_budget_driven_full_escrow_amount() -> None:
    """Recommendation sync: standard payout follows escrow budget-driven semantics."""
    proc = _mk_processor_for_behavior_tests()
    ev = _mk_event(event_type="accept", issue=1, author_github="author-gh", agent="alice@y")
    assert proc.process(ev), "PROTOCOL.md v0.1.1: standard accept should process"
    assert proc.balances["agents"]["alice@y"]["balance"] == 87, (
        "PROTOCOL.md v0.1.1: standard payout must equal full escrow amount "
        "(budget-driven behavior)"
    )
    assert "1" not in proc.escrows["active"], "PROTOCOL.md v0.1.1: exhausted standard escrow must close"


def test_protocol_v011_progressive_idem_key_must_include_slot_suffix() -> None:
    """Recommendation sync: progressive idem keys must be slot-specific."""
    proc = _mk_processor_for_behavior_tests()
    ev1 = _mk_event(event_type="accept", issue=2, author_github="author-gh", agent="alice@y", comment_id=11)
    ev2 = _mk_event(
        event_type="accept",
        issue=2,
        author_github="author-gh",
        agent="alice@y",
        comment_id=12,
        created_at="2026-03-05T12:01:00Z",
    )
    assert proc.process(ev1), "PROTOCOL.md v0.1.1: progressive slot 1 accept should process"
    assert proc.process(ev2), "PROTOCOL.md v0.1.1: progressive slot 2 accept should process"

    keys = proc.idem_keys.get("keys", {})
    assert "payment|2|alice@y|slot1" in keys, (
        "PROTOCOL.md v0.1.1: progressive idem key for slot 1 must be `...|slot1`"
    )
    assert "payment|2|alice@y|slot2" in keys, (
        "PROTOCOL.md v0.1.1: progressive idem key for slot 2 must be `...|slot2`"
    )


def test_protocol_v011_claimed_is_non_exclusive_for_non_duel_tasks() -> None:
    """Recommendation sync: CLAIMED should support multiple claimants for non-duel."""
    proc = _mk_processor_for_behavior_tests()
    claim1 = _mk_event(event_type="claim", issue=3, author_github="alice-gh", agent="alice@y", comment_id=21)
    claim2 = _mk_event(
        event_type="claim",
        issue=3,
        author_github="bob-gh",
        agent="bob@z",
        comment_id=22,
        created_at="2026-03-05T12:01:00Z",
    )
    assert proc.process(claim1), "PROTOCOL.md v0.1.1: first claim should process"
    assert proc.process(claim2), (
        "PROTOCOL.md v0.1.1: second claimant should also be allowed for non-duel task"
    )
    keys = proc.idem_keys.get("keys", {})
    assert "claim|3|alice@y" in keys and "claim|3|bob@z" in keys, (
        "PROTOCOL.md v0.1.1: claim idem keys must be per-agent, enabling multi-claim semantics"
    )
