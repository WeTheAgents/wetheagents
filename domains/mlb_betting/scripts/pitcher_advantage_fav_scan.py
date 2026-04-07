"""Pitcher-advantage filter scan for Fav -1.5 (2014+, excluding bullpen days).

Mirror of Session 27 away scan: does the same starter quality + depth + bullpen
fatigue mechanic work when the FAVORITE has the better starter?

Hypothesis: when the home favorite sends a quality deep starter against a weak/short
away starter, AND the away bullpen is tired — the favorite covers -1.5 at elevated rates.

Usage:
    python scripts/pitcher_advantage_fav_scan.py
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

TRAIN_SEASONS = [2014, 2015, 2016, 2017, 2018, 2019]
TEST_SEASONS = [2021, 2022, 2023, 2024, 2025]
FAV_RL_FALLBACK = 2.40


# ── Data ────────────────────────────────────────────────────────────────────────

def build_fav_rl_data():
    """Build Fav -1.5 universe with walk-forward edge, mirroring rl_fav_analysis.build_dataset."""
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds, american_to_decimal
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    logging.getLogger().setLevel(logging.INFO)
    print("Loading data and building features...")
    full = build_spec_features()

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    print("Running walk-forward model (~2 min)...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    mk = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]

    if "fav_margin" not in df.columns:
        df["fav_margin"] = np.where(
            df["fav_is_home"],
            df["home_final"] - df["away_final"],
            df["away_final"] - df["home_final"],
        )

    df["covers"] = df["fav_margin"] >= 2

    # RL odds for fav -1.5
    df["rl_odds"] = np.nan
    if "home_run_line_odds" in df.columns:
        home_fav_mask = df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == -1.5)
        df.loc[home_fav_mask, "rl_odds"] = df.loc[home_fav_mask, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    if "away_run_line_odds" in df.columns:
        away_fav_mask = ~df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == 1.5)
        df.loc[away_fav_mask, "rl_odds"] = df.loc[away_fav_mask, "away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    df["rl_odds"] = df["rl_odds"].fillna(FAV_RL_FALLBACK)

    # Universe
    if "home_run_line" in df.columns:
        rl_valid = df["home_run_line"].isin([-1.5, 1.5])
    else:
        rl_valid = pd.Series(True, index=df.index)
    if "involves_col" in df.columns:
        rl_valid = rl_valid & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        rl_valid = rl_valid & ~df["is_extreme_line"]

    rl = df[rl_valid].copy()
    logging.getLogger().setLevel(logging.WARNING)

    n_real = (rl["rl_odds"] != FAV_RL_FALLBACK).sum()
    print(f"Fav -1.5 universe: {len(rl)} games ({n_real} real RL odds)")
    return rl


# ── Eval helpers ────────────────────────────────────────────────────────────────

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

def _fav_pick(rl, home_col, away_col):
    """Pick home value when fav_is_home, else away value. Returns pd.Series."""
    if home_col not in rl.columns or away_col not in rl.columns:
        return None
    return pd.Series(
        np.where(rl["fav_is_home"], rl[home_col], rl[away_col]),
        index=rl.index,
    )


def add_derived(rl):
    """Add fav-oriented pitcher columns.

    Convention: for fav-oriented features, we flip so positive = fav stronger.
    Since most games have fav_is_home=True, we also keep raw home/away columns
    for direct access.
    """
    flip = pd.Series(np.where(rl["fav_is_home"], 1, -1), index=rl.index)

    # Starter FIP diff: fav perspective (positive = fav starter has LOWER FIP = better)
    # starter_fip_diff = home_sp_fip_short - away_sp_fip_short (already exists)
    # For fav: we want negative starter_fip_diff when fav is home (fav has lower FIP)
    if "starter_fip_diff" in rl.columns:
        rl["fav_fip_short_diff"] = rl["starter_fip_diff"] * flip  # negative = fav better
    if "home_sp_fip_long" in rl.columns and "away_sp_fip_long" in rl.columns:
        raw = rl["home_sp_fip_long"] - rl["away_sp_fip_long"]
        rl["fav_fip_long_diff"] = raw * flip

    # Starter depth: fav perspective (positive = fav goes deeper)
    if "home_sp_ip_per_start_long" in rl.columns and "away_sp_ip_per_start_long" in rl.columns:
        raw = rl["home_sp_ip_per_start_long"] - rl["away_sp_ip_per_start_long"]
        rl["fav_depth_diff"] = raw * flip

    # Individual fav/dog starter stats
    for out_col, home_col, away_col in [
        ("fav_sp_fip_short", "home_sp_fip_short", "away_sp_fip_short"),
        ("fav_sp_fip_long", "home_sp_fip_long", "away_sp_fip_long"),
        ("dog_sp_fip_short", "away_sp_fip_short", "home_sp_fip_short"),
        ("dog_sp_fip_long", "away_sp_fip_long", "home_sp_fip_long"),
        ("fav_sp_ip_per_start", "home_sp_ip_per_start_long", "away_sp_ip_per_start_long"),
        ("dog_sp_ip_per_start", "away_sp_ip_per_start_long", "home_sp_ip_per_start_long"),
        ("fav_sp_whip_long", "home_sp_whip_long", "away_sp_whip_long"),
        ("dog_sp_whip_long", "away_sp_whip_long", "home_sp_whip_long"),
        ("fav_sp_ra_long", "home_sp_ra_long", "away_sp_ra_long"),
        ("dog_sp_ra_long", "away_sp_ra_long", "home_sp_ra_long"),
        ("fav_bp_ip_3d", "bp_ip_3d_home", "bp_ip_3d_away"),
        ("dog_bp_ip_3d", "bp_ip_3d_away", "bp_ip_3d_home"),
        ("fav_bp_fip_short", "bp_fip_short_home", "bp_fip_short_away"),
        ("dog_bp_fip_short", "bp_fip_short_away", "bp_fip_short_home"),
    ]:
        if home_col in rl.columns and away_col in rl.columns:
            rl[out_col] = np.where(rl["fav_is_home"], rl[home_col], rl[away_col])

    # Bullpen gaps (fav perspective)
    if "bp_ip_3d_home" in rl.columns and "bp_ip_3d_away" in rl.columns:
        raw = rl["bp_ip_3d_home"] - rl["bp_ip_3d_away"]
        rl["fav_bp_workload_gap"] = raw * flip  # negative = fav BP more rested
    if "bullpen_fip_diff" in rl.columns:
        rl["fav_bp_fip_gap"] = rl["bullpen_fip_diff"] * flip

    # Bullpen day flags
    for out_col, home_col, away_col in [
        ("fav_is_bullpen_day", "home_is_bullpen_no_starter", "away_is_bullpen_no_starter"),
        ("dog_is_bullpen_day", "away_is_bullpen_no_starter", "home_is_bullpen_no_starter"),
    ]:
        if home_col in rl.columns and away_col in rl.columns:
            rl[out_col] = np.where(rl["fav_is_home"], rl[home_col], rl[away_col])


# ── Filter builder ──────────────────────────────────────────────────────────────

def build_filters(rl):
    c = {}

    # === A. Fav starter quality (low FIP = good) ===
    if "fav_sp_fip_short" in rl.columns:
        for t in [3.0, 3.5, 3.8, 4.0]:
            c[f"fav_fip_short <= {t}"] = rl["fav_sp_fip_short"] <= t
    if "fav_sp_fip_long" in rl.columns:
        for t in [3.0, 3.5, 3.8, 4.0]:
            c[f"fav_fip_long <= {t}"] = rl["fav_sp_fip_long"] <= t

    # === B. Dog starter weakness (high FIP = bad) ===
    if "dog_sp_fip_short" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"dog_fip_short >= {t}"] = rl["dog_sp_fip_short"] >= t
    if "dog_sp_fip_long" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"dog_fip_long >= {t}"] = rl["dog_sp_fip_long"] >= t
    if "dog_sp_ra_long" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"dog_ra_long >= {t}"] = rl["dog_sp_ra_long"] >= t

    # === C. FIP mismatch (fav has lower FIP, so diff is negative) ===
    if "fav_fip_short_diff" in rl.columns:
        for t in [-0.3, -0.5, -0.8, -1.0, -1.5]:
            c[f"fav_fip_short_diff <= {t}"] = rl["fav_fip_short_diff"] <= t
    if "fav_fip_long_diff" in rl.columns:
        for t in [-0.3, -0.5, -0.8, -1.0, -1.5]:
            c[f"fav_fip_long_diff <= {t}"] = rl["fav_fip_long_diff"] <= t

    # === D. Fav starter depth (high IP/start = deep) ===
    if "fav_sp_ip_per_start" in rl.columns:
        for t in [5.0, 5.5, 6.0]:
            c[f"fav_depth >= {t}"] = rl["fav_sp_ip_per_start"] >= t

    # === E. Dog starter short (low IP/start) ===
    if "dog_sp_ip_per_start" in rl.columns:
        for t in [5.5, 5.0, 4.5]:
            c[f"dog_depth <= {t}"] = rl["dog_sp_ip_per_start"] <= t

    # === F. Depth gap (fav goes deeper, positive = fav deeper) ===
    if "fav_depth_diff" in rl.columns:
        for t in [0.5, 1.0, 1.5]:
            c[f"fav_depth_diff >= {t}"] = rl["fav_depth_diff"] >= t

    # === G. Dog bullpen fatigue (tired = bad for dog) ===
    if "dog_bp_ip_3d" in rl.columns:
        for t in [6, 8, 10, 12]:
            c[f"dog_bp_3d >= {t}"] = rl["dog_bp_ip_3d"] >= t

    # === H. Fav bullpen rested ===
    if "fav_bp_ip_3d" in rl.columns:
        for t in [6, 8, 10]:
            c[f"fav_bp_3d <= {t}"] = rl["fav_bp_ip_3d"] <= t

    # === I. BP workload gap (negative = fav BP more rested) ===
    if "fav_bp_workload_gap" in rl.columns:
        for t in [0, -1, -2, -3]:
            c[f"fav_bp_wl_gap <= {t}"] = rl["fav_bp_workload_gap"] <= t

    # === J. Compound depth filters ===
    if "fav_sp_ip_per_start" in rl.columns and "dog_sp_ip_per_start" in rl.columns:
        c["depth: fav>=5.5 + dog<5.0"] = (
            (rl["fav_sp_ip_per_start"] >= 5.5) & (rl["dog_sp_ip_per_start"] < 5.0)
        )
        c["depth: fav>=6.0 + dog<5.0"] = (
            (rl["fav_sp_ip_per_start"] >= 6.0) & (rl["dog_sp_ip_per_start"] < 5.0)
        )
        c["depth: fav>=5.5 + dog<5.5"] = (
            (rl["fav_sp_ip_per_start"] >= 5.5) & (rl["dog_sp_ip_per_start"] < 5.5)
        )

    # === K. Implied prob (moderate fav = not extreme) ===
    if "home_implied_prob" in rl.columns and "away_implied_prob" in rl.columns:
        rl["_fav_impl"] = pd.Series(
            np.where(rl["fav_is_home"], rl["home_implied_prob"], rl["away_implied_prob"]),
            index=rl.index,
        )
        for lo, hi in [(0.55, 0.65), (0.55, 0.70), (0.60, 0.70), (0.60, 0.75), (0.62, 0.75)]:
            c[f"impl {int(lo*100)}-{int(hi*100)}%"] = (rl["_fav_impl"] >= lo) & (rl["_fav_impl"] <= hi)

    return c


# ── Same-category check ────────────────────────────────────────────────────────

_CAT_PREFIXES = [
    ("fav_fip_short <=", "fav_fip_short"),
    ("fav_fip_long <=", "fav_fip_long"),
    ("dog_fip_short >=", "dog_fip_short"),
    ("dog_fip_long >=", "dog_fip_long"),
    ("dog_ra_long >=", "dog_ra_long"),
    ("fav_fip_short_diff", "fav_fip_short_diff"),
    ("fav_fip_long_diff", "fav_fip_long_diff"),
    ("fav_depth >=", "fav_depth"),
    ("dog_depth <=", "dog_depth"),
    ("fav_depth_diff", "fav_depth_diff"),
    ("dog_bp_3d", "dog_bp_3d"),
    ("fav_bp_3d", "fav_bp_3d"),
    ("fav_bp_wl_gap", "fav_bp_wl_gap"),
    ("depth:", "depth_compound"),
    ("impl ", "impl"),
]


def _get_cat(name):
    for prefix, cat in _CAT_PREFIXES:
        if name.startswith(prefix):
            return cat
    return name


def same_category(f1, f2):
    return _get_cat(f1) == _get_cat(f2)


# ── Phases ──────────────────────────────────────────────────────────────────────

def _to_bool_series(mask, index):
    """Ensure mask is a pandas bool Series with fillna applied."""
    if isinstance(mask, np.ndarray):
        return pd.Series(mask, index=index).fillna(False)
    return mask.fillna(False)


def phase1_singles(rl, candidates):
    results = [eval_strat(rl, "BASELINE (no BP days)")]
    for name, mask in candidates.items():
        mask = _to_bool_series(mask, rl.index)
        r = eval_strat(rl[mask], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    ptable(results[:40], "PHASE 1: SINGLE FILTERS — Fav -1.5 Pitcher Advantage")
    return results


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
    ptable(combo_results[:25], "PHASE 2: TOP 2-WAY COMBOS — Fav -1.5 Pitcher Advantage")
    return combo_results


def phase3_train_test(rl, candidates, singles, combos):
    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()
    print(f"\n{'=' * 130}")
    print(f"PHASE 3: TRAIN/TEST (TRAIN=2014-2019, TEST=2021-2025)")
    print(f"TRAIN: {len(train)} games, TEST: {len(test)} games")
    print(f"{'=' * 130}")

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
            r = eval_strat(sd[mask], f"[{label}] {name}", min_bets=8)
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(
                    f"  {r['filter']:<75} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                    f"ROI {r['roi']:+6.1f}%  flds {r['folds']}  [{rois}]"
                )


def phase4_starter_soft_bp(rl):
    """Starter-first: starter quality combos + soft bullpen overlay."""
    print(f"\n{'=' * 130}")
    print("PHASE 4: STARTER-FIRST + SOFT BULLPEN OVERLAY — Fav -1.5")
    print(f"{'=' * 130}")

    train = rl[rl["season"].isin(TRAIN_SEASONS)].copy()
    test = rl[rl["season"].isin(TEST_SEASONS)].copy()

    # Starter bases
    sb = {}
    if "fav_sp_fip_short" in rl.columns:
        for t in [3.0, 3.5, 3.8]:
            sb[f"fav_fip_short <= {t}"] = rl["fav_sp_fip_short"] <= t
    if "fav_sp_fip_long" in rl.columns:
        for t in [3.0, 3.5, 3.8]:
            sb[f"fav_fip_long <= {t}"] = rl["fav_sp_fip_long"] <= t
    if "dog_sp_fip_short" in rl.columns:
        for t in [4.0, 4.5, 5.0]:
            sb[f"dog_fip_short >= {t}"] = rl["dog_sp_fip_short"] >= t
    if "dog_sp_ra_long" in rl.columns:
        for t in [4.0, 4.5, 5.0]:
            sb[f"dog_ra_long >= {t}"] = rl["dog_sp_ra_long"] >= t
    if "fav_depth_diff" in rl.columns:
        for t in [0.5, 1.0]:
            sb[f"fav_depth_diff >= {t}"] = rl["fav_depth_diff"] >= t
    if "fav_fip_short_diff" in rl.columns:
        for t in [-0.3, -0.5, -0.8]:
            sb[f"fav_fip_short_diff <= {t}"] = rl["fav_fip_short_diff"] <= t

    # Soft BP overlays
    bp = {"(none)": pd.Series(True, index=rl.index)}
    if "dog_bp_ip_3d" in rl.columns:
        bp["dog_bp_3d >= 6"] = rl["dog_bp_ip_3d"] >= 6
        bp["dog_bp_3d >= 8"] = rl["dog_bp_ip_3d"] >= 8
    if "fav_bp_workload_gap" in rl.columns:
        bp["fav_bp_wl_gap <= 0"] = rl["fav_bp_workload_gap"] <= 0
        bp["fav_bp_wl_gap <= -1"] = rl["fav_bp_workload_gap"] <= -1

    # Implied prob bands
    impl_filters = {}
    if "_fav_impl" in rl.columns:
        impl_filters["impl 62-75%"] = (rl["_fav_impl"] >= 0.62) & (rl["_fav_impl"] <= 0.75)
        impl_filters["impl 55-70%"] = (rl["_fav_impl"] >= 0.55) & (rl["_fav_impl"] <= 0.70)

    # Section A: starter-only 2-way
    starter_names = list(sb.keys())
    s2 = []
    for f1, f2 in combinations(starter_names, 2):
        if _get_cat(f1) == _get_cat(f2):
            continue
        m = sb[f1].fillna(False) & sb[f2].fillna(False)
        r = eval_strat(rl[m], f"{f1} + {f2}")
        if r:
            s2.append(r)
    s2.sort(key=lambda x: -x["roi"])
    ptable(s2[:20], "  STARTER-ONLY 2-WAY COMBOS — Fav -1.5")

    # Section B: starter combo + soft BP + optional impl
    top_combos = [r for r in s2 if r["roi"] > 0][:10]
    all_3way = []
    for sc in top_combos:
        parts = sc["filter"].split(" + ")
        base_mask = pd.Series(True, index=rl.index)
        for p in parts:
            base_mask = base_mask & sb[p].fillna(False)

        for bp_name, bp_mask in bp.items():
            if bp_name == "(none)":
                continue
            combined = base_mask & bp_mask.fillna(False)
            r = eval_strat(rl[combined], f"{sc['filter']} + {bp_name}")
            if r and r["roi"] > sc["roi"]:
                all_3way.append(r)

        # Also try with impl band
        for impl_name, impl_mask in impl_filters.items():
            combined = base_mask & impl_mask.fillna(False)
            r = eval_strat(rl[combined], f"{sc['filter']} + {impl_name}")
            if r and r["roi"] > sc["roi"]:
                all_3way.append(r)

    all_3way.sort(key=lambda x: -x["roi"])
    ptable(all_3way[:20], "  STARTER COMBO + SOFT OVERLAY (ROI > base) — Fav -1.5")

    # Section C: train/test for top strategies
    print(f"\n  Train/Test validation:")
    validate = []
    for r in s2[:5]:
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
            # Rebuild all filters on split
            all_f = {}
            if "fav_sp_fip_short" in sd.columns:
                for t in [3.0, 3.5, 3.8]:
                    all_f[f"fav_fip_short <= {t}"] = sd["fav_sp_fip_short"] <= t
            if "fav_sp_fip_long" in sd.columns:
                for t in [3.0, 3.5, 3.8]:
                    all_f[f"fav_fip_long <= {t}"] = sd["fav_sp_fip_long"] <= t
            if "dog_sp_fip_short" in sd.columns:
                for t in [4.0, 4.5, 5.0]:
                    all_f[f"dog_fip_short >= {t}"] = sd["dog_sp_fip_short"] >= t
            if "dog_sp_ra_long" in sd.columns:
                for t in [4.0, 4.5, 5.0]:
                    all_f[f"dog_ra_long >= {t}"] = sd["dog_sp_ra_long"] >= t
            if "fav_depth_diff" in sd.columns:
                for t in [0.5, 1.0]:
                    all_f[f"fav_depth_diff >= {t}"] = sd["fav_depth_diff"] >= t
            if "fav_fip_short_diff" in sd.columns:
                for t in [-0.3, -0.5, -0.8]:
                    all_f[f"fav_fip_short_diff <= {t}"] = sd["fav_fip_short_diff"] <= t
            if "dog_bp_ip_3d" in sd.columns:
                all_f["dog_bp_3d >= 6"] = sd["dog_bp_ip_3d"] >= 6
                all_f["dog_bp_3d >= 8"] = sd["dog_bp_ip_3d"] >= 8
            if "fav_bp_workload_gap" in sd.columns:
                all_f["fav_bp_wl_gap <= 0"] = sd["fav_bp_workload_gap"] <= 0
                all_f["fav_bp_wl_gap <= -1"] = sd["fav_bp_workload_gap"] <= -1
            if "_fav_impl" in sd.columns:
                all_f["impl 62-75%"] = (sd["_fav_impl"] >= 0.62) & (sd["_fav_impl"] <= 0.75)
                all_f["impl 55-70%"] = (sd["_fav_impl"] >= 0.55) & (sd["_fav_impl"] <= 0.70)

            mask = pd.Series(True, index=sd.index)
            valid = True
            for part in parts:
                if part in all_f:
                    mask = mask & all_f[part].fillna(False)
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


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 130)
    print("PITCHER ADVANTAGE SCAN — Fav -1.5 (2014+, excluding bullpen days)")
    print("=" * 130)

    rl = build_fav_rl_data()
    rl = rl[rl["season"] >= 2014].copy()

    n_before = len(rl)
    add_derived(rl)

    # Exclude bullpen days (fav side)
    if "fav_is_bullpen_day" in rl.columns:
        rl = rl[~rl["fav_is_bullpen_day"].fillna(False)].copy()
    if "dog_is_bullpen_day" in rl.columns:
        rl = rl[~rl["dog_is_bullpen_day"].fillna(False)].copy()

    print(f"\nUniverse: {len(rl)} games ({n_before - len(rl)} bullpen days excluded)")
    print(f"  Cover rate: {rl['covers'].mean()*100:.1f}%")
    print(f"  Avg RL odds: {rl['rl_odds'].mean():.3f}")
    print(f"  Seasons: {sorted(rl['season'].unique().astype(int).tolist())}")

    # Column check
    key_cols = [
        "fav_sp_fip_short", "fav_sp_fip_long", "fav_sp_ip_per_start",
        "dog_sp_fip_short", "dog_sp_fip_long", "dog_sp_ip_per_start",
        "fav_fip_short_diff", "fav_depth_diff",
        "dog_bp_ip_3d", "fav_bp_ip_3d", "fav_bp_workload_gap",
    ]
    present = [c for c in key_cols if c in rl.columns and rl[c].notna().any()]
    missing = [c for c in key_cols if c not in rl.columns or not rl[c].notna().any()]
    print(f"\n  Key columns present: {len(present)}/{len(key_cols)}")
    if missing:
        print(f"  Missing/empty: {missing}")

    candidates = build_filters(rl)
    singles = phase1_singles(rl, candidates)
    combos = phase2_combos(rl, candidates, singles)
    phase3_train_test(rl, candidates, singles, combos)
    phase4_starter_soft_bp(rl)


if __name__ == "__main__":
    main()
