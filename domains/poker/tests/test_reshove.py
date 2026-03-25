"""Tests for reshove (3-bet jam) module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.reshove import get_reshove_action
from src.table.state import ActionType, GameState, Position, Street


def _make_reshove_state(
    cards: list[str],
    position: Position = Position.BB,
    stack_bb: float = 14,
    bb: float = 20,
    to_call: float = 50,  # facing a 2.5x open
    num_players: int = 6,
    players_in_hand: int = 3,
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


class TestReshove:
    """Test 3-bet jam ranges."""

    def test_aa_jams_from_bb(self):
        """AA at 14BB facing a raise from BB should always jam."""
        state = _make_reshove_state(["Ah", "As"], position=Position.BB, stack_bb=14)
        action = get_reshove_action(state)
        assert action is not None
        assert action.type == ActionType.ALL_IN

    def test_garbage_folds_15bb(self):
        """72o at 15BB facing a raise should fold (not in reshove range)."""
        state = _make_reshove_state(["7h", "2c"], position=Position.BB, stack_bb=15)
        action = get_reshove_action(state)
        assert action is not None
        assert action.type == ActionType.FOLD

    def test_wider_from_sb_vs_btn(self):
        """SB should reshove wider vs BTN opens (few folds = BTN open)."""
        # 77 is in SB->BTN 12-15bb range
        state = _make_reshove_state(
            ["7h", "7c"], position=Position.SB, stack_bb=13,
            players_in_hand=2,  # heads up = BTN open
        )
        action = get_reshove_action(state)
        assert action is not None
        assert action.type == ActionType.ALL_IN, \
            f"77 from SB vs BTN at 13BB should jam, got {action.type}"

    def test_not_applicable_deep_stack(self):
        """30BB stack should not trigger reshove."""
        state = _make_reshove_state(["Ah", "As"], stack_bb=30)
        action = get_reshove_action(state)
        assert action is None, "Reshove should not apply at 30BB"

    def test_not_applicable_no_raise(self):
        """Without a raise (to_call = 0), reshove should not apply."""
        state = _make_reshove_state(["Ah", "As"], to_call=0)
        action = get_reshove_action(state)
        assert action is None, "Reshove should not apply when no raise to face"

    def test_integration_via_preflop(self):
        """Reshove should be triggered through get_preflop_action."""
        from src.strategy.preflop import get_preflop_action
        state = _make_reshove_state(["Ah", "As"], position=Position.BB, stack_bb=14)
        action = get_preflop_action(state)
        assert action.type == ActionType.ALL_IN, \
            f"AA at 14BB facing raise should jam via preflop, got {action.type}"
