from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ledger_ops import (
    LedgerError,
    apply_payment,
    compute_ranking_payouts,
    create_escrow,
    create_provisional_registration,
    fib,
    reconcile_provisional_registration,
    return_escrow,
    validate_claim,
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _supply_total(balances: dict, escrows: dict) -> int:
    balances_sum = sum(v.get("balance", 0) for v in balances.get("agents", {}).values())
    escrow_sum = sum(v.get("amount", 0) for v in escrows.get("active", {}).values())
    return balances_sum + escrow_sum


def test_escrow_lifecycle_create_pay_return_remainder(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    escrows = _read_json(temp_repo / "ledger" / "escrows.json")
    before_total = _supply_total(balances, escrows)

    create_escrow(
        balances,
        escrows,
        issue=101,
        author="author@local",
        reward=30,
        created_at="2026-03-04T10:00:00Z",
        fee=1,
        escrow_type="standard",
    )

    payout = apply_payment(
        balances,
        escrows,
        issue=101,
        agent="alice@test",
        mechanic="every_good",
        amount=10,
    )
    assert payout == 10
    refunded = return_escrow(balances, escrows, issue=101)
    assert refunded == 20

    assert balances["agents"]["alice@test"]["balance"] == 10
    assert balances["agents"]["author@local"]["balance"] == 489
    assert balances["agents"]["agent0@system"]["balance"] == 10001
    assert "101" not in escrows["active"]
    assert _supply_total(balances, escrows) == before_total


def test_progressive_pod_fibonacci_slots(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    escrows = _read_json(temp_repo / "ledger" / "escrows.json")

    create_escrow(
        balances,
        escrows,
        issue=102,
        author="author@local",
        reward=4,
        created_at="2026-03-04T10:00:00Z",
        fee=1,
        escrow_type="progressive",
        slots=3,
    )

    p1 = apply_payment(balances, escrows, issue=102, agent="alice@test", mechanic="progressive")
    p2 = apply_payment(balances, escrows, issue=102, agent="bob@test", mechanic="progressive")
    p3 = apply_payment(balances, escrows, issue=102, agent="carol@test", mechanic="progressive")

    assert [p1, p2, p3] == [1, 1, 2]
    assert "102" not in escrows["active"]
    assert balances["agents"]["alice@test"]["balance"] == 1
    assert balances["agents"]["bob@test"]["balance"] == 1
    assert balances["agents"]["carol@test"]["balance"] == 2


def test_linear_pod_slots(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    escrows = _read_json(temp_repo / "ledger" / "escrows.json")

    # 4 slots: budget = 4*5/2 = 10
    create_escrow(
        balances,
        escrows,
        issue=103,
        author="author@local",
        reward=10,
        created_at="2026-03-04T10:00:00Z",
        fee=1,
        escrow_type="linear",
        slots=4,
    )

    p1 = apply_payment(balances, escrows, issue=103, agent="alice@test", mechanic="linear")
    p2 = apply_payment(balances, escrows, issue=103, agent="bob@test", mechanic="linear")
    p3 = apply_payment(balances, escrows, issue=103, agent="carol@test", mechanic="linear")
    p4 = apply_payment(balances, escrows, issue=103, agent="alice@test", mechanic="linear")

    assert [p1, p2, p3, p4] == [1, 2, 3, 4]
    assert "103" not in escrows["active"]
    assert balances["agents"]["alice@test"]["balance"] == 1 + 4  # slots 1 and 4
    assert balances["agents"]["bob@test"]["balance"] == 2
    assert balances["agents"]["carol@test"]["balance"] == 3


def test_ranking_payout_splits_and_winner_take_all() -> None:
    assert compute_ranking_payouts(100, 2, 2) == [70, 30]
    assert compute_ranking_payouts(100, 3, 3) == [50, 30, 20]
    assert compute_ranking_payouts(100, 1, 1) == [100]
    assert compute_ranking_payouts(100, 2, 5) == [75, 25]


def test_provisional_registration_confirm_and_reverse(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    provisionals = {"records": {}}

    create_provisional_registration(
        provisionals,
        agent="new@agent",
        github_username="newagent-gh",
        created_at="2026-03-04T10:00:00Z",
        ttl_hours=24,
    )

    state = reconcile_provisional_registration(
        provisionals,
        balances,
        agent="new@agent",
        now="2026-03-04T12:00:00Z",
        confirm=True,
    )
    assert state == "confirmed"
    assert "new@agent" in balances["agents"]

    create_provisional_registration(
        provisionals,
        agent="late@agent",
        github_username="lateagent-gh",
        created_at="2026-03-04T10:00:00Z",
        ttl_hours=24,
    )
    state = reconcile_provisional_registration(
        provisionals,
        balances,
        agent="late@agent",
        now="2026-03-05T10:00:01Z",
        confirm=False,
    )
    assert state == "reversed"


def test_edge_cases_self_claim_negative_amount_and_insufficient_escrow(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    escrows = _read_json(temp_repo / "ledger" / "escrows.json")

    with pytest.raises(LedgerError):
        validate_claim("author@local", "author@local")

    create_escrow(
        balances,
        escrows,
        issue=103,
        author="author@local",
        reward=10,
        created_at="2026-03-04T10:00:00Z",
        fee=1,
        escrow_type="standard",
    )

    with pytest.raises(LedgerError):
        apply_payment(
            balances,
            escrows,
            issue=103,
            agent="alice@test",
            mechanic="every_good",
            amount=-1,
        )

    with pytest.raises(LedgerError):
        apply_payment(
            balances,
            escrows,
            issue=103,
            agent="alice@test",
            mechanic="every_good",
            amount=11,
        )

    balances["agents"]["author@local"]["balance"] = 0
    with pytest.raises(LedgerError):
        create_escrow(
            balances,
            escrows,
            issue=104,
            author="author@local",
            reward=1,
            created_at="2026-03-04T10:00:00Z",
            fee=1,
            escrow_type="standard",
        )


# ---------------------------------------------------------------------------
# Fibonacci edge cases (#64)
# ---------------------------------------------------------------------------


class TestFibonacci:
    def test_sequence(self):
        assert [fib(n) for n in range(1, 7)] == [1, 1, 2, 3, 5, 8]

    def test_zero_raises(self):
        with pytest.raises(LedgerError):
            fib(0)

    def test_negative_raises(self):
        with pytest.raises(LedgerError):
            fib(-1)

    def test_large(self):
        assert fib(10) == 55


# ---------------------------------------------------------------------------
# Ranking payout edge cases — PROTOCOL test vectors (#64)
# ---------------------------------------------------------------------------


class TestRankingPayoutsEdgeCases:
    def test_protocol_3best_100(self):
        assert compute_ranking_payouts(100, 3, 3) == [50, 30, 20]

    def test_protocol_birdie_x3_k2(self):
        """Birdie rule: K=2 actual ranked, X=3 declared → use X=3 table, truncate to 2."""
        assert compute_ranking_payouts(100, 2, 3) == [70, 30]

    def test_budget_one(self):
        assert compute_ranking_payouts(1, 1, 1) == [1]

    def test_rounding_remainder_to_rank1(self):
        """Rank 1 gets floor-rounding remainder."""
        result = compute_ranking_payouts(99, 3, 3)
        # splits [50, 30, 20]: r2=floor(99*30/100)=29, r3=floor(99*20/100)=19
        # r1 = 99 - 29 - 19 = 51
        assert result == [51, 29, 19]
        assert sum(result) == 99

    def test_budget_zero_raises(self):
        with pytest.raises(LedgerError):
            compute_ranking_payouts(0, 1, 1)

    def test_k_exceeds_x_raises(self):
        with pytest.raises(LedgerError):
            compute_ranking_payouts(100, 3, 2)

    def test_x_out_of_range_raises(self):
        with pytest.raises(LedgerError):
            compute_ranking_payouts(100, 1, 6)


# ---------------------------------------------------------------------------
# Escrow fee=0 edge case (#64)
# ---------------------------------------------------------------------------


def test_escrow_fee_zero(temp_repo: Path) -> None:
    balances = _read_json(temp_repo / "ledger" / "balances.json")
    escrows = _read_json(temp_repo / "ledger" / "escrows.json")

    author_before = balances["agents"]["author@local"]["balance"]
    a0_before = balances["agents"]["agent0@system"]["balance"]

    create_escrow(
        balances,
        escrows,
        issue=200,
        author="author@local",
        reward=10,
        created_at="2026-03-04T10:00:00Z",
        fee=0,
        escrow_type="standard",
    )

    assert balances["agents"]["author@local"]["balance"] == author_before - 10
    assert balances["agents"]["agent0@system"]["balance"] == a0_before  # no fee
