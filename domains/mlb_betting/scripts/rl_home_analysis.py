"""Home underdog strategy analysis: Run Line +1.5 and Moneyline wins.

Two strategies tested in parallel:
  A) Home +1.5: covers when margin_home >= -1 (home wins or loses by max 1).
     Odds: REAL home_run_line_odds (no estimation needed).
  B) Home ML:  wins when margin_home > 0 (home wins outright).
     Odds: home_decimal_odds.

Universe: ~fav_is_home (away team is favorite, home team is underdog).
Edge direction: same inverted logic as away +1.5 -- edge > 0.05 means
favorite overpriced, tighter games expected, benefits underdog.

Usage:
    python scripts/rl_home_analysis.py
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
    odds = data["odds"].values
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

    # Derived model signals
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0

    if "pred_M4" in df.columns:
        df["m4_edge"] = df["closing_decimal_odds_favorite"] - df["pred_M4"]
    if all(c in df.columns for c in ["pred_M3", "pred_M4", "pred_M0", "pred_M2"]):
        df["m34_vs_m02"] = (df["pred_M3"] + df["pred_M4"]) / 2 - (df["pred_M0"] + df["pred_M2"]) / 2

    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["day"] = pd.to_datetime(df["date"]).dt.day
    df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (df["day"] <= ASG_DAY))

    df["margin_home"] = df["home_final"] - df["away_final"]

    # Dog decimal (ML odds for the underdog = home team in this universe)
    df["dog_decimal"] = np.where(
        df["fav_is_home"], df["away_decimal_odds"], df["home_decimal_odds"]
    )

    # Universe: home is underdog (away is favorite)
    universe = ~df["fav_is_home"]
    home_dog = df[universe].copy()

    # --- Strategy A: Home +1.5 ---
    # Valid RL: home_run_line == 1.5 (actual underdog spread, not misclassified O/U)
    rl_valid = home_dog["home_run_line"] == 1.5 if "home_run_line" in home_dog.columns else pd.Series(False, index=home_dog.index)

    if "home_run_line_odds" in home_dog.columns:
        home_dog["rl_odds"] = home_dog["home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    else:
        home_dog["rl_odds"] = np.nan

    home_dog["covers_rl"] = home_dog["margin_home"] >= -1  # home wins or loses by max 1

    # --- Strategy B: Home ML win ---
    home_dog["ml_odds"] = home_dog["home_decimal_odds"]
    home_dog["covers_ml"] = home_dog["margin_home"] > 0  # home wins outright

    # Split into RL and ML datasets
    df_rl = home_dog[rl_valid & home_dog["rl_odds"].notna()].copy()
    df_rl["covers"] = df_rl["covers_rl"]
    df_rl["odds"] = df_rl["rl_odds"]

    df_ml = home_dog.copy()
    df_ml["covers"] = df_ml["covers_ml"]
    df_ml["odds"] = df_ml["ml_odds"]

    print(f"\nHome underdog universe: {len(home_dog)} games")
    print(f"  RL +1.5 subset (real odds): {len(df_rl)} games")
    print(f"  ML subset: {len(df_ml)} games")
    print(f"  Seasons: {sorted(home_dog['season'].unique())}")
    return df_rl, df_ml


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section1_baseline(df, label):
    print(f"\n{'#'*80}")
    print(f"SECTION 1: BASELINE — {label}")
    print(f"{'#'*80}")

    n = len(df)
    cr = df["covers"].mean()
    pnl = np.where(df["covers"], (df["odds"] - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    print(f"All {label}: {n} bets, cover {cr*100:.1f}%, avg odds {df['odds'].mean():.3f}, ROI {roi:+.1f}%")

    # Edge bands
    print("\n  Edge bands:")
    for lo, hi, elabel in [
        (None, -0.10, "edge < -0.10"), (-0.10, -0.07, "-0.10 <= edge < -0.07"),
        (-0.07, -0.05, "-0.07 <= edge < -0.05"), (-0.05, -0.03, "-0.05 <= edge < -0.03"),
        (-0.03, 0, "-0.03 <= edge < 0"), (0, 0.05, "0 <= edge < 0.05"),
        (0.05, 0.10, "0.05 <= edge < 0.10"), (0.10, None, "edge >= 0.10"),
    ]:
        if lo is None: mask = df["edge_consensus"] < hi
        elif hi is None: mask = df["edge_consensus"] >= lo
        else: mask = (df["edge_consensus"] >= lo) & (df["edge_consensus"] < hi)
        mb = df[mask]
        nm = len(mb)
        if nm < 15: continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {elabel:<30} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Odds buckets (underdog size)
    print("\n  By underdog size (ML odds):")
    for lo, hi, olabel in [
        (1.50, 2.00, "small dog 1.50-2.00"), (2.00, 2.30, "small dog 2.00-2.30"),
        (2.30, 2.70, "medium dog 2.30-2.70"), (2.70, 3.50, "big dog 2.70-3.50"),
        (3.50, None, "longshot 3.50+"),
    ]:
        if hi is None: mask = df["dog_decimal"] >= lo
        else: mask = (df["dog_decimal"] >= lo) & (df["dog_decimal"] < hi)
        mb = df[mask]
        nm = len(mb)
        if nm < 15: continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    {olabel:<30} {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")

    # Monthly
    print("\n  By month:")
    for m in sorted(df["month"].unique()):
        mb = df[df["month"] == m]
        nm = len(mb)
        if nm < 10: continue
        mcr = mb["covers"].mean()
        mp = np.where(mb["covers"], (mb["odds"] - 1) * 100, -100)
        mroi = mp.sum() / (nm * 100) * 100
        print(f"    Month {m:2d}: {nm:5d}  cover {mcr*100:5.1f}%  ROI {mroi:+6.1f}%")


def section2_singles(df, label):
    print(f"\n{'#'*80}")
    print(f"SECTION 2: SINGLE FILTERS — {label}")
    print(f"{'#'*80}")

    # Inverted edge for underdog: edge > 0.05 = fav overpriced = tighter games
    base = df[df["edge_consensus"] > 0.05].copy()
    print(f"Base (edge > 0.05): {len(base)} bets")

    candidates = {}

    # RPI: positive = home stronger (underdog by line but strong fundamentally)
    for t in [0, 0.01, 0.02, 0.03]:
        candidates[f"rpi_diff >= {t} (home stronger)"] = base["rpi_diff"] >= t
    for t in [0, -0.01, -0.02]:
        candidates[f"rpi_diff <= {t} (away stronger)"] = base["rpi_diff"] <= t

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

    # Home team form
    if "wp_last6_home" in base.columns:
        candidates["wp_last6_home >= 0.45"] = base["wp_last6_home"] >= 0.45
        candidates["wp_last6_home >= 0.50"] = base["wp_last6_home"] >= 0.50
    if "wp_last10_home" in base.columns:
        candidates["wp_last10_home >= 0.50"] = base["wp_last10_home"] >= 0.50
    if "streak_home" in base.columns:
        candidates["streak_home >= 0"] = base["streak_home"] >= 0
        candidates["streak_home >= 1 (W1+)"] = base["streak_home"] >= 1
        candidates["streak_home >= 2 (W2+)"] = base["streak_home"] >= 2
        candidates["streak_home >= 3 (W3+)"] = base["streak_home"] >= 3

    # Home field advantage features
    if "wp_home_at_home" in base.columns:
        for t in [0.50, 0.55, 0.60]:
            candidates[f"wp_home_at_home >= {t}"] = base["wp_home_at_home"] >= t
    if "wp_away_on_road" in base.columns:
        for t in [0.40, 0.45, 0.50]:
            candidates[f"wp_away_on_road <= {t} (away weak road)"] = base["wp_away_on_road"] <= t
    if "wp_home_at_home" in base.columns and "wp_away_on_road" in base.columns:
        candidates["HFA: home@home > away@road"] = base["wp_home_at_home"] > base["wp_away_on_road"]

    # Away team form (weakness indicators)
    if "wp_last6_away" in base.columns:
        candidates["wp_last6_away <= 0.50"] = base["wp_last6_away"] <= 0.50
        candidates["wp_last6_away <= 0.40"] = base["wp_last6_away"] <= 0.40
    if "streak_away" in base.columns:
        candidates["streak_away <= 0 (away cold)"] = base["streak_away"] <= 0
        candidates["streak_away <= -1 (away L1+)"] = base["streak_away"] <= -1

    # Pitcher: home pitcher better (lower RA)
    if "starter_fip_diff" in base.columns:
        candidates["starter_fip_diff < 0 (home P better)"] = base["starter_fip_diff"] < 0
        candidates["starter_fip_diff < -0.5"] = base["starter_fip_diff"] < -0.5
    if "home_sp_ra_short" in base.columns:
        med = base["home_sp_ra_short"].median()
        candidates[f"home_sp_ra <= med ({med:.2f})"] = base["home_sp_ra_short"] <= med
    if "away_sp_ra_short" in base.columns:
        med = base["away_sp_ra_short"].median()
        candidates[f"away_sp_ra >= med ({med:.2f}) (away P worse)"] = base["away_sp_ra_short"] >= med

    # Bullpen: tired away bullpen = home advantage
    if "bp_ip_3d_away" in base.columns:
        med = base["bp_ip_3d_away"].median()
        p75 = base["bp_ip_3d_away"].quantile(0.75)
        candidates[f"away_bp_3d > med ({med:.1f})"] = base["bp_ip_3d_away"] > med
        candidates[f"away_bp_3d > p75 ({p75:.1f})"] = base["bp_ip_3d_away"] > p75
    if "bp_ip_3d_home" in base.columns:
        med = base["bp_ip_3d_home"].median()
        candidates[f"home_bp_3d <= med ({med:.1f}) (fresh)"] = base["bp_ip_3d_home"] <= med
    if "bullpen_fip_diff" in base.columns:
        candidates["bullpen_fip_diff < 0 (home BP better)"] = base["bullpen_fip_diff"] < 0

    # Odds band (underdog size)
    if "dog_decimal" in base.columns:
        candidates["dog_decimal <= 2.30 (small dog)"] = base["dog_decimal"] <= 2.30
        candidates["dog_decimal <= 2.50"] = base["dog_decimal"] <= 2.50
        candidates["dog_decimal 2.30-2.70 (medium)"] = (base["dog_decimal"] > 2.30) & (base["dog_decimal"] <= 2.70)
        candidates["dog_decimal >= 2.70 (big dog)"] = base["dog_decimal"] >= 2.70

    # Model signals
    if "m34_vs_m02" in base.columns:
        candidates["m34_vs_m02 > 0 (upset models)"] = base["m34_vs_m02"] > 0
        candidates["m34_vs_m02 < 0 (dominant models)"] = base["m34_vs_m02"] < 0
    if "m4_edge" in base.columns:
        candidates["m4_edge > 0 (fav overprice)"] = base["m4_edge"] > 0
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
    ptable(results, f"SINGLE FILTERS — {label}")
    return base, candidates, results


def section3_combos(base, candidates, single_results, label):
    print(f"\n{'#'*80}")
    print(f"SECTION 3: 2-WAY COMBOS — {label}")
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
    ptable(combo_results[:20], f"TOP 2-WAY COMBOS — {label}")
    return combo_results


def section4_dual_regime(df, label):
    print(f"\n{'#'*80}")
    print(f"SECTION 4: DUAL-REGIME (1H strict / 2H base) — {label}")
    print(f"{'#'*80}")

    base_mask = df["edge_consensus"] > 0.05
    base = df[base_mask].copy()

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

    # Strict 1H filters (home underdog-specific)
    strict_configs = {}
    if "rpi_diff" in base.columns:
        strict_configs["1H: rpi>=0.01"] = base["rpi_diff"] >= 0.01
    if "elo_diff" in base.columns:
        strict_configs["1H: elo>=0"] = base["elo_diff"] >= 0
    if "wp_home_at_home" in base.columns:
        strict_configs["1H: home@home>=0.55"] = base["wp_home_at_home"] >= 0.55
    if "starter_fip_diff" in base.columns:
        strict_configs["1H: fip<0 (home P better)"] = base["starter_fip_diff"] < 0
    if "streak_home" in base.columns:
        strict_configs["1H: streak>=1"] = base["streak_home"] >= 1
    if "bp_ip_3d_away" in base.columns:
        med = base["bp_ip_3d_away"].median()
        strict_configs["1H: away_bp_tired"] = base["bp_ip_3d_away"] > med

    # Dual-regime: strict 1H + base 2H
    results = []
    for sn, smask in strict_configs.items():
        smask = smask.fillna(False)
        h1_strict = h1[smask.reindex(h1.index, fill_value=False)]
        combined = pd.concat([h1_strict, h2])
        r = eval_strat(combined, f"{sn} | 2H base")
        if r:
            results.append(r)

    # Strict combo pairs for 1H
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
        ptable(results, f"DUAL-REGIME — {label}")

    return results


def section5_summary(all_results_rl, all_results_ml):
    print(f"\n{'#'*80}")
    print("SECTION 5: COMBINED SUMMARY")
    print(f"{'#'*80}")

    for strat_label, all_results in [("HOME +1.5", all_results_rl), ("HOME ML", all_results_ml)]:
        viable = []
        for r in all_results:
            if r is None:
                continue
            if r["roi"] > 0 and r["bets"] >= 30:
                folds = r["folds_pos"].split("/")
                if len(folds) == 2 and int(folds[0]) >= 4:
                    viable.append(r)

        viable.sort(key=lambda x: -x["sharpe"])
        ptable(viable[:10], f"VIABLE — {strat_label} (ROI>0, bets>=30, folds>=4)")

        if viable:
            best = viable[0]
            rois_str = ", ".join(f"{x:+.0f}" for x in best["season_rois"])
            print(f"\n  BEST {strat_label}: {best['filter']}")
            print(f"    {best['bets']} bets ({best['bps']:.0f}/s)  Cover {best['cr']*100:.1f}%  ROI {best['roi']:+.1f}%")
            print(f"    Sharpe {best['sharpe']:.3f}  Kelly/2 {best['kelly_half']*100:.2f}%  MaxL {best['max_ls']}")
            print(f"    Seasons: [{rois_str}]")

    print(f"\n  Context (other systems):")
    print(f"    S3-dual (away ML): ~44 bets/season, +17.9% ROI, Sharpe 0.98")
    print(f"    Away +1.5 best (1H+edge>0.10): ~91 bets/season, +11.8% ROI, Sharpe 1.233")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df_rl, df_ml = build_dataset()

    all_rl = []
    all_ml = []

    for label, sdf, collector in [
        ("HOME +1.5", df_rl, all_rl),
        ("HOME ML", df_ml, all_ml),
    ]:
        print(f"\n\n{'*'*80}")
        print(f"{'*'*80}")
        print(f"  STRATEGY: {label}")
        print(f"{'*'*80}")
        print(f"{'*'*80}")

        section1_baseline(sdf, label)
        base, candidates, singles = section2_singles(sdf, label)
        combos = section3_combos(base, candidates, singles, label)
        duals = section4_dual_regime(sdf, label)

        collector.extend(singles + combos + duals)

    section5_summary(all_rl, all_ml)


if __name__ == "__main__":
    main()
