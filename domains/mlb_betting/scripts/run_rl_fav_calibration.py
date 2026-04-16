"""Fav -1.5 RL filter calibration: TRAIN 2021-2024, TEST 2025.

Pure rule-based scan — no walk-forward model, no LLM.
Uses estimated RL odds (2.40) for 2022+ (no real RL odds in data).

Usage:
    python scripts/run_rl_fav_calibration.py
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


# ---------------------------------------------------------------------------
# Helpers (from rl_fav_analysis.py)
# ---------------------------------------------------------------------------

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
    if n < 10:
        return None
    covers = data["covers"].values.astype(float)
    odds = data["rl_odds"].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    avg_odds = odds.mean()

    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1
    bps = n / data["season"].nunique() if data["season"].nunique() > 0 else n
    sharpe = ev / std * np.sqrt(bps) if std > 0 else 0

    b = avg_odds - 1
    kelly = (cr * b - (1 - cr)) / b if b > 0 else 0
    kelly = max(0, kelly) / 2

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
        "sharpe": sharpe, "kelly_half": kelly,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'='*115}")
    print(title)
    print(f"{'='*115}")
    h = (f"{'Filter':<50} {'Bets':>5} {'B/S':>4} {'Cvr':>6} {'Odds':>5} "
         f"{'ROI':>7} {'Shrp':>6} {'K/2':>6} {'Flds':>6}")
    print(h)
    print("-" * 115)
    for r in results:
        if r is None:
            continue
        print(
            f"  {r['filter']:<48} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['cr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['sharpe']:5.3f} {r['kelly_half']*100:5.2f}% {r['folds_pos']:>6}"
        )


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def build_dataset():
    from src.features import build_spec_features

    print("Building spec features (with Retrosheet enrichment)...")
    df = build_spec_features()

    # Exclude Colorado + extreme lines
    mask = pd.Series(True, index=df.index)
    if "involves_col" in df.columns:
        mask = mask & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        mask = mask & ~df["is_extreme_line"]
    df = df[mask].copy()

    # Cover + odds
    df["covers"] = df["fav_margin"] >= 2
    df["rl_odds"] = FAV_RL_FALLBACK
    # Use real RL odds where available (2014-2021)
    if "home_run_line" in df.columns and "home_run_line_odds" in df.columns:
        from src.data_loader import american_to_decimal
        hf = df["fav_is_home"] & (df["home_run_line"] == -1.5)
        df.loc[hf, "rl_odds"] = df.loc[hf, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else FAV_RL_FALLBACK
        )
        if "away_run_line_odds" in df.columns:
            af = ~df["fav_is_home"] & (df["home_run_line"] == 1.5)
            df.loc[af, "rl_odds"] = df.loc[af, "away_run_line_odds"].apply(
                lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else FAV_RL_FALLBACK
            )

    df["month"] = pd.to_datetime(df["date"]).dt.month

    # Fav-oriented features
    flip = np.where(df["fav_is_home"], 1, -1)
    diff_cols = [
        "rpi_diff", "elo_diff", "pyth_wp_diff", "rpg_diff",
        "starter_fip_diff", "starter_whip_diff",
        "bullpen_fip_diff", "bullpen_workload_3d_diff",
        "wp_last3_diff", "wp_last6_diff", "wp_last10_diff",
        "close_game_wp_diff", "hold_rate_diff", "offense_vs_league_diff",
        "sp_wr_long_diff", "sp_ra_long_diff", "sp_ra_momentum_diff",
        "streak_diff",
    ]
    for col in diff_cols:
        if col in df.columns:
            df[f"fav_{col}"] = df[col] * flip

    for fav_col, home_col, away_col in [
        ("fav_rpg", "rpg_home", "rpg_away"),
        ("fav_close_game_wp", "close_game_wp_home", "close_game_wp_away"),
        ("fav_hold_rate", "hold_rate_home", "hold_rate_away"),
        ("fav_offense_vs_league", "offense_vs_league_home", "offense_vs_league_away"),
        ("dog_bp_ip_3d", "bp_ip_3d_away", "bp_ip_3d_home"),
    ]:
        if home_col in df.columns and away_col in df.columns:
            df[fav_col] = np.where(df["fav_is_home"], df[home_col], df[away_col])

    if "home_implied_prob" in df.columns:
        df["fav_implied_prob"] = np.where(
            df["fav_is_home"], df["home_implied_prob"], df["away_implied_prob"]
        )

    if "rpg_home" in df.columns:
        df["combined_rpg"] = df["rpg_home"] + df["rpg_away"]

    print(f"Universe: {len(df)} games")
    for y in sorted(df["season"].unique()):
        s = df[df["season"] == y]
        if len(s) > 100:
            print(f"  {int(y)}: {len(s)} games, cover {s['covers'].mean()*100:.1f}%")

    return df


def build_candidates(base):
    """Build filter candidates dict."""
    candidates = {}

    if "fav_rpi_diff" in base.columns:
        for t in [0.02, 0.03, 0.04]:
            candidates[f"fav_rpi>={t}"] = base["fav_rpi_diff"] >= t

    if "fav_elo_diff" in base.columns:
        for t in [20, 30, 40]:
            candidates[f"fav_elo>={t}"] = base["fav_elo_diff"] >= t

    if "fav_pyth_wp_diff" in base.columns:
        for t in [0.03, 0.05, 0.07]:
            candidates[f"fav_pyth>={t}"] = base["fav_pyth_wp_diff"] >= t

    if "fav_starter_fip_diff" in base.columns:
        for t in [0, -0.3, -0.5]:
            candidates[f"fav_fip<={t}"] = base["fav_starter_fip_diff"] <= t

    if "fav_starter_whip_diff" in base.columns:
        for t in [0, -0.10, -0.20]:
            candidates[f"fav_whip<={t}"] = base["fav_starter_whip_diff"] <= t

    if "fav_sp_wr_long_diff" in base.columns:
        for t in [0.05, 0.10, 0.15]:
            candidates[f"fav_sp_wr>={t}"] = base["fav_sp_wr_long_diff"] >= t

    if "fav_sp_ra_long_diff" in base.columns:
        for t in [0, -0.5]:
            candidates[f"fav_sp_ra<={t}"] = base["fav_sp_ra_long_diff"] <= t

    if "fav_offense_vs_league" in base.columns:
        for t in [1.00, 1.05, 1.10]:
            candidates[f"fav_off>={t}"] = base["fav_offense_vs_league"] >= t

    if "fav_rpg" in base.columns:
        for t in [4.0, 4.5, 5.0]:
            candidates[f"fav_rpg>={t}"] = base["fav_rpg"] >= t

    if "fav_close_game_wp" in base.columns:
        for t in [0.55, 0.50, 0.45, 0.40]:
            candidates[f"fav_cwp<={t}"] = base["fav_close_game_wp"] <= t

    if "fav_hold_rate" in base.columns:
        for t in [0.70, 0.75, 0.80]:
            candidates[f"fav_hold>={t}"] = base["fav_hold_rate"] >= t

    if "dog_bp_ip_3d" in base.columns:
        med = base["dog_bp_ip_3d"].median()
        p75 = base["dog_bp_ip_3d"].quantile(0.75)
        candidates[f"dog_bp>med({med:.0f})"] = base["dog_bp_ip_3d"] > med
        candidates[f"dog_bp>p75({p75:.0f})"] = base["dog_bp_ip_3d"] > p75

    if "fav_sp_ra_momentum_diff" in base.columns:
        for t in [0, -0.2]:
            candidates[f"fav_sp_mom<={t}"] = base["fav_sp_ra_momentum_diff"] <= t

    if "fav_implied_prob" in base.columns:
        candidates["impl55-65%"] = (base["fav_implied_prob"] >= 0.55) & (base["fav_implied_prob"] < 0.65)
        candidates["impl60-70%"] = (base["fav_implied_prob"] >= 0.60) & (base["fav_implied_prob"] < 0.70)
        candidates["impl65-75%"] = (base["fav_implied_prob"] >= 0.65) & (base["fav_implied_prob"] < 0.75)
        candidates["impl<70%"] = base["fav_implied_prob"] < 0.70

    if "fav_wp_last3_diff" in base.columns:
        for t in [0, 0.10, 0.20]:
            candidates[f"fav_wp3>={t}"] = base["fav_wp_last3_diff"] >= t

    if "fav_streak_diff" in base.columns:
        for t in [0, 1, 2]:
            candidates[f"fav_streak>={t}"] = base["fav_streak_diff"] >= t

    if "fav_bullpen_fip_diff" in base.columns:
        for t in [0, -0.3]:
            candidates[f"fav_bp_fip<={t}"] = base["fav_bullpen_fip_diff"] <= t

    if "combined_rpg" in base.columns:
        for t in [8.5, 9.0, 9.5]:
            candidates[f"comb_rpg>={t}"] = base["combined_rpg"] >= t

    if "games_played_min" in base.columns:
        candidates["gp>=30"] = base["games_played_min"] >= 30

    return candidates


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section1_baseline(df):
    print(f"\n{'#'*80}")
    print("SECTION 1: BASELINE")
    print(f"{'#'*80}")

    for label, sub in [("TRAIN 2021-2024", df[df["season"].isin([2021,2022,2023,2024])]),
                       ("TEST 2025", df[df["season"]==2025])]:
        n = len(sub)
        cr = sub["covers"].mean()
        be = 1 / sub["rl_odds"].mean() * 100
        print(f"\n  {label}: {n} games, cover {cr*100:.1f}%, breakeven {be:.1f}%")

        # By season
        for y in sorted(sub["season"].unique()):
            sy = sub[sub["season"]==y]
            print(f"    {int(y)}: {len(sy)} cover {sy['covers'].mean()*100:.1f}%")

        # Implied prob bands
        if "fav_implied_prob" in sub.columns:
            print(f"  Implied prob bands:")
            for lo, hi, label2 in [(0.55, 0.60, "55-60%"), (0.60, 0.65, "60-65%"),
                                   (0.65, 0.70, "65-70%"), (0.70, 0.80, "70-80%")]:
                m = (sub["fav_implied_prob"] >= lo) & (sub["fav_implied_prob"] < hi)
                ms = sub[m]
                if len(ms) >= 10:
                    print(f"    {label2}: {len(ms)} games, cover {ms['covers'].mean()*100:.1f}%")


def section2_singles(train):
    print(f"\n{'#'*80}")
    print("SECTION 2: SINGLE FILTERS (TRAIN 2021-2024)")
    print(f"{'#'*80}")

    candidates = build_candidates(train)
    results = [eval_strat(train, "BASELINE (all)")]
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_strat(train[mask], name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["roi"])
    ptable(results, "SINGLE FILTERS — TRAIN 2021-2024")
    return candidates, results


def section3_combos(train, candidates, singles):
    print(f"\n{'#'*80}")
    print("SECTION 3: 2-WAY COMBOS (TRAIN 2021-2024)")
    print(f"{'#'*80}")

    top_names = [r["filter"] for r in singles
                 if r["roi"] > 0 and r["filter"] != "BASELINE (all)"][:12]

    if len(top_names) < 2:
        print("  Not enough positive-ROI singles for combos.")
        return []

    combo_results = []
    for f1, f2 in combinations(top_names, 2):
        m1 = candidates.get(f1, pd.Series(False, index=train.index)).fillna(False)
        m2 = candidates.get(f2, pd.Series(False, index=train.index)).fillna(False)
        r = eval_strat(train[m1 & m2], f"{f1} + {f2}")
        if r:
            combo_results.append(r)

    combo_results.sort(key=lambda x: -x["roi"])
    ptable(combo_results[:20], "TOP 2-WAY COMBOS — TRAIN 2021-2024")
    return combo_results


def section4_test(df, candidates, singles, combos):
    print(f"\n{'#'*80}")
    print("SECTION 4: TEST ON 2025")
    print(f"{'#'*80}")

    test = df[df["season"] == 2025].copy()
    if len(test) == 0:
        print("  No 2025 data!")
        return

    print(f"\n  2025 baseline: {len(test)} games, cover {test['covers'].mean()*100:.1f}%")

    # Top singles
    top_singles = [r for r in singles if r["roi"] > 0 and r["filter"] != "BASELINE (all)"][:5]
    # Top combos
    top_combos = [r for r in combos if r["roi"] > 0][:5]

    test_candidates = build_candidates(test)

    print(f"\n  --- Top singles on 2025 ---")
    for r in top_singles:
        name = r["filter"]
        if name in test_candidates:
            mask = test_candidates[name].fillna(False)
            tr = eval_strat(test[mask], f"[TEST] {name}")
            if tr:
                rois = ", ".join(f"{x:+.0f}" for x in tr["season_rois"])
                print(f"  {tr['filter']:<50} {tr['bets']:4d} cvr {tr['cr']*100:5.1f}% "
                      f"ROI {tr['roi']:+6.1f}%  [{rois}]")

    print(f"\n  --- Top combos on 2025 ---")
    for r in top_combos:
        name = r["filter"]
        parts = name.split(" + ")
        mask = pd.Series(True, index=test.index)
        valid = True
        for part in parts:
            if part in test_candidates:
                mask = mask & test_candidates[part].fillna(False)
            else:
                valid = False
                break
        if not valid:
            continue
        tr = eval_strat(test[mask], f"[TEST] {name}")
        if tr:
            rois = ", ".join(f"{x:+.0f}" for x in tr["season_rois"])
            print(f"  {tr['filter']:<50} {tr['bets']:4d} cvr {tr['cr']*100:5.1f}% "
                  f"ROI {tr['roi']:+6.1f}%  [{rois}]")

    # Also test the OLD filter on 2025
    print(f"\n  --- Old filter (session 25) on 2025 ---")
    if "fav_close_game_wp" in test.columns and "fav_streak_diff" in test.columns:
        old_mask = (test["fav_close_game_wp"] <= 0.45) & (test["fav_streak_diff"] >= 0)
        old_r = eval_strat(test[old_mask.fillna(False)], "[TEST] OLD: cwp<=0.45+streak>=0")
        if old_r:
            print(f"  {old_r['filter']:<50} {old_r['bets']:4d} cvr {old_r['cr']*100:5.1f}% "
                  f"ROI {old_r['roi']:+6.1f}%")


def section5_summary(singles, combos, df):
    print(f"\n{'#'*80}")
    print("SECTION 5: SUMMARY")
    print(f"{'#'*80}")

    train = df[df["season"].isin([2021, 2022, 2023, 2024])]
    test = df[df["season"] == 2025]

    print(f"\n  TRAIN 2021-2024: {len(train)} games, cover {train['covers'].mean()*100:.1f}%")
    print(f"  TEST 2025:       {len(test)} games, cover {test['covers'].mean()*100:.1f}%")
    print(f"  Breakeven at odds 2.40: {1/2.40*100:.1f}%")

    if test["covers"].mean() < 1 / FAV_RL_FALLBACK:
        print(f"\n  WARNING: 2025 baseline ({test['covers'].mean()*100:.1f}%) is BELOW breakeven "
              f"({1/FAV_RL_FALLBACK*100:.1f}%). Fav -1.5 may be structurally unprofitable "
              f"in 2025 market conditions.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = build_dataset()

    # Filter to recent seasons only
    recent = df[df["season"].isin([2021, 2022, 2023, 2024, 2025])].copy()
    train = recent[recent["season"].isin([2021, 2022, 2023, 2024])].copy()

    section1_baseline(recent)
    candidates, singles = section2_singles(train)
    combos = section3_combos(train, candidates, singles)
    section4_test(recent, candidates, singles, combos)
    section5_summary(singles, combos, recent)


if __name__ == "__main__":
    main()
