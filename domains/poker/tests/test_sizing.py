"""Tests for bet sizing logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.sizing import (
    _bluff_fraction, _cbet_fraction, _value_fraction,
    _villain_adjusted_fraction, get_bet_size,
)
from src.table.state import GameState, Street


def _make_sizing_state(
    board: list[str],
    pot: float = 100,
    stack: float = 1000,
    bb: float = 20,
) -> GameState:
    if len(board) == 3:
        street = Street.FLOP
    elif len(board) == 4:
        street = Street.TURN
    else:
        street = Street.RIVER
    return GameState(
        hole_cards=["Ah", "Kd"],
        community_cards=board,
        pot=pot,
        my_stack=stack,
        big_blind=bb,
        street=street,
        num_players=6,
        players_in_hand=2,
        min_raise=bb * 2,
        max_raise=stack,
    )


class TestCbetFraction:
    """Test texture-aware c-bet sizing."""

    def test_small_ball_dry_flop(self):
        """Dry board (K72 rainbow) should use ~33% pot."""
        state = _make_sizing_state(["Kh", "7c", "2d"])
        frac = _cbet_fraction(state)
        assert 0.30 <= frac <= 0.40, f"Dry flop c-bet should be ~33%, got {frac:.2f}"

    def test_medium_moderate_flop(self):
        """Moderate board should use ~50% pot."""
        # K-Q-8 rainbow: KQ connected (gap=1) +0.25, broadway bonus +0.05 = 0.30
        state = _make_sizing_state(["Kh", "Qc", "8d"])
        frac = _cbet_fraction(state)
        assert 0.45 <= frac <= 0.55, f"Moderate flop c-bet should be ~50%, got {frac:.2f}"

    def test_large_wet_flop(self):
        """Wet board (JT9 two-tone) should use ~66% pot."""
        state = _make_sizing_state(["Jh", "Th", "9c"])
        frac = _cbet_fraction(state)
        assert 0.60 <= frac <= 0.70, f"Wet flop c-bet should be ~66%, got {frac:.2f}"

    def test_turn_unchanged(self):
        """Turn c-bet is 65% regardless of texture."""
        state = _make_sizing_state(["Kh", "7c", "2d", "3s"])
        frac = _cbet_fraction(state)
        assert abs(frac - 0.65) < 0.01, f"Turn c-bet should be 65%, got {frac:.2f}"


class TestValueFraction:
    """Test value bet sizing."""

    def test_base_value(self):
        """Default value bet is 66% pot."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        frac = _value_fraction(state, 0.65)
        assert abs(frac - 0.66) < 0.05, f"Base value should be ~66%, got {frac:.2f}"

    def test_strong_value_larger(self):
        """85%+ equity should bet bigger."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        frac = _value_fraction(state, 0.90)
        assert frac >= 0.75, f"Strong value should be >=75%, got {frac:.2f}"

    def test_river_value_larger(self):
        """River value bets should be slightly larger."""
        state = _make_sizing_state(["7c", "3d", "2h", "9s", "Jc"])
        frac = _value_fraction(state, 0.70)
        assert frac > 0.70, f"River value should be >70%, got {frac:.2f}"

    def test_river_overbet_with_nuts(self):
        """Nuts on river (equity >= 0.90) should overbet (1.3x pot)."""
        state = _make_sizing_state(["7c", "3d", "2h", "9s", "Jc"])
        frac = _value_fraction(state, 0.95)
        assert frac >= 1.20, f"Nuts on river should overbet, got {frac:.2f}"


class TestBluffFraction:
    """Test bluff sizing."""

    def test_flop_bluff_smaller(self):
        """Flop bluffs should be 50% pot (risk less)."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        frac = _bluff_fraction(state)
        assert abs(frac - 0.50) < 0.01, f"Flop bluff should be 50%, got {frac:.2f}"

    def test_river_bluff_larger(self):
        """River bluffs should be 60% pot (need to be believable)."""
        state = _make_sizing_state(["7c", "3d", "2h", "9s", "Jc"])
        frac = _bluff_fraction(state)
        assert abs(frac - 0.60) < 0.01, f"River bluff should be 60%, got {frac:.2f}"


class TestGetBetSize:
    """Test the main bet size calculator."""

    def test_short_stack_jams(self):
        """When stack <= 1.5x pot, should jam."""
        state = _make_sizing_state(["7c", "3d", "2h"], pot=100, stack=120)
        bet = get_bet_size(state, 0.70, is_value=True)
        assert bet == 120, f"Short stack should jam, got {bet}"

    def test_zero_pot_returns_zero(self):
        """Zero pot should return 0 bet."""
        state = _make_sizing_state(["7c", "3d", "2h"], pot=0, stack=1000)
        bet = get_bet_size(state, 0.70, is_value=True)
        assert bet == 0.0


class TestVillainAdjustedFraction:
    """Test villain-adjusted bet sizing."""

    def test_calling_station_value_bigger(self):
        """Against calling station (AF<1.0), value bets should be larger."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        state.villain_aggression = 0.5  # calling station
        adjusted = _villain_adjusted_fraction(0.66, state, is_value=True)
        assert adjusted > 0.66, f"Value vs station should be >66%, got {adjusted:.2f}"

    def test_calling_station_no_bluff(self):
        """Against calling station, bluff sizing should be 0 (don't bluff)."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        state.villain_aggression = 0.5
        adjusted = _villain_adjusted_fraction(0.50, state, is_value=False)
        assert adjusted == 0.0, f"Bluff vs station should be 0, got {adjusted:.2f}"

    def test_lag_value_smaller(self):
        """Against LAG (AF>2.5), value bets should be smaller (induce)."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        state.villain_aggression = 3.0  # LAG
        adjusted = _villain_adjusted_fraction(0.66, state, is_value=True)
        assert adjusted < 0.66, f"Value vs LAG should be <66%, got {adjusted:.2f}"

    def test_nit_value_smaller(self):
        """Against nit (high fold %), value bets should be smaller."""
        state = _make_sizing_state(["7c", "3d", "2h"])
        state.villain_aggression = 1.5  # normal AF
        state.villain_fold_pct = 0.70  # nit
        adjusted = _villain_adjusted_fraction(0.66, state, is_value=True)
        assert adjusted < 0.66, f"Value vs nit should be <66%, got {adjusted:.2f}"

    def test_bluff_zero_returns_zero_bet(self):
        """When villain adjustment says don't bluff, get_bet_size returns 0."""
        state = _make_sizing_state(["7c", "3d", "2h"], pot=100)
        state.villain_aggression = 0.5  # calling station
        bet = get_bet_size(state, 0.40, is_bluff=True)
        assert bet == 0.0, f"Bluff vs calling station should be 0, got {bet}"
