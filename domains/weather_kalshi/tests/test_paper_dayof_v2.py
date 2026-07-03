"""Unit tests for scalp v2 window selection and dedup exceptions."""

import importlib.util
import sys
from pathlib import Path

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
