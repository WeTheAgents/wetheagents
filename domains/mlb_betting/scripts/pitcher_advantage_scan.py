"""Pitcher-advantage filter scan for Away +1.5 (2014+, excluding bullpen days).

Explores the spectrum between extreme bullpen-day signal (Tier 1) and baseline.
Hypothesis: away underdog covers at elevated rates when they have a significantly
better starter AND the home bullpen is weak/tired.

Usage:
    python scripts/pitcher_advantage_scan.py
"""

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

TRAIN_SEASONS = [2014, 2015, 2016, 2017, 2018, 2019]
TEST_SEASONS = [2021, 2022, 2023, 2024, 2025]


def max_ls(outcomes):
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def eval_strat(data, name, min_bets=20):
    n = len(data)
    if n < min_bets:
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


# ── Derived columns ────────────────────────────────────────────────────────────

def add_derived(rl):
    """Add derived pitcher-advantage columns."""
    # Starter FIP diff (long window — more stable)
    if "home_sp_fip_long" in rl.columns and "away_sp_fip_long" in rl.columns:
        rl["starter_fip_long_diff"] = rl["home_sp_fip_long"] - rl["away_sp_fip_long"]

    # Starter WHIP diff (long)
    if "home_sp_whip_long" in rl.columns and "away_sp_whip_long" in rl.columns:
        rl["starter_whip_long_diff"] = rl["home_sp_whip_long"] - rl["away_sp_whip_long"]

    # Starter depth diff (negative = away goes deeper)
    if "home_sp_ip_per_start_long" in rl.columns and "away_sp_ip_per_start_long" in rl.columns:
        rl["starter_depth_diff"] = rl["home_sp_ip_per_start_long"] - rl["away_sp_ip_per_start_long"]

    # Bullpen gaps
    if "bp_fip_short_home" in rl.columns and "bp_fip_short_away" in rl.columns:
        rl["bp_fip_short_gap"] = rl["bp_fip_short_home"] - rl["bp_fip_short_away"]
    if "bp_fip_long_home" in rl.columns and "bp_fip_long_away" in rl.columns:
        rl["bp_fip_long_gap"] = rl["bp_fip_long_home"] - rl["bp_fip_long_away"]
    if "bp_fip_7g_home" in rl.columns and "bp_fip_7g_away" in rl.columns:
        rl["bp_fip_7g_gap"] = rl["bp_fip_7g_home"] - rl["bp_fip_7g_away"]
    if "bp_ip_3d_home" in rl.columns and "bp_ip_3d_away" in rl.columns:
        rl["bp_workload_gap"] = rl["bp_ip_3d_home"] - rl["bp_ip_3d_away"]


# ── Filter builder ──────────────────────────────────────────────────────────────

