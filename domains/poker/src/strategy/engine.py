"""Top-level decision engine: routes to preflop/postflop strategy with tournament adjustments."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.strategy.icm import icm_adjustment
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
            f"| Pos: {state.my_position.value if state.my_position else '?'}"
            f"({state.position_dist}/{state.num_players}) "
            f"| Stack: {state.effective_stack_bb:.0f}BB "
            f"| Pot: {state.pot:.0f} | To call: {state.to_call:.0f}"
        )

        if state.community_cards:
            logger.info(f"Board: {' '.join(state.community_cards)}")

        # Populate exploit context from tracker
        self._populate_exploit_context(state)

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

    def _populate_exploit_context(self, state: GameState) -> None:
        """Populate exploit flags on GameState from tracker data.

        Sets bb_is_afk, sb_is_afk, has_limper, limper_frequency based on
        per-player stats from the opponent tracker.
        """
        if not state.is_preflop:
            return  # exploit context is preflop-only for now

        for p in state.players:
            if not p.name:
                continue
            stats = self.tracker.get_stats(p.name)

            # Identify BB and SB by their forced bets
            # BB has bet == big_blind, SB has bet == big_blind / 2
            if abs(p.bet - state.big_blind) < 1.0:
                # Likely BB
                state.bb_is_afk = stats.is_likely_afk
                state.bb_consecutive_folds = stats.consecutive_folds
                # Passive short stack: <10BB and low PFR
                if (state.big_blind > 0
                        and p.stack / state.big_blind < 10
                        and stats.hands_seen >= 5
                        and stats.pfr < 0.25):
                    state.bb_is_passive_short = True
            elif abs(p.bet - state.big_blind / 2) < 1.0:
                # Likely SB
                state.sb_is_afk = stats.is_likely_afk

            # Limp station detection
            if p.is_active and stats.limp_frequency > 0.30:
                state.has_limper = True
                state.limper_frequency = max(state.limper_frequency, stats.limp_frequency)

            # Opener detection: find who raised (bet > BB = raiser)
            if (p.is_active and p.bet > state.big_blind * 1.5
                    and p.name != self._get_my_name(state)):
                # Estimate opener's position from their bet relative to others
                # If they have the largest bet, they're the opener
                state.opener_pfr = stats.pfr
                # Heuristic: if many players folded, opener is in late position
                folded = state.num_players - state.players_in_hand
                if folded >= 2:
                    state.opener_is_steal = True

    def _get_my_name(self, state: GameState) -> str:
        """Get our name from player list (player with no bet or specific flag)."""
        # Heuristic: our name is the one associated with our stack
        for p in state.players:
            if abs(p.stack - state.my_stack) < 1.0:
                return p.name
        return ""

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
        """ICM-driven tournament adjustments.

        Uses icm_adjustment() to determine aggression level:
        - multiplier > 1.2: predator mode (steal wider, pressure medium stacks)
        - multiplier < 0.9: survival mode (tighten opening ranges)
        - ~1.0: normal play
        """
        icm = icm_adjustment(
            self.tournament.players_remaining,
            self.tournament.players_paid,
            state.effective_stack_bb,
            self.tournament.avg_stack_bb,
        )

        if abs(icm - 1.0) < 0.05:
            return action  # no significant ICM pressure

        eff_bb = state.effective_stack_bb
        is_steal_position = state.my_position in (Position.CO, Position.BTN, Position.SB)

        # Predator mode: widen stealing, convert calls to raises
        if icm >= 1.2:
            logger.info(f"ICM PREDATOR: multiplier={icm:.2f}")

            if action.type == ActionType.FOLD and is_steal_position and state.to_call <= state.big_blind:
                hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
                if self._is_bubble_steal_hand(hand):
                    raise_amount = state.big_blind * 2.5
                    raise_amount = min(raise_amount, state.my_stack)
                    logger.info(f"ICM STEAL: {hand} from {state.my_position.value} -> RAISE")
                    return Action(ActionType.RAISE, raise_amount)

            if action.type == ActionType.CALL and is_steal_position and state.is_preflop:
                raise_amount = state.to_call * 3
                raise_amount = min(raise_amount, state.my_stack)
                logger.info("ICM: Converting call to raise (pressure)")
                return Action(ActionType.RAISE, raise_amount)

        # Survival mode: tighten preflop opens
        elif icm <= 0.85:
            logger.info(f"ICM SURVIVAL: multiplier={icm:.2f}")

            if action.type == ActionType.RAISE and state.is_preflop:
                hand = canonicalize_hand(state.hole_cards[0], state.hole_cards[1])
                if not self._is_bubble_safe_open(hand):
                    logger.info(f"ICM SURVIVAL: {hand} too marginal to open, folding")
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
