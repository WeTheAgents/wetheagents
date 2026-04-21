"""Analyze: does the Analyst scenario help or hurt Momentum's picks?

Questions:
1. When Analyst says "comfortable/blowout" and Momentum bets — win rate?
2. When Analyst says "tight/coinflip" and Momentum bets anyway — win rate?
3. Does Momentum agree with Analyst's winner prediction?
4. Analyst scenario distribution on Momentum's winning vs losing picks.
"""
import argparse
import os
import sys
import warnings
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a saved analyst-impact LLM output file.")
    parser.add_argument(
        "--input",
        type=Path,
        default=os.getenv("MLB_BETTING_LEGACY_OUTPUT_PATH"),
        help="Path to the saved LLM output file. Can also be set via MLB_BETTING_LEGACY_OUTPUT_PATH.",
    )
    return parser.parse_args()


ARGS = _parse_args()
if not ARGS.input:
    raise SystemExit("Pass --input or set MLB_BETTING_LEGACY_OUTPUT_PATH.")

# 1. Parse LLM output — need analyst scenario + momentum verdict
output_path = Path(ARGS.input).expanduser()
lines = output_path.read_text(encoding="utf-8", errors="replace").splitlines(True)

results = []
i = 0
while i < len(lines):
    line = lines[i].strip()
    m = re.match(r"\[(\d+)/80\]\s+(.+)", line)
    if m:
        game_id = m.group(2)
        analyst_winner = analyst_score = analyst_tightness = analyst_conf = None
        momentum_action = momentum_conf = None
        value_action = value_conf = None

        for j in range(i + 1, min(i + 20, len(lines))):
            l = lines[j].strip()
            # Analyst line: "RL Analyst: away wins 5-2 (comfortable, conf=80%)"
            am = re.search(r"RL Analyst: (\w+) wins (\S+) \((\w+), conf=(\d+)%\)", l)
            if am:
                analyst_winner = am.group(1)  # "home" or "away"
                analyst_score = am.group(2)   # "5-2"
                analyst_tightness = am.group(3)  # "comfortable"
                analyst_conf = int(am.group(4)) / 100.0
            if "RL_Momentum:" in l:
                parts = l.split("RL_Momentum: ")[1]
                momentum_action = parts.split(" ")[0]
                mc = re.search(r"conf=([0-9.]+)", parts)
                momentum_conf = float(mc.group(1)) if mc else 0
            if "RL_Value:" in l:
                parts = l.split("RL_Value: ")[1]
                value_action = parts.split(" ")[0]
                vc = re.search(r"conf=([0-9.]+)", parts)
                value_conf = float(vc.group(1)) if vc else 0
            if "-> " in l:
                break

        if momentum_action and analyst_tightness:
            results.append({
                "game": game_id,
                "analyst_winner": analyst_winner,
                "analyst_score": analyst_score,
                "analyst_tightness": analyst_tightness,
                "analyst_conf": analyst_conf,
                "momentum": momentum_action,
                "mom_conf": momentum_conf,
                "value": value_action,
                "val_conf": value_conf,
            })
    i += 1

print(f"Parsed {len(results)} games\n")

# 2. Rebuild same sample for outcomes
from src.features import build_spec_features, SPEC_FEATURES
from src.model import ModelConfig, compute_divergence, run_walk_forward
from src.data_loader import american_to_decimal

print("Rebuilding data...")
full = build_spec_features()
features_available = [
    f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
]
cfg = ModelConfig()
fold_results = run_walk_forward(full, features_available, "closing_decimal_odds_favorite", cfg=cfg)
div = compute_divergence(fold_results)

mk = ["season", "date", "home_team", "away_team"]
full["month"] = pd.to_datetime(full["date"]).dt.month
keep = [c for c in full.columns if c not in div.columns or c in mk]
fs = full[keep].drop_duplicates(subset=mk)
df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

if "fav_margin" not in df.columns:
    df["fav_margin"] = np.where(
        df["fav_is_home"],
        df["home_final"] - df["away_final"],
        df["away_final"] - df["home_final"],
    )

