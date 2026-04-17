"""Shared live readiness diagnostics for the new ML basket strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from src.strategies import tier4_ml_depth_load as tier4
from src.strategies import tier5_ml_obp_recovery as tier5


@dataclass(frozen=True)
class FilterSpec:
    label: str
    predicate: Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class StrategyAuditConfig:
    tier: str
    required_fields: tuple[str, ...]
    threshold_fields: tuple[str, ...]
    filters: tuple[FilterSpec, ...]
    warmup_sparse_fields: tuple[str, ...] = ()
    source_flag_cols: tuple[str, ...] = (
        "starter_feature_source_missing",
        "lineup_feature_source_missing",
    )
    insufficient_flag_cols: tuple[str, ...] = (
        "insufficient_starter_history",
        "insufficient_lineup_history",
    )
    bridge_flag_cols: tuple[str, ...] = ("starter_history_bridge_missing",)


def _tier4_filters() -> tuple[FilterSpec, ...]:
    return (
        FilterSpec("fav_is_home", lambda df: df["fav_is_home"].fillna(False) == True),  # noqa: E712
        FilterSpec("away_dog_ml", lambda df: df["away_close_ml"].fillna(0) > 0),
        FilterSpec("home_starter", lambda df: df["home_is_bullpen_no_starter"] != True),  # noqa: E712
        FilterSpec("away_starter", lambda df: df["away_is_bullpen_no_starter"] != True),  # noqa: E712
        FilterSpec(
            f"starter_depth_diff_short<={tier4.DEPTH_DIFF_MAX}",
            lambda df: df["starter_depth_diff_short"] <= tier4.DEPTH_DIFF_MAX,
        ),
        FilterSpec(
            f"bp_ip_3d_home>={tier4.HOME_BP_3D_MIN}",
            lambda df: df["bp_ip_3d_home"] >= tier4.HOME_BP_3D_MIN,
        ),
        FilterSpec(
            f"effective_obp_away>={tier4.AWAY_EFFECTIVE_OBP_MIN}",
            lambda df: df["effective_obp_away"] >= tier4.AWAY_EFFECTIVE_OBP_MIN,
        ),
        FilterSpec(
            f"bp_sc_xwoba_std_home>={tier4.HOME_BP_SC_XWOBA_STD_MIN:.4f}",
            lambda df: df["bp_sc_xwoba_std_home"] >= tier4.HOME_BP_SC_XWOBA_STD_MIN,
        ),
    )


def _tier5_filters() -> tuple[FilterSpec, ...]:
    return (
        FilterSpec("fav_is_home", lambda df: df["fav_is_home"].fillna(False) == True),  # noqa: E712
        FilterSpec("away_dog_ml", lambda df: df["away_close_ml"].fillna(0) > 0),
        FilterSpec("home_starter", lambda df: df["home_is_bullpen_no_starter"] != True),  # noqa: E712
        FilterSpec("away_starter", lambda df: df["away_is_bullpen_no_starter"] != True),  # noqa: E712
        FilterSpec(
            f"away_sp_fip_short<={tier5.AWAY_FIP_SHORT_MAX}",
            lambda df: df["away_sp_fip_short"] <= tier5.AWAY_FIP_SHORT_MAX,
        ),
        FilterSpec(
            f"bp_ip_3d_home>={tier5.HOME_BP_3D_MIN}",
            lambda df: df["bp_ip_3d_home"] >= tier5.HOME_BP_3D_MIN,
        ),
        FilterSpec(
            f"effective_obp_away>={tier5.AWAY_EFFECTIVE_OBP_MIN}",
            lambda df: df["effective_obp_away"] >= tier5.AWAY_EFFECTIVE_OBP_MIN,
        ),
        FilterSpec(
            f"bp_sc_xwoba_std_home>={tier5.HOME_BP_SC_XWOBA_STD_MIN:.4f}",
            lambda df: df["bp_sc_xwoba_std_home"] >= tier5.HOME_BP_SC_XWOBA_STD_MIN,
        ),
        FilterSpec(
            f"deficit_recovery_diff<={tier5.DEFICIT_RECOVERY_DIFF_MAX:.1f}",
            lambda df: df["deficit_recovery_diff"] <= tier5.DEFICIT_RECOVERY_DIFF_MAX,
        ),
    )


AUDIT_CONFIGS: dict[str, StrategyAuditConfig] = {
    "tier4_ml_depth_load": StrategyAuditConfig(
        tier="tier4_ml_depth_load",
        required_fields=(
            "fav_is_home",
            "away_close_ml",
            "home_is_bullpen_no_starter",
            "away_is_bullpen_no_starter",
            "starter_depth_diff_short",
            "bp_ip_3d_home",
            "effective_obp_away",
            "bp_sc_xwoba_std_home",
        ),
        threshold_fields=(
            "starter_depth_diff_short",
            "bp_ip_3d_home",
            "effective_obp_away",
            "bp_sc_xwoba_std_home",
        ),
        filters=_tier4_filters(),
        warmup_sparse_fields=("starter_depth_diff_short",),
    ),
    "tier5_ml_obp_recovery": StrategyAuditConfig(
        tier="tier5_ml_obp_recovery",
        required_fields=(
            "fav_is_home",
            "away_close_ml",
            "home_is_bullpen_no_starter",
            "away_is_bullpen_no_starter",
            "away_sp_fip_short",
            "bp_ip_3d_home",
            "effective_obp_away",
            "bp_sc_xwoba_std_home",
            "deficit_recovery_diff",
        ),
        threshold_fields=(
            "away_sp_fip_short",
            "bp_ip_3d_home",
            "effective_obp_away",
            "bp_sc_xwoba_std_home",
            "deficit_recovery_diff",
        ),
        filters=_tier5_filters(),
        warmup_sparse_fields=("away_sp_fip_short", "deficit_recovery_diff"),
    ),
}


def target_day_frame(enriched: pd.DataFrame, target_date) -> pd.DataFrame:
    """Slice a target date without assuming a particular datetime representation."""
    if enriched.empty:
        return enriched.copy()
    first = enriched["date"].iloc[0]
    if hasattr(first, "date"):
        return enriched[enriched["date"].dt.date == target_date].copy()
    return enriched[enriched["date"] == target_date].copy()


def _threshold_context(day: pd.DataFrame, fields: tuple[str, ...]) -> dict[str, dict[str, float | int | None]]:
    out: dict[str, dict[str, float | int | None]] = {}
    for field in fields:
        if field not in day.columns:
            out[field] = {"count": 0, "min": None, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "max": None}
            continue
        numeric = pd.to_numeric(day[field], errors="coerce").dropna()
        if numeric.empty:
            out[field] = {"count": 0, "min": None, "p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "max": None}
            continue
        out[field] = {
            "count": int(numeric.count()),
            "min": float(numeric.min()),
            "p10": float(numeric.quantile(0.10)),
            "p25": float(numeric.quantile(0.25)),
            "p50": float(numeric.quantile(0.50)),
            "p75": float(numeric.quantile(0.75)),
            "p90": float(numeric.quantile(0.90)),
            "max": float(numeric.max()),
        }
    return out


def evaluate_strategy_day(
    day: pd.DataFrame,
    tier: str,
    *,
    stale_sources: tuple[str, ...] = (),
) -> dict:
    """Return fillability, filter diagnostics, and a readiness verdict for one day."""
    if tier not in AUDIT_CONFIGS:
        raise KeyError(f"Unsupported live strategy audit tier: {tier}")

    cfg = AUDIT_CONFIGS[tier]
    games = int(len(day))
    missing_columns = [field for field in cfg.required_fields if field not in day.columns]
    missing_by_field = {
        field: (games if field not in day.columns else int(day[field].isna().sum()))
        for field in cfg.required_fields
    }

    if games == 0 or missing_columns:
        usable_mask = pd.Series(False, index=day.index, dtype=bool)
    else:
        usable_mask = day[list(cfg.required_fields)].notna().all(axis=1)

    usable_rows = int(usable_mask.sum())
    usable_pct = (usable_rows / games) if games else 0.0

    filter_diagnostics: list[dict[str, int | str]] = []
    chained = day[usable_mask].copy()
    for filt in cfg.filters:
        if day.empty:
            standalone = pd.Series(dtype=bool)
        else:
            standalone = filt.predicate(day).fillna(False)
        chained = chained[filt.predicate(chained).fillna(False)] if not chained.empty else chained
        filter_diagnostics.append(
            {
                "label": filt.label,
                "standalone_pass_count": int(standalone.sum()),
                "chained_pass_count": int(len(chained)),
            }
        )
    raw_pass = int(len(chained))

    source_flags = {
        col: (int(day[col].fillna(False).astype(bool).sum()) if col in day.columns else 0)
        for col in cfg.source_flag_cols
    }
    insufficient_flags = {
        col: (int(day[col].fillna(False).astype(bool).sum()) if col in day.columns else 0)
        for col in cfg.insufficient_flag_cols
    }
    bridge_flags = {
        col: (int(day[col].fillna(False).astype(bool).sum()) if col in day.columns else 0)
        for col in cfg.bridge_flag_cols
    }

    source_gap_rows = pd.Series(False, index=day.index, dtype=bool)
    for col in cfg.source_flag_cols:
        if col in day.columns:
            source_gap_rows = source_gap_rows | day[col].fillna(False).astype(bool)
    source_gap_share = float(source_gap_rows.mean()) if games else 0.0

    warmup_rows = pd.Series(False, index=day.index, dtype=bool)
    for col in cfg.insufficient_flag_cols:
        if col in day.columns:
            warmup_rows = warmup_rows | day[col].fillna(False).astype(bool)
    for field in cfg.warmup_sparse_fields:
        if field in day.columns:
            warmup_rows = warmup_rows | day[field].isna()
    warmup_share = float(warmup_rows.mean()) if games else 0.0

    if games == 0:
        verdict = "no_games"
        detail = "no games on target date"
    elif missing_columns:
        verdict = "source_blocked"
        detail = f"required columns missing: {missing_columns}"
    elif stale_sources:
        verdict = "source_blocked"
        detail = f"stale sources: {list(stale_sources)}"
    elif source_gap_share > 0.10:
        verdict = "source_blocked"
        detail = f"source-gap rows {source_gap_share:.1%}"
    elif usable_pct < 0.70 and warmup_share > 0:
        verdict = "warmup_sparse"
        detail = f"usable={usable_rows}/{games}; warmup-sparse rows {warmup_share:.1%}"
    elif usable_pct < 0.70:
        verdict = "source_blocked"
        detail = f"usable={usable_rows}/{games} without warmup explanation"
    elif raw_pass == 0 and filter_diagnostics:
        strict_cutoff = max(1, int(round(games * 0.10)))
        scarce = [
            d["label"]
            for d in filter_diagnostics
            if int(d["standalone_pass_count"]) <= strict_cutoff
        ]
        if scarce:
            verdict = "strict_but_ready"
            detail = f"0 raw passes; scarce filters={scarce}"
        else:
            verdict = "ready_to_judge"
            detail = "0 raw passes, but no ultra-scarce standalone filter"
    else:
        verdict = "ready_to_judge"
        detail = f"usable={usable_rows}/{games}, raw_pass={raw_pass}"

    return {
        "tier": tier,
        "games": games,
        "required_fields": list(cfg.required_fields),
        "missing_columns": missing_columns,
        "usable_rows": usable_rows,
        "usable_pct": usable_pct,
        "missing_by_field": missing_by_field,
        "source_missing_flags": source_flags,
        "insufficient_history_flags": insufficient_flags,
        "bridge_missing_flags": bridge_flags,
        "filter_diagnostics": filter_diagnostics,
        "raw_pass": raw_pass,
        "threshold_context": _threshold_context(day, cfg.threshold_fields),
        "verdict": verdict,
        "verdict_detail": detail,
    }
