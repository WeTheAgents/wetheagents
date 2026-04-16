"""Away +1.5 Run Line filter scan — find rule-based edges without LLM.

Cover condition: margin_home <= 1 (away loses by <=1 or wins outright).
Universe: edge_consensus > 0.05, fav_is_home=True.
Odds: away +1.5 from SBR where available, else 1.60 fallback.

Usage:
    python scripts/rl_away_filter_scan.py
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

ASG_DAY = 15
TRAIN_SEASONS = list(range(2010, 2020))  # 2010-2019
TEST_SEASONS = [2021, 2022, 2023, 2024, 2025]


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
# Data pipeline — reuses build_rl_data() from run_rl_calibration.py
# ---------------------------------------------------------------------------

def build_dataset():
    from scripts.run_rl_calibration import build_rl_data
    rl = build_rl_data()

    # Enrich with derived columns
    rl["month"] = pd.to_datetime(rl["date"]).dt.month
    rl["day"] = pd.to_datetime(rl["date"]).dt.day
    rl["is_first_half"] = (rl["month"] < 7) | ((rl["month"] == 7) & (rl["day"] <= ASG_DAY))

    # Minimum games played for both teams
    if "games_played_home" in rl.columns and "games_played_away" in rl.columns:
        rl["games_played_min"] = rl[["games_played_home", "games_played_away"]].min(axis=1)

    # Home implied prob (fav perspective)
    if "home_implied_prob" not in rl.columns:
        if "closing_decimal_odds_favorite" in rl.columns:
            rl["home_implied_prob"] = 1 / rl["closing_decimal_odds_favorite"]

    # Use rl_odds_adj for scoring
    if "rl_odds_adj" in rl.columns:
        rl["rl_odds"] = rl["rl_odds_adj"]
    elif "rl_odds" not in rl.columns:
        rl["rl_odds"] = 1.60

    n_real = rl.get("rl_odds_real", pd.Series(False, index=rl.index)).sum()
    print(f"\nAway +1.5 universe: {len(rl)} games ({n_real} with real RL odds)")
    print(f"  Cover rate: {rl['covers'].mean()*100:.1f}%")
    print(f"  Avg RL odds: {rl['rl_odds'].mean():.3f}")
    print(f"  Seasons: {sorted(rl['season'].unique())}")
    return rl


# ---------------------------------------------------------------------------
# Filter candidates
# ---------------------------------------------------------------------------

def _build_candidates(base):
    """Build filter candidates for Away +1.5 scan."""
    c = {}

    # --- Edge bands ---
    if "edge_consensus" in base.columns:
        c["edge 0.05-0.08"] = (base["edge_consensus"] >= 0.05) & (base["edge_consensus"] < 0.08)
        c["edge 0.08-0.12"] = (base["edge_consensus"] >= 0.08) & (base["edge_consensus"] < 0.12)
        c["edge 0.08-0.16"] = (base["edge_consensus"] >= 0.08) & (base["edge_consensus"] < 0.16)
        c["edge 0.10-0.20"] = (base["edge_consensus"] >= 0.10) & (base["edge_consensus"] < 0.20)
        c["edge >= 0.08"] = base["edge_consensus"] >= 0.08
        c["edge >= 0.10"] = base["edge_consensus"] >= 0.10

    # --- Strength gap: small gap = dog competitive ---
    if "rpi_diff" in base.columns:
        for t in [0.02, 0.03, 0.04, 0.05]:
            c[f"rpi_diff <= {t}"] = base["rpi_diff"] <= t

    if "pyth_wp_diff" in base.columns:
        for t in [0.03, 0.05, 0.08, 0.10]:
            c[f"pyth_diff <= {t}"] = base["pyth_wp_diff"] <= t

    if "elo_diff" in base.columns:
        for t in [20, 30, 40, 50]:
            c[f"elo_diff <= {t}"] = base["elo_diff"] <= t

    # --- Implied prob bands: moderate fav = dog is live ---
    if "home_implied_prob" in base.columns:
        c["impl 55-62%"] = (base["home_implied_prob"] >= 0.55) & (base["home_implied_prob"] < 0.62)
        c["impl 55-65%"] = (base["home_implied_prob"] >= 0.55) & (base["home_implied_prob"] < 0.65)
        c["impl 60-68%"] = (base["home_implied_prob"] >= 0.60) & (base["home_implied_prob"] < 0.68)
        c["impl 62-70%"] = (base["home_implied_prob"] >= 0.62) & (base["home_implied_prob"] < 0.70)
        c["impl < 65%"] = base["home_implied_prob"] < 0.65
        c["impl < 70%"] = base["home_implied_prob"] < 0.70

    # --- Dog form ---
    if "wp_last3_away" in base.columns:
        for t in [0.333, 0.500, 0.667]:
            c[f"dog_wp3 >= {t}"] = base["wp_last3_away"] >= t
    if "wp_last6_away" in base.columns:
        for t in [0.333, 0.500]:
            c[f"dog_wp6 >= {t}"] = base["wp_last6_away"] >= t
    if "wp_last3_diff" in base.columns:
        for t in [0, -0.10, -0.20]:
            c[f"wp3_diff <= {t}"] = base["wp_last3_diff"] <= t
    if "streak_away" in base.columns:
        c["dog_streak >= 0"] = base["streak_away"] >= 0
        c["dog_streak >= 1"] = base["streak_away"] >= 1

    # --- Pitching: home pitcher WORSE = dog's pitcher edge ---
    if "starter_fip_diff" in base.columns:
        for t in [0, 0.3, 0.5, 0.8]:
            c[f"fip_diff >= {t}"] = base["starter_fip_diff"] >= t
    if "starter_whip_diff" in base.columns:
        for t in [0, 0.10, 0.20]:
            c[f"whip_diff >= {t}"] = base["starter_whip_diff"] >= t
    if "sp_ra_momentum_diff" in base.columns:
        for t in [0, 0.2, 0.5]:
            c[f"sp_momentum >= {t}"] = base["sp_ra_momentum_diff"] >= t
    if "starter_recent_ip_diff" in base.columns:
        for t in [0, -0.5, -1.0]:
            c[f"ip_diff <= {t}"] = base["starter_recent_ip_diff"] <= t

    # --- Bullpen ---
    if "bp_ip_3d_home" in base.columns:
        med = base["bp_ip_3d_home"].median()
        p75 = base["bp_ip_3d_home"].quantile(0.75)
        c[f"home_bp_3d > med ({med:.1f})"] = base["bp_ip_3d_home"] > med
        c[f"home_bp_3d > p75 ({p75:.1f})"] = base["bp_ip_3d_home"] > p75
    if "bullpen_fip_diff" in base.columns:
        for t in [0, 0.3, 0.5]:
            c[f"bp_fip_diff >= {t}"] = base["bullpen_fip_diff"] >= t

    # --- Offense gap ---
    if "offense_vs_league_diff" in base.columns:
        for t in [0.05, 0.10]:
            c[f"off_diff <= {t}"] = base["offense_vs_league_diff"] <= t
    if "power_rate_diff" in base.columns:
        c["power_diff <= 0"] = base["power_rate_diff"] <= 0
        c["power_diff <= 0.02"] = base["power_rate_diff"] <= 0.02

    # --- Late-game ---
    if "close_game_wp_home" in base.columns:
        for t in [0.45, 0.50, 0.55]:
            c[f"fav_close_wp >= {t}"] = base["close_game_wp_home"] >= t
    if "close_game_wp_away" in base.columns:
        for t in [0.45, 0.50, 0.55]:
            c[f"dog_close_wp >= {t}"] = base["close_game_wp_away"] >= t
    if "hold_rate_home" in base.columns:
        for t in [0.80, 0.75, 0.70]:
            c[f"fav_hold <= {t}"] = base["hold_rate_home"] <= t
    if "deficit_recovery_rate_away" in base.columns:
        for t in [0.25, 0.30, 0.35]:
            c[f"dog_recovery >= {t}"] = base["deficit_recovery_rate_away"] >= t

    # --- Defense gap ---
    if "defense_vs_league_diff" in base.columns:
        for t in [0, 0.05]:
            c[f"def_diff <= {t}"] = base["defense_vs_league_diff"] <= t

    # --- Season / maturity ---
    if "games_played_min" in base.columns:
        c["gp >= 30"] = base["games_played_min"] >= 30
        c["gp >= 50"] = base["games_played_min"] >= 50
    c["is_first_half"] = base["is_first_half"]
    c["is_second_half"] = ~base["is_first_half"]

    return c


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
    print(f"All away +1.5: {n} bets, cover {cr*100:.1f}%, avg odds {df['rl_odds'].mean():.3f}, "
          f"ROI {roi:+.1f}%, breakeven {be:.1f}%")

    # Implied prob bands
    print("\n  Fav implied probability bands:")
    if "home_implied_prob" in df.columns:
        for lo, hi, label in [
            (0.55, 0.60, "55-60%"), (0.60, 0.65, "60-65%"),
            (0.65, 0.70, "65-70%"), (0.70, 0.75, "70-75%"),
            (0.75, 1.00, "75%+"),
        ]:
            mask = (df["home_implied_prob"] >= lo) & (df["home_implied_prob"] < hi)
            mb = df[mask]
            nm = len(mb)
            if nm < 15:
                continue
            mcr = mb["covers"].mean()
            mp = np.where(mb["covers"], (mb["rl_odds"] - 1) * 100, -100)
            mroi = mp.sum() / (nm * 100) * 100
            print(f"    {label:<12} {nm:5d}  cover {mcr*100:5.1f}%  odds {mb['rl_odds'].mean():.3f}  ROI {mroi:+6.1f}%")

    # Edge bands
    print("\n  Edge bands (positive = fav overpriced by model):")
    for lo, hi, label in [
        (0.05, 0.08, "0.05-0.08"), (0.08, 0.12, "0.08-0.12"),
        (0.12, 0.16, "0.12-0.16"), (0.16, 0.25, "0.16-0.25"),
        (0.25, None, "0.25+"),
    ]:
        if hi is None:
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
        print(f"    {label:<12} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

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


def section2_singles(df):
    print(f"\n{'#'*80}")
    print("SECTION 2: SINGLE FILTERS")
    print(f"{'#'*80}")

    candidates = _build_candidates(df)

    results = [eval_strat(df, "BASELINE: edge > 0.05")]
    for name, mask in candidates.items():
        mask = mask.fillna(False)
        r = eval_strat(df[mask], name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["roi"])
    ptable(results[:40], "SINGLE FILTERS (sorted by ROI)")

    return df, candidates, results


def section3_combos(base, candidates, single_results):
    print(f"\n{'#'*80}")
    print("SECTION 3: 2-WAY COMBOS")
    print(f"{'#'*80}")

    top_names = [r["filter"] for r in single_results
                 if r["roi"] > 0 and not r["filter"].startswith("BASELINE")][:12]

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
    ptable(combo_results[:20], "TOP 2-WAY COMBOS")

    return combo_results


def section4_train_test(df, candidates, single_results, combo_results):
    print(f"\n{'#'*80}")
    print("SECTION 4: TRAIN / TEST VALIDATION")
    print(f"{'#'*80}")

    train = df[df["season"].isin(TRAIN_SEASONS)].copy()
    test = df[df["season"].isin(TEST_SEASONS)].copy()

    print(f"\n  TRAIN: {len(train)} games, seasons {sorted(train['season'].unique())}")
    print(f"  TEST:  {len(test)} games, seasons {sorted(test['season'].unique())}")

    # Collect top strategies: top 5 singles + top 5 combos
    strat_names = []
    for r in single_results:
        if r["roi"] > 0 and not r["filter"].startswith("BASELINE"):
            strat_names.append(r["filter"])
            if len(strat_names) >= 5:
                break
    for r in combo_results:
        if r["roi"] > 0:
            strat_names.append(r["filter"])
            if len(strat_names) >= 10:
                break

    if not strat_names:
        print("  No positive-ROI strategies to validate.")
        return

    for name in strat_names:
        parts = name.split(" + ")

        for split_label, split_df in [("TRAIN", train), ("TEST", test)]:
            mask = pd.Series(True, index=split_df.index)
            cands = _build_candidates(split_df)
            valid = True
            for part in parts:
                if part in cands:
                    mask = mask & cands[part].fillna(False)
                else:
                    valid = False
                    break

            if not valid:
                continue
            r = eval_strat(split_df[mask], f"[{split_label}] {name}")
            if r:
                rois_str = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(f"  {r['filter']:<60} {r['bets']:4d} cvr {r['cr']*100:5.1f}% "
                      f"ROI {r['roi']:+6.1f}%  [{rois_str}]")


def section5_3way(df, candidates, combo_results):
    print(f"\n{'#'*80}")
    print("SECTION 5: 3-WAY COMBOS")
    print(f"{'#'*80}")

    # Take top 3 combos, cross with remaining singles
    top_combos = [r for r in combo_results if r["roi"] > 0][:3]
    if not top_combos:
        print("  No positive-ROI 2-way combos for extension.")
        return []

    # Collect unique filter names used in combos
    used = set()
    for r in top_combos:
        for part in r["filter"].split(" + "):
            used.add(part)

    # Remaining positive-ROI singles
    all_single_names = [name for name in candidates.keys() if name not in used]

    triple_results = []
    for combo_r in top_combos:
        combo_parts = combo_r["filter"].split(" + ")
        m_combo = pd.Series(True, index=df.index)
        for part in combo_parts:
            m_combo = m_combo & candidates.get(part, pd.Series(False, index=df.index)).fillna(False)

        for extra in all_single_names:
            m3 = candidates.get(extra, pd.Series(False, index=df.index)).fillna(False)
            r = eval_strat(df[m_combo & m3], f"{combo_r['filter']} + {extra}")
            if r and r["roi"] > combo_r["roi"]:
                triple_results.append(r)

    triple_results.sort(key=lambda x: -x["roi"])
    ptable(triple_results[:15], "TOP 3-WAY COMBOS (improving on best 2-way)")

    return triple_results


def section6_summary(df, single_results, combo_results, triple_results):
    print(f"\n{'#'*80}")
    print("SECTION 6: SUMMARY")
    print(f"{'#'*80}")

    all_results = single_results + combo_results + triple_results

    viable = []
    for r in all_results:
        if r is None:
            continue
        if r["roi"] > 0 and r["bets"] >= 30 and not r["filter"].startswith("BASELINE"):
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

    be = 1 / df["rl_odds"].mean() * 100
    print(f"\n  Baseline: cover {df['covers'].mean()*100:.1f}%, breakeven {be:.1f}%, "
          f"avg odds {df['rl_odds'].mean():.3f}")

    return viable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("RL AWAY +1.5 FILTER SCAN")
    print("=" * 80)

    df = build_dataset()

    section1_baseline(df)
    base, candidates, singles = section2_singles(df)
    combos = section3_combos(base, candidates, singles)
    section4_train_test(df, candidates, singles, combos)
    triples = section5_3way(df, candidates, combos)
    section6_summary(df, singles, combos, triples)


if __name__ == "__main__":
    main()
