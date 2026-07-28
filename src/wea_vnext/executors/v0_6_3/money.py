"""Integer-only payout vectors fixed by ruleset 0.6."""

from __future__ import annotations

from .rules import Ruleset


class MoneyRuleError(ValueError):
    """Raised when a monetary configuration is not exact integer WEA."""


def _positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MoneyRuleError(f"{field} must be a positive integer WEA value")
    return value


def pod_payout_vector(slots: int, payout_wea: int) -> tuple[int, ...]:
    return (_positive_int(payout_wea, field="payout_wea"),) * _positive_int(
        slots, field="slots"
    )


def progressive_payout_vector(slots: int) -> tuple[int, ...]:
    slots = _positive_int(slots, field="slots")
    vector: list[int] = []
    left, right = 1, 1
    for _ in range(slots):
        vector.append(left)
        left, right = right, left + right
    return tuple(vector)


def linear_payout_vector(slots: int) -> tuple[int, ...]:
    return tuple(range(1, _positive_int(slots, field="slots") + 1))


def winner_take_all_vector(prize_pool_wea: int) -> tuple[int, ...]:
    return (_positive_int(prize_pool_wea, field="prize_pool_wea"),)


def best_x_payout_vector(
    prize_pool_wea: int, winners: int, ruleset: Ruleset
) -> tuple[int, ...]:
    prize_pool_wea = _positive_int(prize_pool_wea, field="prize_pool_wea")
    if type(winners) is not int or winners not in {2, 3, 4, 5}:
        raise MoneyRuleError("Best-X winners must be an integer from 2 through 5")
    percentages = ruleset.content["mechanics"]["best-x"]["percentages"][str(winners)]
    tail = tuple(prize_pool_wea * percentage // 100 for percentage in percentages[1:])
    first = prize_pool_wea - sum(tail)
    vector = (first, *tail)
    if any(amount < 1 for amount in vector):
        raise MoneyRuleError("every Best-X place must receive at least 1 WEA")
    return vector


def duel_outcome_vectors(bank_wea: int) -> dict[str, tuple[tuple[int, int], int]]:
    bank_wea = _positive_int(bank_wea, field="bank_wea")
    if bank_wea < 10 or bank_wea % 10:
        raise MoneyRuleError("Duel bank must be at least 10 WEA and divisible by 10")
    ten_percent = bank_wea // 10
    return {
        "inconclusive": ((bank_wea // 2, bank_wea // 2), 0),
        "no-completers": ((0, 0), bank_wea),
        "single-completer": ((bank_wea - ten_percent, 0), ten_percent),
        "winner": ((bank_wea - ten_percent, ten_percent), 0),
    }


def validate_contract_bank(
    bank_wea: int, review_fee_wea: int, payout_vector: tuple[int, ...]
) -> None:
    bank_wea = _positive_int(bank_wea, field="bank_wea")
    if (
        isinstance(review_fee_wea, bool)
        or not isinstance(review_fee_wea, int)
        or review_fee_wea < 0
    ):
        raise MoneyRuleError("review_fee_wea must be a non-negative integer")
    if not payout_vector or any(
        isinstance(amount, bool) or not isinstance(amount, int) or amount < 1
        for amount in payout_vector
    ):
        raise MoneyRuleError("payout_vector must contain positive integer WEA values")
    if bank_wea != review_fee_wea + sum(payout_vector):
        raise MoneyRuleError("bank must equal review fee plus the payout vector")
