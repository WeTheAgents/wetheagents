"""Home underdog +1.5 pitcher-advantage scan. Does the signal work for home dogs?"""

import sys, warnings, logging
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd


def build_home_dog_data():
    from src.data_loader import american_to_decimal
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    logging.getLogger().setLevel(logging.INFO)
    print("Building features + walk-forward...")
    full = build_spec_features()
    features_available = [f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3]
    cfg = ModelConfig()
    fold_results = run_walk_forward(full, features_available, "closing_decimal_odds_favorite", cfg=cfg)
    div = compute_divergence(fold_results)

    mk = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]

    # HOME DOG: away is favorite
    rl_mask = (
        (df.get("fav_is_home", pd.Series(True, index=df.index)) == False)
        & (df["edge_consensus"] > 0.05)
        & ~df.get("involves_col", pd.Series(False, index=df.index))
        & ~df.get("is_extreme_line", pd.Series(False, index=df.index))
    )
    rl = df[rl_mask].copy()

    # fav_margin from fav (away) perspective
    rl["fav_margin"] = rl["away_final"] - rl["home_final"]
    rl["covers"] = rl["fav_margin"] <= 1  # home dog covers +1.5

    # RL odds: home +1.5
    rl["rl_odds"] = np.nan
    if "home_run_line_odds" in rl.columns:
        mask_rl = rl.get("home_run_line", pd.Series(dtype=float)).fillna(0) == 1.5
        rl.loc[mask_rl, "rl_odds"] = rl.loc[mask_rl, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    rl["rl_odds"] = rl["rl_odds"].fillna(1.60)

    # Dog ML odds
    rl["dog_ml_odds"] = rl.get("home_decimal_odds", pd.Series(2.0, index=rl.index)).fillna(2.0)

    logging.getLogger().setLevel(logging.WARNING)
    print(f"Home dog universe: {len(rl)} games")
    return rl


def eval_s(data, name, odds_col="rl_odds", min_bets=15):
    n = len(data)
    if n < min_bets:
        return None
    covers = data["covers"].values.astype(float)
    odds = data[odds_col].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    srois = []
    for s in sorted(data["season"].unique()):
        sm = data["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(covers[sm.values], (odds[sm.values] - 1) * 100, -100)
        srois.append(sp.sum() / (sn * 100) * 100)
    npos = sum(1 for r in srois if r > 0)
    return {"f": name, "n": n, "cr": cr, "odds": odds.mean(), "roi": roi,
            "folds": f"{npos}/{len(srois)}", "srois": srois}


def pr(results, title):
    print(f"\n{'=' * 120}")
    print(title)
    print(f"{'=' * 120}")
    print(f"  {'Filter':<55} {'Bets':>5} {'Cvr':>6} {'Odds':>5} {'ROI':>7} {'Flds':>6}  Seasons")
    print("-" * 120)
    for r in results:
        if not r:
            continue
        rr = ", ".join(f"{x:+.0f}" for x in r["srois"])
        print(f"  {r['f']:<55} {r['n']:5d} {r['cr']*100:5.1f}% {r['odds']:5.2f} {r['roi']:+6.1f}% {r['folds']:>6}  [{rr}]")


def main():
    print("=" * 120)
    print("HOME UNDERDOG PITCHER ADVANTAGE SCAN (2014+, excl. bullpen days)")
    print("=" * 120)

    rl = build_home_dog_data()
    rl = rl[rl["season"] >= 2014].copy()

    # Exclude bullpen days
    if "home_is_bullpen_no_starter" in rl.columns:
        rl = rl[~rl["home_is_bullpen_no_starter"].fillna(False)].copy()
    if "away_is_bullpen_no_starter" in rl.columns:
        rl = rl[~rl["away_is_bullpen_no_starter"].fillna(False)].copy()

    # Derived: home dog = underdog, away = favorite
    # Positive = home dog advantage
    if "home_sp_fip_long" in rl.columns and "away_sp_fip_long" in rl.columns:
        rl["fip_long_gap"] = rl["away_sp_fip_long"] - rl["home_sp_fip_long"]  # pos = away worse
    if "starter_fip_diff" in rl.columns:
        rl["fip_short_gap"] = -rl["starter_fip_diff"]  # flip: pos = home has lower FIP
    if "home_sp_ip_per_start_long" in rl.columns and "away_sp_ip_per_start_long" in rl.columns:
        rl["depth_gap"] = rl["home_sp_ip_per_start_long"] - rl["away_sp_ip_per_start_long"]
    if "bp_ip_3d_home" in rl.columns and "bp_ip_3d_away" in rl.columns:
        rl["bp_wl_gap"] = rl["bp_ip_3d_away"] - rl["bp_ip_3d_home"]  # pos = away BP more tired

    print(f"\nUniverse: {len(rl)} games (bullpen days excluded)")
    print(f"  Cover rate (+1.5): {rl['covers'].mean()*100:.1f}%")
    print(f"  Avg RL odds: {rl['rl_odds'].mean():.3f}")
    dog_wr = (rl["fav_margin"] < 0).mean()
    print(f"  Dog win rate: {dog_wr*100:.1f}%")
    print(f"  Avg dog ML odds: {rl['dog_ml_odds'].mean():.3f}")
    print(f"  Seasons: {sorted(rl['season'].unique().astype(int).tolist())}")

    # --- Filters ---
    c = {}
    # Home dog starter quality
    if "home_sp_fip_short" in rl.columns:
        for t in [3.0, 3.5, 3.8, 4.0]:
            c[f"home_fip_short<={t}"] = rl["home_sp_fip_short"] <= t
    if "home_sp_fip_long" in rl.columns:
        for t in [3.0, 3.5, 3.8, 4.0]:
            c[f"home_fip_long<={t}"] = rl["home_sp_fip_long"] <= t
    # Away fav starter weakness
    if "away_sp_fip_short" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"away_fip_short>={t}"] = rl["away_sp_fip_short"] >= t
    if "away_sp_ra_long" in rl.columns:
        for t in [4.0, 4.5, 5.0, 5.5]:
            c[f"away_ra_long>={t}"] = rl["away_sp_ra_long"] >= t
    # FIP mismatch
    if "fip_short_gap" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0, 1.5]:
            c[f"fip_short_gap>={t}"] = rl["fip_short_gap"] >= t
    if "fip_long_gap" in rl.columns:
        for t in [0.3, 0.5, 0.8, 1.0]:
            c[f"fip_long_gap>={t}"] = rl["fip_long_gap"] >= t
    # Depth
    if "home_sp_ip_per_start_long" in rl.columns:
        for t in [5.0, 5.5, 6.0]:
            c[f"home_depth>={t}"] = rl["home_sp_ip_per_start_long"] >= t
    if "depth_gap" in rl.columns:
        for t in [0.5, 1.0, 1.5]:
            c[f"depth_gap>={t}"] = rl["depth_gap"] >= t
    # Away BP fatigue
    if "bp_ip_3d_away" in rl.columns:
        for t in [6, 8, 10, 12]:
            c[f"away_bp_3d>={t}"] = rl["bp_ip_3d_away"] >= t
    # Home BP rested
    if "bp_ip_3d_home" in rl.columns:
        for t in [6, 8, 10]:
            c[f"home_bp_3d<={t}"] = rl["bp_ip_3d_home"] <= t
    # BP gap
    if "bp_wl_gap" in rl.columns:
        for t in [0, 1, 2, 3, 5]:
            c[f"bp_gap>={t}"] = rl["bp_wl_gap"] >= t

    # Phase 1
    results = [eval_s(rl, "BASELINE")]
    for name, mask in c.items():
        mask = mask.fillna(False)
        r = eval_s(rl[mask], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    pr(results[:35], "PHASE 1: SINGLES - Home Dog +1.5 RL")

    # Phase 2
    cat_map = {}
    for prefix in ["home_fip_short", "home_fip_long", "away_fip_short", "away_ra_long",
                    "fip_short_gap", "fip_long_gap", "home_depth", "depth_gap",
                    "away_bp_3d", "home_bp_3d", "bp_gap"]:
        for name in c:
            if name.startswith(prefix):
                cat_map[name] = prefix

    top = [r["f"] for r in results if r["roi"] > 0 and r["f"] != "BASELINE"][:12]
    combos = []
    for f1, f2 in combinations(top, 2):
        c1 = cat_map.get(f1, f1)
        c2 = cat_map.get(f2, f2)
        if c1 == c2:
            continue
        m = c[f1].fillna(False) & c[f2].fillna(False)
        r = eval_s(rl[m], f"{f1} + {f2}")
        if r:
            combos.append(r)
    combos.sort(key=lambda x: -x["roi"])
    pr(combos[:20], "PHASE 2: 2-WAY COMBOS - Home Dog +1.5 RL")

    # Train/test
    TRAIN = [2014, 2015, 2016, 2017, 2018, 2019]
    TEST = [2021, 2022, 2023, 2024, 2025]
    train = rl[rl["season"].isin(TRAIN)]
    test = rl[rl["season"].isin(TEST)]
    print(f"\n{'=' * 120}")
    print(f"PHASE 3: TRAIN/TEST (train={len(train)}, test={len(test)})")
    print(f"{'=' * 120}")
    validate = [r["f"] for r in results if r["roi"] > 0 and r["f"] != "BASELINE"][:3]
    validate += [r["f"] for r in combos if r["roi"] > 0][:5]
    for name in validate:
        parts = name.split(" + ")
        for label, sd in [("TRAIN", train), ("TEST", test)]:
            mask = pd.Series(True, index=sd.index)
            ok = True
            for p in parts:
                if p in c:
                    mask = mask & c[p].reindex(sd.index).fillna(False)
                else:
                    ok = False
                    break
            if not ok:
                continue
            r = eval_s(sd[mask], f"[{label}] {name}", min_bets=5)
            if r:
                rr = ", ".join(f"{x:+.0f}" for x in r["srois"])
                print(f"  {r['f']:<65} {r['n']:4d} cvr {r['cr']*100:5.1f}% ROI {r['roi']:+6.1f}%  [{rr}]")

    # Dog ML for top
    print(f"\n{'=' * 120}")
    print("DOG ML for top strategies")
    print(f"{'=' * 120}")
    for r in (results[:5] + combos[:5]):
        if not r or r["f"] == "BASELINE":
            continue
        parts = r["f"].split(" + ")
        mask = pd.Series(True, index=rl.index)
        for p in parts:
            if p in c:
                mask = mask & c[p].fillna(False)
        sub = rl[mask]
        if len(sub) < 15:
            continue
        dog_wins = (sub["fav_margin"] < 0).values.astype(float)
        ml_odds = sub["dog_ml_odds"].values
        pnl = np.where(dog_wins, (ml_odds - 1) * 100, -100)
        ml_roi = pnl.sum() / (len(sub) * 100) * 100
        wr = dog_wins.mean()
        print(f"  {r['f']:<55} RL: {r['n']:4d} cvr {r['cr']*100:.1f}% ROI {r['roi']:+.1f}%  |  ML: win {wr*100:.1f}% ROI {ml_roi:+.1f}%")


if __name__ == "__main__":
    main()
