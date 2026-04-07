"""Fav Run Line -1.5 biased ML backtest.

Walk-forward binary classification for P(fav_margin >= 2).
Uses fav-oriented features from build_fav_rl_features().
Output: primary filter (divergence catcher) for layering rule-based filters on top.

Usage:
    python scripts/run_rl_fav_ml.py
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

FAV_RL_FALLBACK = 2.40


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
    covers = data["fav_covers_rl"].values.astype(float)
    odds = data["rl_odds"].values
    pnl = np.where(covers, (odds - 1) * 100, -100)
    roi = pnl.sum() / (n * 100) * 100
    cr = covers.mean()
    avg_odds = odds.mean()
    ml = max_ls(covers == 0)

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
        "filter": name, "bets": n, "bps": bps,
        "cr": cr, "avg_odds": avg_odds, "roi": roi, "max_ls": ml,
        "sharpe": sharpe, "kelly_half": kelly,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'='*120}")
    print(title)
    print(f"{'='*120}")
    h = (f"{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Cvr':>6} {'Odds':>5} "
         f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'K/2':>6} {'Flds':>6}")
    print(h)
    print("-" * 120)
    for r in results:
        if r is None:
            continue
        print(
            f"  {r['filter']:<53} {r['bets']:5d} {r['bps']:4.0f} "
            f"{r['cr']*100:5.1f}% {r['avg_odds']:5.2f} "
            f"{r['roi']:+6.1f}% {r['max_ls']:5d} "
            f"{r['sharpe']:5.3f} {r['kelly_half']*100:5.2f}% {r['folds_pos']:>6}"
        )


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def build_dataset():
    from src.features import build_fav_rl_features, FAV_RL_FEATURES
    from src.model import FavRLConfig, run_walk_forward_fav_rl
    from src.data_loader import american_to_decimal

    print("Building fav RL features...")
    df = build_fav_rl_features()

    # Universe: valid RL data, exclude Colorado + extreme lines
    mask = pd.Series(True, index=df.index)
    if "home_run_line" in df.columns:
        mask = mask & df["home_run_line"].isin([-1.5, 1.5])
    if "involves_col" in df.columns:
        mask = mask & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        mask = mask & ~df["is_extreme_line"]
    df = df[mask].copy()

    # RL odds for fav -1.5
    df["rl_odds"] = np.nan
    if "home_run_line_odds" in df.columns:
        hf = df["fav_is_home"] & (df["home_run_line"] == -1.5)
        df.loc[hf, "rl_odds"] = df.loc[hf, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    if "away_run_line_odds" in df.columns:
        af = ~df["fav_is_home"] & (df["home_run_line"] == 1.5)
        df.loc[af, "rl_odds"] = df.loc[af, "away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    df["rl_odds"] = df["rl_odds"].fillna(FAV_RL_FALLBACK)

    # Implied prob of fav (may already exist from build_fav_rl_features)
    if "fav_implied_prob" not in df.columns:
        df["fav_implied_prob"] = np.where(
            df["fav_is_home"], df["home_implied_prob"], df["away_implied_prob"]
        )

    # Combined RPG
    if "combined_rpg" not in df.columns and "rpg_home" in df.columns:
        df["combined_rpg"] = df["rpg_home"] + df["rpg_away"]

    # Close game wp of fav
    if "fav_close_game_wp" not in df.columns:
        if "close_game_wp_home" in df.columns:
            df["fav_close_game_wp"] = np.where(
                df["fav_is_home"], df["close_game_wp_home"], df["close_game_wp_away"]
            )

    n_real = (df["rl_odds"] != FAV_RL_FALLBACK).sum()
    print(f"\nFav -1.5 universe: {len(df)} games ({n_real} real RL odds)")
    print(f"  Cover rate: {df['fav_covers_rl'].mean()*100:.1f}%")
    print(f"  Seasons: {sorted(df['season'].unique())}")

    # Run walk-forward
    features_available = [
        f for f in FAV_RL_FEATURES if f in df.columns and df[f].notna().mean() > 0.3
    ]
    print(f"\nFeatures: {len(features_available)}/{len(FAV_RL_FEATURES)}")
    missing = [f for f in FAV_RL_FEATURES if f not in features_available]
    if missing:
        print(f"  Missing: {missing}")

    cfg = FavRLConfig()
    # min_train=3: RL data only from 2014+ (7 seasons), need 3+1+2=6 for folds
    print("Running walk-forward classification...")
    fold_results = run_walk_forward_fav_rl(df, features_available, cfg=cfg, min_train=3)

    # Collect all test predictions
    all_preds = pd.concat([fr.test_predictions for fr in fold_results], ignore_index=True)

    # Merge rl_odds and rule-based filter columns
    mk = ["season", "date", "home_team", "away_team"]
    extra_cols = ["rl_odds", "fav_implied_prob", "fav_close_game_wp", "combined_rpg",
                  "fav_streak_diff", "month", "is_first_half"]
    if "month" not in df.columns:
        df["month"] = pd.to_datetime(df["date"]).dt.month
    if "is_first_half" not in df.columns:
        day = pd.to_datetime(df["date"]).dt.day
        df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (day <= 15))
    keep = [c for c in extra_cols if c in df.columns]
    preds = all_preds.merge(df[mk + keep].drop_duplicates(subset=mk), on=mk, how="left")

    return preds, fold_results, features_available


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def section1_model_quality(fold_results, features):
    print(f"\n{'#'*80}")
    print("SECTION 1: MODEL QUALITY")
    print(f"{'#'*80}")

    aucs = [fr.test_auc for fr in fold_results]
    briers = [fr.test_brier for fr in fold_results]
    print(f"\n  Folds: {len(fold_results)}")
    print(f"  Test AUC:   {np.mean(aucs):.4f} (range {min(aucs):.4f} - {max(aucs):.4f})")
    print(f"  Test Brier: {np.mean(briers):.4f} (range {min(briers):.4f} - {max(briers):.4f})")

    for fr in fold_results:
        print(f"    {fr.fold_name}: AUC={fr.test_auc:.4f}, Brier={fr.test_brier:.4f}, "
              f"n_test={fr.n_test}, threshold_p75={fr.p_cover_threshold:.4f}")

    # Feature importance (average across folds)
    if fold_results[0].feature_importances is not None:
        fi_sum = np.zeros(len(features))
        n_folds = 0
        for fr in fold_results:
            if fr.feature_importances is not None:
                fi_sum += fr.feature_importances
                n_folds += 1
        fi_avg = fi_sum / max(n_folds, 1)
        fi_sorted = sorted(zip(features, fi_avg), key=lambda x: -x[1])
        print(f"\n  Feature importance (avg across {n_folds} folds):")
        for fname, imp in fi_sorted[:15]:
            print(f"    {fname:<40} {imp:6.2f}")


def section2_threshold_scan(preds):
    print(f"\n{'#'*80}")
    print("SECTION 2: P(COVER) THRESHOLD SCAN")
    print(f"{'#'*80}")

    results = []
    for threshold in [0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.52, 0.55]:
        sub = preds[preds["p_cover"] >= threshold]
        r = eval_strat(sub, f"P(cover) >= {threshold:.2f}")
        if r:
            # Also show reduction from full universe
            r["reduction"] = 1 - len(sub) / len(preds)
            results.append(r)

    ptable(results, "THRESHOLD SCAN — P(cover) as primary filter")
    for r in results:
        print(f"    {r['filter']:<40} universe reduction: {r['reduction']*100:.0f}%")

    return results


def section3_ml_plus_rules(preds):
    print(f"\n{'#'*80}")
    print("SECTION 3: ML FILTER + RULE-BASED FILTERS")
    print(f"{'#'*80}")

    # Find best threshold from section 2 (positive ROI, decent volume)
    best_t = 0.44
    for t in [0.44, 0.46, 0.48]:
        sub = preds[preds["p_cover"] >= t]
        if len(sub) >= 50:
            r = eval_strat(sub, f"t={t}")
            if r and r["roi"] > 0:
                best_t = t
                break

    print(f"\n  Using ML threshold: P(cover) >= {best_t:.2f}")
    ml_base = preds[preds["p_cover"] >= best_t].copy()
    print(f"  ML base: {len(ml_base)} games ({len(ml_base)/len(preds)*100:.0f}% of universe)")

    results = [eval_strat(ml_base, f"ML only (p>={best_t})")]

    # Rule-based filters on top of ML
    combos = {}
    if "fav_close_game_wp" in ml_base.columns:
        combos["+ close_wp<=0.45"] = ml_base["fav_close_game_wp"] <= 0.45
        combos["+ close_wp<=0.50"] = ml_base["fav_close_game_wp"] <= 0.50

    if "fav_implied_prob" in ml_base.columns:
        combos["+ impl 65-70%"] = (ml_base["fav_implied_prob"] >= 0.65) & (ml_base["fav_implied_prob"] < 0.70)
        combos["+ impl 60-70%"] = (ml_base["fav_implied_prob"] >= 0.60) & (ml_base["fav_implied_prob"] < 0.70)

    if "combined_rpg" in ml_base.columns:
        combos["+ rpg>=9.5"] = ml_base["combined_rpg"] >= 9.5

    if "fav_streak_diff" in ml_base.columns:
        combos["+ streak>=0"] = ml_base["fav_streak_diff"] >= 0

    if "is_first_half" in ml_base.columns:
        combos["+ 1H only"] = ml_base["is_first_half"]

    for name, mask in combos.items():
        mask = mask.fillna(False)
        r = eval_strat(ml_base[mask], f"ML(p>={best_t}) {name}")
        if r:
            results.append(r)

    # Multi-layer combos
    if "fav_close_game_wp" in ml_base.columns and "fav_streak_diff" in ml_base.columns:
        m = (ml_base["fav_close_game_wp"] <= 0.45) & (ml_base["fav_streak_diff"] >= 0)
        r = eval_strat(ml_base[m.fillna(False)], f"ML(p>={best_t}) + cwp<=0.45 + streak>=0")
        if r:
            results.append(r)

    if "fav_close_game_wp" in ml_base.columns and "fav_implied_prob" in ml_base.columns:
        m = (ml_base["fav_close_game_wp"] <= 0.45) & (ml_base["fav_implied_prob"] >= 0.65) & (ml_base["fav_implied_prob"] < 0.70)
        r = eval_strat(ml_base[m.fillna(False)], f"ML(p>={best_t}) + cwp<=0.45 + impl65-70")
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["sharpe"])
    ptable(results, f"ML (p>={best_t}) + RULE-BASED FILTERS")
    return results


def section4_train_test(preds):
    print(f"\n{'#'*80}")
    print("SECTION 4: TRAIN / TEST VALIDATION")
    print(f"{'#'*80}")

    train = preds[preds["season"].isin(range(2010, 2018))].copy()
    test = preds[preds["season"].isin([2018, 2019, 2021])].copy()

    print(f"\n  TRAIN: {len(train)} games, TEST: {len(test)} games")

    for label, split in [("TRAIN", train), ("TEST", test)]:
        print(f"\n  --- {label} ---")
        for t in [0.44, 0.46, 0.48]:
            sub = split[split["p_cover"] >= t]
            r = eval_strat(sub, f"[{label}] p>={t}")
            if r:
                rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                print(f"    p>={t}: {r['bets']:4d} bets  cvr {r['cr']*100:.1f}%  "
                      f"ROI {r['roi']:+.1f}%  Sharpe {r['sharpe']:.3f}  [{rois}]")

        # ML + close_wp on each split
        if "fav_close_game_wp" in split.columns:
            for t in [0.44, 0.46]:
                sub = split[(split["p_cover"] >= t) & (split["fav_close_game_wp"] <= 0.45)]
                r = eval_strat(sub, f"[{label}] p>={t} + cwp<=0.45")
                if r:
                    rois = ", ".join(f"{x:+.0f}" for x in r["season_rois"])
                    print(f"    p>={t}+cwp<=0.45: {r['bets']:4d} bets  cvr {r['cr']*100:.1f}%  "
                          f"ROI {r['roi']:+.1f}%  Sharpe {r['sharpe']:.3f}  [{rois}]")


def section5_comparison(preds):
    print(f"\n{'#'*80}")
    print("SECTION 5: COMPARISON WITH RULE-ONLY SYSTEM")
    print(f"{'#'*80}")

    # Rule-only baseline (from rl_fav_analysis.py findings)
    if "fav_close_game_wp" in preds.columns and "fav_streak_diff" in preds.columns:
        rule_mask = (preds["fav_close_game_wp"] <= 0.45) & (preds["fav_streak_diff"] >= 0)
        r_rule = eval_strat(preds[rule_mask.fillna(False)], "RULE: cwp<=0.45 + streak>=0")
    else:
        r_rule = eval_strat(preds, "RULE: baseline (all)")

    r_baseline = eval_strat(preds, "Baseline (all games)")

    # ML-only at various thresholds
    r_ml44 = eval_strat(preds[preds["p_cover"] >= 0.44], "ML: p>=0.44")
    r_ml46 = eval_strat(preds[preds["p_cover"] >= 0.46], "ML: p>=0.46")

    # ML + rules
    ml_rule = None
    if "fav_close_game_wp" in preds.columns:
        m = (preds["p_cover"] >= 0.44) & (preds["fav_close_game_wp"] <= 0.45)
        ml_rule = eval_strat(preds[m.fillna(False)], "ML(0.44) + cwp<=0.45")

    results = [r for r in [r_baseline, r_rule, r_ml44, r_ml46, ml_rule] if r is not None]
    ptable(results, "SYSTEM COMPARISON")

    print(f"\n  Reference: S3-dual (away ML) = ~44 bets/season, +17.9% ROI, Sharpe 0.98")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    preds, fold_results, features = build_dataset()
    section1_model_quality(fold_results, features)
    section2_threshold_scan(preds)
    section3_ml_plus_rules(preds)
    section4_train_test(preds)
    section5_comparison(preds)


if __name__ == "__main__":
    main()
