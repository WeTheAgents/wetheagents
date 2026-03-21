"""Run Line analysis with REAL odds from data.

Key insight from user: +1.5 odds drop 0.2-0.55 vs ML depending on pitchers.
Previous analysis used estimated odds -- this one uses ACTUAL RL odds from data.

Data structure:
- home_run_line = -1.5 -> home is favorite (10,909 games)
- home_run_line = +1.5 -> home is underdog (5,839 games)
- home_run_line = 7.0-12.0 -> this is O/U total (misclassified)
- home_run_line_odds = American odds for the HOME side of the RL
- We DON'T have away side RL odds separately
"""

import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features


def am_to_dec(ml):
    if ml > 0:
        return 1 + ml / 100
    elif ml < 0:
        return 1 + 100 / abs(ml)
    return 1.0


# ── Load Data ────────────────────────────────────────────────────────────
print("Loading data...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
print(f"Games: {len(games)}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 1: ACTUAL +1.5 ODDS (home underdog taking points)")
print("=" * 70)

# When home_run_line = +1.5, we have ACTUAL home +1.5 odds
dog_home = games[
    (games["home_run_line"] == 1.5)
    & ~games["involves_col"]
    & ~games["is_september"]
    & ~games["is_extreme_line"]
].copy()

dog_home["rl_dec"] = dog_home["home_run_line_odds"].apply(am_to_dec)
dog_home["margin"] = dog_home["home_final"] - dog_home["away_final"]
dog_home["covers"] = (dog_home["margin"] >= -1).astype(int)
dog_home["pnl"] = np.where(dog_home["covers"], 100 * (dog_home["rl_dec"] - 1), -100)

n = len(dog_home)
wr = dog_home["covers"].mean()
pnl = dog_home["pnl"].sum()
roi = pnl / (n * 100)
print("\nHome underdog +1.5 (ACTUAL odds):")
print(f"  Games: {n}")
print(f"  Cover rate: {wr:.1%}")
print(f"  Avg odds: {dog_home['rl_dec'].mean():.3f}")
print(f"  Median odds: {dog_home['rl_dec'].median():.3f}")
print(f"  ROI: {roi:+.2%}")
print(f"  P&L: ${pnl:+,.0f}")

print("\nBy season:")
for season in sorted(dog_home["season"].unique()):
    s = dog_home[dog_home["season"] == season]
    n = len(s)
    wr = s["covers"].mean()
    pnl = s["pnl"].sum()
    r = pnl / (n * 100)
    print(f"  {int(season)}: {n:>4} games, cover {wr:.1%}, "
          f"odds {s['rl_dec'].mean():.3f}, ROI {r:+.1%}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 2: HOME FAVORITE -1.5 (actual odds)")
print("=" * 70)

fav_home = games[
    (games["home_run_line"] == -1.5)
    & ~games["involves_col"]
    & ~games["is_september"]
    & ~games["is_extreme_line"]
].copy()

fav_home["rl_dec"] = fav_home["home_run_line_odds"].apply(am_to_dec)
fav_home["margin"] = fav_home["home_final"] - fav_home["away_final"]
fav_home["covers"] = (fav_home["margin"] >= 2).astype(int)
fav_home["pnl"] = np.where(fav_home["covers"], 100 * (fav_home["rl_dec"] - 1), -100)

n = len(fav_home)
wr = fav_home["covers"].mean()
pnl = fav_home["pnl"].sum()
roi = pnl / (n * 100)
print("\nHome favorite -1.5 (ACTUAL odds):")
print(f"  Games: {n}")
print(f"  Cover rate: {wr:.1%}")
print(f"  Avg odds: {fav_home['rl_dec'].mean():.3f}")
print(f"  ROI: {roi:+.2%}")
print(f"  P&L: ${pnl:+,.0f}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 3: ODDS COMPARISON — how much does +1.5 cost vs ML?")
print("=" * 70)

# For home underdogs: we have both ML odds and +1.5 odds
dog_home["ml_dec"] = dog_home["home_decimal_odds"]
dog_home["rl_vs_ml"] = dog_home["rl_dec"] - dog_home["ml_dec"]

print("\nHome underdog: ML odds vs +1.5 odds")
print(f"  Avg ML decimal odds: {dog_home['ml_dec'].mean():.3f}")
print(f"  Avg +1.5 decimal odds: {dog_home['rl_dec'].mean():.3f}")
print(f"  Avg drop (ML - RL): {(dog_home['ml_dec'] - dog_home['rl_dec']).mean():.3f}")
print(f"  Median drop: {(dog_home['ml_dec'] - dog_home['rl_dec']).median():.3f}")

# By ML odds bucket
print("\n  ML odds drop by favorite strength:")
dog_home["ml_bucket"] = pd.cut(dog_home["home_implied_prob"],
                                bins=[0.30, 0.35, 0.40, 0.45, 0.50])
for bucket, grp in dog_home.groupby("ml_bucket", observed=True):
    if len(grp) < 30:
        continue
    drop = (grp["ml_dec"] - grp["rl_dec"]).mean()
    print(f"    imp prob {str(bucket):>14}: ML {grp['ml_dec'].mean():.2f} -> "
          f"+1.5 {grp['rl_dec'].mean():.2f} (drop {drop:.2f})")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 4: Away underdog +1.5 estimation accuracy")
print("=" * 70)

# When home is -1.5 favorite, AWAY is the +1.5 underdog
# We need to estimate away +1.5 odds from home -1.5 odds
# Test different vig assumptions

fav_home["home_rl_imp"] = 1 / fav_home["rl_dec"]
fav_home["away_covers"] = (fav_home["margin"] <= 1).astype(int)

for total_vig in [1.030, 1.035, 1.040, 1.045, 1.050, 1.055, 1.060]:
    fav_home["away_rl_imp_est"] = total_vig - fav_home["home_rl_imp"]
    fav_home["away_rl_dec_est"] = 1 / fav_home["away_rl_imp_est"]
    fav_home["away_pnl_est"] = np.where(
        fav_home["away_covers"],
        100 * (fav_home["away_rl_dec_est"] - 1),
        -100,
    )
    pnl = fav_home["away_pnl_est"].sum()
    roi = pnl / (len(fav_home) * 100)
    avg_odds = fav_home["away_rl_dec_est"].mean()
    print(f"  Vig={total_vig:.3f}: avg away +1.5 odds={avg_odds:.3f}, "
          f"ROI {roi:+.1%}, P&L ${pnl:+,.0f}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 5: RPI FILTERS with actual +1.5 odds (home underdog)")
print("=" * 70)

print("\nBuilding features...")
enriched = build_all_features(games)

# Home underdog +1.5 with features
dog_enriched = enriched[
    (enriched["home_run_line"] == 1.5)
    & ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & (enriched["games_played_min"] >= 20)
].copy()

dog_enriched["rl_dec"] = dog_enriched["home_run_line_odds"].apply(am_to_dec)
dog_enriched["margin"] = dog_enriched["home_final"] - dog_enriched["away_final"]
dog_enriched["covers"] = (dog_enriched["margin"] >= -1).astype(int)
dog_enriched["pnl"] = np.where(
    dog_enriched["covers"], 100 * (dog_enriched["rl_dec"] - 1), -100
)

print("\nHome underdog +1.5 with RPI filters (ACTUAL odds):")
print(f"{'Filter':<35} {'Games':>6} {'Cover':>7} {'Odds':>6} {'ROI':>7} {'P&L':>10}")
print("-" * 75)

# rpi_diff = home - away
# Positive = home is stronger by RPI (underdog by line but not by fundamentals!)
for label, mask_fn in [
    ("All (baseline)", lambda df: df.index == df.index),
    ("RPI: home >= away", lambda df: df["rpi_diff"] >= 0),
    ("RPI: home > away +0.01", lambda df: df["rpi_diff"] >= 0.01),
    ("RPI: home > away +0.02", lambda df: df["rpi_diff"] >= 0.02),
    ("RPI: home > away +0.03", lambda df: df["rpi_diff"] >= 0.03),
    ("WP: home > away", lambda df: df["wp_diff"] >= 0),
    ("WP: home > away +0.05", lambda df: df["wp_diff"] >= 0.05),
    ("Streak: home on W1+", lambda df: df["streak_home"] >= 1),
    ("Streak: home on W2+", lambda df: df["streak_home"] >= 2),
    ("Last10: home > away", lambda df: df["wp_last10_diff"] >= 0),
    # Combinations
    ("RPI>=0.01 + WP>=0", lambda df: (df["rpi_diff"] >= 0.01) & (df["wp_diff"] >= 0)),
    ("RPI>=0.02 + Streak W1+", lambda df: (df["rpi_diff"] >= 0.02) & (df["streak_home"] >= 1)),
    ("RPI>=0 + L10>0 + WP>0", lambda df: (df["rpi_diff"] >= 0) & (df["wp_last10_diff"] >= 0) & (df["wp_diff"] >= 0)),
]:
    subset = dog_enriched[mask_fn(dog_enriched)]
    if len(subset) < 30:
        continue
    n = len(subset)
    wr = subset["covers"].mean()
    pnl_sum = subset["pnl"].sum()
    roi = pnl_sum / (n * 100)
    avg_odds = subset["rl_dec"].mean()
    print(f"  {label:<33} {n:>6} {wr:>6.1%} {avg_odds:>6.3f} {roi:>+6.1%} ${pnl_sum:>+9,.0f}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("PART 6: HOME FAVORITE -1.5 with RPI (actual odds)")
print("=" * 70)

fav_enriched = enriched[
    (enriched["home_run_line"] == -1.5)
    & ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & (enriched["games_played_min"] >= 20)
].copy()

fav_enriched["rl_dec"] = fav_enriched["home_run_line_odds"].apply(am_to_dec)
fav_enriched["margin"] = fav_enriched["home_final"] - fav_enriched["away_final"]
fav_enriched["covers"] = (fav_enriched["margin"] >= 2).astype(int)
fav_enriched["pnl"] = np.where(
    fav_enriched["covers"], 100 * (fav_enriched["rl_dec"] - 1), -100
)

print("\nHome favorite -1.5 with RPI filters (ACTUAL odds):")
print(f"{'Filter':<35} {'Games':>6} {'Cover':>7} {'Odds':>6} {'ROI':>7} {'P&L':>10}")
print("-" * 75)

for label, mask_fn in [
    ("All (baseline)", lambda df: df.index == df.index),
    ("RPI: home > away +0.02", lambda df: df["rpi_diff"] >= 0.02),
    ("RPI: home > away +0.03", lambda df: df["rpi_diff"] >= 0.03),
    ("RPI: home > away +0.04", lambda df: df["rpi_diff"] >= 0.04),
    ("RPI: home > away +0.05", lambda df: df["rpi_diff"] >= 0.05),
    ("RPI>=0.03 + WP>=0.10", lambda df: (df["rpi_diff"] >= 0.03) & (df["wp_diff"] >= 0.10)),
    ("RPI>=0.03 + Streak W2+", lambda df: (df["rpi_diff"] >= 0.03) & (df["streak_home"] >= 2)),
    ("RPI>=0.04 + L10>0", lambda df: (df["rpi_diff"] >= 0.04) & (df["wp_last10_diff"] >= 0)),
]:
    subset = fav_enriched[mask_fn(fav_enriched)]
    if len(subset) < 30:
        continue
    n = len(subset)
    wr = subset["covers"].mean()
    pnl_sum = subset["pnl"].sum()
    roi = pnl_sum / (n * 100)
    avg_odds = subset["rl_dec"].mean()
    print(f"  {label:<33} {n:>6} {wr:>6.1%} {avg_odds:>6.3f} {roi:>+6.1%} ${pnl_sum:>+9,.0f}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
NOTE ON ODDS ACCURACY:
- Home underdog +1.5 ODDS ARE REAL (from data)
- Away underdog +1.5 odds are ESTIMATED (mirror of home -1.5)
- Typical drop from ML to +1.5: 0.5-0.6 decimal points
- This means estimated ROI for away +1.5 has ~0.1-0.2 decimal point uncertainty
""")
