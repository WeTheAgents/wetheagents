"""Shared reporting helpers for UNDER totals validation and live rollout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from src.data_loader import american_to_decimal
from src.model import (
    UnderModelConfig,
    predict_under_proba,
    train_under_model,
    walk_forward_splits,
)
from src.under_live import (
    UNDER_BASE_THRESHOLD,
    UNDER_FALLBACK_DECIMAL,
    UNDER_MODIFIER_QUANTILES,
    UNDER_POWER_THRESHOLD,
)

MODIFIER_IP_COL = "bullpen_ip_3d_combined"
MODIFIER_FIP_COL = "bullpen_fip_7g_combined"
MERGE_KEYS = ["season", "date", "home_team", "away_team"]


@dataclass
class UnderThresholdMetrics:
    label: str
    bets: int
    hit_rate: float
    roi_pct: float
    avg_decimal_odds: float | None
    cumulative_units: float
    max_drawdown_units: float
    max_drawdown_pct: float
    longest_loss_streak: int
    longest_win_streak: int
    season_roi_pct: dict[int, float]


def _max_streak(outcomes: np.ndarray, *, target: int) -> int:
    best = current = 0
    for value in outcomes.astype(int):
        if value == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _resolve_decimal_odds(
    frame: pd.DataFrame,
    *,
    odds_col: str | None,
    fallback_decimal: float | None,
) -> pd.Series:
    if odds_col is None or odds_col not in frame.columns:
        if fallback_decimal is None:
            return pd.Series(np.nan, index=frame.index, dtype=float)
        return pd.Series(float(fallback_decimal), index=frame.index, dtype=float)

    odds = pd.to_numeric(frame[odds_col], errors="coerce")
    decimal = odds.where(odds.notna(), np.nan).apply(
        lambda value: american_to_decimal(value) if pd.notna(value) else np.nan
    )
    if fallback_decimal is not None:
        decimal = decimal.where(decimal.notna(), float(fallback_decimal))
    return decimal


def compute_reliability_table(
    preds: pd.DataFrame,
    *,
    prob_col: str = "p_under",
    y_col: str = "under_hit",
    n_bins: int = 10,
) -> pd.DataFrame:
    """Reliability table on equal-width probability bins."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    rows: list[dict[str, Any]] = []
    for idx in range(n_bins):
        lo = bins[idx]
        hi = bins[idx + 1]
        if idx == n_bins - 1:
            mask = (preds[prob_col] >= lo) & (preds[prob_col] <= hi)
        else:
            mask = (preds[prob_col] >= lo) & (preds[prob_col] < hi)
        bucket = preds.loc[mask]
        if bucket.empty:
            continue
        mean_pred = float(bucket[prob_col].mean())
        actual = float(bucket[y_col].mean())
        rows.append(
            {
                "bin_index": idx,
                "bin_lo": lo,
                "bin_hi": hi,
                "bin_center": (lo + hi) / 2.0,
                "n_games": int(len(bucket)),
                "mean_predicted": mean_pred,
                "actual_rate": actual,
                "gap": actual - mean_pred,
                "abs_gap_weighted": abs(actual - mean_pred) * len(bucket),
            }
        )
    return pd.DataFrame(rows)


def compute_calibration_summary(
    preds: pd.DataFrame,
    *,
    prob_col: str = "p_under",
    y_col: str = "under_hit",
) -> dict[str, Any]:
    """AUC/Brier/LogLoss/ECE summary for a prediction frame."""
    if preds.empty:
        return {
            "n_predictions": 0,
            "auc": np.nan,
            "brier": np.nan,
            "logloss": np.nan,
            "ece_10": np.nan,
        }

    y_true = preds[y_col].astype(int).to_numpy()
    y_prob = np.clip(preds[prob_col].astype(float).to_numpy(), 1e-7, 1 - 1e-7)
    reliability = compute_reliability_table(preds, prob_col=prob_col, y_col=y_col)
    ece = (
        float(reliability["abs_gap_weighted"].sum() / len(preds))
        if not reliability.empty
        else np.nan
    )
    auc = np.nan
    if len(np.unique(y_true)) >= 2:
        auc = float(roc_auc_score(y_true, y_prob))
    return {
        "n_predictions": int(len(preds)),
        "auc": auc,
        "brier": float(brier_score_loss(y_true, y_prob)),
        "logloss": float(log_loss(y_true, y_prob)),
        "ece_10": ece,
    }


