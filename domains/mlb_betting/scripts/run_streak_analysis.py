"""Run streak analysis without Jupyter — quick validation script."""

import sys
import os
import warnings

warnings.filterwarnings("ignore")

# Ensure we can import src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend

import numpy as np
import pandas as pd
from scipy import stats

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

# ── 1. Load Data ─────────────────────────────────────────────────────────
print("=== 1. Load Data ===")
games = load_all_seasons()
print(f"Loaded: {len(games)} games")
games = apply_data_filters(games)
print(f"After data filters: {len(games)} games")
games = add_derived_odds(games)
print(f"Seasons: {sorted(games['season'].unique())}")

# ── 2. Build Team Game Sequences ─────────────────────────────────────────
print("\n=== 2. Build Team Game Sequences ===")
home = pd.DataFrame(
    {
        "season": games["season"].values,
        "date": games["date"].values,
        "team": games["home_team"].values,
        "opponent": games["away_team"].values,
        "is_home": True,
        "won": games["home_win"].astype(bool).values,
        "close_ml": games["home_close_ml"].values,
        "decimal_odds": games["home_decimal_odds"].values,
        "implied_prob": games["home_implied_prob"].values,
        "is_favorite": (games["home_implied_prob"] > 0.5).values,
        "involves_col": games["involves_col"].values,
        "is_september": games["is_september"].values,
        "is_extreme_line": games["is_extreme_line"].values,
    }
)
away = pd.DataFrame(
    {
        "season": games["season"].values,
        "date": games["date"].values,
        "team": games["away_team"].values,
        "opponent": games["home_team"].values,
        "is_home": False,
        "won": (~games["home_win"].astype(bool)).values,
        "close_ml": games["away_close_ml"].values,
        "decimal_odds": games["away_decimal_odds"].values,
        "implied_prob": games["away_implied_prob"].values,
        "is_favorite": (games["away_implied_prob"] > 0.5).values,
        "involves_col": games["involves_col"].values,
        "is_september": games["is_september"].values,
        "is_extreme_line": games["is_extreme_line"].values,
    }
)
team_games = pd.concat([home, away], ignore_index=True)
team_games = team_games.sort_values(["team", "season", "date"]).reset_index(drop=True)
print(f"Team-game rows: {len(team_games)}")
print(f"Unique teams: {team_games['team'].nunique()}")

# ── 3. Calculate Streaks ─────────────────────────────────────────────────
print("\n=== 3. Calculate Streaks ===")
streaks_list = []
streak_types_list = []
for (_team, _season), group in team_games.groupby(["team", "season"]):
    group = group.sort_values("date")
    won = group["won"].values
    s_vals = np.zeros(len(group), dtype=int)
    s_types = ["none"] * len(group)
    current_streak = 0
    current_type = "none"
    for i in range(len(group)):
        s_vals[i] = current_streak
        s_types[i] = current_type
        if won[i]:
            if current_type == "W":
                current_streak += 1
            else:
                current_streak = 1
                current_type = "W"
        else:
            if current_type == "L":
                current_streak += 1
            else:
                current_streak = 1
                current_type = "L"
    streaks_list.extend(s_vals)
    streak_types_list.extend(s_types)

team_games["streak"] = streaks_list
team_games["streak_type"] = streak_types_list
team_games["signed_streak"] = np.where(
    team_games["streak_type"] == "W",
    team_games["streak"],
    np.where(team_games["streak_type"] == "L", -team_games["streak"], 0),
)
print(f"Max win streak entering game: {team_games['signed_streak'].max()}")
print(f"Max loss streak entering game: {team_games['signed_streak'].min()}")

# ── 4. Win Rate After Streak N ───────────────────────────────────────────
print("\n=== 4. Win Rate After Streak N ===")
streaked = team_games[team_games["streak"] >= 1].copy()
baseline_wr = team_games["won"].mean()
print(f"Baseline win rate: {baseline_wr:.4f} ({baseline_wr:.1%})")

streak_stats = (
    streaked.groupby("signed_streak")
    .agg(games=("won", "count"), wins=("won", "sum"), win_rate=("won", "mean"))
    .reset_index()
)