def build_filters(rl):
    c = {}

    # === A. Starter FIP mismatch (positive = home worse) ===
    if "starter_fip_diff" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0, 1.5]:
            c[f"fip_short_diff >= {t}"] = rl["starter_fip_diff"] >= t
    if "starter_fip_long_diff" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0, 1.5]:
            c[f"fip_long_diff >= {t}"] = rl["starter_fip_long_diff"] >= t

    # === B. Home starter weakness (absolute) ===
    if "home_sp_fip_long" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"home_fip_long >= {t}"] = rl["home_sp_fip_long"] >= t
    if "home_sp_fip_short" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"home_fip_short >= {t}"] = rl["home_sp_fip_short"] >= t
    if "home_sp_whip_long" in rl.columns:
        for t in [1.3, 1.4, 1.5, 1.6]:
            c[f"home_whip_long >= {t}"] = rl["home_sp_whip_long"] >= t
    if "home_sp_ra_long" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"home_ra_long >= {t}"] = rl["home_sp_ra_long"] >= t

    # === C. Away starter quality (absolute) ===
    if "away_sp_fip_long" in rl.columns:
        for t in [3.5, 3.8, 4.0, 4.3]:
            c[f"away_fip_long <= {t}"] = rl["away_sp_fip_long"] <= t
    if "away_sp_fip_short" in rl.columns:
        for t in [3.5, 3.8, 4.0]:
            c[f"away_fip_short <= {t}"] = rl["away_sp_fip_short"] <= t
    if "away_sp_ip_per_start_long" in rl.columns:
        for t in [5.0, 5.5, 6.0]:
            c[f"away_depth_long >= {t}"] = rl["away_sp_ip_per_start_long"] >= t
    if "away_sp_ra_long" in rl.columns:
        for t in [3.5, 4.0, 4.5]:
            c[f"away_ra_long <= {t}"] = rl["away_sp_ra_long"] <= t

    # === D. Home bullpen weakness ===
    if "bp_fip_short_home" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"home_bp_fip_short >= {t}"] = rl["bp_fip_short_home"] >= t
    if "bp_fip_long_home" in rl.columns:
        for t in [4.0, 4.5, 5.0]:
            c[f"home_bp_fip_long >= {t}"] = rl["bp_fip_long_home"] >= t
    if "bp_ip_3d_home" in rl.columns:
        for t in [8, 10, 12, 14]:
            c[f"home_bp_3d >= {t}"] = rl["bp_ip_3d_home"] >= t

    # === E. Away bullpen strength ===
    if "bp_fip_short_away" in rl.columns:
        for t in [3.5, 4.0, 4.5]:
            c[f"away_bp_fip_short <= {t}"] = rl["bp_fip_short_away"] <= t
    if "bp_ip_3d_away" in rl.columns:
        for t in [6, 8, 10]:
            c[f"away_bp_3d <= {t}"] = rl["bp_ip_3d_away"] <= t

    # === F. Bullpen gap (positive = home worse) ===
    if "bullpen_fip_diff" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0, 1.5]:
            c[f"bp_fip_diff >= {t}"] = rl["bullpen_fip_diff"] >= t
    if "bp_workload_gap" in rl.columns:
        for t in [2, 3, 5, 7]:
            c[f"bp_workload_gap >= {t}"] = rl["bp_workload_gap"] >= t
    if "bp_fip_short_gap" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0]:
            c[f"bp_fip_short_gap >= {t}"] = rl["bp_fip_short_gap"] >= t

    # === G. Starter depth gap (compound + differential) ===
    if "away_sp_ip_per_start_long" in rl.columns and "home_sp_ip_per_start_long" in rl.columns:
        c["depth: away>=5.5 + home<5.0"] = (
            (rl["away_sp_ip_per_start_long"] >= 5.5)
            & (rl["home_sp_ip_per_start_long"] < 5.0)
        )
        c["depth: away>=6.0 + home<5.0"] = (
            (rl["away_sp_ip_per_start_long"] >= 6.0)
            & (rl["home_sp_ip_per_start_long"] < 5.0)
        )
        c["depth: away>=5.5 + home<5.5"] = (
            (rl["away_sp_ip_per_start_long"] >= 5.5)
            & (rl["home_sp_ip_per_start_long"] < 5.5)
        )
    if "starter_depth_diff" in rl.columns:
        for t in [-0.5, -1.0, -1.5]:
            c[f"starter_depth_diff <= {t}"] = rl["starter_depth_diff"] <= t

    return c


# ── Same-category check (avoid redundant combos) ───────────────────────────────

# Map filter name prefix → category key
_CAT_PREFIXES = [
    ("fip_short_diff", "fip_short_diff"),
    ("fip_long_diff", "fip_long_diff"),
    ("home_fip_long", "home_fip_long"),
    ("home_fip_short", "home_fip_short"),
    ("home_whip_long", "home_whip_long"),
    ("home_ra_long", "home_ra_long"),
    ("away_fip_long", "away_fip_long"),
    ("away_fip_short", "away_fip_short"),
    ("away_depth_long", "away_depth_long"),
    ("away_ra_long", "away_ra_long"),
    ("home_bp_fip_short", "home_bp_fip_short"),
    ("home_bp_fip_long", "home_bp_fip_long"),
    ("home_bp_3d", "home_bp_3d"),
    ("away_bp_fip_short", "away_bp_fip_short"),
    ("away_bp_3d", "away_bp_3d"),
    ("bp_fip_diff", "bp_fip_diff"),
    ("bp_workload_gap", "bp_workload_gap"),
    ("bp_fip_short_gap", "bp_fip_short_gap"),
    ("starter_depth_diff", "starter_depth_diff"),
    ("depth:", "depth_compound"),
]


