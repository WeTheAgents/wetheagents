"""May-June deep dive: find the key to unlock S3 in early season."""

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


def max_ls(outcomes):
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def eval_filter(data, name):
    n = len(data)
    if n < 10:
        return None
    wr = data["dog_won"].mean()
    pnl = np.where(data["dog_won"], (data["dog_decimal"] - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    ml = max_ls(data.sort_values("date")["dog_won"].values)
    cum = np.cumsum(pnl)
    bk = 10000 + cum
    pk = np.maximum.accumulate(bk)
    mdd = ((pk - bk) / pk * 100).max()
    return {"filter": name, "bets": n, "wr": wr, "roi": roi, "max_ls": ml, "max_dd": mdd}


def main():
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    print("Building spec features (includes September now)...")
    full = build_spec_features()
    print(f"Games: {len(full)}")

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    print("Running walk-forward...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    # Merge features back
    merge_keys = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    # Keep target + all feature columns
    keep_cols = [c for c in full.columns if c not in div.columns or c in merge_keys]
    full_sub = full[keep_cols].drop_duplicates(subset=merge_keys)
    df = div.merge(full_sub, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # S3 setup
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0
    away_dog = df[df["fav_is_home"]].copy()
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]
    away_dog["dog_won"] = ~away_dog["fav_won"]

    base = away_dog["edge_consensus"] < -0.05
    rpi_ok = away_dog["rpi_diff"] <= 0
    elo_ok = away_dog["elo_diff"] <= 30
    s3 = away_dog[base & rpi_ok & elo_ok].sort_values("date").copy()
    s3["pnl"] = np.where(s3["dog_won"], (s3["dog_decimal"] - 1) * 100, -100)

    # Full season baseline
    n = len(s3)
    print(f"\n=== S3 FULL SEASON (with Sep) ===")
    print(f"Bets: {n}, WR: {s3['dog_won'].mean()*100:.1f}%, ROI: {s3['pnl'].sum()/(n*100)*100:+.1f}%")

    by_month = []
    for m in sorted(s3["month"].unique()):
        mb = s3[s3["month"] == m]
        nm = len(mb)
        if nm < 3:
            continue
        wr = mb["dog_won"].mean()
        roi = mb["pnl"].sum() / (nm * 100) * 100
        ml = max_ls(mb["dog_won"].values)
        by_month.append({"month": m, "bets": nm, "wr": wr, "roi": roi, "max_ls": ml})
        print(f"  Month {m:2d}: {nm:4d} bets  WR {wr*100:5.1f}%  ROI {roi:+6.1f}%  MaxL {ml}")
    print()

    # === MAY-JUNE DEEP DIVE ===
    mj = s3[s3["month"].isin([5, 6])].copy()
    n_mj = len(mj)
    wr_mj = mj["dog_won"].mean()
    roi_mj = mj["pnl"].sum() / (n_mj * 100) * 100
    print(f"=== MAY-JUNE S3: {n_mj} bets, WR {wr_mj*100:.1f}%, ROI {roi_mj:+.1f}% ===")

    # Wins vs losses profile
    wins = mj[mj["dog_won"]]
    losses = mj[~mj["dog_won"]]

    compare_cols = [
        ("dog_decimal", "Dog odds"),
        ("elo_diff", "Elo diff"),
        ("rpi_diff", "RPI diff"),
        ("wp_last3_away", "Away WP3"),
        ("wp_last6_away", "Away WP6"),
        ("wp_last10_away", "Away WP10"),
        ("streak_away", "Away streak"),
        ("streak_home", "Home streak"),
        ("rpg_away", "Away RPG"),
        ("rapg_home", "Home RAPG"),
        ("pyth_wp_diff", "Pyth WP diff"),
        ("away_sp_ra_short", "Away SP RA"),
        ("home_sp_ra_short", "Home SP RA"),
        ("sp_ra_short_diff", "SP RA diff"),
        ("starter_fip_diff", "Starter FIP diff"),
        ("starter_whip_diff", "Starter WHIP diff"),
        ("bp_ip_3d_home", "Home BP 3d"),
        ("bullpen_fip_diff", "BP FIP diff"),
        ("edge_consensus", "Edge"),
        ("games_played_min", "GP min"),
    ]

    print(f"\n--- WINS vs LOSSES profile (May-Jun) ---")
    print(f"{'Feature':<22} {'Win med':>10} {'Loss med':>10} {'Delta':>10} {'Signal':>8}")
    print("-" * 65)
    for col, label in compare_cols:
        if col not in mj.columns:
            continue
        wm = wins[col].median()
        lm = losses[col].median()
        if pd.isna(wm) or pd.isna(lm):
            continue
        delta = wm - lm
        denom = max(abs(wm), abs(lm), 0.01)
        sig = "YES" if abs(delta) / denom > 0.10 else ""
        print(f"  {label:<20} {wm:10.3f} {lm:10.3f} {delta:+10.3f} {sig:>8}")

    # === SUB-FILTER SEARCH ===
    candidates = {}

    # Elo tightening
    for t in [0, 10, 15, 20]:
        candidates[f"elo_diff <= {t}"] = mj["elo_diff"] <= t

    # Edge depth
    for t in [-0.07, -0.10, -0.12, -0.15]:
        candidates[f"edge < {t}"] = mj["edge_consensus"] < t

    # Pitcher quality
    if "away_sp_ra_short" in mj.columns:
        med = mj["away_sp_ra_short"].median()
        p25 = mj["away_sp_ra_short"].quantile(0.25)
        candidates[f"away_sp_ra <= med ({med:.1f})"] = mj["away_sp_ra_short"] <= med
        candidates[f"away_sp_ra <= p25 ({p25:.1f})"] = mj["away_sp_ra_short"] <= p25

    if "home_sp_ra_short" in mj.columns:
        med = mj["home_sp_ra_short"].median()
        p75 = mj["home_sp_ra_short"].quantile(0.75)
        candidates[f"home_sp_ra >= med ({med:.1f})"] = mj["home_sp_ra_short"] >= med
        candidates[f"home_sp_ra >= p75 ({p75:.1f})"] = mj["home_sp_ra_short"] >= p75

    if "starter_fip_diff" in mj.columns:
        candidates["starter_fip_diff > 0"] = mj["starter_fip_diff"] > 0
        candidates["starter_fip_diff > 0.5"] = mj["starter_fip_diff"] > 0.5

    if "sp_ra_short_diff" in mj.columns:
        candidates["sp_ra_diff > 0"] = mj["sp_ra_short_diff"] > 0

    # Form
    if "wp_last6_away" in mj.columns:
        candidates["wp_last6_away >= 0.50"] = mj["wp_last6_away"] >= 0.50
    if "wp_last10_away" in mj.columns:
        candidates["wp_last10_away >= 0.45"] = mj["wp_last10_away"] >= 0.45
        candidates["wp_last10_away >= 0.50"] = mj["wp_last10_away"] >= 0.50

    # Bullpen
    if "bp_ip_3d_home" in mj.columns:
        med = mj["bp_ip_3d_home"].median()
        p75 = mj["bp_ip_3d_home"].quantile(0.75)
        candidates[f"home_bp_3d >= med ({med:.1f})"] = mj["bp_ip_3d_home"] >= med
        candidates[f"home_bp_3d >= p75 ({p75:.1f})"] = mj["bp_ip_3d_home"] >= p75

    # GP threshold
    if "games_played_min" in mj.columns:
        for t in [25, 30, 40]:
            candidates[f"games_played_min >= {t}"] = mj["games_played_min"] >= t

    # Runs context
    if "rpg_away" in mj.columns:
        med = mj["rpg_away"].median()
        candidates[f"rpg_away >= med ({med:.1f})"] = mj["rpg_away"] >= med
    if "rapg_home" in mj.columns:
        med = mj["rapg_home"].median()
        candidates[f"rapg_home >= med ({med:.1f})"] = mj["rapg_home"] >= med

    # RPI tightening
    candidates["rpi_diff <= -0.02"] = mj["rpi_diff"] <= -0.02
    candidates["rpi_diff <= -0.01"] = mj["rpi_diff"] <= -0.01

    # Odds band
    candidates["dog_decimal <= 2.30"] = mj["dog_decimal"] <= 2.30
    candidates["dog_decimal <= 2.50"] = mj["dog_decimal"] <= 2.50

    # Pyth WP
    if "pyth_wp_diff" in mj.columns:
        candidates["pyth_wp_diff <= 0"] = mj["pyth_wp_diff"] <= 0
        candidates["pyth_wp_diff <= -0.03"] = mj["pyth_wp_diff"] <= -0.03

    print(f"\n=== MAY-JUNE SUB-FILTER SEARCH ===")
    header = f"{'Filter':<55} {'Bets':>5} {'WR':>6} {'ROI':>7} {'MaxL':>5} {'MaxDD':>7}"
    print(header)
    print("-" * 90)

    r = eval_filter(mj, "MJ baseline (no filter)")
    print(f"  {r['filter']:<53} {r['bets']:5d} {r['wr']*100:5.1f}% {r['roi']:+6.1f}% {r['max_ls']:5d} {r['max_dd']:6.1f}%")
    print("-" * 90)

    results = []
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_filter(mj[mask], name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["roi"])
    for r in results:
        marker = " <<<" if r["roi"] > 3 else ""
        print(
            f"  {r['filter']:<53} {r['bets']:5d} {r['wr']*100:5.1f}% "
            f"{r['roi']:+6.1f}% {r['max_ls']:5d} {r['max_dd']:6.1f}%{marker}"
        )

    # === 2-WAY COMBOS ===
    top_names = [r["filter"] for r in results if r["roi"] > 0][:10]
    if len(top_names) >= 2:
        print(f"\n=== MAY-JUNE 2-WAY COMBOS (top {len(top_names)} singles) ===")
        header = f"{'Filter':<70} {'Bets':>5} {'WR':>6} {'ROI':>7} {'MaxL':>5} {'MaxDD':>7}"
        print(header)
        print("-" * 100)

        combo_results = []
        for f1, f2 in combinations(top_names, 2):
            m1 = candidates.get(f1, pd.Series(False, index=mj.index)).fillna(False)
            m2 = candidates.get(f2, pd.Series(False, index=mj.index)).fillna(False)
            r = eval_filter(mj[m1 & m2], f"{f1} + {f2}")
            if r:
                combo_results.append(r)

        combo_results.sort(key=lambda x: -x["roi"])
        for r in combo_results[:25]:
            marker = " <<<" if r["roi"] > 5 else ""
            print(
                f"  {r['filter']:<68} {r['bets']:5d} {r['wr']*100:5.1f}% "
                f"{r['roi']:+6.1f}% {r['max_ls']:5d} {r['max_dd']:6.1f}%{marker}"
            )

    # === FINAL: FULL SEASON with best May-June filter applied ===
    print(f"\n=== WHAT IF: Apply best MJ filter to full season? ===")
    # Pick top MJ combo that has > 15 bets and ROI > 5%
    best_mj = [r for r in (combo_results if len(top_names) >= 2 else results)
               if r["bets"] > 15 and r["roi"] > 5]
    if best_mj:
        best = best_mj[0]
        print(f"Best MJ filter: {best['filter']}")
        print(f"MJ performance: {best['bets']} bets, ROI {best['roi']:+.1f}%, MaxL {best['max_ls']}")

    # Also show: what if we just skip May-June entirely?
    s3_no_mj = s3[~s3["month"].isin([5, 6])]
    n_no = len(s3_no_mj)
    roi_no = s3_no_mj["pnl"].sum() / (n_no * 100) * 100 if n_no > 0 else 0
    ml_no = max_ls(s3_no_mj["dog_won"].values)
    print(f"\nAlternative: Skip May-Jun entirely")
    print(f"  Jul-Oct S3: {n_no} bets, ROI {roi_no:+.1f}%, MaxL {ml_no}")
    print(f"  Full S3:    {len(s3)} bets, ROI {s3['pnl'].sum()/(len(s3)*100)*100:+.1f}%")


if __name__ == "__main__":
    main()
