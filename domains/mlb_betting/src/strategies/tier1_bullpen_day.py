"""Tier 1 — Bullpen Day Dog (Sess 26 + Sess 29 expansion).

Pattern: home team runs a bullpen day (no traditional starter), away
team has a real starter.

Two sub-cases validated on 2023-2025 (544 games):

  A) Home is still favorite after BP announcement (Sess 26 universe):
     - Market hasn't fully priced the mismatch yet.
     - ML: 70.4% WR at 2.29 → +59.8% ROI.  RL: 80.6% cover → +29.0% ROI.
     - BOTH ML and RL picks emitted.

  B) Line flipped — home became dog (Sess 29 discovery):
     - Market moved ML odds but RL +1.5 remains underpriced.
     - ML: 76.9% WR but at 1.70 → +30.1% ROI (thin, not worth Kelly).
     - RL: 88.8% cover → +42.2% ROI — HIGHER than case A.
     - ONLY RL +1.5 pick emitted (ML odds too compressed).

Combined volume: ~48 RL picks/season (vs ~24 with old filter).
RL cover rate is stable across halves (1H 82-88%, 2H 83-89%).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier1_bullpen_day"
TIER_FLIPPED = "tier1_bullpen_day_flipped"

# Historical rates (2023-2025, 544 games).
# Case A: home still fav → full Sess 26 rates.
P_DOG_ML = 0.704
P_RL_PLUS_15 = 0.806

# Case B: line flipped → RL only, higher cover rate.
P_RL_PLUS_15_FLIPPED = 0.888

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

    Case A (home still fav): emits ML_dog + RL +1.5.
    Case B (line flipped):   emits RL +1.5 only (ML odds too thin).
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

    # All home bullpen days where away has a real starter.
    bp_mask = (
        (df["home_is_bullpen_no_starter"] == True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
    )
    qualified = df[bp_mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        fav_home = bool(row.get("fav_is_home", True))

        if fav_home:
            # Case A — home still favorite. Both ML and RL.
            reason = "bullpen_day & home_still_fav"
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
        else:
            # Case B — line flipped, home is now dog. RL +1.5 only.
            reason = "bullpen_day & line_flipped (RL only, 88.8% cover)"
            picks.append(
                Pick.make(
                    target_date=target_date,
                    away=str(row["away_team"]),
                    home=str(row["home_team"]),
                    market="RL_+1.5",
                    side="away",
                    tier=TIER_FLIPPED,
                    historical_p=P_RL_PLUS_15_FLIPPED,
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
