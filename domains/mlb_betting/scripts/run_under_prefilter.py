"""Two-stage UNDER pre-filter backtest: Regression + Binary Classifier.

Stage 1: Regime-split regression predicts fair O/U line → ou_edge
Stage 2: Binary classifier predicts P(under|features)
Combined: BET UNDER when ou_edge < -threshold AND p_under > threshold

Usage:
    python scripts/run_under_prefilter.py
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

OU_DECIMAL_ODDS = 1.909  # -110 standard
BREAKEVEN = 1 / OU_DECIMAL_ODDS  # 52.38%
BASE_UNIT = 100


# ── Bankroll metrics ─────────────────────────────────────────────────────

def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def bankroll_metrics(df, name, hit_col="under_hit"):
    """Compute bankroll metrics for O/U bets at fixed -110 odds."""
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 10:
        return None

    hit = df[hit_col].values.astype(float)
    pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    b = OU_DECIMAL_ODDS - 1
    kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)

    mls = max_streak(hit, target=0)
    mws = max_streak(hit, target=1)

    bankroll = 10000 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    dd_pct = (peak - bankroll) / peak * 100
    max_dd = dd_pct.max()

    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(df.loc[sm, hit_col].values, (OU_DECIMAL_ODDS - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)

    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bets_per_season": n / df["season"].nunique(),
        "hit_rate": hr,
        "roi": roi,
        "sharpe": sharpe,
        "kelly_full": kelly_full,
        "kelly_half": kelly_full / 2,
        "max_loss_streak": mls,
        "max_win_streak": mws,
        "max_dd_pct": max_dd,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "worst_season": min(season_rois) if season_rois else 0,
        "best_season": max(season_rois) if season_rois else 0,
        "season_rois": season_rois,
    }


def print_row(m):
    """Print a single metrics row in comparison table format."""
    if m is None:
        return
    print(
        f"  {m['name']:<40} {m['bets']:5d} {m['bets_per_season']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
        f"{m['max_dd_pct']:5.1f}% {m['sharpe']:6.3f} "
        f"{m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
    )


def print_table_header():
    print(
        f"  {'Filter':<40} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
        f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>7} "
        f"{'K/2':>6} {'Flds':>6}"
    )
    print("-" * 110)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    from src.features import OU_FEATURES, build_ou_features
    from src.model import (
        ModelConfig,
        OU_REGIMES,
        UnderModelConfig,
        compute_divergence,
        run_walk_forward,
        run_walk_forward_under,
    )

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: Build O/U features
    # ══════════════════════════════════════════════════════════════════════
    print("=" * 80)
    print("STEP 1: Building O/U features")
    print("=" * 80)

    full = build_ou_features()
    print(f"Games: {len(full)}")
    print(f"Pushes: {full['is_push'].sum()}")
    print(f"Under rate (excl push): {full.loc[~full['is_push'], 'under_hit'].mean()*100:.1f}%")

    # Feature availability
    features_regression = [
        f for f in OU_FEATURES
        if f in full.columns and full[f].notna().mean() > 0.3
        and f != "close_ou"  # close_ou is the regression TARGET, not a feature
    ]
    features_classifier = [
        f for f in OU_FEATURES
        if f in full.columns and full[f].notna().mean() > 0.3
    ]
    print(f"Regression features: {len(features_regression)}/{len(OU_FEATURES)-1}")
    print(f"  {features_regression}")
    print(f"Classifier features: {len(features_classifier)}/{len(OU_FEATURES)}")
    print(f"  {features_classifier}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2: Stage 1 — Regression walk-forward (predict fair O/U line)
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 2: Stage 1 — Regression (predict fair O/U line)")
    print("=" * 80)

    target_reg = "close_ou"
    cfg_reg = ModelConfig()

    # run_walk_forward expects a "regime" column — rename ou_regime
    full["regime"] = full["ou_regime"]

    fold_results = run_walk_forward(
        full, features_regression, target_reg, cfg=cfg_reg, regimes=OU_REGIMES,
    )
    div = compute_divergence(fold_results)

    if div.empty:
        print("ERROR: No regression results. Check data/features.")
        return

    # Merge regression predictions
    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_cols = [c for c in div.columns if c.startswith("pred_T")]
    div_subset = div[merge_keys + pred_cols].copy()
    div_subset = div_subset.drop_duplicates(subset=merge_keys, keep="first")

    df = full.merge(div_subset, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # Consensus prediction and edge
    available_pred = [c for c in df.columns if c.startswith("pred_T")]
    df["pred_consensus"] = df[available_pred].mean(axis=1)
    df["ou_edge"] = df["pred_consensus"] - df["close_ou"]

    has_regression = df["ou_edge"].notna()
    print(f"Regression predictions: {has_regression.sum()}/{len(df)} games")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: Stage 2 — Binary classifier walk-forward P(under)
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 3: Stage 2 — Binary classifier P(under)")
    print("=" * 80)

    cfg_cls = UnderModelConfig()
    under_results = run_walk_forward_under(full, features_classifier, cfg=cfg_cls)

    if not under_results:
        print("ERROR: No classifier results.")
        return

    # Aggregate test predictions across folds
    all_preds = pd.concat(
        [r.test_predictions for r in under_results if r.test_predictions is not None],
        ignore_index=True,
    )
    # Deduplicate: same game may appear in overlapping test folds → keep last (more training data)
    all_preds = all_preds.sort_values("season").drop_duplicates(
        subset=merge_keys, keep="last",
    )
    print(f"Classifier predictions: {len(all_preds)} games")
    print(f"Mean P(under): {all_preds['p_under'].mean():.3f}")
    print(f"P(under) distribution: "
          f"min={all_preds['p_under'].min():.3f}, "
          f"p25={all_preds['p_under'].quantile(0.25):.3f}, "
          f"median={all_preds['p_under'].median():.3f}, "
          f"p75={all_preds['p_under'].quantile(0.75):.3f}, "
          f"max={all_preds['p_under'].max():.3f}")

    # Fold-level summary
    print("\nFold-level metrics:")
    for r in under_results:
        print(f"  {r.fold_name}: val_AUC={r.val_auc:.4f} val_Brier={r.val_brier:.4f} "
              f"| test_AUC={r.test_auc:.4f} test_Brier={r.test_brier:.4f} "
              f"(n_test={r.n_test})")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 4: Merge Stage 1 + Stage 2
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 4: Merging Stage 1 (regression) + Stage 2 (classifier)")
    print("=" * 80)

    # Merge p_under from classifier into df (which has ou_edge from regression)
    cls_subset = all_preds[merge_keys + ["p_under"]].copy()
    combined = df.merge(cls_subset, on=merge_keys, how="inner")
    combined = combined[~combined["is_push"]].copy()

    print(f"Combined games (both stages, no pushes): {len(combined)}")
    print(f"Both ou_edge + p_under available: {(combined['ou_edge'].notna() & combined['p_under'].notna()).sum()}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 5: Two-stage filter sweep
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 5: TWO-STAGE UNDER FILTER SWEEP")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS})  Breakeven: {BREAKEVEN*100:.2f}%")
    print("=" * 80)

    edge_thresholds = [0.3, 0.5, 0.75, 1.0, 1.5]
    p_thresholds = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60]

    print_table_header()

    sweep_results = []
    for edge_t in edge_thresholds:
        for p_t in p_thresholds:
            mask = (combined["ou_edge"] < -edge_t) & (combined["p_under"] > p_t)
            subset = combined[mask].copy()
            name = f"edge<-{edge_t:.1f} & P(u)>{p_t:.2f}"
            m = bankroll_metrics(subset, name)
            sweep_results.append(m)
            if m is not None:
                print_row(m)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 6: Baselines for comparison
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 6: BASELINES — Single-Stage Filters")
    print("=" * 80)
    print_table_header()

    # Stage 1 only: regression edge alone
    for edge_t in edge_thresholds:
        mask = combined["ou_edge"] < -edge_t
        subset = combined[mask].copy()
        m = bankroll_metrics(subset, f"BASELINE: edge<-{edge_t:.1f} only")
        if m is not None:
            print_row(m)

    print()

    # Stage 2 only: classifier alone
    for p_t in p_thresholds:
        mask = combined["p_under"] > p_t
        subset = combined[mask].copy()
        m = bankroll_metrics(subset, f"BASELINE: P(u)>{p_t:.2f} only")
        if m is not None:
            print_row(m)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 7: Calibration analysis
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 7: P(under) Calibration — Decile Analysis")
    print("=" * 80)

    cal_df = combined[combined["p_under"].notna()].copy()
    cal_df["p_decile"] = pd.qcut(cal_df["p_under"], 10, labels=False, duplicates="drop")

    print(f"  {'Decile':<8} {'N':>6} {'Mean P(u)':>10} {'Actual':>10} {'Gap':>8}")
    print("-" * 50)
    for d in sorted(cal_df["p_decile"].unique()):
        g = cal_df[cal_df["p_decile"] == d]
        mean_p = g["p_under"].mean()
        actual = g["under_hit"].mean()
        gap = actual - mean_p
        print(f"  {d:<8d} {len(g):6d} {mean_p:10.3f} {actual:10.3f} {gap:+8.3f}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 8: Feature importance
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 8: Feature Importance (last fold CatBoost)")
    print("=" * 80)

    # Retrain on last fold to get feature importance
    last_fold = under_results[-1]
    from src.model import train_under_model
    cb, _, _, _ = train_under_model(
        full, features_classifier,
        last_fold.train_seasons, last_fold.val_seasons,
        cfg=cfg_cls,
    )
    importances = cb.get_feature_importance()
    feat_imp = sorted(
        zip(features_classifier, importances),
        key=lambda x: x[1],
        reverse=True,
    )
    for feat, imp in feat_imp:
        bar = "#" * int(imp / 2)
        print(f"  {feat:<30} {imp:6.2f}  {bar}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 9: Best combo per-season breakdown
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 9: Per-Season Breakdown (best two-stage combo)")
    print("=" * 80)

    # Find best two-stage combo by ROI with min 50 bets
    valid_combos = [
        m for m in sweep_results
        if m is not None and m["bets"] >= 50
    ]
    if not valid_combos:
        valid_combos = [m for m in sweep_results if m is not None and m["bets"] >= 20]

    if valid_combos:
        best = max(valid_combos, key=lambda m: m["roi"])
        print(f"Best combo: {best['name']}")
        print(f"  Bets: {best['bets']} ({best['bets_per_season']:.0f}/season)")
        print(f"  Hit: {best['hit_rate']*100:.1f}%  ROI: {best['roi']:+.1f}%  "
              f"Sharpe: {best['sharpe']:.3f}  Kelly/2: {best['kelly_half']*100:.2f}%")
        print(f"  Max loss streak: {best['max_loss_streak']}  Max DD: {best['max_dd_pct']:.1f}%")
        print(f"  Seasons profitable: {best['seasons_pos']}")
        rois_str = ", ".join(f"{r:+.0f}" for r in best["season_rois"])
        print(f"  Per-season ROI: [{rois_str}]")
    else:
        print("No combos with enough bets found.")

    print(f"\n{'=' * 80}")
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
