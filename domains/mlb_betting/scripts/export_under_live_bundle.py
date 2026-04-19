"""Train and export the live UNDER totals model bundle."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features import OU_FEATURES, build_ou_features
from src.model import UnderModelConfig, predict_under_proba, train_under_model
from src.under_live import (
    UNDER_BASE_THRESHOLD,
    UNDER_LIVE_SEASONS,
    UNDER_MODEL_PATH,
    UNDER_MODIFIER_QUANTILES,
    UNDER_POWER_THRESHOLD,
    UNDER_SUMMARY_PATH,
    UNDER_TRAIN_SEASONS,
    UNDER_VAL_SEASONS,
    save_under_live_bundle,
)
from src.under_reporting import (
    MODIFIER_FIP_COL,
    MODIFIER_IP_COL,
    compute_calibration_summary,
    compute_reliability_table,
    evaluate_under_threshold,
    run_under_walk_forward_single_year,
    scan_under_modifier_candidates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _summary_path_json_default(value):
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _feature_list(frame: pd.DataFrame) -> list[str]:
    return [feature for feature in OU_FEATURES if feature in frame.columns and frame[feature].notna().mean() > 0.3]


def main() -> int:
    logger.info("Building O/U feature frame for live UNDER export...")
    full = build_ou_features()
    full = full[full["season"] <= max(UNDER_VAL_SEASONS)].copy()

    features = _feature_list(full)
    logger.info("Features available for UNDER bundle: %d/%d", len(features), len(OU_FEATURES))

    cfg = UnderModelConfig()
    cb_model, lr_model, _, metrics = train_under_model(
        full,
        features,
        UNDER_TRAIN_SEASONS,
        UNDER_VAL_SEASONS,
        cfg=cfg,
    )

    train_mask = full["season"].isin(UNDER_TRAIN_SEASONS) & ~full["is_push"]
    val_mask = full["season"].isin(UNDER_VAL_SEASONS) & ~full["is_push"]
    train_preds = full.loc[train_mask, ["season", "date", "home_team", "away_team", "under_hit"]].copy()
    val_preds = full.loc[val_mask, ["season", "date", "home_team", "away_team", "under_hit", "close_ou_odds_under"]].copy()

    train_proba = predict_under_proba(
        full.loc[train_mask, features].to_numpy(dtype=float),
        cb_model,
        lr_model,
        None,
        metrics["train_medians"],
        cfg=cfg,
    )
    val_proba = predict_under_proba(
        full.loc[val_mask, features].to_numpy(dtype=float),
        cb_model,
        lr_model,
        None,
        metrics["train_medians"],
        cfg=cfg,
    )
    train_preds["p_under"] = train_proba
    val_preds["p_under"] = val_proba

    walk_forward_preds = run_under_walk_forward_single_year(full, features, cfg=cfg)
    official_preds = walk_forward_preds[walk_forward_preds["season"].between(2021, 2025)].copy()
    bridge_preds = walk_forward_preds[walk_forward_preds["season"].between(2010, 2025)].copy()

    modifier_scan = scan_under_modifier_candidates(
        official_preds,
        odds_col="close_ou_odds_under",
        fallback_decimal=None,
    )
    train_modifier_thresholds = {
        label: {
            "bullpen_ip_3d_combined": float(full.loc[train_mask, MODIFIER_IP_COL].quantile(q)),
            "bullpen_fip_7g_combined": float(full.loc[train_mask, MODIFIER_FIP_COL].quantile(q)),
        }
        for label, q in UNDER_MODIFIER_QUANTILES.items()
    }

    selected_live = modifier_scan.get("selected")
    shadow_candidate = None
    if modifier_scan.get("candidates"):
        shadow_candidate = max(
            modifier_scan["candidates"],
            key=lambda row: row["roi_delta_pct_points"],
        )

    modifier_metadata = {
        "name": "bullpen_stress_marginal_veto",
        "metric_columns": [MODIFIER_IP_COL, MODIFIER_FIP_COL],
        "base_threshold": UNDER_BASE_THRESHOLD,
        "power_threshold": UNDER_POWER_THRESHOLD,
        "quantiles_tested": train_modifier_thresholds,
        "official_scan": modifier_scan,
        "apply_live": bool(modifier_scan.get("apply_live")),
        "selected_quantile_label": (
            selected_live["quantile_label"] if selected_live is not None else None
        ),
        "selected_thresholds_live": (
            train_modifier_thresholds[selected_live["quantile_label"]]
            if selected_live is not None
            else None
        ),
        "shadow_quantile_label": (
            shadow_candidate["quantile_label"] if shadow_candidate is not None else None
        ),
        "shadow_thresholds_live": (
            train_modifier_thresholds[shadow_candidate["quantile_label"]]
            if shadow_candidate is not None
            else None
        ),
    }

    thresholds = {
        "under_totals": UNDER_BASE_THRESHOLD,
        "under_totals_power": UNDER_POWER_THRESHOLD,
    }
    summary = {
        "bundle": "under_totals_live",
        "train_seasons": UNDER_TRAIN_SEASONS,
        "val_seasons": UNDER_VAL_SEASONS,
        "live_seasons": UNDER_LIVE_SEASONS,
        "features": features,
        "train_metrics": {
            **compute_calibration_summary(train_preds),
            "n_games": int(train_mask.sum()),
        },
        "val_metrics": {
            **compute_calibration_summary(val_preds),
            "n_games": int(val_mask.sum()),
        },
        "official_real_odds_2021_2025": {
            "calibration": compute_calibration_summary(official_preds),
            "reliability_table": compute_reliability_table(official_preds).to_dict(orient="records"),
            "thresholds": {
                "under_totals": evaluate_under_threshold(
                    official_preds,
                    label="under_totals",
                    min_prob=UNDER_BASE_THRESHOLD,
                    odds_col="close_ou_odds_under",
                    fallback_decimal=None,
                ).__dict__,
                "under_totals_power": evaluate_under_threshold(
                    official_preds,
                    label="under_totals_power",
                    min_prob=UNDER_POWER_THRESHOLD,
                    odds_col="close_ou_odds_under",
                    fallback_decimal=None,
                ).__dict__,
            },
        },
        "bridge_flat_110_2010_2025": {
            "calibration": compute_calibration_summary(bridge_preds),
            "thresholds": {
                "under_totals": evaluate_under_threshold(
                    bridge_preds,
                    label="under_totals",
                    min_prob=UNDER_BASE_THRESHOLD,
                ).__dict__,
                "under_totals_power": evaluate_under_threshold(
                    bridge_preds,
                    label="under_totals_power",
                    min_prob=UNDER_POWER_THRESHOLD,
                ).__dict__,
            },
        },
        "modifier": modifier_scan,
    }

    lr_coefficients = None
    lr_intercept = None
    if lr_model is not None:
        lr_coefficients = np.asarray(lr_model.coef_, dtype=float).reshape(-1)
        lr_intercept = float(np.asarray(lr_model.intercept_, dtype=float).reshape(-1)[0])

    save_under_live_bundle(
        cb_model=cb_model,
        features=features,
        train_medians=np.asarray(metrics["train_medians"], dtype=float),
        ensemble_weight_catboost=cfg.ensemble_weight_catboost,
        lr_coefficients=lr_coefficients,
        lr_intercept=lr_intercept,
        train_seasons=UNDER_TRAIN_SEASONS,
        val_seasons=UNDER_VAL_SEASONS,
        live_seasons=UNDER_LIVE_SEASONS,
        thresholds=thresholds,
        summary_metrics={
            "train": summary["train_metrics"],
            "val": summary["val_metrics"],
            "official_real_odds_2021_2025": summary["official_real_odds_2021_2025"]["thresholds"],
        },
        modifier=modifier_metadata,
        model_path=UNDER_MODEL_PATH,
    )
    UNDER_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, default=_summary_path_json_default),
        encoding="utf-8",
    )

    logger.info("Saved UNDER live model -> %s", UNDER_MODEL_PATH)
    logger.info("Saved UNDER live summary -> %s", UNDER_SUMMARY_PATH)
    if selected_live is not None:
        logger.info(
            "Live modifier enabled: %s (ROI delta %+0.2fpp, DD delta %+0.2fpp)",
            selected_live["quantile_label"],
            selected_live["roi_delta_pct_points"],
            selected_live["drawdown_delta_pct_points"],
        )
    else:
        logger.info("Live modifier disabled; leaving veto in shadow/advisory mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
