from __future__ import annotations

from datetime import date

import pandas as pd

from data import fetch_savant_gamelogs
from src.savant_bullpen import build_savant_bullpen_features


def _pitch_row(
    *,
    pitcher: int,
    game_pk: int,
    game_date: str,
    inning: int,
    desc: str = "swinging_strike",
    launch_speed: float | None = None,
    launch_speed_angle: int | None = None,
    xwoba: float | None = None,
) -> dict:
    return {
        "pitcher": pitcher,
        "game_pk": game_pk,
        "game_date": game_date,
        "inning_topbot": "Top",
        "home_team": "BOS",
        "away_team": "DET",
        "description": desc,
        "launch_speed": launch_speed,
        "launch_speed_angle": launch_speed_angle,
        "estimated_woba_using_speedangle": xwoba,
        "pitch_type": "FF",
        "inning": inning,
        "player_name": "Pitcher One",
    }


def test_refresh_season_to_date_upserts_recent_window(
    monkeypatch,
    tmp_path,
):
    out_path = tmp_path / "pitcher_games_2026.parquet"
    existing = pd.DataFrame(
        [
            {
                "pitcher": 1,
                "game_pk": 100,
                "game_date": pd.Timestamp("2026-04-10"),
                "pitcher_team": "BOS",
                "total_pitches": 10,
                "swings": 5,
                "whiffs": 2,
                "batted_balls": 1,
                "hard_hits": 0,
                "barrels": 0,
                "home_team": "BOS",
                "away_team": "DET",
                "player_name": "Pitcher One",
                "is_starter": True,
                "whiff_pct": 0.4,
                "hard_hit_pct": 0.0,
                "barrel_pct": 0.0,
                "xwoba": 0.3,
                "avg_exit_velo": 91.0,
                "season": 2026,
            }
        ]
    )
    existing.to_parquet(out_path, index=False)
    monkeypatch.setattr(fetch_savant_gamelogs, "OUTPUT_DIR", tmp_path)

    calls = []

    def fake_statcast(start_dt: str, end_dt: str):
        calls.append((start_dt, end_dt))
        return pd.DataFrame(
            [
                _pitch_row(pitcher=1, game_pk=100, game_date="2026-04-10", inning=1),
                _pitch_row(
                    pitcher=2,
                    game_pk=101,
                    game_date="2026-04-12",
                    inning=1,
                    desc="hit_into_play",
                    launch_speed=100.0,
                    launch_speed_angle=6,
                    xwoba=0.75,
                ),
            ]
        )

    monkeypatch.setattr(fetch_savant_gamelogs.pybaseball, "statcast", fake_statcast)

    result = fetch_savant_gamelogs.refresh_season_to_date(
        2026,
        through=date(2026, 4, 12),
        recent_backfill_days=3,
    )

    assert calls == [("2026-04-08", "2026-04-12")]
    assert set(result["game_pk"]) == {100, 101}
    assert len(result) == 2
    saved = pd.read_parquet(out_path)
    assert set(saved["game_pk"]) == {100, 101}


def test_build_savant_bullpen_features_discovers_2026(tmp_path):
    rows_2025 = pd.DataFrame(
        [
            {
                "pitcher": 10,
                "game_pk": 500,
                "game_date": pd.Timestamp("2025-09-20"),
                "pitcher_team": "BOS",
                "total_pitches": 12,
                "swings": 6,
                "whiffs": 2,
                "batted_balls": 2,
                "hard_hits": 1,
                "barrels": 0,
                "xwoba": 0.31,
                "avg_exit_velo": 92.0,
                "is_starter": False,
            }
        ]
    )
    rows_2026 = pd.DataFrame(
        [
            {
                "pitcher": 11,
                "game_pk": 600,
                "game_date": pd.Timestamp("2026-04-19"),
                "pitcher_team": "DET",
                "total_pitches": 14,
                "swings": 7,
                "whiffs": 3,
                "batted_balls": 3,
                "hard_hits": 1,
                "barrels": 1,
                "xwoba": 0.35,
                "avg_exit_velo": 94.0,
                "is_starter": False,
            }
        ]
    )
    rows_2025.to_parquet(tmp_path / "pitcher_games_2025.parquet", index=False)
    rows_2026.to_parquet(tmp_path / "pitcher_games_2026.parquet", index=False)

    features = build_savant_bullpen_features(savant_dir=tmp_path)

    assert 2026 in features.attrs["source_seasons"]
    assert pd.to_datetime(features["game_date"]).max().date().year == 2026
