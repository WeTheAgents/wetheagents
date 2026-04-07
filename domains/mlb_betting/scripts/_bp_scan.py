"""Bullpen-focused filter scan for Away +1.5 (2014+ only)."""

import sys
import warnings
import logging
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd
from scripts.run_rl_calibration import build_rl_data


def max_ls(outcomes):
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def eval_strat(data, name):
    n = len(data)
    if n < 20:
        return None
    covers = data["covers"].values.astype(float)
    odds = data["rl_odds"].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    avg_odds = odds.mean()
    bps = n / data["season"].nunique()
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1
    sharpe = ev / std * np.sqrt(bps) if std > 0 else 0

    season_rois = []
    for s in sorted(data["season"].unique()):
        sm = data["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(covers[sm.values], (odds[sm.values] - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "filter": name, "bets": n, "bps": bps,
        "cr": cr, "avg_odds": avg_odds, "roi": roi,
        "sharpe": sharpe, "max_ls": max_ls(covers == 0),
        "folds": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'=' * 130}")
    print(title)
    print(f"{'=' * 130}")
    print(f"  {'Filter':<60} {'Bets':>5} {'B/S':>4} {'Cvr':>6} {'Odds':>5} {'ROI':>7} {'Shrp':>6} {'Flds':>6}  Seasons")
    print("-" * 130)
    for r in results:
        if r is None:
            continue
        rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
        print(
            f"  {r['filter']:<60} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['cr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['sharpe']:5.3f} {r['folds']:>6}  [{rois}]"
        )


def build_candidates(rl):
    c = {}

    # --- Home BP FIP absolute (high = bad for fav) ---
    for col, label in [
        ("bp_fip_short_home", "home_bp_fip_short"),
        ("bp_fip_long_home", "home_bp_fip_long"),
        ("bp_fip_7g_home", "home_bp_fip_7g"),
    ]:
        if col in rl.columns:
            for t in [3.5, 4.0, 4.5, 5.0, 5.5]:
                c[f"{label} >= {t}"] = rl[col] >= t

    # --- Away BP FIP absolute (low = good for dog) ---
    for col, label in [
        ("bp_fip_short_away", "away_bp_fip_short"),
        ("bp_fip_long_away", "away_bp_fip_long"),
    ]:
        if col in rl.columns:
            for t in [4.0, 3.5, 3.0]:
                c[f"{label} <= {t}"] = rl[col] <= t

    # --- BP FIP gap (home - away, positive = home worse) ---
    for col, label in [
        ("bp_fip_short_gap", "bp_fip_short_gap"),
        ("bp_fip_long_gap", "bp_fip_long_gap"),
        ("bp_fip_7g_gap", "bp_fip_7g_gap"),
        ("bullpen_fip_diff", "bullpen_fip_diff"),
    ]:
        if col in rl.columns:
            for t in [0, 0.3, 0.5, 1.0, 1.5, 2.0]:
                c[f"{label} >= {t}"] = rl[col] >= t

    # --- Home BP workload (tired) ---
    if "bp_ip_3d_home" in rl.columns:
        for t in [8, 9, 10, 11, 12, 13]:
            c[f"home_bp_3d >= {t}"] = rl["bp_ip_3d_home"] >= t

    # --- Away BP workload (rested) ---
    if "bp_ip_3d_away" in rl.columns:
        for t in [9, 8, 7, 6]:
            c[f"away_bp_3d <= {t}"] = rl["bp_ip_3d_away"] <= t

    # --- Workload gap (home - away) ---
    if "bp_workload_gap" in rl.columns:
        for t in [0, 1, 2, 3, 4, 5]:
            c[f"bp_workload_gap >= {t}"] = rl["bp_workload_gap"] >= t

    # --- Late-game metrics ---
    if "hold_rate_home" in rl.columns:
        for t in [0.70, 0.75, 0.80, 0.85]:
            c[f"fav_hold <= {t}"] = rl["hold_rate_home"] <= t
    if "hold_rate_away" in rl.columns:
        for t in [0.80, 0.85, 0.90]:
            c[f"dog_hold >= {t}"] = rl["hold_rate_away"] >= t
    if "deficit_recovery_rate_away" in rl.columns:
        for t in [0.25, 0.30, 0.35]:
            c[f"dog_recovery >= {t}"] = rl["deficit_recovery_rate_away"] >= t
    if "close_game_wp_home" in rl.columns:
        for t in [0.45, 0.50, 0.55]:
            c[f"fav_close_wp >= {t}"] = rl["close_game_wp_home"] >= t
    if "close_game_wp_away" in rl.columns:
        for t in [0.45, 0.50, 0.55]:
            c[f"dog_close_wp >= {t}"] = rl["close_game_wp_away"] >= t

    # --- Bullpen game flag ---
    if "home_is_bullpen_no_starter" in rl.columns:
        c["home_bullpen_game"] = rl["home_is_bullpen_no_starter"] == True
        c["NOT home_bullpen_game"] = rl["home_is_bullpen_no_starter"] == False

    return c


