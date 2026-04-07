"""One-shot: parse previous LLM run output and seed the cache file."""
import sys
import re
import json
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

output_path = (
    r"C:\Users\peach\AppData\Local\Temp\claude\D--GitHub-wetheagents-domains-mlb-betting"
    r"\7ae3feb3-f8af-4b20-a2ec-31ec0baa2ae6\tasks\bpm8onx3s.output"
)
lines = open(output_path, encoding="utf-8", errors="replace").readlines()

# Parse LLM results
llm_results = []
i = 0
while i < len(lines):
    line = lines[i].strip()
    m = re.match(r"\[(\d+)/200\]\s+(.+)", line)
    if m:
        game_id = m.group(2)
        analyst_winner = analyst_score = None
        momentum_action = momentum_conf = None
        final_action = None

        for j in range(i + 1, min(i + 20, len(lines))):
            l = lines[j].strip()
            am = re.search(r"Analyst: (\w+) wins (\S+)", l)
            if am:
                analyst_winner = am.group(1)
                analyst_score = am.group(2)
            if "RL_Momentum:" in l:
                parts = l.split("RL_Momentum: ")[1]
                momentum_action = parts.split(" ")[0]
                mc = re.search(r"conf=([0-9.]+)", parts)
                momentum_conf = float(mc.group(1)) if mc else 0
            if "-> BET" in l or "-> PASS" in l:
                final_action = "BET" if "-> BET" in l else "PASS"
                break

        if momentum_action and final_action and analyst_score:
            llm_results.append({
                "game_id": game_id,
                "analyst_winner": analyst_winner,
                "analyst_score": analyst_score,
                "momentum_action": momentum_action,
                "momentum_conf": momentum_conf,
                "final_action": final_action,
            })
    i += 1

print(f"Parsed {len(llm_results)} LLM results")

# Rebuild same sample to get outcomes
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
        df["fav_is_home"], df["home_final"] - df["away_final"],
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
    fav_is_home, df["streak_home"] - df["streak_away"],
    df["streak_away"] - df["streak_home"],
)

filtered = df[(df["fav_close_game_wp"] <= 0.45) & (df["fav_streak_diff"] >= 0)].copy()
covers = filtered[filtered["fav_covers"]].sample(100, random_state=42)
non_covers = filtered[~filtered["fav_covers"]].sample(100, random_state=42)
sample = pd.concat([covers, non_covers]).sample(frac=1, random_state=42).reset_index(drop=True)

print(f"Sample: {len(sample)} games")

# Match LLM results to sample outcomes
cache = []
for idx, llm in enumerate(llm_results):
    if idx >= len(sample):
        break
    row = sample.iloc[idx]
    fav_margin = int(row["fav_margin"])
    fav_covers = bool(fav_margin >= 2)

    analyst_score = llm["analyst_score"]
    try:
        parts = analyst_score.replace("-", " ").split()
        analyst_margin = abs(int(parts[0]) - int(parts[1]))
    except (ValueError, IndexError):
        analyst_margin = 0

    cache.append({
        "game_id": llm["game_id"],
        "season": int(row["season"]),
        "final_action": llm["final_action"],
        "confidence": llm["momentum_conf"],
        "fav_margin": fav_margin,
        "fav_covers": fav_covers,
        "rl_odds": float(row["rl_odds"]),
        "momentum_action": llm["momentum_action"],
        "momentum_conf": llm["momentum_conf"],
        "analyst_score": analyst_score,
        "analyst_margin": analyst_margin,
        "analyst_winner": llm["analyst_winner"],
    })

cache_path = Path(__file__).resolve().parent.parent / "picks" / "rl_fav_cache.json"
cache_path.parent.mkdir(exist_ok=True)
cache_path.write_text(json.dumps(cache, indent=2))
print(f"Wrote {len(cache)} entries to {cache_path}")
