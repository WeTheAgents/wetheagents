"""Tests for ICM adjustment module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.icm import icm_adjustment


class TestICMAdjustment:
    """Test ICM aggression multiplier."""

    def test_cash_game_no_adjustment(self):
        """No paid places = cash game, multiplier should be 1.0."""
        mult = icm_adjustment(
            players_remaining=6, players_paid=0, eff_bb=30, avg_stack_bb=25,
        )
        assert mult == 1.0

    def test_big_stack_bubble_predator(self):
        """Big stack on bubble should get predator multiplier (>1.2)."""
        mult = icm_adjustment(
            players_remaining=5, players_paid=4,  # 1 from money = bubble
            eff_bb=50, avg_stack_bb=25,  # 2x average = big stack
        )
        assert mult >= 1.2, f"Big stack on bubble should be >=1.2, got {mult:.2f}"

    def test_medium_stack_bubble_survival(self):
        """Medium stack on bubble should tighten (multiplier < 1.0)."""
        mult = icm_adjustment(
            players_remaining=5, players_paid=4,  # bubble
            eff_bb=25, avg_stack_bb=25,  # average stack
        )
        assert mult < 1.0, f"Medium stack on bubble should be <1.0, got {mult:.2f}"

    def test_short_stack_bubble_desperate(self):
        """Short stack on bubble should be very tight."""
        mult = icm_adjustment(
            players_remaining=5, players_paid=4,  # bubble
            eff_bb=10, avg_stack_bb=25,  # 0.4x average = short
        )
        assert mult <= 0.7, f"Short stack on bubble should be <=0.7, got {mult:.2f}"

    def test_itm_loosens_up(self):
        """In the money should allow more aggression."""
        mult = icm_adjustment(
            players_remaining=3, players_paid=4,  # already ITM
            eff_bb=30, avg_stack_bb=25,
        )
        assert mult > 1.0, f"ITM should be >1.0, got {mult:.2f}"

    def test_far_from_bubble_normal(self):
        """Far from bubble should be normal play."""
        mult = icm_adjustment(
            players_remaining=20, players_paid=5,  # 15 from money
            eff_bb=25, avg_stack_bb=25,
        )
        assert mult == 1.0, f"Far from bubble should be 1.0, got {mult:.2f}"
