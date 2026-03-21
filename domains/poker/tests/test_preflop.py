"""Tests for preflop strategy engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.preflop import get_preflop_action
from src.table.state import (
    ActionType,
    GameState,
    Position,
    Street,
    canonicalize_hand,
)


def _make_state(
    cards: list[str],
    position: Position = Position.UTG,
    stack_bb: float = 100,
    bb: float = 20,
    to_call: float = 0,
) -> GameState:
    return GameState(
        hole_cards=cards,
        my_position=position,
        my_stack=stack_bb * bb,
        big_blind=bb,
        to_call=to_call,
        street=Street.PREFLOP,
        num_players=6,
        players_in_hand=6,
        min_raise=bb * 2,
        max_raise=stack_bb * bb,
    )


class TestCanonicalizeHand:
    def test_pair(self):
        assert canonicalize_hand("Ah", "As") == "AA"
        assert canonicalize_hand("2c", "2d") == "22"

    def test_suited(self):
        assert canonicalize_hand("Ah", "Kh") == "AKs"
        assert canonicalize_hand("9s", "Ts") == "T9s"  # higher rank first

    def test_offsuit(self):
        assert canonicalize_hand("Ah", "Kd") == "AKo"
        assert canonicalize_hand("7c", "8d") == "87o"  # higher rank first

    def test_order_independent(self):
        assert canonicalize_hand("Kd", "Ah") == canonicalize_hand("Ah", "Kd")
        assert canonicalize_hand("2s", "3s") == canonicalize_hand("3s", "2s")

    def test_ten(self):
        assert canonicalize_hand("Th", "9h") == "T9s"


class TestPreflopRanges:
    """Verify basic range integrity."""

    def test_aa_raises_everywhere(self):
        """AA should always raise from any position."""
        for pos in [Position.UTG, Position.MP, Position.CO, Position.BTN, Position.SB]:
            state = _make_state(["Ah", "As"], position=pos)
            action = get_preflop_action(state)
            assert action.type in (ActionType.RAISE, ActionType.ALL_IN), \
                f"AA should raise from {pos.value}, got {action.type}"

    def test_72o_folds_everywhere(self):
        """72o should fold from any position (except BB free check)."""
        for pos in [Position.UTG, Position.MP, Position.CO, Position.BTN, Position.SB]:
            state = _make_state(["7h", "2c"], position=pos)
            action = get_preflop_action(state)
            assert action.type == ActionType.FOLD, \
                f"72o should fold from {pos.value}, got {action.type}"

    def test_bb_checks_with_garbage(self):
        """BB should check (not fold) garbage hands when no raise."""
        state = _make_state(["7h", "2c"], position=Position.BB, to_call=0)
        action = get_preflop_action(state)
        assert action.type == ActionType.CHECK

    def test_aks_raises_from_btn(self):
        """AKs should raise from BTN."""
        state = _make_state(["Ah", "Kh"], position=Position.BTN)
        action = get_preflop_action(state)
        assert action.type == ActionType.RAISE

    def test_utg_tighter_than_btn(self):
        """UTG should play fewer hands than BTN (e.g., 76s)."""
        state_utg = _make_state(["7h", "6h"], position=Position.UTG)
        state_btn = _make_state(["7h", "6h"], position=Position.BTN)

        action_utg = get_preflop_action(state_utg)
        action_btn = get_preflop_action(state_btn)

        assert action_utg.type == ActionType.FOLD, "76s should fold from UTG"
        assert action_btn.type == ActionType.RAISE, "76s should raise from BTN"


class TestPushFold:
    """Test short-stack push/fold logic."""

    def test_aa_pushes_at_10bb(self):
        state = _make_state(["Ah", "As"], position=Position.UTG, stack_bb=10)
        action = get_preflop_action(state)
        assert action.type == ActionType.ALL_IN

    def test_72o_folds_at_10bb(self):
        state = _make_state(["7h", "2c"], position=Position.UTG, stack_bb=10)
        action = get_preflop_action(state)
        assert action.type == ActionType.FOLD

    def test_btn_wider_than_utg_at_10bb(self):
        """BTN should push much wider than UTG at 10BB."""
        # K7o: should push from BTN but not UTG at 10BB
        state_utg = _make_state(["Kh", "7c"], position=Position.UTG, stack_bb=10)
        state_btn = _make_state(["Kh", "7c"], position=Position.BTN, stack_bb=10)

        action_utg = get_preflop_action(state_utg)
        action_btn = get_preflop_action(state_btn)

        assert action_utg.type == ActionType.FOLD
        assert action_btn.type == ActionType.ALL_IN


class TestPreflopSizing:
    """Test position-aware preflop sizing."""

    def test_3bet_oop_larger(self):
        """SB/BB should 3-bet at 3.8x (larger OOP)."""
        state = _make_state(
            ["Ah", "Kh"], position=Position.BB,
            to_call=50,  # facing a raise (2.5x BB=20)
        )
        action = get_preflop_action(state)
        if action.type == ActionType.RAISE and action.amount:
            # 3-bet from BB: 50 * 3.8 = 190
            assert action.amount >= 50 * 3.5, \
                f"BB 3-bet should be ~3.8x, got {action.amount / 50:.1f}x"

    def test_3bet_ip_smaller(self):
        """BTN/CO should 3-bet at 2.8x (smaller IP)."""
        state = _make_state(
            ["Ah", "Kh"], position=Position.BTN,
            to_call=50,  # facing a raise
        )
        action = get_preflop_action(state)
        if action.type == ActionType.RAISE and action.amount:
            # 3-bet from BTN: 50 * 2.8 = 140
            assert action.amount <= 50 * 3.3, \
                f"BTN 3-bet should be ~2.8x, got {action.amount / 50:.1f}x"

    def test_open_raise_with_limpers(self):
        """Open raise should be +1BB per limper."""
        from src.table.state import PlayerState
        state = _make_state(["Ah", "Kh"], position=Position.CO)
        # Add 2 limpers (players who put in 1BB)
        state.players = [
            PlayerState(name="SB", stack=2000, bet=10),   # SB
            PlayerState(name="BB", stack=2000, bet=20),   # BB
            PlayerState(name="Limper1", stack=2000, bet=20),  # limper
            PlayerState(name="Limper2", stack=2000, bet=20),  # limper
            PlayerState(name="Hero", stack=2000, bet=0),
        ]
        action = get_preflop_action(state)
        if action.type == ActionType.RAISE and action.amount:
            # Base 2.5x + 2 limpers = 4.5x BB = 90
            assert action.amount >= 20 * 4, \
                f"With 2 limpers, raise should be ~4.5x BB, got {action.amount:.0f}"


class TestThreeBetDefense:
    """Test 3-bet defense logic."""

    def test_aa_4bets_vs_3bet(self):
        """AA should 4-bet when facing a 3-bet."""
        state = _make_state(
            ["Ah", "As"], position=Position.CO, to_call=200,  # 10BB 3-bet
        )
        action = get_preflop_action(state)
        assert action.type in (ActionType.RAISE, ActionType.ALL_IN)

    def test_garbage_folds_vs_3bet(self):
        """Garbage should fold facing a 3-bet."""
        state = _make_state(
            ["7h", "2c"], position=Position.CO, to_call=200,
        )
        action = get_preflop_action(state)
        assert action.type == ActionType.FOLD
