"""Unit tests for scalp v2 window selection, dedup, and passive paper fills."""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

# repo-root `scripts/` is a regular package that shadows the domain's namespace
# package under pytest — load the module by file path (same pattern as
# test_collect_all_cities.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# force the domain's scripts/ namespace (paper_dayof itself imports scripts.*)
import types  # noqa: E402

_pkg = types.ModuleType("scripts")
_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "scripts")]
sys.modules["scripts"] = _pkg
_SPEC = importlib.util.spec_from_file_location(
    "weather_paper_dayof",
    Path(__file__).resolve().parents[1] / "scripts" / "paper_dayof.py")
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_mod)

LATE_HOUR = _mod.LATE_HOUR
NONBLOCKING_SKIPS = _mod.NONBLOCKING_SKIPS
already_traded = _mod.already_traded
apply_passive_bid_observation = _mod.apply_passive_bid_observation
desired_bid_price = _mod.desired_bid_price
make_bid_ladder = _mod.make_bid_ladder
select_strategy = _mod.select_strategy


class TestSelectStrategy:
    def test_h50_window(self):
        assert select_strategy(13 * 60, 13) == "A_h50"
        assert select_strategy(13 * 60 + 14, 13) == "A_h50"
        assert select_strategy(13 * 60 + 15, 13) is None

    def test_late_window_separate(self):
        assert select_strategy(17 * 60 + 5, 14) == "A_17"

    def test_h50_equals_late_hour_collapses(self):
        # Madrid case: h50 == 17 -> single A-window, resolved as A_h50
        assert select_strategy(17 * 60 + 5, LATE_HOUR) == "A_h50"

    def test_b_window(self):
        assert select_strategy(16 * 60 + 30, 14) == "B"
        assert select_strategy(16 * 60 + 44, 14) == "B"
        assert select_strategy(16 * 60 + 45, 14) is None

    def test_no_window(self):
        assert select_strategy(12 * 60, 14) is None


def row(strategy="A_curmax_buy", slug="tokyo", md="2026-07-03",
        status="skipped", skip_reason=None):
    return {"strategy": strategy, "city_slug": slug, "market_date": md,
            "status": status, "skip_reason": skip_reason}


class TestDedup:
    def test_open_trade_blocks(self):
        assert already_traded([row(status="open")], "A_curmax_buy", "tokyo", "2026-07-03")

    def test_hard_skip_blocks(self):
        assert already_traded([row(skip_reason="ask_above_0.85")],
                              "A_curmax_buy", "tokyo", "2026-07-03")

    def test_flagged_wait_does_not_block(self):
        for reason in NONBLOCKING_SKIPS:
            assert not already_traded([row(skip_reason=reason)],
                                      "A_curmax_buy", "tokyo", "2026-07-03")

    def test_other_city_or_day_not_blocked(self):
        t = [row(status="open")]
        assert not already_traded(t, "A_curmax_buy", "seoul", "2026-07-03")
        assert not already_traded(t, "A_curmax_buy", "tokyo", "2026-07-04")


