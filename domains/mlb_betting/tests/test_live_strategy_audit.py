from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from data.fetch_2026.mlb_boxscore import build_live_starter_entering_features
from src.live_strategy_audit import evaluate_strategy_day
from src.live_feature_forward import _fill_pitcher_features_from_parquet


def _starter_row(
    gid: str,
    season: int,
    dt: str,
    pitcher_id: str,
    *,
    outs: int,
    h: int,
    bb: int,
    so: int,
    er: int,
    hr: int,
    team: str = "BOS",
    opponent: str = "DET",
    is_home: bool = True,
) -> dict:
    return {
        "gid": gid,
        "season": season,
        "date": pd.Timestamp(dt),
        "game_num": 0,
        "home_team": team if is_home else opponent,
        "away_team": opponent if is_home else team,
        "team": team,
        "is_home": is_home,
        "opponent": opponent,
        "pitcher_id": pitcher_id,
        "outs": outs,
        "ip": outs / 3.0,
        "h": h,
        "bb": bb,
        "so": so,
        "er": er,
        "hr": hr,
    }


def test_build_live_starter_entering_features_carries_historical_starts():
    historical = pd.DataFrame(
        [
            _starter_row("H1", 2025, "2025-09-20", "retro1", outs=15, h=4, bb=1, so=6, er=2, hr=1),
            _starter_row("H2", 2025, "2025-09-27", "retro1", outs=18, h=5, bb=2, so=7, er=1, hr=0),
        ]
    )
    live = pd.DataFrame(
        [
            _starter_row("MLB1", 2026, "2026-03-28", "1001", outs=18, h=6, bb=2, so=5, er=3, hr=1),
        ]
    )
    bridge = pd.DataFrame({"key_retro": ["retro1"], "key_mlbam": ["1001"]})

    entering = build_live_starter_entering_features(
        live,
        historical_starter_logs=historical,
        id_bridge=bridge,
    )

    seed = entering.loc[entering["gid"] == "SEED2026_1001"].iloc[0]
    actual = entering.loc[entering["gid"] == "MLB1"].iloc[0]

    assert seed["starts_prior"] == 2
    assert pd.notna(seed["fip_short"])
    assert pd.notna(seed["ip_per_start_short"])
    assert bool(seed["starter_history_bridge_missing"]) is False

    assert actual["starts_prior"] == 2
    assert pd.notna(actual["fip_short"])
    assert pd.notna(actual["ip_per_start_short"])
    assert bool(actual["starter_history_bridge_missing"]) is False


def test_build_live_starter_entering_features_marks_unmapped_pitchers():
    live = pd.DataFrame(
        [
            _starter_row("MLB2", 2026, "2026-03-30", "2002", outs=15, h=5, bb=1, so=4, er=2, hr=1),
        ]
    )

    entering = build_live_starter_entering_features(
        live,
        historical_starter_logs=pd.DataFrame(),
        id_bridge=pd.DataFrame(),
    )

    row = entering.iloc[0]
    assert row["starts_prior"] == 0
    assert bool(row["starter_history_bridge_missing"]) is True


def test_fill_pitcher_features_marks_bridge_missing_when_no_latest_row(
    monkeypatch: pytest.MonkeyPatch,
):
    target = date(2026, 4, 17)
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp(target),
                "home_team": "BOS",
                "away_team": "DET",
                "home_pitcher": "Pitcher One-R",
                "away_pitcher": "Pitcher Two-R",
            }
        ]
    )

    monkeypatch.setattr(
        "src.live_feature_forward._load_latest_starter_features",
        lambda dt: (
            pd.DataFrame(
                [{"pitcher_id": "9999", "starter_history_bridge_missing": False}]
            ).set_index("pitcher_id"),
            {"Pitcher One-R": "1001"},
        ),
    )

    fills = _fill_pitcher_features_from_parquet(frame, target)

    assert fills == {}
    assert frame.loc[0, "home_starter_id"] == "1001"
    assert bool(frame.loc[0, "starter_history_bridge_missing_home"]) is True
    assert bool(frame.loc[0, "starter_history_bridge_missing_away"]) is False


def test_evaluate_strategy_day_marks_strict_but_ready():
    day = pd.DataFrame(
        [
            {
                "fav_is_home": True,
                "away_close_ml": 130,
                "home_is_bullpen_no_starter": False,
                "away_is_bullpen_no_starter": False,
                "starter_depth_diff_short": -1.1,
                "bp_ip_3d_home": 9.0,
                "effective_obp_away": 0.340,
                "bp_sc_xwoba_std_home": 0.240,
                "starter_feature_source_missing": False,
                "lineup_feature_source_missing": False,
                "insufficient_starter_history": False,
                "insufficient_lineup_history": False,
                "starter_history_bridge_missing": False,
            }
        ]
    )

    info = evaluate_strategy_day(day, "tier4_ml_depth_load")
    assert info["usable_rows"] == 1
    assert info["raw_pass"] == 0
    assert info["verdict"] == "strict_but_ready"


def test_evaluate_strategy_day_marks_warmup_sparse():
    day = pd.DataFrame(
        [
            {
                "fav_is_home": True,
                "away_close_ml": 130,
                "home_is_bullpen_no_starter": False,
                "away_is_bullpen_no_starter": False,
                "starter_depth_diff_short": pd.NA,
                "bp_ip_3d_home": 9.0,
                "effective_obp_away": 0.340,
                "bp_sc_xwoba_std_home": 0.300,
                "starter_feature_source_missing": False,
                "lineup_feature_source_missing": False,
                "insufficient_starter_history": True,
                "insufficient_lineup_history": False,
                "starter_history_bridge_missing": True,
            },
            {
                "fav_is_home": True,
                "away_close_ml": 130,
                "home_is_bullpen_no_starter": False,
                "away_is_bullpen_no_starter": False,
                "starter_depth_diff_short": pd.NA,
                "bp_ip_3d_home": 9.0,
                "effective_obp_away": 0.340,
                "bp_sc_xwoba_std_home": 0.300,
                "starter_feature_source_missing": False,
                "lineup_feature_source_missing": False,
                "insufficient_starter_history": True,
                "insufficient_lineup_history": False,
                "starter_history_bridge_missing": True,
            },
            {
                "fav_is_home": True,
                "away_close_ml": 130,
                "home_is_bullpen_no_starter": False,
                "away_is_bullpen_no_starter": False,
                "starter_depth_diff_short": -1.1,
                "bp_ip_3d_home": 9.0,
                "effective_obp_away": 0.340,
                "bp_sc_xwoba_std_home": 0.300,
                "starter_feature_source_missing": False,
                "lineup_feature_source_missing": False,
                "insufficient_starter_history": False,
                "insufficient_lineup_history": False,
                "starter_history_bridge_missing": False,
            },
        ]
    )

    info = evaluate_strategy_day(day, "tier4_ml_depth_load")
    assert info["usable_rows"] == 1
    assert info["verdict"] == "warmup_sparse"
