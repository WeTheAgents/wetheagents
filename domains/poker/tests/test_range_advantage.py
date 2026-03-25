"""Tests for range advantage scoring."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.board import range_advantage
from src.table.state import Position


class TestRangeAdvantage:
    """Test range advantage by board type."""

    def test_ace_high_board_favours_raiser(self):
        """A-K-3 rainbow: raiser has more AK/AQ/AJ combos."""
        ra = range_advantage(["Ah", "Kc", "3d"], Position.CO, in_position=True)
        assert ra > 0.15, f"AK-high board should favour raiser, got {ra:.2f}"

    def test_low_connected_favours_caller(self):
        """7-8-9 two-tone: caller has suited connectors, raiser mostly missed."""
        ra = range_advantage(["7h", "8h", "9c"], Position.CO, in_position=True)
        assert ra < 0.0, f"Low connected board should favour caller, got {ra:.2f}"

    def test_ep_raiser_stronger_advantage(self):
        """UTG raiser has tighter range = more advantage on high boards."""
        ra_utg = range_advantage(["Ah", "Kc", "3d"], Position.UTG, in_position=False)
        ra_btn = range_advantage(["Ah", "Kc", "3d"], Position.BTN, in_position=True)
        assert ra_utg > ra_btn, \
            f"UTG advantage {ra_utg:.2f} should exceed BTN {ra_btn:.2f} on AK board"

    def test_monotone_penalises_raiser(self):
        """Monotone board slightly favours caller (more suited combos)."""
        ra_mono = range_advantage(["Jh", "8h", "4h"], Position.CO, in_position=True)
        ra_rainbow = range_advantage(["Jh", "8c", "4d"], Position.CO, in_position=True)
        assert ra_mono < ra_rainbow, \
            f"Monotone {ra_mono:.2f} should be worse than rainbow {ra_rainbow:.2f}"

    def test_returns_zero_preflop(self):
        """Should return 0 if fewer than 3 community cards."""
        ra = range_advantage([], Position.CO, in_position=True)
        assert ra == 0.0
