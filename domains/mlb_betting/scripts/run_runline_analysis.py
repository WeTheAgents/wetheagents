"""Run Line analysis: favorites -1.5 and underdogs +1.5 profitability."""

import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

# ── Load Data ────────────────────────────────────────────────────────────
print("Loading data...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
print(f"Games: {len(games)}")

# ── Compute Run Line outcomes ────────────────────────────────────────────
# Run Line = -1.5 for home / +1.5 for away (standard MLB run line)
games["home_margin"] = games["home_final"] - games["away_final"]
games["home_rl_cover"] = (games["home_margin"] >= 2).astype(int)  # Home -1.5
games["away_rl_cover"] = (games["home_margin"] <= -2).astype(int)  # Away covers +1.5
# Push is impossible with 1.5 run line

# Run line odds from data
games["home_rl_odds"] = games["home_run_line_odds"]

# Apply betting filters
bettable = games[
    ~games["involves_col"]
    & ~games["is_september"]
    & ~games["is_extreme_line"]
].copy()
print(f"Bettable games: {len(bettable)}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 1: Favorite Run Line coverage rates
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 1: How often do favorites cover -1.5?")
print("=" * 70)

# Determine who is favorite (lower ML = more favored)
bettable["favorite_is_home"] = bettable["home_implied_prob"] > bettable["away_implied_prob"]

# Favorite covers RL
fav_home = bettable[bettable["favorite_is_home"]].copy()
fav_away = bettable[~bettable["favorite_is_home"]].copy()

fav_home_cover_rate = fav_home["home_rl_cover"].mean()
fav_away_cover_rate = fav_away["away_rl_cover"].mean()

print(f"\nFavorite is HOME ({len(fav_home)} games):")
print(f"  Covers -1.5: {fav_home_cover_rate:.1%}")
print(f"  ML win rate: {fav_home['home_win'].mean():.1%}")

print(f"\nFavorite is AWAY ({len(fav_away)} games):")
print(f"  Covers -1.5: {fav_away_cover_rate:.1%}")
print(f"  ML win rate: {(1 - fav_away['home_win'].mean()):.1%}")

overall_fav_rl = np.concatenate([
    fav_home["home_rl_cover"].values,
    fav_away["away_rl_cover"].values,
])
print(f"\nOverall favorite -1.5 cover rate: {overall_fav_rl.mean():.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 2: ROI betting favorite -1.5 with available RL odds
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 2: ROI for favorite -1.5 (using actual RL odds)")
print("=" * 70)

# We only have home_run_line_odds in our data
# home_run_line is typically -1.5 for home
# If home is favorite, bet home -1.5; if away is favorite, this is trickier

# Let's focus on home favorites covering -1.5 (we have the odds)
rl_valid = fav_home[fav_home["home_rl_odds"].notna() & (fav_home["home_rl_odds"] != 0)].copy()

# Convert American RL odds to decimal
def american_to_decimal_local(ml):
    if ml > 0:
        return 1 + ml / 100
    elif ml < 0:
        return 1 + 100 / abs(ml)
    return 1.0

rl_valid["rl_dec_odds"] = rl_valid["home_rl_odds"].apply(american_to_decimal_local)

# Flat bet ROI
rl_valid["rl_pnl"] = np.where(
    rl_valid["home_rl_cover"],
    100 * (rl_valid["rl_dec_odds"] - 1),
    -100,
)

n_rl = len(rl_valid)
wr = rl_valid["home_rl_cover"].mean()
total_pnl = rl_valid["rl_pnl"].sum()
total_staked = n_rl * 100
roi = total_pnl / total_staked
print("\nHome favorite -1.5 (flat $100 bets):")
print(f"  Bets: {n_rl}")
print(f"  Cover rate: {wr:.1%}")
print(f"  Avg RL odds: {rl_valid['rl_dec_odds'].mean():.3f}")
print(f"  P&L: ${total_pnl:+,.0f}")
print(f"  ROI: {roi:+.2%}")

# By season
print("\nBy season:")
for season, grp in rl_valid.groupby("season"):
    n = len(grp)
    w = grp["home_rl_cover"].mean()
    pnl = grp["rl_pnl"].sum()
    r = pnl / (n * 100)
    print(f"  {int(season)}: {n} bets, {w:.1%} cover, P&L ${pnl:+,.0f}, ROI {r:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 3: Underdog +1.5 ROI
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 3: Underdog +1.5 ROI")
print("=" * 70)

# Underdog is AWAY when home is favorite
# Away +1.5 covers when margin <= 1 (away wins or loses by exactly 1)
fav_home_valid = fav_home[fav_home["home_rl_odds"].notna() & (fav_home["home_rl_odds"] != 0)].copy()
fav_home_valid["away_rl_cover"] = (fav_home_valid["home_margin"] <= 1).astype(int)

# Away +1.5 odds = mirror of home -1.5
# If home -1.5 is at -150 (1.667), away +1.5 is typically around +130 (2.30)
# Approximation: away +1.5 odds ~ 1 / (1 - 1/home_rl_dec_odds) / vig_factor
fav_home_valid["home_rl_dec"] = fav_home_valid["home_rl_odds"].apply(american_to_decimal_local)

# Standard approximation: if home -1.5 at odds D, away +1.5 ~ (1/(1-1/D)) * 0.95
# Better: just flip the implied prob with ~5% vig
fav_home_valid["home_rl_imp"] = 1 / fav_home_valid["home_rl_dec"]
fav_home_valid["away_rl_imp_est"] = 1 - fav_home_valid["home_rl_imp"] + 0.05  # Add vig back
fav_home_valid["away_rl_dec_est"] = 1 / fav_home_valid["away_rl_imp_est"]

# Actually, simpler: use common RL pricing
# If home -1.5 at -150, away +1.5 typically at +130
# If home -1.5 at +150, away +1.5 typically at -170
# Standard RL pairs: (-150/+130), (-120/+100), (-110/-110), (+100/-120)
# Let's use a typical mapping
def estimate_opposite_rl(home_ml_odds):
    """Estimate away +1.5 odds from home -1.5 odds."""
    # Convert home RL American to implied prob
    if home_ml_odds < 0:
        imp = abs(home_ml_odds) / (abs(home_ml_odds) + 100)
    else:
        imp = 100 / (home_ml_odds + 100)
    # Opposite side implied prob (with ~4-5% total vig)
    other_imp = 1.045 - imp  # Total market ~104.5%
    if other_imp <= 0 or other_imp >= 1:
        return 1.91  # fallback
    return 1 / other_imp

fav_home_valid["away_rl_dec_est2"] = fav_home_valid["home_rl_odds"].apply(estimate_opposite_rl)

# PnL for away underdog +1.5
fav_home_valid["away_rl_pnl"] = np.where(
    fav_home_valid["away_rl_cover"],
    100 * (fav_home_valid["away_rl_dec_est2"] - 1),
    -100,
)

n = len(fav_home_valid)
wr = fav_home_valid["away_rl_cover"].mean()
pnl = fav_home_valid["away_rl_pnl"].sum()
roi = pnl / (n * 100)
print("\nAway underdog +1.5 vs home favorite (estimated odds):")
print(f"  Bets: {n}")
print(f"  Cover rate: {wr:.1%}")
print(f"  Avg est. odds: {fav_home_valid['away_rl_dec_est2'].mean():.3f}")
print(f"  P&L: ${pnl:+,.0f}")
print(f"  ROI: {roi:+.2%}")

print("\nBy season:")
for season, grp in fav_home_valid.groupby("season"):
    n = len(grp)
    w = grp["away_rl_cover"].mean()
    pnl = grp["away_rl_pnl"].sum()
    r = pnl / (n * 100)
    print(f"  {int(season)}: {n} bets, {w:.1%} cover, P&L ${pnl:+,.0f}, ROI {r:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 4: Run Line by implied probability bucket
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 4: Favorite -1.5 cover rate by strength bucket")
print("=" * 70)

rl_valid2 = rl_valid.copy()
bins = [0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.65, 0.70, 0.80]
rl_valid2["prob_bucket"] = pd.cut(rl_valid2["home_implied_prob"], bins=bins)

print(f"\n{'Prob Bucket':<20} {'Games':>7} {'Cover%':>8} {'ML WR':>7} {'RL ROI':>8} {'AvgOdds':>8}")
print("-" * 65)
for bucket, grp in rl_valid2.groupby("prob_bucket", observed=True):
    if len(grp) < 50:
        continue
    n = len(grp)
    cover = grp["home_rl_cover"].mean()
    ml_wr = grp["home_win"].mean()
    pnl = grp["rl_pnl"].sum()
    roi = pnl / (n * 100)
    avg_odds = grp["rl_dec_odds"].mean()
    print(f"  {str(bucket):<18} {n:>7} {cover:>7.1%} {ml_wr:>6.1%} {roi:>+7.1%} {avg_odds:>8.3f}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 5: Score margin distribution
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 5: Score margin distribution (home perspective)")
print("=" * 70)

margins = bettable["home_margin"]
print(f"\nMean margin: {margins.mean():+.2f}")
print(f"Median margin: {margins.median():+.1f}")
print(f"Std dev: {margins.std():.2f}")
print("\nMargin distribution:")
for m in range(-8, 9):
    pct = (margins == m).mean()
    bar = "#" * int(pct * 200)
    print(f"  {m:+2d}: {pct:5.1%} {bar}")

print(f"\n  Home wins by 2+: {(margins >= 2).mean():.1%}")
print(f"  Home wins by 1:  {(margins == 1).mean():.1%}")
print(f"  Away wins by 1:  {(margins == -1).mean():.1%}")
print(f"  Away wins by 2+: {(margins <= -2).mean():.1%}")

# ══════════════════════════════════════════════════════════════════════════
# ANALYSIS 6: RPI-filtered Run Line
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("ANALYSIS 6: Run Line with RPI filter (if features available)")
print("=" * 70)

# Build features
from src.features import build_all_features

print("Building features (this takes ~3 min)...")
enriched = build_all_features(games)

# Merge features into bettable
rl_enriched = enriched[
    ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & enriched["home_rl_odds"].notna()
    & (enriched["home_rl_odds"] != 0)
    & (enriched["home_implied_prob"] > enriched["away_implied_prob"])  # Home is favorite
    & (enriched["games_played_min"] >= 20)  # Enough games for features
].copy()

rl_enriched["home_margin"] = rl_enriched["home_final"] - rl_enriched["away_final"]
rl_enriched["home_rl_cover"] = (rl_enriched["home_margin"] >= 2).astype(int)
rl_enriched["rl_dec_odds"] = rl_enriched["home_rl_odds"].apply(american_to_decimal_local)
rl_enriched["rl_pnl"] = np.where(
    rl_enriched["home_rl_cover"],
    100 * (rl_enriched["rl_dec_odds"] - 1),
    -100,
)

print(f"\nRPI-filtered analysis ({len(rl_enriched)} games with features):")

# Strong RPI advantage = home should dominate
for rpi_min in [0.00, 0.01, 0.02, 0.03, 0.04, 0.05]:
    subset = rl_enriched[rl_enriched["rpi_diff"] >= rpi_min]
    if len(subset) < 50:
        continue
    n = len(subset)
    cover = subset["home_rl_cover"].mean()
    pnl = subset["rl_pnl"].sum()
    roi = pnl / (n * 100)
    ml_wr = subset["home_win"].mean()
    print(f"  RPI diff >= {rpi_min:+.2f}: {n} games, ML WR {ml_wr:.1%}, "
          f"RL cover {cover:.1%}, RL ROI {roi:+.1%}")

# Also check: underdog +1.5 when RPI says home is overvalued
print("\nUnderdog +1.5 when RPI disagrees with line:")
for rpi_max in [0.00, -0.01, -0.02, -0.03]:
    subset = rl_enriched[rl_enriched["rpi_diff"] <= rpi_max]
    if len(subset) < 50:
        continue
    n = len(subset)
    # Away covers +1.5 when margin <= 1
    away_cover = (subset["home_margin"] <= 1).mean()
    away_rl_est_odds = subset["home_rl_odds"].apply(estimate_opposite_rl)
    away_pnl = np.where(
        subset["home_margin"] <= 1,
        100 * (away_rl_est_odds.values - 1),
        -100,
    ).sum()
    roi = away_pnl / (n * 100)
    print(f"  RPI diff <= {rpi_max:+.2f}: {n} games, +1.5 cover {away_cover:.1%}, "
          f"est ROI {roi:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
Key findings:
1. Favorite -1.5 cover rate and ROI by strength bucket
2. Underdog +1.5 cover rate and ROI
3. RPI-filtered Run Line edge
4. Score margin distribution shows how often 1-run games happen
""")