df["rl_odds"] = np.nan
if "home_run_line_odds" in df.columns:
    hf = df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == -1.5)
    df.loc[hf, "rl_odds"] = df.loc[hf, "home_run_line_odds"].apply(
        lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
    )
if "away_run_line_odds" in df.columns:
    af = ~df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == 1.5)
    df.loc[af, "rl_odds"] = df.loc[af, "away_run_line_odds"].apply(
        lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
    )
df["rl_odds"] = df["rl_odds"].fillna(2.40)

mask = pd.Series(True, index=df.index)
if "home_run_line" in df.columns:
    mask = mask & df["home_run_line"].isin([-1.5, 1.5])
if "involves_col" in df.columns:
    mask = mask & ~df["involves_col"]
if "is_extreme_line" in df.columns:
    mask = mask & ~df["is_extreme_line"]
df = df[mask].copy()
df["fav_covers"] = df["fav_margin"] >= 2
df["fav_won"] = df["fav_margin"] > 0

fav_is_home = df["fav_is_home"]
df["fav_close_game_wp"] = np.where(fav_is_home, df["close_game_wp_home"], df["close_game_wp_away"])
df["fav_streak_diff"] = np.where(
    fav_is_home, df["streak_home"] - df["streak_away"], df["streak_away"] - df["streak_home"],
)

filtered = df[(df["fav_close_game_wp"] <= 0.45) & (df["fav_streak_diff"] >= 0)].copy()
covers = filtered[filtered["fav_covers"]].sample(40, random_state=42)
non_covers = filtered[~filtered["fav_covers"]].sample(40, random_state=42)
sample = pd.concat([covers, non_covers]).sample(frac=1, random_state=42).reset_index(drop=True)

# 3. Match
rdf = pd.DataFrame(results[:80])
rdf["fav_margin"] = sample["fav_margin"].values
rdf["fav_covers"] = sample["fav_covers"].values
rdf["fav_won"] = sample["fav_won"].values
rdf["fav_is_home"] = sample["fav_is_home"].values
rdf["rl_odds"] = sample["rl_odds"].values

# Determine if analyst predicted FAV wins
# analyst_winner is "home" or "away"; fav_is_home tells us which is the favorite
rdf["analyst_predicts_fav"] = (
    ((rdf["analyst_winner"] == "home") & rdf["fav_is_home"]) |
    ((rdf["analyst_winner"] == "away") & ~rdf["fav_is_home"])
)

# 4. Analysis
mom_bets = rdf[rdf["momentum"] == "BET_RL"].copy()
mom_pass = rdf[rdf["momentum"] == "PASS"].copy()

print("\n" + "=" * 70)
print("ANALYST IMPACT ON MOMENTUM'S PICKS")
print("=" * 70)

# Q1: Analyst tightness vs Momentum action
print("\n--- Analyst scenario when Momentum bets vs passes ---")
for action, label, subset in [("BET_RL", "Momentum BET", mom_bets), ("PASS", "Momentum PASS", mom_pass)]:
    print(f"\n  {label} ({len(subset)} games):")
    for t in ["blowout", "comfortable", "tight", "coinflip"]:
        sub = subset[subset["analyst_tightness"] == t]
        if len(sub) > 0:
            pct = len(sub) / len(subset) * 100
            print(f"    {t}: {len(sub)} ({pct:.0f}%)")

# Q2: Does Momentum follow Analyst's tightness signal?
print("\n--- Momentum BET rate by Analyst tightness ---")
for t in ["blowout", "comfortable", "tight", "coinflip"]:
    sub = rdf[rdf["analyst_tightness"] == t]
    if len(sub) > 0:
        bet_rate = (sub["momentum"] == "BET_RL").mean()
        cr = sub[sub["momentum"] == "BET_RL"]["fav_covers"].mean() if (sub["momentum"] == "BET_RL").any() else 0
        n_bet = (sub["momentum"] == "BET_RL").sum()
        print(f"  {t:12s}: {len(sub)} games, Momentum bets {bet_rate*100:.0f}% ({n_bet}), "
              f"cover when bets: {cr*100:.0f}%")

