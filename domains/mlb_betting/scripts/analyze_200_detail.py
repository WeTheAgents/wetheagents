"""Detailed analysis of 200-game gpt-5.4 run.

1. Full table: Analyst prediction, Momentum decision, actual outcome
2. Missed value: PASS games that covered comfortably — why were they passed?
"""
import sys
import json
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

# Load cache (all 200 results)
cache_path = Path(__file__).resolve().parent.parent / "picks" / "rl_fav_cache.json"
results = json.loads(cache_path.read_text())
rdf = pd.DataFrame(results)

print(f"Loaded {len(rdf)} results\n")

# ======================================================================
# SECTION 1: Full BET table
# ======================================================================
bets = rdf[rdf["final_action"] == "BET"].copy()
bets_win = bets[bets["fav_covers"]].sort_values("fav_margin", ascending=False)
bets_loss = bets[~bets["fav_covers"]].sort_values("fav_margin", ascending=False)

print("=" * 100)
print(f"BET PICKS: {len(bets)} games, {bets['fav_covers'].sum()} wins, "
      f"{(~bets['fav_covers']).sum()} losses, cover {bets['fav_covers'].mean()*100:.1f}%")
print("=" * 100)

print(f"\n--- WINS ({len(bets_win)}) ---")
print(f"{'Game':<40} {'Analyst':>8} {'Mom_c':>6} {'Margin':>7} {'Odds':>5}")
print("-" * 70)
for _, r in bets_win.iterrows():
    print(f"  {r['game_id']:<38} {r['analyst_score']:>8} {r['momentum_conf']:>6.2f} "
          f"{r['fav_margin']:>+6.0f}  {r['rl_odds']:>5.2f}")

print(f"\n--- LOSSES ({len(bets_loss)}) ---")
print(f"{'Game':<40} {'Analyst':>8} {'Mom_c':>6} {'Margin':>7} {'Odds':>5}")
print("-" * 70)
for _, r in bets_loss.iterrows():
    print(f"  {r['game_id']:<38} {r['analyst_score']:>8} {r['momentum_conf']:>6.2f} "
          f"{r['fav_margin']:>+6.0f}  {r['rl_odds']:>5.2f}")

# ======================================================================
# SECTION 2: PASS games that covered by 3+ (missed value)
# ======================================================================
passes = rdf[rdf["final_action"] == "PASS"].copy()
missed = passes[passes["fav_margin"] >= 3].sort_values("fav_margin", ascending=False)

print(f"\n\n{'=' * 100}")
print(f"MISSED VALUE: PASS games where fav won by 3+ runs ({len(missed)} games)")
print(f"{'=' * 100}")
print(f"{'Game':<40} {'Analyst':>8} {'A_mar':>6} {'Mom_c':>6} {'Margin':>7} {'Reason':<30}")
print("-" * 100)
for _, r in missed.iterrows():
    # Infer why Momentum passed
    reasons = []
    if r["analyst_margin"] <= 1:
        reasons.append("Analyst: 1-run game")
    elif r["analyst_margin"] == 2:
        reasons.append("Analyst: 2-run margin")

    if r["momentum_conf"] >= 0.70:
        reasons.append(f"High PASS conf ({r['momentum_conf']:.2f})")
    elif r["momentum_conf"] >= 0.60:
        reasons.append(f"Med PASS conf ({r['momentum_conf']:.2f})")
    else:
        reasons.append(f"Low PASS conf ({r['momentum_conf']:.2f})")

    reason = "; ".join(reasons) if reasons else "?"

    print(f"  {r['game_id']:<38} {r['analyst_score']:>8} {r['analyst_margin']:>5d} "
          f"{r['momentum_conf']:>6.2f} {r['fav_margin']:>+6.0f}  {reason}")

# ======================================================================
# SECTION 3: Summary stats
# ======================================================================
print(f"\n\n{'=' * 100}")
print("SUMMARY STATS")
print(f"{'=' * 100}")

# Analyst margin distribution
print("\n  Analyst predicted margin distribution:")
for m in sorted(rdf["analyst_margin"].unique()):
    sub = rdf[rdf["analyst_margin"] == m]
    n_bet = (sub["final_action"] == "BET").sum()
    actual_cr = sub["fav_covers"].mean()
    print(f"    margin={m}: {len(sub)} games, {n_bet} bets, actual cover {actual_cr*100:.1f}%")

# Momentum bet rate by analyst margin
print("\n  Momentum BET rate by analyst predicted margin:")
for m in sorted(rdf["analyst_margin"].unique()):
    sub = rdf[rdf["analyst_margin"] == m]
    bet_rate = (sub["final_action"] == "BET").mean()
    print(f"    analyst_margin={m}: bet rate {bet_rate*100:.0f}%")

# PASS covers breakdown
print(f"\n  PASS pool breakdown:")
print(f"    Total PASS: {len(passes)}")
print(f"    PASS that covered (margin >= 2): {(passes['fav_margin'] >= 2).sum()}")
print(f"    PASS blowouts (margin >= 4): {(passes['fav_margin'] >= 4).sum()}")
print(f"    PASS blowouts (margin >= 6): {(passes['fav_margin'] >= 6).sum()}")

# Of the missed blowouts, how many had analyst 1-run prediction?
missed_blowouts = passes[passes["fav_margin"] >= 4]
if len(missed_blowouts) > 0:
    analyst_1run = (missed_blowouts["analyst_margin"] <= 1).sum()
    analyst_2plus = (missed_blowouts["analyst_margin"] >= 2).sum()
    print(f"\n  Among {len(missed_blowouts)} missed blowouts (margin >= 4):")
    print(f"    Analyst said 1-run game: {analyst_1run} ({analyst_1run/len(missed_blowouts)*100:.0f}%)")
    print(f"    Analyst said 2+ margin: {analyst_2plus} ({analyst_2plus/len(missed_blowouts)*100:.0f}%)")

# BET vs PASS cover rate by analyst margin
print("\n  Cover rate: BET vs PASS by analyst margin:")
for m in sorted(rdf["analyst_margin"].unique()):
    sub = rdf[rdf["analyst_margin"] == m]
    bets_sub = sub[sub["final_action"] == "BET"]
    pass_sub = sub[sub["final_action"] == "PASS"]
    bet_cr = bets_sub["fav_covers"].mean() if len(bets_sub) > 0 else 0
    pass_cr = pass_sub["fav_covers"].mean() if len(pass_sub) > 0 else 0
    print(f"    margin={m}: BET cover {bet_cr*100:.0f}% ({len(bets_sub)}), "
          f"PASS cover {pass_cr*100:.0f}% ({len(pass_sub)})")
