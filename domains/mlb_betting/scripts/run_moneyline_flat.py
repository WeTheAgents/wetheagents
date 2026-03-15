"""Full-game Moneyline flat bet analysis with pitcher features.

Strategy: flat bet on the game winner using closing ML odds.
We have REAL closing odds for both sides — no estimation needed.

Test both favorite and underdog sides with team + pitcher filters.
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

TRAIN_SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]
TEST_SEASONS = [2018, 2019, 2021]


def flat_bet_report(label, df, win_col, odds_col, stake=100):
    """Print flat bet results."""
    if len(df) < 20:
        print(f"  {label:<60} {'<20 bets':>8}")
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
print(f"Games with features: {len(enriched)}")

# ── Base filters ─────────────────────────────────────────────────────────
base_mask = (
    ~enriched["involves_col"]
    & ~enriched["is_september"]
    & ~enriched["is_extreme_line"]
    & (enriched["games_played_min"] >= 20)
)
df = enriched[base_mask].copy()
print(f"Bettable games: {len(df)}")
print(f"Home win rate: {df['home_win'].mean():.1%}")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 1: RAW BASELINES")
hdr = f"  {'Strategy':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}"
sep = f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}"
print(hdr)
print(sep)
print("=" * 95)

flat_bet_report("Always bet HOME", df, "home_win", "home_decimal_odds")
flat_bet_report("Always bet AWAY", df, "away_win" if "away_win" in df.columns else "home_win",
                "away_decimal_odds")

# Need away_win column
if "away_win" not in df.columns:
    df["away_win"] = 1 - df["home_win"]

flat_bet_report("Always bet AWAY", df, "away_win", "away_decimal_odds")

# Bet on favorite
home_fav = df[df["home_is_favorite"]]
away_fav = df[~df["home_is_favorite"]]
flat_bet_report("Bet HOME when home is fav", home_fav, "home_win", "home_decimal_odds")
flat_bet_report("Bet AWAY when away is fav", away_fav, "away_win", "away_decimal_odds")

# ══════════════════════════════════════════════════════════════════════════
# UNIFIED FAVORITE dataset
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 2: BET ON FAVORITE (full-game ML) with filters")
print(hdr)
print(sep)
print("=" * 95)

# Home favorite side
fav_h = df[df["home_is_favorite"]].copy()
fav_h["fav_odds"] = fav_h["home_decimal_odds"]
fav_h["fav_win"] = fav_h["home_win"]
fav_h["fav_rpi"] = fav_h["rpi_diff"]
fav_h["fav_wp"] = fav_h["wp_diff"]
fav_h["fav_sp_wr"] = fav_h["sp_wr_long_diff"]
fav_h["fav_sp_ra"] = fav_h["sp_ra_long_diff"]
fav_h["fav_imp"] = fav_h["home_implied_prob"]
fav_h["fav_side"] = "home"

# Away favorite side (flip signs)
fav_a = df[~df["home_is_favorite"]].copy()
fav_a["fav_odds"] = fav_a["away_decimal_odds"]
fav_a["fav_win"] = fav_a["away_win"]
fav_a["fav_rpi"] = -fav_a["rpi_diff"]
fav_a["fav_wp"] = -fav_a["wp_diff"]
fav_a["fav_sp_wr"] = -fav_a["sp_wr_long_diff"]
fav_a["fav_sp_ra"] = -fav_a["sp_ra_long_diff"]
fav_a["fav_imp"] = fav_a["away_implied_prob"]
fav_a["fav_side"] = "away"

cols = [
    "season", "date", "home_team", "away_team",
    "fav_odds", "fav_win", "fav_rpi", "fav_wp",
    "fav_sp_wr", "fav_sp_ra", "fav_imp", "fav_side",
]
all_fav = pd.concat([fav_h[cols], fav_a[cols]], ignore_index=True)
print(f"\n  Total favorite bets: {len(all_fav)} ({len(fav_h)} home + {len(fav_a)} away)")

flat_bet_report("Baseline (all favorites ML)", all_fav, "fav_win", "fav_odds")

# By implied prob buckets
print()
for lo, hi in [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.0)]:
    sub = all_fav[(all_fav["fav_imp"] >= lo) & (all_fav["fav_imp"] < hi)]
    flat_bet_report(f"Fav implied [{lo:.2f}, {hi:.2f})", sub, "fav_win", "fav_odds")

# RPI
print()
for t in [0.0, 0.02, 0.03, 0.04, 0.05, 0.06]:
    sub = all_fav[all_fav["fav_rpi"] >= t]
    flat_bet_report(f"RPI fav >= {t:.2f}", sub, "fav_win", "fav_odds")

# SP WR
print()
for t in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
    sub = all_fav[all_fav["fav_sp_wr"] >= t]
    flat_bet_report(f"SP WR fav >= {t:.2f}", sub, "fav_win", "fav_odds")

# SP RA
print()
for t in [0.0, -0.5, -1.0, -1.5, -2.0]:
    sub = all_fav[all_fav["fav_sp_ra"] <= t]
    flat_bet_report(f"SP RA fav <= {t:.1f}", sub, "fav_win", "fav_odds")

# Combos
print()
combos_fav = [
    ("RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.02) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.03 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.03 + SP_WR>=0.15",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_wr"] >= 0.15)),
    ("RPI>=0.04 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.04) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.05) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.03 + WP>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_wp"] >= 0.05) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.03 + SP_RA<=0 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_ra"] <= 0) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.03 + SP_RA<=-0.5 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_ra"] <= -0.5) & (d["fav_sp_wr"] >= 0.10)),
    ("RPI>=0.02 + SP_WR>=0.20",
        lambda d: (d["fav_rpi"] >= 0.02) & (d["fav_sp_wr"] >= 0.20)),
    ("RPI>=0.03 + SP_WR>=0.20",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_wr"] >= 0.20)),
]
for label, fn in combos_fav:
    sub = all_fav[fn(all_fav)]
    flat_bet_report(label, sub, "fav_win", "fav_odds")

# ══════════════════════════════════════════════════════════════════════════
# UNIFIED UNDERDOG dataset
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 3: BET ON UNDERDOG (full-game ML) with filters")
print(hdr)
print(sep)
print("=" * 95)

# Home underdog
dog_h = df[~df["home_is_favorite"]].copy()
dog_h["dog_odds"] = dog_h["home_decimal_odds"]
dog_h["dog_win"] = dog_h["home_win"]
dog_h["dog_rpi"] = dog_h["rpi_diff"]       # home - away; home is dog
dog_h["dog_wp"] = dog_h["wp_diff"]
dog_h["dog_sp_wr"] = dog_h["sp_wr_long_diff"]
dog_h["dog_sp_ra"] = dog_h["sp_ra_long_diff"]
dog_h["dog_imp"] = dog_h["home_implied_prob"]
dog_h["dog_side"] = "home"

# Away underdog (flip signs)
dog_a = df[df["home_is_favorite"]].copy()
dog_a["dog_odds"] = dog_a["away_decimal_odds"]
dog_a["dog_win"] = dog_a["away_win"]
dog_a["dog_rpi"] = -dog_a["rpi_diff"]
dog_a["dog_wp"] = -dog_a["wp_diff"]
dog_a["dog_sp_wr"] = -dog_a["sp_wr_long_diff"]
dog_a["dog_sp_ra"] = -dog_a["sp_ra_long_diff"]
dog_a["dog_imp"] = dog_a["away_implied_prob"]
dog_a["dog_side"] = "away"

dcols = [
    "season", "date", "home_team", "away_team",
    "dog_odds", "dog_win", "dog_rpi", "dog_wp",
    "dog_sp_wr", "dog_sp_ra", "dog_imp", "dog_side",
]
all_dog = pd.concat([dog_h[dcols], dog_a[dcols]], ignore_index=True)
print(f"\n  Total underdog bets: {len(all_dog)} ({len(dog_h)} home + {len(dog_a)} away)")

flat_bet_report("Baseline (all underdogs ML)", all_dog, "dog_win", "dog_odds")

# By implied prob buckets
print()
for lo, hi in [(0.30, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50)]:
    sub = all_dog[(all_dog["dog_imp"] >= lo) & (all_dog["dog_imp"] < hi)]
    flat_bet_report(f"Dog implied [{lo:.2f}, {hi:.2f})", sub, "dog_win", "dog_odds")

# RPI where underdog has edge
print()
for t in [-0.02, -0.01, 0.0, 0.01, 0.02, 0.03]:
    sub = all_dog[all_dog["dog_rpi"] >= t]
    flat_bet_report(f"Dog RPI >= {t:.2f}", sub, "dog_win", "dog_odds")

# SP WR where underdog pitcher is better
print()
for t in [-0.10, -0.05, 0.0, 0.05, 0.10, 0.15]:
    sub = all_dog[all_dog["dog_sp_wr"] >= t]
    flat_bet_report(f"Dog SP WR >= {t:.2f}", sub, "dog_win", "dog_odds")

# Combos — strong underdog + pitcher edge
print()
dog_combos = [
    ("Dog imp>=0.40 + RPI>=0",
        lambda d: (d["dog_imp"] >= 0.40) & (d["dog_rpi"] >= 0)),
    ("Dog imp>=0.45 + RPI>=0",
        lambda d: (d["dog_imp"] >= 0.45) & (d["dog_rpi"] >= 0)),
    ("Dog imp>=0.40 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.40) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog imp>=0.45 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.45) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog RPI>=0 + SP_WR>=0.05",
        lambda d: (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.05)),
    ("Dog RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog RPI>=0.01 + SP_WR>=0.10",
        lambda d: (d["dog_rpi"] >= 0.01) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["dog_rpi"] >= 0.02) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog imp>=0.40 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.40) & (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog imp>=0.45 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.45) & (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog RPI>=0.02 + SP_WR>=0.05",
        lambda d: (d["dog_rpi"] >= 0.02) & (d["dog_sp_wr"] >= 0.05)),
    ("Dog RPI>=0.03 + SP_WR>=0.05",
        lambda d: (d["dog_rpi"] >= 0.03) & (d["dog_sp_wr"] >= 0.05)),
]
for label, fn in dog_combos:
    sub = all_dog[fn(all_dog)]
    flat_bet_report(label, sub, "dog_win", "dog_odds")

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 95)
print("PART 4: TRAIN/TEST SPLIT")
print(f"  TRAIN: 2010-2017  |  TEST: 2018-2019, 2021")
print("=" * 95)

fav_configs = [
    ("Fav ML baseline",
        lambda d: pd.Series(True, index=d.index)),
    ("Fav ML: RPI>=0.03 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_wr"] >= 0.10)),
    ("Fav ML: RPI>=0.04 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.04) & (d["fav_sp_wr"] >= 0.10)),
    ("Fav ML: RPI>=0.03 + SP_RA<=0 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_ra"] <= 0) & (d["fav_sp_wr"] >= 0.10)),
    ("Fav ML: RPI>=0.03 + WP>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_wp"] >= 0.05) & (d["fav_sp_wr"] >= 0.10)),
    ("Fav ML: RPI>=0.02 + SP_WR>=0.20",
        lambda d: (d["fav_rpi"] >= 0.02) & (d["fav_sp_wr"] >= 0.20)),
    ("Fav ML: RPI>=0.03 + SP_WR>=0.20",
        lambda d: (d["fav_rpi"] >= 0.03) & (d["fav_sp_wr"] >= 0.20)),
    ("Fav ML: RPI>=0.05 + SP_WR>=0.10",
        lambda d: (d["fav_rpi"] >= 0.05) & (d["fav_sp_wr"] >= 0.10)),
]

dog_configs = [
    ("Dog ML baseline",
        lambda d: pd.Series(True, index=d.index)),
    ("Dog ML: imp>=0.40 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.40) & (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog ML: imp>=0.45 + RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.45) & (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog ML: RPI>=0 + SP_WR>=0.10",
        lambda d: (d["dog_rpi"] >= 0) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog ML: RPI>=0.02 + SP_WR>=0.10",
        lambda d: (d["dog_rpi"] >= 0.02) & (d["dog_sp_wr"] >= 0.10)),
    ("Dog ML: RPI>=0.03 + SP_WR>=0.05",
        lambda d: (d["dog_rpi"] >= 0.03) & (d["dog_sp_wr"] >= 0.05)),
    ("Dog ML: imp>=0.45 + SP_WR>=0.10",
        lambda d: (d["dog_imp"] >= 0.45) & (d["dog_sp_wr"] >= 0.10)),
]

for split_label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
    print(f"\n  --- {split_label} ---")
    print(f"  {'Config':<60} {'N':>5}  {'WR':>5}  {'Odds':>5}  {'ROI':>6}  {'P&L':>10}")
    print(f"  {'-'*60} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*10}")

    fav_s = all_fav[all_fav["season"].isin(seasons)]
    dog_s = all_dog[all_dog["season"].isin(seasons)]

    for label, fn in fav_configs:
        sub = fav_s[fn(fav_s)]
        flat_bet_report(f"{split_label} {label}", sub, "fav_win", "fav_odds")

    print()
    for label, fn in dog_configs:
        sub = dog_s[fn(dog_s)]
        flat_bet_report(f"{split_label} {label}", sub, "dog_win", "dog_odds")

# ══════════════════════════════════════════════════════════════════════════
# PART 5: Robustness grids
print("\n" + "=" * 95)
print("PART 5: ROBUSTNESS GRID — Fav ML (RPI x SP_WR)")
print("=" * 95)

rpi_bins = [(0.00, 0.02), (0.02, 0.04), (0.04, 0.06), (0.06, 1.0)]
wr_bins = [(0.00, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.0)]

for split_label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
    print(f"\n  {split_label} — Favorite ML:")
    fav_s = all_fav[all_fav["season"].isin(seasons)]
    header = "  RPI \\ SP_WR   "
    for wlo, whi in wr_bins:
        header += f"  [{wlo:.2f},{whi:.2f})"
    print(header)

    for rlo, rhi in rpi_bins:
        row = f"  [{rlo:.2f},{rhi:.2f})  "
        for wlo, whi in wr_bins:
            cell = fav_s[
                (fav_s["fav_rpi"] >= rlo) & (fav_s["fav_rpi"] < rhi)
                & (fav_s["fav_sp_wr"] >= wlo) & (fav_s["fav_sp_wr"] < whi)
            ]
            if len(cell) >= 20:
                pnl = np.where(cell["fav_win"], 100 * (cell["fav_odds"] - 1), -100).sum()
                roi = pnl / (len(cell) * 100)
                row += f"  {roi:>+5.1%}({len(cell):>4})"
            else:
                row += f"  {'---':>10}"
            row += " "
        print(row)

print("\n" + "=" * 95)
print("PART 5b: ROBUSTNESS GRID — Dog ML (RPI x SP_WR)")
print("=" * 95)

dog_rpi_bins = [(-0.06, -0.03), (-0.03, 0.00), (0.00, 0.02), (0.02, 1.0)]
dog_wr_bins = [(-0.20, -0.05), (-0.05, 0.05), (0.05, 0.15), (0.15, 1.0)]

for split_label, seasons in [("TRAIN", TRAIN_SEASONS), ("TEST", TEST_SEASONS)]:
    print(f"\n  {split_label} — Underdog ML:")
    dog_s = all_dog[all_dog["season"].isin(seasons)]
    header = "  RPI \\ SP_WR   "
    for wlo, whi in dog_wr_bins:
        header += f" [{wlo:+.2f},{whi:+.2f})"
    print(header)

    for rlo, rhi in dog_rpi_bins:
        row = f"  [{rlo:+.2f},{rhi:+.2f})  "
        for wlo, whi in dog_wr_bins:
            cell = dog_s[
                (dog_s["dog_rpi"] >= rlo) & (dog_s["dog_rpi"] < rhi)
                & (dog_s["dog_sp_wr"] >= wlo) & (dog_s["dog_sp_wr"] < whi)
            ]
            if len(cell) >= 20:
                pnl = np.where(cell["dog_win"], 100 * (cell["dog_odds"] - 1), -100).sum()
                roi = pnl / (len(cell) * 100)
                row += f"  {roi:>+5.1%}({len(cell):>4})"
            else:
                row += f"  {'---':>10}"
            row += " "
        print(row)

print("\nDone!")
