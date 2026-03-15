"""Train/test split validation for series dogon with pitcher features.

Critical question: is +3.07% ROI robust or curve-fitted?

Approach:
- TRAIN: 2010-2017 (8 seasons) — optimize filter thresholds
- TEST: 2018-2019, 2021 (3 seasons) — apply fixed thresholds, measure OOS performance
- Features are computed WITHIN each period (no leakage across split)

Note: features like rolling RPI/WP/pitcher stats use only prior games,
so there's no direct look-ahead. But threshold SELECTION on full data
could overfit, which is what we're testing here.
"""

import sys
import os
import warnings
import logging

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features
from src.series import (
    build_backtest_summary,
    identify_series,
    run_series_dogon,
    select_series_favorite,
    Series,
    SeriesResult,
)

# ── Load data ────────────────────────────────────────────────────────────
print("Loading data...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)

# ── Build features on FULL data ──────────────────────────────────────────
# This is OK because features only use prior games (no look-ahead).
# The key validation is whether THRESHOLD SELECTION generalizes.
print("Computing features (team + pitcher)...")
enriched = build_all_features(games, include_pitcher=True)
print(f"Total games with features: {len(enriched)}")

# ── Split into TRAIN and TEST ────────────────────────────────────────────
TRAIN_SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]
TEST_SEASONS = [2018, 2019, 2021]

train_games = enriched[enriched["season"].isin(TRAIN_SEASONS)].copy()
test_games = enriched[enriched["season"].isin(TEST_SEASONS)].copy()

print(f"\nTRAIN: {len(train_games)} games ({TRAIN_SEASONS})")
print(f"TEST:  {len(test_games)} games ({TEST_SEASONS})")

# ── Identify series for each split ───────────────────────────────────────
train_series = identify_series(train_games)
test_series = identify_series(test_games)

print(f"TRAIN series: {len(train_series)}")
print(f"TEST series:  {len(test_series)}")

# ── Feature lookup ───────────────────────────────────────────────────────
feature_cols = [
    "rpi_home", "rpi_away", "rpi_diff", "rpi_min",
    "wp_home", "wp_away", "wp_diff",
    "wp_last10_home", "wp_last10_away", "wp_last10_diff",
    "streak_home", "streak_away", "streak_diff",
    "games_played_min",
    "home_implied_prob", "away_implied_prob",
    "home_sp_wr_short", "home_sp_wr_long", "home_sp_wr_momentum",
    "away_sp_wr_short", "away_sp_wr_long", "away_sp_wr_momentum",
    "home_sp_ra_short", "home_sp_ra_long", "home_sp_ra_momentum",
    "away_sp_ra_short", "away_sp_ra_long", "away_sp_ra_momentum",
    "home_sp_fi_ra_long", "away_sp_fi_ra_long",
    "home_sp_starts", "away_sp_starts",
    "sp_wr_short_diff", "sp_wr_long_diff", "sp_wr_momentum_diff",
    "sp_ra_short_diff", "sp_ra_long_diff", "sp_ra_momentum_diff",
    "sp_fi_ra_combined",
]


def build_lookup(df):
    return df.set_index(["home_team", "away_team", "date"])


train_lookup = build_lookup(train_games)
test_lookup = build_lookup(test_games)


def get_series_features(series: Series, lookup) -> dict | None:
    g1 = series.games[0]
    key = (g1.home_team, g1.away_team, g1.date)
    if key in lookup.index:
        row = lookup.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return {col: row.get(col, np.nan) for col in feature_cols}
    return None


# ── Filtered dogon runner ────────────────────────────────────────────────


