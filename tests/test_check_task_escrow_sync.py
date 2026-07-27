from __future__ import annotations

from scripts.check_task_escrow_sync import _compute_remaining_by_issue


def test_remaining_escrow_subtracts_payments_and_returns() -> None:
    remaining, paid, returned = _compute_remaining_by_issue(
        {
            "keys": {
                "escrow": {"action": "escrow", "issue": 42, "amount": 20},
                "payment": {"action": "payment", "issue": 42, "amount": 7},
                "return": {
                    "action": "escrow_return",
                    "issue": 42,
                    "amount": 5,
                },
            }
        }
    )

    assert remaining == {"42": 8}
    assert paid == {"42": 7}
    assert returned == {"42": 5}


def test_remaining_escrow_keeps_issues_independent() -> None:
    remaining, paid, returned = _compute_remaining_by_issue(
        {
            "keys": {
                "first": {"action": "escrow", "issue": 1, "amount": 10},
                "second": {"action": "escrow", "issue": 2, "amount": 4},
                "paid": {"action": "payment", "issue": 1, "amount": 3},
            }
        }
    )

    assert remaining == {"1": 7, "2": 4}
    assert paid == {"1": 3}
    assert returned == {}


def test_remaining_escrow_accepts_integer_strings() -> None:
    remaining, _, _ = _compute_remaining_by_issue(
        {
            "keys": {
                "escrow": {"action": "escrow", "issue": "9", "amount": "12"},
                "payment": {"action": "payment", "issue": "9", "amount": "2"},
            }
        }
    )

    assert remaining == {"9": 10}


def test_remaining_escrow_ignores_unusable_records() -> None:
    remaining, paid, returned = _compute_remaining_by_issue(
        {
            "keys": {
                "not-a-record": "ignored",
                "missing-issue": {"action": "escrow", "amount": 5},
                "bad-amount": {
                    "action": "payment",
                    "issue": 3,
                    "amount": "not-a-number",
                },
                "unknown-action": {"action": "claim", "issue": 4, "amount": 1},
            }
        }
    )

    assert remaining == {}
    assert paid == {}
    assert returned == {}
