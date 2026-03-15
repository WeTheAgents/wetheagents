"""First 5 Innings Moneyline flat bet analysis with pitcher features.

Strategy: bet on the F5 winner using full-game ML odds adjusted down by 0.10
to account for the ~10% push (tie after 5 innings) scenario where the bet loses.

F5 ML odds estimation:
  f5_decimal = full_game_decimal - 0.10
This reduces both home and away odds symmetrically.

Push handling: tie after 5 innings = bet LOSES (standard F5 ML rules).

We test both "bet on home favorite" and "bet on away favorite" perspectives,
then unify into a single "bet on the F5 favorite" dataset with proper sign flipping.
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
from src.market_builder import add_f5_markets

F5_ODDS_DISCOUNT = 0.10  # Deduct from full-game decimal odds for push risk

TRAIN_SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]
TEST_SEASONS = [2018, 2019, 2021]


def flat_bet_report(label, df, win_col, odds_col, stake=100):
    """Print flat bet results. Push = loss (already handled in win_col)."""
    if len(df) < 20:
        print(f"  {label:<60} {'<20 games':>8}")
        return None
    n = len(df)
    wr = df[win_col].mean()
    pnl = np.where(df[win_col], stake * (df[odds_col] - 1), -stake).sum()
    roi = pnl / (n * stake)
    avg_odds = df[odds_col].mean()
    print(
        f"  {label:<60} {n:>5}  {wr:>5.1%}  {avg_odds:>5.3f}  "
        f"{roi:>+6.2%}  ${pnl:>+9,.0f}"
    )
    return {"n": n, "wr": wr, "roi": roi, "pnl": pnl, "avg_odds": avg_odds}


# ── Load data + features ─────────────────────────────────────────────────
print("Loading data and computing features (team + pitcher)...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
enriched = build_all_features(games, include_pitcher=True)

# Add F5 markets
enriched = add_f5_markets(enriched)

print(f"Games with features: {len(enriched)}")

# ── Base filters ─────────────────────────────────────────────────────────
base_mask = (
    ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & (enriched["games_played_min"] >= 20)
)
df = enriched[base_mask].copy()

# ── Build F5 ML odds and outcomes ────────────────────────────────────────
# F5 adjusted odds: full game decimal - discount
df["home_f5_odds"] = df["home_decimal_odds"] - F5_ODDS_DISCOUNT
df["away_f5_odds"] = df["away_decimal_odds"] - F5_ODDS_DISCOUNT

# Ensure odds stay above 1.0 (minimum payout)
df["home_f5_odds"] = df["home_f5_odds"].clip(lower=1.01)
df["away_f5_odds"] = df["away_f5_odds"].clip(lower=1.01)

# F5 outcomes (push = loss for our bet)
df["home_f5_win"] = (df["f5_winner"] == "home").astype(int)
df["away_f5_win"] = (df["f5_winner"] == "away").astype(int)
df["f5_push"] = (df["f5_winner"] == "push").astype(int)

print(f"\nBettable games: {len(df)}")
print(f"F5 home win: {df['home_f5_win'].mean():.1%}")
print(f"F5 away win: {df['away_f5_win'].mean():.1%}")
print(f"F5 push:     {df['f5_push'].mean():.1%}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 1: RAW BASELINES")
print(f"  {'Strategy':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 95)

# Always bet home F5
flat_bet_report("Always bet HOME F5 ML", df, "home_f5_win", "home_f5_odds")
# Always bet away F5
flat_bet_report("Always bet AWAY F5 ML", df, "away_f5_win", "away_f5_odds")
# Bet on F5 favorite (home is fav)
home_fav = df[df["home_is_favorite"]].copy()
flat_bet_report("Bet HOME when home is favorite (F5 ML)", home_fav, "home_f5_win", "home_f5_odds")
# Bet on F5 favorite (away is fav)
away_fav = df[~df["home_is_favorite"]].copy()
flat_bet_report("Bet AWAY when away is favorite (F5 ML)", away_fav, "away_f5_win", "away_f5_odds")

# ══════════════════════════════════════════════════════════════════════════
# UNIFIED: bet on the favorite side in F5
# Normalize features so positive = favorite advantage
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 2: FAVORITE F5 ML with filters")
print("  Bet on the full-game favorite to also win F5. Push = loss.")
print(f"  {'Filter':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 95)

# Home favorite side
fav_h = df[df["home_is_favorite"]].copy()
fav_h["fav_f5_odds"] = fav_h["home_f5_odds"]
fav_h["fav_f5_win"] = fav_h["home_f5_win"]
fav_h["fav_rpi_diff"] = fav_h["rpi_diff"]        # home - away, positive = fav stronger
fav_h["fav_wp_diff"] = fav_h["wp_diff"]
fav_h["fav_sp_wr_diff"] = fav_h["sp_wr_long_diff"]
fav_h["fav_sp_ra_diff"] = fav_h["sp_ra_long_diff"]
fav_h["fav_implied_prob"] = fav_h["home_implied_prob"]
fav_h["fav_side"] = "home"

# Away favorite side (flip signs so positive = fav advantage)
fav_a = df[~df["home_is_favorite"]].copy()
fav_a["fav_f5_odds"] = fav_a["away_f5_odds"]
fav_a["fav_f5_win"] = fav_a["away_f5_win"]
fav_a["fav_rpi_diff"] = -fav_a["rpi_diff"]       # flip: away is fav
fav_a["fav_wp_diff"] = -fav_a["wp_diff"]
fav_a["fav_sp_wr_diff"] = -fav_a["sp_wr_long_diff"]
fav_a["fav_sp_ra_diff"] = -fav_a["sp_ra_long_diff"]
fav_a["fav_implied_prob"] = fav_a["away_implied_prob"]
fav_a["fav_side"] = "away"

common_cols = [
    "season", "date", "home_team", "away_team",
    "fav_f5_odds", "fav_f5_win", "fav_rpi_diff", "fav_wp_diff",
    "fav_sp_wr_diff", "fav_sp_ra_diff", "fav_implied_prob", "fav_side",
]
all_fav = pd.concat([fav_h[common_cols], fav_a[common_cols]], ignore_index=True)

print(f"\n  Total F5 favorite bets: {len(all_fav)} ({len(fav_h)} home fav + {len(fav_a)} away fav)")

# Baseline
flat_bet_report("Baseline (all favorites F5 ML)", all_fav, "fav_f5_win", "fav_f5_odds")

# By implied probability buckets (favorite strength)
print()
for lo, hi in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.0)]:
    sub = all_fav[(all_fav["fav_implied_prob"] >= lo) & (all_fav["fav_implied_prob"] < hi)]
    flat_bet_report(f"Fav implied prob [{lo:.2f}, {hi:.2f})", sub, "fav_f5_win", "fav_f5_odds")

# RPI filters
print()
for rpi_t in [0.0, 0.02, 0.03, 0.04, 0.05, 0.06]:
    sub = all_fav[all_fav["fav_rpi_diff"] >= rpi_t]
    flat_bet_report(f"RPI fav advantage >= {rpi_t:.2f}", sub, "fav_f5_win", "fav_f5_odds")

# SP WR filters
print()
for wr_t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]:
    sub = all_fav[all_fav["fav_sp_wr_diff"] >= wr_t]
    flat_bet_report(f"SP WR fav advantage >= {wr_t:.2f}", sub, "fav_f5_win", "fav_f5_odds")

# SP RA filters (negative = fav pitcher gives up fewer runs)
print()
for ra_t in [0.0, -0.5, -1.0, -1.5, -2.0]:
    sub = all_fav[all_fav["fav_sp_ra_diff"] <= ra_t]
    flat_bet_report(f"SP RA fav advantage <= {ra_t:.1f}", sub, "fav_f5_win", "fav_f5_odds")

# Combos
print()
combos = [
    ("RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.02) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.03 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.03 + SP_WR>=0.15",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_wr_diff"] >= 0.15)),
    ("RPI>=0.04 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.04) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.05) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.03 + WP>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_wp_diff"] >= 0.05) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.03 + SP_RA<=0 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_ra_diff"] <= 0) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.03 + SP_RA<=-0.5 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_ra_diff"] <= -0.5) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("RPI>=0.02 + SP_WR>=0.15",
        lambda d: (d["fav_rpi_diff"] >= 0.02) & (d["fav_sp_wr_diff"] >= 0.15)),
    ("RPI>=0.02 + SP_WR>=0.20",
        lambda d: (d["fav_rpi_diff"] >= 0.02) & (d["fav_sp_wr_diff"] >= 0.20)),
]
for label, mask_fn in combos:
    sub = all_fav[mask_fn(all_fav)]
    flat_bet_report(label, sub, "fav_f5_win", "fav_f5_odds")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 3: UNDERDOG F5 ML with filters")
print("  Bet on the full-game underdog to win F5. Push = loss.")
print(f"  {'Filter':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
print(f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")
print("=" * 95)

# Build unified underdog dataset (positive diffs = underdog relatively strong)
# Home is underdog when home is NOT favorite
dog_h = df[~df["home_is_favorite"]].copy()
dog_h["dog_f5_odds"] = dog_h["home_f5_odds"]
dog_h["dog_f5_win"] = dog_h["home_f5_win"]
dog_h["dog_rpi_diff"] = dog_h["rpi_diff"]           # home - away; home is dog
dog_h["dog_wp_diff"] = dog_h["wp_diff"]
dog_h["dog_sp_wr_diff"] = dog_h["sp_wr_long_diff"]
dog_h["dog_sp_ra_diff"] = dog_h["sp_ra_long_diff"]
dog_h["dog_implied_prob"] = dog_h["home_implied_prob"]
dog_h["dog_side"] = "home"

# Away is underdog when home IS favorite
dog_a = df[df["home_is_favorite"]].copy()
dog_a["dog_f5_odds"] = dog_a["away_f5_odds"]
dog_a["dog_f5_win"] = dog_a["away_f5_win"]
dog_a["dog_rpi_diff"] = -dog_a["rpi_diff"]           # flip: away is dog
dog_a["dog_wp_diff"] = -dog_a["wp_diff"]
dog_a["dog_sp_wr_diff"] = -dog_a["sp_wr_long_diff"]
dog_a["dog_sp_ra_diff"] = -dog_a["sp_ra_long_diff"]
dog_a["dog_implied_prob"] = dog_a["away_implied_prob"]
dog_a["dog_side"] = "away"

dog_cols = [
    "season", "date", "home_team", "away_team",
    "dog_f5_odds", "dog_f5_win", "dog_rpi_diff", "dog_wp_diff",
    "dog_sp_wr_diff", "dog_sp_ra_diff", "dog_implied_prob", "dog_side",
]
all_dog = pd.concat([dog_h[dog_cols], dog_a[dog_cols]], ignore_index=True)

print(f"\n  Total F5 underdog bets: {len(all_dog)} ({len(dog_h)} home dog + {len(dog_a)} away dog)")

# Baseline
flat_bet_report("Baseline (all underdogs F5 ML)", all_dog, "dog_f5_win", "dog_f5_odds")

# By underdog strength (higher implied prob = stronger dog, closer to pick-em)
print()
for lo, hi in [(0.30, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50)]:
    sub = all_dog[(all_dog["dog_implied_prob"] >= lo) & (all_dog["dog_implied_prob"] < hi)]
    flat_bet_report(f"Dog implied prob [{lo:.2f}, {hi:.2f})", sub, "dog_f5_win", "dog_f5_odds")

# RPI where underdog has advantage (line is "wrong")
print()
for rpi_t in [-0.02, -0.01, 0.0, 0.01, 0.02]:
    sub = all_dog[all_dog["dog_rpi_diff"] >= rpi_t]
    flat_bet_report(f"Dog RPI advantage >= {rpi_t:.2f}", sub, "dog_f5_win", "dog_f5_odds")

# Pitcher WR where underdog's pitcher is better
print()
for wr_t in [-0.10, -0.05, 0.0, 0.05, 0.10]:
    sub = all_dog[all_dog["dog_sp_wr_diff"] >= wr_t]
    flat_bet_report(f"Dog SP WR advantage >= {wr_t:.2f}", sub, "dog_f5_win", "dog_f5_odds")

# Combos — strong underdog with pitcher edge
print()
dog_combos = [
    ("Dog imp>=0.40 + RPI>=0",
        lambda d: (d["dog_implied_prob"] >= 0.40) & (d["dog_rpi_diff"] >= 0)),
    ("Dog imp>=0.45 + RPI>=0",
        lambda d: (d["dog_implied_prob"] >= 0.45) & (d["dog_rpi_diff"] >= 0)),
    ("Dog imp>=0.40 + SP_WR>=0.10",
        lambda d: (d["dog_implied_prob"] >= 0.40) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog imp>=0.45 + SP_WR>=0.10",
        lambda d: (d["dog_implied_prob"] >= 0.45) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog RPI>=0 + SP_WR>=0.05",
        lambda d: (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.05)),
    ("Dog RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["dog_rpi_diff"] >= 0.02) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog imp>=0.40 + RPI>=0 + SP_WR>=0.05",
        lambda d: (d["dog_implied_prob"] >= 0.40) & (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.05)),
    ("Dog imp>=0.40 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_implied_prob"] >= 0.40) & (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.10)),
]
for label, mask_fn in dog_combos:
    sub = all_dog[mask_fn(all_dog)]
    flat_bet_report(label, sub, "dog_f5_win", "dog_f5_odds")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 4: TRAIN/TEST SPLIT — best F5 configs")
print(f"  TRAIN: 2010-2017  |  TEST: 2018-2019, 2021")
print("=" * 95)

# Configs to validate
fav_configs = [
    ("Fav F5 baseline",
        lambda d: pd.Series(True, index=d.index)),
    ("Fav F5: RPI>=0.03 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("Fav F5: RPI>=0.04 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.04) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("Fav F5: RPI>=0.03 + SP_RA<=0 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_sp_ra_diff"] <= 0) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("Fav F5: RPI>=0.03 + WP>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi_diff"] >= 0.03) & (d["fav_wp_diff"] >= 0.05) & (d["fav_sp_wr_diff"] >= 0.10)),
    ("Fav F5: RPI>=0.02 + SP_WR>=0.15",
        lambda d: (d["fav_rpi_diff"] >= 0.02) & (d["fav_sp_wr_diff"] >= 0.15)),
    ("Fav F5: RPI>=0.02 + SP_WR>=0.20",
        lambda d: (d["fav_rpi_diff"] >= 0.02) & (d["fav_sp_wr_diff"] >= 0.20)),
]

dog_configs = [
    ("Dog F5 baseline",
        lambda d: pd.Series(True, index=d.index)),
    ("Dog F5: imp>=0.40 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_implied_prob"] >= 0.40) & (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog F5: imp>=0.45 + SP_WR>=0.10",
        lambda d: (d["dog_implied_prob"] >= 0.45) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog F5: RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_rpi_diff"] >= 0) & (d["dog_sp_wr_diff"] >= 0.10)),
    ("Dog F5: RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["dog_rpi_diff"] >= 0.02) & (d["dog_sp_wr_diff"] >= 0.10)),
]

for split_label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
    print(f"\n  --- {split_label} ---")
    print(f"  {'Config':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
    print(f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")

    fav_sub = all_fav[all_fav["season"].isin(seasons)]
    dog_sub = all_dog[all_dog["season"].isin(seasons)]

    for label, mask_fn in fav_configs:
        sub = fav_sub[mask_fn(fav_sub)]
        flat_bet_report(f"{split_label} {label}", sub, "fav_f5_win", "fav_f5_odds")

    print()
    for label, mask_fn in dog_configs:
        sub = dog_sub[mask_fn(dog_sub)]
        flat_bet_report(f"{split_label} {label}", sub, "dog_f5_win", "dog_f5_odds")

# ══════════════════════════════════════════════════════════════════════════
# PART 5: Robustness grid (RPI x SP_WR) for best direction
print("\n" + "=" * 95)
print("PART 5: ROBUSTNESS GRID — Fav F5 ML (RPI x SP_WR)")
print("  Cells show ROI % (N bets)")
print("=" * 95)

rpi_bins = [(0.00, 0.02), (0.02, 0.04), (0.04, 0.06), (0.06, 1.0)]
wr_bins = [(0.00, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.0)]

for split_label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
    print(f"\n  {split_label}:")
    fav_sub = all_fav[all_fav["season"].isin(seasons)]
    header = "  RPI \\ SP_WR   "
    for wlo, whi in wr_bins:
        header += f"  [{wlo:.2f},{whi:.2f})"
    print(header)

    for rlo, rhi in rpi_bins:
        row = f"  [{rlo:.2f},{rhi:.2f})  "
        for wlo, whi in wr_bins:
            cell = fav_sub[
                (fav_sub["fav_rpi_diff"] >= rlo) & (fav_sub["fav_rpi_diff"] < rhi)
                & (fav_sub["fav_sp_wr_diff"] >= wlo) & (fav_sub["fav_sp_wr_diff"] < whi)
            ]
            if len(cell) >= 20:
                pnl = np.where(
                    cell["fav_f5_win"], 100 * (cell["fav_f5_odds"] - 1), -100
                ).sum()
                roi = pnl / (len(cell) * 100)
                row += f"  {roi:>+5.1%}({len(cell):>4})"
            else:
                row += f"  {'---':>10}"
            row += " "
        print(row)

print("\nDone!")