def run_filtered_dogon(
    series_list, lookup,
    min_rpi_diff=0.0, min_wp_diff=0.0,
    max_sp_ra_long_diff=None, min_sp_wr_long_diff=None,
    min_games_played=20, target_profit=100.0, max_games=2,
):
    results = []
    for series in series_list:
        if "COL" in (series.home_team, series.away_team):
            continue
        if series.games and pd.Timestamp(series.games[0].date).month == 9:
            continue

        feats = get_series_features(series, lookup)
        if feats is None:
            continue
        if feats.get("games_played_min", 0) < min_games_played:
            continue

        pick = select_series_favorite(series, method="game1_odds")
        if pick is None:
            continue
        favorite, underdog = pick

        g1 = series.games[0]
        fav_is_home = favorite == g1.home_team

        if fav_is_home:
            rpi_diff = feats.get("rpi_diff", 0)
            fav_wp = feats.get("wp_home", 0.5)
            dog_wp = feats.get("wp_away", 0.5)
            sp_ra_diff = feats.get("sp_ra_long_diff", np.nan)
            sp_wr_diff = feats.get("sp_wr_long_diff", np.nan)
        else:
            rpi_diff = -(feats.get("rpi_diff", 0))
            fav_wp = feats.get("wp_away", 0.5)
            dog_wp = feats.get("wp_home", 0.5)
            sp_ra_diff = -(feats.get("sp_ra_long_diff", np.nan))
            sp_wr_diff = -(feats.get("sp_wr_long_diff", np.nan))

        # Team filters
        if rpi_diff < min_rpi_diff:
            continue
        if (fav_wp - dog_wp) < min_wp_diff:
            continue

        # Pitcher filters
        has_pitcher = not (np.isnan(sp_ra_diff) if isinstance(sp_ra_diff, float) else False)
        if max_sp_ra_long_diff is not None:
            if not has_pitcher or sp_ra_diff > max_sp_ra_long_diff:
                continue
        if min_sp_wr_long_diff is not None:
            if not has_pitcher or sp_wr_diff < min_sp_wr_long_diff:
                continue

        result = run_series_dogon(series, favorite, target_profit, max_games)
        results.append(result)

    summary = build_backtest_summary(results)
    return results, summary


