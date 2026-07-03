"""Unit tests for src/clob_book.py fill simulation."""

import importlib.util
import sys
from pathlib import Path

# repo-root `src/` is a regular package that can shadow the domain's src under
# the monorepo pytest setup — load by file path (as test_collect_all_cities.py)
_SPEC = importlib.util.spec_from_file_location(
    "weather_clob_book",
    Path(__file__).resolve().parents[1] / "src" / "clob_book.py")
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["weather_clob_book"] = _mod  # dataclasses need the module registered
_SPEC.loader.exec_module(_mod)

Fill = _mod.Fill
walk_fill = _mod.walk_fill
no_levels_from_yes_bids = _mod.no_levels_from_yes_bids


class TestWalkFill:
    def test_full_fill_single_level(self):
        f = walk_fill([(0.50, 1000)], 100.0)
        assert f.complete
        assert f.avg_price == 0.50
        assert f.shares == 200.0
        assert f.stake_filled == 100.0
        assert f.levels_used == 1

    def test_full_fill_multiple_levels_vwap(self):
        # 100 shares @ 0.40 = $40, then rest at 0.50
        f = walk_fill([(0.40, 100), (0.50, 1000)], 100.0)
        assert f.complete
        # $60 remaining buys 120 shares at 0.50 -> 220 shares for $100
        assert abs(f.shares - 220.0) < 1e-9
        assert abs(f.avg_price - 100.0 / 220.0) < 1e-9
        assert f.levels_used == 2

    def test_partial_fill_when_depth_runs_out(self):
        f = walk_fill([(0.25, 100)], 100.0)  # only $25 of depth
        assert not f.complete
        assert f.shares == 100.0
        assert abs(f.stake_filled - 25.0) < 1e-9
        assert f.avg_price == 0.25

    def test_empty_book(self):
        f = walk_fill([], 100.0)
        assert not f.complete
        assert f.avg_price is None
        assert f.shares == 0.0

    def test_zero_price_levels_skipped(self):
        f = walk_fill([(0.0, 500), (0.10, 10)], 100.0)
        assert f.shares == 10.0
        assert f.avg_price == 0.10


class TestNoLevels:
    def test_transform_and_order(self):
        # YES bids best-first (highest first) -> NO asks cheapest-first
        bids = [(0.96, 39.0), (0.81, 16.0)]
        no = no_levels_from_yes_bids(bids)
        assert no[0] == (1.0 - 0.96, 39.0)
        assert no[1] == (1.0 - 0.81, 16.0)
        assert no[0][0] < no[1][0]

    def test_degenerate_prices_dropped(self):
        assert no_levels_from_yes_bids([(0.0, 5), (1.0, 5)]) == []