def evaluate_under_threshold(
    preds: pd.DataFrame,
    *,
    label: str,
    min_prob: float,
    max_prob: float | None = None,
    odds_col: str | None = None,
    fallback_decimal: float | None = UNDER_FALLBACK_DECIMAL,
) -> UnderThresholdMetrics:
    """Compute ROI + drawdown metrics for a thresholded UNDER portfolio."""
    mask = preds["p_under"] >= min_prob
    if max_prob is not None:
        mask &= preds["p_under"] < max_prob
    subset = preds.loc[mask].copy()

    if subset.empty:
        return UnderThresholdMetrics(
            label=label,
            bets=0,
            hit_rate=np.nan,
            roi_pct=np.nan,
            avg_decimal_odds=np.nan,
            cumulative_units=0.0,
            max_drawdown_units=0.0,
            max_drawdown_pct=0.0,
            longest_loss_streak=0,
            longest_win_streak=0,
            season_roi_pct={},
        )

    subset["bet_decimal"] = _resolve_decimal_odds(
        subset,
        odds_col=odds_col,
        fallback_decimal=fallback_decimal,
    )
    subset = subset[subset["bet_decimal"].notna()].copy()
    if subset.empty:
        return UnderThresholdMetrics(
            label=label,
            bets=0,
            hit_rate=np.nan,
            roi_pct=np.nan,
            avg_decimal_odds=np.nan,
            cumulative_units=0.0,
            max_drawdown_units=0.0,
            max_drawdown_pct=0.0,
            longest_loss_streak=0,
            longest_win_streak=0,
            season_roi_pct={},
        )

    subset = subset.sort_values(["date", "away_team", "home_team"]).reset_index(drop=True)
    hit = subset["under_hit"].astype(int).to_numpy()
    decimal = subset["bet_decimal"].astype(float).to_numpy()
    pnl = np.where(hit == 1, decimal - 1.0, -1.0)
    cum_pnl = np.cumsum(pnl)
    bankroll = 100.0 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    drawdown_units = np.maximum.accumulate(cum_pnl) - cum_pnl
    drawdown_pct = np.where(peak > 0.0, (peak - bankroll) / peak * 100.0, 0.0)

    season_roi_pct: dict[int, float] = {}
    for season, group in subset.groupby("season"):
        g_hit = group["under_hit"].astype(int).to_numpy()
        g_decimal = group["bet_decimal"].astype(float).to_numpy()
        g_pnl = np.where(g_hit == 1, g_decimal - 1.0, -1.0)
        season_roi_pct[int(season)] = float(g_pnl.mean() * 100.0)

    return UnderThresholdMetrics(
        label=label,
        bets=int(len(subset)),
        hit_rate=float(hit.mean()),
        roi_pct=float(pnl.mean() * 100.0),
        avg_decimal_odds=float(decimal.mean()) if len(decimal) else np.nan,
        cumulative_units=float(cum_pnl[-1]) if len(cum_pnl) else 0.0,
        max_drawdown_units=float(drawdown_units.max()) if len(drawdown_units) else 0.0,
        max_drawdown_pct=float(drawdown_pct.max()) if len(drawdown_pct) else 0.0,
        longest_loss_streak=_max_streak(hit, target=0),
        longest_win_streak=_max_streak(hit, target=1),
        season_roi_pct=season_roi_pct,
    )


