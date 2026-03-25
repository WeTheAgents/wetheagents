"""A/B test: Platt (sigmoid) vs Isotonic vs No calibration for UNDER model.

Same CatBoost+LR ensemble, same features (V1, 22), same walk-forward.
Only the calibration step differs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import warnings

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegressionCV
from sklearn.metrics import brier_score_loss, roc_auc_score

from src.data_loader import (
    add_derived_odds,
    apply_data_filters,
    enrich_innings_from_retrosheet,
    load_all_seasons,
)
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.model import UnderModelConfig, UnderFoldResult, walk_forward_splits

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

ODDS_UNDER = 1.909


def _impute_nan(X, medians):
    X = X.copy()
    for j in range(X.shape[1]):
        mask = np.isnan(X[:, j])
        if mask.any():
            X[mask, j] = medians[j]
    return X


def run_walk_forward_calibration_ab(df, features, cfg=None):
    """Walk-forward with 3 calibration methods in parallel."""
    if cfg is None:
        cfg = UnderModelConfig()

    seasons = sorted(df["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=5, max_train=cfg.max_train_seasons)

    results = {"platt": [], "isotonic": [], "none": []}

    for i, (train_s, val_s, test_s) in enumerate(folds):
        fold_name = f"fold_{i}_{val_s[0]}_{test_s[0]}-{test_s[-1]}"

        push_mask = df["is_push"] if "is_push" in df.columns else pd.Series(False, index=df.index)
        train_mask = df["season"].isin(train_s) & ~push_mask
        val_mask = df["season"].isin(val_s) & ~push_mask
        test_mask = df["season"].isin(test_s) & ~push_mask

        X_train = df.loc[train_mask, features].values.astype(float)
        y_train = df.loc[train_mask, "under_hit"].values.astype(int)
        X_val = df.loc[val_mask, features].values.astype(float)
        y_val = df.loc[val_mask, "under_hit"].values.astype(int)
        X_test = df.loc[test_mask, features].values.astype(float)
        y_test = df.loc[test_mask, "under_hit"].values.astype(int)

        if len(X_test) < 10:
            continue

        # NaN imputation
        train_medians = np.nanmedian(X_train, axis=0)
        train_medians = np.where(np.isnan(train_medians), 0.0, train_medians)
        X_train = _impute_nan(X_train, train_medians)
        X_val = _impute_nan(X_val, train_medians)
        X_test = _impute_nan(X_test, train_medians)

        # Train CatBoost (shared across all calibrations)
        cb = CatBoostClassifier(**cfg.catboost_params)
        cb.fit(X_train, y_train, eval_set=(X_val, y_val))

        # Train LR (shared)
        lr_model = None
        try:
            lr_model = LogisticRegressionCV(
                Cs=[0.01, 0.1, 1.0, 10.0], cv=5, max_iter=1000, random_state=42
            )
            lr_model.fit(X_train, y_train)
        except Exception:
            pass

        # Raw ensemble proba on val and test
        def ensemble_proba(X):
            cb_p = cb.predict_proba(X)[:, 1]
            if lr_model is not None:
                lr_p = lr_model.predict_proba(X)[:, 1]
                return cfg.ensemble_weight_catboost * cb_p + (1 - cfg.ensemble_weight_catboost) * lr_p
            return cb_p

        raw_val = ensemble_proba(X_val)
        raw_test = ensemble_proba(X_test)

        # === 3 calibration methods ===

        # 1. Platt (sigmoid via LR)
        try:
            platt = LogisticRegressionCV(
                Cs=[1e10], cv=3, solver="lbfgs", max_iter=1000, random_state=42
            )
            platt.fit(raw_val.reshape(-1, 1), y_val)
            p_platt = np.clip(platt.predict_proba(raw_test.reshape(-1, 1))[:, 1], 0, 1)
        except Exception:
            p_platt = raw_test

        # 2. Isotonic
        try:
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(raw_val, y_val)
            p_iso = np.clip(iso.predict(raw_test), 0, 1)
        except Exception:
            p_iso = raw_test

        # 3. None (raw ensemble)
        p_none = np.clip(raw_test, 0, 1)

        # Build results for each method
        meta_cols = ["season", "date", "home_team", "away_team", "close_ou",
                     "total_runs", "under_hit"]

        for method, p_test in [("platt", p_platt), ("isotonic", p_iso), ("none", p_none)]:
            test_auc = float(roc_auc_score(y_test, p_test))
            test_brier = float(brier_score_loss(y_test, p_test))

            # Val metrics with same calibration
            if method == "platt":
                p_val_cal = np.clip(platt.predict_proba(raw_val.reshape(-1, 1))[:, 1], 0, 1)
            elif method == "isotonic":
                p_val_cal = np.clip(iso.predict(raw_val), 0, 1)
            else:
                p_val_cal = np.clip(raw_val, 0, 1)

            val_auc = float(roc_auc_score(y_val, p_val_cal))
            val_brier = float(brier_score_loss(y_val, p_val_cal))

            preds_df = df.loc[test_mask, meta_cols].copy()
            preds_df["p_under"] = p_test

            results[method].append(UnderFoldResult(
                fold_name=fold_name,
                train_seasons=train_s,
                val_seasons=val_s,
                test_seasons=test_s,
                n_train=len(X_train),
                n_val=len(X_val),
                n_test=len(X_test),
                val_auc=val_auc,
                val_brier=val_brier,
                test_auc=test_auc,
                test_brier=test_brier,
                test_predictions=preds_df,
                p_under_threshold=float(np.percentile(p_test, 75)),
            ))

        logger.info(
            f"  {fold_name}: Platt AUC={results['platt'][-1].test_auc:.4f} "
            f"Iso AUC={results['isotonic'][-1].test_auc:.4f} "
            f"None AUC={results['none'][-1].test_auc:.4f}"
        )

    return results


def simulate_betting(fold_results, threshold):
    all_preds = pd.concat(
        [r.test_predictions for r in fold_results if r.test_predictions is not None],
        ignore_index=True,
    )
    bets = all_preds[all_preds["p_under"] >= threshold]
    if len(bets) == 0:
        return {"n_bets": 0, "hit_rate": 0.0, "roi": 0.0, "profit": 0.0}
    wins = bets["under_hit"].sum()
    n = len(bets)
    profit = wins * (ODDS_UNDER - 1) - (n - wins) * 1
    return {"n_bets": n, "hit_rate": wins / n, "roi": profit / n, "profit": profit}


def main():
    print("=" * 90)
    print("CALIBRATION A/B: Platt vs Isotonic vs None")
    print("=" * 90)

    logger.info("Loading data...")
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    ou = build_ou_features(enriched=enriched)
    features = [f for f in OU_FEATURES if f in ou.columns and ou[f].notna().mean() > 0.3]
    print(f"\nFeatures: {len(features)}/{len(OU_FEATURES)}")

    logger.info("Running walk-forward with 3 calibration methods...")
    results = run_walk_forward_calibration_ab(ou, features)

    # === Summary ===
    methods = ["platt", "isotonic", "none"]
    print("\n" + "=" * 90)
    print("SUMMARY: avg test metrics across 14 folds")
    print("=" * 90)
    print(f"  {'Method':<12} {'AUC':>8} {'Brier':>8} {'Std AUC':>9}")
    print("-" * 45)

    baseline_auc = np.mean([r.test_auc for r in results["platt"]])
    for m in methods:
        aucs = [r.test_auc for r in results[m]]
        briers = [r.test_brier for r in results[m]]
        d = np.mean(aucs) - baseline_auc
        label = "BASELINE" if m == "platt" else ("BETTER" if d > 0.001 else "WORSE" if d < -0.001 else "FLAT")
        print(f"  {m:<12} {np.mean(aucs):>8.4f} {np.mean(briers):>8.4f} {np.std(aucs):>9.4f}  {d:>+.4f} {label}")

    # === Per-fold ===
    print("\n" + "=" * 90)
    print("PER-FOLD AUC")
    print("=" * 90)
    print(f"  {'Fold':<25}" + "".join(f" {m:>10}" for m in methods))
    print("-" * 60)
    for i in range(len(results["platt"])):
        fold = results["platt"][i].fold_name
        vals = [results[m][i].test_auc for m in methods]
        best = max(vals)
        row = f"  {fold:<25}"
        for v in vals:
            marker = "*" if v == best else " "
            row += f" {v:>9.4f}{marker}"
        print(row)

    # === Per-fold Brier ===
    print("\n" + "=" * 90)
    print("PER-FOLD BRIER (lower is better)")
    print("=" * 90)
    print(f"  {'Fold':<25}" + "".join(f" {m:>10}" for m in methods))
    print("-" * 60)
    for i in range(len(results["platt"])):
        fold = results["platt"][i].fold_name
        vals = [results[m][i].test_brier for m in methods]
        best = min(vals)
        row = f"  {fold:<25}"
        for v in vals:
            marker = "*" if v == best else " "
            row += f" {v:>9.4f}{marker}"
        print(row)

    # === Betting ===
    print("\n" + "=" * 90)
    print("BETTING SIMULATION (flat $100 at -110)")
    print("=" * 90)
    for threshold in [0.52, 0.55, 0.58, 0.60]:
        print(f"\n  P(under) >= {threshold:.2f}:")
        for m in methods:
            s = simulate_betting(results[m], threshold)
            print(
                f"    {m:<10}: {s['n_bets']:>5} bets, "
                f"hit {s['hit_rate']*100:>5.1f}%, "
                f"ROI {s['roi']*100:>+6.1f}%, "
                f"P/L ${s['profit']:>+8.0f}"
            )

    # === Calibration curve ===
    print("\n" + "=" * 90)
    print("CALIBRATION CURVE (predicted P(under) bins vs actual hit rate)")
    print("=" * 90)
    bins = [(0.45, 0.50), (0.50, 0.52), (0.52, 0.55), (0.55, 0.58), (0.58, 0.62), (0.62, 1.00)]
    for m in methods:
        print(f"\n  {m}:")
        all_preds = pd.concat(
            [r.test_predictions for r in results[m] if r.test_predictions is not None],
            ignore_index=True,
        )
        for lo, hi in bins:
            mask = (all_preds["p_under"] >= lo) & (all_preds["p_under"] < hi)
            n = mask.sum()
            if n > 0:
                actual = all_preds.loc[mask, "under_hit"].mean()
                expected = all_preds.loc[mask, "p_under"].mean()
                gap = actual - expected
                print(f"    [{lo:.2f}-{hi:.2f}): n={n:>5}, predicted={expected*100:.1f}%, actual={actual*100:.1f}%, gap={gap*100:>+.1f}pp")
            else:
                print(f"    [{lo:.2f}-{hi:.2f}): n=    0")

    # === Verdict ===
    best = max(methods, key=lambda m: np.mean([r.test_auc for r in results[m]]))
    print(f"\n  BEST by AUC: {best}")
    best_brier = min(methods, key=lambda m: np.mean([r.test_brier for r in results[m]]))
    print(f"  BEST by Brier: {best_brier}")


if __name__ == "__main__":
    main()
