"""ICM (Independent Chip Model) adjustments for tournament play.

ICM pressure changes optimal strategy: chips you lose are worth more
than chips you win (diminishing marginal value). Near the bubble,
medium stacks should tighten up while big stacks exploit this fear.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def icm_adjustment(
    players_remaining: int,
    players_paid: int,
    eff_bb: float,
    avg_stack_bb: float,
) -> float:
    """Calculate ICM aggression multiplier.

    Returns a value in [0.5, 1.5]:
    - < 1.0: tighten up (survive, avoid marginal spots)
    - 1.0: play normal (no ICM pressure)
    - > 1.0: widen ranges (exploit tighter opponents)
    """
    if players_paid <= 0 or players_remaining <= 0:
        return 1.0  # cash game or unknown: no ICM

    spots_from_money = players_remaining - players_paid

    # Stack classification relative to average
    if avg_stack_bb > 0:
        stack_ratio = eff_bb / avg_stack_bb
    else:
        stack_ratio = 1.0

    # Already in the money: ladder ICM (each elimination = pay jump)
    if spots_from_money <= 0:
        # ITM: can afford to be slightly more aggressive
        # Short stacks need to double up; big stacks can bully
        if stack_ratio > 1.5:
            return 1.3
        elif stack_ratio < 0.5:
            return 0.8  # short stack ITM: pick spots carefully
        return 1.2

    # On the bubble (within 2 spots of money)
    if spots_from_money <= 2:
        if stack_ratio > 1.5:
            # Big stack on bubble: predator mode
            # Everyone else is tightening → steal relentlessly
            return 1.3
        elif stack_ratio < 0.7:
            # Short stack on bubble: desperate but not dead
            # Need to pick premium spots or blind out
            return 0.6
        else:
            # Medium stack on bubble: survival mode
            # Most exploitable spot — tighten significantly
            return 0.8

    # Near bubble (3-4 spots away)
    if spots_from_money <= 4:
        if stack_ratio > 1.5:
            return 1.2  # start applying pressure early
        elif stack_ratio < 0.7:
            return 0.7  # short stack approaching bubble
        return 0.9  # slight tightening

    # Far from bubble: normal play
    return 1.0
