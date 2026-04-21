"""Live Savant refresh wrapper for the 2026 MLB runtime."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from data.fetch_savant_gamelogs import refresh_season_to_date
from data.fetch_2026.io_safety import append_audit, atomic_write_text
from data.fetch_2026.runtime_files import state_path
from src.savant_bullpen import (
    SAVANT_DIR,
    build_savant_bullpen_features,
    discover_available_seasons,
    save_savant_bullpen_features,
)

SAVANT_PITCHER_GAMES_PATH = SAVANT_DIR / "pitcher_games_2026.parquet"
SAVANT_BULLPEN_FEATURES_PATH = SAVANT_DIR / "savant_bullpen_features.parquet"


def _read_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    atomic_write_text(json.dumps(state, indent=2, default=str), state_path())


def _max_date(path: Path, date_col: str) -> date | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=[date_col])
    if df.empty or date_col not in df.columns:
        return None
    values = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if values.empty:
        return None
    return values.max().date()


def validate_live_savant(expected_date: date) -> dict[str, Any]:
    pitcher_max = _max_date(SAVANT_PITCHER_GAMES_PATH, "game_date")
    bullpen_max = _max_date(SAVANT_BULLPEN_FEATURES_PATH, "game_date")
    return {
        "expected_date": expected_date.isoformat(),
        "pitcher_max_date": pitcher_max.isoformat() if pitcher_max else None,
        "bullpen_max_date": bullpen_max.isoformat() if bullpen_max else None,
        "ok": pitcher_max == expected_date and bullpen_max == expected_date,
    }


def _advance_savant_state(
    *,
    refresh_date: date,
    data_date: date,
) -> None:
    state = _read_state()
    state["last_savant_refresh_date"] = refresh_date.isoformat()
    state["last_savant_data_date"] = data_date.isoformat()
    state["last_savant_date"] = data_date.isoformat()
    _write_state(state)


def refresh_live_savant(
    through: date,
    *,
    recent_backfill_days: int = 3,
) -> dict[str, Any]:
    """Refresh live 2026 Savant data and validate written max dates."""
    pitcher_games = refresh_season_to_date(
        2026,
        through=through,
        recent_backfill_days=recent_backfill_days,
    )
    features = build_savant_bullpen_features()
    source_seasons = discover_available_seasons()
    save_savant_bullpen_features(features, source_seasons=source_seasons)

    validation = validate_live_savant(through)
    if not validation["ok"]:
        raise ValueError(
            "Live Savant validation failed: "
            f"expected={validation['expected_date']} "
            f"pitcher_max={validation['pitcher_max_date']} "
            f"bullpen_max={validation['bullpen_max_date']}"
        )

    _advance_savant_state(refresh_date=date.today(), data_date=through)
    append_audit(
        "savant_refresh",
        target_date=through,
        rows_total=len(pitcher_games),
        files_written=[
            SAVANT_PITCHER_GAMES_PATH.name,
            SAVANT_BULLPEN_FEATURES_PATH.name,
        ],
        extra={
            "pitcher_rows": int(len(pitcher_games)),
            "pitcher_max_date": validation["pitcher_max_date"],
            "bullpen_rows": int(len(features)),
            "bullpen_max_date": validation["bullpen_max_date"],
            "recent_backfill_days": int(recent_backfill_days),
            "source_seasons": source_seasons,
        },
    )
    return {
        "through": through.isoformat(),
        "pitcher_rows": int(len(pitcher_games)),
        "pitcher_max_date": validation["pitcher_max_date"],
        "bullpen_rows": int(len(features)),
        "bullpen_max_date": validation["bullpen_max_date"],
        "source_seasons": source_seasons,
    }
