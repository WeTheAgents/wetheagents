"""Tier 4 — ML Depth Load.

Pattern: away underdog gets a meaningfully deeper starter against a home
favorite whose bullpen is already loaded, while the away lineup carries
enough on-base skill and the home bullpen quality baseline is weak enough
to keep the dog ML live.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier4_ml_depth_load"
P_DOG_ML = 0.5208711433756806

DEPTH_DIFF_MAX = -0.75
HOME_BP_3D_MIN = 8.0
AWAY_EFFECTIVE_OBP_MIN = 0.315
HOME_BP_SC_XWOBA_STD_MIN = 0.28021246065799577

SNAPSHOT_COLS = [
    "starter_depth_diff_short",
    "home_sp_ip_per_start_short",
    "away_sp_ip_per_start_short",
    "bp_ip_3d_home",
    "bp_ip_3d_away",
    "effective_obp_away",
    "bp_sc_xwoba_std_home",
    "away_close_ml",
    "home_close_ml",
    "fav_is_home",
    "home_is_bullpen_no_starter",
    "away_is_bullpen_no_starter",
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
        "fav_is_home",
        "away_close_ml",
        "home_is_bullpen_no_starter",
        "away_is_bullpen_no_starter",
        "starter_depth_diff_short",
        "bp_ip_3d_home",
        "effective_obp_away",
        "bp_sc_xwoba_std_home",
    ]
    if any(col not in df.columns for col in required):
        return []

    mask = (
        (df["fav_is_home"].fillna(False) == True)  # noqa: E712
        & (df["away_close_ml"].fillna(0) > 0)
        & (df["home_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["starter_depth_diff_short"] <= DEPTH_DIFF_MAX)
        & (df["bp_ip_3d_home"] >= HOME_BP_3D_MIN)
        & (df["effective_obp_away"] >= AWAY_EFFECTIVE_OBP_MIN)
        & (df["bp_sc_xwoba_std_home"] >= HOME_BP_SC_XWOBA_STD_MIN)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        reason = (
            f"depth_diff_short={row['starter_depth_diff_short']:.2f} <= {DEPTH_DIFF_MAX}"
            f" & home_bp_3d={row['bp_ip_3d_home']:.1f} >= {HOME_BP_3D_MIN}"
            f" & effective_obp_away={row['effective_obp_away']:.3f} >= {AWAY_EFFECTIVE_OBP_MIN}"
            f" & home_bp_sc_xwoba_std={row['bp_sc_xwoba_std_home']:.3f} >= {HOME_BP_SC_XWOBA_STD_MIN:.3f}"
        )
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
                feature_snapshot=feature_snapshot(row, SNAPSHOT_COLS),
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
