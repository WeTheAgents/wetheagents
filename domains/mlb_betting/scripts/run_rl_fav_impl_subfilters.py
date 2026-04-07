"""Sub-filter scan WITHIN impl 65-75% band.

TRAIN 2021-2024, TEST 2025. Finds "aggressive attackers" among moderate-strong favorites.

Usage:
    python scripts/run_rl_fav_impl_subfilters.py
"""

import sys
import warnings
import logging
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

FAV_RL_FALLBACK = 2.40


def eval_strat(data, name):
    n = len(data)
    if n < 10:
        return None
    covers = data["covers"].values.astype(float)
    odds = data["rl_odds"].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    season_rois = []
    for s in sorted(data["season"].unique()):
        sm = data["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(covers[sm.values], (odds[sm.values] - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)
    return {"filter": name, "bets": n, "cr": cr, "roi": roi,
            "folds_pos": f"{n_pos}/{len(season_rois)}", "season_rois": season_rois}


def ptable(results, title):
    print(f"\n{'='*100}")
    print(title)
    print(f"{'='*100}")
    print(f"{'Filter':<45} {'N':>4} {'Cvr':>6} {'ROI':>7} {'Flds':>6} {'Seasons'}")
    print("-" * 100)
    for r in results:
        if r is None:
            continue
        rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
        print(f"  {r['filter']:<43} {r['bets']:4d} {r['cr']*100:5.1f}% "
              f"{r['roi']:+6.1f}% {r['folds_pos']:>6}  [{rois}]")


def main():
    from src.features import build_spec_features

    print("Building features...")
    df = build_spec_features()

    mask = pd.Series(True, index=df.index)
    if "involves_col" in df.columns:
        mask = mask & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        mask = mask & ~df["is_extreme_line"]
    df = df[mask].copy()

    df["covers"] = df["fav_margin"] >= 2
    df["rl_odds"] = FAV_RL_FALLBACK
    df["month"] = pd.to_datetime(df["date"]).dt.month

    # Fav-oriented
    flip = np.where(df["fav_is_home"], 1, -1)
    for col in ["rpi_diff", "elo_diff", "pyth_wp_diff", "rpg_diff",
                "starter_fip_diff", "starter_whip_diff",
                "close_game_wp_diff", "hold_rate_diff", "offense_vs_league_diff",
                "sp_wr_long_diff", "sp_ra_long_diff", "sp_ra_momentum_diff",
                "streak_diff", "bullpen_fip_diff", "bullpen_workload_3d_diff",
                "power_rate_diff", "effective_obp_diff", "team_wrc_plus_diff"]:
        if col in df.columns:
            df[f"fav_{col}"] = df[col] * flip

    for fav_col, h, a in [
        ("fav_rpg", "rpg_home", "rpg_away"),
        ("fav_close_game_wp", "close_game_wp_home", "close_game_wp_away"),
        ("fav_hold_rate", "hold_rate_home", "hold_rate_away"),
        ("fav_offense_vs_league", "offense_vs_league_home", "offense_vs_league_away"),
        ("fav_power_rate", "power_rate_home", "power_rate_away"),
        ("fav_deficit_recovery", "deficit_recovery_rate_home", "deficit_recovery_rate_away"),
        ("dog_bp_ip_3d", "bp_ip_3d_away", "bp_ip_3d_home"),
    ]:
        if h in df.columns and a in df.columns:
            df[fav_col] = np.where(df["fav_is_home"], df[h], df[a])

    df["fav_implied_prob"] = np.where(
        df["fav_is_home"], df["home_implied_prob"], df["away_implied_prob"]
    )
    if "rpg_home" in df.columns:
        df["combined_rpg"] = df["rpg_home"] + df["rpg_away"]

    # Impl 65-75% pool
    impl_mask = (df["fav_implied_prob"] >= 0.65) & (df["fav_implied_prob"] < 0.75)
    pool = df[impl_mask].copy()

    train = pool[pool["season"].isin([2021, 2022, 2023, 2024])].copy()
    test = pool[pool["season"] == 2025].copy()

    print(f"\nimpl 65-75% pool:")
    print(f"  TRAIN 2021-2024: {len(train)} games, cover {train['covers'].mean()*100:.1f}%")
    print(f"  TEST 2025:       {len(test)} games, cover {test['covers'].mean()*100:.1f}%")

    # Build sub-filter candidates
    cands = {}

    if "fav_rpg" in train.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            cands[f"rpg>={t}"] = train["fav_rpg"] >= t

    if "fav_offense_vs_league" in train.columns:
        for t in [1.00, 1.05, 1.10, 1.15]:
            cands[f"off>={t}"] = train["fav_offense_vs_league"] >= t

    if "fav_pyth_wp_diff" in train.columns:
        for t in [0.05, 0.07, 0.10]:
            cands[f"pyth>={t}"] = train["fav_pyth_wp_diff"] >= t

    if "fav_rpi_diff" in train.columns:
        for t in [0.02, 0.03, 0.04]:
            cands[f"rpi>={t}"] = train["fav_rpi_diff"] >= t

    if "fav_starter_fip_diff" in train.columns:
        for t in [0, -0.3, -0.5]:
            cands[f"fip<={t}"] = train["fav_starter_fip_diff"] <= t

    if "fav_starter_whip_diff" in train.columns:
        for t in [0, -0.10]:
            cands[f"whip<={t}"] = train["fav_starter_whip_diff"] <= t

    if "fav_hold_rate" in train.columns:
        for t in [0.70, 0.75, 0.80]:
            cands[f"hold>={t}"] = train["fav_hold_rate"] >= t

    if "fav_close_game_wp" in train.columns:
        for t in [0.55, 0.50, 0.45]:
            cands[f"cwp<={t}"] = train["fav_close_game_wp"] <= t

    if "combined_rpg" in train.columns:
        for t in [8.5, 9.0, 9.5]:
            cands[f"crpg>={t}"] = train["combined_rpg"] >= t

    if "fav_streak_diff" in train.columns:
        for t in [0, 1]:
            cands[f"streak>={t}"] = train["fav_streak_diff"] >= t

    if "dog_bp_ip_3d" in train.columns:
        med = train["dog_bp_ip_3d"].median()
        cands[f"dog_bp>med"] = train["dog_bp_ip_3d"] > med

    if "fav_sp_ra_momentum_diff" in train.columns:
        cands["sp_mom<=0"] = train["fav_sp_ra_momentum_diff"] <= 0

    if "fav_bullpen_fip_diff" in train.columns:
        cands["bp_fip<=0"] = train["fav_bullpen_fip_diff"] <= 0

    if "fav_wp_last3_diff" in train.columns:
        cands["wp3>=0"] = train["fav_wp_last3_diff"] >= 0

    # === ATTACK QUALITY METRICS ===

    # Power rate: multi-run innings / scoring innings (explosiveness)
    if "fav_power_rate" in train.columns:
        for t in [0.42, 0.45, 0.48, 0.50, 0.52]:
            cands[f"pwr>={t}"] = train["fav_power_rate"] >= t

    # Effective OBP diff (lineup vs opposing pitcher hand)
    if "fav_effective_obp_diff" in train.columns:
        for t in [0, 0.01, 0.02, 0.03]:
            cands[f"eobp>={t}"] = train["fav_effective_obp_diff"] >= t

    # wRC+ diff (season batting quality)
    if "fav_team_wrc_plus_diff" in train.columns:
        for t in [0, 5, 10]:
            cands[f"wrc+>={t}"] = train["fav_team_wrc_plus_diff"] >= t

    # Power rate diff (fav more explosive than dog)
    if "fav_power_rate_diff" in train.columns:
        for t in [0, 0.03, 0.05]:
            cands[f"pwr_d>={t}"] = train["fav_power_rate_diff"] >= t

    # Deficit recovery (comeback ability)
    if "fav_deficit_recovery" in train.columns:
        for t in [0.20, 0.25]:
            cands[f"recov>={t}"] = train["fav_deficit_recovery"] >= t

    # Singles on TRAIN
    results = [eval_strat(train, "BASE (impl65-75%)")]
    for name, mask in cands.items():
        r = eval_strat(train[mask.fillna(False)], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    ptable(results, "SINGLE SUB-FILTERS WITHIN impl 65-75% — TRAIN 2021-2024")

    # Combos
    top_names = [r["filter"] for r in results
                 if r["roi"] > results[0]["roi"] and r["filter"] != "BASE (impl65-75%)"][:10]
    # If none beat base, take top 8 by ROI
    if len(top_names) < 2:
        top_names = [r["filter"] for r in results if r["filter"] != "BASE (impl65-75%)"][:8]

    combo_results = []
    if len(top_names) >= 2:
        for f1, f2 in combinations(top_names, 2):
            m1 = cands.get(f1, pd.Series(False, index=train.index)).fillna(False)
            m2 = cands.get(f2, pd.Series(False, index=train.index)).fillna(False)
            r = eval_strat(train[m1 & m2], f"{f1}+{f2}")
            if r:
                combo_results.append(r)
        combo_results.sort(key=lambda x: -x["roi"])
        ptable(combo_results[:15], "TOP COMBOS WITHIN impl 65-75% — TRAIN 2021-2024")

    # TEST on 2025
    print(f"\n{'='*100}")
    print("TEST ON 2025")
    print(f"{'='*100}")
    print(f"  Baseline: {len(test)} games, cover {test['covers'].mean()*100:.1f}%\n")

    test_cands = {}
    for name in cands:
        # Rebuild masks on test data
        if "rpg>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_rpg"] >= t
        elif "off>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_offense_vs_league"] >= t
        elif "pyth>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_pyth_wp_diff"] >= t
        elif "rpi>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_rpi_diff"] >= t
        elif "fip<=" in name:
            t = float(name.split("<=")[1])
            test_cands[name] = test["fav_starter_fip_diff"] <= t
        elif "whip<=" in name:
            t = float(name.split("<=")[1])
            test_cands[name] = test["fav_starter_whip_diff"] <= t
        elif "hold>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_hold_rate"] >= t
        elif "cwp<=" in name:
            t = float(name.split("<=")[1])
            test_cands[name] = test["fav_close_game_wp"] <= t
        elif "crpg>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["combined_rpg"] >= t
        elif "streak>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_streak_diff"] >= t
        elif name == "dog_bp>med":
            test_cands[name] = test["dog_bp_ip_3d"] > test["dog_bp_ip_3d"].median()
        elif name == "sp_mom<=0":
            test_cands[name] = test["fav_sp_ra_momentum_diff"] <= 0
        elif name == "bp_fip<=0":
            test_cands[name] = test["fav_bullpen_fip_diff"] <= 0
        elif name == "wp3>=0":
            test_cands[name] = test["fav_wp_last3_diff"] >= 0
        # Attack quality metrics
        elif "pwr>=" in name and "pwr_d" not in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_power_rate"] >= t
        elif "pwr_d>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_power_rate_diff"] >= t
        elif "eobp>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_effective_obp_diff"] >= t
        elif "wrc+>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_team_wrc_plus_diff"] >= t
        elif "recov>=" in name:
            t = float(name.split(">=")[1])
            test_cands[name] = test["fav_deficit_recovery"] >= t

    # Top 8 singles on test
    for r in results[:8]:
        name = r["filter"]
        if name == "BASE (impl65-75%)":
            continue
        if name in test_cands:
            tr = eval_strat(test[test_cands[name].fillna(False)], f"[TEST] {name}")
            if tr:
                rois = ", ".join(f"{x:+.0f}" for x in tr["season_rois"])
                print(f"  {tr['filter']:<43} {tr['bets']:4d} cvr {tr['cr']*100:5.1f}% "
                      f"ROI {tr['roi']:+6.1f}%  [{rois}]")

    # Top 5 combos on test
    if combo_results:
        print()
        for r in combo_results[:5]:
            name = r["filter"]
            parts = name.split("+")
            mask = pd.Series(True, index=test.index)
            valid = True
            for p in parts:
                if p in test_cands:
                    mask = mask & test_cands[p].fillna(False)
                else:
                    valid = False
                    break
            if not valid:
                continue
            tr = eval_strat(test[mask], f"[TEST] {name}")
            if tr:
                rois = ", ".join(f"{x:+.0f}" for x in tr["season_rois"])
                print(f"  {tr['filter']:<43} {tr['bets']:4d} cvr {tr['cr']*100:5.1f}% "
                      f"ROI {tr['roi']:+6.1f}%  [{rois}]")


if __name__ == "__main__":
    main()
