"""Dedicated OVER model experiment: asymmetric offensive features.

Variants:
  A) V3 baseline (21 features, target=over_hit) -- control, confirms zero signal
  B) OVER-dedicated (22 features: asymmetric offense + directional interactions)
  C) Minimal OVER (11 features: Tiers 1+3 only, no context/pitching vulnerability)

Decision gate:
  - If B at P(over)>=0.52 hits >52.4% AND ROI>0 AND >=7/15 seasons: production
  - If B at P(over)>=0.55 hits >55% AND ROI>0 but P>=0.52 fails: high-conf only
  - If nothing hits 52%: OVER ML is NOT viable, recommend LLM-only

Usage:
    python scripts/run_over_dedicated_model.py
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss

from src.data_loader import (
    add_derived_odds,
    apply_data_filters,
    load_all_seasons,
)
from src.features import (
    OU_FEATURES_V3,
    OU_FEATURES_OVER,
    OU_FEATURES_OVER_MINIMAL,
    build_all_features,
    build_ou_features_v3,
    build_ou_features_over,
)
from src.model import (
    UnderModelConfig,
    train_under_model,
    predict_under_proba,
    walk_forward_splits,
    UnderFoldResult,
)

OU_DECIMAL_ODDS = 1.909
BREAKEVEN = 1 / OU_DECIMAL_ODDS

# Session 19 removed features (for V3 baseline variant)
V3_REMOVED = {"close_ou", "combined_rpg_last10", "combined_rapg",
              "combined_rapg_last10", "pyth_wp_combined"}


def run_walk_forward_over(
    df: pd.DataFrame,
    features: list[str],
    *,
    cfg: UnderModelConfig = UnderModelConfig(),
    min_train: int = 5,
) -> list[UnderFoldResult]:
    """Walk-forward binary classification for P(over)."""
    seasons = sorted(df["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=min_train,
                                max_train=cfg.max_train_seasons)
    if not folds:
        return []

    logger.info(f"OVER walk-forward: {len(folds)} folds, {len(features)} features")
    results = []

    for i, (train_s, val_s, test_s) in enumerate(folds):
        fold_name = f"fold_{i}_{val_s[0]}_{test_s[0]}-{test_s[-1]}"

        # Swap target: train on over_hit instead of under_hit
        df_over = df.copy()
        df_over["under_hit"] = df_over["over_hit"]

        push_mask = df_over["is_push"] if "is_push" in df_over.columns else pd.Series(False, index=df_over.index)
        test_mask = df["season"].isin(test_s) & ~push_mask

        cb, lr_model, calibrator, metrics = train_under_model(
            df_over, features, train_s, val_s, cfg=cfg,
        )
        train_medians = metrics["train_medians"]

        n_test = int(test_mask.sum())
        if n_test < 10:
            continue

        X_test = df.loc[test_mask, features].values.astype(float)
        y_test = df.loc[test_mask, "over_hit"].values.astype(int)
        p_over = predict_under_proba(X_test, cb, lr_model, calibrator, train_medians, cfg=cfg)

        test_auc = float(roc_auc_score(y_test, p_over))
        test_brier = float(brier_score_loss(y_test, p_over))

        meta_cols = ["season", "date", "home_team", "away_team", "close_ou",
                     "total_runs", "over_hit", "under_hit"]
        meta_cols = [c for c in meta_cols if c in df.columns]
        preds_df = df.loc[test_mask, meta_cols].copy()
        preds_df["p_over"] = p_over

        results.append(UnderFoldResult(
            fold_name=fold_name,
            train_seasons=train_s,
            val_seasons=val_s,
            test_seasons=test_s,
            n_train=metrics["n_train"],
            n_val=metrics["n_val"],
            n_test=n_test,
            val_auc=metrics.get("val_auc", 0.0),
            val_brier=metrics.get("val_brier", 0.0),
            test_auc=test_auc,
            test_brier=test_brier,
            test_predictions=preds_df,
        ))

    logger.info(f"OVER walk-forward complete: {len(results)} folds")
    return results


def collect_predictions(results) -> pd.DataFrame:
    """Concatenate test predictions from all folds, exclude pushes."""
    dfs = [r.test_predictions for r in results if r.test_predictions is not None]
    if not dfs:
        return pd.DataFrame()
    preds = pd.concat(dfs, ignore_index=True)
    if "is_push" in preds.columns:
        preds = preds[~preds["is_push"]].copy()
    return preds


def simulate_over(preds: pd.DataFrame, threshold: float) -> dict:
    """Simulate flat-bet OVER at P(over) >= threshold."""
    bets = preds[preds["p_over"] >= threshold]
    n = len(bets)
    if n < 10:
        return {"n": n, "hit%": None, "roi%": None}

    hits = bets["over_hit"].sum()
    hr = hits / n
    profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
    roi = profit / (n * 100) * 100

    # Per-season
    season_rois = []
    for s in sorted(bets["season"].unique()):
        sm = bets[bets["season"] == s]
        sn = len(sm)
        if sn < 3:
            continue
        sh = sm["over_hit"].sum()
        sp = sh * (OU_DECIMAL_ODDS - 1) * 100 - (sn - sh) * 100
        season_rois.append(sp / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "n": n,
        "per_season": n / preds["season"].nunique(),
        "hit%": hr * 100,
        "roi%": roi,
        "profit": profit,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "worst": min(season_rois) if season_rois else None,
        "best": max(season_rois) if season_rois else None,
        "season_rois": season_rois,
    }


def print_calibration(preds: pd.DataFrame, name: str):
    """Print calibration curve: actual OVER rate by predicted P(over) bin."""
    bins = [0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.60]
    preds = preds.copy()
    preds["p_over_bin"] = pd.cut(preds["p_over"], bins=bins, right=False)
    cal = preds.groupby("p_over_bin", observed=True).agg(
        n=("over_hit", "size"),
        actual=("over_hit", "mean"),
    )
    print(f"\n  {name} calibration:")
    print(f"    {'P(over) bin':<15} {'N':>6} {'Actual':>8} {'Expected':>9} {'Gap':>7}")
    print(f"    {'-'*50}")
    for idx, row in cal.iterrows():
        if row["n"] < 10:
            continue
        mid = (idx.left + idx.right) / 2
        gap = row["actual"] - mid
        print(f"    {str(idx):<15} {int(row['n']):>6} {row['actual']*100:>7.1f}% {mid*100:>8.1f}% {gap*100:>+6.1f}%")


def main():
    print("=" * 90)
    print("DEDICATED OVER MODEL EXPERIMENT")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS}), breakeven {BREAKEVEN*100:.1f}%")
    print("=" * 90)

    # ── Load data once ────────────────────────────────────────────────────
    logger.info("Loading and enriching data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    # ── Build feature DataFrames ──────────────────────────────────────────
    logger.info("Building V3 features (for baseline)...")
    ou_v3 = build_ou_features_v3(enriched=enriched)

    logger.info("Building OVER-dedicated features...")
    ou_over = build_ou_features_over(enriched=enriched)

    # ── Resolve feature lists ─────────────────────────────────────────────
    feats_v3 = [f for f in OU_FEATURES_V3
                if f in ou_v3.columns and ou_v3[f].notna().mean() > 0.3 and f not in V3_REMOVED]

    feats_over = [f for f in OU_FEATURES_OVER
                  if f in ou_over.columns and ou_over[f].notna().mean() > 0.3]

    feats_minimal = [f for f in OU_FEATURES_OVER_MINIMAL
                     if f in ou_over.columns and ou_over[f].notna().mean() > 0.3]

    variants = [
        ("A) V3-baseline", ou_v3, feats_v3),
        ("B) OVER-dedicated", ou_over, feats_over),
        ("C) Minimal-OVER", ou_over, feats_minimal),
    ]

    print(f"\nFeature counts:")
    for name, df, feats in variants:
        print(f"  {name}: {len(feats)} features")
    print(f"\nB features: {feats_over}")
    print(f"C features: {feats_minimal}")

    # Check coverage for key new features
    print(f"\nFeature coverage (OVER-dedicated):")
    for f in OU_FEATURES_OVER:
        if f in ou_over.columns:
            cov = ou_over[f].notna().mean() * 100
            print(f"  {f:<40} {cov:>5.1f}%")
        else:
            print(f"  {f:<40}  MISSING")

    # ── Run walk-forward for each variant ─────────────────────────────────
    all_results = {}
    for name, df, feats in variants:
        logger.info(f"Running {name} ({len(feats)} features)...")
        results = run_walk_forward_over(df, feats)
        all_results[name] = results
        aucs = [r.test_auc for r in results]
        logger.info(f"  {name}: avg AUC={np.mean(aucs):.4f}")

    # ── AUC comparison ────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("AUC COMPARISON (test, predicting over_hit)")
    print("=" * 90)
    print(f"  {'Variant':<30} {'Feats':>5} {'AUC':>7} {'Brier':>7} {'Std':>7}")
    print("-" * 65)
    for name, _, feats in variants:
        res = all_results[name]
        aucs = [r.test_auc for r in res]
        briers = [r.test_brier for r in res]
        print(f"  {name:<30} {len(feats):>5} {np.mean(aucs):>7.4f} {np.mean(briers):>7.4f} {np.std(aucs):>7.4f}")

    # ── Betting simulation ────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("OVER BETTING SIMULATION (flat $100 at -110)")
    print("=" * 90)

    thresholds = [0.52, 0.53, 0.55, 0.58]
    for threshold in thresholds:
        print(f"\n  P(over) >= {threshold:.2f}:")
        print(f"    {'Variant':<30} {'Bets':>6} {'B/S':>5} {'Hit%':>7} {'ROI%':>8} {'P/L':>10} {'Flds':>6}")
        print(f"    {'-'*75}")
        for name, _, _ in variants:
            preds = collect_predictions(all_results[name])
            if preds.empty:
                continue
            s = simulate_over(preds, threshold)
            if s["hit%"] is None:
                print(f"    {name:<30} {s['n']:>6}  (too few)")
                continue
            print(f"    {name:<30} {s['n']:>6} {s['per_season']:>5.0f} {s['hit%']:>6.1f}% "
                  f"{s['roi%']:>+7.1f}% ${s['profit']:>+9.0f} {s['seasons_pos']:>6}")

    # ── Per-season detail for B (main hypothesis) ─────────────────────────
    print("\n" + "=" * 90)
    print("PER-SEASON ROI — B) OVER-dedicated")
    print("=" * 90)
    preds_b = collect_predictions(all_results["B) OVER-dedicated"])
    if not preds_b.empty:
        for t in thresholds:
            s = simulate_over(preds_b, t)
            if s.get("season_rois"):
                rois_str = ", ".join(f"{x:+.0f}" for x in s["season_rois"])
                print(f"  P(over)>={t:.2f}: [{rois_str}]")

    # ── Calibration curves ────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("CALIBRATION CURVES")
    print("=" * 90)
    for name, _, _ in variants:
        preds = collect_predictions(all_results[name])
        if not preds.empty:
            print_calibration(preds, name)

    # ── Monthly breakdown for B at P(over)>=0.53 ─────────────────────────
    print("\n" + "=" * 90)
    print("MONTHLY BREAKDOWN — B) OVER-dedicated, P(over)>=0.53")
    print("=" * 90)
    if not preds_b.empty:
        preds_b["month"] = pd.to_datetime(preds_b["date"]).dt.month
        over_bets = preds_b[preds_b["p_over"] >= 0.53].copy()
        month_names = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct"}
        print(f"\n  {'Month':<8} {'N':>5} {'Hit%':>7} {'ROI%':>8} {'P/L':>9}")
        print(f"  {'-'*45}")
        for m in range(4, 11):
            subset = over_bets[over_bets["month"] == m]
            n = len(subset)
            if n < 5:
                continue
            hits = subset["over_hit"].sum()
            hr = hits / n
            profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
            roi = profit / (n * 100) * 100
            print(f"  {month_names.get(m, str(m)):<8} {n:>5} {hr*100:>6.1f}% {roi:>+7.1f}% ${profit:>+8.0f}")

    # ── Feature importance for B ──────────────────────────────────────────
    print("\n" + "=" * 90)
    print("FEATURE IMPORTANCE — B) OVER-dedicated (last fold CatBoost)")
    print("=" * 90)
    res_b = all_results["B) OVER-dedicated"]
    if res_b:
        last_fold = res_b[-1]
        # Re-train last fold to get feature importance
        df_b = ou_over.copy()
        df_b["under_hit"] = df_b["over_hit"]
        cfg = UnderModelConfig()
        cb, _, _, _ = train_under_model(
            df_b, feats_over,
            last_fold.train_seasons, last_fold.val_seasons, cfg=cfg,
        )
        importances = cb.get_feature_importance()
        fi_pairs = sorted(zip(feats_over, importances), key=lambda x: -x[1])
        print(f"\n  {'Feature':<45} {'Importance':>10}")
        print(f"  {'-'*60}")
        for feat, imp in fi_pairs:
            print(f"  {feat:<45} {imp:>9.2f}%")

    # ── DECISION GATE ─────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("DECISION GATE")
    print("=" * 90)

    gate_passed = False
    gate_result = "FAIL"

    for name, _, _ in variants:
        preds = collect_predictions(all_results[name])
        if preds.empty:
            continue

        # Gate 1: P(over)>=0.52 with robust profitability
        s52 = simulate_over(preds, 0.52)
        if s52.get("hit%") and s52["hit%"] > BREAKEVEN * 100 and s52["roi%"] > 0:
            n_pos = int(s52["seasons_pos"].split("/")[0])
            n_total = int(s52["seasons_pos"].split("/")[1])
            if n_pos >= 7:
                print(f"  GATE 1 PASS: {name} at P(over)>=0.52")
                print(f"    {s52['n']} bets, {s52['hit%']:.1f}% hit, {s52['roi%']:+.1f}% ROI, {s52['seasons_pos']} seasons")
                gate_passed = True
                gate_result = "PRODUCTION"

        # Gate 2: P(over)>=0.55 high-confidence only
        s55 = simulate_over(preds, 0.55)
        if s55.get("hit%") and s55["hit%"] > 55.0 and s55["roi%"] > 0:
            n_pos = int(s55["seasons_pos"].split("/")[0])
            n_total = int(s55["seasons_pos"].split("/")[1])
            if n_pos >= 5:
                print(f"  GATE 2 PASS: {name} at P(over)>=0.55 (high-conf only)")
                print(f"    {s55['n']} bets, {s55['hit%']:.1f}% hit, {s55['roi%']:+.1f}% ROI, {s55['seasons_pos']} seasons")
                if not gate_passed:
                    gate_passed = True
                    gate_result = "HIGH_CONF_ONLY"

    if not gate_passed:
        print("  ALL GATES FAILED.")
        print("  VERDICT: OVER ML pre-filter is NOT viable with current features.")
        print()
        print("  Recommendations:")
        print("    1. Pure LLM expert gate for OVER (OffenseFirst + FatigueExploit genomes)")
        print("       Run on ALL games where P(under)<0.50, no ML pre-filter")
        print("    2. Rules-based heuristic pre-filter:")
        print("       bp_fip_osc > 0.5 (either side) AND power_rate_max > 0.35 AND rpg_vs_line > 0")
        print("    3. Focus portfolio on UNDER (proven +30% ROI at P>=0.55)")
        gate_result = "FAIL"

    print(f"\n  Final gate result: {gate_result}")
    print("=" * 90)


if __name__ == "__main__":
    main()
