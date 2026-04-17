from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features, build_yrfi_features
from src.live_feature_forward import forward_project_features
from src.live_pregame import load_pregame_overlay
from src.strategies import add_derived_for_strategies

TARGET = date(2026, 4, 16)


def test_pregame_overlay_fixture_has_10_games_after_filters():
    overlay = load_pregame_overlay(TARGET, allow_network_pitcher_fallback=False)
    assert len(overlay) == 10
    filtered = apply_data_filters(overlay.copy())
    assert len(filtered) == 10


@pytest.fixture(scope="module")
def projected_target_day() -> pd.DataFrame:
    games = load_all_seasons(seasons=[2025, 2026])
    overlay = load_pregame_overlay(TARGET, allow_network_pitcher_fallback=False)
    mask_existing = games["date"].dt.date == TARGET
    games = pd.concat([games.loc[~mask_existing].copy(), overlay], ignore_index=True, sort=False)
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    enriched = build_all_features(games)
    enriched = forward_project_features(enriched, TARGET)
    enriched = add_derived_for_strategies(enriched)

    day = enriched[enriched["date"].dt.date == TARGET].copy()
    assert len(day) == 10
    return day


def test_future_live_features_are_non_null_or_explicitly_flagged(projected_target_day: pd.DataFrame):
    day = projected_target_day

    for side in ["home", "away"]:
        starter_ok = (
            day[f"{side}_sp_fip_short"].notna()
            | day[f"insufficient_starter_history_{side}"].fillna(False)
            | day[f"starter_feature_source_missing_{side}"].fillna(False)
        )
        assert starter_ok.all(), f"{side} starter rows must be present or explicitly flagged"

        lineup_ok = (
            day[f"effective_obp_{side}"].notna()
            | day[f"insufficient_lineup_history_{side}"].fillna(False)
            | day[f"lineup_feature_source_missing_{side}"].fillna(False)
        )
        assert lineup_ok.all(), f"{side} lineup rows must be present or explicitly flagged"

    fav_diff_ok = (
        day["fav_starter_fip_diff"].notna()
        | day["insufficient_starter_history"].fillna(False)
        | day["starter_feature_source_missing"].fillna(False)
    )
    assert fav_diff_ok.all()


def test_future_yrfi_rows_keep_live_babip_or_raise_explicit_history_flags(
    projected_target_day: pd.DataFrame,
):
    yrfi = build_yrfi_features(enriched=projected_target_day)
    assert len(yrfi) == 10
    assert yrfi["is_future_overlay"].all()
    assert yrfi["yrfi"].isna().all()

    babip_ok = (
        yrfi["top3_babip_inn1_home"].notna()
        & yrfi["top3_babip_inn1_away"].notna()
        & yrfi["sp_babip_inn1_home"].notna()
        & yrfi["sp_babip_inn1_away"].notna()
    )
    explicit_gap = (
        yrfi["unsupported_live_babip_features"].fillna(False)
        | yrfi["insufficient_babip_history"].fillna(False)
    )
    assert (babip_ok | explicit_gap).all()
    assert not yrfi["unsupported_live_babip_features"].all()
    assert not yrfi["unsupported_live_yrfi_features"].all()
