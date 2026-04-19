"""Live UNDER totals strategy backed by the persisted ensemble bundle."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.features import build_ou_features
from src.under_live import (
    UNDER_BASE_THRESHOLD,
    UNDER_POWER_THRESHOLD,
    load_under_live_bundle,
    predict_under_bundle_proba,
)

from .base import Pick, feature_snapshot

logger = logging.getLogger(__name__)

TIER_BASE = "under_totals"
TIER_POWER = "under_totals_power"

SNAPSHOT_COLS = [
    "close_ou",
    "combined_rpg",
    "combined_rpg_last10",
    "rpg_vs_line",
    "bullpen_fip_7g_combined",
    "bullpen_ip_3d_combined",
    "sp_ra_floor_long",
    "sp_fip_combined",
    "hold_rate_combined",
]


def _marginal_veto(
    row: pd.Series,
    thresholds: dict | None,
    *,
    min_prob: float,
    max_prob: float,
) -> bool:
    if not thresholds:
        return False
    p_under = float(row.get("p_under", 0.0))
    if p_under < min_prob or p_under >= max_prob:
        return False
    ip_cut = thresholds.get("bullpen_ip_3d_combined")
    fip_cut = thresholds.get("bullpen_fip_7g_combined")
    if ip_cut is None or fip_cut is None:
        return False
    ip_value = row.get("bullpen_ip_3d_combined")
    fip_value = row.get("bullpen_fip_7g_combined")
    if pd.isna(ip_value) or pd.isna(fip_value):
        return False
    return bool(ip_value > ip_cut and fip_value > fip_cut)


def find_picks(games: pd.DataFrame, target_date: date) -> list[Pick]:
    if games.empty:
        return []

    try:
        bundle = load_under_live_bundle()
    except FileNotFoundError as exc:
        logger.warning("UNDER live bundle unavailable: %s", exc)
        return []

    ou_frame = build_ou_features(enriched=games)
    if ou_frame.empty:
        return []

    day = ou_frame[ou_frame["date"].dt.date == target_date].copy()
    if day.empty:
        return []

    day["p_under"] = predict_under_bundle_proba(day, bundle)
    base_threshold = float(bundle.thresholds.get(TIER_BASE, UNDER_BASE_THRESHOLD))
    power_threshold = float(bundle.thresholds.get(TIER_POWER, UNDER_POWER_THRESHOLD))

    modifier = bundle.modifier or {}
    apply_live_modifier = bool(modifier.get("apply_live"))
    selected_thresholds = modifier.get("selected_thresholds_live") or {}
    shadow_thresholds = modifier.get("shadow_thresholds_live") or {}

    picks: list[Pick] = []
    qualified = day[day["p_under"] >= base_threshold].copy()
    for _, row in qualified.iterrows():
        live_veto = _marginal_veto(
            row,
            selected_thresholds,
            min_prob=base_threshold,
            max_prob=power_threshold,
        )
        if apply_live_modifier and live_veto:
            continue

        tier = TIER_POWER if float(row["p_under"]) >= power_threshold else TIER_BASE
        shadow_veto = _marginal_veto(
            row,
            shadow_thresholds,
            min_prob=base_threshold,
            max_prob=power_threshold,
        )

        snapshot = feature_snapshot(row, SNAPSHOT_COLS)
        snapshot["p_under"] = float(row["p_under"])
        snapshot["modifier_live_enabled"] = apply_live_modifier
        snapshot["modifier_live_veto"] = bool(live_veto)
        snapshot["modifier_shadow_veto"] = bool(shadow_veto)
        snapshot["modifier_selected_quantile"] = modifier.get("selected_quantile_label")
        snapshot["modifier_shadow_quantile"] = modifier.get("shadow_quantile_label")

        reason = (
            f"bundle_p_under={row['p_under']:.3f} "
            f"(base>={base_threshold:.2f}, power>={power_threshold:.2f})"
        )
        if shadow_veto and not apply_live_modifier:
            reason += " | shadow_bullpen_veto_only"

        picks.append(
            Pick.make(
                target_date=target_date,
                away=str(row["away_team"]),
                home=str(row["home_team"]),
                market="O/U",
                side="under",
                tier=tier,
                historical_p=float(row["p_under"]),
                ref_odds_espn=bundle.fallback_ref_odds,
                market_line=float(row["close_ou"]),
                reason=reason,
                feature_snapshot=snapshot,
            )
        )

    return picks
