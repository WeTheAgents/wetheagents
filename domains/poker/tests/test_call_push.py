"""Tests for position-aware call-push ranges."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.preflop import _get_call_push_action
from src.table.state import ActionType, GameState, Position, Street


def _make_call_push_state(
    cards: list[str],
    position: Position = Position.BB,
    stack_bb: float = 10,
    bb: float = 20,
    to_call: float = 200,  # facing all-in
    num_players: int = 6,
    players_in_hand: int = 2,
) -> GameState:
    return GameState(
        hole_cards=cards,
        my_position=position,
        my_stack=stack_bb * bb,
        big_blind=bb,
        to_call=to_call,
        street=Street.PREFLOP,
        num_players=num_players,
        players_in_hand=players_in_hand,
        min_raise=bb * 2,
        max_raise=stack_bb * bb,
    )


class TestCallPush:
    """Test position-aware calling ranges vs all-in shoves."""

    def test_premium_calls_vs_any_position(self):
        """AA should call an all-in from any position."""
        from src.table.state import canonicalize_hand
        hand = canonicalize_hand("Ah", "As")
        # vs EP (few folds: 6 players, 5 in hand = 1 folded -> vs_EP)
        state = _make_call_push_state(
            ["Ah", "As"], num_players=6, players_in_hand=5,
        )
        action = _get_call_push_action(state, hand)
        assert action is not None
        assert action.type == ActionType.ALL_IN

    def test_tighter_vs_ep_push(self):
        """TT should NOT call a 15BB push from EP (tighter range)."""
        from src.table.state import canonicalize_hand
        hand = canonicalize_hand("Th", "Ts")
        # EP push: few folds (6 players, 5 in hand = 1 folded -> vs_EP)
        state = _make_call_push_state(
            ["Th", "Ts"], stack_bb=15, num_players=6, players_in_hand=5,
        )
        action = _get_call_push_action(state, hand)
        assert action is not None
        assert action.type == ActionType.FOLD, \
            f"TT should fold vs EP 15BB push, got {action.type}"

    def test_wider_vs_sb_push(self):
        """99 should call a 15BB push from SB (wider pusher range)."""
        from src.table.state import canonicalize_hand
        hand = canonicalize_hand("9h", "9s")
        # SB push: many folds (6 players, 2 in hand = 4 folded -> vs_SB)
        state = _make_call_push_state(
            ["9h", "9s"], stack_bb=15, num_players=6, players_in_hand=2,
        )
        action = _get_call_push_action(state, hand)
        assert action is not None
        assert action.type == ActionType.ALL_IN, \
            f"99 should call vs SB 15BB push, got {action.type}"