def run_under_walk_forward_single_year(
    df: pd.DataFrame,
    features: list[str],
    *,
    cfg: UnderModelConfig | None = None,
    min_train: int = 5,
    modifier_quantiles: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Single-year walk-forward predictions with fold-specific modifier bands."""
    cfg = cfg or UnderModelConfig()
    modifier_quantiles = modifier_quantiles or UNDER_MODIFIER_QUANTILES

    seasons = sorted(df["season"].dropna().astype(int).unique().tolist())
    folds = walk_forward_splits(
        seasons,
        min_train=min_train,
        max_train=cfg.max_train_seasons,
        test_size=1,
    )
    if not folds:
        return pd.DataFrame()

    all_preds: list[pd.DataFrame] = []
    push_mask = df["is_push"] if "is_push" in df.columns else pd.Series(False, index=df.index)
    for fold_index, (train_s, val_s, test_s) in enumerate(folds):
        cb_model, lr_model, calibrator, metrics = train_under_model(
            df,
            features,
            train_s,
            val_s,
            cfg=cfg,
        )
        train_medians = metrics["train_medians"]

        test_mask = df["season"].isin(test_s) & ~push_mask
        if int(test_mask.sum()) == 0:
            continue

        X_test = df.loc[test_mask, features].to_numpy(dtype=float)
        p_under = predict_under_proba(
            X_test,
            cb_model,
            lr_model,
            calibrator,
            train_medians,
            cfg=cfg,
        )

        preds = df.loc[
            test_mask,
            [
                "season",
                "date",
                "home_team",
                "away_team",
                "close_ou",
                "close_ou_odds_under",
                "total_runs",
                "under_hit",
                MODIFIER_IP_COL,
                MODIFIER_FIP_COL,
            ],
        ].copy()
        preds["p_under"] = p_under
        preds["fold_index"] = fold_index
        preds["fold_name"] = f"fold_{fold_index}_{val_s[0]}_{test_s[0]}"
        preds["train_seasons"] = [list(train_s)] * len(preds)
        preds["val_seasons"] = [list(val_s)] * len(preds)
        preds["test_seasons"] = [list(test_s)] * len(preds)
        preds["val_auc"] = metrics.get("val_auc", np.nan)
        preds["val_brier"] = metrics.get("val_brier", np.nan)
        preds["val_logloss"] = metrics.get("val_logloss", np.nan)

        y_test = df.loc[test_mask, "under_hit"].astype(int).to_numpy()
        preds["test_auc"] = (
            float(roc_auc_score(y_test, p_under))
            if len(np.unique(y_test)) >= 2
            else np.nan
        )
        preds["test_brier"] = float(brier_score_loss(y_test, p_under))
        preds["test_logloss"] = float(log_loss(y_test, np.clip(p_under, 1e-7, 1 - 1e-7)))

        train_frame = df.loc[df["season"].isin(train_s) & ~push_mask]
        for label, q in modifier_quantiles.items():
            preds[f"modifier_ip_{label}"] = float(train_frame[MODIFIER_IP_COL].quantile(q))
            preds[f"modifier_fip_{label}"] = float(train_frame[MODIFIER_FIP_COL].quantile(q))
        all_preds.append(preds)

    if not all_preds:
        return pd.DataFrame()

    out = pd.concat(all_preds, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out = out.sort_values(["date", "season", "away_team", "home_team", "fold_index"])
    out = out.drop_duplicates(subset=MERGE_KEYS, keep="last").reset_index(drop=True)
    return out


def scan_under_modifier_candidates(
    preds: pd.DataFrame,
    *,
    odds_col: str | None,
    fallback_decimal: float | None = None,
    quantile_labels: list[str] | None = None,
    base_threshold: float = UNDER_BASE_THRESHOLD,
    power_threshold: float = UNDER_POWER_THRESHOLD,
) -> dict[str, Any]:
    """Evaluate marginal-band bullpen veto candidates and choose a live verdict."""
    quantile_labels = quantile_labels or list(UNDER_MODIFIER_QUANTILES)

    baseline = evaluate_under_threshold(
        preds,
        label=f"P>= {base_threshold:.2f}",
        min_prob=base_threshold,
        odds_col=odds_col,
        fallback_decimal=fallback_decimal,
    )
    marginal = evaluate_under_threshold(
        preds,
        label=f"{base_threshold:.2f} <= P < {power_threshold:.2f}",
        min_prob=base_threshold,
        max_prob=power_threshold,
        odds_col=odds_col,
        fallback_decimal=fallback_decimal,
    )
    baseline_positive_seasons = {
        season for season, roi in baseline.season_roi_pct.items() if roi > 0.0
    }

    candidates: list[dict[str, Any]] = []
    marginal_mask = (preds["p_under"] >= base_threshold) & (preds["p_under"] < power_threshold)
    marginal_count = int(marginal_mask.sum())

    for label in quantile_labels:
        ip_col = f"modifier_ip_{label}"
        fip_col = f"modifier_fip_{label}"
        if ip_col not in preds.columns or fip_col not in preds.columns:
            continue

        veto_mask = (
            marginal_mask
            & preds[MODIFIER_IP_COL].gt(preds[ip_col])
            & preds[MODIFIER_FIP_COL].gt(preds[fip_col])
        )
        kept = preds.loc[~veto_mask].copy()
        kept_marginal = int((marginal_mask & ~veto_mask).sum())
        candidate = evaluate_under_threshold(
            kept,
            label=f"modifier_{label}",
            min_prob=base_threshold,
            odds_col=odds_col,
            fallback_decimal=fallback_decimal,
        )

        roi_delta = candidate.roi_pct - baseline.roi_pct
        dd_delta = candidate.max_drawdown_pct - baseline.max_drawdown_pct
        volume_retained = (
            kept_marginal / marginal_count if marginal_count > 0 else np.nan
        )
        positive_flip = False
        for season in baseline_positive_seasons:
            if candidate.season_roi_pct.get(season, 0.0) < 0.0:
                positive_flip = True
                break

        pass_live = (
            roi_delta >= 2.0
            and dd_delta <= 1.0
            and (np.isnan(volume_retained) or volume_retained >= 0.70)
            and not positive_flip
        )
        candidates.append(
            {
                "quantile_label": label,
                "threshold": UNDER_MODIFIER_QUANTILES.get(label),
                "baseline_roi_pct": baseline.roi_pct,
                "candidate_roi_pct": candidate.roi_pct,
                "roi_delta_pct_points": roi_delta,
                "baseline_max_drawdown_pct": baseline.max_drawdown_pct,
                "candidate_max_drawdown_pct": candidate.max_drawdown_pct,
                "drawdown_delta_pct_points": dd_delta,
                "marginal_bets": marginal_count,
                "marginal_kept": kept_marginal,
                "volume_retained": volume_retained,
                "positive_season_flip": positive_flip,
                "pass_live": pass_live,
                "candidate_metrics": candidate.__dict__,
            }
        )

    selected = None
    passing = [row for row in candidates if row["pass_live"]]
    if passing:
        selected = max(
            passing,
            key=lambda row: (
                row["roi_delta_pct_points"],
                -row["drawdown_delta_pct_points"],
                row["volume_retained"],
            ),
        )

    return {
        "baseline_metrics": baseline.__dict__,
        "marginal_metrics": marginal.__dict__,
        "candidates": candidates,
        "selected": selected,
        "apply_live": selected is not None,
    }
