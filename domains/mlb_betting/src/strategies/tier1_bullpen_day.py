"""Tier 1 — Bullpen Day Dog (Sess 26).

Pattern: home favorite runs a bullpen day (no traditional starter), away
underdog has a real starter. Market underprices the dog because the
default model "home team wins" doesn't account for the structural
mismatch.

Per Sess 26:
  - 264 games, 11/11 seasons profitable (2014-2025)
  - Dog ML: 74.2% win rate at avg 2.20 → +63.9% ROI
  - RL +1.5: 83.7% cover at avg 1.56 → +31.2% ROI

The audit plan documents this as the only strategy that's truly ready
on Day 1 of the season (no rolling-window dependencies). The picks
generator deploys both ML and RL +1.5 sides for every qualifying game.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier1_bullpen_day"

# Historical (Sess 26) cover/win rates. The picks generator shrinks
# these by 5% before computing Kelly (plans/§11.1 #14).
P_DOG_ML = 0.742
P_RL_PLUS_15 = 0.837

SNAPSHOT_COLS = [
    "home_is_bullpen_no_starter",
    "away_is_bullpen_no_starter",
    "home_close_ml",
    "away_close_ml",
    "home_implied_prob",
    "away_implied_prob",
    "fav_is_home",
]


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    """Return all Tier 1 picks for ``target_date``.

    Tier 1 ships TWO picks per qualifying game: dog ML + dog RL +1.5.
    The dedup step in the generator chooses the higher-conviction pick
    (ML by default — 74% win is more reliable than 83% cover with vig).

    The strategy is symmetrical in principle (away bullpen day + home
    starter would be the same edge mirrored), but Sess 26 only validated
    the home-bullpen-day → away-dog direction. We follow the validated
    direction strictly here.
    """
    if games.empty:
        return []

    df = games[games["date"].dt.date == target_date] if hasattr(
        games["date"].iloc[0], "date"
    ) else games[games["date"] == target_date]

    if df.empty:
        return []

    if "home_is_bullpen_no_starter" not in df.columns:
        return []

    # Sess 26 universe: fav_is_home == True (home favorite). Without this
    # filter we over-count by ~1.6x because road favorites occasionally
    # run bullpen days too — those weren't validated by Sess 26.
    mask = (
        (df["home_is_bullpen_no_starter"] == True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["fav_is_home"].fillna(False) == True)  # noqa: E712
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        reason = "home_is_bullpen_no_starter & away_has_starter"

        # Dog ML pick (primary — higher Kelly even at lower implied prob)
        picks.append(
            Pick.make(
                target_date=target_date,
                away=str(row["away_team"]),
                home=str(row["home_team"]),
                market="ML_dog",
                side="away",
                tier=TIER,
                historical_p=P_DOG_ML,
                ref_odds_espn=_decimal_or_none(row.get("away_close_ml")),
                reason=reason,
                feature_snapshot=snap,
            )
        )

        # Dog RL +1.5 pick (secondary — buffer against single-run loss)
        picks.append(
            Pick.make(
                target_date=target_date,
                away=str(row["away_team"]),
                home=str(row["home_team"]),
                market="RL_+1.5",
                side="away",
                tier=TIER,
                historical_p=P_RL_PLUS_15,
                ref_odds_espn=_decimal_or_none(row.get("away_run_line_odds")),
                reason=reason,
                feature_snapshot=snap,
            )
        )

    return picks


def _decimal_or_none(american_odds) -> float | None:
    """Convert American odds to decimal, or return None if unavailable."""
    if pd.isna(american_odds) or american_odds == 0:
        return None
    val = float(american_odds)
    if val > 0:
        return 1.0 + val / 100.0
    return 1.0 + 100.0 / abs(val)
