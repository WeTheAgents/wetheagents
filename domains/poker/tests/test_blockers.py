"""Tests for blocker analysis module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.blockers import blocker_adjustment


class TestBlockerAdjustment:
    """Test blocker-based fold equity adjustments."""

    def test_nut_flush_blocker(self):
        """Holding Ah on three-heart board should give positive adjustment."""
        adj = blocker_adjustment(
            ["Ah", "Kd"],  # Ah blocks nut flush
            ["7h", "3h", "9h"],  # monotone hearts
        )
        assert adj >= 0.10, f"Nut flush blocker should give >=0.10, got {adj:.2f}"

    def test_king_flush_blocker(self):
        """Holding Kh on three-heart board should give smaller adjustment."""
        adj = blocker_adjustment(
            ["Kh", "Qd"],  # Kh blocks second nut flush
            ["7h", "3h", "9h"],
        )
        assert 0.05 <= adj <= 0.10, f"King flush blocker should be 0.05-0.10, got {adj:.2f}"

    def test_top_card_blocker(self):
        """Holding a card matching the top board card gives small adjustment."""
        adj = blocker_adjustment(
            ["Ah", "2d"],  # Ah matches top board card
            ["Ac", "7d", "3s"],  # A-high board
        )
        assert adj > 0, f"Top card blocker should be positive, got {adj:.2f}"

    def test_no_blockers(self):
        """No relevant blockers should return 0."""
        adj = blocker_adjustment(
            ["2h", "3d"],  # no blockers
            ["Ac", "Kd", "Qs"],  # AKQ rainbow, no flush draw
        )
        assert adj == 0.0, f"No blockers should give 0, got {adj:.2f}"

    def test_preflop_returns_zero(self):
        """Fewer than 3 community cards should return 0."""
        adj = blocker_adjustment(["Ah", "Kd"], [])
        assert adj == 0.0

    def test_combined_flush_and_top_card(self):
        """Holding Ah on A-high three-heart board gives combined adjustment."""
        adj = blocker_adjustment(
            ["Ah", "Kd"],
            ["As", "7h", "3h", "2h"],  # flush possible + we block top pair
        )
        # Ah blocks flush draw (but on hearts, Ah is hearts? No, As is spade, board has 3 hearts)
        # Actually Ah IS a heart, so it blocks nut flush on heart board
        # Plus we block top pair (we have an A, board has an A)
        assert adj > 0.10, f"Combined blockers should give >0.10, got {adj:.2f}"
