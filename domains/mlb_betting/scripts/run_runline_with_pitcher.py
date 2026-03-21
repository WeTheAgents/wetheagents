"""Run Line analysis with pitcher features.

Strategy logic:
- FAVORITE -1.5: bet that favorite wins by 2+. Higher odds than ML, needs strong edge.
  When we select favorites with good RPI + good pitcher, they should cover -1.5 more.
- UNDERDOG +1.5: bet that underdog loses by 1 or wins. Lower odds than ML.
  Strong underdogs (by RPI/pitcher) should cover +1.5 often but odds are thin.

Data notes:
- home_run_line = -1.5: home is favorite. We have REAL home -1.5 odds.
- home_run_line = +1.5: home is underdog. We have REAL home +1.5 odds.
- Away side RL odds: must be estimated from vig (total_vig - home_rl_implied).
- We use vig=1.045 (standard MLB RL vig).

Key insight from user: lower underdog odds = stronger underdog = more likely to cover.
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

TOTAL_VIG = 1.045  # Standard RL vig


def am_to_dec(ml):
    """American to decimal odds."""
    if ml > 0:
        return 1 + ml / 100
    elif ml < 0:
        return 1 + 100 / abs(ml)
    return 1.0


def flat_bet_report(label, df, cover_col, odds_col, stake=100):
    """Print flat bet results."""
    if len(df) < 20:
        print(f"  {label:<58} {'<20 games':>8}")
        return
    n = len(df)
    wr = df[cover_col].mean()
    pnl = np.where(df[cover_col], stake * (df[odds_col] - 1), -stake).sum()
    roi = pnl / (n * stake)
    avg_odds = df[odds_col].mean()
    print(f"  {label:<58} {n:>5}  {wr:>5.1%}  {avg_odds:>5.3f}  {roi:>+6.2%}  ${pnl:>+9,.0f}")


# ── Load data + features ─────────────────────────────────────────────────
print("Loading data and computing features (team + pitcher)...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
enriched = build_all_features(games, include_pitcher=True)
print(f"Games with features: {len(enriched)}")

# ── Prepare RL data ──────────────────────────────────────────────────────
# Base filters
base_mask = (
    ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & (enriched["games_played_min"] >= 20)
)

# FAVORITE -1.5 (home is favorite)
fav_home = enriched[base_mask & (enriched["home_run_line"] == -1.5)].copy()
fav_home["rl_dec"] = fav_home["home_run_line_odds"].apply(am_to_dec)
fav_home["margin"] = fav_home["home_final"] - fav_home["away_final"]
fav_home["covers_minus"] = (fav_home["margin"] >= 2).astype(int)  # home -1.5 covers

# Estimate AWAY +1.5 odds (away is underdog when home is -1.5 favorite)
fav_home["home_rl_imp"] = 1 / fav_home["rl_dec"]
fav_home["away_rl_imp_est"] = TOTAL_VIG - fav_home["home_rl_imp"]
fav_home["away_rl_dec_est"] = 1 / fav_home["away_rl_imp_est"]
fav_home["covers_plus"] = (fav_home["margin"] <= 1).astype(int)  # away +1.5 covers

# UNDERDOG +1.5 (home is underdog)
dog_home = enriched[base_mask & (enriched["home_run_line"] == 1.5)].copy()
dog_home["rl_dec"] = dog_home["home_run_line_odds"].apply(am_to_dec)
dog_home["margin"] = dog_home["home_final"] - dog_home["away_final"]
dog_home["covers_plus"] = (dog_home["margin"] >= -1).astype(int)  # home +1.5 covers

# Estimate AWAY -1.5 odds (away is favorite when home is +1.5 underdog)
dog_home["home_rl_imp"] = 1 / dog_home["rl_dec"]
dog_home["away_rl_imp_est"] = TOTAL_VIG - dog_home["home_rl_imp"]
dog_home["away_rl_dec_est"] = 1 / dog_home["away_rl_imp_est"]
dog_home["covers_minus"] = (dog_home["margin"] <= -2).astype(int)  # away -1.5 covers

print(f"\nHome favorite -1.5 games: {len(fav_home)}")
print(f"Home underdog +1.5 games: {len(dog_home)}")
print(f"Total RL games: {len(fav_home) + len(dog_home)}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("PART 1: BASELINES (no feature filters)")
print(f"  {'Strategy':<58} {'N':>5}  {'Cover':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*58} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 90)

# 1a. Home favorite -1.5 (REAL odds)
flat_bet_report("Home fav -1.5 (real odds)", fav_home, "covers_minus", "rl_dec")

# 1b. Away underdog +1.5 (estimated odds, when home is -1.5 fav)
flat_bet_report("Away dog +1.5 (est odds, home=fav)", fav_home, "covers_plus", "away_rl_dec_est")

# 1c. Home underdog +1.5 (REAL odds)
flat_bet_report("Home dog +1.5 (real odds)", dog_home, "covers_plus", "rl_dec")

# 1d. Away favorite -1.5 (estimated odds, when home is +1.5 dog)
flat_bet_report("Away fav -1.5 (est odds, home=dog)", dog_home, "covers_minus", "away_rl_dec_est")

# ══════════════════════════════════════════════════════════════════════════
# COMBINED: All favorites -1.5 (home fav + away fav)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("PART 2: FAVORITE -1.5 with filters")
print("  Bet on favorite to win by 2+. Higher odds = bigger profit if right.")
print(f"  {'Filter':<58} {'N':>5}  {'Cover':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*58} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 90)

# Build unified favorite -1.5 dataset
# Home favorite: use real odds, rpi_diff = home - away (positive = fav stronger)
fav_from_home = fav_home[["season", "date", "home_team", "away_team",
    "rl_dec", "margin", "covers_minus",
    "rpi_diff", "wp_diff", "sp_wr_long_diff", "sp_ra_long_diff",
    "streak_home", "streak_away",
    "home_sp_wr_long", "away_sp_wr_long",
    "home_sp_ra_long", "away_sp_ra_long",
    "home_implied_prob"]].copy()
fav_from_home.rename(columns={
    "covers_minus": "covers",
    "home_implied_prob": "fav_implied_prob",
}, inplace=True)
fav_from_home["fav_side"] = "home"
# rpi_diff already = fav - dog (home is fav)
# sp_wr_long_diff already = home - away (positive = home pitcher better)

# Away favorite: use estimated odds, flip signs
# When home is +1.5 (underdog), away is the favorite
fav_from_away = dog_home[["season", "date", "home_team", "away_team",
    "away_rl_dec_est", "margin", "covers_minus",
    "rpi_diff", "wp_diff", "sp_wr_long_diff", "sp_ra_long_diff",
    "streak_home", "streak_away",
    "home_sp_wr_long", "away_sp_wr_long",
    "home_sp_ra_long", "away_sp_ra_long",
    "away_implied_prob"]].copy()
fav_from_away.rename(columns={
    "away_rl_dec_est": "rl_dec",
    "covers_minus": "covers",
    "away_implied_prob": "fav_implied_prob",
}, inplace=True)
fav_from_away["fav_side"] = "away"
# FLIP: rpi_diff = home - away, but favorite is AWAY, so fav advantage = -(home-away)
fav_from_away["rpi_diff"] = -fav_from_away["rpi_diff"]
fav_from_away["wp_diff"] = -fav_from_away["wp_diff"]
fav_from_away["sp_wr_long_diff"] = -fav_from_away["sp_wr_long_diff"]
fav_from_away["sp_ra_long_diff"] = -fav_from_away["sp_ra_long_diff"]

# Combine
all_fav = pd.concat([fav_from_home, fav_from_away], ignore_index=True)
print(f"\n  Total favorite -1.5 bets: {len(all_fav)} ({len(fav_from_home)} home + {len(fav_from_away)} away)")

# Baseline
flat_bet_report("Baseline (all favorites -1.5)", all_fav, "covers", "rl_dec")

# RPI filters (fav advantage)
for rpi_t in [0.0, 0.02, 0.03, 0.04, 0.05]:
    sub = all_fav[all_fav["rpi_diff"] >= rpi_t]
    flat_bet_report(f"RPI fav advantage >= {rpi_t:.2f}", sub, "covers", "rl_dec")

# Pitcher WR filter
for wr_t in [0.0, 0.05, 0.10, 0.15, 0.20]:
    sub = all_fav[all_fav["sp_wr_long_diff"] >= wr_t]
    flat_bet_report(f"SP WR fav advantage >= {wr_t:.2f}", sub, "covers", "rl_dec")

# Pitcher RA filter (lower = better for fav, so negative diff = fav better)
for ra_t in [0.0, -0.5, -1.0, -1.5]:
    sub = all_fav[all_fav["sp_ra_long_diff"] <= ra_t]
    flat_bet_report(f"SP RA fav advantage <= {ra_t:.1f}", sub, "covers", "rl_dec")

# Combos
print()
combos = [
    ("RPI>=0.02 + SP_WR>=0.10", {"rpi": 0.02, "wr": 0.10}),
    ("RPI>=0.03 + SP_WR>=0.10", {"rpi": 0.03, "wr": 0.10}),
    ("RPI>=0.03 + SP_WR>=0.15", {"rpi": 0.03, "wr": 0.15}),
    ("RPI>=0.04 + SP_WR>=0.10", {"rpi": 0.04, "wr": 0.10}),
    ("RPI>=0.05 + SP_WR>=0.10", {"rpi": 0.05, "wr": 0.10}),
    ("RPI>=0.03 + SP_RA<=0 + SP_WR>=0.10", {"rpi": 0.03, "wr": 0.10, "ra": 0.0}),
    ("RPI>=0.03 + WP>=0.05 + SP_WR>=0.10", {"rpi": 0.03, "wp": 0.05, "wr": 0.10}),
]
for label, params in combos:
    mask = all_fav["rpi_diff"] >= params.get("rpi", -99)
    if "wr" in params:
        mask = mask & (all_fav["sp_wr_long_diff"] >= params["wr"])
    if "ra" in params:
        mask = mask & (all_fav["sp_ra_long_diff"] <= params["ra"])
    if "wp" in params:
        mask = mask & (all_fav["wp_diff"] >= params["wp"])
    sub = all_fav[mask]
    flat_bet_report(label, sub, "covers", "rl_dec")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("PART 3: UNDERDOG +1.5 with filters")
print("  Bet on underdog to lose by 1 or win. Low odds, needs high cover rate.")
print(f"  {'Filter':<58} {'N':>5}  {'Cover':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*58} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 90)

# Build unified underdog +1.5 dataset
# Home underdog: use real odds
dog_from_home = dog_home[["season", "date", "home_team", "away_team",
    "rl_dec", "margin", "covers_plus",
    "rpi_diff", "wp_diff", "sp_wr_long_diff", "sp_ra_long_diff",
    "home_implied_prob"]].copy()
dog_from_home.rename(columns={
    "covers_plus": "covers",
    "home_implied_prob": "dog_implied_prob",
}, inplace=True)
dog_from_home["dog_side"] = "home"
# For underdog perspective: flip so positive = underdog is relatively strong
# rpi_diff = home - away. Home is underdog. Positive rpi_diff = strong underdog.
# sp_wr_long_diff = home - away. Positive = home pitcher better (underdog pitcher better)
# No flip needed — home IS the underdog here

# Away underdog: use estimated odds
dog_from_away = fav_home[["season", "date", "home_team", "away_team",
    "away_rl_dec_est", "margin", "covers_plus",
    "rpi_diff", "wp_diff", "sp_wr_long_diff", "sp_ra_long_diff",
    "away_implied_prob"]].copy()
dog_from_away.rename(columns={
    "away_rl_dec_est": "rl_dec",
    "covers_plus": "covers",
    "away_implied_prob": "dog_implied_prob",
}, inplace=True)
dog_from_away["dog_side"] = "away"
# Away is underdog when home is -1.5 favorite
# rpi_diff = home - away. Away is underdog. For underdog strength: flip sign
dog_from_away["rpi_diff"] = -dog_from_away["rpi_diff"]
dog_from_away["wp_diff"] = -dog_from_away["wp_diff"]
dog_from_away["sp_wr_long_diff"] = -dog_from_away["sp_wr_long_diff"]
dog_from_away["sp_ra_long_diff"] = -dog_from_away["sp_ra_long_diff"]

# Combine
all_dog = pd.concat([dog_from_home, dog_from_away], ignore_index=True)
print(f"\n  Total underdog +1.5 bets: {len(all_dog)} ({len(dog_from_home)} home + {len(dog_from_away)} away)")

# Key insight: for +1.5 underdog, we want the underdog to be RELATIVELY STRONG
# Lower implied prob = weaker underdog = less likely to cover
# Higher implied prob (closer to 50%) = stronger underdog = more likely to cover

# Baseline
flat_bet_report("Baseline (all underdogs +1.5)", all_dog, "covers", "rl_dec")

# Filter by underdog strength (implied prob — closer to 50% = stronger dog)
for lo, hi in [(0.35, 0.40), (0.40, 0.45), (0.45, 0.50), (0.35, 0.50)]:
    sub = all_dog[(all_dog["dog_implied_prob"] >= lo) & (all_dog["dog_implied_prob"] < hi)]
    flat_bet_report(f"Dog implied prob [{lo:.2f}, {hi:.2f})", sub, "covers", "rl_dec")

# RPI filters (underdog has RPI advantage — line is "wrong")
for rpi_t in [0.0, 0.01, 0.02, 0.03]:
    sub = all_dog[all_dog["rpi_diff"] >= rpi_t]
    flat_bet_report(f"Underdog RPI advantage >= {rpi_t:.2f}", sub, "covers", "rl_dec")

# Pitcher WR filter (underdog's pitcher is better)
for wr_t in [0.0, 0.05, 0.10, 0.15]:
    sub = all_dog[all_dog["sp_wr_long_diff"] >= wr_t]
    flat_bet_report(f"Underdog SP WR advantage >= {wr_t:.2f}", sub, "covers", "rl_dec")

# Combos
print()
combos_dog = [
    ("Dog imp>=0.45 + RPI>=0", {"prob_lo": 0.45, "rpi": 0.0}),
    ("Dog imp>=0.45 + SP_WR>=0.10", {"prob_lo": 0.45, "wr": 0.10}),
    ("Dog RPI>=0.01 + SP_WR>=0.05", {"rpi": 0.01, "wr": 0.05}),
    ("Dog RPI>=0.02 + SP_WR>=0.10", {"rpi": 0.02, "wr": 0.10}),
    ("Dog imp>=0.40 + RPI>=0 + SP_WR>=0.10", {"prob_lo": 0.40, "rpi": 0.0, "wr": 0.10}),
]
for label, params in combos_dog:
    mask = pd.Series(True, index=all_dog.index)
    if "prob_lo" in params:
        mask = mask & (all_dog["dog_implied_prob"] >= params["prob_lo"])
    if "rpi" in params:
        mask = mask & (all_dog["rpi_diff"] >= params["rpi"])
    if "wr" in params:
        mask = mask & (all_dog["sp_wr_long_diff"] >= params["wr"])
    sub = all_dog[mask]
    flat_bet_report(label, sub, "covers", "rl_dec")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 90)
print("PART 4: TRAIN/TEST SPLIT for best RL configs")
print("  TRAIN: 2010-2017  |  TEST: 2018-2019, 2021")
print("=" * 90)

TRAIN_SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]
TEST_SEASONS = [2018, 2019, 2021]

for dataset_label, df_label, seasons in [
    ("TRAIN", "train", TRAIN_SEASONS),
    ("TEST", "test", TEST_SEASONS),
]:
    print(f"\n  --- {dataset_label} ---")
    fav_sub = all_fav[all_fav["season"].isin(seasons)]
    dog_sub = all_dog[all_dog["season"].isin(seasons)]

    # Favorite -1.5 configs
    for label, mask_fn in [
        ("Fav -1.5 baseline",
            lambda df: pd.Series(True, index=df.index)),
        ("Fav -1.5: RPI>=0.03 + SP_WR>=0.10",
            lambda df: (df["rpi_diff"] >= 0.03) & (df["sp_wr_long_diff"] >= 0.10)),
        ("Fav -1.5: RPI>=0.04 + SP_WR>=0.10",
            lambda df: (df["rpi_diff"] >= 0.04) & (df["sp_wr_long_diff"] >= 0.10)),
        ("Fav -1.5: RPI>=0.05 + SP_WR>=0.10",
            lambda df: (df["rpi_diff"] >= 0.05) & (df["sp_wr_long_diff"] >= 0.10)),
    ]:
        sub = fav_sub[mask_fn(fav_sub)]
        flat_bet_report(f"{dataset_label} {label}", sub, "covers", "rl_dec")

    # Underdog +1.5 configs
    for label, mask_fn in [
        ("Dog +1.5 baseline",
            lambda df: pd.Series(True, index=df.index)),
        ("Dog +1.5: imp>=0.45 + SP_WR>=0.10",
            lambda df: (df["dog_implied_prob"] >= 0.45) & (df["sp_wr_long_diff"] >= 0.10)),
        ("Dog +1.5: RPI>=0.01 + SP_WR>=0.05",
            lambda df: (df["rpi_diff"] >= 0.01) & (df["sp_wr_long_diff"] >= 0.05)),
        ("Dog +1.5: RPI>=0.02 + SP_WR>=0.10",
            lambda df: (df["rpi_diff"] >= 0.02) & (df["sp_wr_long_diff"] >= 0.10)),
    ]:
        sub = dog_sub[mask_fn(dog_sub)]
        flat_bet_report(f"{dataset_label} {label}", sub, "covers", "rl_dec")

print("\nDone!")