# Q3: Analyst winner prediction accuracy
print("\n--- Analyst predicts FAV wins ---")
print(f"  Analyst says fav wins: {rdf['analyst_predicts_fav'].sum()}/{len(rdf)} "
      f"({rdf['analyst_predicts_fav'].mean()*100:.0f}%)")
fav_pred = rdf[rdf["analyst_predicts_fav"]]
dog_pred = rdf[~rdf["analyst_predicts_fav"]]
print(f"  When analyst says fav: actual fav cover {fav_pred['fav_covers'].mean()*100:.1f}%, "
      f"fav win {fav_pred['fav_won'].mean()*100:.1f}%")
if len(dog_pred) > 0:
    print(f"  When analyst says dog: actual fav cover {dog_pred['fav_covers'].mean()*100:.1f}%, "
          f"fav win {dog_pred['fav_won'].mean()*100:.1f}%")

# Q4: On Momentum's WINNING picks — what did Analyst say?
print("\n--- Analyst scenario on Momentum's WINS vs LOSSES ---")
mom_wins = mom_bets[mom_bets["fav_covers"]]
mom_losses = mom_bets[~mom_bets["fav_covers"]]
print(f"\n  Momentum WINS ({len(mom_wins)}):")
for t in ["blowout", "comfortable", "tight", "coinflip"]:
    n = (mom_wins["analyst_tightness"] == t).sum()
    if n > 0:
        print(f"    {t}: {n} ({n/len(mom_wins)*100:.0f}%)")
print(f"    Analyst predicted fav: {mom_wins['analyst_predicts_fav'].sum()}/{len(mom_wins)}")
print(f"    Avg analyst conf: {mom_wins['analyst_conf'].mean():.2f}")

print(f"\n  Momentum LOSSES ({len(mom_losses)}):")
for t in ["blowout", "comfortable", "tight", "coinflip"]:
    n = (mom_losses["analyst_tightness"] == t).sum()
    if n > 0:
        print(f"    {t}: {n} ({n/len(mom_losses)*100:.0f}%)")
print(f"    Analyst predicted fav: {mom_losses['analyst_predicts_fav'].sum()}/{len(mom_losses)}")
print(f"    Avg analyst conf: {mom_losses['analyst_conf'].mean():.2f}")

# Q5: Does Momentum override Analyst's tight/coinflip warnings?
print("\n--- Momentum overrides Analyst 'tight' warning ---")
tight = rdf[rdf["analyst_tightness"].isin(["tight", "coinflip"])]
tight_bets = tight[tight["momentum"] == "BET_RL"]
print(f"  Analyst says tight/coinflip: {len(tight)} games")
print(f"  Momentum bets anyway: {len(tight_bets)}")
if len(tight_bets) > 0:
    print(f"  Cover when overrides: {tight_bets['fav_covers'].mean()*100:.1f}%")
    for _, r in tight_bets.iterrows():
        tag = "WIN" if r["fav_covers"] else "LOSS"
        print(f"    [{tag}] {r['game']}: margin={r['fav_margin']:.0f} mom_c={r['mom_conf']:.2f}")

# Q6: Correlation between analyst confidence and Momentum confidence
print("\n--- Confidence correlation ---")
corr = rdf[["analyst_conf", "mom_conf"]].corr().iloc[0, 1]
print(f"  Analyst conf vs Momentum conf (all 80): r = {corr:.3f}")
corr_bets = mom_bets[["analyst_conf", "mom_conf"]].corr().iloc[0, 1]
print(f"  Analyst conf vs Momentum conf (BET only): r = {corr_bets:.3f}")

# Q7: Detailed game-by-game for Momentum BET
print(f"\n{'=' * 70}")
print("GAME-BY-GAME: Momentum BET_RL (24 games)")
print(f"{'=' * 70}")
for _, r in mom_bets.sort_values("fav_covers", ascending=False).iterrows():
    tag = "WIN" if r["fav_covers"] else "LOSS"
    print(f"  [{tag}] {r['game']}: margin={r['fav_margin']:+.0f}  "
          f"analyst={r['analyst_tightness']}({r['analyst_conf']:.0%}) "
          f"mom={r['mom_conf']:.2f}")
