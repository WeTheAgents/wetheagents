"""Tier 3 — Pitcher Advantage (Sess 27).

Pattern: away underdog has a quality starter (low FIP) who eats innings
(high IP/start) against a home favorite whose bullpen is already tired.
The home team's starter-to-bullpen handoff happens early into a fatigued
bullpen — structural edge for the away dog +1.5.

Per Sess 27 production filter:
  away_sp_fip_short <= 3.5
  starter_depth_diff <= -1.0      (away SP averages 1+ more IP/start)
  bp_ip_3d_home >= 8

  → 81 games (2014-2025), 79.0% RL +1.5 cover, +24.7% ROI
  → 8/10 seasons profitable

**Decision §9.1 (operator)**: live picks use the SHORT (5-start) window
for ip_per_start instead of the LONG (15-start) window. The long window
won't be valid until ~mid-June. Pre-flight in scripts/check_2026_pipeline.py
reproduces Sess 27 with the short-window swap and aborts go-live if the
ROI drops below +10%.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier3_pitcher_advantage"
P_RL_PLUS_15 = 0.790  # Sess 27 cover rate

# Filter thresholds — exact reproduction of Sess 27 production filter,
# with the short-window swap from Decision §9.1.
AWAY_FIP_SHORT_MAX = 3.5
DEPTH_DIFF_MAX = -1.0          # away SP goes ≥1 inning deeper than home
HOME_BP_3D_MIN = 8.0

SNAPSHOT_COLS = [
    "away_sp_fip_short",
    "home_sp_fip_short",
    "starter_depth_diff_short",
    "starter_depth_diff",
    "home_sp_ip_per_start_short",
    "away_sp_ip_per_start_short",
    "bp_ip_3d_home",
    "bp_ip_3d_away",
]


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    if games.empty:
        return []

    df = games[games["date"].dt.date == target_date] if hasattr(
        games["date"].iloc[0], "date"
    ) else games[games["date"] == target_date]

    if df.empty:
        return []

    required = [
        "away_sp_fip_short",
        "starter_depth_diff_short",
        "bp_ip_3d_home",
        "home_is_bullpen_no_starter",
        "away_is_bullpen_no_starter",
        "fav_is_home",
    ]
    if any(c not in df.columns for c in required):
        return []

    mask = (
        # Sess 27 universe restriction (home favorite)
        (df["fav_is_home"].fillna(False) == True)  # noqa: E712
        # Both teams have a starter (Tier 1 owns the bullpen-day case)
        & (df["home_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
        # Away starter is high quality
        & (df["away_sp_fip_short"] <= AWAY_FIP_SHORT_MAX)
        # Away starter goes meaningfully deeper than home starter
        & (df["starter_depth_diff_short"] <= DEPTH_DIFF_MAX)
        # Home bullpen is fatigued
        & (df["bp_ip_3d_home"] >= HOME_BP_3D_MIN)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        snap = feature_snapshot(row, SNAPSHOT_COLS)
        reason = (
            f"away_fip_short={row['away_sp_fip_short']:.2f} ≤ {AWAY_FIP_SHORT_MAX}"
            f" & depth_diff_short={row['starter_depth_diff_short']:.2f} ≤ {DEPTH_DIFF_MAX}"
            f" & home_bp_3d={row['bp_ip_3d_home']:.1f} ≥ {HOME_BP_3D_MIN}"
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
