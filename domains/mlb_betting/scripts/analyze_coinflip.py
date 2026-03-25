"""Coinflip zone analysis: games where teams are ~equal by odds.

Finds all coinflip games (odds spread <= 4%) in target months,
analyzes volume, characteristics, and feature-based edges that
LLM experts could exploit.

Usage:
    python scripts/analyze_coinflip.py
    python scripts/analyze_coinflip.py --month 2024-06
"""

import sys
import warnings
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features, build_spec_features, SPEC_FEATURES
from src.model import run_walk_forward, compute_divergence

TARGET_MONTHS = [
    ("2025-04", 2025, 4),
    ("2024-06", 2024, 6),
    ("2024-08", 2024, 8),
]


def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def analyze_cf_features(cf: pd.DataFrame, label: str):
    """Analyze which features differentiate CF winners."""
    print(f"\n  {'='*70}")
    print(f"  FEATURE ANALYSIS: {label}")
    print(f"  {'='*70}")

    n = len(cf)
    if n < 10:
        print(f"  Too few games ({n}) for analysis.")
        return

    # Home win rate in coinflip games
    hw = cf["home_win"].mean()
    print(f"\n  Home win rate: {hw*100:.1f}% ({int(cf['home_win'].sum())}/{n})")

    # Features that could differentiate winners
    diff_features = [
        ("rpi_diff", "RPI diff (home - away)", ">"),
        ("wp_diff", "Win% diff", ">"),
        ("wp_last10_diff", "Win% last 10 diff", ">"),
        ("pyth_wp_diff", "Pythagorean WP diff", ">"),
        ("streak_diff", "Streak diff", ">"),
        ("rpg_diff", "RPG diff (offense)", ">"),
        ("sp_wr_long_diff", "SP Win Rate diff", ">"),
        ("sp_ra_long_diff", "SP Runs Allowed diff", "<"),  # lower RA is better
        ("sp_fi_momentum_diff", "SP 1st-Inn Momentum diff", "<"),
        ("starter_fip_diff", "Starter FIP diff", "<"),
        ("starter_whip_diff", "Starter WHIP diff", "<"),
        ("elo_diff", "Elo diff", ">"),
        ("bullpen_fip_diff", "Bullpen FIP diff", "<"),
    ]

    print(f"\n  {'Feature':<30} {'Present':>7} {'Threshold':>10} {'Bets':>5} "
          f"{'Win%':>6} {'P&L':>8} {'ROI':>7}")
    print(f"  {'-'*80}")

    for feat, desc, direction in diff_features:
        if feat not in cf.columns:
            continue
        valid = cf[feat].notna()
        n_valid = valid.sum()
        if n_valid < 10:
            continue

        vals = cf.loc[valid, feat]
        hw_vals = cf.loc[valid, "home_win"]

        # Try thresholds at 25th, 50th, 75th percentiles
        for pct, pct_label in [(75, "p75"), (50, "p50"), (25, "p25")]:
            thresh = np.percentile(vals, pct)
            if direction == ">":
                mask = vals > thresh
                bet_side = "home"
            else:
                mask = vals < thresh
                bet_side = "home"

            n_bets = mask.sum()
            if n_bets < 5:
                continue

            wins = hw_vals[mask].sum()
            wr = wins / n_bets * 100

            # P&L: bet on home when filter passes, use home_decimal_odds
            odds = cf.loc[valid & mask, "home_decimal_odds"].values
            outcomes = cf.loc[valid & mask, "home_win"].values.astype(float)
            pnl = np.where(outcomes, (odds - 1) * 100, -100).sum()
            roi = pnl / (n_bets * 100) * 100

            if abs(roi) > 1:  # Only show meaningful edges
                marker = " ***" if roi > 3 else ""
                print(f"  {desc:<30} {n_valid:7d} {f'{pct_label}={thresh:+.3f}':>10} "
                      f"{n_bets:5d} {wr:5.1f}% {pnl:+8.0f} {roi:+6.1f}%{marker}")

    # Away side analysis (flip perspective)
    print(f"\n  --- Away perspective (bet away when feature favors away) ---")
    for feat, desc, direction in diff_features:
        if feat not in cf.columns:
            continue
        valid = cf[feat].notna()
        n_valid = valid.sum()
        if n_valid < 10:
            continue

        vals = cf.loc[valid, feat]

        for pct, pct_label in [(25, "p25"), (50, "p50")]:
            thresh = np.percentile(vals, pct)
            if direction == ">":
                mask = vals < thresh  # inverted — away is better
            else:
                mask = vals > thresh  # inverted

            n_bets = mask.sum()
            if n_bets < 5:
                continue

            away_win = ~cf.loc[valid & mask, "home_win"].astype(bool)
            wins = away_win.sum()
            wr = wins / n_bets * 100

            odds = cf.loc[valid & mask, "away_decimal_odds"].values
            outcomes = away_win.values.astype(float)
            pnl = np.where(outcomes, (odds - 1) * 100, -100).sum()
            roi = pnl / (n_bets * 100) * 100

            if abs(roi) > 1:
                marker = " ***" if roi > 3 else ""
                print(f"  {desc:<30} {n_valid:7d} {f'{pct_label}={thresh:+.3f}':>10} "
                      f"{n_bets:5d} {wr:5.1f}% {pnl:+8.0f} {roi:+6.1f}%{marker}")


