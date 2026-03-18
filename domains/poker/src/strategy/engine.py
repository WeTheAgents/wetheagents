"""Top-level decision engine: routes to preflop/postflop strategy with tournament adjustments."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.table.state import Action, ActionType, GameState, Position, canonicalize_hand
from src.tracker.stats import OpponentTracker

logger = logging.getLogger(__name__)


@dataclass
class TournamentState:
    """Tournament context for ICM/bubble adjustments."""
    players_remaining: int = 0
    players_started: int = 0
    players_paid: int = 0  # how many places get paid
    avg_stack_bb: float = 0.0

    @property
    def is_bubble(self) -> bool:
        """Are we on or near the money bubble?"""
        if self.players_paid <= 0:
            return False
        # Bubble = within 2 spots of the money
        return 0 < (self.players_remaining - self.players_paid) <= 2

    @property
    def is_near_bubble(self) -> bool:
        """Approaching bubble (within 4 spots)."""
        if self.players_paid <= 0:
            return False
        return 0 < (self.players_remaining - self.players_paid) <= 4

    @property
    def in_the_money(self) -> bool:
        return self.players_paid > 0 and self.players_remaining <= self.players_paid

    @property
    def phase(self) -> str:
        if self.players_started <= 0:
            return "unknown"
        ratio = self.players_remaining / self.players_started
        if ratio > 0.7:
            return "early"
        elif ratio > 0.4:
            return "middle"
        elif self.is_bubble:
            return "bubble"
        elif self.in_the_money:
            return "final_table"
        else:
            return "middle"


class PokerEngine:
    """Main decision engine for the poker bot."""

    def __init__(
        self,
        tournament: TournamentState | None = None,
        tracker: OpponentTracker | None = None,
    ):
        self.tournament = tournament or TournamentState()
        self.tracker = tracker or OpponentTracker()
        self._hand_count = 0

    def update_tournament(self, **kwargs) -> None:
        """Update tournament state (called by operator or auto-detected)."""
        for key, val in kwargs.items():
            if hasattr(self.tournament, key):
                setattr(self.tournament, key, val)

    def get_action(self, state: GameState) -> Action:
        """Main entry point: get the best action for the current game state.

        Decision flow:
        1. Preflop -> preflop engine (with bubble adjustments)
        2. Postflop -> postflop engine
        3. Apply tournament adjustments
        """
        self._hand_count += 1

        if len(state.hole_cards) < 2:
            logger.warning("No hole cards, folding")
            return Action(ActionType.FOLD)

        hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
        logger.info(
            f"\n{'='*60}\n"
            f"Hand #{self._hand_count}: {hand} ({state.hole_cards[0]} {state.hole_cards[1]}) "
            f"| Position: {state.my_position.value if state.my_position else '?'} "
            f"| Stack: {state.effective_stack_bb:.0f}BB "
            f"| Pot: {state.pot:.0f} | To call: {state.to_call:.0f}"
        )

        if state.community_cards:
            logger.info(f"Board: {' '.join(state.community_cards)}")

        if state.is_preflop:
            action = self._preflop_decision(state)
        else:
            action = self._postflop_decision(state)

        # Apply bubble aggression
        action = self._apply_bubble_adjustment(state, action)

        logger.info(f"DECISION: {action}")
        return action

    def _preflop_decision(self, state: GameState) -> Action:
        """Delegate to preflop engine."""
        from src.strategy.preflop import get_preflop_action
        return get_preflop_action(state)

    def _postflop_decision(self, state: GameState) -> Action:
        """Delegate to postflop engine with opponent model."""
        from src.strategy.postflop import get_postflop_action

        # Populate opponent model from tracker
        state.villain_fold_pct = self._estimate_villain_fold_pct(state)
        state.villain_aggression = self._estimate_villain_aggression(state)
        state.in_position = self._is_in_position(state)
        return get_postflop_action(state)

    def _estimate_villain_fold_pct(self, state: GameState) -> float:
        """Estimate how often the current villain folds to a raise.

        Uses per-player fold_to_raise stats if available, falls back to
        player-type heuristics, then to table average.
        """
        # Find the active opponent(s) still in the hand
        fold_pcts: list[float] = []
        for p in state.players:
            if p.is_active and p.name:
                stats = self.tracker.get_stats(p.name)
                fold_pcts.append(stats.fold_to_raise)

        if not fold_pcts:
            return 0.45  # conservative default

        # If heads-up (1 opponent): use their exact stat
        # If multiway: use the minimum (hardest to bluff off)
        if len(fold_pcts) == 1:
            return fold_pcts[0]
        return min(fold_pcts)

    def _estimate_villain_aggression(self, state: GameState) -> float:
        """Estimate villain's aggression factor from tracker.

        AF > 2.0 = aggressive (bluffs often, triple-barrels)
        AF 1.0-2.0 = average
        AF < 1.0 = passive (only bets with goods, never bluffs)

        This drives WA/WB: check-call vs aggressive, bet/fold vs passive.
        """
        afs: list[float] = []
        for p in state.players:
            if p.is_active and p.name:
                stats = self.tracker.get_stats(p.name)
                afs.append(stats.aggression_factor)
        if not afs:
            return 1.5  # average default
        # Heads-up: exact AF. Multiway: max (most aggressive player drives action)
        if len(afs) == 1:
            return afs[0]
        return max(afs)

    def _is_in_position(self, state: GameState) -> bool:
        """Determine if we are in position (acting last) postflop."""
        if state.my_position is None:
            return True  # assume IP if unknown
        # BTN is always in position; CO if BTN folded
        # SB/BB are always out of position
        # Simple heuristic: BTN/CO = IP, everything else = OOP
        return state.my_position in (Position.BTN, Position.CO)

    def _apply_bubble_adjustment(self, state: GameState, action: Action) -> Action:
        """Bubble aggression: widen stealing ranges, pressure medium stacks.

        Key insight: on the bubble, medium stacks (15-30BB) are terrified of
        busting before the money. They fold WAY too much. We exploit this by:
        1. Opening wider from steal positions (CO/BTN/SB)
        2. 3-betting lighter vs opens from scared players
        3. Never folding to their steals with a big stack

        When WE are the short stack on the bubble, we tighten up and wait for
        premium hands, since everyone else is also tightening and we can pick
        up blinds with less risk.
        """
        if not self.tournament.is_bubble and not self.tournament.is_near_bubble:
            return action

        eff_bb = state.effective_stack_bb
        is_steal_position = state.my_position in (Position.CO, Position.BTN, Position.SB)

        # Big stack on bubble = predator mode
        if eff_bb > 30 and self.tournament.is_bubble:
            logger.info("BUBBLE: Big stack predator mode active")

            # Convert folds to raises from steal positions
            if action.type == ActionType.FOLD and is_steal_position and state.to_call <= state.big_blind:
                hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
                if self._is_bubble_steal_hand(hand):
                    raise_amount = state.big_blind * 2.5
                    raise_amount = min(raise_amount, state.my_stack)
                    logger.info(f"BUBBLE STEAL: {hand} from {state.my_position.value} -> RAISE")
                    return Action(ActionType.RAISE, raise_amount)

            # Increase aggression: convert calls to raises
            if action.type == ActionType.CALL and is_steal_position and state.is_preflop:
                from src.strategy.sizing import get_bet_size
                raise_amount = state.to_call * 3
                raise_amount = min(raise_amount, state.my_stack)
                logger.info("BUBBLE: Converting call to raise (pressure)")
                return Action(ActionType.RAISE, raise_amount)

        # Medium stack on bubble = survival mode (tighten slightly)
        elif 15 <= eff_bb <= 30 and self.tournament.is_bubble:
            # Don't open marginal hands — risk of getting 3-bet jammed
            if action.type == ActionType.RAISE and state.is_preflop:
                hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
                if not self._is_bubble_safe_open(hand):
                    logger.info(f"BUBBLE SURVIVAL: {hand} too marginal to open, folding")
                    return Action(ActionType.FOLD)

        return action

    def _is_bubble_steal_hand(self, hand: str) -> bool:
        """Hands we can profitably steal with on the bubble from late position.
        Much wider than normal ranges — any ace, any king, suited connectors, pairs.
        """
        if hand[0] in ('A', 'K'):
            return True
        if len(hand) == 2:  # pair
            return True
        if hand.endswith('s') and hand[0] in 'QJT98':  # suited broadway/connectors
            return True
        if hand in ('QJo', 'QTo', 'JTo'):
            return True
        return False

    def _is_bubble_safe_open(self, hand: str) -> bool:
        """Hands safe to open from medium stack on bubble (top ~12%)."""
        safe = {
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
            'AKs', 'AQs', 'AJs', 'ATs',
            'AKo', 'AQo',
            'KQs', 'KJs',
        }
        return hand in safe
