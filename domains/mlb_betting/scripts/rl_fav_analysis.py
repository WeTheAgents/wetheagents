"""Favorite Run Line -1.5 strategy analysis.

Cover condition: fav_margin >= 2 (favorite wins by 2+ runs).
Odds: fav RL -1.5 odds from real data where available, else 2.40 fallback.

Two-base design:
  - Base A: ALL games (rule-based filters only)
  - Base B: edge < -0.05 (fav underpriced by walk-forward model)

Usage:
    python scripts/rl_fav_analysis.py
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
ASG_DAY = 15


# ---------------------------------------------------------------------------
# Helpers (from rl_away_analysis.py)
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

    # Walk-forward derived
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]

    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["day"] = pd.to_datetime(df["date"]).dt.day
    df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (df["day"] <= ASG_DAY))

    # Margin from favorite perspective (already in build_spec_features)
    if "fav_margin" not in df.columns:
        df["fav_margin"] = np.where(
            df["fav_is_home"],
            df["home_final"] - df["away_final"],
            df["away_final"] - df["home_final"],
        )

    # Cover: favorite wins by 2+
    df["covers"] = df["fav_margin"] >= 2

    # RL odds for fav -1.5
    # When home is fav (home_run_line == -1.5): home_run_line_odds is fav RL price
    # When away is fav (home_run_line == 1.5): away_run_line_odds is fav RL price
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

    # Universe: valid RL data only
    if "home_run_line" in df.columns:
        rl_valid = df["home_run_line"].isin([-1.5, 1.5])
    else:
        rl_valid = pd.Series(True, index=df.index)

    # Exclude Colorado + extreme lines
    if "involves_col" in df.columns:
        rl_valid = rl_valid & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        rl_valid = rl_valid & ~df["is_extreme_line"]

    rl = df[rl_valid].copy()

    # Fav-oriented features: flip diffs when away is favorite
    # Convention: positive = favorite is STRONGER
    flip = np.where(rl["fav_is_home"], 1, -1)

    diff_cols = [
        "rpi_diff", "elo_diff", "pyth_wp_diff",
        "starter_fip_diff", "starter_whip_diff",
        "offense_vs_league_diff", "rpg_diff",
        "hold_rate_diff", "close_game_wp_diff",
        "wp_last3_diff", "wp_last6_diff", "wp_last10_diff",
        "bullpen_fip_diff",
        "sp_wr_long_diff", "sp_ra_long_diff", "sp_ra_momentum_diff",
        "streak_diff",
    ]
    for col in diff_cols:
        if col in rl.columns:
            rl[f"fav_{col}"] = rl[col] * flip

    # Individual fav/dog columns
    for fav_col, home_col, away_col in [
        ("fav_rpg", "rpg_home", "rpg_away"),
        ("dog_rpg", "rpg_away", "rpg_home"),
        ("fav_offense_vs_league", "offense_vs_league_home", "offense_vs_league_away"),
        ("fav_hold_rate", "hold_rate_home", "hold_rate_away"),
        ("fav_close_game_wp", "close_game_wp_home", "close_game_wp_away"),
        ("fav_sp_ra", "home_sp_ra_short", "away_sp_ra_short"),
        ("dog_sp_ra", "away_sp_ra_short", "home_sp_ra_short"),
        ("fav_sp_wr_long", "home_sp_wr_long", "away_sp_wr_long"),
        ("dog_bp_ip_3d", "bp_ip_3d_away", "bp_ip_3d_home"),
        ("fav_bp_ip_3d", "bp_ip_3d_home", "bp_ip_3d_away"),
    ]:
        if home_col in rl.columns and away_col in rl.columns:
            rl[fav_col] = np.where(rl["fav_is_home"], rl[home_col], rl[away_col])

    # Implied prob of favorite
    if "home_implied_prob" in rl.columns and "away_implied_prob" in rl.columns:
        rl["fav_implied_prob"] = np.where(
            rl["fav_is_home"], rl["home_implied_prob"], rl["away_implied_prob"]
        )

    n_real = (rl["rl_odds"] != FAV_RL_FALLBACK).sum()
    n_home_fav = rl["fav_is_home"].sum()
    n_away_fav = (~rl["fav_is_home"]).sum()
    print(f"\nFav -1.5 universe: {len(rl)} games ({n_real} with real RL odds, {len(rl)-n_real} estimated)")
    print(f"  Home favorites: {n_home_fav}, Away favorites: {n_away_fav}")
    print(f"  Seasons: {sorted(rl['season'].unique())}")
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
    be = 1 / df["rl_odds"].mean() * 100
    print(f"All fav -1.5: {n} bets, cover {cr*100:.1f}%, avg odds {df['rl_odds'].mean():.3f}, "
          f"ROI {roi:+.1f}%, breakeven {be:.1f}%")

    # Implied prob bands (KEY hypothesis)
    print("\n  Implied probability bands (favorite ML strength):")
    if "fav_implied_prob" in df.columns:
        for lo, hi, label in [
            (0.55, 0.60, "55-60%"), (0.60, 0.65, "60-65%"),
            (0.65, 0.70, "65-70%"), (0.70, 0.75, "70-75%"),
            (0.75, 1.00, "75%+"),
        ]:
            mask = (df["fav_implied_prob"] >= lo) & (df["fav_implied_prob"] < hi)
            mb = df[mask]
            nm = len(mb)
            if nm < 15:
                continue
            mcr = mb["covers"].mean()
            mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
            mroi = mp.sum() / (nm * 100) * 100
            mbe = 1 / mb["rl_odds"].mean() * 100
            print(f"    {label:<12} {nm:5d}  cover {mcr*100:5.1f}%  odds {mb['rl_odds'].mean():.3f}  "
                  f"ROI {mroi:+6.1f}%  BE {mbe:.1f}%")

    # Edge bands (INVERTED: edge < 0 = fav underpriced)
    print("\n  Edge bands (negative = fav underpriced by model):")
    for lo, hi, label in [
        (None, -0.15, "edge < -0.15"), (-0.15, -0.10, "-0.15 <= edge < -0.10"),
        (-0.10, -0.07, "-0.10 <= edge < -0.07"), (-0.07, -0.05, "-0.07 <= edge < -0.05"),
        (-0.05, -0.03, "-0.05 <= edge < -0.03"), (-0.03, 0, "-0.03 <= edge < 0"),
        (0, 0.05, "0 <= edge < 0.05"), (0.05, None, "edge >= 0.05"),
    ]:
        if lo is None:
            mask = df["edge_consensus"] < hi
        elif hi is None:
            mask = df["edge_consensus"] >= lo
        else:
            mask = (df["edge_consensus"] >= lo) & (df["edge_consensus"] < hi)
        mb = df[mask]
        nm = len(mb)
        if nm < 15:
            continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label:<30} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Monthly
    print("\n  By month:")
    for m in sorted(df["month"].unique()):
        mb = df[df["month"] == m]
        nm = len(mb)
        if nm < 10:
            continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    Month {m:2d}: {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # 1H vs 2H
    print("\n  Half-season:")
    for half, label in [(True, "1H (pre-ASG)"), (False, "2H (post-ASG)")]:
        mb = df[df["is_first_half"] == half]
        nm = len(mb)
        if nm < 10:
            continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {label:<20} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # By season
    print("\n  By season:")
    for s in sorted(df["season"].unique()):
        mb = df[df["season"] == s]
        nm = len(mb)
        if nm < 10:
            continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {int(s)}: {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")


def _build_candidates(base):
    """Build filter candidates dict for single-filter scan."""
    candidates = {}

    # --- Primary: fav advantage (positive = fav stronger) ---

    # RPI diff (fav - dog)
    if "fav_rpi_diff" in base.columns:
        for t in [0.02, 0.03, 0.04, 0.05]:
            candidates[f"fav_rpi >= {t}"] = base["fav_rpi_diff"] >= t

    # Elo diff
    if "fav_elo_diff" in base.columns:
        for t in [20, 30, 40, 50]:
            candidates[f"fav_elo >= {t}"] = base["fav_elo_diff"] >= t

    # Pyth WP diff
    if "fav_pyth_wp_diff" in base.columns:
        for t in [0.03, 0.05, 0.07]:
            candidates[f"fav_pyth >= {t}"] = base["fav_pyth_wp_diff"] >= t

    # Starter FIP (negative = fav pitcher better, lower FIP)
    if "fav_starter_fip_diff" in base.columns:
        for t in [0, -0.3, -0.5, -0.8]:
            candidates[f"fav_fip_diff <= {t}"] = base["fav_starter_fip_diff"] <= t

    # Starter WHIP (negative = fav pitcher less leaky)
    if "fav_starter_whip_diff" in base.columns:
        for t in [0, -0.10, -0.20]:
            candidates[f"fav_whip_diff <= {t}"] = base["fav_starter_whip_diff"] <= t

    # SP WR long (positive = fav pitcher higher win rate)
    if "fav_sp_wr_long_diff" in base.columns:
        for t in [0.05, 0.10, 0.15, 0.20]:
            candidates[f"fav_sp_wr >= {t}"] = base["fav_sp_wr_long_diff"] >= t

    # SP RA long (negative = fav pitcher allows fewer runs)
    if "fav_sp_ra_long_diff" in base.columns:
        for t in [0, -0.5, -1.0]:
            candidates[f"fav_sp_ra_long <= {t}"] = base["fav_sp_ra_long_diff"] <= t

    # Offense vs league (fav team)
    if "fav_offense_vs_league" in base.columns:
        for t in [1.00, 1.05, 1.10, 1.15]:
            candidates[f"fav_off_vs_lg >= {t}"] = base["fav_offense_vs_league"] >= t

    # RPG of favorite
    if "fav_rpg" in base.columns:
        for t in [4.0, 4.5, 5.0]:
            candidates[f"fav_rpg >= {t}"] = base["fav_rpg"] >= t

    # --- Secondary ---

    # Dog bullpen tired
    if "dog_bp_ip_3d" in base.columns:
        med = base["dog_bp_ip_3d"].median()
        p75 = base["dog_bp_ip_3d"].quantile(0.75)
        candidates[f"dog_bp_3d > med ({med:.1f})"] = base["dog_bp_ip_3d"] > med
        candidates[f"dog_bp_3d > p75 ({p75:.1f})"] = base["dog_bp_ip_3d"] > p75

    # Fav hold rate (closes out leads)
    if "fav_hold_rate" in base.columns:
        for t in [0.70, 0.75, 0.80]:
            candidates[f"fav_hold >= {t}"] = base["fav_hold_rate"] >= t

    # SP RA momentum (negative = fav pitcher improving)
    if "fav_sp_ra_momentum_diff" in base.columns:
        for t in [0, -0.2, -0.5]:
            candidates[f"fav_sp_momentum <= {t}"] = base["fav_sp_ra_momentum_diff"] <= t

    # Close game WP (INVERSE: low = fav wins BIG, not close)
    if "fav_close_game_wp" in base.columns:
        for t in [0.55, 0.50, 0.45]:
            candidates[f"fav_close_wp <= {t} (big wins)"] = base["fav_close_game_wp"] <= t

    # Combined RPG (run environment)
    if "rpg_home" in base.columns and "rpg_away" in base.columns:
        comb = base["rpg_home"] + base["rpg_away"]
        for t in [8.5, 9.0, 9.5]:
            candidates[f"combined_rpg >= {t}"] = comb >= t

    # Implied prob band (sweet spot)
    if "fav_implied_prob" in base.columns:
        candidates["impl 60-70%"] = (base["fav_implied_prob"] >= 0.60) & (base["fav_implied_prob"] < 0.70)
        candidates["impl 62-69%"] = (base["fav_implied_prob"] >= 0.62) & (base["fav_implied_prob"] < 0.69)
        candidates["impl 65-72%"] = (base["fav_implied_prob"] >= 0.65) & (base["fav_implied_prob"] < 0.72)
        candidates["impl < 70%"] = base["fav_implied_prob"] < 0.70

    # Form
    if "fav_wp_last3_diff" in base.columns:
        for t in [0, 0.10, 0.20]:
            candidates[f"fav_wp3 >= {t}"] = base["fav_wp_last3_diff"] >= t

    if "fav_streak_diff" in base.columns:
        for t in [0, 1, 2]:
            candidates[f"fav_streak >= {t}"] = base["fav_streak_diff"] >= t

    # Bullpen FIP diff (negative = fav bullpen better)
    if "fav_bullpen_fip_diff" in base.columns:
        for t in [0, -0.3]:
            candidates[f"fav_bp_fip <= {t}"] = base["fav_bullpen_fip_diff"] <= t

    # Games played (season maturity)
    if "games_played_min" in base.columns:
        candidates["gp >= 30"] = base["games_played_min"] >= 30
        candidates["gp >= 50"] = base["games_played_min"] >= 50

    # Half season
    candidates["is_first_half"] = base["is_first_half"]
    candidates["is_second_half"] = ~base["is_first_half"]

    return candidates


def section2_singles(df):
    print(f"\n{'#'*80}")
    print("SECTION 2: SINGLE FILTERS")
    print(f"{'#'*80}")

    all_results = {}

    # --- Base A: ALL games ---
    print(f"\n  --- Base A: ALL GAMES ({len(df)} bets) ---")
    cands_a = _build_candidates(df)

    results_a = [eval_strat(df, "BASE A: all games")]
    for name, mask in cands_a.items():
        mask = mask.fillna(False)
        r = eval_strat(df[mask], name)
        if r:
            results_a.append(r)

    results_a.sort(key=lambda x: -x["roi"])
    ptable(results_a, "BASE A — SINGLE FILTERS (no edge filter)")

    # --- Base B: edge < -0.05 ---
    base_b = df[df["edge_consensus"] < -0.05].copy()
    print(f"\n  --- Base B: EDGE < -0.05 ({len(base_b)} bets) ---")
    cands_b = _build_candidates(base_b)

    # Also test deeper edge thresholds
    cands_b["edge < -0.07"] = base_b["edge_consensus"] < -0.07
    cands_b["edge < -0.10"] = base_b["edge_consensus"] < -0.10
    cands_b["edge < -0.15"] = base_b["edge_consensus"] < -0.15

    results_b = [eval_strat(base_b, "BASE B: edge < -0.05")]
    for name, mask in cands_b.items():
        mask = mask.fillna(False)
        r = eval_strat(base_b[mask], f"B:{name}")
        if r:
            results_b.append(r)

    results_b.sort(key=lambda x: -x["roi"])
    ptable(results_b, "BASE B — SINGLE FILTERS (edge < -0.05)")

    all_results = {"A": (df, cands_a, results_a), "B": (base_b, cands_b, results_b)}
    return all_results


def section3_combos(all_singles):
    print(f"\n{'#'*80}")
    print("SECTION 3: 2-WAY COMBOS")
    print(f"{'#'*80}")

    all_combos = {}

    for base_label, (base, candidates, single_results) in all_singles.items():
        prefix = "" if base_label == "A" else "B:"
        top_names = [r["filter"] for r in single_results
                     if r["roi"] > 0 and not r["filter"].startswith("BASE")][:12]

        if len(top_names) < 2:
            print(f"\n  Base {base_label}: Not enough positive-ROI singles for combos.")
            all_combos[base_label] = []
            continue

        combo_results = []
        for f1, f2 in combinations(top_names, 2):
            # Strip prefix for candidate lookup
            k1 = f1[2:] if f1.startswith("B:") else f1
            k2 = f2[2:] if f2.startswith("B:") else f2
            m1 = candidates.get(k1, pd.Series(False, index=base.index)).fillna(False)
            m2 = candidates.get(k2, pd.Series(False, index=base.index)).fillna(False)
            r = eval_strat(base[m1 & m2], f"{prefix}{k1} + {k2}")
            if r:
                combo_results.append(r)

        combo_results.sort(key=lambda x: -x["roi"])
        ptable(combo_results[:20], f"BASE {base_label} — TOP 2-WAY COMBOS")
        all_combos[base_label] = combo_results

    return all_combos


def section4_train_test(df, all_singles, all_combos):
    print(f"\n{'#'*80}")
    print("SECTION 4: TRAIN / TEST VALIDATION")
    print(f"{'#'*80}")

    train = df[df["season"].isin(range(2010, 2018))].copy()
    test = df[df["season"].isin([2018, 2019, 2021])].copy()

    print(f"\n  TRAIN: {len(train)} games, seasons {sorted(train['season'].unique())}")
    print(f"  TEST:  {len(test)} games, seasons {sorted(test['season'].unique())}")

    # Collect top strategies from both bases
    top_strats = []
    for base_label in ["A", "B"]:
        base, candidates, singles = all_singles[base_label]
        combos = all_combos.get(base_label, [])

        # Top 3 singles + top 3 combos
        for r in singles[:3]:
            if r["roi"] > 0 and not r["filter"].startswith("BASE"):
                top_strats.append((base_label, r["filter"], candidates))
        for r in combos[:3]:
            if r["roi"] > 0:
                top_strats.append((base_label, r["filter"], candidates))

    if not top_strats:
        print("  No positive-ROI strategies to validate.")
        return

    for base_label, name, candidates in top_strats:
        # Parse filter names from combo string
        prefix = "B:" if base_label == "B" else ""
        clean = name[2:] if name.startswith("B:") else name

        # Build mask from filter name(s)
        parts = clean.split(" + ")
        for split_label, split_df in [("TRAIN", train), ("TEST", test)]:
            # Apply edge filter for base B
            if base_label == "B":
                sub = split_df[split_df["edge_consensus"] < -0.05].copy()
            else:
                sub = split_df.copy()

            # Apply individual filters
            mask = pd.Series(True, index=sub.index)
            valid = True
            for part in parts:
                cands = _build_candidates(sub)
                if base_label == "B":
                    cands["edge < -0.07"] = sub["edge_consensus"] < -0.07
                    cands["edge < -0.10"] = sub["edge_consensus"] < -0.10
                    cands["edge < -0.15"] = sub["edge_consensus"] < -0.15
                if part in cands:
                    mask = mask & cands[part].fillna(False)
                else:
                    valid = False
                    break

            if not valid:
                continue
            r = eval_strat(sub[mask], f"[{split_label}] {prefix}{clean}")
            if r:
                rois_str = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(f"  {r['filter']:<60} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                      f"ROI {r['roi']:+6.1f}%  [{rois_str}]")


def section5_summary(df, all_singles, all_combos):
    print(f"\n{'#'*80}")
    print("SECTION 5: SUMMARY")
    print(f"{'#'*80}")

    # Collect all results
    all_results = []
    for base_label in ["A", "B"]:
        _, _, singles = all_singles[base_label]
        combos = all_combos.get(base_label, [])
        all_results.extend(singles)
        all_results.extend(combos)

    viable = []
    for r in all_results:
        if r is None:
            continue
        if r["roi"] > 0 and r["bets"] >= 30 and not r["filter"].startswith("BASE"):
            folds = r["folds_pos"].split("/")
            if len(folds) == 2 and int(folds[0]) >= 3:
                viable.append(r)

    # Deduplicate
    seen = set()
    unique = []
    for r in viable:
        if r["filter"] not in seen:
            seen.add(r["filter"])
            unique.append(r)
    viable = unique

    viable.sort(key=lambda x: -x["sharpe"])
    ptable(viable[:20], "VIABLE STRATEGIES (ROI>0, bets>=30, folds>=3)")

    if viable:
        best = viable[0]
        rois_str = ", ".join(f"{x:+.0f}" for x in best["season_rois"])
        print(f"\n  BEST: {best['filter']}")
        print(f"    {best['bets']} bets ({best['bps']:.0f}/s)  Cover {best['cr']*100:.1f}%  ROI {best['roi']:+.1f}%")
        print(f"    Sharpe {best['sharpe']:.3f}  Kelly/2 {best['kelly_half']*100:.2f}%  MaxL {best['max_ls']}")
        print(f"    Seasons: [{rois_str}]")

    print(f"\n  Context (other systems):")
    print(f"    S3-dual (away ML): ~44 bets/season, +17.9% ROI, Sharpe 0.98")
    print(f"    Away +1.5 best: DEAD (real odds -6.7% baseline)")
    be = 1 / df["rl_odds"].mean() * 100
    print(f"    Fav -1.5 baseline: cover {df['covers'].mean()*100:.1f}%, breakeven {be:.1f}%")

    return viable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = build_dataset()
    section1_baseline(df)
    all_singles = section2_singles(df)
    all_combos = section3_combos(all_singles)
    section4_train_test(df, all_singles, all_combos)
    section5_summary(df, all_singles, all_combos)


if __name__ == "__main__":
    main()
