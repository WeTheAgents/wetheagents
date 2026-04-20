from __future__ import annotations

import pandas as pd
import pytest

from src.fav_rl_audit import (
    current_shadow_filter_mask,
    estimate_away_fav_rl_decimal,
    summarize_flat_bets,
)


def test_estimate_away_fav_rl_decimal_matches_legacy_formula():
    home_plus_one_point_five = -180

    estimated = estimate_away_fav_rl_decimal(home_plus_one_point_five)

    home_plus_decimal = 1.0 + 100.0 / 180.0
    home_plus_implied = 1.0 / home_plus_decimal
    expected = 1.0 / (1.045 - home_plus_implied)
    assert estimated == pytest.approx(expected)


def test_current_shadow_filter_mask_requires_away_favorite_lane():
    df = pd.DataFrame(
        [
            {
                "fav_is_home": False,
                "fav_implied_prob": 0.68,
                "fav_starter_fip_diff": -0.50,
                "fav_power_rate_diff": 0.03,
            },
            {
                "fav_is_home": True,
                "fav_implied_prob": 0.68,
                "fav_starter_fip_diff": -0.50,
                "fav_power_rate_diff": 0.03,
            },
        ]
    )

    mask = current_shadow_filter_mask(df)

    assert mask.tolist() == [True, False]


def test_summarize_flat_bets_tracks_price_sources_and_seasons():
    df = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-04-01"),
                "away_team": "A",
                "home_team": "B",
                "season": 2024,
                "covers": True,
                "official_rl_odds": 2.30,
                "price_source": "actual",
            },
            {
                "date": pd.Timestamp("2024-04-02"),
                "away_team": "C",
                "home_team": "D",
                "season": 2024,
                "covers": False,
                "official_rl_odds": 2.10,
                "price_source": "estimated",
            },
            {
                "date": pd.Timestamp("2025-04-01"),
                "away_team": "E",
                "home_team": "F",
                "season": 2025,
                "covers": True,
                "official_rl_odds": 2.20,
                "price_source": "actual",
            },
        ]
    )

    stats = summarize_flat_bets(df)

    assert stats["bets"] == 3
    assert stats["actual_prices"] == 2
    assert stats["estimated_prices"] == 1
    assert stats["positive_seasons"] == 2
    assert [row["season"] for row in stats["season_rows"]] == [2024, 2025]
