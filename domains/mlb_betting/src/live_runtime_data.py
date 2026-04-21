"""Shared target-day frame builder and completeness diagnostics for live runs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def _game_keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    if frame.empty or not {"away_team", "home_team"}.issubset(frame.columns):
        return set()
    pairs = frame[["away_team", "home_team"]].drop_duplicates()
    return {
        (str(row.away_team), str(row.home_team))
        for row in pairs.itertuples(index=False)
    }


def _day_slice(frame: pd.DataFrame, target: date) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    first = frame["date"].iloc[0]
    if hasattr(first, "date"):
        return frame[frame["date"].dt.date == target].copy()
    return frame[frame["date"] == target].copy()


def _missing_game_reason(
    row: pd.Series,
    overlay_day: pd.DataFrame,
) -> str:
    if pd.isna(row.get("home_close_ml")) or pd.isna(row.get("away_close_ml")):
        return "missing_odds"
    if float(row.get("home_close_ml", 0) or 0) == 0 or float(row.get("away_close_ml", 0) or 0) == 0:
        return "missing_odds"

    home_pitcher = str(row.get("home_pitcher") or "").strip()
    away_pitcher = str(row.get("away_pitcher") or "").strip()
    if not home_pitcher or not away_pitcher:
        return "missing_probable_pitcher"

    same_matchup = overlay_day[
        (overlay_day["date"] == row["date"])
        & (overlay_day["matchup_key"] == row["matchup_key"])
    ]
    if len(same_matchup) > 1:
        return "doubleheader_matchup_removed"

    same_home_team = overlay_day[
        (overlay_day["date"] == row["date"])
        & (
            (overlay_day["home_team"] == row["home_team"])
            | (overlay_day["away_team"] == row["home_team"])
        )
    ]
    same_away_team = overlay_day[
        (overlay_day["date"] == row["date"])
        & (
            (overlay_day["home_team"] == row["away_team"])
            | (overlay_day["away_team"] == row["away_team"])
        )
    ]
    if len(same_home_team) > 1 or len(same_away_team) > 1:
        return "duplicate_team_date_removed"

    return "unknown_filter_drop"


def summarize_live_completeness(
    target: date,
    overlay: pd.DataFrame,
    filtered_day: pd.DataFrame,
    enriched_day: pd.DataFrame,
) -> dict[str, Any]:
    overlay_day = _day_slice(overlay, target)
    overlay_keys = _game_keys(overlay_day)
    filtered_keys = _game_keys(filtered_day)
    enriched_keys = _game_keys(enriched_day)

    missing_after_filters = sorted(overlay_keys - filtered_keys)
    missing_after_enrichment = sorted(filtered_keys - enriched_keys)

    overlay_lookup = {
        (str(row.away_team), str(row.home_team)): row
        for _, row in overlay_day.iterrows()
    }

    filter_details = []
    for key in missing_after_filters:
        row = overlay_lookup.get(key)
        reason = _missing_game_reason(row, overlay_day) if row is not None else "unknown_filter_drop"
        filter_details.append({"away": key[0], "home": key[1], "reason": reason})

    enrichment_details = [
        {"away": away, "home": home, "reason": "feature_pipeline_drop"}
        for away, home in missing_after_enrichment
    ]

    return {
        "target_date": target.isoformat(),
        "overlay_games": len(overlay_keys),
        "filtered_games": len(filtered_keys),
        "enriched_games": len(enriched_keys),
        "missing_after_filters": filter_details,
        "missing_after_enrichment": enrichment_details,
        "blocked": bool(filter_details or enrichment_details),
    }


def build_live_enriched(target: date) -> dict[str, Any]:
    """Build the live enriched frame and target-day completeness diagnostics."""
    from src.data_loader import (  # noqa: PLC0415
        add_derived_odds,
        apply_data_filters,
        load_all_seasons,
    )
    from src.features import build_all_features  # noqa: PLC0415
    from src.live_feature_forward import forward_project_features  # noqa: PLC0415
    from src.live_pregame import load_pregame_overlay  # noqa: PLC0415
    from src.strategies import add_derived_for_strategies  # noqa: PLC0415

    games = load_all_seasons()
    should_overlay = target >= date.today()
    if not should_overlay and len(games):
        should_overlay = not (games["date"].dt.date == target).any()

    overlay = pd.DataFrame()
    if should_overlay:
        overlay = load_pregame_overlay(target)
        if not overlay.empty:
            mask_existing = games["date"].dt.date == target if len(games) else pd.Series(dtype=bool)
            if len(mask_existing) and mask_existing.any():
                games = games.loc[~mask_existing].copy()
            games = pd.concat([games, overlay], ignore_index=True, sort=False)

    filtered = apply_data_filters(games)
    filtered_day = _day_slice(filtered, target)
    filtered = add_derived_odds(filtered)
    filtered = filtered[filtered["season"].isin([2024, 2025, 2026])].copy()

    enriched = build_all_features(filtered)
    if should_overlay:
        enriched = forward_project_features(enriched, target)
    enriched = add_derived_for_strategies(enriched)
    day = _day_slice(enriched, target)

    completeness = summarize_live_completeness(target, overlay, filtered_day, day)
    return {
        "target_date": target,
        "overlay_applied": should_overlay,
        "overlay": overlay,
        "filtered_day": filtered_day,
        "enriched": enriched,
        "day": day,
        "completeness": completeness,
    }
