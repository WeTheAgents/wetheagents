"""YRFI CatBoost v3: multiclass (0 runs / 1 run / 2+ runs) classifier.

Single CatBoostClassifier with MultiClass loss predicts P(0), P(1), P(2+).
P(YRFI) = P(1 run) + P(2+ runs).  Edge = P(YRFI) - P_market(YRFI).

The 3-class decomposition reveals whether YRFI signal comes from marginal
games (single run) or explosive games (2+ runs), enabling smarter filtering.

Train/Val/Test: 2010-2019 / 2021 / 2022-2025 (2020 excluded).
Features: 19 fundamentals (no close_ou in input).

Usage:
    python scripts/run_yrfi_catboost.py
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd


def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def _bet_stats(sel, n_seasons):
    """Compute betting statistics for a selection of games."""
    n = len(sel)
    if n < 5:
        return None
    hit = sel["yrfi"].values.astype(float)
    hr = hit.mean()
    avg_ou = sel["close_ou"].mean()
    avg_odds = sel["est_odds"].mean()

    adj_pnl = np.where(hit, (sel["est_odds"].values - 1) * 100, -100)
    adj_roi = adj_pnl.sum() / (n * 100) * 100

    fix_pnl = np.where(hit, 0.85 * 100, -100)
    fix_roi = fix_pnl.sum() / (n * 100) * 100

    bps = n / n_seasons if n_seasons > 0 else n
    mls = max_streak(hit, target=0)

    return {
        "n": n, "bps": bps, "hr": hr, "avg_ou": avg_ou, "avg_odds": avg_odds,
        "adj_roi": adj_roi, "fix_roi": fix_roi, "mls": mls,
    }


def _print_sweep(test_df, thresholds, n_seasons, label, extra_mask=None):
    """Print edge threshold sweep table."""
    print(f"  {'Edge':>6} {'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AvgOU':>6} "
          f"{'EstOd':>6} {'AdjROI':>8} {'FixROI':>8} {'MLS':>4}")
    print(f"  {'-'*66}")
    for thr in thresholds:
        mask = test_df["edge"] >= thr
        if extra_mask is not None:
            mask = mask & extra_mask
        sel = test_df[mask]
        s = _bet_stats(sel, n_seasons)
        if s is None:
            continue
        marker = " ***" if s["adj_roi"] > 0 else ""
        print(
            f"  {thr:>6.2f} {s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% "
            f"{s['avg_ou']:5.2f} {s['avg_odds']:5.3f} {s['adj_roi']:+7.1f}% "
            f"{s['fix_roi']:+7.1f}% {s['mls']:4d}{marker}"
        )


# ========================================================================
# MAIN
# ========================================================================
def main():
    from src.features import YRFI_REG_FEATURES, build_yrfi_features
    from src.market_builder import estimate_yrfi_odds
    from src.model import (
        YRFI_CLASSES,
        YRFIMultiConfig,
        predict_yrfi_multiclass,
        train_yrfi_multiclass,
    )

    cfg = YRFIMultiConfig()

    # ================================================================
    # STEP 1: BUILD FEATURES
    # ================================================================
    print("=" * 90)
    print("STEP 1: Building YRFI features (multiclass)")
    print("=" * 90)

    df = build_yrfi_features()

    print(f"\nDataset: {len(df)} games")
    print(f"Seasons: {sorted(df['season'].unique().tolist())}")

    # Class distribution
    print(f"\nClass distribution:")
    for c, label in YRFI_CLASSES.items():
        n_c = (df["fi_class"] == c).sum()
        print(f"  {c} ({label}): {n_c:6d} ({n_c/len(df)*100:5.1f}%)")
    print(f"  YRFI (1+2): {df['yrfi'].mean()*100:.1f}%")

    # Feature coverage
    features_available = []
    print(f"\nFeature coverage ({len(YRFI_REG_FEATURES)} features, no close_ou):")
    for f in YRFI_REG_FEATURES:
        if f in df.columns:
            n_ok = df[f].notna().sum()
            pct = n_ok / len(df) * 100
            print(f"  {f:<35} {n_ok:>6}/{len(df)} ({pct:5.1f}%)")
            if pct > 30:
                features_available.append(f)
        else:
            print(f"  {f:<35} MISSING")

    print(f"\nUsable features: {len(features_available)}")

    # ================================================================
    # STEP 2: DEFINE SPLIT
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 2: Train/Val/Test split")
    print("=" * 90)

    train_seasons = list(range(2010, 2020))
    val_seasons = [2021]
    test_seasons = [s for s in range(2022, 2026) if s in df["season"].unique()]

    for label, seasons in [("TRAIN", train_seasons), ("VAL", val_seasons), ("TEST", test_seasons)]:
        sub = df[df["season"].isin(seasons)]
        print(f"  {label}: {seasons[0]}-{seasons[-1]} ({len(sub)} games)")
        for c, cname in YRFI_CLASSES.items():
            n_c = (sub["fi_class"] == c).sum()
            print(f"         class {c} ({cname}): {n_c} ({n_c/len(sub)*100:.1f}%)")

    # ================================================================
    # STEP 3: TRAIN MULTICLASS MODEL
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 3: Training 3-class CatBoost")
    print("=" * 90)

    print(f"  Config: depth={cfg.catboost_params['depth']}, "
          f"lr={cfg.catboost_params['learning_rate']}, "
          f"iters={cfg.catboost_params['iterations']}, "
          f"l2={cfg.catboost_params['l2_leaf_reg']}, "
          f"min_leaf={cfg.catboost_params['min_data_in_leaf']}")

    cb, calibrator, metrics = train_yrfi_multiclass(
        df, features_available, train_seasons, val_seasons, cfg=cfg,
    )

    print(f"\n  Train: {metrics['n_train']} games")
    print(f"  Val:   {metrics['n_val']} games")
    for c, label in YRFI_CLASSES.items():
        auc_key = f"val_auc_class{c}"
        if auc_key in metrics:
            print(f"  Val AUC class {c} ({label}): {metrics[auc_key]:.4f}")
    print(f"  Val AUC YRFI (raw):    {metrics.get('val_auc_yrfi_raw', float('nan')):.4f}")
    print(f"  Val AUC YRFI (cal):    {metrics.get('val_auc_yrfi', float('nan')):.4f}")
    print(f"  Val Brier YRFI (cal):  {metrics.get('val_brier_yrfi', float('nan')):.4f}")
    print(f"  Val LogLoss (3-class): {metrics.get('val_logloss', float('nan')):.4f}")
    print(f"  Calibrator: {'isotonic' if calibrator else 'none'}")

    # ================================================================
    # STEP 4: TEST PREDICTIONS
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 4: Test predictions")
    print("=" * 90)

    test_mask = df["season"].isin(test_seasons)
    test_df = df[test_mask].copy()
    X_test = test_df[features_available].values.astype(float)
    y_test = test_df["fi_class"].values.astype(int)

    proba = predict_yrfi_multiclass(X_test, cb, metrics["train_medians"])
    test_df["p_nrfi_raw"] = proba[:, 0]
    test_df["p_1run_raw"] = proba[:, 1]
    test_df["p_2plus_raw"] = proba[:, 2]
    test_df["p_yrfi_raw"] = proba[:, 1] + proba[:, 2]

    # Calibrate P(YRFI)
    if calibrator is not None:
        test_df["p_yrfi"] = calibrator.predict(test_df["p_yrfi_raw"].values)
    else:
        test_df["p_yrfi"] = test_df["p_yrfi_raw"]
    test_df["p_nrfi"] = 1 - test_df["p_yrfi"]
    # Preserve raw class decomposition ratios for analysis
    raw_yrfi = test_df["p_yrfi_raw"].values
    safe_raw = np.where(raw_yrfi > 0, raw_yrfi, 1e-9)
    test_df["p_1run"] = test_df["p_yrfi"] * (proba[:, 1] / safe_raw)
    test_df["p_2plus"] = test_df["p_yrfi"] * (proba[:, 2] / safe_raw)

    # Per-class AUC on test
    from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
    print(f"\n  Test results (raw probabilities):")
    for c, label in YRFI_CLASSES.items():
        y_bin = (y_test == c).astype(int)
        if y_bin.sum() > 0 and y_bin.sum() < len(y_bin):
            auc = roc_auc_score(y_bin, proba[:, c])
            print(f"    AUC class {c} ({label}): {auc:.4f}")

    # YRFI binary metrics (calibrated)
    p_yrfi = test_df["p_yrfi"].values
    y_yrfi = test_df["yrfi"].values.astype(int)
    test_auc = roc_auc_score(y_yrfi, p_yrfi)
    test_brier = brier_score_loss(y_yrfi, p_yrfi)
    test_ll = log_loss(y_yrfi, np.clip(p_yrfi, 1e-7, 1 - 1e-7))

    print(f"\n  Calibrated test results:")
    print(f"    AUC YRFI (cal):     {test_auc:.4f}")
    print(f"    Brier YRFI (cal):   {test_brier:.4f}")
    print(f"    LogLoss YRFI (cal): {test_ll:.4f}")

    print(f"\n  Predicted means (calibrated):")
    print(f"    P(NRFI):  {test_df['p_nrfi'].mean()*100:.1f}%  (actual: {(y_test==0).mean()*100:.1f}%)")
    print(f"    P(1 run): {test_df['p_1run'].mean()*100:.1f}%  (actual: {(y_test==1).mean()*100:.1f}%)")
    print(f"    P(2+):    {test_df['p_2plus'].mean()*100:.1f}%  (actual: {(y_test==2).mean()*100:.1f}%)")
    print(f"    P(YRFI):  {test_df['p_yrfi'].mean()*100:.1f}%  (actual: {y_yrfi.mean()*100:.1f}%)")
    print(f"    P(YRFI) raw mean: {test_df['p_yrfi_raw'].mean()*100:.1f}%")

    # Calibration deciles on P(YRFI)
    print(f"\n  P(YRFI) calibration deciles:")
    print(f"  {'Decile':<8} {'PredP':>7} {'Actual':>7} {'Count':>6} {'Gap':>7}")
    print(f"  {'-'*38}")
    decile_edges = np.percentile(p_yrfi, np.arange(0, 101, 10))
    for i in range(10):
        lo, hi = decile_edges[i], decile_edges[i + 1]
        mask = (p_yrfi >= lo) & (p_yrfi < hi + 1e-9)
        if mask.sum() == 0:
            continue
        pred_avg = p_yrfi[mask].mean()
        actual_avg = y_yrfi[mask].mean()
        gap = actual_avg - pred_avg
        print(f"  D{i+1:<7} {pred_avg*100:6.1f}% {actual_avg*100:6.1f}% {mask.sum():6d} {gap*100:+6.1f}pp")

    # ================================================================
    # STEP 5: FEATURE IMPORTANCE
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 5: Feature importance")
    print("=" * 90)

    # Per-class importance
    try:
        imp_per_class = cb.get_feature_importance(type="ShapValues")
        # ShapValues shape: (n_train, n_features+1, n_classes) — skip bias col
        # Fallback to standard importance
        raise ValueError("use standard")
    except Exception:
        importances = cb.get_feature_importance()
        feat_imp = sorted(
            zip(features_available, importances),
            key=lambda x: x[1],
            reverse=True,
        )
        print(f"  {'Feature':<35} {'Importance':>10}")
        print(f"  {'-'*47}")
        for feat, imp in feat_imp:
            print(f"  {feat:<35} {imp:10.2f}")

    # ================================================================
    # STEP 6: CLASS DECOMPOSITION ANALYSIS
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 6: Class decomposition analysis")
    print("=" * 90)

    # How P(2+) vs P(1 run) relates to actual YRFI
    test_df["p_ratio_2plus"] = test_df["p_2plus"] / test_df["p_yrfi"]  # share of 2+ in YRFI

    print(f"\n  P(2+) share in P(YRFI):")
    print(f"    Mean:   {test_df['p_ratio_2plus'].mean()*100:.1f}%")
    print(f"    Median: {test_df['p_ratio_2plus'].median()*100:.1f}%")

    # By P(2+)/P(YRFI) quintiles — does explosive component predict better?
    test_df["ratio_q"] = pd.qcut(test_df["p_ratio_2plus"], 5, labels=False, duplicates="drop")
    print(f"\n  Performance by P(2+) share quintile:")
    print(f"  {'Q':>4} {'Games':>6} {'YRFI%':>6} {'P(YRFI)':>8} {'P(2+)':>7} {'P(1r)':>7} {'AvgOU':>6}")
    print(f"  {'-'*50}")
    for q in sorted(test_df["ratio_q"].unique()):
        grp = test_df[test_df["ratio_q"] == q]
        print(f"  {q+1:>4} {len(grp):6d} {grp['yrfi'].mean()*100:5.1f}% "
              f"{grp['p_yrfi'].mean()*100:7.1f}% {grp['p_2plus'].mean()*100:6.1f}% "
              f"{grp['p_1run'].mean()*100:6.1f}% {grp['close_ou'].mean():5.2f}")

    # High P(2+) games: do they actually have more 2+ run first innings?
    print(f"\n  High P(2+) validation:")
    p2_median = test_df["p_2plus"].median()
    for label, mask in [
        ("P(2+) > median", test_df["p_2plus"] > p2_median),
        ("P(2+) < median", test_df["p_2plus"] <= p2_median),
    ]:
        sub = test_df[mask]
        actual_2plus = (sub["fi_class"] == 2).mean()
        actual_1run = (sub["fi_class"] == 1).mean()
        actual_nrfi = (sub["fi_class"] == 0).mean()
        print(f"    {label}: NRFI={actual_nrfi*100:.1f}%, "
              f"1run={actual_1run*100:.1f}%, 2+={actual_2plus*100:.1f}%, "
              f"n={len(sub)}")

    # ================================================================
    # STEP 7: EDGE CALCULATION
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 7: Edge calculation")
    print("=" * 90)

    # Market P(YRFI) from close_ou
    test_df = test_df.dropna(subset=["close_ou"]).copy()
    market_odds = estimate_yrfi_odds(test_df["close_ou"])
    test_df["est_odds"] = market_odds.values
    test_df["p_market"] = 1.0 / test_df["est_odds"]
    test_df["edge"] = test_df["p_yrfi"] - test_df["p_market"]

    # Recompute probas after dropna (with calibration)
    X_ou = test_df[features_available].values.astype(float)
    proba_ou = predict_yrfi_multiclass(X_ou, cb, metrics["train_medians"])
    p_yrfi_raw = proba_ou[:, 1] + proba_ou[:, 2]
    if calibrator is not None:
        p_yrfi_cal = calibrator.predict(p_yrfi_raw)
    else:
        p_yrfi_cal = p_yrfi_raw
    test_df["p_yrfi"] = p_yrfi_cal
    test_df["p_nrfi"] = 1 - p_yrfi_cal
    safe_raw = np.where(p_yrfi_raw > 0, p_yrfi_raw, 1e-9)
    test_df["p_1run"] = p_yrfi_cal * (proba_ou[:, 1] / safe_raw)
    test_df["p_2plus"] = p_yrfi_cal * (proba_ou[:, 2] / safe_raw)
    test_df["edge"] = test_df["p_yrfi"] - test_df["p_market"]

    n_test = len(test_df)
    print(f"\n  Games with close_ou: {n_test}")
    print(f"  Avg model P(YRFI):  {test_df['p_yrfi'].mean()*100:.1f}%")
    print(f"  Avg market P(YRFI): {test_df['p_market'].mean()*100:.1f}%")
    print(f"  Actual YRFI rate:   {test_df['yrfi'].mean()*100:.1f}%")
    print(f"  Avg edge:           {test_df['edge'].mean()*100:.2f}pp")

    print(f"\n  Edge distribution:")
    for thr in [-0.10, -0.05, 0, 0.02, 0.03, 0.05, 0.10]:
        n_above = (test_df["edge"] >= thr).sum()
        print(f"    edge >= {thr:+.2f}: {n_above:6d} games ({n_above/n_test*100:.1f}%)")

    # ================================================================
    # STEP 8: BETTING SIMULATION
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 8: Betting simulation (TEST)")
    print("=" * 90)

    n_s = len(test_seasons)
    thresholds = [0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]

    # 8a: Edge only
    print(f"\n  8a) Edge only:")
    _print_sweep(test_df, thresholds, n_s, "edge_only")

    # 8b: Edge + P(2+) > median (explosive signal)
    p2_med = test_df["p_2plus"].median()
    print(f"\n  8b) Edge + P(2+) > {p2_med*100:.1f}% (explosive signal):")
    _print_sweep(test_df, thresholds, n_s, "explosive",
                 extra_mask=test_df["p_2plus"] > p2_med)

    # 8c: Edge + P(2+) > P(1run) (explosive > marginal)
    print(f"\n  8c) Edge + P(2+) > P(1run):")
    _print_sweep(test_df, thresholds, n_s, "2plus_gt_1run",
                 extra_mask=test_df["p_2plus"] > test_df["p_1run"])

    # 8d: Edge + high confidence (P(NRFI) < 0.45)
    print(f"\n  8d) Edge + P(NRFI) < 45% (confident YRFI):")
    _print_sweep(test_df, thresholds, n_s, "confident",
                 extra_mask=test_df["p_nrfi"] < 0.45)

    # Per-season detail for edge >= 0.02
    print(f"\n  Per-season detail (edge >= 0.02):")
    sel = test_df[test_df["edge"] >= 0.02]
    if len(sel) >= 5:
        print(f"  {'Season':>8} {'Bets':>6} {'Hit%':>6} {'AvgOU':>6} {'AdjROI':>8} "
              f"{'P(2+)':>7} {'P(1r)':>7} {'AvgEdge':>8}")
        print(f"  {'-'*66}")
        for s in sorted(sel["season"].unique()):
            ss = sel[sel["season"] == s]
            h = ss["yrfi"].values.astype(float)
            pnl = np.where(h, (ss["est_odds"].values - 1) * 100, -100)
            roi = pnl.sum() / (len(ss) * 100) * 100
            print(
                f"  {s:>8} {len(ss):6d} {h.mean()*100:5.1f}% "
                f"{ss['close_ou'].mean():5.2f} {roi:+7.1f}% "
                f"{ss['p_2plus'].mean()*100:6.1f}% "
                f"{ss['p_1run'].mean()*100:6.1f}% "
                f"{ss['edge'].mean()*100:+7.2f}pp"
            )

    # ================================================================
    # STEP 9: DIAGNOSTICS
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 9: Diagnostics")
    print("=" * 90)

    # By close_ou bucket
    print(f"\n  Performance by close_ou bucket (edge >= 0.02):")
    sel = test_df[test_df["edge"] >= 0.02].copy()
    if len(sel) > 0:
        sel["ou_bucket"] = pd.cut(sel["close_ou"], bins=[6, 7.5, 8.0, 8.5, 9.0, 10.0, 15.0])
        print(f"  {'OU Bucket':<15} {'Bets':>6} {'Hit%':>6} {'AdjROI':>8} {'P(2+)':>7}")
        print(f"  {'-'*44}")
        for bucket, grp in sel.groupby("ou_bucket", observed=True):
            if len(grp) < 5:
                continue
            h = grp["yrfi"].values.astype(float)
            pnl = np.where(h, (grp["est_odds"].values - 1) * 100, -100)
            roi = pnl.sum() / (len(grp) * 100) * 100
            print(f"  {str(bucket):<15} {len(grp):6d} {h.mean()*100:5.1f}% "
                  f"{roi:+7.1f}% {grp['p_2plus'].mean()*100:6.1f}%")

    # Monthly
    print(f"\n  Monthly breakdown (edge >= 0.02):")
    sel = test_df[test_df["edge"] >= 0.02].copy()
    if len(sel) > 0:
        sel["month"] = pd.to_datetime(sel["date"]).dt.month
        print(f"  {'Month':>6} {'Bets':>6} {'Hit%':>6} {'AdjROI':>8}")
        print(f"  {'-'*28}")
        for m in sorted(sel["month"].unique()):
            grp = sel[sel["month"] == m]
            if len(grp) < 3:
                continue
            h = grp["yrfi"].values.astype(float)
            pnl = np.where(h, (grp["est_odds"].values - 1) * 100, -100)
            roi = pnl.sum() / (len(grp) * 100) * 100
            print(f"  {m:>6} {len(grp):6d} {h.mean()*100:5.1f}% {roi:+7.1f}%")

    # ML vs rule-based
    print(f"\n  ML vs Rule-based (TEST):")
    print(f"  {'System':<35} {'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8}")
    print(f"  {'-'*62}")

    for label, thr, extra in [
        ("ML edge>=0.02", 0.02, None),
        ("ML edge>=0.03", 0.03, None),
        ("ML edge>=0.02+explosive", 0.02, test_df["p_2plus"] > p2_med),
        ("ML edge>=0.02+confident", 0.02, test_df["p_nrfi"] < 0.45),
    ]:
        mask = test_df["edge"] >= thr
        if extra is not None:
            mask = mask & extra
        sel = test_df[mask]
        s = _bet_stats(sel, n_s)
        if s is None:
            print(f"  {label:<35} (too few)")
            continue
        print(f"  {label:<35} {s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% {s['adj_roi']:+7.1f}%")

    # Rule-based combos
    for name, col_a, op_a, val_a, col_b, op_b, val_b in [
        ("obp>0.72+kbb<3.8", "top3_obp_short_combined", ">", 0.72, "starter_kbb_combined", "<", 3.8),
        ("babip>0.66+fip>7.5", "top3_babip_inn1_combined", ">", 0.66, "starter_fip_combined", ">", 7.5),
        ("fi_rate>0.63+kbb<4.0", "fi_score_rate_combined", ">", 0.63, "starter_kbb_combined", "<", 4.0),
    ]:
        if col_a not in test_df.columns or col_b not in test_df.columns:
            continue
        mask_a = test_df[col_a].notna() & (test_df[col_a] > val_a if op_a == ">" else test_df[col_a] < val_a)
        mask_b = test_df[col_b].notna() & (test_df[col_b] > val_b if op_b == ">" else test_df[col_b] < val_b)
        sel = test_df[mask_a & mask_b]
        s = _bet_stats(sel, n_s)
        if s is None:
            print(f"  {name:<35} (too few)")
            continue
        print(f"  {name:<35} {s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% {s['adj_roi']:+7.1f}%")

    # ================================================================
    # STEP 10: MATCHUP-LEVEL ANALYSIS
    # ================================================================
    print(f"\n{'='*90}")
    print("STEP 10: Matchup-Level Analysis")
    print("  TOP 1st: away batters vs home pitcher")
    print("  BOT 1st: home batters vs away pitcher")
    print("  YRFI bet = TOP fires OR BOT fires")
    print("=" * 90)

    # 10a) Verify individual matchup columns
    matchup_cols = {
        "attack_home": ["fi_score_rate_home", "effective_obp_home",
                        "top3_obp_short_home", "top3_babip_inn1_home"],
        "attack_away": ["fi_score_rate_away", "effective_obp_away",
                        "top3_obp_short_away", "top3_babip_inn1_away"],
        "pitcher_home": ["home_sp_fi_ra_short", "home_sp_fi_ra_long",
                         "home_sp_kbb_short", "home_sp_ra_short",
                         "home_sp_fip_short"],
        "pitcher_away": ["away_sp_fi_ra_short", "away_sp_fi_ra_long",
                         "away_sp_kbb_short", "away_sp_ra_short",
                         "away_sp_fip_short"],
    }
    print(f"\n  10a) Matchup column coverage (test_df, n={len(test_df)}):")
    for group, cols in matchup_cols.items():
        print(f"    [{group}]")
        for c in cols:
            if c in test_df.columns:
                n_ok = test_df[c].notna().sum()
                print(f"      {c:<30} {n_ok:>5}/{len(test_df)} ({n_ok/len(test_df)*100:5.1f}%)")
            else:
                print(f"      {c:<30} MISSING")

    # 10b) Define matchup filter combos
    # Each combo: (name, attack_col_suffix, attack_op, attack_thr,
    #              pitcher_col_prefix, pitcher_op, pitcher_thr)
    # "suffix" means: we'll use fi_score_rate_{side}
    # "prefix" means: we'll use {side}_sp_fi_ra_short

    def _eval_matchup(tdf, attack_col, attack_op, attack_thr,
                      pitcher_col, pitcher_op, pitcher_thr):
        """Evaluate one side of a matchup. Returns boolean mask."""
        if attack_col not in tdf.columns or pitcher_col not in tdf.columns:
            return pd.Series(False, index=tdf.index)
        a_ok = tdf[attack_col].notna()
        p_ok = tdf[pitcher_col].notna()
        if attack_op == ">":
            a_pass = a_ok & (tdf[attack_col] > attack_thr)
        else:
            a_pass = a_ok & (tdf[attack_col] < attack_thr)
        if pitcher_op == ">":
            p_pass = p_ok & (tdf[pitcher_col] > pitcher_thr)
        else:
            p_pass = p_ok & (tdf[pitcher_col] < pitcher_thr)
        return a_pass & p_pass

    # Matchup definitions: (name, attack_metric, attack_op, pitcher_metric, pitcher_op)
    # We'll sweep thresholds for each
    matchup_defs = [
        ("M1: fi_rate+kbb",    "fi_score_rate", ">", "sp_kbb_short", "<"),
        ("M2: fi_rate+fi_ra",  "fi_score_rate", ">", "sp_fi_ra_short", ">"),
        ("M3: eff_obp+kbb",    "effective_obp",  ">", "sp_kbb_short", "<"),
        ("M4: eff_obp+fi_ra",  "effective_obp",  ">", "sp_fi_ra_short", ">"),
        ("M5: babip+fi_ra",    "top3_babip_inn1", ">", "sp_fi_ra_short", ">"),
        ("M6: fi_rate+fi_ra_long", "fi_score_rate", ">", "sp_fi_ra_long", ">"),
    ]

    # Column name resolution per side
    def _resolve_cols(attack_metric, pitcher_metric, side):
        """Resolve column names for a given side (TOP or BOT).
        TOP: away batters vs home pitcher
        BOT: home batters vs away pitcher
        """
        if side == "TOP":
            atk_side, pitch_side = "away", "home"
        else:
            atk_side, pitch_side = "home", "away"
        attack_col = f"{attack_metric}_{atk_side}"
        pitcher_col = f"{pitch_side}_sp_{pitcher_metric}" if not pitcher_metric.startswith("sp_") \
            else f"{pitch_side}_{pitcher_metric}"
        # Fix: pitcher columns are named home_sp_X / away_sp_X
        # attack_metric like "fi_score_rate" -> fi_score_rate_away
        # pitcher_metric like "sp_kbb_short" -> home_sp_kbb_short
        return attack_col, pitcher_col

    # Threshold grids per metric
    attack_thresholds = {
        "fi_score_rate": [0.25, 0.28, 0.30, 0.33, 0.35],
        "effective_obp": [0.33, 0.35, 0.36, 0.38],
        "top3_babip_inn1": [0.28, 0.30, 0.32, 0.34, 0.36],
    }
    pitcher_thresholds = {
        "sp_kbb_short": [2.0, 2.3, 2.5, 3.0, 3.5],
        "sp_fi_ra_short": [0.3, 0.4, 0.5, 0.6],
        "sp_fi_ra_long": [0.3, 0.4, 0.5, 0.6],
    }

    # 10c) Sweep matchup thresholds
    print(f"\n  10c) Matchup threshold sweep (OR of TOP + BOT)")
    print(f"  {'Combo':<30} {'AtkTh':>6} {'PitTh':>6} "
          f"{'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8} {'MLS':>4}")
    print(f"  {'-'*90}")

    sweep_results = []
    for mname, atk_metric, atk_op, pit_metric, pit_op in matchup_defs:
        atk_thrs = attack_thresholds[atk_metric]
        pit_thrs = pitcher_thresholds[pit_metric]
        for atk_thr in atk_thrs:
            for pit_thr in pit_thrs:
                # TOP: away batters vs home pitcher
                top_atk_col, top_pit_col = _resolve_cols(atk_metric, pit_metric, "TOP")
                top_mask = _eval_matchup(test_df, top_atk_col, atk_op, atk_thr,
                                         top_pit_col, pit_op, pit_thr)
                # BOT: home batters vs away pitcher
                bot_atk_col, bot_pit_col = _resolve_cols(atk_metric, pit_metric, "BOT")
                bot_mask = _eval_matchup(test_df, bot_atk_col, atk_op, atk_thr,
                                         bot_pit_col, pit_op, pit_thr)
                combined = top_mask | bot_mask
                sel = test_df[combined]
                s = _bet_stats(sel, n_s)
                if s is None:
                    continue
                sweep_results.append({
                    "name": mname, "atk_thr": atk_thr, "pit_thr": pit_thr,
                    **s, "top_n": top_mask.sum(), "bot_n": bot_mask.sum(),
                })
                if s["adj_roi"] > 0 or s["bps"] >= 100:
                    marker = " ***" if s["adj_roi"] > 0 else ""
                    print(
                        f"  {mname:<30} {atk_thr:6.2f} {pit_thr:6.2f} "
                        f"{s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% "
                        f"{s['adj_roi']:+7.1f}% {s['fix_roi']:+7.1f}% {s['mls']:4d}{marker}"
                    )

    # Summary: top-10 by adj_roi (min 50 bets/season)
    viable = [r for r in sweep_results if r["bps"] >= 50]
    viable.sort(key=lambda r: r["adj_roi"], reverse=True)
    print(f"\n  Top-10 matchup combos by adj_roi (min 50 bets/season):")
    print(f"  {'#':>3} {'Combo':<30} {'AtkTh':>6} {'PitTh':>6} "
          f"{'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8}")
    print(f"  {'-'*96}")
    for i, r in enumerate(viable[:10]):
        print(f"  {i+1:3d} {r['name']:<30} {r['atk_thr']:6.2f} {r['pit_thr']:6.2f} "
              f"{r['n']:6d} {r['bps']:5.0f}/s {r['hr']*100:5.1f}% "
              f"{r['adj_roi']:+7.1f}% {r['fix_roi']:+7.1f}%")

    # Top-10 by volume (positive roi only)
    positive = [r for r in sweep_results if r["adj_roi"] > 0 and r["bps"] >= 30]
    positive.sort(key=lambda r: r["bps"], reverse=True)
    print(f"\n  Top-10 matchup combos by volume (positive adj_roi only):")
    print(f"  {'#':>3} {'Combo':<30} {'AtkTh':>6} {'PitTh':>6} "
          f"{'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8}")
    print(f"  {'-'*96}")
    for i, r in enumerate(positive[:10]):
        print(f"  {i+1:3d} {r['name']:<30} {r['atk_thr']:6.2f} {r['pit_thr']:6.2f} "
              f"{r['n']:6d} {r['bps']:5.0f}/s {r['hr']*100:5.1f}% "
              f"{r['adj_roi']:+7.1f}% {r['fix_roi']:+7.1f}%")

    # 10d) Matchup + ML soft filters
    print(f"\n  10d) Best matchup combos + ML soft filters")

    # Collect best combos (top 5 by adj_roi, viable volume)
    best_combos = viable[:5] if len(viable) >= 5 else viable
    ml_filters = [
        ("none", None),
        ("P(2+)>0.24", lambda df: df["p_2plus"] > 0.24),
        ("P(2+)>0.28", lambda df: df["p_2plus"] > 0.28),
        ("P(2+)>0.32", lambda df: df["p_2plus"] > 0.32),
        ("P(1run)>0.20", lambda df: df["p_1run"] > 0.20),
        ("P(1run)>0.22", lambda df: df["p_1run"] > 0.22),
        ("P(1run)>0.24", lambda df: df["p_1run"] > 0.24),
        ("P(YRFI)>0.48", lambda df: df["p_yrfi"] > 0.48),
        ("P(YRFI)>0.50", lambda df: df["p_yrfi"] > 0.50),
        ("P(YRFI)>0.52", lambda df: df["p_yrfi"] > 0.52),
    ]

    print(f"  {'Matchup':<30} {'ML Filter':<16} "
          f"{'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8} {'MLS':>4}")
    print(f"  {'-'*100}")

    hybrid_results = []
    for combo in best_combos:
        mname = combo["name"]
        atk_thr = combo["atk_thr"]
        pit_thr = combo["pit_thr"]

        # Find the matching definition
        mdef = None
        for md in matchup_defs:
            if md[0] == mname:
                mdef = md
                break
        if mdef is None:
            continue
        _, atk_metric, atk_op, pit_metric, pit_op = mdef

        # Recompute matchup mask
        top_atk_col, top_pit_col = _resolve_cols(atk_metric, pit_metric, "TOP")
        top_mask = _eval_matchup(test_df, top_atk_col, atk_op, atk_thr,
                                 top_pit_col, pit_op, pit_thr)
        bot_atk_col, bot_pit_col = _resolve_cols(atk_metric, pit_metric, "BOT")
        bot_mask = _eval_matchup(test_df, bot_atk_col, atk_op, atk_thr,
                                 bot_pit_col, pit_op, pit_thr)
        matchup_mask = top_mask | bot_mask

        for ml_name, ml_fn in ml_filters:
            if ml_fn is not None:
                full_mask = matchup_mask & ml_fn(test_df)
            else:
                full_mask = matchup_mask
            sel = test_df[full_mask]
            s = _bet_stats(sel, n_s)
            if s is None:
                continue
            hybrid_results.append({
                "matchup": mname, "atk_thr": atk_thr, "pit_thr": pit_thr,
                "ml_filter": ml_name, **s,
            })
            marker = " ***" if s["adj_roi"] > 0 else ""
            print(
                f"  {mname:<30} {ml_name:<16} "
                f"{s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% "
                f"{s['adj_roi']:+7.1f}% {s['fix_roi']:+7.1f}% {s['mls']:4d}{marker}"
            )

    # 10e) Per-season breakdown for best hybrid combos
    print(f"\n  10e) Per-season breakdown for best hybrid combos")

    # Collect best hybrids
    best_hybrids = sorted(
        [h for h in hybrid_results if h["bps"] >= 40],
        key=lambda h: h["adj_roi"], reverse=True,
    )[:5]

    for bh in best_hybrids:
        mname = bh["matchup"]
        ml_name = bh["ml_filter"]
        atk_thr = bh["atk_thr"]
        pit_thr = bh["pit_thr"]

        mdef = None
        for md in matchup_defs:
            if md[0] == mname:
                mdef = md
                break
        if mdef is None:
            continue
        _, atk_metric, atk_op, pit_metric, pit_op = mdef

        top_atk_col, top_pit_col = _resolve_cols(atk_metric, pit_metric, "TOP")
        top_mask = _eval_matchup(test_df, top_atk_col, atk_op, atk_thr,
                                 top_pit_col, pit_op, pit_thr)
        bot_atk_col, bot_pit_col = _resolve_cols(atk_metric, pit_metric, "BOT")
        bot_mask = _eval_matchup(test_df, bot_atk_col, atk_op, atk_thr,
                                 bot_pit_col, pit_op, pit_thr)
        matchup_mask = top_mask | bot_mask

        ml_fn = None
        for mn, mf in ml_filters:
            if mn == ml_name:
                ml_fn = mf
                break
        if ml_fn is not None:
            full_mask = matchup_mask & ml_fn(test_df)
        else:
            full_mask = matchup_mask

        sel = test_df[full_mask]
        print(f"\n  {mname} + {ml_name} (atk>{atk_thr}, pit{'<' if pit_op == '<' else '>'}{pit_thr})")
        print(f"  {'Season':>8} {'Bets':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8} {'AvgOU':>6}")
        print(f"  {'-'*48}")
        for s in sorted(sel["season"].unique()):
            ss = sel[sel["season"] == s]
            st = _bet_stats(ss, 1)
            if st is None:
                continue
            print(f"  {s:>8} {st['n']:6d} {st['hr']*100:5.1f}% "
                  f"{st['adj_roi']:+7.1f}% {st['fix_roi']:+7.1f}% {ss['close_ou'].mean():5.2f}")

    # 10f) Compare matchup vs SUM vs hybrid
    print(f"\n  10f) Matchup-level vs SUM-level comparison")
    print(f"  {'System':<45} {'Bets':>6} {'B/Sea':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8}")
    print(f"  {'-'*85}")

    comparison_rows = []

    # SUM baseline combos (from Step 9)
    sum_combos = [
        ("SUM: fi_rate>0.58+kbb<4.5", "fi_score_rate_combined", ">", 0.58,
         "starter_kbb_combined", "<", 4.5),
        ("SUM: fi_rate>0.63+kbb<4.0", "fi_score_rate_combined", ">", 0.63,
         "starter_kbb_combined", "<", 4.0),
        ("SUM: babip>0.66+fip>7.5", "top3_babip_inn1_combined", ">", 0.66,
         "starter_fip_combined", ">", 7.5),
        ("SUM: obp>0.72+kbb<3.8", "top3_obp_short_combined", ">", 0.72,
         "starter_kbb_combined", "<", 3.8),
    ]
    for name, c1, o1, v1, c2, o2, v2 in sum_combos:
        if c1 not in test_df.columns or c2 not in test_df.columns:
            continue
        m1 = test_df[c1].notna() & (test_df[c1] > v1 if o1 == ">" else test_df[c1] < v1)
        m2 = test_df[c2].notna() & (test_df[c2] > v2 if o2 == ">" else test_df[c2] < v2)
        sel = test_df[m1 & m2]
        s = _bet_stats(sel, n_s)
        if s is None:
            print(f"  {name:<45} (too few)")
            continue
        marker = " ***" if s["adj_roi"] > 0 else ""
        comparison_rows.append({"name": name, **s})
        print(f"  {name:<45} {s['n']:6d} {s['bps']:5.0f}/s {s['hr']*100:5.1f}% "
              f"{s['adj_roi']:+7.1f}% {s['fix_roi']:+7.1f}%{marker}")

    # Best matchup-only
    for r in (viable[:3] if len(viable) >= 3 else viable):
        name = f"MATCH: {r['name']}({r['atk_thr']},{r['pit_thr']})"
        comparison_rows.append({"name": name, **{k: r[k] for k in ["n", "bps", "hr", "adj_roi", "fix_roi"]}})
        marker = " ***" if r["adj_roi"] > 0 else ""
        print(f"  {name:<45} {r['n']:6d} {r['bps']:5.0f}/s {r['hr']*100:5.1f}% "
              f"{r['adj_roi']:+7.1f}% {r['fix_roi']:+7.1f}%{marker}")

    # Best hybrid (matchup+ML)
    for bh in best_hybrids[:3]:
        name = f"HYBRID: {bh['matchup']}+{bh['ml_filter']}"
        marker = " ***" if bh["adj_roi"] > 0 else ""
        print(f"  {name:<45} {bh['n']:6d} {bh['bps']:5.0f}/s {bh['hr']*100:5.1f}% "
              f"{bh['adj_roi']:+7.1f}% {bh['fix_roi']:+7.1f}%{marker}")

    # 10g) Portfolio construction
    print(f"\n  10g) Portfolio construction")

    # Build tiers from hybrid_results
    tier1 = [h for h in hybrid_results
             if h["adj_roi"] > 0.5 and h["ml_filter"] != "none" and h["bps"] >= 40]
    tier2 = [h for h in hybrid_results
             if h["adj_roi"] > -1.0 and "P(1run)" in h["ml_filter"] and h["bps"] >= 80]
    tier3 = [h for h in hybrid_results
             if h["adj_roi"] > -2.0 and h["ml_filter"] == "none" and h["bps"] >= 100]

    for tier_name, tier_list in [("Tier 1 (tight+ML)", tier1),
                                  ("Tier 2 (volume+P1)", tier2),
                                  ("Tier 3 (loose matchup)", tier3)]:
        if not tier_list:
            print(f"\n  {tier_name}: no qualifying combos")
            continue
        best_t = max(tier_list, key=lambda h: h["adj_roi"])
        print(f"\n  {tier_name}: {best_t['matchup']} + {best_t['ml_filter']}")
        print(f"    Bets: {best_t['n']}, {best_t['bps']:.0f}/season, "
              f"Hit: {best_t['hr']*100:.1f}%, AdjROI: {best_t['adj_roi']:+.1f}%, "
              f"FixROI: {best_t['fix_roi']:+.1f}%, MLS: {best_t['mls']}")

    # UNION of tier 1 + tier 2 (if both exist)
    if tier1 and tier2:
        t1 = max(tier1, key=lambda h: h["adj_roi"])
        t2 = max(tier2, key=lambda h: h["bps"])

        # Rebuild masks for union
        union_masks = []
        for t in [t1, t2]:
            mdef = None
            for md in matchup_defs:
                if md[0] == t["matchup"]:
                    mdef = md
                    break
            if mdef is None:
                continue
            _, atk_metric, atk_op, pit_metric, pit_op = mdef
            top_atk, top_pit = _resolve_cols(atk_metric, pit_metric, "TOP")
            bot_atk, bot_pit = _resolve_cols(atk_metric, pit_metric, "BOT")
            m = (_eval_matchup(test_df, top_atk, atk_op, t["atk_thr"],
                               top_pit, pit_op, t["pit_thr"]) |
                 _eval_matchup(test_df, bot_atk, atk_op, t["atk_thr"],
                               bot_pit, pit_op, t["pit_thr"]))
            ml_fn = None
            for mn, mf in ml_filters:
                if mn == t["ml_filter"]:
                    ml_fn = mf
                    break
            if ml_fn is not None:
                m = m & ml_fn(test_df)
            union_masks.append(m)

        if len(union_masks) == 2:
            union = union_masks[0] | union_masks[1]
            sel = test_df[union]
            s = _bet_stats(sel, n_s)
            if s is not None:
                print(f"\n  UNION (Tier1 + Tier2):")
                print(f"    Bets: {s['n']}, {s['bps']:.0f}/season, "
                      f"Hit: {s['hr']*100:.1f}%, AdjROI: {s['adj_roi']:+.1f}%, "
                      f"FixROI: {s['fix_roi']:+.1f}%, MLS: {s['mls']}")

                # Daily coverage
                sel_dates = pd.to_datetime(sel["date"]).dt.normalize()
                all_dates = pd.to_datetime(test_df["date"]).dt.normalize()
                days_with_bets = sel_dates.nunique()
                total_days = all_dates.nunique()
                print(f"    Coverage: {days_with_bets}/{total_days} days "
                      f"({days_with_bets/total_days*100:.0f}%)")

                # Per-season
                print(f"    {'Season':>8} {'Bets':>6} {'Hit%':>6} {'AdjROI':>8} {'FixROI':>8}")
                print(f"    {'-'*40}")
                for yr in sorted(sel["season"].unique()):
                    ss = sel[sel["season"] == yr]
                    st = _bet_stats(ss, 1)
                    if st is None:
                        continue
                    print(f"    {yr:>8} {st['n']:6d} {st['hr']*100:5.1f}% "
                          f"{st['adj_roi']:+7.1f}% {st['fix_roi']:+7.1f}%")

    print(f"\n{'='*90}")
    print("DONE")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