class TestPassiveBidLadder:
    def test_desired_price_uses_bought_side_mid(self):
        assert desired_bid_price("YES", 0.30, 0.50) == (0.40, "mid")
        assert desired_bid_price("NO", 0.30, 0.50) == (0.60, "mid")

    def test_desired_price_falls_back_one_cent_inside_touch(self):
        assert desired_bid_price("YES", None, 0.50) == (0.49, "touch_minus_1c")
        assert desired_bid_price("NO", 0.30, None) == (0.69, "touch_minus_1c")

    def test_ladder_prices_and_stakes(self):
        orders = make_bid_ladder(0.50)
        assert [(o["stake_target"], o["price"]) for o in orders] == [
            (10.0, 0.50), (8.0, 0.49), (6.0, 0.48)]

    def test_yes_touch_half_fills_then_pass_fills_remaining_levels(self):
        trade = {"side": "YES", "stake": 24.0, "bid_orders": make_bid_ladder(0.50)}
        events, touch = apply_passive_bid_observation(trade, 0.40, 0.50, "t1")
        assert touch == 0.50
        assert [e["event"] for e in events] == ["touched"]
        assert trade["bid_orders"][0]["filled_stake"] == 5.0
        assert trade["fill_stake"] == 5.0

        events, touch = apply_passive_bid_observation(trade, 0.40, 0.485, "t2")
        assert touch == 0.485
        assert [(e["level"], e["event"], e["delta_stake"]) for e in events] == [
            (1, "passed", 5.0), (2, "passed", 8.0)]
        assert trade["fill_stake"] == 18.0
        assert not trade["fill_complete"]

    def test_no_touch_and_pass_use_yes_bid_as_no_ask(self):
        trade = {"side": "NO", "stake": 24.0, "bid_orders": make_bid_ladder(0.20)}
        events, touch = apply_passive_bid_observation(trade, 0.80, 0.90, "t1")
        assert touch == 0.20
        assert [(e["level"], e["event"]) for e in events] == [(1, "touched")]
        assert trade["fill_stake"] == 5.0

        events, touch = apply_passive_bid_observation(trade, 0.815, 0.90, "t2")
        assert touch == 0.185
        assert [(e["level"], e["event"]) for e in events] == [(1, "passed"), (2, "passed")]
        assert trade["fill_stake"] == 18.0

    def test_settle_uses_filled_stake_only_for_passive_rows(self):
        old_trades, old_runs, old_fetch = _mod.TRADES_PATH, _mod.RUNS_PATH, _mod.fetch_price_history
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _mod.TRADES_PATH = root / "paper_trades.jsonl"
                _mod.RUNS_PATH = root / "paper_runs.jsonl"
                trade = {
                    "trade_id": "t1", "status": "open", "settled": None,
                    "execution_model": _mod.PASSIVE_MODEL,
                    "city_slug": "tokyo", "market_date": "2020-01-01",
                    "token_id": "token", "side": "YES",
                    "fill_shares": 20.0, "fill_stake": 10.0,
                    "fills": {"24": {"shares": 20.0, "stake_filled": 10.0}},
                }
                _mod.TRADES_PATH.write_text(json.dumps(trade) + "\n", encoding="utf-8")
                _mod.fetch_price_history = lambda *a, **k: [{"p": 0.99}]
                result = _mod.run_settle({"tokyo": {"tz": ZoneInfo("UTC")}})
                assert result["settled"] == 1
                settled = json.loads(_mod.TRADES_PATH.read_text(encoding="utf-8").strip())
                assert settled["status"] == "settled"
                assert settled["settled"]["pnl"] == 10.0
                assert settled["settled"]["pnl_24"] == 10.0
        finally:
            _mod.TRADES_PATH, _mod.RUNS_PATH, _mod.fetch_price_history = old_trades, old_runs, old_fetch

    def test_settle_ignores_legacy_open_rows(self):
        old_trades, old_runs, old_fetch = _mod.TRADES_PATH, _mod.RUNS_PATH, _mod.fetch_price_history
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _mod.TRADES_PATH = root / "paper_trades.jsonl"
                _mod.RUNS_PATH = root / "paper_runs.jsonl"
                trade = {
                    "trade_id": "legacy", "status": "open", "settled": None,
                    "city_slug": "tokyo", "market_date": "2020-01-01",
                    "token_id": "token", "side": "YES",
                    "fill_shares": 20.0, "fill_stake": 10.0,
                }
                _mod.TRADES_PATH.write_text(json.dumps(trade) + "\n", encoding="utf-8")
                _mod.fetch_price_history = lambda *a, **k: [{"p": 0.99}]
                result = _mod.run_settle({"tokyo": {"tz": ZoneInfo("UTC")}})
                assert result["settled"] == 0
                assert result["checked"] == 0
                assert result["ignored_legacy"] == 1
                unchanged = json.loads(_mod.TRADES_PATH.read_text(encoding="utf-8").strip())
                assert unchanged["status"] == "open"
                assert unchanged["settled"] is None
        finally:
            _mod.TRADES_PATH, _mod.RUNS_PATH, _mod.fetch_price_history = old_trades, old_runs, old_fetch
