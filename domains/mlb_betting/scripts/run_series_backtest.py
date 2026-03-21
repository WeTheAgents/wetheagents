"""Run series dogon backtest with multiple configurations."""

import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.series import (
    backtest_series_dogon,
    identify_series,
    print_backtest_report,
    series_summary,
)

# ── 1. Load Data ─────────────────────────────────────────────────────────
print("=" * 70)
print("LOADING DATA")
print("=" * 70)
games = load_all_seasons()
print(f"Loaded: {len(games)} games")
games = apply_data_filters(games)
print(f"After filters: {len(games)} games")
games = add_derived_odds(games)
print(f"Seasons: {sorted(games['season'].unique())}")

# Check NaN counts in critical columns
for col in ["home_final", "away_final", "home_close_ml", "away_close_ml"]:
    n_nan = games[col].isna().sum()
    if n_nan > 0:
        print(f"  WARNING: {n_nan} NaN values in {col}")

# ── 2. Series Overview ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SERIES IDENTIFICATION")
print("=" * 70)
all_series = identify_series(games)
sdf = series_summary(all_series)
print(f"\nTotal series: {len(all_series)}")
print("Series length distribution:")
print(sdf["length"].value_counts().sort_index().to_string())
print("\nBy season:")
for season, grp in sdf.groupby("season"):
    print(f"  {int(season)}: {len(grp)} series (avg {grp['length'].mean():.1f} games)")

# ── 3. Backtest Configurations ──────────────────────────────────────────

configs = [
    {
        "name": "1. BASELINE: Any favorite, $100 target, 2-game dogon",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 2,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.0,
            "max_implied_prob": 1.0,
        },
    },
    {
        "name": "2. FILTERED: Favorite implied prob > 0.55",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 2,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.55,
            "max_implied_prob": 0.80,
        },
    },
    {
        "name": "3. STRONG: Favorite implied prob > 0.60",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 2,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.60,
            "max_implied_prob": 0.80,
        },
    },
    {
        "name": "4. NO DOGON: G1 only, flat $100 target",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 1,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.0,
            "max_implied_prob": 1.0,
        },
    },
    {
        "name": "5. 3-GAME DOGON: Up to 3 recovery attempts",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 3,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.0,
            "max_implied_prob": 1.0,
        },
    },
    {
        "name": "6. MODERATE FAVORITES: prob 0.52-0.60 (avoid heavy favorites)",
        "kwargs": {
            "target_profit": 100.0,
            "max_games": 2,
            "selection_method": "game1_odds",
            "min_implied_prob": 0.52,
            "max_implied_prob": 0.60,
        },
    },
]

for cfg in configs:
    print("\n\n" + "#" * 70)
    print(f"# {cfg['name']}")
    print("#" * 70)
    try:
        results, summary = backtest_series_dogon(games, **cfg["kwargs"])
        print_backtest_report(results, summary)

        # Additional dogon risk analysis
        if not summary.empty and "max_exposure" in summary.columns:
            print("\nRisk metrics:")
            print(f"  Median stake (G1): ${summary['g1_odds'].apply(lambda o: 100/(o-1) if o > 1 else 0).median():,.0f}")
            if summary["needed_dogon"].any():
                dogon_stakes = summary.loc[summary["needed_dogon"], "g2_stake"]
                print(f"  Median dogon stake: ${dogon_stakes.median():,.0f}")
                print(f"  Max dogon stake: ${dogon_stakes.max():,.0f}")
                print(f"  95th pctile dogon stake: ${dogon_stakes.quantile(0.95):,.0f}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

# ── 4. Comparison Table ─────────────────────────────────────────────────
print("\n\n" + "=" * 70)
print("COMPARISON TABLE")
print("=" * 70)
print(f"{'Config':<55} {'Series':>7} {'WR':>7} {'P&L':>10} {'ROI':>7} {'Max$':>8}")
print("-" * 100)

for cfg in configs:
    try:
        results, summary = backtest_series_dogon(games, **cfg["kwargs"])
        if not summary.empty:
            n = len(summary)
            wr = summary["won"].mean()
            pnl = summary["total_pnl"].sum()
            staked = summary["total_stake"].sum()
            roi = pnl / staked if staked > 0 else 0
            max_exp = summary["max_exposure"].max()
            name = cfg["name"][:55]
            print(f"{name:<55} {n:>7} {wr:>6.1%} {pnl:>+10,.0f} {roi:>6.1%} {max_exp:>8,.0f}")
    except Exception:
        pass

print()
