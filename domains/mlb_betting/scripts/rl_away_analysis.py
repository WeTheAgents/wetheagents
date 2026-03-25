"""Away Run Line +1.5 strategy analysis (post-dedup, September included).

Cover condition: margin_home <= 1 (away loses by max 1 run, or wins).
Odds: away_run_line_odds if available, else estimate 1.87.

Usage:
    python scripts/rl_away_analysis.py
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

AWAY_RL_FALLBACK = 1.87
ASG_DAY = 15


# ---------------------------------------------------------------------------
# Helpers
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
    if n < 15:
        return None
    covers = data["covers"].values.astype(float)
    odds = data["rl_odds"].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    avg_odds = odds.mean()
    ml = max_ls(covers == 0)

    cum = np.cumsum(pnl)
    bk = 10000 + cum
    pk = np.maximum.accumulate(bk)
    mdd = ((pk - bk) / pk * 100).max()

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
        "filter": name, "bets": n, "bps": n / data["season"].nunique(),
        "cr": cr, "avg_odds": avg_odds, "roi": roi, "max_ls": ml, "max_dd": mdd,
        "sharpe": sharpe, "kelly_half": kelly,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'='*125}")
    print(title)
    print(f"{'='*125}")
    h = (f"{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Cvr':>6} {'Odds':>5} "
         f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>6} {'K/2':>6} {'Flds':>6}")
    print(h)
    print("-" * 125)
    for r in results:
        if r is None:
            continue
        print(
            f"  {r['filter']:<53} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['cr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['max_ls']:5d} {r['max_dd']:5.1f}% "
            f"{r['sharpe']:5.3f} {r['kelly_half']*100:5.2f}% {r['folds_pos']:>6}"
        )


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def build_dataset():
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward
    from src.data_loader import american_to_decimal

    print("Building spec features...")
    full = build_spec_features()

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    print("Running walk-forward...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    mk = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

    # Derived
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0

    if "pred_M4" in df.columns:
        df["m4_edge"] = df["closing_decimal_odds_favorite"] - df["pred_M4"]
    if "pred_M3" in df.columns and "pred_M4" in df.columns and "pred_M0" in df.columns and "pred_M2" in df.columns:
        df["m34_vs_m02"] = (df["pred_M3"] + df["pred_M4"]) / 2 - (df["pred_M0"] + df["pred_M2"]) / 2

    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["day"] = pd.to_datetime(df["date"]).dt.day
    df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (df["day"] <= ASG_DAY))

    # RL cover: away +1.5 covers when margin_home <= 1
    df["margin_home"] = df["home_final"] - df["away_final"]
    df["covers"] = df["margin_home"] <= 1

    # RL odds for away +1.5
    if "away_run_line_odds" in df.columns:
        df["rl_odds"] = df["away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    else:
        df["rl_odds"] = np.nan

    # Filter: only games where home_run_line == -1.5 (real RL, not misclassified O/U)
    if "home_run_line" in df.columns:
        rl_valid = df["home_run_line"].isin([-1.5, 1.5])
    else:
        rl_valid = pd.Series(True, index=df.index)

    # Fallback for missing RL odds
    df["rl_odds"] = df["rl_odds"].fillna(AWAY_RL_FALLBACK)

    # Dog decimal (ML odds)
    df["dog_decimal"] = np.where(
        df["fav_is_home"], df["away_decimal_odds"], df["home_decimal_odds"]
    )

    # Universe: away is underdog (home is favorite by implied prob)
    # AND valid RL data
    universe = df["fav_is_home"] & rl_valid
    rl = df[universe].copy()

    n_real = (rl["rl_odds"] != AWAY_RL_FALLBACK).sum()
    print(f"RL universe: {len(rl)} games ({n_real} with real RL odds, {len(rl)-n_real} estimated)")
    print(f"Seasons: {sorted(rl['season'].unique())}")
    return rl


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section1_baseline(df):
    print(f"\n{'#'*80}")
    print("SECTION 1: BASELINE")
    print(f"{'#'*80}")

    n = len(df)
    cr = df["covers"].mean()
    pnl = np.where(df["covers"], (df["rl_odds"] - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    print(f"All away +1.5: {n} bets, cover {cr*100:.1f}%, avg odds {df['rl_odds'].mean():.3f}, ROI {roi:+.1f}%")

    # Edge bands
    print("\n  Edge bands:")
    for lo, hi, label in [
        (None, -0.10, "edge < -0.10"), (-0.10, -0.07, "-0.10 <= edge < -0.07"),
        (-0.07, -0.05, "-0.07 <= edge < -0.05"), (-0.05, -0.03, "-0.05 <= edge < -0.03"),
        (-0.03, 0, "-0.03 <= edge < 0"), (0, 0.05, "0 <= edge < 0.05"),
        (0.05, None, "edge >= 0.05"),
    ]:
        if lo is None: mask = df["edge_consensus"] < hi
        elif hi is None: mask = df["edge_consensus"] >= lo
        else: mask = (df["edge_consensus"] >= lo) & (df["edge_consensus"] < hi)
        mb = df[mask]
        nm = len(mb)
        if nm < 15: continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label:<30} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Monthly
    print("\n  By month:")
    for m in sorted(df["month"].unique()):
        mb = df[df["month"] == m]
        nm = len(mb)
        if nm < 10: continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    Month {m:2d}: {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")


def section2_singles(df):
    print(f"\n{'#'*80}")
    print("SECTION 2: SINGLE FILTERS (on edge < -0.05)")
    print(f"{'#'*80}")

    # INVERTED edge for RL +1.5: edge > 0.05 works (tighter games, fav overpriced)
    base = df[df["edge_consensus"] > 0.05].copy()
    print(f"Base (edge > 0.05): {len(base)} bets")

    candidates = {}

    # RPI: for RL+1.5 we test both directions
    # Away stronger (rpi_diff <= X) AND fav with weakness (rpi_diff >= X)
    for t in [0, -0.01, -0.02]:
        candidates[f"rpi_diff <= {t} (away stronger)"] = base["rpi_diff"] <= t
    for t in [0, 0.01, 0.02]:
        candidates[f"rpi_diff >= {t} (home stronger)"] = base["rpi_diff"] >= t

    # Elo: both directions
    for t in [30, 15, 0]:
        candidates[f"elo_diff <= {t}"] = base["elo_diff"] <= t
    for t in [0, 10, 20]:
        candidates[f"elo_diff >= {t} (home stronger)"] = base["elo_diff"] >= t

    # Pyth: both directions
    if "pyth_wp_diff" in base.columns:
        for t in [0.05, 0.03, 0]:
            candidates[f"pyth_wp_diff <= {t}"] = base["pyth_wp_diff"] <= t
        for t in [0, 0.03]:
            candidates[f"pyth_wp_diff >= {t} (home stronger)"] = base["pyth_wp_diff"] >= t

    # Form
    if "wp_last6_away" in base.columns:
        candidates["wp_last6_away >= 0.45"] = base["wp_last6_away"] >= 0.45
        candidates["wp_last6_away >= 0.50"] = base["wp_last6_away"] >= 0.50
    if "streak_away" in base.columns:
        candidates["streak_away >= 0"] = base["streak_away"] >= 0
        candidates["streak_away >= 1"] = base["streak_away"] >= 1

    # Pitcher
    if "starter_fip_diff" in base.columns:
        candidates["starter_fip_diff > 0 (home P worse)"] = base["starter_fip_diff"] > 0
        candidates["starter_fip_diff > 0.5"] = base["starter_fip_diff"] > 0.5
    if "away_sp_ra_short" in base.columns:
        med = base["away_sp_ra_short"].median()
        candidates[f"away_sp_ra <= med ({med:.2f})"] = base["away_sp_ra_short"] <= med
    if "home_sp_ra_short" in base.columns:
        med = base["home_sp_ra_short"].median()
        candidates[f"home_sp_ra >= med ({med:.2f})"] = base["home_sp_ra_short"] >= med

    # Bullpen (KEY from session 7)
    if "bp_ip_3d_home" in base.columns:
        med = base["bp_ip_3d_home"].median()
        p75 = base["bp_ip_3d_home"].quantile(0.75)
        candidates[f"home_bp_3d > med ({med:.1f})"] = base["bp_ip_3d_home"] > med
        candidates[f"home_bp_3d > p75 ({p75:.1f})"] = base["bp_ip_3d_home"] > p75
    if "bullpen_fip_diff" in base.columns:
        candidates["bullpen_fip_diff > 0 (home BP worse)"] = base["bullpen_fip_diff"] > 0

    # Odds band
    if "dog_decimal" in base.columns:
        for t in [2.30, 2.50, 3.00]:
            candidates[f"dog_decimal <= {t}"] = base["dog_decimal"] <= t

    # Model signals (for RL +1.5: fav overpriced direction)
    if "m34_vs_m02" in base.columns:
        candidates["m34_vs_m02 > 0 (upset models)"] = base["m34_vs_m02"] > 0
        candidates["m34_vs_m02 < 0 (dominant models)"] = base["m34_vs_m02"] < 0
    if "m4_edge" in base.columns:
        candidates["m4_edge > 0 (upset model: fav overprice)"] = base["m4_edge"] > 0
        candidates["m4_edge > 0.05"] = base["m4_edge"] > 0.05
    if "div_std" in base.columns:
        med = base["div_std"].median()
        candidates[f"div_std > med ({med:.4f})"] = base["div_std"] > med
        candidates[f"div_std <= med"] = base["div_std"] <= med

    # Deeper edge thresholds
    candidates["edge > 0.07"] = base["edge_consensus"] > 0.07
    candidates["edge > 0.10"] = base["edge_consensus"] > 0.10
    candidates["edge > 0.15"] = base["edge_consensus"] > 0.15

    # GP
    candidates["games_played >= 30"] = base["games_played_min"] >= 30

    # Half season
    candidates["is_first_half"] = base["is_first_half"]
    candidates["is_second_half"] = ~base["is_first_half"]

    results = [eval_strat(base, "BASE: edge > 0.05")]
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_strat(base[mask], name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["roi"])
    ptable(results, "SINGLE FILTERS ON edge < -0.05")
    return base, candidates, results


def section3_combos(base, candidates, single_results):
    print(f"\n{'#'*80}")
    print("SECTION 3: 2-WAY COMBOS")
    print(f"{'#'*80}")

    top_names = [r["filter"] for r in single_results
                 if r["roi"] > 0 and r["filter"] != "BASE: edge > 0.05"][:12]

    if len(top_names) < 2:
        print("  Not enough positive-ROI singles for combos.")
        return []

    combo_results = []
    for f1, f2 in combinations(top_names, 2):
        m1 = candidates.get(f1, pd.Series(False, index=base.index)).fillna(False)
        m2 = candidates.get(f2, pd.Series(False, index=base.index)).fillna(False)
        r = eval_strat(base[m1 & m2], f"{f1} + {f2}")
        if r:
            combo_results.append(r)

    combo_results.sort(key=lambda x: -x["roi"])
    ptable(combo_results[:20], "TOP 2-WAY COMBOS (edge < -0.05)")
    return combo_results


def section4_dual_regime(df):
    print(f"\n{'#'*80}")
    print("SECTION 4: DUAL-REGIME (1H strict / 2H base)")
    print(f"{'#'*80}")

    base_mask = df["edge_consensus"] > 0.05
    base = df[base_mask].copy()

    # Identify top filters for 1H and 2H separately
    h1 = base[base["is_first_half"]]
    h2 = base[~base["is_first_half"]]

    print(f"\n  1H (pre-ASG): {len(h1)} bets")
    r1 = eval_strat(h1, "1H base (edge>0.05)")
    if r1:
        print(f"    Cover {r1['cr']*100:.1f}%, ROI {r1['roi']:+.1f}%, Sharpe {r1['sharpe']:.3f}")

    print(f"  2H (post-ASG): {len(h2)} bets")
    r2 = eval_strat(h2, "2H base (edge>0.05)")
    if r2:
        print(f"    Cover {r2['cr']*100:.1f}%, ROI {r2['roi']:+.1f}%, Sharpe {r2['sharpe']:.3f}")

    # Test strict 1H filters
    strict_configs = {}
    if "rpi_diff" in base.columns:
        strict_configs["1H: rpi<=-0.01"] = base["rpi_diff"] <= -0.01
    if "elo_diff" in base.columns:
        strict_configs["1H: elo<=15"] = base["elo_diff"] <= 15
    if "bp_ip_3d_home" in base.columns:
        med = base["bp_ip_3d_home"].median()
        strict_configs[f"1H: bp_3d>med"] = base["bp_ip_3d_home"] > med
    if "starter_fip_diff" in base.columns:
        strict_configs["1H: fip>0"] = base["starter_fip_diff"] > 0

    # Dual-regime combos
    results = []
    for sn, smask in strict_configs.items():
        smask = smask.fillna(False)
        h1_strict = h1[smask.reindex(h1.index, fill_value=False)]
        combined = pd.concat([h1_strict, h2])
        r = eval_strat(combined, f"{sn} | 2H base")
        if r:
            results.append(r)

    # Also test strict combos for 1H
    strict_pairs = list(combinations(strict_configs.keys(), 2))
    for s1, s2 in strict_pairs[:10]:
        m1 = strict_configs[s1].fillna(False)
        m2 = strict_configs[s2].fillna(False)
        h1_strict = h1[m1.reindex(h1.index, fill_value=False) & m2.reindex(h1.index, fill_value=False)]
        combined = pd.concat([h1_strict, h2])
        r = eval_strat(combined, f"{s1}+{s2} | 2H base")
        if r:
            results.append(r)

    if results:
        results.sort(key=lambda x: -x["sharpe"])
        ptable(results, "DUAL-REGIME CONFIGURATIONS")

    return results


def section5_summary(all_results):
    print(f"\n{'#'*80}")
    print("SECTION 5: SUMMARY")
    print(f"{'#'*80}")

    viable = []
    for r in all_results:
        if r is None:
            continue
        if r["roi"] > 0 and r["bets"] >= 30:
            folds = r["folds_pos"].split("/")
            if len(folds) == 2 and int(folds[0]) >= 4:
                viable.append(r)

    viable.sort(key=lambda x: -x["sharpe"])
    ptable(viable[:15], "VIABLE STRATEGIES (ROI>0, bets>=30, folds>=4)")

    if viable:
        best = viable[0]
        rois_str = ", ".join(f"{x:+.0f}" for x in best["season_rois"])
        print(f"\n  BEST: {best['filter']}")
        print(f"    {best['bets']} bets ({best['bps']:.0f}/s)  Cover {best['cr']*100:.1f}%  ROI {best['roi']:+.1f}%")
        print(f"    Sharpe {best['sharpe']:.3f}  Kelly/2 {best['kelly_half']*100:.2f}%  MaxL {best['max_ls']}")
        print(f"    Seasons: [{rois_str}]")

    print(f"\n  Context (other systems):")
    print(f"    S3-dual (away ML): ~44 bets/season, +17.9% ROI, Sharpe 0.98")
    if viable:
        print(f"    RL +1.5 best: ~{viable[0]['bps']:.0f} bets/season, {viable[0]['roi']:+.1f}% ROI, Sharpe {viable[0]['sharpe']:.3f}")

    return viable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = build_dataset()
    section1_baseline(df)
    base, candidates, singles = section2_singles(df)
    combos = section3_combos(base, candidates, singles)
    duals = section4_dual_regime(df)

    all_results = singles + combos + duals
    section5_summary(all_results)


if __name__ == "__main__":
    main()
