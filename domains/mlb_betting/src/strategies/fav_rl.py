"""Fav -1.5 Run Line shadow strategy.

Re-audited on 2026-04-19. The away-favorite / home-underdog lane did not
clear the resurrection bar on official 2021-2025 actual odds, so ``fav_rl``
is no longer part of the default live tier set.

We keep the strategy callable for manual/shadow logging only, restricted to
the current away-favorite shadow basket:
  fav_implied ∈ [0.62, 0.75)
  fav_starter_fip_diff <= -0.2
  fav_power_rate_diff >= 0
  fav_is_home == False
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.fav_rl_audit import (
    CURRENT_SHADOW_FILTER,
    CURRENT_SHADOW_HISTORICAL_P,
    estimate_away_fav_rl_decimal,
)

from .base import Pick, feature_snapshot

TIER = "fav_rl"
P_COVER = CURRENT_SHADOW_HISTORICAL_P

# Shadow-only filter thresholds from the 2026-04-19 canonical re-audit.
IMPL_MIN = CURRENT_SHADOW_FILTER["impl_min"]
IMPL_MAX = CURRENT_SHADOW_FILTER["impl_max"]  # exclusive upper bound
FIP_DIFF_MAX = CURRENT_SHADOW_FILTER["fav_starter_fip_diff_max"]
POWER_RATE_DIFF_MIN = CURRENT_SHADOW_FILTER["fav_power_rate_diff_min"]

SNAPSHOT_COLS = [
    "fav_implied_prob",
    "fav_is_home",
    "fav_starter_fip_diff",
    "fav_power_rate_diff",
    "away_run_line_odds",
    "home_run_line_odds",
    "home_sp_fip_short",
    "away_sp_fip_short",
    "power_rate_home",
    "power_rate_away",
    "home_close_ml",
    "away_close_ml",
]


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    if games.empty:
        return []

    df = games[games["date"].dt.date == target_date] if hasattr(
        games["date"].iloc[0], "date"
    ) else games[games["date"] == target_date]

    if df.empty:
        return []

    required = ["fav_implied_prob", "fav_starter_fip_diff", "fav_power_rate_diff", "fav_is_home"]
    if any(c not in df.columns for c in required):
        return []

    mask = (
        (~df["fav_is_home"].fillna(False))
        &
        (df["fav_implied_prob"] >= IMPL_MIN)
        & (df["fav_implied_prob"] < IMPL_MAX)
        & (df["fav_starter_fip_diff"] <= FIP_DIFF_MAX)
        & (df["fav_power_rate_diff"] >= POWER_RATE_DIFF_MIN)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        snap["shadow_only_mode"] = True
        snap["shadow_filter_label"] = "away_fav_only_current_filter"
        side = "away"
        reason = (
            "shadow-only away-fav lane: "
            f"fav_implied={row['fav_implied_prob']:.3f} ∈ [{IMPL_MIN}, {IMPL_MAX})"
            f" & fav_fip_diff={row['fav_starter_fip_diff']:.2f} ≤ {FIP_DIFF_MAX}"
            f" & fav_power_diff={row['fav_power_rate_diff']:.3f} ≥ {POWER_RATE_DIFF_MIN}"
        )
        ref_odds = _favorite_rl_reference_odds(row)

        picks.append(
            Pick.make(
                target_date=target_date,
                away=str(row["away_team"]),
                home=str(row["home_team"]),
                market="RL_-1.5",
                side=side,
                tier=TIER,
                historical_p=P_COVER,
                ref_odds_espn=ref_odds,
                reason=reason,
                feature_snapshot=snap,
            )
        )

    return picks


def _favorite_rl_reference_odds(row: pd.Series) -> float | None:
    away_actual = _decimal_or_none(row.get("away_run_line_odds"))
    if away_actual is not None:
        return away_actual
    estimated = estimate_away_fav_rl_decimal(row.get("home_run_line_odds"))
    if estimated is None:
        return None
    return float(estimated)


def _decimal_or_none(american_odds) -> float | None:
    if pd.isna(american_odds) or american_odds == 0:
        return None
    val = float(american_odds)
    if val > 0:
        return 1.0 + val / 100.0
    return 1.0 + 100.0 / abs(val)