def main():
    rl = build_rl_data()
    rl = rl[rl["season"] >= 2014].copy()
    rl["rl_odds"] = rl["rl_odds_adj"]

    # Derived
    rl["bp_fip_short_gap"] = rl["bp_fip_short_home"] - rl["bp_fip_short_away"]
    rl["bp_fip_long_gap"] = rl["bp_fip_long_home"] - rl["bp_fip_long_away"]
    rl["bp_fip_7g_gap"] = rl["bp_fip_7g_home"] - rl["bp_fip_7g_away"]
    rl["bp_workload_gap"] = rl["bp_ip_3d_home"] - rl["bp_ip_3d_away"]

    print(f"\n{'#' * 80}")
    print("BULLPEN-FOCUSED SCAN (2014+ only)")
    print(f"{'#' * 80}")
    r = eval_strat(rl, "BASELINE 2014+")
    print(f"Baseline: {r['bets']} games, cover {r['cr']*100:.1f}%, "
          f"avg odds {r['avg_odds']:.3f}, ROI {r['roi']:+.1f}%")

    # --- Singles ---
    candidates = build_candidates(rl)
    results = [eval_strat(rl, "BASELINE")]
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_strat(rl[mask], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    ptable(results[:35], "SINGLE BULLPEN FILTERS (2014+)")

    # --- 2-way combos ---
    top_names = [r["filter"] for r in results
                 if r["roi"] > 0 and r["filter"] != "BASELINE"][:15]
    combo_results = []
    for f1, f2 in combinations(top_names, 2):
        m1 = candidates.get(f1, pd.Series(False, index=rl.index)).fillna(False)
        m2 = candidates.get(f2, pd.Series(False, index=rl.index)).fillna(False)
        r = eval_strat(rl[m1 & m2], f"{f1} + {f2}")
        if r:
            combo_results.append(r)
    combo_results.sort(key=lambda x: -x["roi"])
    ptable(combo_results[:20], "TOP 2-WAY BULLPEN COMBOS (2014+)")

    # --- Train/Test ---
    train = rl[rl["season"].isin([2014, 2015, 2016, 2017, 2018, 2019])].copy()
    test = rl[rl["season"].isin([2021, 2022, 2023, 2024, 2025])].copy()
    print(f"\n{'#' * 80}")
    print(f"TRAIN/TEST VALIDATION (TRAIN=2014-2019, TEST=2021-2025)")
    print(f"TRAIN: {len(train)} games, TEST: {len(test)} games")
    print(f"{'#' * 80}")

    for combo_r in combo_results[:10]:
        parts = combo_r["filter"].split(" + ")
        for label, split_df in [("TRAIN", train), ("TEST", test)]:
            sd = split_df.copy()
            sd["bp_fip_short_gap"] = sd["bp_fip_short_home"] - sd["bp_fip_short_away"]
            sd["bp_fip_long_gap"] = sd["bp_fip_long_home"] - sd["bp_fip_long_away"]
            sd["bp_fip_7g_gap"] = sd["bp_fip_7g_home"] - sd["bp_fip_7g_away"]
            sd["bp_workload_gap"] = sd["bp_ip_3d_home"] - sd["bp_ip_3d_away"]

            sc = build_candidates(sd)
            mask = pd.Series(True, index=sd.index)
            valid = True
            for part in parts:
                if part in sc:
                    mask = mask & sc[part].fillna(False)
                else:
                    valid = False
                    break
            if not valid:
                continue
            r = eval_strat(sd[mask], f"[{label}] {combo_r['filter']}")
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(
                    f"  {r['filter']:<70} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                    f"ROI {r['roi']:+6.1f}%  [{rois}]"
                )


if __name__ == "__main__":
    main()
