"""NRFI binary classifier: A/B/C feature set comparison with walk-forward validation.

Mirrors the UNDER model architecture (CatBoost+LogReg ensemble, None calibration)
but targets first-inning outcomes: nrfi_hit = (inn1_runs == 0).

Three feature sets tested:
  A: 1st-inning specific (13 features from build_yrfi_features)
  B: UNDER V3 features retrained on nrfi_hit target (25 features)
  C: Hybrid — top features from A + B by importance

Decision gate (from session 21):
  Gate 1: P(nrfi)>=0.60 → >60% hit + >0% adj_roi + >=7/15 seasons → PRODUCTION
  Gate 2: P(nrfi)>=0.65 → >65% hit + >0% adj_roi → HIGH-CONF ONLY
  Neither → NRFI ML dead, use rule-based filters

Usage:
    python scripts/run_nrfi_model.py
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd

BASE_UNIT = 100


# ── Helpers ──────────────────────────────────────────────────────────────

def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def nrfi_bankroll_metrics(df, name, odds_col="nrfi_est_odds"):
    """Compute bankroll metrics for NRFI bets with per-game variable odds."""
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 10:
        return None

    hit = df["nrfi_hit"].values.astype(float)
    est_odds = df[odds_col].values

    # PnL: win pays (odds-1)*100, loss costs 100
    pnl = np.where(hit, (est_odds - 1) * BASE_UNIT, -BASE_UNIT)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * BASE_UNIT) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    avg_odds = est_odds.mean()
    b = avg_odds - 1
    kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)

    mls = max_streak(hit, target=0)
    mws = max_streak(hit, target=1)

    bankroll = 10000 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    dd_pct = (peak - bankroll) / peak * 100
    max_dd = dd_pct.max()

    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(
            df.loc[sm, "nrfi_hit"].values,
            (df.loc[sm, odds_col].values - 1) * BASE_UNIT,
            -BASE_UNIT,
        )
        season_rois.append(sp.sum() / (sn * BASE_UNIT) * 100)

    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bets_per_season": n / df["season"].nunique(),
        "hit_rate": hr,
        "avg_odds": avg_odds,
        "roi": roi,
        "sharpe": sharpe,
        "kelly_full": kelly_full,
        "kelly_half": kelly_full / 2,
        "max_loss_streak": mls,
        "max_win_streak": mws,
        "max_dd_pct": max_dd,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "n_seasons": len(season_rois),
        "n_pos_seasons": n_pos,
        "worst_season": min(season_rois) if season_rois else 0,
        "best_season": max(season_rois) if season_rois else 0,
    }


def print_row(m):
    if m is None:
        return
    print(
        f"  {m['name']:<35} {m['bets']:5d} {m['bets_per_season']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['avg_odds']:.2f} {m['roi']:+6.1f}% "
        f"{m['max_loss_streak']:5d} {m['max_dd_pct']:5.1f}% "
        f"{m['sharpe']:6.3f} {m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
    )


def print_table_header():
    print(
        f"  {'Filter':<35} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
        f"{'Odds':>5} {'ROI':>7} {'MaxL':>5} {'DD%':>6} "
        f"{'Shrp':>7} {'K/2':>6} {'Flds':>6}"
    )
    print("-" * 115)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    from src.features import (
        NRFI_FEATURES_A,
        OU_FEATURES_V3,
        build_yrfi_features,
    )
    from src.market_builder import estimate_nrfi_odds
    from src.model import NRFIModelConfig, run_walk_forward_nrfi

    # ══════════════════════════════════════════════════════════════════════
    # STEP 1: Build features
    # ══════════════════════════════════════════════════════════════════════
    print("=" * 80)
    print("STEP 1: Building YRFI features (reuse for NRFI)")
    print("=" * 80)

    df = build_yrfi_features()
    print(f"Games with inning data: {len(df)}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2: Prepare NRFI target, odds, filters
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 2: NRFI target + market-adjusted odds + filters")
    print("=" * 80)

    # Target
    df["inn1_runs"] = df["away_inn_1"] + df["home_inn_1"]
    df["nrfi_hit"] = (df["inn1_runs"] == 0).astype(int)

    # Market-adjusted odds
    df["nrfi_est_odds"] = estimate_nrfi_odds(df["close_ou"])
    df["nrfi_breakeven"] = 1.0 / df["nrfi_est_odds"]

    # Filters: no Colorado, no April
    pre_filter = len(df)
    if "involves_col" in df.columns:
        df = df[~df["involves_col"]].copy()
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df = df[df["month"] != 4].copy()
    if "is_extreme_line" in df.columns:
        df = df[~df["is_extreme_line"]].copy()
    post_filter = len(df)

    print(f"After filters (no COL, no April, no extreme): {post_filter} (removed {pre_filter - post_filter})")
    print(f"NRFI rate (unconditional): {df['nrfi_hit'].mean()*100:.1f}%")
    print(f"Average estimated odds: {df['nrfi_est_odds'].mean():.3f}")
    print(f"Average breakeven: {df['nrfi_breakeven'].mean()*100:.1f}%")
    print(f"Seasons: {sorted(df['season'].unique())}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 3: Feature coverage report
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 3: Feature coverage")
    print("=" * 80)

    feature_sets = {
        "A (1st-inning)": NRFI_FEATURES_A,
        "B (UNDER V3)": OU_FEATURES_V3,
    }

    available_features = {}
    for set_name, flist in feature_sets.items():
        avail = [f for f in flist if f in df.columns and df[f].notna().mean() > 0.3]
        missing = [f for f in flist if f not in avail]
        available_features[set_name] = avail
        print(f"\nSet {set_name}: {len(avail)}/{len(flist)} available")
        for f in avail:
            cov = df[f].notna().mean() * 100
            print(f"  {f:<35} {cov:5.1f}%")
        if missing:
            print(f"  MISSING: {missing}")

    features_A = available_features["A (1st-inning)"]
    features_B = available_features["B (UNDER V3)"]

    if len(features_A) < 5:
        print("\nERROR: Too few Set A features available. Check build_yrfi_features().")
        return
    if len(features_B) < 5:
        print("\nERROR: Too few Set B features available. Check build_ou_features().")
        return

    # ══════════════════════════════════════════════════════════════════════
    # STEP 4: Walk-forward Set A
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"STEP 4: Walk-forward Set A ({len(features_A)} features)")
    print("=" * 80)

    cfg = NRFIModelConfig()
    results_A = run_walk_forward_nrfi(df, features_A, cfg=cfg)

    if not results_A:
        print("ERROR: No folds for Set A.")
        return

    print("\nFold metrics:")
    for r in results_A:
        print(f"  {r.fold_name}: val_AUC={r.val_auc:.4f} val_Brier={r.val_brier:.4f} "
              f"| test_AUC={r.test_auc:.4f} test_Brier={r.test_brier:.4f} (n={r.n_test})")

    mean_auc_A = np.mean([r.test_auc for r in results_A])
    mean_brier_A = np.mean([r.test_brier for r in results_A])
    print(f"\nSet A mean: AUC={mean_auc_A:.4f}, Brier={mean_brier_A:.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 5: Walk-forward Set B
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print(f"STEP 5: Walk-forward Set B ({len(features_B)} features)")
    print("=" * 80)

    results_B = run_walk_forward_nrfi(df, features_B, cfg=cfg)

    if not results_B:
        print("ERROR: No folds for Set B.")
        return

    print("\nFold metrics:")
    for r in results_B:
        print(f"  {r.fold_name}: val_AUC={r.val_auc:.4f} val_Brier={r.val_brier:.4f} "
              f"| test_AUC={r.test_auc:.4f} test_Brier={r.test_brier:.4f} (n={r.n_test})")

    mean_auc_B = np.mean([r.test_auc for r in results_B])
    mean_brier_B = np.mean([r.test_brier for r in results_B])
    print(f"\nSet B mean: AUC={mean_auc_B:.4f}, Brier={mean_brier_B:.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 6: Build Set C (hybrid) from feature importance
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 6: Build hybrid Set C from A+B feature importance")
    print("=" * 80)

    # Get feature importance from last fold of each set
    from src.model import train_nrfi_model

    # Retrain last fold of A to get importance
    last_A = results_A[-1]
    cb_A, _, _, _ = train_nrfi_model(
        df, features_A, last_A.train_seasons, last_A.val_seasons, cfg=cfg,
    )
    imp_A = dict(zip(features_A, cb_A.get_feature_importance()))

    # Retrain last fold of B to get importance
    last_B = results_B[-1]
    cb_B, _, _, _ = train_nrfi_model(
        df, features_B, last_B.train_seasons, last_B.val_seasons, cfg=cfg,
    )
    imp_B = dict(zip(features_B, cb_B.get_feature_importance()))

    print("\nSet A feature importance:")
    for f, imp in sorted(imp_A.items(), key=lambda x: -x[1]):
        print(f"  {f:<35} {imp:6.2f}%")

    print("\nSet B feature importance:")
    for f, imp in sorted(imp_B.items(), key=lambda x: -x[1]):
        print(f"  {f:<35} {imp:6.2f}%")

    # Take top 8 from each, deduplicate
    top_A = sorted(imp_A, key=imp_A.get, reverse=True)[:8]
    top_B = sorted(imp_B, key=imp_B.get, reverse=True)[:8]
    features_C = list(dict.fromkeys(top_A + top_B))  # preserve order, deduplicate

    print(f"\nSet C ({len(features_C)} features): {features_C}")

    # Walk-forward Set C
    results_C = run_walk_forward_nrfi(df, features_C, cfg=cfg)

    if not results_C:
        print("WARNING: No folds for Set C. Continuing with A and B only.")
        results_C = []

    if results_C:
        print("\nFold metrics:")
        for r in results_C:
            print(f"  {r.fold_name}: val_AUC={r.val_auc:.4f} val_Brier={r.val_brier:.4f} "
                  f"| test_AUC={r.test_auc:.4f} test_Brier={r.test_brier:.4f} (n={r.n_test})")

        mean_auc_C = np.mean([r.test_auc for r in results_C])
        mean_brier_C = np.mean([r.test_brier for r in results_C])
        print(f"\nSet C mean: AUC={mean_auc_C:.4f}, Brier={mean_brier_C:.4f}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 7: Profitability map (market-adjusted)
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 7: Profitability map (market-adjusted NRFI odds)")
    print("=" * 80)

    merge_keys = ["season", "date", "home_team", "away_team"]
    thresholds = np.arange(0.50, 0.71, 0.01)

    set_configs = [("A", results_A), ("B", results_B)]
    if results_C:
        set_configs.append(("C", results_C))

    all_set_preds = {}
    for set_name, results in set_configs:
        # Aggregate predictions across folds
        preds = pd.concat(
            [r.test_predictions for r in results if r.test_predictions is not None],
            ignore_index=True,
        )
        # Deduplicate: keep last (more training data)
        preds = preds.sort_values("season").drop_duplicates(
            subset=merge_keys, keep="last",
        )
        # Add estimated odds
        preds["nrfi_est_odds"] = estimate_nrfi_odds(preds["close_ou"])
        all_set_preds[set_name] = preds

    for set_name, preds in all_set_preds.items():
        print(f"\n-- Set {set_name} profitability map --")
        print(f"Total predictions: {len(preds)}, mean P(nrfi): {preds['p_nrfi'].mean():.3f}")
        print_table_header()

        for thr in thresholds:
            mask = preds["p_nrfi"] >= thr
            subset = preds[mask].copy()
            if len(subset) < 10:
                continue
            name = f"P(nrfi)>={thr:.2f}"
            m = nrfi_bankroll_metrics(subset, name)
            if m is not None:
                print_row(m)

    # ══════════════════════════════════════════════════════════════════════
    # STEP 8: Decision gate
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 8: Decision gate evaluation")
    print("=" * 80)

    gate_results = {}
    for set_name, preds in all_set_preds.items():
        print(f"\n-- Set {set_name} --")

        for gate_name, p_thr, hit_thr, min_seasons in [
            ("Gate1 (Production)", 0.60, 0.60, 7),
            ("Gate2 (High-Conf)", 0.65, 0.65, 0),
        ]:
            subset = preds[preds["p_nrfi"] >= p_thr].copy()
            if len(subset) < 20:
                print(f"  {gate_name}: FAIL (only {len(subset)} bets)")
                gate_results[(set_name, gate_name)] = "FAIL"
                continue

            m = nrfi_bankroll_metrics(subset, gate_name)
            if m is None:
                print(f"  {gate_name}: FAIL (insufficient data)")
                gate_results[(set_name, gate_name)] = "FAIL"
                continue

            hr = m["hit_rate"]
            roi = m["roi"]
            n_pos = m["n_pos_seasons"]
            n_total = m["n_seasons"]

            passed = hr >= hit_thr and roi > 0
            if min_seasons > 0:
                passed = passed and n_pos >= min_seasons

            verdict = "PASS" if passed else "FAIL"
            gate_results[(set_name, gate_name)] = verdict

            print(f"  {gate_name}: {verdict}")
            print(f"    Bets={m['bets']}, Hit={hr*100:.1f}% (need >{hit_thr*100:.0f}%), "
                  f"ROI={roi:+.1f}% (need >0%), "
                  f"Seasons={m['seasons_pos']}"
                  f"{f' (need >={min_seasons})' if min_seasons > 0 else ''}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 9: Head-to-head comparison
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 9: Head-to-head comparison")
    print("=" * 80)

    set_summaries = []
    set_features_map = {"A": features_A, "B": features_B}
    if results_C:
        set_features_map["C"] = features_C

    set_results_map = {"A": results_A, "B": results_B}
    if results_C:
        set_results_map["C"] = results_C

    for set_name in all_set_preds:
        results = set_results_map[set_name]
        preds = all_set_preds[set_name]
        feats = set_features_map[set_name]

        mean_auc = np.mean([r.test_auc for r in results])
        mean_brier = np.mean([r.test_brier for r in results])

        # Find best threshold (max ROI with >=20 bets)
        best_roi = -999
        best_thr = 0.50
        best_hr = 0
        best_m = None
        for thr in thresholds:
            subset = preds[preds["p_nrfi"] >= thr].copy()
            if len(subset) < 20:
                continue
            m = nrfi_bankroll_metrics(subset, f"P>={thr:.2f}")
            if m and m["roi"] > best_roi:
                best_roi = m["roi"]
                best_thr = thr
                best_hr = m["hit_rate"]
                best_m = m

        g1 = gate_results.get((set_name, "Gate1 (Production)"), "FAIL")
        g2 = gate_results.get((set_name, "Gate2 (High-Conf)"), "FAIL")

        if g1 == "PASS":
            verdict = "PRODUCTION"
        elif g2 == "PASS":
            verdict = "HIGH-CONF"
        else:
            verdict = "FAIL"

        set_summaries.append({
            "Set": set_name,
            "Features": len(feats),
            "AUC": mean_auc,
            "Brier": mean_brier,
            "Best_P": f">={best_thr:.2f}",
            "Hit%": f"{best_hr*100:.1f}%",
            "AdjROI": f"{best_roi:+.1f}%",
            "Seasons": best_m["seasons_pos"] if best_m else "N/A",
            "Verdict": verdict,
        })

    print(f"\n  {'Set':<4} {'Feat':>4} {'AUC':>6} {'Brier':>6} {'Best_P':>7} "
          f"{'Hit%':>6} {'AdjROI':>7} {'Seasons':>8} {'Verdict':>12}")
    print("-" * 75)
    for s in set_summaries:
        print(f"  {s['Set']:<4} {s['Features']:>4} {s['AUC']:>6.4f} {s['Brier']:>6.4f} "
              f"{s['Best_P']:>7} {s['Hit%']:>6} {s['AdjROI']:>7} "
              f"{s['Seasons']:>8} {s['Verdict']:>12}")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 10: Feature importance + calibration for best set
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    print("STEP 10: Calibration analysis (best set)")
    print("=" * 80)

    # Pick the set with best ROI
    best_set = max(set_summaries, key=lambda s: float(s["AdjROI"].rstrip("%")))
    best_name = best_set["Set"]
    preds = all_set_preds[best_name]

    print(f"\nBest set: {best_name}")

    # Calibration deciles
    preds = preds.copy()
    preds["p_decile"] = pd.qcut(preds["p_nrfi"], 10, labels=False, duplicates="drop")

    print("\nCalibration (predicted P(nrfi) vs actual NRFI rate):")
    print(f"  {'Decile':>6} {'N':>6} {'Mean P':>8} {'Actual':>8} {'Gap':>7}")
    print("-" * 45)
    for d in sorted(preds["p_decile"].unique()):
        g = preds[preds["p_decile"] == d]
        mean_p = g["p_nrfi"].mean()
        actual = g["nrfi_hit"].mean()
        gap = actual - mean_p
        print(f"  {d:>6} {len(g):>6} {mean_p:>8.3f} {actual:>8.3f} {gap:>+7.3f}")

    # Per-season NRFI rate
    print("\nPer-season NRFI base rate:")
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        print(f"  {s}: {df.loc[sm, 'nrfi_hit'].mean()*100:.1f}% ({sm.sum()} games)")

    # ══════════════════════════════════════════════════════════════════════
    # VERDICT
    # ══════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 80}")
    any_pass = any(s["Verdict"] != "FAIL" for s in set_summaries)
    if any_pass:
        winners = [s for s in set_summaries if s["Verdict"] != "FAIL"]
        print("VERDICT: NRFI ML model PASSES decision gate")
        for w in winners:
            print(f"  Set {w['Set']}: {w['Verdict']} at {w['Best_P']} "
                  f"({w['Hit%']} hit, {w['AdjROI']} ROI, {w['Seasons']} seasons)")
        print("\nNext: integrate into genome system + add LLM expert gate for edge cases")
    else:
        print("VERDICT: NRFI ML is DEAD — all sets failed decision gates")
        print("Recommendation: use rule-based filters from run_nrfi_research.py")
    print("=" * 80)


if __name__ == "__main__":
    main()
