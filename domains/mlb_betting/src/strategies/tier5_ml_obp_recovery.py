"""Tier 5 — ML OBP Recovery.

Pattern: away underdog brings a capable starter and enough lineup recovery
ability against a home favorite whose bullpen is already taxed and whose
late-game recovery profile is not stronger than the dog's.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .base import Pick, feature_snapshot

TIER = "tier5_ml_obp_recovery"
P_DOG_ML = 0.4843400447427293

AWAY_FIP_SHORT_MAX = 4.8
HOME_BP_3D_MIN = 4.0
AWAY_EFFECTIVE_OBP_MIN = 0.335
HOME_BP_SC_XWOBA_STD_MIN = 0.28021246065799577
DEFICIT_RECOVERY_DIFF_MAX = 0.0

SNAPSHOT_COLS = [
    "away_sp_fip_short",
    "home_sp_fip_short",
    "bp_ip_3d_home",
    "bp_ip_3d_away",
    "effective_obp_away",
    "bp_sc_xwoba_std_home",
    "deficit_recovery_diff",
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
        "away_sp_fip_short",
        "bp_ip_3d_home",
        "effective_obp_away",
        "bp_sc_xwoba_std_home",
        "deficit_recovery_diff",
    ]
    if any(col not in df.columns for col in required):
        return []

    mask = (
        (df["fav_is_home"].fillna(False) == True)  # noqa: E712
        & (df["away_close_ml"].fillna(0) > 0)
        & (df["home_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["away_is_bullpen_no_starter"] != True)  # noqa: E712
        & (df["away_sp_fip_short"] <= AWAY_FIP_SHORT_MAX)
        & (df["bp_ip_3d_home"] >= HOME_BP_3D_MIN)
        & (df["effective_obp_away"] >= AWAY_EFFECTIVE_OBP_MIN)
        & (df["bp_sc_xwoba_std_home"] >= HOME_BP_SC_XWOBA_STD_MIN)
        & (df["deficit_recovery_diff"] <= DEFICIT_RECOVERY_DIFF_MAX)
    )
    qualified = df[mask]

    picks: list[Pick] = []
    for _, row in qualified.iterrows():
        reason = (
            f"away_sp_fip_short={row['away_sp_fip_short']:.2f} <= {AWAY_FIP_SHORT_MAX}"
            f" & home_bp_3d={row['bp_ip_3d_home']:.1f} >= {HOME_BP_3D_MIN}"
            f" & effective_obp_away={row['effective_obp_away']:.3f} >= {AWAY_EFFECTIVE_OBP_MIN}"
            f" & home_bp_sc_xwoba_std={row['bp_sc_xwoba_std_home']:.3f} >= {HOME_BP_SC_XWOBA_STD_MIN:.3f}"
            f" & deficit_recovery_diff={row['deficit_recovery_diff']:.3f} <= {DEFICIT_RECOVERY_DIFF_MAX:.1f}"
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
