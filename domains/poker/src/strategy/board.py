"""Board texture analysis for postflop decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.table.state import Position


def board_wetness(community_cards: list[str]) -> float:
    """Analyze board texture: 0.0 = bone dry, 1.0 = soaking wet.

    Factors:
    - Flush draws: 2+ cards of same suit = wet
    - Straight draws: connected/close ranks = wet
    - Paired board: slightly dry (fewer combos connect)
    - High card density: more broadway = more potential hands

    Dry board (K-7-2 rainbow) = bluffs work great, WA/WB applies.
    Wet board (J-T-9 two-tone) = bluffs fail, opponents have draws.
    """
    if len(community_cards) < 3:
        return 0.5  # can't evaluate preflop

    rank_values = {
        "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
        "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
    }

    ranks = []
    suits: dict[str, int] = {}
    for card in community_cards:
        r, s = card[0].upper(), card[1].lower()
        ranks.append(rank_values.get(r, 7))
        suits[s] = suits.get(s, 0) + 1

    score = 0.0

    # --- Flush draw potential ---
    max_suited = max(suits.values())
    if max_suited >= 4:
        score += 0.40  # 4-flush on board = extremely wet
    elif max_suited == 3:
        score += 0.35  # monotone flop = very wet
    elif max_suited == 2:
        score += 0.15  # two-tone = moderately wet

    # --- Straight draw potential ---
    sorted_ranks = sorted(set(ranks))
    # Count how many ranks are within 4 of each other (straight window)
    gaps = []
    for i in range(len(sorted_ranks) - 1):
        gaps.append(sorted_ranks[i + 1] - sorted_ranks[i])

    if gaps:
        min_gap = min(gaps)
        if min_gap == 1:
            score += 0.25  # connected (e.g., 9-T or J-Q)
        elif min_gap == 2:
            score += 0.15  # one-gapper
        elif min_gap == 3:
            score += 0.05  # two-gapper

    # Bonus: 3+ ranks within a 5-card window
    if len(sorted_ranks) >= 3:
        spread = sorted_ranks[-1] - sorted_ranks[0]
        if spread <= 4:
            score += 0.15  # very connected board

    # --- Paired board = slightly drier ---
    if len(set(ranks)) < len(ranks):
        score -= 0.10

    # --- High card density (broadway cards give more combos) ---
    broadway = sum(1 for r in ranks if r >= 10)
    if broadway >= 3:
        score += 0.10
    elif broadway >= 2:
        score += 0.05

    return max(0.0, min(1.0, score))


def range_advantage(
    community_cards: list[str],
    position: "Position | None",
    in_position: bool,
) -> float:
    """Estimate how well the board favours the preflop raiser's range.

    Returns -1.0 (strongly favours caller) to +1.0 (strongly favours raiser).

    High-card boards favour the raiser (more broadways in opening range).
    Low, connected boards favour the caller (suited connectors, small pairs).
    """
    if len(community_cards) < 3:
        return 0.0

    rank_values = {
        "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
        "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
    }

    ranks = [rank_values.get(c[0].upper(), 7) for c in community_cards[:3]]
    suits: dict[str, int] = {}
    for c in community_cards[:3]:
        s = c[1].lower()
        suits[s] = suits.get(s, 0) + 1

    advantage = 0.0

    # High cards favour the raiser (AK, AQ, KQ in opening range)
    high_cards = sum(1 for r in ranks if r >= 12)  # Q, K, A
    advantage += high_cards * 0.15

    # Low connected cards favour the caller (suited connectors in defending range)
    sorted_ranks = sorted(ranks)
    spread = sorted_ranks[-1] - sorted_ranks[0]
    low_cards = sum(1 for r in ranks if r <= 8)

    if spread <= 4 and low_cards >= 2:
        advantage -= 0.25  # connected low board = bad for raiser

    # Two-tone or monotone slightly favours caller (more suited combos)
    max_suited = max(suits.values())
    if max_suited >= 3:
        advantage -= 0.10  # monotone
    elif max_suited == 2:
        advantage -= 0.05  # two-tone

    # Early position raiser has tighter range = stronger advantage on high boards
    if position is not None:
        from src.table.state import Position
        if position in (Position.UTG, Position.UTG1, Position.UTG2, Position.MP):
            advantage += 0.10  # tight opener range

    # In position bonus (can realise equity better)
    if in_position:
        advantage += 0.05

    return max(-1.0, min(1.0, advantage))
