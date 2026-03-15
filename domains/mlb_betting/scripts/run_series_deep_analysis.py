"""Deep analysis of series dogon — find profitable subsets and patterns."""

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
from src.series import (
    backtest_series_dogon,
    build_backtest_summary,
    identify_series,
    run_series_dogon,
    select_series_favorite,
)

# ── Load Data ────────────────────────────────────────────────────────────
print("Loading data...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
print(f"Games: {len(games)}, Seasons: {sorted(games['season'].unique())}")

# ── Run baseline to get full results ─────────────────────────────────────
results, summary = backtest_series_dogon(
    games,
    target_profit=100.0,
    max_games=2,
    selection_method="game1_odds",
)
print(f"\nBaseline: {len(summary)} series, WR {summary['won'].mean():.1%}, "
      f"ROI {summary['total_pnl'].sum()/summary['total_stake'].sum():.2%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 1: Win rate and ROI by G1 implied probability buckets
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 1: ROI by favorite implied probability bucket")
print("=" * 70)

# Get favorite's implied prob for each series
fav_probs = []
for r in results:
    g1 = r.bets[0]
    if g1.bet_side == "home":
        # Favorite is home in game 1
        fav_probs.append(g1.decimal_odds)
    else:
        fav_probs.append(g1.decimal_odds)

summary["fav_g1_odds"] = [r.bets[0].decimal_odds for r in results]
summary["fav_g1_imp_prob"] = 1 / summary["fav_g1_odds"]  # Approx (includes vig)

bins = [0.45, 0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.65, 0.70, 0.80]
summary["prob_bucket"] = pd.cut(summary["fav_g1_imp_prob"], bins=bins)

print(f"\n{'Prob Bucket':<20} {'Series':>7} {'WR':>7} {'P&L':>10} {'ROI':>7} {'AvgOdds':>8}")
print("-" * 65)
for bucket, grp in summary.groupby("prob_bucket", observed=True):
    if len(grp) < 50:
        continue
    n = len(grp)
    wr = grp["won"].mean()
    pnl = grp["total_pnl"].sum()
    staked = grp["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    avg_odds = grp["fav_g1_odds"].mean()
    print(f"  {str(bucket):<18} {n:>7} {wr:>6.1%} {pnl:>+10,.0f} {roi:>6.1%} {avg_odds:>8.2f}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 2: Does home vs away favorite matter?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 2: Home vs Away favorite")
print("=" * 70)

summary["fav_is_home_g1"] = [r.bets[0].bet_side == "home" for r in results]

for label, mask in [("Fav = HOME", True), ("Fav = AWAY", False)]:
    grp = summary[summary["fav_is_home_g1"] == mask]
    n = len(grp)
    wr = grp["won"].mean()
    pnl = grp["total_pnl"].sum()
    staked = grp["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    print(f"  {label}: {n} series, {wr:.1%} WR, P&L ${pnl:+,.0f}, ROI {roi:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 3: Series length and which game in series matters
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 3: Game 1 vs Game 2 win rates (all series)")
print("=" * 70)

# Get individual bet-level data
all_bets = []
for r in results:
    for b in r.bets:
        all_bets.append({
            "series_key": b.series_key,
            "game_in_series": b.game_in_series,
            "won": b.won,
            "pnl": b.pnl,
            "stake": b.stake,
            "odds": b.decimal_odds,
            "is_dogon": b.is_dogon,
        })
bets_df = pd.DataFrame(all_bets)

for gn in [1, 2]:
    subset = bets_df[bets_df["game_in_series"] == gn]
    n = len(subset)
    wr = subset["won"].mean()
    pnl = subset["pnl"].sum()
    staked = subset["stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    print(f"  Game {gn}: {n} bets, {wr:.1%} WR, P&L ${pnl:+,.0f}, ROI {roi:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 4: P&L breakdown — how much does the vig cost us?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 4: Vig impact analysis")
print("=" * 70)

g1_bets = bets_df[bets_df["game_in_series"] == 1]
avg_g1_odds = g1_bets["odds"].mean()
avg_g1_imp = (1 / g1_bets["odds"]).mean()
g1_wr = g1_bets["won"].mean()

print(f"  G1 average decimal odds: {avg_g1_odds:.3f}")
print(f"  G1 average implied prob (from odds): {avg_g1_imp:.3f}")
print(f"  G1 actual win rate: {g1_wr:.3f}")
print(f"  Delta (actual - implied): {g1_wr - avg_g1_imp:.3f}")
print()
print(f"  Favorites win G1: {g1_wr:.1%} of the time")
print(f"  Odds imply they should win: {avg_g1_imp:.1%}")
print(f"  Gap = {(g1_wr - avg_g1_imp)*100:.1f}pp — this is the vig eating our edge")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 5: What about underdogs? Bet AGAINST favorites in G2?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 5: Contrarian — bet UNDERDOG with dogon")
print("=" * 70)

# Run backtest where we always pick the underdog
all_series_list = identify_series(games)

contrarian_results = []
for series in all_series_list:
    # Skip Colorado, September
    if "COL" in (series.home_team, series.away_team):
        continue
    if series.games and pd.Timestamp(series.games[0].date).month == 9:
        continue

    pick = select_series_favorite(series, method="game1_odds")
    if pick is None:
        continue

    _fav, underdog = pick  # We bet on the UNDERDOG
    result = run_series_dogon(series, underdog, target_profit=100.0, max_games=2)
    contrarian_results.append(result)

c_summary = build_backtest_summary(contrarian_results)
if not c_summary.empty:
    n = len(c_summary)
    wr = c_summary["won"].mean()
    pnl = c_summary["total_pnl"].sum()
    staked = c_summary["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    print(f"  Underdog dogon: {n} series, {wr:.1%} WR, P&L ${pnl:+,.0f}, ROI {roi:+.1%}")
    print(f"  Max exposure: ${c_summary['max_exposure'].max():,.0f}")
    print(f"  Avg max exposure: ${c_summary['max_exposure'].mean():,.0f}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 6: Day of week — Monday vs Friday series starts
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 6: Series start day of week")
print("=" * 70)

summary["start_dow"] = pd.to_datetime(summary["start_date"]).dt.day_name()

print(f"\n{'Day':<12} {'Series':>7} {'WR':>7} {'P&L':>10} {'ROI':>7}")
print("-" * 50)
for dow in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
    grp = summary[summary["start_dow"] == dow]
    if len(grp) < 50:
        continue
    n = len(grp)
    wr = grp["won"].mean()
    pnl = grp["total_pnl"].sum()
    staked = grp["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    print(f"  {dow:<10} {n:>7} {wr:>6.1%} {pnl:>+10,.0f} {roi:>6.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 7: Mathematical analysis — what edge do we need?
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 7: Mathematical edge requirement")
print("=" * 70)

print("\nFor 2-game dogon to break even:")
print("  If G1 odds = 1.70 (favorite), stake = $100/(1.70-1) = $143")
print("  If G1 lost, need $243 profit from G2")
print("  If G2 odds = 1.70, G2 stake = $243/(1.70-1) = $347")
print("  Total risk if both lost: $143 + $347 = $490")
print("  Profit if either wins: $100")
print()

# Actual math from our data
avg_g1_odds = summary["g1_odds"].mean()
g2_rows = summary[summary["needed_dogon"]]
if not g2_rows.empty:
    avg_g2_odds = g2_rows["g2_odds"].mean()
    avg_g1_stake = 100 / (avg_g1_odds - 1)
    avg_g2_stake = (avg_g1_stake + 100) / (avg_g2_odds - 1)

    total_risk = avg_g1_stake + avg_g2_stake

    # P(series win) = P(g1 win) + P(g1 loss) × P(g2 win)
    # For breakeven: $100 × P(win) = total_risk × P(lose)
    # $100 × P(win) = total_risk × (1 - P(win))
    # P(win) = total_risk / (total_risk + 100)

    be_wr = total_risk / (total_risk + 100)

    print(f"From our data:")
    print(f"  Avg G1 odds: {avg_g1_odds:.2f} -> stake ${avg_g1_stake:.0f}")
    print(f"  Avg G2 odds: {avg_g2_odds:.2f} -> stake ${avg_g2_stake:.0f}")
    print(f"  Total risk per lost series: ${total_risk:.0f}")
    print(f"  Profit per won series: $100")
    print(f"  Breakeven series win rate: {be_wr:.1%}")
    print(f"  Our actual win rate: {summary['won'].mean():.1%}")
    print(f"  Gap: {(summary['won'].mean() - be_wr)*100:+.1f}pp")
    print()

    # What if we improved selection by X pp?
    print("  Sensitivity: what win rate do we need?")
    for target_roi in [0, 0.05, 0.10, 0.15, 0.20]:
        # roi = (100 × wr - total_risk × (1-wr)) / (stake_g1 × wr_g1 + ...)
        # Simplified: roi ~ (100 × wr - total_risk × (1-wr)) / avg_stake_per_series
        needed_wr = (total_risk + total_risk * target_roi) / (total_risk + 100 + total_risk * target_roi / 0.5)
        print(f"    For ROI {target_roi:+.0%}: need ~{needed_wr:.1%} series WR (we have {summary['won'].mean():.1%})")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 8: Bankroll simulation — maximum drawdown
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 8: Bankroll simulation (chronological)")
print("=" * 70)

# Sort by date
summary_sorted = summary.sort_values("start_date")
cum_pnl = summary_sorted["total_pnl"].cumsum()
running_max = cum_pnl.cummax()
drawdown = cum_pnl - running_max

print(f"  Starting bankroll: $10,000")
print(f"  Final P&L: ${cum_pnl.iloc[-1]:+,.0f}")
print(f"  Max cumulative P&L: ${running_max.max():+,.0f}")
print(f"  Max drawdown: ${drawdown.min():,.0f}")
print(f"  Final bankroll: ${10_000 + cum_pnl.iloc[-1]:,.0f}")

# Worst streak of consecutive losses
losses_streak = 0
max_losses_streak = 0
for won in summary_sorted["won"].values:
    if not won:
        losses_streak += 1
        max_losses_streak = max(max_losses_streak, losses_streak)
    else:
        losses_streak = 0
print(f"  Max consecutive series losses: {max_losses_streak}")

# Peak single-series loss
worst_series = summary["total_pnl"].min()
print(f"  Worst single series P&L: ${worst_series:,.0f}")

# ══════════════════════════════════════════════════════════════════════════
# SUMMARY & CONCLUSIONS
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)
print("""
1. RAW DOGON IS UNPROFITABLE: ~-2.8% ROI across all configs
   - 80.9% WR sounds great but isn't enough vs the vig
   - Each loss wipes out multiple wins (asymmetric risk)

2. VIG IS THE ENEMY: Favorites win 58.3% (G1) but odds imply ~57-60%
   - The bookmaker prices in favorite strength accurately
   - No free money just from picking favorites + dogon

3. PROBABILITY BUCKETS: All buckets are negative ROI
   - Stronger favorites = higher WR but worse ROI (lower odds)
   - Moderate favorites = worse WR but slightly better odds

4. EDGE MUST COME FROM SELECTIVITY:
   - Current: bet on ALL 6432 series -> -2.8% ROI
   - Need: select ~500-1000 best series using features (RPI, pitcher, form)
   - The question is: can features identify series where fav WR > breakeven?

5. NEXT STEPS:
   - Build features.py with rolling RPI, pitcher stats, team form
   - Add features to series selection criteria
   - Find the 10-20% of series with genuine edge
   - Test whether selective approach turns profitable
""")
