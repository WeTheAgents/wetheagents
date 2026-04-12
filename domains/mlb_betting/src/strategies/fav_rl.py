"""Fav -1.5 Run Line (Sess 25).

Pattern: moderate-to-strong favorite (62-75% implied) with a clear
pitching edge (low FIP) and offensive explosiveness (positive power
rate diff). Sess 25 found this is the most robust filter combination
across 2014-2025: market underprices -1.5 coverage when both
ingredients line up.

Per Sess 25:
  fav_implied ∈ [0.62, 0.75)
  fav_starter_fip_diff <= -0.2     (fav SP has lower FIP)
  fav_power_rate_diff >= 0          (fav at least as explosive)

  → 548 train + 121 test games (2021-2024 / 2025)
  → 49.8% / 47.9% cover at est. odds 2.40
  → +19.6% TRAIN / +15.0% TEST 2025 OOS

This is the highest-volume strategy in the portfolio (~137 games/season).
The bottleneck is feature readiness: fav_starter_fip_diff needs ≥5 starts
per starter, so picks won't fire reliably until ~May 1-5 (audit plan §4).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "fav_rl"
P_COVER = 0.498  # Sess 25 cover rate (TRAIN average)

# Filter thresholds — exact reproduction of Sess 25 production filter.
IMPL_MIN = 0.62
IMPL_MAX = 0.75   # exclusive upper bound
FIP_DIFF_MAX = -0.2
POWER_RATE_DIFF_MIN = 0.0

SNAPSHOT_COLS = [
    "fav_implied_prob",
    "fav_is_home",
    "fav_starter_fip_diff",
    "fav_power_rate_diff",
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
        (df["fav_implied_prob"] >= IMPL_MIN)
        & (df["fav_implied_prob"] < IMPL_MAX)
        & (df["fav_starter_fip_diff"] <= FIP_DIFF_MAX)
        & (df["fav_power_rate_diff"] >= POWER_RATE_DIFF_MIN)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        fav_is_home = bool(row["fav_is_home"])
        side = "home" if fav_is_home else "away"
        reason = (
            f"fav_implied={row['fav_implied_prob']:.3f} ∈ [{IMPL_MIN}, {IMPL_MAX})"
            f" & fav_fip_diff={row['fav_starter_fip_diff']:.2f} ≤ {FIP_DIFF_MAX}"
            f" & fav_power_diff={row['fav_power_rate_diff']:.3f} ≥ {POWER_RATE_DIFF_MIN}"
        )
        # Reference RL odds: fav side is the -1.5 line. The xlsx run_line column
        # is the home spread (-1.5 if home is fav, +1.5 if away is fav). For
        # the favorite's -1.5 we want the home_run_line_odds when fav is home,
        # and away_run_line_odds when fav is away (and the spread is -1.5).
        ref_odds = None
        if fav_is_home and "home_run_line_odds" in row:
            ref_odds = _decimal_or_none(row.get("home_run_line_odds"))
        elif not fav_is_home and "away_run_line_odds" in row:
            ref_odds = _decimal_or_none(row.get("away_run_line_odds"))

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


def _decimal_or_none(american_odds) -> float | None:
    if pd.isna(american_odds) or american_odds == 0:
        return None
    val = float(american_odds)
    if val > 0:
        return 1.0 + val / 100.0
    return 1.0 + 100.0 / abs(val)
