from __future__ import annotations

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest

from src.features import calc_streaks

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "streak_ml_edge_discovery.py"
)
SPEC = spec_from_file_location("streak_ml_edge_discovery", MODULE_PATH)
assert SPEC and SPEC.loader
streak_ml_edge_discovery = module_from_spec(SPEC)
sys.modules[SPEC.name] = streak_ml_edge_discovery
SPEC.loader.exec_module(streak_ml_edge_discovery)


def test_calc_streaks_uses_entering_game_semantics_and_resets_each_season():
    log = pd.DataFrame(
        [
            {
                "team": "AAA",
                "season": 2024,
                "date": pd.Timestamp("2024-04-01"),
                "won": True,
            },
            {
                "team": "AAA",
                "season": 2024,
                "date": pd.Timestamp("2024-04-02"),
                "won": True,
            },
            {
                "team": "AAA",
                "season": 2024,
                "date": pd.Timestamp("2024-04-03"),
                "won": False,
            },
            {
                "team": "AAA",
                "season": 2025,
                "date": pd.Timestamp("2025-04-01"),
                "won": True,
            },
        ]
    )

    out = calc_streaks(log).sort_values(["season", "date"]).reset_index(drop=True)

    assert out["signed_streak"].tolist() == [0, 1, 2, 0]


def test_normalize_team_side_frame_maps_home_and_away_fields_correctly():
    enriched = pd.DataFrame(
        [
            {
                "season": 2024,
                "date": pd.Timestamp("2024-06-15"),
                "home_team": "BOS",
                "away_team": "NYY",
                "home_win": True,
                "home_decimal_odds": 1.80,
                "away_decimal_odds": 2.15,
                "home_implied_prob": 0.56,
                "away_implied_prob": 0.44,
                "streak_home": 3,
                "streak_away": -2,
                "wp_last3_home": 1.00,
                "wp_last3_away": 0.00,
                "wp_last6_home": 0.667,
                "wp_last6_away": 0.333,
                "elo_diff": 12.0,
                "rpi_diff": 0.08,
                "streak_diff": 5,
                "is_september": False,
                "is_extreme_line": False,
                "involves_col": False,
            }
        ]
    )

    out = streak_ml_edge_discovery.normalize_team_side_frame(enriched)
    assert len(out) == 2

    home = out[out["team"] == "BOS"].iloc[0]
    away = out[out["team"] == "NYY"].iloc[0]

    assert bool(home["team_is_home"]) is True
    assert bool(home["team_won"]) is True
    assert bool(home["team_is_favorite"]) is True
    assert home["team_signed_streak"] == 3
    assert home["opp_signed_streak"] == -2
    assert home["wp_last6_bucket"] == ">=.500"
    assert home["opp_streak_bucket"] == "opp_cold"
    assert home["season_phase"] == "Jun-Jul"

    assert bool(away["team_is_home"]) is False
    assert bool(away["team_won"]) is False
    assert bool(away["team_is_favorite"]) is False
    assert away["team_signed_streak"] == -2
    assert away["opp_signed_streak"] == 3
    assert away["wp_last6_bucket"] == "<.500"
    assert away["opp_streak_bucket"] == "opp_hot"
    assert away["season_phase"] == "Jun-Jul"


def test_pnl_helpers_handle_back_and_fade_cases():
    assert streak_ml_edge_discovery.back_team_pnl(True, 2.40) == pytest.approx(1.40)
    assert streak_ml_edge_discovery.back_team_pnl(False, 2.40) == pytest.approx(-1.0)
    assert streak_ml_edge_discovery.fade_team_pnl(True, 1.85) == pytest.approx(-1.0)
    assert streak_ml_edge_discovery.fade_team_pnl(False, 1.85) == pytest.approx(0.85)


def test_run_analysis_short_window_writes_outputs_and_hits_headline_checks(tmp_path):
    artifact = tmp_path / "streak_ml_edge_discovery.json"
    report = tmp_path / "session_report_42_streak_ml.md"

    out = streak_ml_edge_discovery.run_analysis(
        season_min=2022,
        season_max=2025,
        discovery_start=2022,
        discovery_end=2023,
        test_season=2024,
        live_season=2025,
        artifact_path=artifact,
        report_path=report,
    )

    assert artifact.exists()
    assert report.exists()
    data = json.loads(artifact.read_text(encoding="utf-8"))
    assert set(data) == {
        "meta",
        "raw_tables",
        "pricing_tables",
        "candidate_filters",
        "validation",
        "verdict",
    }

    headline_raw = {
        row["bucket"]: row for row in data["raw_tables"]["main"]["threshold"]
    }
    headline_pricing = {
        row["bucket"]: row
        for row in data["pricing_tables"]["main"]["overall"]["threshold"]
    }

    assert headline_raw["W3+"]["win_rate"] > 0.50
    assert headline_raw["L3+"]["win_rate"] < 0.50
    assert headline_pricing["W3+"]["back_roi"] < 0
    assert headline_pricing["L3+"]["fade_roi"] < 0
    assert 2026 not in data["meta"]["loaded_seasons"]

    report_text = report.read_text(encoding="utf-8")
    assert "Session 42 -- Streak ML Momentum" in report_text
    assert out["verdict"]["pricing_verdict"]["main_W3_plus"]["back_roi"] < 0
