"""Tests for check-raise logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.postflop import _should_check_raise, _strong_hand_raise_frequency
from src.table.state import GameState, Street


def _make_cr_state(
    equity: float = 0.60,
    wetness_hint: float = 0.10,
    in_position: bool = False,
    checked_this_street: bool = True,
    players_in_hand: int = 2,
    villain_fold_pct: float = 0.45,
    villain_aggression: float = 1.5,
    street: Street = Street.FLOP,
    spr: float = 5.0,
) -> GameState:
    pot = 100.0
    stack = pot * spr
    return GameState(
        hole_cards=["Ah", "Kd"],
        community_cards=["7c", "3d", "2h"],  # dry board placeholder
        pot=pot,
        my_stack=stack,
        big_blind=20,
        street=street,
        num_players=6,
        players_in_hand=players_in_hand,
        in_position=in_position,
        checked_this_street=checked_this_street,
        villain_fold_pct=villain_fold_pct,
        villain_aggression=villain_aggression,
        to_call=50,
        min_raise=40,
        max_raise=stack,
    )


class TestCheckRaise:
    """Test check-raise decision logic."""

    def test_value_check_raise_strong_hand_oop(self):
        """Strong hand OOP after checking should check-raise most of the time."""
        hits = 0
        trials = 100
        for _ in range(trials):
            state = _make_cr_state(in_position=False, checked_this_street=True)
            if _should_check_raise(state, equity=0.80, wetness=0.15):
                hits += 1
        # Should hit ~70% of the time
        assert hits > 50, f"Value CR should trigger ~70% of time, got {hits}%"

    def test_no_check_raise_ip(self):
        """In position should never check-raise (it's an OOP play)."""
        state = _make_cr_state(in_position=True, checked_this_street=True)
        result = _should_check_raise(state, equity=0.85, wetness=0.15)
        assert result is False, "Should not check-raise in position"

    def test_no_check_raise_without_check(self):
        """Cannot check-raise if we haven't checked this street."""
        state = _make_cr_state(in_position=False, checked_this_street=False)
        result = _should_check_raise(state, equity=0.85, wetness=0.15)
        assert result is False, "Cannot CR without checking first"

    def test_bluff_check_raise_wet_board(self):
        """Draws on wet boards with fold equity should sometimes bluff-CR."""
        hits = 0
        trials = 200
        for _ in range(trials):
            state = _make_cr_state(
                in_position=False,
                checked_this_street=True,
                villain_fold_pct=0.50,
            )
            if _should_check_raise(state, equity=0.42, wetness=0.45):
                hits += 1
        # Should hit ~25% of the time
        assert 10 < hits < 80, f"Bluff CR should trigger ~25% of time, got {hits / 2}%"

    def test_no_bluff_cr_dry_board(self):
        """No bluff check-raise on dry boards (low fold equity, no draws)."""
        state = _make_cr_state(
            in_position=False,
            checked_this_street=True,
            villain_fold_pct=0.50,
        )
        result = _should_check_raise(state, equity=0.42, wetness=0.10)
        assert result is False, "No bluff CR on dry board"


class TestDynamicRaiseFrequency:
    """Test the dynamic strong-hand raise frequency."""

    def test_wet_board_raises_more(self):
        """Wet board should increase raise frequency."""
        state = _make_cr_state(spr=6.0, street=Street.FLOP)
        freq_wet = _strong_hand_raise_frequency(state, 0.65, wetness=0.50)
        freq_dry = _strong_hand_raise_frequency(state, 0.65, wetness=0.10)
        assert freq_wet > freq_dry, \
            f"Wet board freq {freq_wet:.2f} should exceed dry {freq_dry:.2f}"

    def test_passive_villain_raises_more(self):
        """Vs passive villain, should raise more for value."""
        state = _make_cr_state(villain_aggression=0.7)
        freq = _strong_hand_raise_frequency(state, 0.65, wetness=0.30)
        assert freq > 0.40, f"Vs passive, freq should be >40%, got {freq:.2f}"

    def test_river_raises_less(self):
        """River should decrease raise frequency."""
        state = _make_cr_state(street=Street.RIVER)
        freq = _strong_hand_raise_frequency(state, 0.65, wetness=0.30)
        state_flop = _make_cr_state(street=Street.FLOP)
        freq_flop = _strong_hand_raise_frequency(state_flop, 0.65, wetness=0.30)
        assert freq < freq_flop, \
            f"River freq {freq:.2f} should be less than flop {freq_flop:.2f}"

    def test_frequency_clamped(self):
        """Frequency should be clamped to [0.15, 0.65]."""
        state = _make_cr_state(villain_aggression=5.0, street=Street.RIVER, spr=20.0)
        freq = _strong_hand_raise_frequency(state, 0.65, wetness=0.05)
        assert freq >= 0.15, f"Min freq should be 0.15, got {freq:.2f}"

        state2 = _make_cr_state(villain_aggression=0.5, street=Street.FLOP, spr=2.0)
        freq2 = _strong_hand_raise_frequency(state2, 0.65, wetness=0.60)
        assert freq2 <= 0.65, f"Max freq should be 0.65, got {freq2:.2f}"
