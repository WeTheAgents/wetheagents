"""Analyze LEAN breakdown: which expert drives the winning picks?"""
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
    parser = argparse.ArgumentParser(description="Analyze a saved LEAN LLM output file.")
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

# 1. Parse LLM run output
output_path = Path(ARGS.input).expanduser()
lines = output_path.read_text(encoding="utf-8", errors="replace").splitlines(True)

results = []
i = 0
while i < len(lines):
    line = lines[i].strip()
    m = re.match(r"\[(\d+)/80\]\s+(.+)", line)
    if m:
        game_id = m.group(2)
        momentum_action = momentum_conf = value_action = value_conf = None
        final_action = None
        for j in range(i + 1, min(i + 15, len(lines))):
            l = lines[j].strip()
            if "RL_Momentum:" in l:
                parts = l.split("RL_Momentum: ")[1]
                momentum_action = parts.split(" ")[0]
                mc = re.search(r"conf=([0-9.]+)", parts)
                momentum_conf = float(mc.group(1)) if mc else 0
            elif "RL_Value:" in l:
                parts = l.split("RL_Value: ")[1]
                value_action = parts.split(" ")[0]
                vc = re.search(r"conf=([0-9.]+)", parts)
                value_conf = float(vc.group(1)) if vc else 0
            elif "-> " in l:
                final_action = l.split("-> ")[1].split(" ")[0]
                break
        if momentum_action and value_action and final_action:
            results.append({
                "game": game_id,
                "momentum": momentum_action,
                "mom_conf": momentum_conf,
                "value": value_action,
                "val_conf": value_conf,
                "final": final_action,
            })
    i += 1

print(f"Parsed {len(results)} game results from LLM output\n")

# 2. Rebuild the same sample to get outcomes
from src.features import build_spec_features, SPEC_FEATURES
from src.model import ModelConfig, compute_divergence, run_walk_forward
from src.data_loader import american_to_decimal

print("Rebuilding data (features + walk-forward)...")
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

fav_is_home = df["fav_is_home"]
df["fav_close_game_wp"] = np.where(fav_is_home, df["close_game_wp_home"], df["close_game_wp_away"])
df["fav_streak_diff"] = np.where(
    fav_is_home,
    df["streak_home"] - df["streak_away"],
    df["streak_away"] - df["streak_home"],
)

filtered = df[(df["fav_close_game_wp"] <= 0.45) & (df["fav_streak_diff"] >= 0)].copy()
covers = filtered[filtered["fav_covers"]].sample(40, random_state=42)
non_covers = filtered[~filtered["fav_covers"]].sample(40, random_state=42)
sample = pd.concat([covers, non_covers]).sample(frac=1, random_state=42).reset_index(drop=True)

# 3. Match
rdf = pd.DataFrame(results[:80])
rdf["fav_margin"] = sample["fav_margin"].values
rdf["fav_covers"] = sample["fav_covers"].values
rdf["rl_odds"] = sample["rl_odds"].values

# 4. LEAN analysis
print("\n" + "=" * 70)
print("LEAN BREAKDOWN: WHO DRIVES THE SIGNAL?")
print("=" * 70)

lean = rdf[rdf["final"] == "LEAN"]
print(f"\nTotal LEAN: {len(lean)} games, cover {lean['fav_covers'].mean()*100:.1f}%")

mom_bet = lean[lean["momentum"] == "BET_RL"]
val_bet = lean[lean["value"] == "BET_RL"]

print(f"\n--- Momentum voted BET, Value voted PASS ({len(mom_bet)} games) ---")
if len(mom_bet) > 0:
    cr = mom_bet["fav_covers"].mean()
    pnl = np.where(mom_bet["fav_covers"], (mom_bet["rl_odds"] - 1) * 100, -100)
    roi = pnl.sum() / (len(mom_bet) * 100) * 100
    print(f"  Cover: {cr*100:.1f}%  ROI: {roi:+.1f}%")
    print(f"  Avg mom_conf: {mom_bet['mom_conf'].mean():.2f}  Avg val_conf: {mom_bet['val_conf'].mean():.2f}")
    for _, r in mom_bet.iterrows():
        tag = "WIN" if r["fav_covers"] else "LOSS"
        print(f"    [{tag}] {r['game']}: margin={r['fav_margin']:.0f}  mom={r['mom_conf']:.2f} val={r['val_conf']:.2f}")

print(f"\n--- Value voted BET, Momentum voted PASS ({len(val_bet)} games) ---")
if len(val_bet) > 0:
    cr = val_bet["fav_covers"].mean()
    pnl = np.where(val_bet["fav_covers"], (val_bet["rl_odds"] - 1) * 100, -100)
    roi = pnl.sum() / (len(val_bet) * 100) * 100
    print(f"  Cover: {cr*100:.1f}%  ROI: {roi:+.1f}%")
    print(f"  Avg mom_conf: {val_bet['mom_conf'].mean():.2f}  Avg val_conf: {val_bet['val_conf'].mean():.2f}")
    for _, r in val_bet.iterrows():
        tag = "WIN" if r["fav_covers"] else "LOSS"
        print(f"    [{tag}] {r['game']}: margin={r['fav_margin']:.0f}  mom={r['mom_conf']:.2f} val={r['val_conf']:.2f}")

# 5. Solo expert accuracy
print(f"\n{'=' * 70}")
print("EXPERT SOLO ACCURACY (across all 80 games)")
print(f"{'=' * 70}")

for name, col in [("Momentum", "momentum"), ("Value", "value")]:
    bet = rdf[rdf[col] == "BET_RL"]
    pas = rdf[rdf[col] == "PASS"]
    print(f"\n  {name}:")
    print(f"    BET_RL: {len(bet)} games, cover {bet['fav_covers'].mean()*100:.1f}%")
    pnl = np.where(bet["fav_covers"], (bet["rl_odds"] - 1) * 100, -100)
    print(f"    ROI: {pnl.sum()/(len(bet)*100)*100:+.1f}%")
    print(f"    PASS:   {len(pas)} games, cover {pas['fav_covers'].mean()*100:.1f}%")
    print(f"    Selectivity lift: {(bet['fav_covers'].mean() - pas['fav_covers'].mean())*100:+.1f}pp")

# 6. STRONG_BET detail
print(f"\n{'=' * 70}")
print("STRONG_BET DETAIL")
print(f"{'=' * 70}")
strong = rdf[rdf["final"] == "STRONG_BET"]
print(f"N: {len(strong)}, Cover: {strong['fav_covers'].mean()*100:.1f}%")
for _, r in strong.iterrows():
    tag = "WIN" if r["fav_covers"] else "LOSS"
    print(f"  [{tag}] {r['game']}: margin={r['fav_margin']:.0f}  mom={r['mom_conf']:.2f} val={r['val_conf']:.2f}")
