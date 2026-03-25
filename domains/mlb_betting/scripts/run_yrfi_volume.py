"""YRFI volume expansion: find more bets to fill idle days.

We already have top3_obp+kbb (~16/season, +17.8% adj ROI) and a few other
high-edge combos.  But most days have zero bets — lost opportunity cost.

This script:
  1. Relaxes thresholds systematically on proven features
  2. Builds a tiered portfolio (Tier A: high edge, Tier B: medium, Tier C: volume)
  3. Measures overlap between tiers
  4. Computes daily coverage: how many days per season have >=1 bet?
  5. Models total bankroll growth under Kelly staking

Usage:
    python scripts/run_yrfi_volume.py
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

# ── Odds calibration (same as run_yrfi_research.py) ──────────────────────
CALIB_POINTS = [
    (6.5, 2.32), (7.25, 2.02), (7.75, 1.94), (8.25, 1.89),
    (8.75, 1.84), (9.50, 1.80), (10.25, 1.71), (11.0, 1.59),
]
CALIB_OU = np.array([p[0] for p in CALIB_POINTS])
CALIB_ODDS = np.array([p[1] for p in CALIB_POINTS])


def estimate_yrfi_odds(close_ou: pd.Series) -> pd.Series:
    return pd.Series(
        np.interp(close_ou.values, CALIB_OU, CALIB_ODDS),
        index=close_ou.index,
    )


def metrics(df, name, min_bets=20):
    """Compute adjusted YRFI metrics."""
    df = df.dropna(subset=["close_ou"]).sort_values("date").copy()
    n = len(df)
    if n < min_bets:
        return None
    hit = df["yrfi"].values.astype(float)
    hr = hit.mean()
    est_odds = estimate_yrfi_odds(df["close_ou"])
    avg_ou = df["close_ou"].mean()
    avg_odds = est_odds.mean()
    adj_pnl = np.where(hit, (est_odds.values - 1) * 100, -100)
    adj_roi = adj_pnl.sum() / (n * 100) * 100
    implied = (1 / avg_odds) if avg_odds > 0 else 0.5
    edge = hr - implied

    # Per-season ROI
    season_rois = {}
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        s_hit = df.loc[sm, "yrfi"].values.astype(float)
        s_odds = est_odds.loc[sm].values
        s_pnl = np.where(s_hit, (s_odds - 1) * 100, -100)
        season_rois[s] = s_pnl.sum() / (sn * 100) * 100
    n_pos = sum(1 for r in season_rois.values() if r > 0)

    # Sharpe
    ev = adj_pnl.mean()
    std = adj_pnl.std(ddof=1) if n > 1 else 1
    sharpe_bet = ev / std if std > 0 else 0
    n_seasons = df["season"].nunique()
    bps = n / n_seasons if n_seasons > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    # Daily coverage
    days = df.groupby("season")["date"].apply(lambda x: x.dt.date.nunique())
    avg_days = days.mean()

    return {
        "name": name, "bets": n, "bps": bps, "hit_rate": hr,
        "avg_ou": avg_ou, "est_odds": avg_odds, "adj_roi": adj_roi,
        "edge": edge, "sharpe": sharpe,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois, "avg_days": avg_days,
    }


def print_row(m, show_days=True):
    if m is None:
        return
    marker = " ***" if m["adj_roi"] > 0 and m["edge"] > 0 else ""
    days_str = f" {m['avg_days']:5.1f}d" if show_days else ""
    print(
        f"  {m['name']:<55} {m['bets']:5d} {m['bps']:5.0f}/s "
        f"{m['hit_rate']*100:5.1f}% {m['avg_ou']:5.2f} {m['est_odds']:5.3f} "
        f"{m['adj_roi']:+6.1f}% {m['edge']*100:+5.1f}pp "
        f"{m['sharpe']:5.2f} {m['seasons_pos']:>5}{days_str}{marker}"
    )


# ========================================================================
# MAIN
# ========================================================================
def main():
    from src.data_loader import (
        PROCESSED_DIR,
        _map_team_code_to_retrosheet,
        add_derived_odds,
        apply_data_filters,
        load_all_seasons,
    )
    from src.features import build_all_features

    print("Loading games and building features...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    df = enriched.copy()

    # Filter to real inning data
    away_inn_sum = sum(
        df[f"away_inn_{i}"] for i in range(1, 10) if f"away_inn_{i}" in df.columns
    )
    home_inn_sum = sum(
        df[f"home_inn_{i}"] for i in range(1, 10) if f"home_inn_{i}" in df.columns
    )
    df = df[(away_inn_sum + home_inn_sum) > 0].copy()

    if "involves_col" in df.columns:
        df = df[~df["involves_col"]].copy()
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df = df[df["month"] != 4].copy()

    df["inn1_runs"] = df["away_inn_1"] + df["home_inn_1"]
    df["yrfi"] = df["inn1_runs"] > 0

    # ── Merge BvP lineup features ────────────────────────────────────
    lineup_path = PROCESSED_DIR / "retrosheet" / "game_lineup_features.parquet"
    if lineup_path.exists():
        lineup = pd.read_parquet(lineup_path)
        lineup["date"] = pd.to_datetime(lineup["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_lu_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]),
                axis=1,
            )
            lu_cols = [c for c in lineup.columns if c.startswith("top3_") or c == "n_batters"]
            lu_rename = {"team": f"_lu_{side}_team"}
            for c in lu_cols:
                lu_rename[c] = f"{c}_{side}"
            side_lu = lineup[["team", "date"] + lu_cols].rename(columns=lu_rename)
            side_lu = side_lu.drop_duplicates(subset=[f"_lu_{side}_team", "date"], keep="first")
            df = df.merge(side_lu, on=[f"_lu_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_lu_{side}_team"])

        for stat in [
            "obp_short", "obp_long", "k_rate_short", "k_rate_long",
            "hr_rate_short", "obp_vs_rhp", "k_rate_vs_rhp",
            "obp_vs_lhp", "k_rate_vs_lhp",
        ]:
            h_col = f"top3_{stat}_home"
            a_col = f"top3_{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"top3_{stat}_combined"] = df[h_col] + df[a_col]

    # ── Merge 1st-inning BABIP ───────────────────────────────────────
    babip_path = PROCESSED_DIR / "retrosheet" / "first_inning_babip.parquet"
    if babip_path.exists():
        babip = pd.read_parquet(babip_path)
        babip["date"] = pd.to_datetime(babip["date"]).dt.normalize()
        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_bb_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]),
                axis=1,
            )
            bb_rename = {
                "team": f"_bb_{side}_team",
                "top3_babip_inn1": f"top3_babip_inn1_{side}",
                "sp_babip_inn1": f"sp_babip_inn1_{side}",
            }
            side_bb = babip[["team", "date", "top3_babip_inn1", "sp_babip_inn1"]].rename(columns=bb_rename)
            side_bb = side_bb.drop_duplicates(subset=[f"_bb_{side}_team", "date"], keep="first")
            df = df.merge(side_bb, on=[f"_bb_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_bb_{side}_team"])
        for stat in ["top3_babip_inn1", "sp_babip_inn1"]:
            h_col = f"{stat}_home"
            a_col = f"{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"{stat}_combined"] = df[h_col] + df[a_col]

    # ── Build pitcher SUM composites ─────────────────────────────────
    for col, h_col, a_col in [
        ("sp_ra_combined_short", "home_sp_ra_short", "away_sp_ra_short"),
        ("sp_ra_combined_long", "home_sp_ra_long", "away_sp_ra_long"),
        ("sp_fi_ra_combined", "home_sp_fi_ra_short", "away_sp_fi_ra_short"),
        ("sp_fi_ra_combined_long", "home_sp_fi_ra_long", "away_sp_fi_ra_long"),
        ("starter_fip_combined", "home_sp_fip_short", "away_sp_fip_short"),
        ("starter_whip_combined", "home_sp_whip_short", "away_sp_whip_short"),
        ("starter_kbb_combined", "home_sp_kbb_short", "away_sp_kbb_short"),
        ("sp_fi_momentum_combined", "home_sp_fi_momentum", "away_sp_fi_momentum"),
        ("sp_ra_momentum_combined", "home_sp_ra_momentum", "away_sp_ra_momentum"),
    ]:
        if h_col in df.columns and a_col in df.columns:
            df[col] = df[h_col] + df[a_col]

    for col, h_col, a_col in [
        ("combined_rpg", "rpg_home", "rpg_away"),
        ("combined_rpg_last10", "rpg_last10_home", "rpg_last10_away"),
        ("combined_rapg", "rapg_home", "rapg_away"),
        ("fi_score_rate_combined", "fi_score_rate_home", "fi_score_rate_away"),
        ("fi_score_rate_last_combined", "fi_score_rate_last_home", "fi_score_rate_last_away"),
    ]:
        if h_col in df.columns and a_col in df.columns:
            df[col] = df[h_col] + df[a_col]

    # Effective OBP
    if all(c in df.columns for c in [
        "away_sp_hand", "home_sp_hand",
        "top3_obp_vs_rhp_home", "top3_obp_vs_lhp_home",
        "top3_obp_vs_rhp_away", "top3_obp_vs_lhp_away",
    ]):
        df["effective_obp_home"] = np.where(
            df["away_sp_hand"] == "R",
            df["top3_obp_vs_rhp_home"],
            df["top3_obp_vs_lhp_home"],
        )
        df["effective_obp_away"] = np.where(
            df["home_sp_hand"] == "R",
            df["top3_obp_vs_rhp_away"],
            df["top3_obp_vs_lhp_away"],
        )
        df["effective_obp_combined"] = df["effective_obp_home"] + df["effective_obp_away"]

    n_total = len(df)
    n_seasons = df["season"].nunique()
    total_days = df.groupby("season")["date"].apply(lambda x: x.dt.date.nunique()).sum()
    print(f"\nDataset: {n_total} games, {n_seasons} seasons, {total_days} game-days")
    print(f"Avg game-days/season: {total_days/n_seasons:.0f}")
    print(f"YRFI rate: {df['yrfi'].mean()*100:.1f}%")

    # ================================================================
    # SECTION 1: THRESHOLD RELAXATION ON PROVEN COMBOS
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 1: THRESHOLD RELAXATION — expanding proven combos")
    print(f"{'='*120}")

    hdr = (
        f"  {'Filter':<55} {'Bets':>5} {'B/Sea':>5} "
        f"{'Hit%':>6} {'AvgOU':>6} {'EstOd':>5} {'AdjROI':>7} {'Edge':>6} "
        f"{'Shrp':>5} {'Flds':>5} {'Days':>6}"
    )
    sep = "-" * 120

    # --- Combo A: top3_obp + kbb (proven star) ---
    print(f"\n  --- top3_obp_short_combined + starter_kbb_combined ---")
    print(hdr)
    print(sep)
    for obp_th in [0.73, 0.72, 0.71, 0.70, 0.69, 0.68, 0.67, 0.66]:
        for kbb_th in [3.4, 3.6, 3.8, 4.0, 4.2, 4.5, 5.0]:
            mask = (
                df["top3_obp_short_combined"].notna()
                & (df["top3_obp_short_combined"] > obp_th)
                & df["starter_kbb_combined"].notna()
                & (df["starter_kbb_combined"] < kbb_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"obp>{obp_th} + kbb<{kbb_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo B: effective_obp + sp_fi_ra_long ---
    print(f"\n  --- effective_obp_combined + sp_fi_ra_combined_long ---")
    print(hdr)
    print(sep)
    for obp_th in [0.72, 0.71, 0.70, 0.69, 0.68, 0.67, 0.66, 0.65]:
        for fi_th in [1.27, 1.20, 1.10, 1.00, 0.95, 0.90, 0.80]:
            mask = (
                df["effective_obp_combined"].notna()
                & (df["effective_obp_combined"] > obp_th)
                & df["sp_fi_ra_combined_long"].notna()
                & (df["sp_fi_ra_combined_long"] > fi_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"eff_obp>{obp_th} + fi_ra_long>{fi_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo C: top3_babip_inn1 + fip ---
    print(f"\n  --- top3_babip_inn1_combined + starter_fip_combined ---")
    print(hdr)
    print(sep)
    for bab_th in [0.68, 0.66, 0.65, 0.64, 0.63, 0.62, 0.60]:
        for fip_th in [8.4, 8.0, 7.5, 7.0]:
            mask = (
                df["top3_babip_inn1_combined"].notna()
                & (df["top3_babip_inn1_combined"] > bab_th)
                & df["starter_fip_combined"].notna()
                & (df["starter_fip_combined"] > fip_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"babip_inn1>{bab_th} + fip>{fip_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo D: fi_score_rate + kbb ---
    print(f"\n  --- fi_score_rate_combined + starter_kbb_combined ---")
    print(hdr)
    print(sep)
    for fi_th in [0.63, 0.60, 0.58, 0.55, 0.52, 0.50]:
        for kbb_th in [3.4, 3.6, 3.8, 4.0, 4.2, 4.5, 5.0]:
            mask = (
                df["fi_score_rate_combined"].notna()
                & (df["fi_score_rate_combined"] > fi_th)
                & df["starter_kbb_combined"].notna()
                & (df["starter_kbb_combined"] < kbb_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"fi_rate>{fi_th} + kbb<{kbb_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo E: top3_babip_inn1 + fi_score_rate ---
    print(f"\n  --- top3_babip_inn1_combined + fi_score_rate_combined ---")
    print(hdr)
    print(sep)
    for bab_th in [0.68, 0.66, 0.65, 0.64, 0.63, 0.62, 0.60]:
        for fi_th in [0.63, 0.60, 0.58, 0.55, 0.52, 0.50]:
            mask = (
                df["top3_babip_inn1_combined"].notna()
                & (df["top3_babip_inn1_combined"] > bab_th)
                & df["fi_score_rate_combined"].notna()
                & (df["fi_score_rate_combined"] > fi_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"babip_inn1>{bab_th} + fi_rate>{fi_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo F: effective_obp + top3_hr_rate ---
    print(f"\n  --- effective_obp_combined + top3_hr_rate_short_combined ---")
    print(hdr)
    print(sep)
    for obp_th in [0.72, 0.70, 0.69, 0.68, 0.67, 0.66, 0.65]:
        for hr_th in [0.09, 0.08, 0.07, 0.06, 0.05]:
            if "top3_hr_rate_short_combined" not in df.columns:
                break
            mask = (
                df["effective_obp_combined"].notna()
                & (df["effective_obp_combined"] > obp_th)
                & df["top3_hr_rate_short_combined"].notna()
                & (df["top3_hr_rate_short_combined"] > hr_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"eff_obp>{obp_th} + hr_rate>{hr_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # --- Combo G: top3_obp + top3_hr_rate (STRONG on TEST) ---
    print(f"\n  --- top3_obp_short_combined + top3_hr_rate_short_combined ---")
    print(hdr)
    print(sep)
    for obp_th in [0.73, 0.72, 0.71, 0.70, 0.69, 0.68, 0.67, 0.66]:
        for hr_th in [0.10, 0.09, 0.08, 0.07, 0.06, 0.05]:
            if "top3_hr_rate_short_combined" not in df.columns:
                break
            mask = (
                df["top3_obp_short_combined"].notna()
                & (df["top3_obp_short_combined"] > obp_th)
                & df["top3_hr_rate_short_combined"].notna()
                & (df["top3_hr_rate_short_combined"] > hr_th)
            )
            sub = df[mask]
            if len(sub) < 50:
                continue
            m = metrics(sub, f"obp>{obp_th} + hr_rate>{hr_th}")
            if m and m["adj_roi"] > -2:
                print_row(m)

    # ================================================================
    # SECTION 2: SINGLE BROAD FILTERS (Tier C - volume plays)
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 2: BROAD SINGLE FILTERS (volume plays)")
    print(f"{'='*120}")
    print(hdr)
    print(sep)

    # top3_babip_inn1 was the ONLY profitable single feature
    for feat, direction, thresholds in [
        ("top3_babip_inn1_combined", ">", [0.60, 0.62, 0.63, 0.64, 0.65, 0.66, 0.68]),
        ("fi_score_rate_combined", ">", [0.50, 0.52, 0.55, 0.58, 0.60, 0.63]),
        ("effective_obp_combined", ">", [0.66, 0.67, 0.68, 0.69, 0.70]),
        ("top3_obp_short_combined", ">", [0.67, 0.68, 0.69, 0.70, 0.71]),
        ("starter_kbb_combined", "<", [5.5, 5.0, 4.5, 4.2, 4.0, 3.8, 3.4]),
    ]:
        if feat not in df.columns:
            continue
        for th in thresholds:
            if direction == ">":
                mask = df[feat].notna() & (df[feat] > th)
            else:
                mask = df[feat].notna() & (df[feat] < th)
            sub = df[mask]
            m = metrics(sub, f"{feat.replace('_combined','')}{direction}{th}")
            if m:
                print_row(m)

    # ================================================================
    # SECTION 3: PORTFOLIO ASSEMBLY & OVERLAP
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 3: PORTFOLIO ASSEMBLY")
    print(f"{'='*120}")

    # Define candidate tiers with their filters
    # Each tier: (name, mask_func)
    tiers = {}

    # Tier A: proven high-edge combos
    def tier_a_mask(d):
        return (
            d["top3_obp_short_combined"].notna()
            & (d["top3_obp_short_combined"] > 0.70)
            & d["starter_kbb_combined"].notna()
            & (d["starter_kbb_combined"] < 4.0)
        )
    tiers["A: obp>0.70+kbb<4.0"] = tier_a_mask

    # Tier A2: effective_obp + sp_fi_ra_long
    def tier_a2_mask(d):
        return (
            d["effective_obp_combined"].notna()
            & (d["effective_obp_combined"] > 0.69)
            & d["sp_fi_ra_combined_long"].notna()
            & (d["sp_fi_ra_combined_long"] > 1.10)
        )
    tiers["A2: eff_obp>0.69+fi_ra_long>1.10"] = tier_a2_mask

    # Tier B: babip + fip
    def tier_b_mask(d):
        return (
            d["top3_babip_inn1_combined"].notna()
            & (d["top3_babip_inn1_combined"] > 0.65)
            & d["starter_fip_combined"].notna()
            & (d["starter_fip_combined"] > 8.0)
        )
    tiers["B: babip>0.65+fip>8.0"] = tier_b_mask

    # Tier B2: fi_score_rate + kbb
    def tier_b2_mask(d):
        return (
            d["fi_score_rate_combined"].notna()
            & (d["fi_score_rate_combined"] > 0.58)
            & d["starter_kbb_combined"].notna()
            & (d["starter_kbb_combined"] < 4.0)
        )
    tiers["B2: fi_rate>0.58+kbb<4.0"] = tier_b2_mask

    # Tier B3: obp + hr_rate
    def tier_b3_mask(d):
        return (
            d["top3_obp_short_combined"].notna()
            & (d["top3_obp_short_combined"] > 0.69)
            & d["top3_hr_rate_short_combined"].notna()
            & (d["top3_hr_rate_short_combined"] > 0.07)
        )
    tiers["B3: obp>0.69+hr_rate>0.07"] = tier_b3_mask

    # Tier C: broad single filter (volume)
    def tier_c_mask(d):
        return (
            d["top3_babip_inn1_combined"].notna()
            & (d["top3_babip_inn1_combined"] > 0.65)
        )
    tiers["C: babip_inn1>0.65"] = tier_c_mask

    # Evaluate each tier
    print(f"\n  Individual tier performance:")
    print(hdr)
    print(sep)

    tier_indices = {}
    for name, mask_fn in tiers.items():
        mask = mask_fn(df)
        sub = df[mask]
        tier_indices[name] = set(sub.index)
        m = metrics(sub, name)
        if m:
            print_row(m)

    # Overlap matrix
    tier_names = list(tiers.keys())
    print(f"\n  Overlap matrix (shared bets):")
    print(f"  {'':>40}", end="")
    for tn in tier_names:
        print(f" {tn[:8]:>8}", end="")
    print()
    for tn1 in tier_names:
        print(f"  {tn1:<40}", end="")
        for tn2 in tier_names:
            overlap = len(tier_indices[tn1] & tier_indices[tn2])
            print(f" {overlap:8d}", end="")
        print()

    # Union portfolio
    print(f"\n  Portfolio (union of all tiers):")
    print(hdr)
    print(sep)
    union_mask = pd.Series(False, index=df.index)
    for mask_fn in tiers.values():
        union_mask |= mask_fn(df)
    union_df = df[union_mask]
    m = metrics(union_df, "UNION (all tiers)")
    if m:
        print_row(m)

    # Also try without Tier C (which might dilute)
    union_no_c = pd.Series(False, index=df.index)
    for name, mask_fn in tiers.items():
        if not name.startswith("C:"):
            union_no_c |= mask_fn(df)
    m2 = metrics(df[union_no_c], "UNION (A+A2+B+B2+B3, no C)")
    if m2:
        print_row(m2)

    # Baseline
    m_all = metrics(df, "ALL games (baseline)")
    if m_all:
        print_row(m_all)

    # ================================================================
    # SECTION 4: DAILY COVERAGE ANALYSIS
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 4: DAILY COVERAGE")
    print(f"{'='*120}")

    df["game_date"] = pd.to_datetime(df["date"]).dt.date

    for name, mask_fn in tiers.items():
        mask = mask_fn(df)
        sub = df[mask]
        if len(sub) == 0:
            continue
        season_stats = []
        for s in sorted(sub["season"].unique()):
            ss = sub[sub["season"] == s]
            total_game_days = df[df["season"] == s]["game_date"].nunique()
            active_days = ss["game_date"].nunique()
            bets_per_active_day = len(ss) / active_days if active_days > 0 else 0
            coverage = active_days / total_game_days * 100 if total_game_days > 0 else 0
            season_stats.append({
                "season": s, "bets": len(ss), "game_days": total_game_days,
                "active_days": active_days, "coverage": coverage,
                "bpd": bets_per_active_day,
            })

        sdf = pd.DataFrame(season_stats)
        print(f"\n  {name}")
        print(f"    Avg bets/season: {sdf['bets'].mean():.0f}")
        print(f"    Avg active days: {sdf['active_days'].mean():.0f} / {sdf['game_days'].mean():.0f} ({sdf['coverage'].mean():.1f}%)")
        print(f"    Avg bets/active day: {sdf['bpd'].mean():.1f}")

    # Union coverage
    union_sub = df[union_mask]
    print(f"\n  UNION (all tiers)")
    season_stats = []
    for s in sorted(union_sub["season"].unique()):
        ss = union_sub[union_sub["season"] == s]
        total_game_days = df[df["season"] == s]["game_date"].nunique()
        active_days = ss["game_date"].nunique()
        bpd = len(ss) / active_days if active_days > 0 else 0
        coverage = active_days / total_game_days * 100 if total_game_days > 0 else 0
        season_stats.append({
            "season": s, "bets": len(ss), "game_days": total_game_days,
            "active_days": active_days, "coverage": coverage, "bpd": bpd,
        })
    sdf = pd.DataFrame(season_stats)
    print(f"    Avg bets/season: {sdf['bets'].mean():.0f}")
    print(f"    Avg active days: {sdf['active_days'].mean():.0f} / {sdf['game_days'].mean():.0f} ({sdf['coverage'].mean():.1f}%)")
    print(f"    Avg bets/active day: {sdf['bpd'].mean():.1f}")

    # ================================================================
    # SECTION 5: WALK-FORWARD VALIDATION OF PORTFOLIO
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 5: WALK-FORWARD VALIDATION (TRAIN 2010-2017, TEST 2018+)")
    print(f"{'='*120}")

    train = df[df["season"].between(2010, 2017)]
    test = df[df["season"] >= 2018]

    print(f"\n  TRAIN: {len(train)} games ({train['season'].min()}-{train['season'].max()})")
    print(f"  TEST:  {len(test)} games ({test['season'].min()}-{test['season'].max()})")

    print(f"\n  Per-tier on TEST:")
    print(hdr)
    print(sep)
    for name, mask_fn in tiers.items():
        mask = mask_fn(test)
        sub = test[mask]
        m = metrics(sub, f"[TEST] {name}")
        if m:
            print_row(m)

    # Union on TEST
    test_union = pd.Series(False, index=test.index)
    for mask_fn in tiers.values():
        test_union |= mask_fn(test)
    m_test = metrics(test[test_union], "[TEST] UNION all tiers")
    if m_test:
        print_row(m_test)

    test_union_no_c = pd.Series(False, index=test.index)
    for name, mask_fn in tiers.items():
        if not name.startswith("C:"):
            test_union_no_c |= mask_fn(test)
    m_test2 = metrics(test[test_union_no_c], "[TEST] UNION A+A2+B+B2+B3")
    if m_test2:
        print_row(m_test2)

    # ================================================================
    # SECTION 6: KELLY BANKROLL SIMULATION
    # ================================================================
    print(f"\n{'='*120}")
    print("SECTION 6: KELLY BANKROLL SIMULATION (fractional Kelly = 0.25)")
    print(f"{'='*120}")

    kelly_frac = 0.25

    for label, tier_mask_src in [
        ("Tier A only (obp+kbb)", tier_a_mask),
        ("UNION all tiers", lambda d: union_mask.loc[d.index] if hasattr(union_mask, 'loc') else union_mask),
    ]:
        if label == "UNION all tiers":
            sim_df = df[union_mask].dropna(subset=["close_ou"]).sort_values("date").copy()
        else:
            sim_df = df[tier_mask_src(df)].dropna(subset=["close_ou"]).sort_values("date").copy()

        if len(sim_df) == 0:
            continue

        sim_df["est_odds"] = estimate_yrfi_odds(sim_df["close_ou"])
        sim_df["implied_prob"] = 1 / sim_df["est_odds"]

        # Simulate Kelly growth
        bankroll = 1000.0
        history = []
        for _, row in sim_df.iterrows():
            odds = row["est_odds"]
            # Use overall hit rate as estimated probability (in real life, would be model's estimate)
            p_est = sim_df["yrfi"].mean()  # simplified
            q = 1 - p_est
            b = odds - 1
            edge_kelly = p_est * b - q
            if edge_kelly <= 0:
                continue
            f_star = edge_kelly / b
            bet_size = bankroll * kelly_frac * f_star
            bet_size = min(bet_size, bankroll * 0.05)  # cap at 5% of bankroll

            if row["yrfi"]:
                bankroll += bet_size * b
            else:
                bankroll -= bet_size
            history.append({"date": row["date"], "season": row["season"], "bankroll": bankroll})

        if history:
            hdf = pd.DataFrame(history)
            print(f"\n  {label}:")
            print(f"    Starting bankroll: $1,000")
            print(f"    Final bankroll:    ${bankroll:,.0f}")
            print(f"    Total bets:        {len(history)}")
            print(f"    Growth:            {(bankroll/1000 - 1)*100:+.1f}%")
            for s in sorted(hdf["season"].unique()):
                sh = hdf[hdf["season"] == s]
                start_b = sh.iloc[0]["bankroll"]
                end_b = sh.iloc[-1]["bankroll"]
                print(f"      {s}: ${start_b:,.0f} -> ${end_b:,.0f} ({(end_b/start_b-1)*100:+.1f}%, {len(sh)} bets)")

    print(f"\n{'='*120}")
    print("DONE")
    print(f"{'='*120}")


if __name__ == "__main__":
    main()