display_stats = streak_stats[
    (streak_stats["signed_streak"] >= -10)
    & (streak_stats["signed_streak"] <= 10)
    & (streak_stats["games"] >= 50)
].copy()
display_stats["vs_baseline"] = ((display_stats["win_rate"] - baseline_wr) * 100).round(1)

print("\nWin Rate After Streak (min 50 games):")
print("=" * 80)
for _, row in display_stats.iterrows():
    ss = int(row["signed_streak"])
    sl = f"W{ss}" if ss > 0 else f"L{abs(ss)}"
    wr = row["win_rate"] * 100
    n = int(row["games"])
    w = int(row["wins"])
    vb = row["vs_baseline"]
    print(f"  After {sl:>3}: {wr:5.1f}% win rate ({w}/{n} games) {vb:+.1f}% vs baseline")

# ── 5. Statistical Significance ──────────────────────────────────────────
print("\n=== 5. Statistical Significance (Binomial Test vs Baseline) ===")
for _, row in display_stats.iterrows():
    n, k = int(row["games"]), int(row["wins"])
    p_value = stats.binomtest(k, n, baseline_wr).pvalue
    ss = int(row["signed_streak"])
    sl = f"W{ss}" if ss > 0 else f"L{abs(ss)}"
    sig = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*" if p_value < 0.05 else ""
    print(f"  After {sl:>3}: p={p_value:.4f} {sig:>3}  (n={n})")

# ── 6. Favorites vs Underdogs ─────────────────────────────────────────────
print("\n=== 6. Favorites vs Underdogs on Streaks ===")
for fav_label, fav_mask in [("Favorites", True), ("Underdogs", False)]:
    subset = streaked[streaked["is_favorite"] == fav_mask]
    base = subset["won"].mean()
    print(f"\n{fav_label} (baseline: {base:.1%}):")
    print("-" * 60)
    sub_stats = (
        subset.groupby("signed_streak")
        .agg(games=("won", "count"), win_rate=("won", "mean"))
        .reset_index()
    )
    sub_stats = sub_stats[
        (sub_stats["signed_streak"] >= -8)
        & (sub_stats["signed_streak"] <= 8)
        & (sub_stats["games"] >= 30)
    ]
    for _, row in sub_stats.iterrows():
        ss = int(row["signed_streak"])
        sl = f"W{ss}" if ss > 0 else f"L{abs(ss)}"
        diff = (row["win_rate"] - base) * 100
        print(f"  After {sl:>3}: {row['win_rate']:.1%} ({int(row['games'])} games) {diff:+.1f}% vs base")

# ── 7. Home vs Away ──────────────────────────────────────────────────────
print("\n=== 7. Home vs Away on Streaks ===")
for location, loc_mask in [("Home", True), ("Away", False)]:
    subset = streaked[streaked["is_home"] == loc_mask]
    base = subset["won"].mean()
    print(f"\n{location} Games (baseline: {base:.1%}):")
    print("-" * 60)
    sub_stats = (
        subset.groupby("signed_streak")
        .agg(games=("won", "count"), win_rate=("won", "mean"))
        .reset_index()
    )
    sub_stats = sub_stats[
        (sub_stats["signed_streak"] >= -8)
        & (sub_stats["signed_streak"] <= 8)
        & (sub_stats["games"] >= 30)
    ]
    for _, row in sub_stats.iterrows():
        ss = int(row["signed_streak"])
        sl = f"W{ss}" if ss > 0 else f"L{abs(ss)}"
        diff = (row["win_rate"] - base) * 100
        print(f"  After {sl:>3}: {row['win_rate']:.1%} ({int(row['games'])} games) {diff:+.1f}% vs base")

# ── 8. ROI Simulation ────────────────────────────────────────────────────
print("\n=== 8. ROI Simulation ===")
bettable = streaked[
    ~streaked["involves_col"] & ~streaked["is_september"] & ~streaked["is_extreme_line"]
].copy()
print(f"Bettable games with streaks: {len(bettable)}")


