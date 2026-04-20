from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_repeat_series_signal_analysis.py"
)
SPEC = spec_from_file_location("run_repeat_series_signal_analysis", MODULE_PATH)
assert SPEC and SPEC.loader
repeat_series_signal_analysis = module_from_spec(SPEC)
sys.modules[SPEC.name] = repeat_series_signal_analysis
SPEC.loader.exec_module(repeat_series_signal_analysis)


def _game_row(
    *,
    season: int = 2025,
    game_date: str = "2025-04-01",
    away_team: str = "STL",
    home_team: str = "HOU",
    away_implied_prob: float = 0.45,
    home_implied_prob: float = 0.55,
    away_close_ml: float = 122,
    home_close_ml: float = -132,
    away_decimal_odds: float = 2.22,
    home_decimal_odds: float = 1.76,
    away_streak: float = 1.0,
    home_streak: float = -1.0,
    away_wp_last10: float = 0.6,
    home_wp_last10: float = 0.4,
) -> dict:
    return {
        "season": season,
        "date": pd.Timestamp(game_date),
        "away_team": away_team,
        "home_team": home_team,
        "away_implied_prob": away_implied_prob,
        "home_implied_prob": home_implied_prob,
        "away_close_ml": away_close_ml,
        "home_close_ml": home_close_ml,
        "away_decimal_odds": away_decimal_odds,
        "home_decimal_odds": home_decimal_odds,
        "away_run_line_odds": 1.91,
        "home_run_line_odds": 1.91,
        "away_sp_fip_short": 3.3,
        "home_sp_fip_short": 4.1,
        "away_sp_ip_per_start_short": 5.8,
        "home_sp_ip_per_start_short": 5.0,
        "bp_ip_3d_away": 4.0,
        "bp_ip_3d_home": 8.0,
        "bp_fip_short_away": 3.8,
        "bp_fip_short_home": 4.3,
        "bp_fip_7g_away": 3.9,
        "bp_fip_7g_home": 4.5,
        "streak_away": away_streak,
        "streak_home": home_streak,
        "wp_last3_away": 0.667,
        "wp_last3_home": 0.333,
        "wp_last6_away": 0.667,
        "wp_last6_home": 0.333,
        "wp_last10_away": away_wp_last10,
        "wp_last10_home": home_wp_last10,
        "rpg_last10_away": 5.3,
        "rpg_last10_home": 4.2,
        "rapg_last10_away": 3.6,
        "rapg_last10_home": 4.9,
        "rpi_away": 0.56,
        "rpi_home": 0.47,
    }


def _signal_row(
    *,
    game_index: int,
    game_date: str,
    team: str = "STL",
    opponent: str = "HOU",
    tier: str = "tier2_fatigue_gap",
    market: str = "RL_+1.5",
    market_family: str = "RL",
    flat_return: float = 0.91,
    won: bool = True,
    decimal_odds: float = 1.91,
    series_key: str = "2025_2025-04-01_HOU_STL",
    game_in_series: int = 1,
) -> dict:
    return {
        "season": 2025,
        "date": pd.Timestamp(game_date),
        "game_index": game_index,
        "series_key": series_key,
        "series_start_date": "2025-04-01",
        "game_in_series": game_in_series,
        "series_length": 3,
        "away_team": "STL",
        "home_team": "HOU",
        "team": team,
        "opponent": opponent,
        "team_is_home": False,
        "tier": tier,
        "market": market,
        "market_family": market_family,
        "side": "away",
        "decimal_odds": decimal_odds,
        "implied_prob": 1 / decimal_odds,
        "won": won,
        "result_label": "win" if won else "loss",
        "flat_return": flat_return,
        "historical_p": 0.72,
        "pick_id": f"{game_index}-{tier}",
        "reason": tier,
    }


def _team_signal_row(
    *,
    game_in_series: int,
    signal_result: str,
    signal_roi: float,
    signal_market_family: str = "RL",
    signal_tiers: list[str] | None = None,
    support_count: int = 1,
    season: int = 2025,
    series_key: str = "2025_2025-04-01_HOU_STL",
    team_wp_last10: float = 0.55,
    opp_wp_last10: float = 0.45,
    team_implied_prob: float = 0.44,
    signal_decimal_odds: float = 1.91,
) -> dict:
    tiers = signal_tiers or ["tier2_fatigue_gap"]
    return {
        "season": season,
        "date": pd.Timestamp("2025-04-01") + pd.Timedelta(days=game_in_series - 1),
        "game_index": game_in_series - 1,
        "series_key": series_key,
        "series_start_date": "2025-04-01",
        "game_in_series": game_in_series,
        "series_length": 3,
        "team": "STL",
        "opponent": "HOU",
        "team_is_home": False,
        "away_team": "STL",
        "home_team": "HOU",
        "signal_market_family": signal_market_family,
        "signal_markets": ["RL_+1.5"],
        "signal_tiers": tiers,
        "support_count": support_count,
        "raw_pick_count": support_count,
        "signal_result": signal_result,
        "signal_roi": signal_roi,
        "signal_decimal_odds": signal_decimal_odds,
        "signal_implied_prob": 1 / signal_decimal_odds,
        "signal_hit_rate": 1.0 if signal_result == "win" else 0.0,
        "team_is_favorite": 0.0,
        "team_close_ml": 125.0,
        "opp_close_ml": -135.0,
        "team_implied_prob": team_implied_prob,
        "opp_implied_prob": 1.0 - team_implied_prob,
        "team_decimal_odds": 2.25,
        "opp_decimal_odds": 1.74,
        "team_wp_last10": team_wp_last10,
        "opp_wp_last10": opp_wp_last10,
        "diff_wp_last10": team_wp_last10 - opp_wp_last10,
        "team_streak": 1.0,
        "opp_streak": -1.0,
        "diff_streak": 2.0,
    }


