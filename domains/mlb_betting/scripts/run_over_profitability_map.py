"""OVER profitability map: fine-grained ROI by P(under) bins.

Uses walk-forward UNDER classifier (V3, 21 features, None calibration)
to produce P(under) per game. Then maps the OVER tail:
  - P(under) < 0.50 → OVER signal
  - Fine bins: 0.40-0.50 in 0.01 steps
  - Cumulative thresholds: P(under) < X for each cutoff

Answers:
  1. Where does OVER become profitable?
  2. Is OVER signal symmetric with UNDER?
  3. What thresholds should we use for tiering?

Usage:
    python scripts/run_over_profitability_map.py
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

from src.data_loader import (
    add_derived_odds,
    apply_data_filters,
    load_all_seasons,
)
from src.features import (
    OU_FEATURES_V3,
    build_all_features,
    build_ou_features_v3,
)
from src.model import UnderModelConfig, run_walk_forward_under

OU_DECIMAL_ODDS = 1.909  # -110 standard
BREAKEVEN = 1 / OU_DECIMAL_ODDS  # 52.38%


def collect_all_predictions(results) -> pd.DataFrame:
    """Concatenate test predictions from all folds."""
    dfs = [r.test_predictions for r in results if r.test_predictions is not None]
    if not dfs:
        return pd.DataFrame()
    preds = pd.concat(dfs, ignore_index=True)
    # Exclude pushes
    if "is_push" in preds.columns:
        preds = preds[~preds["is_push"]].copy()
    else:
        preds = preds[preds["total_runs"] != preds["close_ou"]].copy()
    preds["over_hit"] = (preds["total_runs"] > preds["close_ou"]).astype(int)
    preds["p_over"] = 1 - preds["p_under"]
    return preds


def bin_analysis(preds: pd.DataFrame, bin_col: str, bins: list, side: str):
    """Compute ROI and stats for each bin."""
    labels = [f"{bins[i]:.2f}-{bins[i+1]:.2f}" for i in range(len(bins) - 1)]
    preds["bin"] = pd.cut(preds[bin_col], bins=bins, labels=labels, right=False)

    rows = []
    for label in labels:
        subset = preds[preds["bin"] == label]
        n = len(subset)
        if n < 10:
            rows.append({"bin": label, "n": n, "hit%": None, "roi%": None,
                         "profit": None, "seasons": None})
            continue

        target = "over_hit" if side == "over" else "under_hit"
        hits = subset[target].sum()
        hr = hits / n
        profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
        roi = profit / (n * 100) * 100

        # Per-season breakdown
        season_rois = []
        for s in sorted(subset["season"].unique()):
            sm = subset[subset["season"] == s]
            sn = len(sm)
            if sn < 3:
                continue
            sh = sm[target].sum()
            sp = sh * (OU_DECIMAL_ODDS - 1) * 100 - (sn - sh) * 100
            season_rois.append(sp / (sn * 100) * 100)
        n_pos = sum(1 for r in season_rois if r > 0)

        rows.append({
            "bin": label,
            "n": n,
            "hit%": hr * 100,
            "roi%": roi,
            "profit": profit,
            "seasons": f"{n_pos}/{len(season_rois)}",
            "worst": min(season_rois) if season_rois else None,
            "best": max(season_rois) if season_rois else None,
        })
    return pd.DataFrame(rows)


def cumulative_threshold_analysis(preds: pd.DataFrame):
    """For OVER bets: bet when P(under) < threshold."""
    thresholds = [0.50, 0.49, 0.48, 0.47, 0.46, 0.45, 0.44, 0.43, 0.42, 0.40]
    rows = []
    for t in thresholds:
        subset = preds[preds["p_under"] < t]
        n = len(subset)
        if n < 10:
            rows.append({"threshold": f"P(u)<{t:.2f}", "n": n})
            continue

        hits = subset["over_hit"].sum()
        hr = hits / n
        profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
        roi = profit / (n * 100) * 100

        # Per-season
        season_rois = []
        for s in sorted(subset["season"].unique()):
            sm = subset[subset["season"] == s]
            sn = len(sm)
            if sn < 3:
                continue
            sh = sm["over_hit"].sum()
            sp = sh * (OU_DECIMAL_ODDS - 1) * 100 - (sn - sh) * 100
            season_rois.append(sp / (sn * 100) * 100)
        n_pos = sum(1 for r in season_rois if r > 0)

        rows.append({
            "threshold": f"P(u)<{t:.2f}",
            "n": n,
            "per_season": n / preds["season"].nunique(),
            "hit%": hr * 100,
            "roi%": roi,
            "profit": profit,
            "seasons_pos": f"{n_pos}/{len(season_rois)}",
            "worst": min(season_rois) if season_rois else None,
            "best": max(season_rois) if season_rois else None,
            "season_rois": season_rois,
        })
    return rows


def symmetry_comparison(preds: pd.DataFrame):
    """Compare OVER tail vs UNDER tail to check signal symmetry."""
    print("\n" + "=" * 90)
    print("SYMMETRY CHECK: OVER tail vs UNDER tail")
    print("=" * 90)
    print(f"  {'Zone':<25} {'Bets':>6} {'B/S':>5} {'Hit%':>7} {'ROI%':>8} {'P/L':>10} {'Flds':>6}")
    print("-" * 75)

    pairs = [
        # (label, filter_func, target_col)
        ("UNDER P(u)>=0.55", lambda d: d[d["p_under"] >= 0.55], "under_hit"),
        ("UNDER P(u)>=0.52", lambda d: d[d["p_under"] >= 0.52], "under_hit"),
        ("UNDER P(u) 0.51-0.52", lambda d: d[(d["p_under"] >= 0.51) & (d["p_under"] < 0.52)], "under_hit"),
        ("---", None, None),
        ("OVER P(u)<0.45", lambda d: d[d["p_under"] < 0.45], "over_hit"),
        ("OVER P(u)<0.48", lambda d: d[d["p_under"] < 0.48], "over_hit"),
        ("OVER P(u) 0.48-0.49", lambda d: d[(d["p_under"] >= 0.48) & (d["p_under"] < 0.49)], "over_hit"),
        ("OVER P(u) 0.49-0.50", lambda d: d[(d["p_under"] >= 0.49) & (d["p_under"] < 0.50)], "over_hit"),
    ]

    for label, filt, target in pairs:
        if filt is None:
            print(f"  {'-' * 70}")
            continue
        subset = filt(preds)
        n = len(subset)
        if n < 10:
            print(f"  {label:<25} {n:>6}  (too few)")
            continue
        hits = subset[target].sum()
        hr = hits / n
        profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
        roi = profit / (n * 100) * 100
        bps = n / preds["season"].nunique()

        # Seasons profitable
        season_rois = []
        for s in sorted(subset["season"].unique()):
            sm = subset[subset["season"] == s]
            sn = len(sm)
            if sn < 3:
                continue
            sh = sm[target].sum()
            sp = sh * (OU_DECIMAL_ODDS - 1) * 100 - (sn - sh) * 100
            season_rois.append(sp / (sn * 100) * 100)
        n_pos = sum(1 for r in season_rois if r > 0)

        print(f"  {label:<25} {n:>6} {bps:>5.0f} {hr*100:>6.1f}% {roi:>+7.1f}% ${profit:>+9.0f} {n_pos}/{len(season_rois)}")


def main():
    print("=" * 90)
    print("OVER PROFITABILITY MAP")
    print(f"Model: V3 hybrid (21 features), None calibration, walk-forward")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS}), breakeven {BREAKEVEN*100:.1f}%")
    print("=" * 90)

    # ── Load data ─────────────────────────────────────────────────────────
    logger.info("Loading and enriching data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    logger.info("Building V3 features...")
    ou = build_ou_features_v3(enriched=enriched)

    # Use actual V3 feature list minus removed features (session 19: 22→21)
    removed = {"close_ou", "combined_rpg_last10", "combined_rapg",
               "combined_rapg_last10", "pyth_wp_combined"}
    feats = [f for f in OU_FEATURES_V3
             if f in ou.columns and ou[f].notna().mean() > 0.3 and f not in removed]
    print(f"\nFeatures: {len(feats)}/{len(OU_FEATURES_V3)}")
    print(f"  Used: {feats}")
    print(f"  Removed: {removed & set(OU_FEATURES_V3)}")

    # ── Walk-forward ──────────────────────────────────────────────────────
    logger.info("Running walk-forward UNDER classifier...")
    results = run_walk_forward_under(ou, feats)

    # ── Collect predictions ───────────────────────────────────────────────
    preds = collect_all_predictions(results)
    print(f"\nTotal predictions: {len(preds)} (pushes excluded)")
    print(f"Seasons: {sorted(preds['season'].unique())}")
    print(f"Overall: under_hit={preds['under_hit'].mean()*100:.1f}%, "
          f"over_hit={preds['over_hit'].mean()*100:.1f}%")
    print(f"P(under) distribution: mean={preds['p_under'].mean():.3f}, "
          f"std={preds['p_under'].std():.3f}, "
          f"min={preds['p_under'].min():.3f}, max={preds['p_under'].max():.3f}")

    # ── 1. Fine-grained bin analysis (OVER tail) ─────────────────────────
    print("\n" + "=" * 90)
    print("SECTION 1: OVER TAIL — P(under) BIN ANALYSIS")
    print("Bins from 0.40 to 0.52 in 0.01 steps")
    print("=" * 90)

    bins = [round(0.40 + i * 0.01, 2) for i in range(13)]  # 0.40 to 0.52
    bin_df = bin_analysis(preds, "p_under", bins, side="over")
    print(f"\n  {'Bin':<12} {'N':>6} {'Hit%':>7} {'ROI%':>8} {'P/L':>10} {'Seasons':>8} {'Worst':>7} {'Best':>7}")
    print("-" * 75)
    for _, row in bin_df.iterrows():
        if row["hit%"] is None:
            print(f"  {row['bin']:<12} {row['n']:>6}  (too few)")
            continue
        print(f"  {row['bin']:<12} {row['n']:>6} {row['hit%']:>6.1f}% {row['roi%']:>+7.1f}% "
              f"${row['profit']:>+9.0f} {row['seasons']:>8} {row['worst']:>+6.0f}% {row['best']:>+6.0f}%")

    # ── 2. Cumulative threshold sweep ─────────────────────────────────────
    print("\n" + "=" * 90)
    print("SECTION 2: CUMULATIVE THRESHOLDS — bet OVER when P(under) < X")
    print("=" * 90)

    cum_rows = cumulative_threshold_analysis(preds)
    print(f"\n  {'Threshold':<15} {'Bets':>6} {'B/S':>5} {'Hit%':>7} {'ROI%':>8} {'P/L':>10} {'Flds':>6} {'Worst':>7} {'Best':>7}")
    print("-" * 80)
    for r in cum_rows:
        if "hit%" not in r:
            print(f"  {r['threshold']:<15} {r['n']:>6}  (too few)")
            continue
        print(f"  {r['threshold']:<15} {r['n']:>6} {r['per_season']:>5.0f} {r['hit%']:>6.1f}% "
              f"{r['roi%']:>+7.1f}% ${r['profit']:>+9.0f} {r['seasons_pos']:>6} "
              f"{r['worst']:>+6.0f}% {r['best']:>+6.0f}%")

    # Per-season detail for best thresholds
    print("\n  Per-season ROI detail:")
    for r in cum_rows:
        if "season_rois" in r and r.get("roi%") is not None:
            rois_str = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
            print(f"    {r['threshold']}: [{rois_str}]")

    # ── 3. Symmetry comparison ────────────────────────────────────────────
    symmetry_comparison(preds)

    # ── 4. OVER edge calibration curve ────────────────────────────────────
    print("\n" + "=" * 90)
    print("SECTION 4: CALIBRATION CURVE — actual OVER rate by P(over) bin")
    print("=" * 90)

    # Fine-grained P(over) bins
    preds["p_over_bin"] = pd.cut(preds["p_over"],
                                  bins=[0.48, 0.49, 0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.60],
                                  right=False)
    cal = preds.groupby("p_over_bin", observed=True).agg(
        n=("over_hit", "size"),
        actual_over_rate=("over_hit", "mean"),
    )
    print(f"\n  {'P(over) bin':<15} {'N':>6} {'Actual OVER%':>12} {'Gap vs 50%':>10}")
    print("-" * 50)
    for idx, row in cal.iterrows():
        if row["n"] < 10:
            continue
        gap = row["actual_over_rate"] * 100 - 50
        print(f"  {str(idx):<15} {int(row['n']):>6} {row['actual_over_rate']*100:>11.1f}% {gap:>+9.1f}%")

    # ── 5. Monthly breakdown for key OVER thresholds ──────────────────────
    print("\n" + "=" * 90)
    print("SECTION 5: MONTHLY BREAKDOWN — OVER bets P(under)<0.48")
    print("=" * 90)

    preds["month"] = pd.to_datetime(preds["date"]).dt.month
    over_bets = preds[preds["p_under"] < 0.48].copy()

    print(f"\n  {'Month':<8} {'N':>5} {'Hit%':>7} {'ROI%':>8} {'P/L':>9}")
    print("-" * 45)
    for m in range(4, 11):
        subset = over_bets[over_bets["month"] == m]
        n = len(subset)
        if n < 5:
            continue
        hits = subset["over_hit"].sum()
        hr = hits / n
        profit = hits * (OU_DECIMAL_ODDS - 1) * 100 - (n - hits) * 100
        roi = profit / (n * 100) * 100
        month_names = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct"}
        print(f"  {month_names.get(m, str(m)):<8} {n:>5} {hr*100:>6.1f}% {roi:>+7.1f}% ${profit:>+8.0f}")

    print("\n" + "=" * 90)
    print("DONE. Use results to set OVER tiering thresholds.")
    print("=" * 90)


if __name__ == "__main__":
    main()
