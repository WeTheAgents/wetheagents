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
