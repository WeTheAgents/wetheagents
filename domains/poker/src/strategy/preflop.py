"""Preflop strategy engine: lookup tables for open-raising, 3-betting, and push/fold."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.table.state import Action, ActionType, GameState, Position, canonicalize_hand

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Load ranges at module level
_ranges: dict | None = None
_push_fold: dict | None = None


def _load_ranges() -> dict:
    global _ranges
    if _ranges is None:
        with open(DATA_DIR / "preflop_ranges.json") as f:
            _ranges = json.load(f)
    return _ranges


def _load_push_fold() -> dict:
    global _push_fold
    if _push_fold is None:
        with open(DATA_DIR / "push_fold.json") as f:
            _push_fold = json.load(f)
    return _push_fold


def _position_key(pos: Position | None) -> str:
    """Map Position enum to range table key."""
    if pos is None:
        return "MP"
    mapping = {
        Position.UTG: "UTG",
        Position.UTG1: "UTG+1",
        Position.UTG2: "UTG+2",
        Position.MP: "MP",
        Position.HJ: "HJ",
        Position.CO: "CO",
        Position.BTN: "BTN",
        Position.SB: "SB",
        Position.BB: "BB",
    }
    return mapping.get(pos, "MP")


def _stack_tier(eff_bb: float) -> str:
    """Categorize stack depth."""
    if eff_bb < 20:
        return "short"
    elif eff_bb <= 50:
        return "medium"
    else:
        return "deep"


def _find_position_in_ranges(pos_key: str, ranges: dict) -> dict | None:
    """Find the position in range dict, falling back to nearby positions."""
    if pos_key in ranges:
        return ranges[pos_key]

    # Fallback chain for positions not in all tiers
    fallbacks = {
        "UTG+1": ["UTG"],
        "UTG+2": ["MP", "UTG+1", "UTG"],
        "HJ": ["CO", "MP"],
    }
    for fb in fallbacks.get(pos_key, []):
        if fb in ranges:
            return ranges[fb]
    return None


def get_push_fold_action(state: GameState) -> Action | None:
    """Check push/fold charts for short-stack play (<20BB).

    Returns Action if push/fold applies, None otherwise.
    """
    eff_bb = state.effective_stack_bb
    if eff_bb >= 20:
        return None

    push_fold = _load_push_fold()
    hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
    pos_key = _position_key(state.my_position)

    # Only apply push/fold when it's folded to us (no raise ahead)
    # If someone already raised, use 3bet-jam or call logic instead
    if state.to_call > state.big_blind * 1.5:
        # Facing a raise — check call_push ranges
        return _get_call_push_action(state, hand)

    # Determine which BB tier to use
    if eff_bb <= 8:
        tier = "8bb"
    elif eff_bb <= 10:
        tier = "10bb"
    else:
        tier = "15bb"

    push_ranges = push_fold.get("push", {}).get(tier, {})
    pos_hands = push_ranges.get(pos_key)

    if pos_hands is None:
        return None

    # "any" means push with any two cards
    if pos_hands == "any" or hand in pos_hands:
        logger.info(f"PUSH/FOLD: {hand} from {pos_key} at {eff_bb:.0f}BB -> ALL-IN")
        return Action(ActionType.ALL_IN, state.my_stack)

    logger.info(f"PUSH/FOLD: {hand} from {pos_key} at {eff_bb:.0f}BB -> FOLD")
    return Action(ActionType.FOLD)


def _get_call_push_action(state: GameState, hand: str) -> Action | None:
    """Decide whether to call an all-in shove."""
    push_fold = _load_push_fold()
    call_ranges = push_fold.get("call_push", {})

    eff_bb = state.effective_stack_bb
    if eff_bb <= 8:
        key = "vs_8bb_push"
    elif eff_bb <= 10:
        key = "vs_10bb_push"
    else:
        key = "vs_15bb_push"

    hands = call_ranges.get(key, [])
    if hand in hands:
        logger.info(f"CALL PUSH: {hand} at {eff_bb:.0f}BB -> CALL ALL-IN")
        return Action(ActionType.ALL_IN, state.my_stack)

    logger.info(f"CALL PUSH: {hand} at {eff_bb:.0f}BB -> FOLD")
    return Action(ActionType.FOLD)


def get_preflop_action(state: GameState) -> Action:
    """Get preflop action from lookup tables.

    Decision tree:
    1. Short stack (<20BB) -> push/fold charts
    2. Facing a 3-bet -> 3bet defense chart
    3. Open spot / facing limps -> position ranges
    4. BB facing raise -> BB defense chart
    """
    ranges = _load_ranges()
    hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
    pos_key = _position_key(state.my_position)
    tier = _stack_tier(state.effective_stack_bb)

    # 1. Short stack -> push/fold
    pf_action = get_push_fold_action(state)
    if pf_action is not None:
        return pf_action

    # 2. Facing a 3-bet (raise > 2.5x original raise, roughly > 7BB)
    if state.to_call >= state.big_blind * 7:
        return _handle_3bet(state, hand, ranges)

    # 3. Normal open / facing limps
    tier_ranges = ranges.get(tier, ranges.get("deep", {}))
    pos_ranges = _find_position_in_ranges(pos_key, tier_ranges)

    if pos_ranges is None:
        logger.warning(f"No ranges for {pos_key} in {tier}, folding")
        return Action(ActionType.FOLD)

    action_code = pos_ranges.get(hand)

    if action_code is None:
        # Hand not in range -> fold (or check from BB)
        if state.my_position == Position.BB and state.to_call <= 0:
            logger.info(f"PREFLOP: {hand} from BB, no raise -> CHECK")
            return Action(ActionType.CHECK)
        logger.info(f"PREFLOP: {hand} from {pos_key} not in range -> FOLD")
        return Action(ActionType.FOLD)

    if action_code == "R":
        # Open raise: 2.5x BB (or 3x from early positions)
        multiplier = 3.0 if pos_key in ("UTG", "UTG+1", "UTG+2") else 2.5
        raise_amount = state.big_blind * multiplier
        # If someone already raised, make it a 3-bet (3x their raise)
        if state.to_call > state.big_blind:
            raise_amount = state.to_call * 3
        raise_amount = min(raise_amount, state.my_stack)
        raise_amount = max(raise_amount, state.min_raise) if state.min_raise > 0 else raise_amount
        logger.info(f"PREFLOP: {hand} from {pos_key} -> RAISE {raise_amount:.0f}")
        return Action(ActionType.RAISE, raise_amount)

    elif action_code == "3B":
        # 3-bet: 3x the open raise
        raise_amount = state.to_call * 3
        raise_amount = min(raise_amount, state.my_stack)
        raise_amount = max(raise_amount, state.min_raise) if state.min_raise > 0 else raise_amount
        logger.info(f"PREFLOP: {hand} from {pos_key} -> 3-BET {raise_amount:.0f}")
        return Action(ActionType.RAISE, raise_amount)

    elif action_code == "C":
        if state.to_call <= 0:
            logger.info(f"PREFLOP: {hand} from {pos_key} -> CHECK")
            return Action(ActionType.CHECK)
        logger.info(f"PREFLOP: {hand} from {pos_key} -> CALL {state.to_call:.0f}")
        return Action(ActionType.CALL)

    elif action_code == "4B":
        raise_amount = min(state.to_call * 2.5, state.my_stack)
        logger.info(f"PREFLOP: {hand} from {pos_key} -> 4-BET {raise_amount:.0f}")
        return Action(ActionType.RAISE, raise_amount)

    # Default: fold
    return Action(ActionType.FOLD)


def _handle_3bet(state: GameState, hand: str, ranges: dict) -> Action:
    """Handle facing a 3-bet preflop."""
    defense = ranges.get("3bet_defense", {})
    action_code = defense.get(hand)

    if action_code == "4B":
        # 4-bet or jam
        raise_amount = min(state.to_call * 2.5, state.my_stack)
        # If 4-bet would commit >40% of stack, just jam
        if raise_amount > state.my_stack * 0.4:
            logger.info(f"3BET DEFENSE: {hand} -> ALL-IN (committed)")
            return Action(ActionType.ALL_IN, state.my_stack)
        logger.info(f"3BET DEFENSE: {hand} -> 4-BET {raise_amount:.0f}")
        return Action(ActionType.RAISE, raise_amount)

    elif action_code == "C":
        logger.info(f"3BET DEFENSE: {hand} -> CALL {state.to_call:.0f}")
        return Action(ActionType.CALL)

    else:
        logger.info(f"3BET DEFENSE: {hand} -> FOLD")
        return Action(ActionType.FOLD)
