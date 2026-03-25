"""Reshove (3-bet jam) ranges for 12-18bb stacks facing an open-raise.

With 12-18bb, calling a raise OOP bleeds chips. The correct play is
jam-or-fold: either 3-bet all-in for maximum fold equity, or fold.
Ranges are tighter vs EP openers and wider vs LP openers.
"""

from __future__ import annotations

import logging

from src.table.state import Action, ActionType, GameState, Position, canonicalize_hand

logger = logging.getLogger(__name__)

# our_position -> opener_position -> stack_tier -> hands
RESHOVE_RANGES: dict[str, dict[str, dict[str, list[str]]]] = {
    "BB": {
        "BTN": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66",
                "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A5s", "A4s",
                "AKo", "AQo", "AJo", "ATo",
                "KQs", "KJs", "KTs",
                "QJs", "QTs",
                "JTs",
            ],
            "15-18bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99", "88",
                "AKs", "AQs", "AJs", "ATs", "A5s",
                "AKo", "AQo", "AJo",
                "KQs", "KJs",
                "QJs",
            ],
        },
        "CO": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99", "88",
                "AKs", "AQs", "AJs", "ATs", "A5s",
                "AKo", "AQo", "AJo",
                "KQs", "KJs",
            ],
            "15-18bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99",
                "AKs", "AQs", "AJs",
                "AKo", "AQo",
                "KQs",
            ],
        },
        "MP": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT",
                "AKs", "AQs",
                "AKo",
            ],
            "15-18bb": [
                "AA", "KK", "QQ", "JJ",
                "AKs", "AKo",
            ],
        },
    },
    "SB": {
        "BTN": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
                "AKs", "AQs", "AJs", "ATs", "A9s", "A5s", "A4s",
                "AKo", "AQo", "AJo", "ATo",
                "KQs", "KJs", "KTs",
                "QJs",
            ],
            "15-18bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99",
                "AKs", "AQs", "AJs", "ATs",
                "AKo", "AQo", "AJo",
                "KQs", "KJs",
            ],
        },
        "CO": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT", "99",
                "AKs", "AQs", "AJs",
                "AKo", "AQo",
                "KQs",
            ],
            "15-18bb": [
                "AA", "KK", "QQ", "JJ", "TT",
                "AKs", "AQs",
                "AKo", "AQo",
            ],
        },
    },
    "CO": {
        "MP": {
            "12-15bb": [
                "AA", "KK", "QQ", "JJ", "TT",
                "AKs", "AQs",
                "AKo",
            ],
        },
    },
}

# Simplified position classification for opener
_POSITION_ALIASES: dict[str, str] = {
    "UTG": "MP", "UTG+1": "MP", "UTG+2": "MP",
    "MP": "MP", "HJ": "CO",
    "CO": "CO", "BTN": "BTN",
    "SB": "BTN", "BB": "BTN",  # rarely opens, treat as wide
}


def get_reshove_action(state: GameState) -> Action | None:
    """Check if we should 3-bet jam with 12-18bb facing a raise.

    Returns Action(ALL_IN) if hand is in reshove range,
    Action(FOLD) if not (at this stack depth, flat-calling is a leak),
    or None if reshove doesn't apply (wrong stack depth, no raise).
    """
    eff_bb = state.effective_stack_bb
    if not (12 <= eff_bb <= 18):
        return None

    # Must be facing a raise (not just blinds)
    if state.to_call <= state.big_blind * 1.5:
        return None

    hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
    my_pos = state.my_position.value if state.my_position else "BB"

    # Determine opener position heuristic:
    # If we're in BB and facing a raise, opener could be anywhere.
    # Use a conservative estimate based on raise size and remaining players.
    # For now, assume opener is from the latest position that could have raised.
    opener_pos = _estimate_opener_position(state)

    tier = "12-15bb" if eff_bb < 15 else "15-18bb"

    pos_ranges = RESHOVE_RANGES.get(my_pos, {})
    opener_ranges = pos_ranges.get(opener_pos, {})
    hands = opener_ranges.get(tier, [])

    if not hands:
        # No specific range defined — don't reshove, let normal logic handle
        return None

    if hand in hands:
        logger.info(
            f"RESHOVE: {hand} from {my_pos} vs {opener_pos} at {eff_bb:.0f}BB -> ALL-IN"
        )
        return Action(ActionType.ALL_IN, state.my_stack)

    # At 12-18bb facing a raise with a hand not in reshove range: fold.
    # Flat-calling bleeds chips OOP at this stack depth.
    logger.info(f"RESHOVE: {hand} from {my_pos} vs {opener_pos} at {eff_bb:.0f}BB -> FOLD")
    return Action(ActionType.FOLD)


def _estimate_opener_position(state: GameState) -> str:
    """Estimate the opener's position based on available info.

    Heuristic: more folds = later position opener (UTG/MP folded first,
    so if 4+ folded the opener is likely BTN/CO).
    """
    folded = state.num_players - state.players_in_hand
    if folded >= 3:
        return "BTN"  # many folds -> late position open
    elif folded >= 1:
        return "CO"  # some folds -> middle/late
    else:
        return "MP"  # no folds -> early position open
