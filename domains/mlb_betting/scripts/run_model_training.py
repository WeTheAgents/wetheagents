"""End-to-end training: features -> regime models -> evaluation -> divergence.

Usage:
    python scripts/run_model_training.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    from src.data_loader import (
        add_derived_odds,
        apply_data_filters,
        enrich_innings_from_retrosheet,
        load_all_seasons,
    )
    from src.features import SPEC_FEATURES, build_all_features, build_spec_features
    from src.model import REGIMES, ModelConfig, compute_divergence, run_walk_forward

    # ── Step 1: Build features ───────────────────────────────────────────
    logger.info("=" * 70)
    logger.info(f"STEP 1: Building spec features ({len(SPEC_FEATURES)} features)")
    logger.info("=" * 70)
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    df = build_spec_features(enriched=enriched)

    logger.info(f"\nDataset: {len(df)} games, seasons {df['season'].min()}-{df['season'].max()}")
    logger.info(f"Regimes: {df['regime'].value_counts().to_dict()}")

    # Feature coverage
    for f in SPEC_FEATURES:
        if f in df.columns:
            pct = df[f].notna().mean() * 100
            logger.info(f"  {f}: {pct:.1f}% non-null")
        else:
            logger.info(f"  {f}: MISSING")

    # Target stats
    target = "closing_decimal_odds_favorite"
    logger.info(f"\nTarget ({target}):")
    logger.info(f"  mean={df[target].mean():.3f}, std={df[target].std():.3f}")
    logger.info(f"  range=[{df[target].min():.3f}, {df[target].max():.3f}]")

    # ── Step 2: Walk-forward training ────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info("STEP 2: Walk-forward training (CatBoost + Ridge, 4 regimes)")
    logger.info("=" * 70)

    features_available = [f for f in SPEC_FEATURES if f in df.columns and df[f].notna().mean() > 0.3]
    logger.info(f"Using {len(features_available)} features: {features_available}")

    cfg = ModelConfig()
    fold_results = run_walk_forward(df, features_available, target, cfg=cfg)

    # ── Step 3: Summary ──────────────────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info("STEP 3: Results Summary")
    logger.info("=" * 70)

    summary_rows = []
    for r in fold_results:
        summary_rows.append({
            "fold": r.fold_name,
            "regime": r.regime,
            "n_train": r.n_train,
            "n_val": r.n_val,
            "n_test": r.n_test,
            "val_RMSE": r.val_rmse,
            "val_MAE": r.val_mae,
            "test_RMSE": r.test_rmse,
            "test_MAE": r.test_mae,
        })
    summary = pd.DataFrame(summary_rows)
    logger.info("\n" + summary.to_string(index=False))

    # Average metrics per regime
    logger.info("\n--- Average metrics by regime ---")
    for regime in REGIMES:
        regime_results = summary[summary["regime"] == regime]
        if regime_results.empty:
            continue
        avg_test_rmse = regime_results["test_RMSE"].mean()
        avg_test_mae = regime_results["test_MAE"].mean()
        logger.info(f"  {regime}: avg test RMSE={avg_test_rmse:.4f}, MAE={avg_test_mae:.4f}")

    # Naive baseline: predict mean closing odds
    naive_pred = df[target].mean()
    naive_rmse = float(np.sqrt(((df[target] - naive_pred) ** 2).mean()))
    logger.info(f"\n  Naive (mean) baseline: RMSE={naive_rmse:.4f}")

    # ── Step 4: Divergence analysis ──────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info("STEP 4: Divergence Analysis")
    logger.info("=" * 70)

    div_df = compute_divergence(fold_results)
    if div_df.empty:
        logger.info("No divergence data available (need ≥2 regime predictions)")
    else:
        logger.info(f"Divergence computed for {len(div_df)} test games")
        logger.info(f"  div_range: mean={div_df['div_range'].mean():.4f}, "
                     f"std={div_df['div_range'].std():.4f}")
        logger.info(f"  div_std:   mean={div_df['div_std'].mean():.4f}")

        # High vs low divergence analysis
        median_div = div_df["div_range"].median()
        high_div = div_df[div_df["div_range"] > median_div]
        low_div = div_df[div_df["div_range"] <= median_div]

        target_col = "closing_decimal_odds_favorite"
        if target_col in div_df.columns:
            pred_cols = [c for c in div_df.columns if c.startswith("pred_")]
            if pred_cols:
                # Check if high-divergence games have higher prediction error
                avg_pred = div_df[pred_cols].mean(axis=1)
                div_df["avg_pred_error"] = (div_df[target_col] - avg_pred).abs()

                high_err = div_df.loc[div_df["div_range"] > median_div, "avg_pred_error"].mean()
                low_err = div_df.loc[div_df["div_range"] <= median_div, "avg_pred_error"].mean()
                logger.info(f"\n  High-divergence games: avg error = {high_err:.4f}")
                logger.info(f"  Low-divergence games:  avg error = {low_err:.4f}")
                logger.info(f"  -> {'Divergence correlates with uncertainty' if high_err > low_err else 'Divergence does NOT correlate with uncertainty'}")

        # Regime distribution in high-div vs low-div
        if "regime" in div_df.columns:
            logger.info("\n  Regime distribution:")
            logger.info(f"  High div: {high_div['regime'].value_counts().to_dict()}")
            logger.info(f"  Low div:  {low_div['regime'].value_counts().to_dict()}")

    logger.info("\n" + "=" * 70)
    logger.info("DONE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
