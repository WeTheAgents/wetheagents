"""Tier 2 — Bullpen Fatigue Gap (Sess 26).

Pattern: both teams have a regular starter (no bullpen day), but the
home favorite's bullpen has worked materially more innings in the last
3 days than the away dog's bullpen. The market hasn't fully priced in
which side has fresh relievers when the starter exits.

Per Sess 26:
  - ~25-35 games/season at +11.2% ROI on RL +1.5
  - Cover rate ~72%
  - 10/11 seasons profitable
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier2_fatigue_gap"
P_RL_PLUS_15 = 0.722  # Sess 26 cover rate

# Filter thresholds — exact reproduction of Sess 26 production filter.
WORKLOAD_GAP_MIN = 3.0
AWAY_BP_3D_MAX = 7.0

SNAPSHOT_COLS = [
    "home_is_bullpen_no_starter",
    "away_is_bullpen_no_starter",
    "bp_ip_3d_home",
    "bp_ip_3d_away",
    "bp_workload_gap",
    "bp_fip_short_home",
    "bp_fip_short_away",
]


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    if games.empty:
        return []

    df = games[games["date"].dt.date == target_date] if hasattr(
        games["date"].iloc[0], "date"
    ) else games[games["date"] == target_date]

    if df.empty:
        return []

    required = ["bp_ip_3d_home", "bp_ip_3d_away", "bp_workload_gap"]
    if any(c not in df.columns for c in required):
        return []

    mask = (
        # Sess 26 universe restriction (home favorite)
        (df["fav_is_home"].fillna(False) == True)  # noqa: E712
        # Both have starters (Tier 1 owns the bullpen-day case)
        & (df["home_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
        # Home BP worked materially more than away BP in the last 3 days
        & (df["bp_workload_gap"] >= WORKLOAD_GAP_MIN)
        # Away BP is rested
        & (df["bp_ip_3d_away"] <= AWAY_BP_3D_MAX)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        reason = (
            f"bp_workload_gap={row['bp_workload_gap']:.1f} >= {WORKLOAD_GAP_MIN}"
            f" & bp_ip_3d_away={row['bp_ip_3d_away']:.1f} <= {AWAY_BP_3D_MAX}"
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

    return picks


def _decimal_or_none(american_odds) -> float | None:
    if pd.isna(american_odds) or american_odds == 0:
        return None
    val = float(american_odds)
    if val > 0:
        return 1.0 + val / 100.0
    return 1.0 + 100.0 / abs(val)
