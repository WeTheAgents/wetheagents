"""Series dogon with feature-based selection — the key test.

Legacy insight: selectivity IS the edge. We need to filter series
using RPI, form, and streak features to find the ~500-1000 best
series out of ~6400.
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
    print_backtest_report,
    run_series_dogon,
    select_series_favorite,
    Series,
    SeriesResult,
)

# ── Load and build features ──────────────────────────────────────────────
print("Loading data and computing features (takes ~3 min)...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
enriched = build_all_features(games)
print(f"Games with features: {len(enriched)}")

# ── Identify series ──────────────────────────────────────────────────────
all_series = identify_series(enriched)
print(f"Total series: {len(all_series)}")

# ── Build feature lookup: for each series game 1, get features ───────────
# Create a lookup from (home_team, away_team, date) -> features
feature_cols = [
    "rpi_home", "rpi_away", "rpi_diff", "rpi_min",
    "wp_home", "wp_away", "wp_diff",
    "wp_last10_home", "wp_last10_away", "wp_last10_diff",
    "streak_home", "streak_away", "streak_diff",
    "rpg_home", "rpg_away",
    "rapg_home", "rapg_away",
    "games_played_min",
    "home_implied_prob", "away_implied_prob",
]

# Index enriched for fast lookup
enriched_lookup = enriched.set_index(["home_team", "away_team", "date"])


def get_series_features(series: Series) -> dict | None:
    """Get features for game 1 of a series."""
    g1 = series.games[0]
    key = (g1.home_team, g1.away_team, g1.date)
    if key in enriched_lookup.index:
        row = enriched_lookup.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]  # If multiple matches, take first
        return {col: row.get(col, np.nan) for col in feature_cols}
    return None


# ── Run strategy with feature filters ────────────────────────────────────


def run_filtered_dogon(
    series_list: list[Series],
    min_rpi_diff: float = 0.0,
    min_rpi_min: float = 0.0,
    min_wp_diff: float = 0.0,
    min_streak_fav: int | None = None,
    max_streak_dog: int | None = None,
    min_games_played: int = 20,
    min_implied_prob: float = 0.0,
    max_implied_prob: float = 1.0,
    target_profit: float = 100.0,
    max_games: int = 2,
) -> tuple[list[SeriesResult], pd.DataFrame]:
    """Run dogon with feature-based filtering."""
    results = []
    skipped = {
        "colorado": 0, "september": 0, "no_features": 0,
        "no_favorite": 0, "games_played": 0,
        "rpi_diff": 0, "rpi_min": 0, "wp_diff": 0,
        "streak": 0, "prob_filter": 0,
    }

    for series in series_list:
        # Skip Colorado
        if "COL" in (series.home_team, series.away_team):
            skipped["colorado"] += 1
            continue
        # Skip September
        if series.games and pd.Timestamp(series.games[0].date).month == 9:
            skipped["september"] += 1
            continue

        # Get features
        feats = get_series_features(series)
        if feats is None:
            skipped["no_features"] += 1
            continue

        # Games played filter
        if feats.get("games_played_min", 0) < min_games_played:
            skipped["games_played"] += 1
            continue

        # Select favorite from G1 odds
        pick = select_series_favorite(series, method="game1_odds")
        if pick is None:
            skipped["no_favorite"] += 1
            continue

        favorite, underdog = pick

        # Determine favorite's features
        g1 = series.games[0]
        if favorite == g1.home_team:
            fav_rpi = feats.get("rpi_home", 0.5)
            dog_rpi = feats.get("rpi_away", 0.5)
            fav_wp = feats.get("wp_home", 0.5)
            dog_wp = feats.get("wp_away", 0.5)
            fav_streak = feats.get("streak_home", 0)
            dog_streak = feats.get("streak_away", 0)
            fav_prob = g1.home_implied_prob
            rpi_diff = feats.get("rpi_diff", 0)  # home - away = fav - dog
        else:
            fav_rpi = feats.get("rpi_away", 0.5)
            dog_rpi = feats.get("rpi_home", 0.5)
            fav_wp = feats.get("wp_away", 0.5)
            dog_wp = feats.get("wp_home", 0.5)
            fav_streak = feats.get("streak_away", 0)
            dog_streak = feats.get("streak_home", 0)
            fav_prob = g1.away_implied_prob
            rpi_diff = -(feats.get("rpi_diff", 0))  # flip: fav - dog

        # Implied prob filter
        if fav_prob < min_implied_prob or fav_prob > max_implied_prob:
            skipped["prob_filter"] += 1
            continue

        # RPI diff filter (favorite's RPI advantage)
        if rpi_diff < min_rpi_diff:
            skipped["rpi_diff"] += 1
            continue

        # RPI quality floor
        rpi_min_val = min(fav_rpi, dog_rpi)
        if rpi_min_val < min_rpi_min:
            skipped["rpi_min"] += 1
            continue

        # WP diff filter
        wp_diff = fav_wp - dog_wp
        if wp_diff < min_wp_diff:
            skipped["wp_diff"] += 1
            continue

        # Streak filter
        if min_streak_fav is not None and fav_streak < min_streak_fav:
            skipped["streak"] += 1
            continue
        if max_streak_dog is not None and dog_streak > max_streak_dog:
            skipped["streak"] += 1
            continue

        # Run dogon
        result = run_series_dogon(series, favorite, target_profit, max_games)
        results.append(result)

    summary = build_backtest_summary(results)
    return results, summary


def report(name, results, summary):
    """Print compact report."""
    if summary.empty:
        print(f"  {name}: 0 series (all filtered out)")
        return
    n = len(summary)
    wr = summary["won"].mean()
    pnl = summary["total_pnl"].sum()
    staked = summary["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    max_exp = summary["max_exposure"].max()
    print(f"  {name:<50} {n:>5} series, {wr:>5.1%} WR, "
          f"P&L ${pnl:>+8,.0f}, ROI {roi:>+5.1%}, Max$ {max_exp:>6,.0f}")


# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 1: RPI-based selection")
print("=" * 70)

for rpi_thresh in [0.00, 0.01, 0.02, 0.03, 0.04, 0.05]:
    r, s = run_filtered_dogon(
        all_series, min_rpi_diff=rpi_thresh, min_games_played=20,
    )
    report(f"RPI diff >= {rpi_thresh:+.2f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 2: RPI + WP combined")
print("=" * 70)

for rpi_t, wp_t in [(0.01, 0.00), (0.02, 0.00), (0.02, 0.05),
                     (0.03, 0.05), (0.03, 0.10), (0.04, 0.10)]:
    r, s = run_filtered_dogon(
        all_series, min_rpi_diff=rpi_t, min_wp_diff=wp_t, min_games_played=20,
    )
    report(f"RPI>={rpi_t:+.2f} + WP>={wp_t:+.2f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 3: RPI + quality floor (MinRPIoBet from legacy)")
print("=" * 70)

for rpi_min in [0.47, 0.48, 0.49, 0.50]:
    r, s = run_filtered_dogon(
        all_series, min_rpi_diff=0.02, min_rpi_min=rpi_min, min_games_played=20,
    )
    report(f"RPI diff>=0.02 + min RPI>={rpi_min}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 4: Streak-based filters")
print("=" * 70)

# Fav on winning streak
for streak_min in [1, 2, 3]:
    r, s = run_filtered_dogon(
        all_series, min_streak_fav=streak_min, min_games_played=20,
    )
    report(f"Fav streak >= W{streak_min}", r, s)

# Dog on losing streak
for streak_max in [-1, -2, -3]:
    r, s = run_filtered_dogon(
        all_series, max_streak_dog=streak_max, min_games_played=20,
    )
    report(f"Dog streak <= L{abs(streak_max)}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 5: Combined (RPI + streak + WP)")
print("=" * 70)

combos = [
    {"min_rpi_diff": 0.02, "min_streak_fav": 1, "min_wp_diff": 0.05},
    {"min_rpi_diff": 0.02, "min_streak_fav": 2, "min_wp_diff": 0.05},
    {"min_rpi_diff": 0.03, "min_streak_fav": 1, "min_wp_diff": 0.05},
    {"min_rpi_diff": 0.02, "max_streak_dog": -2, "min_wp_diff": 0.00},
    {"min_rpi_diff": 0.01, "min_streak_fav": 1, "max_streak_dog": -1},
    {"min_rpi_diff": 0.02, "min_streak_fav": 1, "max_streak_dog": -1, "min_wp_diff": 0.05},
    {"min_rpi_diff": 0.03, "min_streak_fav": 2, "min_wp_diff": 0.10, "min_rpi_min": 0.48},
]
for combo in combos:
    r, s = run_filtered_dogon(all_series, **combo, min_games_played=20)
    desc = " + ".join(f"{k}={v}" for k, v in combo.items())
    report(desc[:50], r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 6: Implied prob sweet spot (from Analysis 1)")
print("=" * 70)

# The (0.50, 0.52] bucket was +10.8% ROI in raw dogon
for lo, hi in [(0.50, 0.53), (0.50, 0.55), (0.53, 0.58)]:
    r, s = run_filtered_dogon(
        all_series, min_implied_prob=lo, max_implied_prob=hi, min_games_played=20,
    )
    report(f"Implied prob [{lo:.2f}, {hi:.2f})", r, s)

# With RPI on top
for lo, hi in [(0.50, 0.53), (0.50, 0.55)]:
    r, s = run_filtered_dogon(
        all_series, min_implied_prob=lo, max_implied_prob=hi,
        min_rpi_diff=0.02, min_games_played=20,
    )
    report(f"Prob [{lo:.2f},{hi:.2f}) + RPI>=0.02", r, s)

# ══════════════════════════════════════════════════════════════════════════
# BEST CONFIG: detailed report
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("DETAILED: Best config deep dive")
print("=" * 70)

# Run the most promising config
best_r, best_s = run_filtered_dogon(
    all_series,
    min_rpi_diff=0.02,
    min_wp_diff=0.05,
    min_games_played=20,
    target_profit=100.0,
    max_games=2,
)
print_backtest_report(best_r, best_s)
