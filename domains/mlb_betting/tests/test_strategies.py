"""Unit tests for the production strategy filters.

Each strategy is tested with synthetic frames so we can pin the exact
filter logic without needing the full feature pipeline. This catches
filter regressions (e.g. if someone changes a threshold or accidentally
flips a comparison) within seconds in CI.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.strategies import (
    Pick,
    add_derived_for_strategies,
    find_fav_rl_picks,
    find_tier1_picks,
    find_tier2_picks,
    find_tier3_picks,
)


# ---------------------------------------------------------------------------
# Fixture: a tiny enriched DataFrame the strategies can consume.
# ---------------------------------------------------------------------------


def _row(**kwargs) -> dict:
    """Build a single game row with sensible defaults."""
    base = {
        "date": pd.Timestamp("2026-04-12"),
        "season": 2026,
        "away_team": "AAA",
        "home_team": "BBB",
        "home_close_ml": -150,
        "away_close_ml": 130,
        "home_implied_prob": 0.60,
        "away_implied_prob": 0.43,
        "home_is_bullpen_no_starter": False,
        "away_is_bullpen_no_starter": False,
        "bp_ip_3d_home": 5.0,
        "bp_ip_3d_away": 5.0,
        "home_sp_fip_short": 4.00,
        "away_sp_fip_short": 4.00,
        "home_sp_ip_per_start_short": 5.5,
        "away_sp_ip_per_start_short": 5.5,
        "home_sp_ip_per_start_long": 5.5,
        "away_sp_ip_per_start_long": 5.5,
        "power_rate_home": 0.40,
        "power_rate_away": 0.40,
        "away_run_line_odds": 150,
        "home_run_line_odds": -180,
    }
    base.update(kwargs)
    return base


def _frame(*rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    return add_derived_for_strategies(df)


TODAY = date(2026, 4, 12)


# ---------------------------------------------------------------------------
# add_derived_for_strategies
# ---------------------------------------------------------------------------


def test_derived_columns_present():
    df = _frame(_row())
    for col in [
        "fav_implied_prob",
        "fav_is_home",
        "fav_starter_fip_diff",
        "fav_power_rate_diff",
        "bp_workload_gap",
        "starter_depth_diff_short",
        "starter_depth_diff",
    ]:
        assert col in df.columns, f"missing derived col: {col}"


def test_fav_is_home_true_when_home_implied_higher():
    df = _frame(_row(home_implied_prob=0.65, away_implied_prob=0.42))
    assert df["fav_is_home"].iloc[0] is True or df["fav_is_home"].iloc[0] == True  # noqa: E712


def test_fav_is_home_false_when_away_implied_higher():
    df = _frame(_row(home_implied_prob=0.40, away_implied_prob=0.65))
    assert not df["fav_is_home"].iloc[0]


def test_fip_diff_signed_for_home_fav():
    """If home is fav and home FIP is LOWER (better), fav_starter_fip_diff is negative."""
    df = _frame(
        _row(
            home_implied_prob=0.65,
            away_implied_prob=0.40,
            home_sp_fip_short=3.20,
            away_sp_fip_short=4.00,
        )
    )
    # raw = home - away = -0.80; flip = +1 (fav is home); fav_diff = -0.80
    assert df["fav_starter_fip_diff"].iloc[0] == pytest.approx(-0.80)


def test_fip_diff_signed_for_away_fav():
    """If AWAY is the fav and AWAY FIP is lower, fav_starter_fip_diff is also negative."""
    df = _frame(
        _row(
            home_implied_prob=0.40,
            away_implied_prob=0.65,
            home_sp_fip_short=4.00,
            away_sp_fip_short=3.20,
        )
    )
    # raw = home - away = +0.80; flip = -1 (fav is away); fav_diff = -0.80
    assert df["fav_starter_fip_diff"].iloc[0] == pytest.approx(-0.80)


# ---------------------------------------------------------------------------
# Tier 1 — bullpen day dog
# ---------------------------------------------------------------------------


def test_tier1_fires_on_home_bullpen_day_with_home_fav():
    """Case A: home still fav -> ML_dog + RL_+1.5 (2 picks)."""
    df = _frame(
        _row(
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.70,
            away_implied_prob=0.34,
        )
    )
    picks = find_tier1_picks(df, TODAY)
    assert len(picks) == 2
    assert {p.market for p in picks} == {"ML_dog", "RL_+1.5"}
    assert all(p.side == "away" for p in picks)
    assert all(p.tier == "tier1_bullpen_day" for p in picks)


def test_tier1_flipped_emits_rl_only():
    """Case B (Sess 29): line flipped, home is now dog -> RL +1.5 only."""
    df = _frame(
        _row(
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.45,
            away_implied_prob=0.60,
        )
    )
    picks = find_tier1_picks(df, TODAY)
    assert len(picks) == 1
    assert picks[0].market == "RL_+1.5"
    assert picks[0].tier == "tier1_bullpen_day_flipped"
    assert picks[0].historical_p == pytest.approx(0.888)


def test_tier1_skipped_when_away_is_also_bullpen_day():
    df = _frame(
        _row(
            home_is_bullpen_no_starter=True,
            away_is_bullpen_no_starter=True,
            home_implied_prob=0.65,
            away_implied_prob=0.40,
        )
    )
    assert find_tier1_picks(df, TODAY) == []


def test_tier1_skipped_when_no_bullpen_day():
    df = _frame(_row(home_is_bullpen_no_starter=False))
    assert find_tier1_picks(df, TODAY) == []


def test_tier1_case_a_uses_sess26_probabilities():
    df = _frame(
        _row(
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.70,
            away_implied_prob=0.34,
        )
    )
    picks = find_tier1_picks(df, TODAY)
    ml = next(p for p in picks if p.market == "ML_dog")
    rl = next(p for p in picks if p.market == "RL_+1.5")
    assert ml.historical_p == pytest.approx(0.704)
    assert rl.historical_p == pytest.approx(0.806)


# ---------------------------------------------------------------------------
# Tier 2 — bullpen fatigue gap
# ---------------------------------------------------------------------------


def test_tier2_fires_on_workload_gap_and_rested_away_bp():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            bp_ip_3d_home=12.0,
            bp_ip_3d_away=4.0,  # gap=8
        )
    )
    picks = find_tier2_picks(df, TODAY)
    assert len(picks) == 1
    assert picks[0].market == "RL_+1.5"
    assert picks[0].side == "away"
    assert picks[0].tier == "tier2_fatigue_gap"


def test_tier2_skipped_when_workload_gap_below_3():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            bp_ip_3d_home=8.0,
            bp_ip_3d_away=6.0,  # gap=2
        )
    )
    assert find_tier2_picks(df, TODAY) == []


def test_tier2_skipped_when_away_bp_too_busy():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            bp_ip_3d_home=12.0,
            bp_ip_3d_away=8.0,  # gap=4 OK, but away >7
        )
    )
    assert find_tier2_picks(df, TODAY) == []


def test_tier2_skipped_on_bullpen_day():
    """Tier 1 owns the bullpen-day case; Tier 2 must not double-fire."""
    df = _frame(
        _row(
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            bp_ip_3d_home=12.0,
            bp_ip_3d_away=4.0,
        )
    )
    assert find_tier2_picks(df, TODAY) == []


def test_tier2_skipped_when_away_is_fav():
    df = _frame(
        _row(
            home_implied_prob=0.40,
            away_implied_prob=0.62,
            bp_ip_3d_home=12.0,
            bp_ip_3d_away=4.0,
        )
    )
    assert find_tier2_picks(df, TODAY) == []


# ---------------------------------------------------------------------------
# Tier 3 — pitcher advantage (short window per Decision §9.1)
# ---------------------------------------------------------------------------


def test_tier3_fires_on_quality_away_starter_and_tired_home_bp():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            away_sp_fip_short=3.20,
            home_sp_ip_per_start_short=5.0,
            away_sp_ip_per_start_short=6.5,  # depth_diff_short = -1.5
            bp_ip_3d_home=10.0,
        )
    )
    picks = find_tier3_picks(df, TODAY)
    assert len(picks) == 1
    assert picks[0].market == "RL_+1.5"
    assert picks[0].historical_p == pytest.approx(0.790)


def test_tier3_skipped_when_away_fip_too_high():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            away_sp_fip_short=4.00,  # > 3.5
            home_sp_ip_per_start_short=5.0,
            away_sp_ip_per_start_short=6.5,
            bp_ip_3d_home=10.0,
        )
    )
    assert find_tier3_picks(df, TODAY) == []


def test_tier3_skipped_when_depth_advantage_too_small():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            away_sp_fip_short=3.20,
            home_sp_ip_per_start_short=5.5,
            away_sp_ip_per_start_short=6.0,  # depth_diff_short = -0.5 > -1.0
            bp_ip_3d_home=10.0,
        )
    )
    assert find_tier3_picks(df, TODAY) == []


def test_tier3_skipped_when_home_bp_fresh():
    df = _frame(
        _row(
            home_implied_prob=0.62,
            away_implied_prob=0.42,
            away_sp_fip_short=3.20,
            home_sp_ip_per_start_short=5.0,
            away_sp_ip_per_start_short=6.5,
            bp_ip_3d_home=4.0,  # < 8
        )
    )
    assert find_tier3_picks(df, TODAY) == []


# ---------------------------------------------------------------------------
# Fav -1.5 RL
# ---------------------------------------------------------------------------


def test_fav_rl_fires_for_home_fav_with_pitching_and_attack_edge():
    df = _frame(
        _row(
            home_implied_prob=0.68,
            away_implied_prob=0.36,
            home_sp_fip_short=3.30,
            away_sp_fip_short=4.00,  # fav_fip_diff = -0.7
            power_rate_home=0.45,
            power_rate_away=0.40,    # fav_power_diff = +0.05
        )
    )
    picks = find_fav_rl_picks(df, TODAY)
    assert len(picks) == 1
    assert picks[0].market == "RL_-1.5"
    assert picks[0].side == "home"
    assert picks[0].historical_p == pytest.approx(0.498)


def test_fav_rl_fires_for_away_fav():
    df = _frame(
        _row(
            home_implied_prob=0.36,
            away_implied_prob=0.68,
            home_sp_fip_short=4.00,
            away_sp_fip_short=3.30,  # fav_fip_diff = -0.7 (away fav)
            power_rate_home=0.40,
            power_rate_away=0.45,    # fav_power_diff = +0.05
        )
    )
    picks = find_fav_rl_picks(df, TODAY)
    assert len(picks) == 1
    assert picks[0].side == "away"


def test_fav_rl_skipped_below_impl_band():
    df = _frame(
        _row(
            home_implied_prob=0.55,  # < 0.62
            away_implied_prob=0.48,
            home_sp_fip_short=3.30,
            away_sp_fip_short=4.00,
        )
    )
    assert find_fav_rl_picks(df, TODAY) == []


def test_fav_rl_skipped_above_impl_band():
    df = _frame(
        _row(
            home_implied_prob=0.80,  # >= 0.75
            away_implied_prob=0.25,
            home_sp_fip_short=3.30,
            away_sp_fip_short=4.00,
        )
    )
    assert find_fav_rl_picks(df, TODAY) == []


def test_fav_rl_skipped_when_fav_has_worse_fip():
    df = _frame(
        _row(
            home_implied_prob=0.68,
            away_implied_prob=0.36,
            home_sp_fip_short=4.20,
            away_sp_fip_short=3.50,  # fav_fip_diff = +0.7 > -0.2
            power_rate_home=0.45,
            power_rate_away=0.40,
        )
    )
    assert find_fav_rl_picks(df, TODAY) == []


def test_fav_rl_skipped_when_fav_lacks_attack():
    df = _frame(
        _row(
            home_implied_prob=0.68,
            away_implied_prob=0.36,
            home_sp_fip_short=3.30,
            away_sp_fip_short=4.00,
            power_rate_home=0.35,
            power_rate_away=0.45,    # fav_power_diff = -0.10 < 0
        )
    )
    assert find_fav_rl_picks(df, TODAY) == []


# ---------------------------------------------------------------------------
# Pick.make / pick_id stability
# ---------------------------------------------------------------------------


def test_pick_id_stable_across_runs():
    """Same inputs must produce the same pick_id (idempotent re-runs)."""
    p1 = Pick.make(
        target_date=TODAY,
        away="BAL",
        home="TOR",
        market="ML_dog",
        side="away",
        tier="tier1_bullpen_day",
        historical_p=0.742,
        ref_odds_espn=2.0,
        reason="test",
        feature_snapshot={},
    )
    p2 = Pick.make(
        target_date=TODAY,
        away="BAL",
        home="TOR",
        market="ML_dog",
        side="away",
        tier="tier1_bullpen_day",
        historical_p=0.742,
        ref_odds_espn=2.0,
        reason="test",
        feature_snapshot={},
    )
    assert p1.pick_id == p2.pick_id
    assert len(p1.pick_id) == 12


def test_pick_id_changes_with_market():
    p1 = Pick.make(
        target_date=TODAY, away="BAL", home="TOR", market="ML_dog", side="away",
        tier="tier1_bullpen_day", historical_p=0.742, ref_odds_espn=2.0,
        reason="", feature_snapshot={},
    )
    p2 = Pick.make(
        target_date=TODAY, away="BAL", home="TOR", market="RL_+1.5", side="away",
        tier="tier1_bullpen_day", historical_p=0.837, ref_odds_espn=1.6,
        reason="", feature_snapshot={},
    )
    assert p1.pick_id != p2.pick_id


# ---------------------------------------------------------------------------
# Multiple games
# ---------------------------------------------------------------------------


def test_strategies_handle_multiple_games_in_one_day():
    df = _frame(
        _row(
            away_team="BAL", home_team="TOR",
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.70, away_implied_prob=0.34,  # Case A
        ),
        _row(
            away_team="NYM", home_team="BOS",
            home_is_bullpen_no_starter=True,
            home_implied_prob=0.45, away_implied_prob=0.60,  # Case B (flipped)
        ),
        _row(
            away_team="STL", home_team="MIL",
            home_is_bullpen_no_starter=False,  # not a Tier 1 game
            home_implied_prob=0.60, away_implied_prob=0.42,
        ),
    )
    picks = find_tier1_picks(df, TODAY)
    # BAL@TOR: Case A -> 2 picks (ML + RL), NYM@BOS: Case B -> 1 pick (RL only)
    assert len(picks) == 3
    assert {p.away for p in picks} == {"BAL", "NYM"}
    bal_picks = [p for p in picks if p.away == "BAL"]
    nym_picks = [p for p in picks if p.away == "NYM"]
    assert len(bal_picks) == 2  # ML + RL
    assert len(nym_picks) == 1  # RL only
    assert nym_picks[0].tier == "tier1_bullpen_day_flipped"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