def sim_bet(df, min_streak, streak_type, unit=100.0):
    if streak_type == "W":
        bets = df[df["signed_streak"] >= min_streak].copy()
    else:
        bets = df[df["signed_streak"] <= -min_streak].copy()
        bets["won"] = ~bets["won"]
        bets["decimal_odds"] = 1 / (1 - 1 / bets["decimal_odds"])
    if len(bets) == 0:
        return None
    bets["pnl"] = bets.apply(
        lambda r: unit * (r["decimal_odds"] - 1) if r["won"] else -unit, axis=1
    )
    total_staked = len(bets) * unit
    return {
        "n": len(bets),
        "wr": bets["won"].mean(),
        "roi": bets["pnl"].sum() / total_staked,
        "pnl": bets["pnl"].sum(),
        "odds": bets["decimal_odds"].mean(),
    }


print("\nBetting ON winning streaks (back the hot team):")
print(f"{'Streak':>8} {'Bets':>6} {'Win%':>7} {'AvgOdds':>9} {'ROI':>8} {'P&L':>10}")
print("-" * 55)
for ms in range(1, 9):
    r = sim_bet(bettable, ms, "W")
    if r and r["n"] >= 50:
        print(
            f"  W{ms}+  {r['n']:6d} {r['wr']:6.1%} {r['odds']:9.2f} "
            f"{r['roi']:7.1%} {r['pnl']:10.0f}"
        )

print("\nBetting AGAINST losing streaks (fade the cold team):")
print(f"{'Streak':>8} {'Bets':>6} {'Win%':>7} {'AvgOdds':>9} {'ROI':>8} {'P&L':>10}")
print("-" * 55)
for ms in range(1, 9):
    r = sim_bet(bettable, ms, "L")
    if r and r["n"] >= 50:
        print(
            f"  L{ms}+  {r['n']:6d} {r['wr']:6.1%} {r['odds']:9.2f} "
            f"{r['roi']:7.1%} {r['pnl']:10.0f}"
        )

# ── 9. Year-by-Year Consistency ──────────────────────────────────────────
print("\n=== 9. Year-by-Year Consistency ===")
for season in sorted(streaked["season"].unique()):
    s = streaked[streaked["season"] == season]
    w3 = s[s["signed_streak"] >= 3]
    l3 = s[s["signed_streak"] <= -3]
    w3_wr = w3["won"].mean() if len(w3) > 0 else 0
    l3_wr = l3["won"].mean() if len(l3) > 0 else 0
    print(
        f"  {season}: After W3+ = {w3_wr:.1%} (n={len(w3)})  |  "
        f"After L3+ = {l3_wr:.1%} (n={len(l3)})"
    )

# ── 10. VERDICT ──────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("STREAK ANALYSIS -- SUMMARY")
print("=" * 80)
w3_games = streaked[streaked["signed_streak"] >= 3]
l3_games = streaked[streaked["signed_streak"] <= -3]
w3_wr = w3_games["won"].mean()
l3_wr = l3_games["won"].mean()
w3_p = stats.binomtest(int(w3_games["won"].sum()), len(w3_games), baseline_wr).pvalue
l3_p = stats.binomtest(int(l3_games["won"].sum()), len(l3_games), baseline_wr).pvalue

print(f"\nBaseline: {baseline_wr:.1%}")
print(f"After W3+: {w3_wr:.1%} (n={len(w3_games)}, p={w3_p:.4f})")
print(f"After L3+: {l3_wr:.1%} (n={len(l3_games)}, p={l3_p:.4f})")

print("\n--- VERDICT ---")
if w3_p < 0.05:
    if w3_wr > baseline_wr:
        print("HOT HAND EXISTS: Win rate after W3+ is significantly ABOVE baseline")
    else:
        print("REGRESSION: Win rate after W3+ is significantly BELOW baseline")
else:
    print("NO momentum (wins): Win rate after W3+ not significantly different from baseline")

if l3_p < 0.05:
    if l3_wr < baseline_wr:
        print("COLD STREAK EXISTS: Win rate after L3+ is significantly BELOW baseline")
    else:
        print("BOUNCE BACK: Win rate after L3+ is significantly ABOVE baseline")
else:
    print("NO momentum (losses): Win rate after L3+ not significantly different from baseline")

print("\n--- BETTING IMPLICATION ---")
print("If no momentum found -> streak-based strategies have NO edge.")
print("If momentum found -> check ROI table (Section 8) for profitability.")
print("Even if win rate differs, odds may already price this in -> ROI still negative.")
