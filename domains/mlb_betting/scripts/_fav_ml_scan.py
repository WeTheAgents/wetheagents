"""Fav ML (moneyline) pitcher-advantage scan. Fav just needs to WIN."""

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
from scripts.pitcher_advantage_fav_scan import build_fav_rl_data, add_derived, max_ls

TRAIN = [2014, 2015, 2016, 2017, 2018, 2019]
TEST = [2021, 2022, 2023, 2024, 2025]


def eval_strat(data, name, min_bets=20):
    n = len(data)
    if n < min_bets:
        return None
    wins = data["covers"].values.astype(float)
    odds = data["ml_odds"].values
    pnl = np.where(wins, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    wr = wins.mean()
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
        sp = np.where(wins[sm.values], (odds[sm.values] - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)
    return {
        "filter": name, "bets": n, "bps": bps,
        "cr": wr, "avg_odds": avg_odds, "roi": roi,
        "sharpe": sharpe, "folds": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'=' * 130}")
    print(title)
    print(f"{'=' * 130}")
    hdr = f"  {'Filter':<60} {'Bets':>5} {'B/S':>4} {'Win%':>6} {'Odds':>5} {'ROI':>7} {'Shrp':>6} {'Flds':>6}  Seasons"
    print(hdr)
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


def _s(mask, idx):
    if isinstance(mask, np.ndarray):
        return pd.Series(mask, index=idx).fillna(False)
    return mask.fillna(False)


def build_filters(rl):
    c = {}
    for col, label in [("fav_sp_fip_short", "fav_fip_short"), ("fav_sp_fip_long", "fav_fip_long")]:
        if col in rl.columns:
            for t in [3.0, 3.5, 3.8, 4.0]:
                c[f"{label} <= {t}"] = rl[col] <= t
    for col, label in [("dog_sp_fip_short", "dog_fip_short"), ("dog_sp_fip_long", "dog_fip_long"),
                        ("dog_sp_ra_long", "dog_ra_long")]:
        if col in rl.columns:
            for t in [4.0, 4.5, 5.0, 5.5]:
                c[f"{label} >= {t}"] = rl[col] >= t
    if "fav_fip_short_diff" in rl.columns:
        for t in [-0.3, -0.5, -0.8, -1.0, -1.5]:
            c[f"fip_short_diff <= {t}"] = rl["fav_fip_short_diff"] <= t
    if "fav_fip_long_diff" in rl.columns:
        for t in [-0.3, -0.5, -0.8, -1.0, -1.5]:
            c[f"fip_long_diff <= {t}"] = rl["fav_fip_long_diff"] <= t
    if "fav_sp_ip_per_start" in rl.columns:
        for t in [5.0, 5.5, 6.0]:
            c[f"fav_depth >= {t}"] = rl["fav_sp_ip_per_start"] >= t
    if "dog_sp_ip_per_start" in rl.columns:
        for t in [5.5, 5.0, 4.5]:
            c[f"dog_depth <= {t}"] = rl["dog_sp_ip_per_start"] <= t
    if "fav_depth_diff" in rl.columns:
        for t in [0.5, 1.0, 1.5]:
            c[f"depth_diff >= {t}"] = rl["fav_depth_diff"] >= t
    if "dog_bp_ip_3d" in rl.columns:
        for t in [6, 8, 10, 12]:
            c[f"dog_bp_3d >= {t}"] = rl["dog_bp_ip_3d"] >= t
    if "fav_bp_ip_3d" in rl.columns:
        for t in [6, 8, 10]:
            c[f"fav_bp_3d <= {t}"] = rl["fav_bp_ip_3d"] <= t
    if "fav_bp_workload_gap" in rl.columns:
        for t in [0, -1, -2, -3]:
            c[f"bp_wl_gap <= {t}"] = rl["fav_bp_workload_gap"] <= t
    if "_fav_impl" in rl.columns:
        for lo, hi in [(0.55, 0.65), (0.55, 0.70), (0.60, 0.70), (0.60, 0.75), (0.62, 0.75)]:
            c[f"impl {int(lo*100)}-{int(hi*100)}%"] = (rl["_fav_impl"] >= lo) & (rl["_fav_impl"] <= hi)
    return c


_CAT_MAP = {
    "fav_fip_short": "fav_fip_short", "fav_fip_long": "fav_fip_long",
    "dog_fip_short": "dog_fip_short", "dog_fip_long": "dog_fip_long",
    "dog_ra_long": "dog_ra_long",
    "fip_short_diff": "fip_short_diff", "fip_long_diff": "fip_long_diff",
    "fav_depth": "fav_depth", "dog_depth": "dog_depth", "depth_diff": "depth_diff",
    "dog_bp_3d": "dog_bp_3d", "fav_bp_3d": "fav_bp_3d",
    "bp_wl_gap": "bp_wl_gap", "impl": "impl",
}


def get_cat(name):
    for prefix, cat in _CAT_MAP.items():
        if name.startswith(prefix):
            return cat
    return name


def main():
    print("=" * 130)
    print("FAV ML PITCHER ADVANTAGE SCAN (2014+, excl. bullpen days)")
    print("=" * 130)

    rl = build_fav_rl_data()
    rl = rl[rl["season"] >= 2014].copy()
    add_derived(rl)

    if "fav_is_bullpen_day" in rl.columns:
        rl = rl[~rl["fav_is_bullpen_day"].fillna(False)].copy()
    if "dog_is_bullpen_day" in rl.columns:
        rl = rl[~rl["dog_is_bullpen_day"].fillna(False)].copy()

    # Switch to ML: fav wins
    rl["covers"] = rl["fav_margin"] > 0
    rl["ml_odds"] = rl.get("closing_decimal_odds_favorite", pd.Series(1.60, index=rl.index)).fillna(1.60)

    print(f"\nUniverse: {len(rl)} games")
    print(f"  Fav win rate: {rl['covers'].mean()*100:.1f}%")
    print(f"  Avg ML odds: {rl['ml_odds'].mean():.3f}")
    be = 1 / rl["ml_odds"].mean() * 100
    print(f"  Breakeven win%: {be:.1f}%")
    pnl = np.where(rl["covers"], (rl["ml_odds"] - 1) * 100, -100)
    print(f"  Baseline ROI: {pnl.sum() / (len(rl) * 100) * 100:.1f}%")
    print(f"  Seasons: {sorted(rl['season'].unique().astype(int).tolist())}")

    candidates = build_filters(rl)

    # Phase 1
    results = [eval_strat(rl, "BASELINE")]
    for name, mask in candidates.items():
        mask = _s(mask, rl.index)
        r = eval_strat(rl[mask], name)
        if r:
            results.append(r)
    results.sort(key=lambda x: -x["roi"])
    ptable(results[:40], "PHASE 1: SINGLE FILTERS — Fav ML")

    # Phase 2
    top = [r["filter"] for r in results if r["roi"] > 0 and r["filter"] != "BASELINE"][:15]
    combos = []
    for f1, f2 in combinations(top, 2):
        if get_cat(f1) == get_cat(f2):
            continue
        m1 = _s(candidates[f1], rl.index)
        m2 = _s(candidates[f2], rl.index)
        r = eval_strat(rl[m1 & m2], f"{f1} + {f2}")
        if r:
            combos.append(r)
    combos.sort(key=lambda x: -x["roi"])
    ptable(combos[:25], "PHASE 2: TOP 2-WAY COMBOS — Fav ML")

    # Phase 3: train/test
    train = rl[rl["season"].isin(TRAIN)].copy()
    test = rl[rl["season"].isin(TEST)].copy()
    print(f"\n{'=' * 130}")
    print(f"PHASE 3: TRAIN/TEST (TRAIN={len(train)}, TEST={len(test)})")
    print(f"{'=' * 130}")

    validate = [r["filter"] for r in results if r["roi"] > 0 and r["filter"] != "BASELINE"][:5]
    validate += [r["filter"] for r in combos if r["roi"] > 0][:10]

    for name in validate:
        parts = name.split(" + ")
        for label, sd in [("TRAIN", train), ("TEST", test)]:
            sd2 = sd.copy()
            add_derived(sd2)
            sd2["covers"] = sd2["fav_margin"] > 0
            sd2["ml_odds"] = sd2.get("closing_decimal_odds_favorite", pd.Series(1.60, index=sd2.index)).fillna(1.60)
            sc = build_filters(sd2)
            mask = pd.Series(True, index=sd2.index)
            ok = True
            for p in parts:
                if p in sc:
                    mask = mask & _s(sc[p], sd2.index)
                else:
                    ok = False
                    break
            if not ok:
                continue
            r = eval_strat(sd2[mask], f"[{label}] {name}", min_bets=8)
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(
                    f"  {r['filter']:<75} {r['bets']:4d} win {r['cr']*100:5.1f}% "
                    f"ROI {r['roi']:+6.1f}%  flds {r['folds']}  [{rois}]"
                )


if __name__ == "__main__":
    main()