def analyze_combo_filters(cf: pd.DataFrame, label: str):
    """Test 2-way feature combos for CF edge."""
    print(f"\n  {'='*70}")
    print(f"  2-WAY COMBOS: {label}")
    print(f"  {'='*70}")

    n = len(cf)
    if n < 20:
        print(f"  Too few games ({n}).")
        return

    # Best single features for combo testing
    combos = [
        ("rpi_diff", ">", 0),
        ("wp_last10_diff", ">", 0),
        ("sp_ra_long_diff", "<", 0),
        ("sp_wr_long_diff", ">", 0),
        ("starter_fip_diff", "<", 0),
        ("elo_diff", ">", 0),
        ("pyth_wp_diff", ">", 0),
        ("streak_diff", ">", 0),
    ]

    results = []
    for i, (f1, d1, t1) in enumerate(combos):
        if f1 not in cf.columns:
            continue
        for f2, d2, t2 in combos[i+1:]:
            if f2 not in cf.columns:
                continue
            m1 = cf[f1] > t1 if d1 == ">" else cf[f1] < t1
            m2 = cf[f2] > t2 if d2 == ">" else cf[f2] < t2
            mask = m1 & m2 & cf[f1].notna() & cf[f2].notna()
            n_bets = mask.sum()
            if n_bets < 5:
                continue
            wins = cf.loc[mask, "home_win"].sum()
            wr = wins / n_bets * 100
            odds = cf.loc[mask, "home_decimal_odds"].values
            outcomes = cf.loc[mask, "home_win"].values.astype(float)
            pnl = np.where(outcomes, (odds - 1) * 100, -100).sum()
            roi = pnl / (n_bets * 100) * 100
            avg_odds = odds.mean()
            results.append({
                "filter": f"{f1}{d1}{t1} + {f2}{d2}{t2}",
                "bets": n_bets, "wr": wr, "pnl": pnl, "roi": roi,
                "avg_odds": avg_odds,
            })

    if not results:
        print("  No valid combos found.")
        return

    results.sort(key=lambda x: -x["roi"])
    print(f"\n  {'Filter':<50} {'Bets':>5} {'Win%':>6} {'P&L':>8} {'ROI':>7} {'AvgOd':>6}")
    print(f"  {'-'*85}")
    for r in results[:15]:
        marker = " ***" if r["roi"] > 5 else ""
        print(f"  {r['filter']:<50} {r['bets']:5d} {r['wr']:5.1f}% "
              f"{r['pnl']:+8.0f} {r['roi']:+6.1f}% {r['avg_odds']:5.2f}{marker}")