def _get_cat(name):
    for prefix, cat in _CAT_PREFIXES:
        if name.startswith(prefix):
            return cat
    return name


def same_category(f1, f2):
    return _get_cat(f1) == _get_cat(f2)


# ── Phases ──────────────────────────────────────────────────────────────────────

def phase1_singles(rl):
    candidates = build_filters(rl)
    results = [eval_strat(rl, "BASELINE (no BP days)")]
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_strat(rl[mask], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    ptable(results[:40], "PHASE 1: SINGLE PITCHER-ADVANTAGE FILTERS (sorted by ROI)")
    return candidates, results


def phase2_combos(rl, candidates, singles):
    top_names = [
        r["filter"] for r in singles
        if r["roi"] > 0 and not r["filter"].startswith("BASELINE")
    ][:15]
    combo_results = []
    for f1, f2 in combinations(top_names, 2):
        if same_category(f1, f2):
            continue
        m1 = candidates[f1].fillna(False)
        m2 = candidates[f2].fillna(False)
        r = eval_strat(rl[m1 & m2], f"{f1} + {f2}")
        if r:
            combo_results.append(r)
    combo_results.sort(key=lambda x: -x["roi"])
    ptable(combo_results[:25], "PHASE 2: TOP 2-WAY PITCHER-ADVANTAGE COMBOS")
    return combo_results


def phase3_train_test(rl, candidates, singles, combos):
    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()
    print(f"\n{'=' * 130}")
    print(f"PHASE 3: TRAIN/TEST VALIDATION (TRAIN=2014-2019, TEST=2021-2025)")
    print(f"TRAIN: {len(train)} games, TEST: {len(test)} games")
    print(f"{'=' * 130}")

    # Collect strategies: top 5 singles + top 10 combos with positive ROI
    strat_names = []
    for r in singles:
        if r["roi"] > 0 and not r["filter"].startswith("BASELINE"):
            strat_names.append(r["filter"])
            if len(strat_names) >= 5:
                break
    for r in combos:
        if r["roi"] > 0:
            strat_names.append(r["filter"])
            if len(strat_names) >= 15:
                break

    for name in strat_names:
        parts = name.split(" + ")
        for label, split_df in [("TRAIN", train), ("TEST", test)]:
            sd = split_df.copy()
            add_derived(sd)
            sc = build_filters(sd)
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
            r = eval_strat(sd[mask], f"[{label}] {name}", min_bets=10)
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(
                    f"  {r['filter']:<75} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                    f"ROI {r['roi']:+6.1f}%  flds {r['folds']}  [{rois}]"
                )


def _apply_filter(rl, candidates, filter_name):
    """Apply a composite filter (parts joined by ' + ') and return masked DataFrame."""
    parts = filter_name.split(" + ")
    mask = pd.Series(True, index=rl.index)
    for part in parts:
        if part in candidates:
            mask = mask & candidates[part].fillna(False)
        else:
            return None
    return rl[mask]


def _season_table(subset, bet_type="rl"):
    """Print per-season table for RL or Dog ML."""
    if bet_type == "rl":
        print(f"  {'Season':<8} {'Games':>6} {'Cover%':>7} {'AvgOdds':>8} {'ROI':>8}")
        print("-" * 50)
        for season in sorted(subset["season"].unique()):
            s = subset[subset["season"] == season]
            n = len(s)
            if n < 3:
                continue
            covers = s["covers"].values.astype(float)
            odds = s["rl_odds"].values
            pnl = np.where(covers, (odds - 1) * 100, -100)
            roi = pnl.sum() / (n * 100) * 100
            cr = covers.mean()
            print(f"  {int(season):<8} {n:6d} {cr*100:6.1f}% {odds.mean():7.3f} {roi:+7.1f}%")
    else:
        print(f"  {'Season':<8} {'Games':>6} {'Win%':>7} {'AvgOdds':>8} {'ROI':>8}")
        print("-" * 50)
        for season in sorted(subset["season"].unique()):
            s = subset[subset["season"] == season]
            n = len(s)
            if n < 3:
                continue
            dog_wins = (s["fav_margin"] < 0).values.astype(float)
            ml_odds = s["away_decimal_odds"].values
            ml_pnl = np.where(dog_wins, (ml_odds - 1) * 100, -100)
            ml_roi = ml_pnl.sum() / (n * 100) * 100
            wr = dog_wins.mean()
            print(f"  {int(season):<8} {n:6d} {wr*100:6.1f}% {ml_odds.mean():7.3f} {ml_roi:+7.1f}%")


def eval_ml(data, name, min_bets=20):
    """Evaluate Dog ML (moneyline) strategy."""
    n = len(data)
    if n < min_bets:
        return None
    dog_wins = (data["fav_margin"] < 0).values.astype(float)
    odds = data["away_decimal_odds"].values
    pnl = np.where(dog_wins, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    wr = dog_wins.mean()
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
        sp = np.where(dog_wins[sm.values], (odds[sm.values] - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "filter": name, "bets": n, "bps": bps,
        "cr": wr, "avg_odds": avg_odds, "roi": roi,
        "sharpe": sharpe, "max_ls": max_ls(dog_wins == 0),
        "folds": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def phase4_season_detail(rl, candidates, combos):
    if not combos or combos[0]["roi"] <= 0:
        print("\nNo positive-ROI combos found.")
        return

    best = combos[0]
    subset = _apply_filter(rl, candidates, best["filter"])
    if subset is None or len(subset) == 0:
        return

    print(f"\n{'=' * 130}")
    print(f"PHASE 4: SEASON DETAIL — {best['filter']}")
    print(f"  Total: {best['bets']} bets, cover {best['cr']*100:.1f}%, ROI {best['roi']:+.1f}%")
    print(f"{'=' * 130}")
    _season_table(subset, "rl")

    if "away_decimal_odds" in subset.columns:
        print(f"\n  Dog ML equivalent:")
        _season_table(subset, "ml")


# ── Phase 5: 3-way combos on base strategies ───────────────────────────────────

BASE_STRATEGIES = [
    "away_bp_3d <= 6 + bp_workload_gap >= 3",
    "away_bp_3d <= 6 + home_bp_3d >= 8",
]

# Starter/pitcher filters to layer on top (categories A-C, G only)
STARTER_CATEGORIES = {"fip_short_diff", "fip_long_diff",
                       "home_fip_long", "home_fip_short", "home_whip_long", "home_ra_long",
                       "away_fip_long", "away_fip_short", "away_depth_long", "away_ra_long",
                       "starter_depth_diff", "depth_compound"}


def phase5_3way(rl, candidates):
    print(f"\n{'=' * 130}")
    print("PHASE 5: 3-WAY COMBOS (base bullpen + starter filter)")
    print(f"{'=' * 130}")

    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()

    for base_name in BASE_STRATEGIES:
        base_parts = base_name.split(" + ")
        base_mask = pd.Series(True, index=rl.index)
        for part in base_parts:
            base_mask = base_mask & candidates[part].fillna(False)

        base_sub = rl[base_mask]
        base_r = eval_strat(base_sub, f"BASE: {base_name}")

        print(f"\n  --- Base: {base_name} ({base_r['bets']} bets, "
              f"cvr {base_r['cr']*100:.1f}%, ROI {base_r['roi']:+.1f}%) ---")

        # Test each starter filter as 3rd layer
        results_3way = []
        for fname, fmask in candidates.items():
            cat = _get_cat(fname)
            if cat not in STARTER_CATEGORIES:
                continue
            # Skip filters already in base
            if fname in base_parts:
                continue
            combined = base_mask & fmask.fillna(False)
            r = eval_strat(rl[combined], f"{base_name} + {fname}")
            if r and r["roi"] > base_r["roi"]:
                results_3way.append(r)

        results_3way.sort(key=lambda x: -x["roi"])
        ptable(results_3way[:15], f"  3-WAY: {base_name} + starter filter")

        # Train/test for top 5
        print(f"\n  Train/Test validation (top 5):")
        for r3 in results_3way[:5]:
            parts = r3["filter"].split(" + ")
            for label, split_df in [("TRAIN", train), ("TEST", test)]:
                sd = split_df.copy()
                add_derived(sd)
                sc = build_filters(sd)
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
                rv = eval_strat(sd[mask], f"[{label}] {r3['filter']}", min_bets=8)
                if rv:
                    rois = ", ".join(f"{x:+.0f}" for x in rv["season_rois"])
                    print(
                        f"    {rv['filter']:<80} {rv['bets']:4d} cvr {rv['cr']*100:5.1f}% "
                        f"ROI {rv['roi']:+6.1f}%  flds {rv['folds']}  [{rois}]"
                    )


# ── Phase 6: Dog ML evaluation ─────────────────────────────────────────────────

def phase6_dog_ml(rl, candidates):
    print(f"\n{'=' * 130}")
    print("PHASE 6: DOG ML (moneyline) — same filters, dog wins outright")
    print(f"{'=' * 130}")

    if "away_decimal_odds" not in rl.columns:
        print("  No away_decimal_odds column — skipping Dog ML.")
        return

    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()

    # Evaluate base strategies + their best 3-way extensions
    strats = list(BASE_STRATEGIES)

    # Also test the top 2-way combos from Phase 2 that had high ROI
    extra_combos = [
        "home_ra_long >= 5.5 + home_bp_3d >= 10",
        "starter_depth_diff <= -1.0 + away_fip_short <= 3.5",
        "home_ra_long >= 5.5 + away_fip_short <= 3.5",
        "away_bp_3d <= 6 + home_bp_3d >= 10",
    ]
    strats.extend(extra_combos)

    ml_results = []
    for sname in strats:
        subset = _apply_filter(rl, candidates, sname)
        if subset is None:
            continue
        r = eval_ml(subset, sname)
        if r:
            ml_results.append(r)

    ml_results.sort(key=lambda x: -x["roi"])
    # Reuse ptable but header says Win% not Cvr
    print(f"\n{'=' * 130}")
    print("  DOG ML RESULTS (sorted by ROI)")
    print(f"{'=' * 130}")
    print(f"  {'Filter':<60} {'Bets':>5} {'B/S':>4} {'Win%':>6} {'Odds':>5} {'ROI':>7} {'Shrp':>6} {'Flds':>6}  Seasons")
    print("-" * 130)
    for r in ml_results:
        rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
        print(
            f"  {r['filter']:<60} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['cr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['sharpe']:5.3f} {r['folds']:>6}  [{rois}]"
        )

    # Train/test for all
    print(f"\n  Train/Test validation (Dog ML):")
    for sname in strats:
        for label, split_df in [("TRAIN", train), ("TEST", test)]:
            sd = split_df.copy()
            add_derived(sd)
            sc = build_filters(sd)
            subset = _apply_filter(sd, sc, sname)
            if subset is None:
                continue
            rv = eval_ml(subset, f"[{label}] {sname}", min_bets=8)
            if rv:
                rois = ", ".join(f"{x:+.0f}" for x in rv["season_rois"])
                print(
                    f"    {rv['filter']:<75} {rv['bets']:4d} win {rv['cr']*100:5.1f}% "
                    f"ROI {rv['roi']:+6.1f}%  flds {rv['folds']}  [{rois}]"
                )

    # Season detail for best Dog ML strategy
    if ml_results:
        best = ml_results[0]
        subset = _apply_filter(rl, candidates, best["filter"])
        if subset is not None and len(subset) >= 20:
            print(f"\n  Season detail — Dog ML: {best['filter']}")
            _season_table(subset, "ml")


# ── Phase 7: Starter as base, soft bullpen overlay ──────────────────────────────

def phase7_starter_base(rl):
    """Starter quality filters first, then layer soft bullpen conditions."""
    print(f"\n{'=' * 130}")
    print("PHASE 7: STARTER-FIRST SCAN (starter quality base + soft bullpen overlay)")
    print(f"{'=' * 130}")

    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()

    # --- Starter base filters (broader than Phase 1-2) ---
    starter_bases = {}

    # FIP mismatch (home worse than away)
    if "starter_fip_diff" in rl.columns:
        for t in [0.3, 0.5, 0.8]:
            starter_bases[f"fip_short_diff >= {t}"] = rl["starter_fip_diff"] >= t
    if "starter_fip_long_diff" in rl.columns:
        for t in [0.3, 0.5, 0.8]:
            starter_bases[f"fip_long_diff >= {t}"] = rl["starter_fip_long_diff"] >= t

    # Away starter quality
    if "away_sp_fip_short" in rl.columns:
        for t in [3.5, 3.8, 4.0]:
            starter_bases[f"away_fip_short <= {t}"] = rl["away_sp_fip_short"] <= t
    if "away_sp_fip_long" in rl.columns:
        for t in [3.5, 3.8, 4.0]:
            starter_bases[f"away_fip_long <= {t}"] = rl["away_sp_fip_long"] <= t
    if "away_sp_ip_per_start_long" in rl.columns:
        for t in [5.0, 5.5]:
            starter_bases[f"away_depth >= {t}"] = rl["away_sp_ip_per_start_long"] >= t

    # Home starter weakness
    if "home_sp_fip_short" in rl.columns:
        for t in [4.0, 4.5, 5.0]:
            starter_bases[f"home_fip_short >= {t}"] = rl["home_sp_fip_short"] >= t
    if "home_sp_ra_long" in rl.columns:
        for t in [4.0, 4.5, 5.0]:
            starter_bases[f"home_ra_long >= {t}"] = rl["home_sp_ra_long"] >= t
    if "home_sp_whip_long" in rl.columns:
        for t in [1.3, 1.4]:
            starter_bases[f"home_whip_long >= {t}"] = rl["home_sp_whip_long"] >= t

    # Depth gap
    if "starter_depth_diff" in rl.columns:
        for t in [-0.5, -1.0]:
            starter_bases[f"depth_diff <= {t}"] = rl["starter_depth_diff"] <= t

    # --- Soft bullpen overlays (inclusive, not restrictive) ---
    bp_overlays = {"(no BP filter)": pd.Series(True, index=rl.index)}

    if "bp_workload_gap" in rl.columns:
        bp_overlays["bp_wl_gap >= 0"] = rl["bp_workload_gap"] >= 0
        bp_overlays["bp_wl_gap >= 1"] = rl["bp_workload_gap"] >= 1
        bp_overlays["bp_wl_gap >= 2"] = rl["bp_workload_gap"] >= 2
    if "bp_ip_3d_away" in rl.columns:
        bp_overlays["away_bp_3d <= 8"] = rl["bp_ip_3d_away"] <= 8
        bp_overlays["away_bp_3d <= 10"] = rl["bp_ip_3d_away"] <= 10
    if "bp_ip_3d_home" in rl.columns:
        bp_overlays["home_bp_3d >= 6"] = rl["bp_ip_3d_home"] >= 6
        bp_overlays["home_bp_3d >= 8"] = rl["bp_ip_3d_home"] >= 8
    if "bullpen_fip_diff" in rl.columns:
        bp_overlays["bp_fip_diff >= 0"] = rl["bullpen_fip_diff"] >= 0
        bp_overlays["bp_fip_diff >= 0.3"] = rl["bullpen_fip_diff"] >= 0.3

    # --- 2-way: starter + starter combos ---
    print(f"\n  Section A: Starter-only combos (no bullpen filter)")
    starter_names = list(starter_bases.keys())
    s2_results = []
    for f1, f2 in combinations(starter_names, 2):
        if _get_cat(f1) == _get_cat(f2):
            continue
        m = starter_bases[f1].fillna(False) & starter_bases[f2].fillna(False)
        r = eval_strat(rl[m], f"{f1} + {f2}")
        if r:
            s2_results.append(r)
    s2_results.sort(key=lambda x: -x["roi"])
    ptable(s2_results[:20], "  STARTER-ONLY 2-WAY COMBOS (no bullpen)")

    # --- 3-way: starter combo + soft bullpen ---
    print(f"\n  Section B: Best starter combos + soft bullpen overlay")
    top_starter_combos = [r for r in s2_results if r["roi"] > 0][:10]

    all_3way = []
    for sc in top_starter_combos:
        parts = sc["filter"].split(" + ")
        base_mask = pd.Series(True, index=rl.index)
        for p in parts:
            base_mask = base_mask & starter_bases[p].fillna(False)

        for bp_name, bp_mask in bp_overlays.items():
            if bp_name == "(no BP filter)":
                continue
            combined = base_mask & bp_mask.fillna(False)
            r = eval_strat(rl[combined], f"{sc['filter']} + {bp_name}")
            if r and r["roi"] > sc["roi"]:
                all_3way.append(r)

    all_3way.sort(key=lambda x: -x["roi"])
    ptable(all_3way[:20], "  STARTER COMBO + SOFT BULLPEN (ROI > base)")

    # --- Train/test for top starter combos + best 3-way ---
    print(f"\n  Section C: Train/Test validation")
    validate = []
    for r in s2_results[:8]:
        if r["roi"] > 0:
            validate.append(r["filter"])
    for r in all_3way[:8]:
        if r["roi"] > 0 and r["filter"] not in validate:
            validate.append(r["filter"])

    for name in validate:
        parts = name.split(" + ")
        for label, split_df in [("TRAIN", train), ("TEST", test)]:
            sd = split_df.copy()
            add_derived(sd)

            # Rebuild both starter and bp filters on the split
            sb = {}
            if "starter_fip_diff" in sd.columns:
                for t in [0.3, 0.5, 0.8]:
                    sb[f"fip_short_diff >= {t}"] = sd["starter_fip_diff"] >= t
            if "starter_fip_long_diff" in sd.columns:
                for t in [0.3, 0.5, 0.8]:
                    sb[f"fip_long_diff >= {t}"] = sd["starter_fip_long_diff"] >= t
            if "away_sp_fip_short" in sd.columns:
                for t in [3.5, 3.8, 4.0]:
                    sb[f"away_fip_short <= {t}"] = sd["away_sp_fip_short"] <= t
            if "away_sp_fip_long" in sd.columns:
                for t in [3.5, 3.8, 4.0]:
                    sb[f"away_fip_long <= {t}"] = sd["away_sp_fip_long"] <= t
            if "away_sp_ip_per_start_long" in sd.columns:
                for t in [5.0, 5.5]:
                    sb[f"away_depth >= {t}"] = sd["away_sp_ip_per_start_long"] >= t
            if "home_sp_fip_short" in sd.columns:
                for t in [4.0, 4.5, 5.0]:
                    sb[f"home_fip_short >= {t}"] = sd["home_sp_fip_short"] >= t
            if "home_sp_ra_long" in sd.columns:
                for t in [4.0, 4.5, 5.0]:
                    sb[f"home_ra_long >= {t}"] = sd["home_sp_ra_long"] >= t
            if "home_sp_whip_long" in sd.columns:
                for t in [1.3, 1.4]:
                    sb[f"home_whip_long >= {t}"] = sd["home_sp_whip_long"] >= t
            if "starter_depth_diff" in sd.columns:
                for t in [-0.5, -1.0]:
                    sb[f"depth_diff <= {t}"] = sd["starter_depth_diff"] <= t

            # BP overlays
            if "bp_workload_gap" in sd.columns:
                sb["bp_wl_gap >= 0"] = sd["bp_workload_gap"] >= 0
                sb["bp_wl_gap >= 1"] = sd["bp_workload_gap"] >= 1
                sb["bp_wl_gap >= 2"] = sd["bp_workload_gap"] >= 2
            if "bp_ip_3d_away" in sd.columns:
                sb["away_bp_3d <= 8"] = sd["bp_ip_3d_away"] <= 8
                sb["away_bp_3d <= 10"] = sd["bp_ip_3d_away"] <= 10
            if "bp_ip_3d_home" in sd.columns:
                sb["home_bp_3d >= 6"] = sd["bp_ip_3d_home"] >= 6
                sb["home_bp_3d >= 8"] = sd["bp_ip_3d_home"] >= 8
            if "bullpen_fip_diff" in sd.columns:
                sb["bp_fip_diff >= 0"] = sd["bullpen_fip_diff"] >= 0
                sb["bp_fip_diff >= 0.3"] = sd["bullpen_fip_diff"] >= 0.3

            mask = pd.Series(True, index=sd.index)
            valid = True
            for part in parts:
                if part in sb:
                    mask = mask & sb[part].fillna(False)
                else:
                    valid = False
                    break
            if not valid:
                continue
            r = eval_strat(sd[mask], f"[{label}] {name}", min_bets=8)
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(
                    f"    {r['filter']:<80} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                    f"ROI {r['roi']:+6.1f}%  flds {r['folds']}  [{rois}]"
                )

    # --- Dog ML for top strategies ---
    print(f"\n  Section D: Dog ML for top starter-based strategies")
    if "away_decimal_odds" in rl.columns:
        ml_strats = validate[:8]
        for name in ml_strats:
            parts = name.split(" + ")
            # Build mask from all filters
            all_f = {**starter_bases, **bp_overlays}
            mask = pd.Series(True, index=rl.index)
            valid = True
            for p in parts:
                if p in all_f:
                    mask = mask & all_f[p].fillna(False)
                else:
                    valid = False
                    break
            if not valid:
                continue
            r_rl = eval_strat(rl[mask], name)
            r_ml = eval_ml(rl[mask], name)
            if r_rl and r_ml:
                print(f"\n  {name}")
                print(f"    RL +1.5: {r_rl['bets']} bets, cvr {r_rl['cr']*100:.1f}%, "
                      f"ROI {r_rl['roi']:+.1f}%, flds {r_rl['folds']}")
                print(f"    Dog ML:  {r_ml['bets']} bets, win {r_ml['cr']*100:.1f}%, "
                      f"ROI {r_ml['roi']:+.1f}%, flds {r_ml['folds']}")


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 130)
    print("PITCHER ADVANTAGE SCAN — Away +1.5 (2014+, excluding bullpen days)")
    print("=" * 130)

    rl = build_rl_data()
    rl = rl[rl["season"] >= 2014].copy()
    rl["rl_odds"] = rl["rl_odds_adj"]

    n_before = len(rl)
    # Exclude bullpen days (handled by Tier 1)
    if "home_is_bullpen_no_starter" in rl.columns:
        rl = rl[~rl["home_is_bullpen_no_starter"].fillna(False)].copy()
    if "away_is_bullpen_no_starter" in rl.columns:
        rl = rl[~rl["away_is_bullpen_no_starter"].fillna(False)].copy()

    add_derived(rl)

    print(f"\nUniverse: {len(rl)} games ({n_before - len(rl)} bullpen days excluded)")
    print(f"  Cover rate: {rl['covers'].mean()*100:.1f}%")
    print(f"  Avg RL odds: {rl['rl_odds'].mean():.3f}")
    print(f"  Seasons: {sorted(rl['season'].unique().astype(int).tolist())}")

    # Report column availability
    key_cols = [
        "starter_fip_diff", "starter_fip_long_diff", "starter_whip_long_diff",
        "starter_depth_diff",
        "home_sp_fip_long", "home_sp_fip_short", "home_sp_whip_long", "home_sp_ra_long",
        "away_sp_fip_long", "away_sp_fip_short", "away_sp_ip_per_start_long", "away_sp_ra_long",
        "bp_fip_short_home", "bp_fip_long_home", "bp_ip_3d_home",
        "bp_fip_short_away", "bp_ip_3d_away",
        "bullpen_fip_diff", "bp_workload_gap", "bp_fip_short_gap",
    ]
    present = [c for c in key_cols if c in rl.columns and rl[c].notna().any()]
    missing = [c for c in key_cols if c not in rl.columns or not rl[c].notna().any()]
    print(f"\n  Key columns present: {len(present)}/{len(key_cols)}")
    if missing:
        print(f"  Missing/empty: {missing}")

    candidates, singles = phase1_singles(rl)
    combos = phase2_combos(rl, candidates, singles)
    phase3_train_test(rl, candidates, singles, combos)
    phase4_season_detail(rl, candidates, combos)
    phase5_3way(rl, candidates)
    phase6_dog_ml(rl, candidates)
    phase7_starter_base(rl)


if __name__ == "__main__":
    main()
