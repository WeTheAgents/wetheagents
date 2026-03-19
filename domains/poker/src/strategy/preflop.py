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


def _3bet_multiplier(pos: Position | None) -> float:
    """Position-aware 3-bet sizing multiplier.

    OOP (SB/BB): larger 3-bet to compensate for positional disadvantage.
    IP (BTN/CO): smaller 3-bet, position advantage lets us play smaller pots.
    """
    if pos in (Position.SB, Position.BB):
        return 3.8  # OOP
    elif pos in (Position.BTN, Position.CO):
        return 2.8  # IP
    return 3.2  # default


def _count_limpers(state: GameState) -> int:
    """Count players who limped (called BB without raising)."""
    count = 0
    for p in state.players:
        if p.is_active and p.bet > 0 and p.bet <= state.big_blind:
            count += 1
    # Subtract the 2 blinds (SB + BB are forced, not limpers)
    return max(0, count - 2)


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
    """Decide whether to call an all-in shove.

    Position-aware: tighter calling range vs EP pushes (they have
    stronger ranges), wider vs LP/SB pushes (they push wider).
    """
    push_fold = _load_push_fold()
    call_ranges = push_fold.get("call_push", {})

    eff_bb = state.effective_stack_bb
    if eff_bb <= 8:
        key = "vs_8bb_push"
    elif eff_bb <= 10:
        key = "vs_10bb_push"
    else:
        key = "vs_15bb_push"

    tier_data = call_ranges.get(key, {})

    # Position-aware: estimate where the pusher is sitting
    pusher_key = _estimate_pusher_position(state)

    if isinstance(tier_data, dict):
        hands = tier_data.get(pusher_key, tier_data.get("vs_LP", []))
    else:
        hands = tier_data  # legacy flat list fallback

    if hand in hands:
        logger.info(f"CALL PUSH: {hand} {pusher_key} at {eff_bb:.0f}BB -> CALL ALL-IN")
        return Action(ActionType.ALL_IN, state.my_stack)

    logger.info(f"CALL PUSH: {hand} {pusher_key} at {eff_bb:.0f}BB -> FOLD")
    return Action(ActionType.FOLD)


def _estimate_pusher_position(state: GameState) -> str:
    """Estimate the pusher's position for call-push decisions.

    Heuristic: more folds before the push = later position pusher.
    """
    folded = state.num_players - state.players_in_hand
    if folded >= 4:
        return "vs_SB"  # many folds -> likely SB or BTN push
    elif folded >= 2:
        return "vs_LP"  # some folds -> CO/BTN push
    else:
        return "vs_EP"  # few folds -> early position push


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

    # 1.5a AFK blind steal: if BB or SB is AFK, widen opening range
    afk_action = _afk_steal_action(state, hand)
    if afk_action is not None:
        return afk_action

    # 1.5b Iso-raise vs known limping stations
    iso_action = _iso_raise_vs_limper(state, hand)
    if iso_action is not None:
        return iso_action

    # 1.5c Reshove (3-bet jam) with 12-18BB facing a raise
    if 12 <= state.effective_stack_bb <= 18 and state.to_call > state.big_blind * 1.5:
        from src.strategy.reshove import get_reshove_action
        reshove = get_reshove_action(state)
        if reshove is not None:
            return reshove

    # 1.5d Light 3-bet vs steal-position opens
    if state.to_call > state.big_blind and state.to_call < state.big_blind * 7:
        light_3bet = _light_3bet_action(state, hand)
        if light_3bet is not None:
            return light_3bet

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
        # BB defends wider vs single raises (up to 3x BB)
        if state.my_position == Position.BB and 0 < state.to_call <= state.big_blind * 3:
            logger.info(f"PREFLOP: {hand} from BB, wide defend -> CALL {state.to_call:.0f}")
            return Action(ActionType.CALL)
        logger.info(f"PREFLOP: {hand} from {pos_key} not in range -> FOLD")
        return Action(ActionType.FOLD)

    if action_code == "R":
        # Open raise: 2.5x BB (or 3x from early positions)
        multiplier = 3.0 if pos_key in ("UTG", "UTG+1", "UTG+2") else 2.5
        # Add 1BB per limper
        limpers = _count_limpers(state)
        raise_amount = state.big_blind * (multiplier + limpers)
        # If someone already raised, make it a 3-bet (position-aware)
        if state.to_call > state.big_blind:
            raise_amount = state.to_call * _3bet_multiplier(state.my_position)
        raise_amount = min(raise_amount, state.my_stack)
        raise_amount = max(raise_amount, state.min_raise) if state.min_raise > 0 else raise_amount
        logger.info(f"PREFLOP: {hand} from {pos_key} -> RAISE {raise_amount:.0f}")
        return Action(ActionType.RAISE, raise_amount)

    elif action_code == "3B":
        # 3-bet: position-aware multiplier
        raise_amount = state.to_call * _3bet_multiplier(state.my_position)
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