def main():
    parser = argparse.ArgumentParser(description="Coinflip zone analysis")
    parser.add_argument("--month", type=str, default=None,
                        help="Single month YYYY-MM (default: all 3 target months)")
    args = parser.parse_args()

    print("Loading data and building features...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    # Build ML predictions for edge_consensus
    print("Running ML walk-forward...")
    spec = build_spec_features(enriched=enriched)
    fold_results = run_walk_forward(spec, SPEC_FEATURES, "closing_decimal_odds_favorite")
    div_df = compute_divergence(fold_results)
    pred_cols = [c for c in div_df.columns if c.startswith("pred_")]
    if pred_cols:
        div_df["pred_consensus"] = div_df[pred_cols].mean(axis=1)
        div_df["edge_consensus"] = div_df["closing_decimal_odds_favorite"] - div_df["pred_consensus"]

    # Merge predictions
    master = enriched.copy()
    master["date"] = pd.to_datetime(master["date"]).dt.normalize()
    if "edge_consensus" in div_df.columns:
        merge_cols = ["season", "date", "home_team", "away_team"]
        avail = [c for c in merge_cols if c in div_df.columns]
        if avail:
            div_df["date"] = pd.to_datetime(div_df["date"]).dt.normalize()
            master = master.merge(
                div_df[avail + ["edge_consensus"]].drop_duplicates(subset=avail),
                on=avail, how="left", suffixes=("", "_div"),
            )

    # Select months
    if args.month:
        year, mon = int(args.month.split("-")[0]), int(args.month.split("-")[1])
        months = [(args.month, year, mon)]
    else:
        months = TARGET_MONTHS

    # ── Global CF stats across all seasons ────────────────────────────
    all_cf = master[master.get("is_coinflip", pd.Series(False, index=master.index)) == True]
    print(f"\n{'#'*80}")
    print(f"  COINFLIP ZONE: GLOBAL OVERVIEW")
    print(f"{'#'*80}")
    print(f"\n  Total coinflip games (all seasons): {len(all_cf)}")
    print(f"  CF rate: {len(all_cf)/len(master)*100:.1f}% of all games")
    if not all_cf.empty:
        print(f"  Home win rate in CF: {all_cf['home_win'].mean()*100:.1f}%")
        print(f"  Avg home odds: {all_cf['home_decimal_odds'].mean():.3f}")
        print(f"  Avg away odds: {all_cf['away_decimal_odds'].mean():.3f}")
        print(f"  Avg odds spread: {all_cf['odds_spread'].mean()*100:.2f}%")

    # Season-by-season CF volume
    if not all_cf.empty:
        print(f"\n  Season  CF Games  CF Rate  Home WR  Avg Home Odds")
        print(f"  {'-'*55}")
        for season in sorted(all_cf["season"].unique()):
            s_cf = all_cf[all_cf["season"] == season]
            s_all = master[master["season"] == season]
            print(f"  {season}     {len(s_cf):4d}     {len(s_cf)/len(s_all)*100:4.1f}%   "
                  f"{s_cf['home_win'].mean()*100:5.1f}%    {s_cf['home_decimal_odds'].mean():.3f}")

    # ── Per-month deep dive ──────────────────────────────────────────
    for month_label, year, mon in months:
        month_mask = (
            (pd.to_datetime(master["date"]).dt.year == year)
            & (pd.to_datetime(master["date"]).dt.month == mon)
        )
        month_data = master[month_mask]
        cf = month_data[month_data.get("is_coinflip", pd.Series(False, index=month_data.index)) == True].copy()

        print(f"\n{'#'*80}")
        print(f"  COINFLIP ZONE: {month_label}")
        print(f"{'#'*80}")
        print(f"\n  Games in month: {len(month_data)}")
        print(f"  Coinflip games: {len(cf)} ({len(cf)/len(month_data)*100:.1f}%)")

        if cf.empty:
            continue

        print(f"  Home win rate: {cf['home_win'].mean()*100:.1f}%")
        print(f"  Avg home odds: {cf['home_decimal_odds'].mean():.3f}")
        print(f"  Avg away odds: {cf['away_decimal_odds'].mean():.3f}")

        # Baseline P&L: blindly bet home in all CF games
        home_pnl = np.where(
            cf["home_win"].values,
            (cf["home_decimal_odds"].values - 1) * 100,
            -100,
        )
        print(f"\n  Baseline (blind home): {len(cf)} bets, "
              f"WR {cf['home_win'].mean()*100:.1f}%, "
              f"P&L {home_pnl.sum():+.0f}, ROI {home_pnl.sum()/(len(cf)*100)*100:+.1f}%")

        away_win = ~cf["home_win"].astype(bool)
        away_pnl = np.where(
            away_win.values,
            (cf["away_decimal_odds"].values - 1) * 100,
            -100,
        )
        print(f"  Baseline (blind away): {len(cf)} bets, "
              f"WR {away_win.mean()*100:.1f}%, "
              f"P&L {away_pnl.sum():+.0f}, ROI {away_pnl.sum()/(len(cf)*100)*100:+.1f}%")

        # Day-by-day distribution
        cf_dates = pd.to_datetime(cf["date"]).dt.date
        daily_counts = cf_dates.value_counts().sort_index()
        print(f"\n  Daily CF volume: avg {daily_counts.mean():.1f}, "
              f"max {daily_counts.max()}, min {daily_counts.min()}")

        # Feature analysis
        analyze_cf_features(cf, month_label)

    # Full-sample feature analysis
    if not all_cf.empty:
        print(f"\n{'#'*80}")
        print(f"  FULL-SAMPLE ANALYSIS (all seasons)")
        print(f"{'#'*80}")
        # Filter to bettable
        bettable_cf = all_cf[
            ~all_cf.get("involves_col", pd.Series(False, index=all_cf.index))
            & ~all_cf.get("is_extreme_line", pd.Series(False, index=all_cf.index))
        ].copy()
        analyze_cf_features(bettable_cf, "All Seasons (bettable)")
        analyze_combo_filters(bettable_cf, "All Seasons (bettable)")


if __name__ == "__main__":
    main()
