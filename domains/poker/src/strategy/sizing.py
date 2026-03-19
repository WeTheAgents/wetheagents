"""Bet sizing logic: determines how much to bet/raise in different situations."""

from __future__ import annotations

import logging

from src.strategy.board import board_wetness
from src.table.state import GameState, Street

logger = logging.getLogger(__name__)


def get_bet_size(
    state: GameState,
    equity: float,
    is_value: bool = False,
    is_cbet: bool = False,
    is_bluff: bool = False,
) -> float:
    """Calculate bet size as a fraction of pot.

    Sizing strategy:
    - C-bet: 50-66% pot (smaller = more frequent, same EV)
    - Value bet: 66-80% pot (extract max from calling ranges)
    - Bluff: 50-60% pot (risk less, give bad odds)
    - All-in: when stack < 2x pot (committed)
    """
    pot = state.pot
    stack = state.my_stack

    if pot <= 0 or stack <= 0:
        return 0.0

    # If stack is small relative to pot, just jam
    if stack <= pot * 1.5:
        return stack

    if is_cbet:
        fraction = _cbet_fraction(state)
    elif is_value:
        fraction = _value_fraction(state, equity)
    elif is_bluff:
        fraction = _bluff_fraction(state)
    else:
        fraction = 0.60  # default

    # Adjust for villain tendencies
    if is_value or is_bluff:
        fraction = _villain_adjusted_fraction(fraction, state, is_value)
        if fraction <= 0:
            return 0.0  # don't bet (e.g. don't bluff calling stations)

    bet = pot * fraction

    # Clamp to valid range
    bet = max(bet, state.min_raise) if state.min_raise > 0 else bet
    bet = min(bet, state.max_raise) if state.max_raise > 0 else min(bet, stack)
    bet = min(bet, stack)

    return round(bet)


def _cbet_fraction(state: GameState) -> float:
    """C-bet sizing by street and board texture.

    Modern poker uses small bets on dry boards (high frequency, low risk)
    and larger bets on wet boards (protection, lower frequency).
    """
    if state.street == Street.FLOP:
        wetness = board_wetness(state.community_cards)
        if wetness < 0.20:
            return 0.33  # small-ball on dry boards
        elif wetness < 0.40:
            return 0.50  # medium texture
        else:
            return 0.66  # wet board: larger for protection
    elif state.street == Street.TURN:
        return 0.65
    else:
        return 0.70


def _value_fraction(state: GameState, equity: float) -> float:
    """Value bet sizing based on hand strength and street."""
    base = 0.66

    # Overbets: nuts on river -> 1.3x pot to extract maximum
    if equity >= 0.90 and state.street == Street.RIVER:
        return 1.30

    # Stronger hands -> larger bets
    if equity >= 0.85:
        base = 0.80
    elif equity >= 0.75:
        base = 0.75

    # Later streets -> slightly larger
    if state.street == Street.TURN:
        base += 0.05
    elif state.street == Street.RIVER:
        base += 0.10

    return min(base, 1.0)


def _bluff_fraction(state: GameState) -> float:
    """Bluff sizing: use smaller bets to risk less."""
    if state.street == Street.FLOP:
        return 0.50
    elif state.street == Street.TURN:
        return 0.55
    else:
        return 0.60  # river bluffs need to be believable


def _villain_adjusted_fraction(base: float, state: GameState, is_value: bool) -> float:
    """Adjust bet sizing based on villain tendencies.

    Calling station (AF < 1.0): bet bigger for value, don't bluff.
    LAG (AF > 2.5): bet smaller for value (induce raises), smaller bluffs.
    Nit (high fold %): smaller value bets to get calls.
    """
    af = state.villain_aggression

    if is_value:
        if af < 1.0:
            # Calling station: they call too much, extract max value
            return min(base + 0.15, 1.0)
        elif af > 2.5:
            # LAG: bet smaller to induce raises/bluffs
            return base - 0.10
        elif state.villain_fold_pct > 0.60:
            # Nit: bet smaller so they don't fold everything
            return base - 0.10
    else:
        # Bluff sizing
        if af < 1.0:
            # Calling station: don't bluff
            return 0.0
        elif af > 2.5:
            # LAG: smaller bluffs (they re-raise light)
            return base - 0.10

    return base