def report_line(name, summary, label=""):
    if summary.empty:
        print(f"  {label}{name:<52} {'---':>5}  {'---':>5}  {'---':>10}  {'---':>7}")
        return
    n = len(summary)
    wr = summary["won"].mean()
    pnl = summary["total_pnl"].sum()
    staked = summary["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    print(f"  {label}{name:<52} {n:>5}  {wr:>5.1%}  ${pnl:>+9,.0f}  {roi:>+6.2%}")


# ══════════════════════════════════════════════════════════════════════════
# Define configs to test
# ══════════════════════════════════════════════════════════════════════════

configs = {
    # Baselines (team only)
    "Baseline (no filters)": {},
    "RPI>=0.02": {"min_rpi_diff": 0.02},
    "RPI>=0.03": {"min_rpi_diff": 0.03},
    "RPI>=0.05": {"min_rpi_diff": 0.05},

    # Pitcher only
    "SP_WR>=0.10": {"min_sp_wr_long_diff": 0.10},
    "SP_RA<=0.0": {"max_sp_ra_long_diff": 0.0},
    "SP_RA<=-1.0": {"max_sp_ra_long_diff": -1.0},

    # RPI + Pitcher WR (best family from full backtest)
    "RPI>=0.02 + SP_WR>=0.10": {"min_rpi_diff": 0.02, "min_sp_wr_long_diff": 0.10},
    "RPI>=0.03 + SP_WR>=0.05": {"min_rpi_diff": 0.03, "min_sp_wr_long_diff": 0.05},
    "RPI>=0.03 + SP_WR>=0.10": {"min_rpi_diff": 0.03, "min_sp_wr_long_diff": 0.10},
    "RPI>=0.05 + SP_WR>=0.10": {"min_rpi_diff": 0.05, "min_sp_wr_long_diff": 0.10},

    # RPI + Pitcher RA
    "RPI>=0.02 + SP_RA<=0.0": {"min_rpi_diff": 0.02, "max_sp_ra_long_diff": 0.0},
    "RPI>=0.03 + SP_RA<=0.0": {"min_rpi_diff": 0.03, "max_sp_ra_long_diff": 0.0},

    # Triple (best from full backtest)
    "RPI>=0.03 + WP>=0.05 + SP_WR>=0.10": {
        "min_rpi_diff": 0.03, "min_wp_diff": 0.05, "min_sp_wr_long_diff": 0.10,
    },
    "RPI>=0.03 + RA<=0.0 + WR>=0.05": {
        "min_rpi_diff": 0.03, "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.05,
    },
    "RPI>=0.03 + RA<=-0.5 + WR>=0.10": {
        "min_rpi_diff": 0.03, "max_sp_ra_long_diff": -0.5, "min_sp_wr_long_diff": 0.10,
    },

    # THE BEST from full backtest (our "champion")
    "BEST: RPI>=0.03+WP>=0.05+RA<=0+WR>=0.10": {
        "min_rpi_diff": 0.03, "min_wp_diff": 0.05,
        "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.10,
    },
}

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("TRAIN/TEST SPLIT VALIDATION")
print(f"TRAIN: {TRAIN_SEASONS}  |  TEST: {TEST_SEASONS}")
print("=" * 90)
print(f"  {'Config':<55} {'N':>5}  {'WR':>5}  {'P&L':>10}  {'ROI':>7}")
print(f"  {'-'*55} {'-'*5}  {'-'*5}  {'-'*10}  {'-'*7}")

for name, params in configs.items():
    # TRAIN
    r_train, s_train = run_filtered_dogon(train_series, train_lookup, **params)
    # TEST
    r_test, s_test = run_filtered_dogon(test_series, test_lookup, **params)

    report_line(name, s_train, label="TRAIN  ")
    report_line(name, s_test, label="TEST   ")
    print()

# ══════════════════════════════════════════════════════════════════════════
# DETAILED: Best config per-season breakdown
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("DETAILED: Best config per-season breakdown")
print("=" * 90)

best_params = {
    "min_rpi_diff": 0.03, "min_wp_diff": 0.05,
    "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.10,
}

# Run on full data for season breakdown
r_full, s_full = run_filtered_dogon(
    train_series + test_series,
    build_lookup(enriched),
    **best_params,
)

if not s_full.empty:
    print(f"\n{'Season':<10} {'N':>6} {'WR':>7} {'P&L':>10} {'ROI':>8} {'Split':>8}")
    print("-" * 55)
    for season in sorted(s_full["season"].unique()):
        ss = s_full[s_full["season"] == season]
        n = len(ss)
        wr = ss["won"].mean()
        pnl = ss["total_pnl"].sum()
        staked = ss["total_stake"].sum()
        roi = pnl / staked if staked > 0 else 0
        split = "TRAIN" if season in TRAIN_SEASONS else "TEST"
        print(f"  {int(season):<8} {n:>6} {wr:>6.1%} ${pnl:>+9,.0f} {roi:>+7.2%} {split:>8}")

    # Aggregate by split
    print("-" * 55)
    for label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
        ss = s_full[s_full["season"].isin(seasons)]
        if ss.empty:
            continue
        n = len(ss)
        wr = ss["won"].mean()
        pnl = ss["total_pnl"].sum()
        staked = ss["total_stake"].sum()
        roi = pnl / staked if staked > 0 else 0
        print(f"  {label:<8} {n:>6} {wr:>6.1%} ${pnl:>+9,.0f} {roi:>+7.2%}")

# ══════════════════════════════════════════════════════════════════════════
# ROBUSTNESS: Compare multiple "good" configs on TEST only
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("ROBUSTNESS: Multiple promising configs on TEST data only")
print("=" * 90)
print(f"  {'Config':<55} {'N':>5}  {'WR':>5}  {'P&L':>10}  {'ROI':>7}")
print(f"  {'-'*55} {'-'*5}  {'-'*5}  {'-'*10}  {'-'*7}")

# Systematic grid on TEST data
for rpi_t in [0.02, 0.03, 0.04, 0.05]:
    for wr_t in [0.0, 0.05, 0.10, 0.15]:
        name = f"RPI>={rpi_t:.2f} + SP_WR>={wr_t:.2f}"
        r, s = run_filtered_dogon(
            test_series, test_lookup,
            min_rpi_diff=rpi_t, min_sp_wr_long_diff=wr_t,
        )
        report_line(name, s)

print("\nDone!")
