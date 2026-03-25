"""Favorite-side strategy exploration: ML, RL -1.5, contrarian, divergence.

Three angles of attack:
  1. Fav RL -1.5 (win by 2+) — higher odds, M2 regime alignment
  2. Contrarian favorites (model value + visible weakness)
  3. Model divergence as standalone signal

Usage:
    python scripts/favorite_dive.py
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


def eval_strat(data, name, won_col, odds_col):
    """Evaluate a strategy: returns dict of metrics."""
    n = len(data)
    if n < 15:
        return None
    won = data[won_col].values.astype(float)
    odds = data[odds_col].values
    pnl = np.where(won, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    wr = won.mean()
    avg_odds = odds.mean()
    ml = max_ls(won == 0)

    cum = np.cumsum(pnl)
    bk = 10000 + cum
    pk = np.maximum.accumulate(bk)
    mdd = ((pk - bk) / pk * 100).max()

    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1
    sb = ev / std if std > 0 else 0
    bps = n / data["season"].nunique() if data["season"].nunique() > 0 else n
    sharpe = sb * np.sqrt(bps)

    b = avg_odds - 1
    kelly = (wr * b - (1 - wr)) / b if b > 0 else 0
    kelly = max(0, kelly) / 2

    season_rois = []
    for s in sorted(data["season"].unique()):
        sm = data["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(won[sm.values], (odds[sm.values] - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "filter": name, "bets": n, "bps": n / data["season"].nunique(),
        "wr": wr, "avg_odds": avg_odds, "roi": roi, "max_ls": ml, "max_dd": mdd,
        "sharpe": sharpe, "kelly_half": kelly,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'='*120}")
    print(title)
    print(f"{'='*120}")
    h = (f"{'Filter':<58} {'Bets':>5} {'B/S':>4} {'WR':>6} {'Odds':>5} "
         f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>6} {'K/2':>6} {'Flds':>6}")
    print(h)
    print("-" * 120)
    for r in results:
        if r is None:
            continue
        print(
            f"  {r['filter']:<56} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['wr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['max_ls']:5d} {r['max_dd']:5.1f}% "
            f"{r['sharpe']:5.3f} {r['kelly_half']*100:5.2f}% {r['folds_pos']:>6}"
        )


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def build_dataset():
    """Build full dataset with model predictions, features, RL cover."""
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

    # Merge features back
    mk = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

    # Derived columns
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0
    df["fav_decimal"] = np.where(
        df["fav_is_home"], df["home_decimal_odds"], df["away_decimal_odds"]
    )
    df["dog_decimal"] = np.where(
        df["fav_is_home"], df["away_decimal_odds"], df["home_decimal_odds"]
    )

    # RL cover (favorite perspective)
    df["margin_home"] = df["home_final"] - df["away_final"]
    df["fav_margin_abs"] = df["fav_margin"]
    df["fav_covers_rl"] = df["fav_margin"] >= 2  # Fav wins by 2+

    # RL odds for favorite
    # home_run_line_odds is for the home side; need to figure out which side is fav
    if "home_run_line" in df.columns and "home_run_line_odds" in df.columns:
        rl_valid = df["home_run_line"].isin([-1.5, 1.5])
        # Home fav: home is -1.5, use home_run_line_odds
        # Away fav: away is -1.5, need away_run_line_odds
        df["fav_rl_odds"] = np.nan

        # Home favorite → home is -1.5 → use home RL odds
        hf_mask = df["fav_is_home"] & rl_valid & df["home_run_line_odds"].notna()
        df.loc[hf_mask, "fav_rl_odds"] = df.loc[hf_mask, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if x != 0 else np.nan
        )

        # Away favorite → away is -1.5 → use away RL odds if available
        if "away_run_line_odds" in df.columns:
            af_mask = ~df["fav_is_home"] & rl_valid & df["away_run_line_odds"].notna()
            df.loc[af_mask, "fav_rl_odds"] = df.loc[af_mask, "away_run_line_odds"].apply(
                lambda x: american_to_decimal(x) if x != 0 else np.nan
            )
    else:
        df["fav_rl_odds"] = np.nan

    # Model divergence signals
    if "pred_M3" in df.columns and "pred_M4" in df.columns and "pred_M0" in df.columns and "pred_M2" in df.columns:
        df["m34_vs_m02"] = (df["pred_M3"] + df["pred_M4"]) / 2 - (df["pred_M0"] + df["pred_M2"]) / 2
        df["m4_edge"] = df["closing_decimal_odds_favorite"] - df["pred_M4"]
        df["m2_edge"] = df["closing_decimal_odds_favorite"] - df["pred_M2"]

    df["month"] = pd.to_datetime(df["date"]).dt.month

    print(f"Dataset: {len(df)} games, {df['season'].nunique()} seasons")
    return df


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section1_fav_ml_baseline(df):
    """Section 1: Favorite ML baseline."""
    fav = df.copy()
    n = len(fav)
    wr = fav["fav_won"].mean()
    pnl = np.where(fav["fav_won"], (fav["fav_decimal"] - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100

    print(f"\n{'#'*80}")
    print("SECTION 1: FAVORITE ML BASELINE")
    print(f"{'#'*80}")
    print(f"All games: {n}, WR {wr*100:.1f}%, avg odds {fav['fav_decimal'].mean():.3f}, ROI {roi:+.1f}%")

    # Monthly
    print("\n  By month:")
    for m in sorted(fav["month"].unique()):
        mb = fav[fav["month"] == m]
        nm = len(mb)
        if nm < 10:
            continue
        mwr = mb["fav_won"].mean()
        mp = np.where(mb["fav_won"], (mb["fav_decimal"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    Month {m:2d}: {nm:5d}  WR {mwr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Home vs Away fav
    print("\n  Home vs Away favorite:")
    for is_home, label in [(True, "Home fav"), (False, "Away fav")]:
        mb = fav[fav["fav_is_home"] == is_home]
        nm = len(mb)
        mwr = mb["fav_won"].mean()
        mp = np.where(mb["fav_won"], (mb["fav_decimal"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label}: {nm:5d}  WR {mwr*100:5.1f}%  avg odds {mb['fav_decimal'].mean():.3f}  ROI {mroi:+6.1f}%")

    # Edge bands
    print("\n  Edge bands (edge = actual_odds - pred_consensus):")
    for lo, hi, label in [
        (None, -0.10, "edge < -0.10 (fav very cheap)"),
        (-0.10, -0.05, "-0.10 <= edge < -0.05"),
        (-0.05, 0, "-0.05 <= edge < 0"),
        (0, 0.05, "0 <= edge < 0.05"),
        (0.05, 0.10, "0.05 <= edge < 0.10"),
        (0.10, None, "edge >= 0.10 (fav overpriced)"),
    ]:
        if lo is None:
            mask = fav["edge_consensus"] < hi
        elif hi is None:
            mask = fav["edge_consensus"] >= lo
        else:
            mask = (fav["edge_consensus"] >= lo) & (fav["edge_consensus"] < hi)
        mb = fav[mask]
        nm = len(mb)
        if nm < 10:
            continue
        mwr = mb["fav_won"].mean()
        mp = np.where(mb["fav_won"], (mb["fav_decimal"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label:<40} {nm:5d}  WR {mwr*100:5.1f}%  ROI {mroi:+6.1f}%")


def section2_fav_rl(df):
    """Section 2: Favorite RL -1.5."""
    print(f"\n{'#'*80}")
    print("SECTION 2: FAVORITE RL -1.5 (win by 2+)")
    print(f"{'#'*80}")

    rl = df[df["fav_rl_odds"].notna() & (df["fav_rl_odds"] > 1)].copy()
    print(f"Games with valid fav RL odds: {len(rl)}")
    if len(rl) < 50:
        print("  Not enough RL data. Skipping.")
        # Fallback: use ML odds as proxy for RL analysis
        print("\n  Fallback: analyzing fav_covers_rl with ML odds as proxy...")
        rl = df.copy()
        rl["fav_rl_odds"] = rl["fav_decimal"] * 1.25  # Rough proxy: RL odds ~25% higher
        print(f"  Using proxy RL odds for {len(rl)} games")

    cover_rate = rl["fav_covers_rl"].mean()
    print(f"  Cover rate (fav -1.5): {cover_rate*100:.1f}%")
    print(f"  Avg RL odds: {rl['fav_rl_odds'].mean():.3f}")

    # Baseline ROI
    pnl = np.where(rl["fav_covers_rl"], (rl["fav_rl_odds"] - 1) * 100, -100)
    roi = pnl.sum() / (len(rl) * 100) * 100
    print(f"  RL baseline ROI: {roi:+.1f}%")

    # Edge bands for RL
    print("\n  RL cover rate by edge band:")
    for lo, hi, label in [
        (None, -0.10, "edge < -0.10"),
        (-0.10, -0.05, "-0.10 <= edge < -0.05"),
        (-0.05, 0, "-0.05 <= edge < 0"),
        (0, 0.05, "0 <= edge < 0.05"),
        (0.05, None, "edge >= 0.05"),
    ]:
        if lo is None:
            mask = rl["edge_consensus"] < hi
        elif hi is None:
            mask = rl["edge_consensus"] >= lo
        else:
            mask = (rl["edge_consensus"] >= lo) & (rl["edge_consensus"] < hi)
        mb = rl[mask]
        nm = len(mb)
        if nm < 15:
            continue
        cr = mb["fav_covers_rl"].mean()
        mp = np.where(mb["fav_covers_rl"], (mb["fav_rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label:<30} {nm:5d}  cover {cr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # M2-specific edge
    if "m2_edge" in rl.columns:
        print("\n  RL cover rate by M2 edge (M2 = fav wins 2+):")
        for lo, hi, label in [
            (None, -0.10, "m2_edge < -0.10"),
            (-0.10, -0.05, "-0.10 <= m2_edge < -0.05"),
            (-0.05, 0, "-0.05 <= m2_edge < 0"),
            (0, 0.05, "0 <= m2_edge < 0.05"),
            (0.05, None, "m2_edge >= 0.05"),
        ]:
            if lo is None:
                mask = rl["m2_edge"] < hi
            elif hi is None:
                mask = rl["m2_edge"] >= lo
            else:
                mask = (rl["m2_edge"] >= lo) & (rl["m2_edge"] < hi)
            mb = rl[mask]
            nm = len(mb)
            if nm < 15:
                continue
            cr = mb["fav_covers_rl"].mean()
            mp = np.where(mb["fav_covers_rl"], (mb["fav_rl_odds"] - 1) * 100, -100)
            mroi = mp.sum() / (nm * 100) * 100
            print(f"    {label:<30} {nm:5d}  cover {cr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Sub-filter search for RL
    cheap_rl = rl[rl["edge_consensus"] < -0.05].copy()
    if len(cheap_rl) >= 30:
        candidates = {}
        candidates["fav_is_home"] = cheap_rl["fav_is_home"]
        for t in [-20, -10, 0]:
            candidates[f"elo_diff <= {t}"] = cheap_rl["elo_diff"] <= t
        for t in [0.01, 0.02, 0.03]:
            candidates[f"rpi_diff >= {t}"] = cheap_rl["rpi_diff"] >= t
        if "starter_fip_diff" in cheap_rl.columns:
            candidates["starter_fip_diff < 0"] = cheap_rl["starter_fip_diff"] < 0
            candidates["starter_fip_diff < -0.5"] = cheap_rl["starter_fip_diff"] < -0.5
        if "bp_ip_3d_home" in cheap_rl.columns:
            med = cheap_rl["bp_ip_3d_home"].median()
            candidates[f"home_bp_3d <= med ({med:.1f})"] = cheap_rl["bp_ip_3d_home"] <= med
        if "wp_last6_home" in cheap_rl.columns:
            candidates["wp_last6_home >= 0.50"] = cheap_rl["wp_last6_home"] >= 0.50
            candidates["wp_last6_home >= 0.60"] = cheap_rl["wp_last6_home"] >= 0.60
        candidates["games_played_min >= 30"] = cheap_rl["games_played_min"] >= 30
        if "m2_edge" in cheap_rl.columns:
            candidates["m2_edge < -0.05"] = cheap_rl["m2_edge"] < -0.05
            candidates["m2_edge < -0.10"] = cheap_rl["m2_edge"] < -0.10

        results = [eval_strat(cheap_rl, "RL baseline (edge<-0.05)", "fav_covers_rl", "fav_rl_odds")]
        for name, mask in candidates.items():
            r = eval_strat(cheap_rl[mask.fillna(False)], name, "fav_covers_rl", "fav_rl_odds")
            if r:
                results.append(r)
        results.sort(key=lambda x: -x["roi"])
        ptable(results, "FAV RL -1.5 SUB-FILTERS (edge < -0.05)")


def section3_contrarian(df):
    """Section 3: Contrarian favorites — model value + visible weakness."""
    print(f"\n{'#'*80}")
    print("SECTION 3: CONTRARIAN FAVORITES (weakness + model value)")
    print(f"{'#'*80}")

    fav = df.copy()

    # Define weaknesses
    weaknesses = {}
    weaknesses["elo_diff > 0 (away stronger by Elo)"] = fav["elo_diff"] > 0
    if "rpi_diff" in fav.columns:
        weaknesses["rpi_diff < 0 (fav lower RPI)"] = fav["rpi_diff"] < 0
    if "starter_fip_diff" in fav.columns:
        weaknesses["starter_fip_diff > 0 (fav pitcher worse)"] = fav["starter_fip_diff"] > 0
    if "streak_home" in fav.columns:
        weaknesses["streak_home < 0 (fav losing streak)"] = fav["streak_home"] < 0
    if "wp_last6_home" in fav.columns:
        weaknesses["wp_last6_home < 0.50 (fav cold form)"] = fav["wp_last6_home"] < 0.50

    # For each weakness x edge threshold
    print("\n  Weakness x edge depth (fav ML):")
    print(f"  {'Weakness':<45} {'Edge':>8} {'Bets':>5} {'WR':>6} {'ROI':>7} {'MaxL':>5}")
    print("  " + "-" * 85)

    for wname, wmask in weaknesses.items():
        wmask = wmask.fillna(False)
        for edge_thresh in [-0.03, -0.05, -0.07, -0.10]:
            emask = fav["edge_consensus"] < edge_thresh
            combo = fav[wmask & emask]
            n = len(combo)
            if n < 15:
                continue
            wr = combo["fav_won"].mean()
            pnl = np.where(combo["fav_won"], (combo["fav_decimal"] - 1) * 100, -100)
            roi = pnl.sum() / (n * 100) * 100
            ml = max_ls(combo.sort_values("date")["fav_won"].values == 0)
            marker = " <<<" if roi > 3 else ""
            print(f"  {wname:<45} {edge_thresh:>8.2f} {n:5d} {wr*100:5.1f}% {roi:+6.1f}% {ml:5d}{marker}")

    # Best contrarian combos: 2 weaknesses + edge
    print("\n  Two weaknesses + edge < -0.05:")
    edge_mask = fav["edge_consensus"] < -0.05
    wnames = list(weaknesses.keys())
    combo_results = []
    for w1, w2 in combinations(wnames, 2):
        m1 = weaknesses[w1].fillna(False)
        m2 = weaknesses[w2].fillna(False)
        combo = fav[m1 & m2 & edge_mask]
        r = eval_strat(combo, f"{w1[:25]} + {w2[:25]}", "fav_won", "fav_decimal")
        if r:
            combo_results.append(r)

    if combo_results:
        combo_results.sort(key=lambda x: -x["roi"])
        ptable(combo_results[:15], "CONTRARIAN 2-WEAKNESS COMBOS (edge < -0.05)")


def section4_divergence(df):
    """Section 4: Model divergence as signal."""
    print(f"\n{'#'*80}")
    print("SECTION 4: DIVERGENCE SIGNALS")
    print(f"{'#'*80}")

    fav = df.copy()

    # m34_vs_m02: negative = dominant models see lower odds = fav stronger
    if "m34_vs_m02" in fav.columns:
        print("\n  m34_vs_m02 (negative = fav stronger per dominant models):")
        for lo, hi, label in [
            (None, -0.05, "m34_vs_m02 < -0.05 (dominant strong)"),
            (-0.05, 0, "-0.05 <= m34_vs_m02 < 0"),
            (0, 0.05, "0 <= m34_vs_m02 < 0.05"),
            (0.05, None, "m34_vs_m02 >= 0.05 (upset bias)"),
        ]:
            if lo is None:
                mask = fav["m34_vs_m02"] < hi
            elif hi is None:
                mask = fav["m34_vs_m02"] >= lo
            else:
                mask = (fav["m34_vs_m02"] >= lo) & (fav["m34_vs_m02"] < hi)
            mb = fav[mask]
            nm = len(mb)
            if nm < 15:
                continue
            wr = mb["fav_won"].mean()
            pnl = np.where(mb["fav_won"], (mb["fav_decimal"] - 1) * 100, -100)
            roi = pnl.sum() / (nm * 100) * 100
            print(f"    {label:<45} {nm:5d}  WR {wr*100:5.1f}%  ROI {roi:+6.1f}%")

    # m4_edge: negative = even upset model says fav is cheap (strong confirmation)
    if "m4_edge" in fav.columns:
        print("\n  m4_edge (negative = even upset model confirms fav cheap):")
        for lo, hi, label in [
            (None, -0.10, "m4_edge < -0.10 (all models agree)"),
            (-0.10, -0.05, "-0.10 <= m4_edge < -0.05"),
            (-0.05, 0, "-0.05 <= m4_edge < 0"),
            (0, None, "m4_edge >= 0 (upset model disagrees)"),
        ]:
            if lo is None:
                mask = fav["m4_edge"] < hi
            elif hi is None:
                mask = fav["m4_edge"] >= lo
            else:
                mask = (fav["m4_edge"] >= lo) & (fav["m4_edge"] < hi)
            mb = fav[mask]
            nm = len(mb)
            if nm < 15:
                continue
            wr = mb["fav_won"].mean()
            pnl = np.where(mb["fav_won"], (mb["fav_decimal"] - 1) * 100, -100)
            roi = pnl.sum() / (nm * 100) * 100
            print(f"    {label:<45} {nm:5d}  WR {wr*100:5.1f}%  ROI {roi:+6.1f}%")

    # div_std: low = models agree, high = uncertainty
    if "div_std" in fav.columns:
        print("\n  div_std (model agreement) x edge < -0.05:")
        cheap = fav[fav["edge_consensus"] < -0.05]
        for pct, label in [(0.25, "low div (p25)"), (0.50, "med div (p50)"), (0.75, "high div (p75)")]:
            thresh = cheap["div_std"].quantile(pct)
            below = cheap[cheap["div_std"] <= thresh]
            above = cheap[cheap["div_std"] > thresh]
            for data, tag in [(below, f"div_std <= {thresh:.3f} ({label})"), (above, f"div_std > {thresh:.3f}")]:
                nm = len(data)
                if nm < 15:
                    continue
                wr = data["fav_won"].mean()
                pnl = np.where(data["fav_won"], (data["fav_decimal"] - 1) * 100, -100)
                roi = pnl.sum() / (nm * 100) * 100
                print(f"    {tag:<45} {nm:5d}  WR {wr*100:5.1f}%  ROI {roi:+6.1f}%")

    # Combined: edge < -0.05 + m34_vs_m02 < 0 + m4_edge < 0
    if "m34_vs_m02" in fav.columns and "m4_edge" in fav.columns:
        print("\n  Combined divergence filters (fav ML):")
        combos = {
            "edge<-0.05 + m34<0": (fav["edge_consensus"] < -0.05) & (fav["m34_vs_m02"] < 0),
            "edge<-0.05 + m4_edge<0": (fav["edge_consensus"] < -0.05) & (fav["m4_edge"] < 0),
            "edge<-0.05 + m34<0 + m4<0": (fav["edge_consensus"] < -0.05) & (fav["m34_vs_m02"] < 0) & (fav["m4_edge"] < 0),
            "edge<-0.05 + m34<-0.03": (fav["edge_consensus"] < -0.05) & (fav["m34_vs_m02"] < -0.03),
            "edge<-0.07 + m4_edge<-0.05": (fav["edge_consensus"] < -0.07) & (fav["m4_edge"] < -0.05),
        }
        results = []
        for name, mask in combos.items():
            r = eval_strat(fav[mask], name, "fav_won", "fav_decimal")
            if r:
                results.append(r)
        results.sort(key=lambda x: -x["roi"])
        ptable(results, "DIVERGENCE COMBO FILTERS (fav ML)")


def section5_summary(df):
    """Section 5: Summary — best candidates across all sections."""
    print(f"\n{'#'*80}")
    print("SECTION 5: SUMMARY")
    print(f"{'#'*80}")

    fav = df.copy()

    # Collect the most promising strategies from each section
    strats = {}

    # ML candidates
    for edge in [-0.05, -0.07, -0.10]:
        mask = fav["edge_consensus"] < edge
        strats[f"Fav ML (edge<{edge})"] = ("fav_won", "fav_decimal", mask)

    # RL candidates (if available)
    rl_mask = fav["fav_rl_odds"].notna() & (fav["fav_rl_odds"] > 1)
    if rl_mask.sum() > 50:
        for edge in [-0.05, -0.07]:
            mask = rl_mask & (fav["edge_consensus"] < edge)
            strats[f"Fav RL -1.5 (edge<{edge})"] = ("fav_covers_rl", "fav_rl_odds", mask)

    # Contrarian
    if "starter_fip_diff" in fav.columns:
        mask = (fav["edge_consensus"] < -0.05) & (fav["starter_fip_diff"] > 0)
        strats["Contrarian: fip>0 + edge<-0.05"] = ("fav_won", "fav_decimal", mask)

    mask = (fav["edge_consensus"] < -0.05) & (fav["elo_diff"] > 0)
    strats["Contrarian: elo>0 + edge<-0.05"] = ("fav_won", "fav_decimal", mask)

    # Divergence
    if "m4_edge" in fav.columns:
        mask = (fav["edge_consensus"] < -0.05) & (fav["m4_edge"] < 0)
        strats["Divergence: edge<-0.05 + m4<0"] = ("fav_won", "fav_decimal", mask)
        if "m34_vs_m02" in fav.columns:
            mask = (fav["edge_consensus"] < -0.05) & (fav["m34_vs_m02"] < 0) & (fav["m4_edge"] < 0)
            strats["Divergence: edge<-0.05 + m34<0 + m4<0"] = ("fav_won", "fav_decimal", mask)

    results = []
    for name, (won_col, odds_col, mask) in strats.items():
        r = eval_strat(fav[mask], name, won_col, odds_col)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["sharpe"])
    ptable(results, "ALL FAVORITE CANDIDATES (sorted by Sharpe)")

    # Best with > 50 bets and positive ROI
    viable = [r for r in results if r["roi"] > 0 and r["bets"] > 50]
    if viable:
        best = viable[0]
        rois_str = ", ".join(f"{x:+.0f}" for x in best["season_rois"])
        print(f"\n  BEST CANDIDATE: {best['filter']}")
        print(f"    {best['bets']} bets ({best['bps']:.0f}/s)  ROI {best['roi']:+.1f}%  Sharpe {best['sharpe']:.3f}")
        print(f"    Seasons: [{rois_str}]")

    # Volume comparison with S3-dual
    print(f"\n  Volume comparison:")
    print(f"    S3-dual: ~44 bets/season")
    for r in viable[:3]:
        print(f"    {r['filter']}: ~{r['bps']:.0f} bets/season")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = build_dataset()

    section1_fav_ml_baseline(df)
    section2_fav_rl(df)
    section3_contrarian(df)
    section4_divergence(df)
    section5_summary(df)


if __name__ == "__main__":
    main()