def test_synthetic_series_emits_one_g1_to_g2_transition():
    team_rows = pd.DataFrame(
        [
            _team_signal_row(game_in_series=1, signal_result="win", signal_roi=0.91),
            _team_signal_row(game_in_series=2, signal_result="loss", signal_roi=-1.0),
        ]
    )

    transitions = repeat_series_signal_analysis.build_repeat_transitions(team_rows)

    assert len(transitions) == 1
    assert transitions.iloc[0]["from_game"] == 1
    assert transitions.iloc[0]["to_game"] == 2


def test_multi_tier_same_game_collapses_to_one_team_row():
    games = pd.DataFrame(
        [
            _game_row(),
        ]
    )
    signal_rows = pd.DataFrame(
        [
            _signal_row(
                game_index=0,
                game_date="2025-04-01",
                tier="tier2_fatigue_gap",
                flat_return=0.91,
                won=True,
            ),
            _signal_row(
                game_index=0,
                game_date="2025-04-01",
                tier="tier3_pitcher_advantage",
                flat_return=0.91,
                won=True,
            ),
        ]
    )

    collapsed = repeat_series_signal_analysis.collapse_team_level_signals(signal_rows, games)

    assert len(collapsed) == 1
    assert collapsed.iloc[0]["support_count"] == 2
    assert collapsed.iloc[0]["signal_tiers"] == [
        "tier2_fatigue_gap",
        "tier3_pitcher_advantage",
    ]


def test_prior_result_buckets_keep_win_and_loss_paths_separate():
    team_rows = pd.DataFrame(
        [
            _team_signal_row(
                game_in_series=1,
                signal_result="win",
                signal_roi=0.91,
                series_key="series-win",
            ),
            _team_signal_row(
                game_in_series=2,
                signal_result="win",
                signal_roi=0.91,
                series_key="series-win",
            ),
            _team_signal_row(
                game_in_series=1,
                signal_result="loss",
                signal_roi=-1.0,
                series_key="series-loss",
            ),
            _team_signal_row(
                game_in_series=2,
                signal_result="win",
                signal_roi=0.91,
                series_key="series-loss",
            ),
        ]
    )

    transitions = repeat_series_signal_analysis.build_repeat_transitions(team_rows)

    assert set(transitions["first_signal_result"]) == {"win", "loss"}
    assert int((transitions["first_signal_result"] == "win").sum()) == 1
    assert int((transitions["first_signal_result"] == "loss").sum()) == 1


def test_market_result_math_for_ml_and_rl():
    ml = repeat_series_signal_analysis.evaluate_pick_result(
        market="ML_dog",
        side="away",
        decimal_odds=2.40,
        home_final=3,
        away_final=5,
    )
    rl = repeat_series_signal_analysis.evaluate_pick_result(
        market="RL_+1.5",
        side="away",
        decimal_odds=1.91,
        home_final=4,
        away_final=3,
    )

    assert ml["won"] is True
    assert ml["flat_return"] == pytest.approx(1.40)
    assert rl["won"] is True
    assert rl["flat_return"] == pytest.approx(0.91)


def test_feature_deltas_use_second_game_minus_prior_game_without_leakage():
    team_rows = pd.DataFrame(
        [
            _team_signal_row(
                game_in_series=1,
                signal_result="win",
                signal_roi=0.91,
                team_wp_last10=0.50,
                opp_wp_last10=0.60,
                team_implied_prob=0.42,
                signal_decimal_odds=2.00,
            ),
            _team_signal_row(
                game_in_series=2,
                signal_result="win",
                signal_roi=0.91,
                team_wp_last10=0.60,
                opp_wp_last10=0.55,
                team_implied_prob=0.46,
                signal_decimal_odds=1.95,
            ),
            _team_signal_row(
                game_in_series=3,
                signal_result="loss",
                signal_roi=-1.0,
                team_wp_last10=0.40,
                opp_wp_last10=0.70,
                team_implied_prob=0.38,
                signal_decimal_odds=2.15,
            ),
        ]
    )

    transitions = repeat_series_signal_analysis.build_repeat_transitions(team_rows)

    first = transitions.iloc[0]
    second = transitions.iloc[1]

    assert first["delta_team_wp_last10"] == pytest.approx(0.10)
    assert first["delta_opp_wp_last10"] == pytest.approx(-0.05)
    assert first["delta_diff_wp_last10"] == pytest.approx(0.15)
    assert first["delta_team_implied_prob"] == pytest.approx(0.04)
    assert first["delta_signal_decimal_odds"] == pytest.approx(-0.05)

    assert second["delta_team_wp_last10"] == pytest.approx(-0.20)
    assert second["delta_diff_wp_last10"] == pytest.approx(-0.35)


def test_tier4_loader_supports_pyc_fallback_when_source_missing():
    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "strategies"
        / "tier4_ml_depth_load.py"
    )
    module, loaded_from = repeat_series_signal_analysis.load_strategy_module(
        "src.strategies.tier4_ml_depth_load"
    )

    assert hasattr(module, "find_picks")
    if not source_path.exists():
        assert loaded_from.endswith(".pyc")
