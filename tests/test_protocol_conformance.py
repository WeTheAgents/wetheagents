from __future__ import annotations

import math
import subprocess
import sys

import pytest

from scripts.tide_ops import SPLIT_TABLE, compute_ranking_payouts, fib, linear_budget, progressive_budget


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


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, 1), (2, 3), (3, 6), (4, 10), (5, 15), (6, 21)],
)
def test_protocol_linear_budget_section_6_1_1(n: int, expected: int) -> None:
    assert (
        linear_budget(n) == expected
    ), f"PROTOCOL.md §6.1.1: expected linear_budget({n}) == {expected}"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_protocol_linear_budget_identity_section_6_1_1(n: int) -> None:
    expected = n * (n + 1) // 2
    assert (
        linear_budget(n) == expected
    ), f"PROTOCOL.md §6.1.1: expected linear_budget({n}) == {n}*({n}+1)/2 == {expected}"


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