def _afk_steal_action(state: GameState, hand: str) -> Action | None:
    """Exploit AFK players in the blinds by stealing wider.

    Graduated response:
    - 4-5 consecutive folds: steal with top ~50% of hands
    - 6+ consecutive folds (is_likely_afk): steal with any two cards

    Only applies in steal positions (CO, BTN, SB) when folded to us.
    Uses min-raise sizing (2.0x BB) to risk less.
    """
    if state.my_position not in (Position.CO, Position.BTN, Position.SB):
        return None

    # Only when it's folded to us (no raise ahead)
    if state.to_call > state.big_blind:
        return None

    # Check if BB is AFK
    if state.bb_is_afk:
        raise_amount = min(state.big_blind * 2.0, state.my_stack)
        logger.info(f"AFK STEAL: {hand} -> any2 steal vs AFK BB (2.0x)")
        return Action(ActionType.RAISE, raise_amount)

    # Graduated: 4-5 folds -> steal with wider range (~top 50%)
    if state.bb_consecutive_folds >= 4:
        if _is_top50_hand(hand):
            raise_amount = min(state.big_blind * 2.0, state.my_stack)
            logger.info(f"AFK STEAL: {hand} -> wide steal vs {state.bb_consecutive_folds} folds")
            return Action(ActionType.RAISE, raise_amount)

    # Passive short stack: <10BB BB with low PFR -> steal with any2
    if state.bb_is_passive_short:
        raise_amount = min(state.big_blind * 2.0, state.my_stack)
        logger.info(f"SHORT STACK EXPLOIT: {hand} -> steal vs passive short BB")
        return Action(ActionType.RAISE, raise_amount)

    return None


# Top ~50% of starting hands for graduated AFK stealing
_TOP50_HANDS = {
    # Pairs
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
    # Suited aces
    "AKs", "AQs", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    # Offsuit aces
    "AKo", "AQo", "AJo", "ATo", "A9o", "A8o", "A7o",
    # Suited kings
    "KQs", "KJs", "KTs", "K9s", "K8s", "K7s",
    # Offsuit kings
    "KQo", "KJo", "KTo",
    # Suited queens
    "QJs", "QTs", "Q9s", "Q8s",
    # Offsuit queens
    "QJo", "QTo",
    # Suited jacks
    "JTs", "J9s", "J8s",
    # Offsuit jacks
    "JTo",
    # Suited connectors/gappers
    "T9s", "T8s", "98s", "97s", "87s", "86s", "76s", "75s", "65s", "54s",
}


def _is_top50_hand(hand: str) -> bool:
    return hand in _TOP50_HANDS


def _light_3bet_action(state: GameState, hand: str) -> Action | None:
    """Light 3-bet vs wide steal-position opens.

    When facing a raise from CO/BTN/SB and we're in BB or SB, 3-bet
    with a polarized range: value hands (handled by normal ranges) +
    bluff hands with good blockers and playability.

    The bluff range widens further when the opener has a high PFR
    (>0.30 = opening very wide from steal positions).
    """
    # Only from BB or SB facing a steal-position open
    if state.my_position not in (Position.BB, Position.SB):
        return None

    if not state.opener_is_steal:
        return None

    # Need enough stack to 3-bet (not a reshove situation)
    if state.effective_stack_bb < 20:
        return None

    # Check if hand is in our bluff 3-bet range
    if state.opener_pfr > 0.30:
        # Opener is very wide -> expand bluff range
        bluff_range = _LIGHT_3BET_WIDE
    else:
        # Standard bluff 3-bet range vs steals
        bluff_range = _LIGHT_3BET_BASE

    if hand not in bluff_range:
        return None

    raise_amount = state.to_call * _3bet_multiplier(state.my_position)
    raise_amount = min(raise_amount, state.my_stack)
    raise_amount = max(raise_amount, state.min_raise) if state.min_raise > 0 else raise_amount
    logger.info(
        f"LIGHT 3BET: {hand} from {state.my_position.value} "
        f"vs steal (opener PFR={state.opener_pfr:.0%}) -> RAISE {raise_amount:.0f}"
    )
    return Action(ActionType.RAISE, raise_amount)


# Bluff 3-bet hands: blockers (Ax removes AA/AK from their range) + playability
_LIGHT_3BET_BASE = {
    # Suited aces with blockers (removes AA, AK from villain's range)
    "A5s", "A4s", "A3s", "A2s",
    # Suited connectors (play well postflop if called)
    "76s", "65s", "54s",
    # Suited king blockers (removes KK, AK)
    "K9s", "K8s",
}

# Expanded bluff range vs very wide openers (PFR > 0.30)
_LIGHT_3BET_WIDE = _LIGHT_3BET_BASE | {
    # More suited aces
    "A6s", "A7s", "A8s", "A9s",
    # More suited connectors
    "87s", "97s", "86s", "T9s",
    # Offsuit blockers
    "A5o", "A4o",
    # Suited kings
    "K7s", "K6s",
    # Queens with blockers
    "Q9s", "QTs",
}


def _iso_raise_vs_limper(state: GameState, hand: str) -> Action | None:
    """Iso-raise wider vs known limping stations.

    When a player with limp_frequency > 0.30 has limped in, widen our
    raising range to top ~35% with sizing 3x BB + 1x per limper.
    """
    if not state.has_limper:
        return None

    # Only when facing a limp (to_call == BB, no raise)
    if state.to_call > state.big_blind:
        return None

    limpers = _count_limpers(state)
    if limpers < 1:
        return None

    # Widen range to top ~35% vs limpers (top50 set covers this)
    if _is_top50_hand(hand):
        raise_amount = state.big_blind * (3.0 + limpers)
        raise_amount = min(raise_amount, state.my_stack)
        logger.info(f"ISO-RAISE: {hand} -> {raise_amount:.0f} vs {limpers} limper(s)")
        return Action(ActionType.RAISE, raise_amount)

    return None


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
