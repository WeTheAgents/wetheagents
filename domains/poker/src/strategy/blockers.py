"""Blocker analysis for poker decisions.

A "blocker" is a card in our hand that reduces the number of combos
in the opponent's range. Holding the Ah on a three-heart board means
the opponent is less likely to have the nut flush.

Blocker effects improve bluff EV (villain folds more) and affect
value decisions (villain's calling range shifts).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Rank values for comparison
_RANK_VALUES = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10,
                "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}


def blocker_adjustment(hole_cards: list[str], community_cards: list[str]) -> float:
    """Calculate blocker-based adjustment to fold equity.

    Returns [-0.10, +0.15]:
    - Positive: our cards block villain's strong holdings (better for bluffing)
    - Negative: our cards block villain's weak holdings (worse for bluffing)
    """
    if len(community_cards) < 3 or len(hole_cards) < 2:
        return 0.0

    adj = 0.0

    # Check for flush blocker
    adj += _flush_blocker(hole_cards, community_cards)

    # Check for top pair / top card blocker
    adj += _top_card_blocker(hole_cards, community_cards)

    return max(-0.10, min(0.15, adj))


def _flush_blocker(hole_cards: list[str], community_cards: list[str]) -> float:
    """Check if we hold a nut flush blocker.

    If 3+ community cards share a suit, holding the ace of that suit
    blocks the opponent's nut flush. Great for bluff raises.
    """
    # Count suits on board
    suit_counts: dict[str, int] = {}
    for card in community_cards:
        suit = card[1].lower()
        suit_counts[suit] = suit_counts.get(suit, 0) + 1

    # Find flush-possible suit (3+ of same suit)
    flush_suit = None
    for suit, count in suit_counts.items():
        if count >= 3:
            flush_suit = suit
            break

    if flush_suit is None:
        return 0.0

    # Do we hold the ace of that suit?
    for card in hole_cards:
        rank, suit = card[0].upper(), card[1].lower()
        if suit == flush_suit and rank == "A":
            return 0.10  # nut flush blocker

    # Do we hold the king of that suit? (second nut blocker)
    for card in hole_cards:
        rank, suit = card[0].upper(), card[1].lower()
        if suit == flush_suit and rank == "K":
            return 0.05

    return 0.0


def _top_card_blocker(hole_cards: list[str], community_cards: list[str]) -> float:
    """Check if we block top pair combos.

    Holding a card matching the highest board card means villain has
    fewer top pair combos. This slightly improves bluff equity.
    """
    # Find highest board card rank
    board_ranks = []
    for card in community_cards:
        rank = card[0].upper()
        if rank in _RANK_VALUES:
            board_ranks.append(_RANK_VALUES[rank])

    if not board_ranks:
        return 0.0

    top_rank = max(board_ranks)

    # Do any of our hole cards match the top board card?
    for card in hole_cards:
        rank = card[0].upper()
        if _RANK_VALUES.get(rank, 0) == top_rank:
            return 0.05

    return 0.0
