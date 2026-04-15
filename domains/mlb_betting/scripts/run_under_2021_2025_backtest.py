"""UNDER totals walk-forward backtest: 2021-2025 validation.

Step 0: Reproduce historical benchmark (test_size=2, compare with Session 15)
Step 1: Per-year walk-forward with test_size=1 for clean 2021-2025 predictions
Step 2: Profitability map at P(under) thresholds 0.50-0.60
Step 3: Epoch comparison (2010-2021 vs 2022-2025) + calibration + AUC trend

Usage:
    python scripts/run_under_2021_2025_backtest.py
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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.features import OU_FEATURES, build_ou_features
from src.model import (
    UnderModelConfig,
    run_walk_forward_under,
    walk_forward_splits,
    train_under_model,
    predict_under_proba,
)

# ── Constants ────────────────────────────────────────────────────────────

OU_DECIMAL_ODDS = 1.909  # -110 standard
BREAKEVEN = 1 / OU_DECIMAL_ODDS  # 52.38%
BASE_UNIT = 100
THRESHOLDS = [round(0.50 + i * 0.01, 2) for i in range(11)]  # 0.50..0.60
OLD_EPOCHS = list(range(2010, 2020)) + [2021]
NEW_EPOCHS = [2022, 2023, 2024, 2025]
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

MERGE_KEYS = ["season", "date", "home_team", "away_team"]


# ── Bankroll Metrics (from run_under_prefilter.py) ───────────────────────

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
    pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * BASE_UNIT) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    sharpe_bet = ev / std if std > 0 else 0
    n_seasons = df["season"].nunique()
    bps = n / n_seasons if n_seasons > 0 else n
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
        sp = np.where(df.loc[sm, hit_col].values, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
        season_rois.append(sp.sum() / (sn * BASE_UNIT) * 100)

    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name, "bets": n, "bets_per_season": n / max(n_seasons, 1),
        "hit_rate": hr, "roi": roi, "sharpe": sharpe,
        "kelly_full": kelly_full, "kelly_half": kelly_full / 2,
        "max_loss_streak": mls, "max_win_streak": mws,
        "max_dd_pct": max_dd,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "worst_season": min(season_rois) if season_rois else 0,
        "best_season": max(season_rois) if season_rois else 0,
        "season_rois": season_rois,
    }


def print_table_header():
    print(
        f"  {'Filter':<40} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
        f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>7} "
        f"{'K/2':>6} {'Flds':>6}"
    )
    print("  " + "-" * 105)


def print_row(m):
    if m is None:
        return
    print(
        f"  {m['name']:<40} {m['bets']:5d} {m['bets_per_season']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
        f"{m['max_dd_pct']:5.1f}% {m['sharpe']:6.3f} "
        f"{m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
    )


# ── Bootstrap CI ─────────────────────────────────────────────────────────

def bootstrap_roi_ci(hits, n_bootstrap=10000, ci=0.95):
    """Bootstrap 95% CI on ROI from binary hit/miss array."""
    rng = np.random.default_rng(42)
    n = len(hits)
    if n < 10:
        return (np.nan, np.nan)
    rois = []
    for _ in range(n_bootstrap):
        sample = rng.choice(hits, size=n, replace=True)
        pnl = np.where(sample, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
        rois.append(pnl.sum() / (n * BASE_UNIT) * 100)
    lo = np.percentile(rois, (1 - ci) / 2 * 100)
    hi = np.percentile(rois, (1 + ci) / 2 * 100)
    return (lo, hi)


# ── Walk-Forward with test_size=1 ────────────────────────────────────────

def run_walk_forward_single_year(df, features, cfg=None, min_train=5):
    """Walk-forward with test_size=1. Mirrors model.py:755-807 exactly."""
    if cfg is None:
        cfg = UnderModelConfig()

    seasons = sorted(df["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=min_train,
                                max_train=cfg.max_train_seasons,
                                test_size=1)
    if not folds:
        logger.warning("No folds generated with test_size=1")
        return pd.DataFrame()

    logger.info(f"Single-year walk-forward: {len(folds)} folds, {len(features)} features")
    all_preds = []

    for i, (train_s, val_s, test_s) in enumerate(folds):
        fold_name = f"fold_{i}_{val_s[0]}_{test_s[0]}"
        logger.info(f"  {fold_name}: train={train_s[0]}-{train_s[-1]}, "
                     f"val={val_s}, test={test_s}")

        cb, lr_model, calibrator, metrics = train_under_model(
            df, features, train_s, val_s, cfg=cfg,
        )
        train_medians = metrics["train_medians"]

        push_mask = df["is_push"] if "is_push" in df.columns else pd.Series(False, index=df.index)
        test_mask = df["season"].isin(test_s) & ~push_mask
        n_test = int(test_mask.sum())

        if n_test < 10:
            logger.warning(f"  {fold_name}: only {n_test} test games, skipping")
            continue

        X_test = df.loc[test_mask, features].values.astype(float)
        y_test = df.loc[test_mask, "under_hit"].values.astype(int)
        p_under = predict_under_proba(X_test, cb, lr_model, calibrator, train_medians, cfg=cfg)

        test_auc = float(roc_auc_score(y_test, p_under))
        test_brier = float(brier_score_loss(y_test, p_under))
        val_auc = metrics.get("val_auc", 0.0)
        logger.info(f"  {fold_name}: test AUC={test_auc:.4f}, Brier={test_brier:.4f}")

        meta_cols = ["season", "date", "home_team", "away_team", "close_ou",
                     "total_runs", "under_hit"]
        preds_df = df.loc[test_mask, meta_cols].copy()
        preds_df["p_under"] = p_under
        preds_df["fold"] = fold_name
        preds_df["train_end"] = train_s[-1]
        preds_df["val_auc"] = val_auc
        preds_df["test_auc"] = test_auc
        preds_df["test_brier"] = test_brier
        all_preds.append(preds_df)

    if not all_preds:
        return pd.DataFrame()
    return pd.concat(all_preds, ignore_index=True)


# ── Profitability Map ────────────────────────────────────────────────────

def compute_profitability_map(preds, thresholds, target_seasons=None):
    """Profitability at each threshold, per year and aggregate."""
    rows = []
    for t in thresholds:
        subset = preds[preds["p_under"] >= t]
        if target_seasons is not None:
            subset = subset[subset["season"].isin(target_seasons)]

        # Per-year
        for s in sorted(subset["season"].unique()):
            sy = subset[subset["season"] == s]
            n = len(sy)
            if n < 5:
                continue
            hit = sy["under_hit"].values.astype(float)
            pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
            roi = pnl.sum() / (n * BASE_UNIT) * 100
            bankroll = 10000 + np.cumsum(pnl)
            peak = np.maximum.accumulate(bankroll)
            max_dd = ((peak - bankroll) / peak * 100).max()
            rows.append({"threshold": t, "year": s, "n": n,
                         "hit_rate": hit.mean(), "roi": roi, "max_dd": max_dd})

        # Aggregate
        n = len(subset)
        if n >= 10:
            hit = subset["under_hit"].values.astype(float)
            pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
            roi = pnl.sum() / (n * BASE_UNIT) * 100
            ev = pnl.mean()
            std = pnl.std(ddof=1) if n > 1 else 1
            sharpe_bet = ev / std if std > 0 else 0
            n_seasons = subset["season"].nunique()
            bps = n / max(n_seasons, 1)
            sharpe = sharpe_bet * np.sqrt(bps)
            ci_lo, ci_hi = bootstrap_roi_ci(hit)
            rows.append({"threshold": t, "year": "ALL", "n": n,
                         "hit_rate": hit.mean(), "roi": roi, "max_dd": np.nan,
                         "sharpe": sharpe, "ci_lo": ci_lo, "ci_hi": ci_hi})

    return pd.DataFrame(rows)


# ── Calibration ──────────────────────────────────────────────────────────

def compute_calibration(preds, n_bins=10):
    """Reliability diagram: predicted P(under) bins vs actual under rate."""
    bins = np.linspace(0, 1, n_bins + 1)
    rows = []
    for j in range(n_bins):
        lo, hi = bins[j], bins[j + 1]
        mask = (preds["p_under"] >= lo) & (preds["p_under"] < hi)
        subset = preds[mask]
        if len(subset) < 5:
            continue
        mean_pred = subset["p_under"].mean()
        actual = subset["under_hit"].mean()
        rows.append({"bin_lo": lo, "bin_hi": hi, "bin_center": (lo + hi) / 2,
                      "mean_predicted": mean_pred, "actual_rate": actual,
                      "n_games": len(subset), "gap": actual - mean_pred})
    return pd.DataFrame(rows)


# ── AUC per year ─────────────────────────────────────────────────────────

def compute_auc_per_year(preds):
    """AUC-ROC per test year."""
    rows = []
    for s in sorted(preds["season"].unique()):
        sy = preds[preds["season"] == s]
        if len(sy) < 20 or sy["under_hit"].nunique() < 2:
            continue
        auc = roc_auc_score(sy["under_hit"], sy["p_under"])
        rows.append({"year": s, "auc": auc, "n_games": len(sy)})
    return pd.DataFrame(rows)


# ── Plots ────────────────────────────────────────────────────────────────

def plot_profitability_heatmap(prof_map, save_path):
    """Heatmap: threshold (x) vs year (y), color = ROI."""
    per_year = prof_map[prof_map["year"] != "ALL"].copy()
    per_year["year"] = per_year["year"].astype(int)
    pivot = per_year.pivot_table(index="year", columns="threshold", values="roi")

    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto",
                   vmin=-30, vmax=50)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{t:.2f}" for t in pivot.columns], rotation=45)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("P(under) threshold")
    ax.set_ylabel("Season")
    ax.set_title("UNDER Totals ROI (%) by Threshold and Season")

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:+.0f}", ha="center", va="center",
                        fontsize=8, color="black" if abs(val) < 25 else "white")

    plt.colorbar(im, ax=ax, label="ROI %")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


def plot_calibration(cal_old, cal_new, save_path):
    """Calibration plot: old vs new epoch."""
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")

    if not cal_old.empty:
        ax.plot(cal_old["mean_predicted"], cal_old["actual_rate"],
                "bo-", label=f"2010-2021 (n={cal_old['n_games'].sum()})")
    if not cal_new.empty:
        ax.plot(cal_new["mean_predicted"], cal_new["actual_rate"],
                "rs-", label=f"2022-2025 (n={cal_new['n_games'].sum()})")

    ax.set_xlabel("Mean Predicted P(under)")
    ax.set_ylabel("Actual Under Rate")
    ax.set_title("UNDER Model Calibration: Old vs New Epoch")
    ax.legend()
    ax.set_xlim(0.3, 0.8)
    ax.set_ylim(0.3, 0.8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


def plot_auc_trend(auc_df, save_path):
    """AUC per year line chart."""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(auc_df["year"], auc_df["auc"], "bo-", markersize=8)

    # Trend line
    if len(auc_df) >= 3:
        z = np.polyfit(auc_df["year"], auc_df["auc"], 1)
        p = np.poly1d(z)
        ax.plot(auc_df["year"], p(auc_df["year"]), "r--", alpha=0.5,
                label=f"Trend: {z[0]:+.4f}/year")
        ax.legend()

    for _, r in auc_df.iterrows():
        ax.annotate(f"{r['auc']:.3f}\n(n={int(r['n_games'])})",
                    (r["year"], r["auc"]), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=8)

    ax.set_xlabel("Test Year")
    ax.set_ylabel("AUC-ROC")
    ax.set_title("UNDER Model AUC Trend by Test Year")
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0.45, 0.70)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"  Saved: {save_path}")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("UNDER TOTALS — WALK-FORWARD BACKTEST 2021-2025")
    print("=" * 80)

    # ── Build features ───────────────────────────────────────────────────
    print("\nBuilding O/U features...")
    full = build_ou_features()

    # Filter out 2026 partial data
    full = full[full["season"] <= 2025].copy()

    features = [
        f for f in OU_FEATURES
        if f in full.columns and full[f].notna().mean() > 0.3
    ]
    print(f"Games: {len(full)} | Features: {len(features)}/{len(OU_FEATURES)}")
    print(f"Seasons: {sorted(full['season'].unique().tolist())}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 0: Reproduce Historical Benchmark (test_size=2)
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 0: HISTORICAL BENCHMARK (test_size=2, compare with Session 15)")
    print("=" * 80)

    cfg = UnderModelConfig()
    benchmark_results = run_walk_forward_under(full, features, cfg=cfg)

    if not benchmark_results:
        print("ERROR: No benchmark results. Check data/features.")
        return

    # Aggregate predictions
    bench_preds = pd.concat(
        [r.test_predictions for r in benchmark_results if r.test_predictions is not None],
        ignore_index=True,
    )
    bench_preds = bench_preds.sort_values("season").drop_duplicates(
        subset=MERGE_KEYS, keep="last",
    )
    print(f"Benchmark predictions: {len(bench_preds)} games")

    # Fold summary
    print("\nFold summary:")
    for r in benchmark_results:
        print(f"  {r.fold_name}: val_AUC={r.val_auc:.4f} test_AUC={r.test_auc:.4f} "
              f"(n_test={r.n_test})")

    # Compare with Session 15 benchmarks
    print("\nSession 15 comparison:")
    print(f"  {'Threshold':<15} {'Hit%':>6} {'ROI':>7} {'Volume':>7} {'Session 15 Hit%':>16} {'S15 ROI':>10}")
    print("  " + "-" * 70)
    s15_benchmarks = {
        0.55: {"hit": "53-61%", "roi": "+0.2 to +15%"},
        0.60: {"hit": "69-85%", "roi": "+32 to +61%"},
    }
    for t in [0.52, 0.55, 0.58, 0.60]:
        subset = bench_preds[bench_preds["p_under"] >= t]
        n = len(subset)
        if n < 10:
            continue
        hr = subset["under_hit"].mean()
        pnl = np.where(subset["under_hit"].values, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
        roi = pnl.sum() / (n * BASE_UNIT) * 100
        s15 = s15_benchmarks.get(t, {"hit": "n/a", "roi": "n/a"})
        print(f"  P>={t:.2f}        {hr*100:5.1f}% {roi:+6.1f}% {n:7d} {s15['hit']:>16} {s15['roi']:>10}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: Per-Year Walk-Forward (test_size=1)
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 1: PER-YEAR WALK-FORWARD (test_size=1)")
    print("=" * 80)

    preds = run_walk_forward_single_year(full, features, cfg=cfg)

    if preds.empty:
        print("ERROR: No per-year predictions.")
        return

    # Filter to 2021-2025 target years
    target_preds = preds[preds["season"].isin([2021] + NEW_EPOCHS)]
    print(f"\nPredictions 2021-2025: {len(target_preds)} games")
    print(f"P(under) distribution: "
          f"min={target_preds['p_under'].min():.3f}, "
          f"median={target_preds['p_under'].median():.3f}, "
          f"max={target_preds['p_under'].max():.3f}")

    # Per-year fold detail
    print("\nPer-year detail:")
    for s in sorted(target_preds["season"].unique()):
        sy = target_preds[target_preds["season"] == s]
        auc_val = sy["test_auc"].iloc[0] if len(sy) > 0 else 0
        print(f"  {s}: {len(sy)} games, AUC={auc_val:.4f}, "
              f"under_rate={sy['under_hit'].mean()*100:.1f}%")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2: PROFITABILITY MAP
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 2: PROFITABILITY MAP (2021-2025)")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS})  Breakeven: {BREAKEVEN*100:.2f}%")
    print("=" * 80)

    prof_map = compute_profitability_map(preds, THRESHOLDS,
                                         target_seasons=[2021] + NEW_EPOCHS)

    # Print aggregate table
    print("\nAggregate (all years):")
    print(f"  {'Threshold':>9} {'Bets':>6} {'Hit%':>6} {'ROI':>7} "
          f"{'Sharpe':>7} {'95% CI':>16}")
    print("  " + "-" * 60)
    agg = prof_map[prof_map["year"] == "ALL"]
    for _, r in agg.iterrows():
        ci_str = f"[{r.get('ci_lo', 0):+.1f}, {r.get('ci_hi', 0):+.1f}]"
        print(f"  P>={r['threshold']:.2f}   {r['n']:6.0f} {r['hit_rate']*100:5.1f}% "
              f"{r['roi']:+6.1f}% {r.get('sharpe', 0):7.3f} {ci_str:>16}")

    # Print per-year table
    print("\nPer-year ROI:")
    per_year = prof_map[prof_map["year"] != "ALL"].copy()
    per_year["year"] = per_year["year"].astype(int)
    years = sorted(per_year["year"].unique())

    print(f"  {'Threshold':>9}", end="")
    for y in years:
        print(f"  {y:>8}", end="")
    print()
    print("  " + "-" * (9 + 10 * len(years)))

    for t in THRESHOLDS:
        print(f"  P>={t:.2f}  ", end="")
        for y in years:
            row = per_year[(per_year["threshold"] == t) & (per_year["year"] == y)]
            if row.empty:
                print(f"  {'n/a':>8}", end="")
            else:
                r = row.iloc[0]
                print(f"  {r['roi']:+7.1f}%", end="")
        print()

    # Heatmap
    if not per_year.empty:
        plot_profitability_heatmap(prof_map,
                                   KNOWLEDGE_DIR / "under_validation_profitability.png")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2b: SINGLE-THRESHOLD DEEP METRICS
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 2b: DEEP METRICS AT KEY THRESHOLDS (2021-2025)")
    print("=" * 80)

    target = preds[preds["season"].isin([2021] + NEW_EPOCHS)]
    print_table_header()
    for t in [0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.60]:
        subset = target[target["p_under"] >= t]
        m = bankroll_metrics(subset, f"P(under) >= {t:.2f}")
        print_row(m)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: EPOCH COMPARISON
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 3: EPOCH COMPARISON (2010-2021 vs 2022-2025)")
    print("=" * 80)

    # Use benchmark predictions (test_size=2) for old epoch coverage
    # and per-year predictions for new epoch
    old_preds = bench_preds[bench_preds["season"].isin(OLD_EPOCHS)]
    new_preds = preds[preds["season"].isin(NEW_EPOCHS)]

    print(f"\nOld epoch: {len(old_preds)} games ({sorted(old_preds['season'].unique().tolist())})")
    print(f"New epoch: {len(new_preds)} games ({sorted(new_preds['season'].unique().tolist())})")

    # Per-threshold comparison
    print(f"\n  {'Threshold':>9} {'Old Hit%':>8} {'Old ROI':>8} {'New Hit%':>8} "
          f"{'New ROI':>8} {'Delta ROI':>10}")
    print("  " + "-" * 60)
    for t in [0.52, 0.53, 0.54, 0.55, 0.56, 0.58, 0.60]:
        old_s = old_preds[old_preds["p_under"] >= t]
        new_s = new_preds[new_preds["p_under"] >= t]
        if len(old_s) < 10 or len(new_s) < 10:
            continue
        old_hr = old_s["under_hit"].mean()
        new_hr = new_s["under_hit"].mean()
        old_pnl = np.where(old_s["under_hit"].values, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
        new_pnl = np.where(new_s["under_hit"].values, (OU_DECIMAL_ODDS - 1) * BASE_UNIT, -BASE_UNIT)
        old_roi = old_pnl.sum() / (len(old_s) * BASE_UNIT) * 100
        new_roi = new_pnl.sum() / (len(new_s) * BASE_UNIT) * 100
        delta = new_roi - old_roi
        print(f"  P>={t:.2f}   {old_hr*100:7.1f}% {old_roi:+7.1f}% "
              f"{new_hr*100:7.1f}% {new_roi:+7.1f}% {delta:+9.1f}pp")

    # Calibration
    print("\nCalibration analysis:")
    cal_old = compute_calibration(old_preds)
    cal_new = compute_calibration(new_preds)

    if not cal_old.empty:
        print("\n  Old epoch (2010-2021):")
        print(f"  {'Bin':>8} {'Predicted':>10} {'Actual':>8} {'Gap':>7} {'N':>6}")
        for _, r in cal_old.iterrows():
            print(f"  {r['bin_center']:.2f}   {r['mean_predicted']:9.3f} "
                  f"{r['actual_rate']:7.3f} {r['gap']:+6.3f} {r['n_games']:6.0f}")

    if not cal_new.empty:
        print("\n  New epoch (2022-2025):")
        print(f"  {'Bin':>8} {'Predicted':>10} {'Actual':>8} {'Gap':>7} {'N':>6}")
        for _, r in cal_new.iterrows():
            print(f"  {r['bin_center']:.2f}   {r['mean_predicted']:9.3f} "
                  f"{r['actual_rate']:7.3f} {r['gap']:+6.3f} {r['n_games']:6.0f}")

    # Plot calibration
    if not cal_old.empty or not cal_new.empty:
        plot_calibration(cal_old, cal_new,
                         KNOWLEDGE_DIR / "under_validation_calibration.png")

    # AUC trend
    print("\nAUC trend:")
    # Combine AUCs from both runs for full picture
    auc_old = compute_auc_per_year(old_preds)
    auc_new = compute_auc_per_year(new_preds)
    auc_all = pd.concat([auc_old, auc_new], ignore_index=True)

    if not auc_all.empty:
        print(f"  {'Year':>6} {'AUC':>7} {'N games':>8}")
        for _, r in auc_all.iterrows():
            epoch = "new" if r["year"] in NEW_EPOCHS else "old"
            print(f"  {int(r['year']):>6} {r['auc']:7.4f} {int(r['n_games']):>8}  ({epoch})")

        # Trend
        if len(auc_all) >= 3:
            z = np.polyfit(auc_all["year"], auc_all["auc"], 1)
            print(f"\n  AUC trend: {z[0]:+.5f} per year "
                  f"({'improving' if z[0] > 0 else 'degrading'})")

        plot_auc_trend(auc_all, KNOWLEDGE_DIR / "under_validation_auc_trend.png")

    # ══════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print("=" * 80)

    # Find optimal threshold on new epoch
    agg_new = compute_profitability_map(preds, THRESHOLDS, target_seasons=NEW_EPOCHS)
    agg_new = agg_new[agg_new["year"] == "ALL"]
    if not agg_new.empty:
        best = agg_new.loc[agg_new["roi"].idxmax()]
        print(f"\n  Best threshold on 2022-2025: P>={best['threshold']:.2f}")
        print(f"  ROI: {best['roi']:+.1f}%  Hit: {best['hit_rate']*100:.1f}%  "
              f"Volume: {best['n']:.0f} games")

    # LLM expansion zone sizing
    expansion = preds[preds["season"].isin(NEW_EPOCHS)]
    for zone_lo, zone_hi in [(0.50, 0.52), (0.51, 0.52), (0.515, 0.52)]:
        zone = expansion[(expansion["p_under"] >= zone_lo) & (expansion["p_under"] < zone_hi)]
        n = len(zone)
        hr = zone["under_hit"].mean() * 100 if n > 0 else 0
        est_cost = n * 3 * 0.001  # 3 LLM calls * $0.001 each
        print(f"\n  LLM zone [{zone_lo:.3f}, {zone_hi:.3f}): "
              f"{n} games, under_rate={hr:.1f}%, est. cost=${est_cost:.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
