"""A/B test: team quality features for UNDER model.

5 variants tested:
  B0 (baseline)  — 22 combined features (current production)
  R1             — 22 + rpi_combined = 23
  H1             — 22 + hold_rate_combined = 23
  C1             — 22 + close_game_wp_combined = 23
  RHC            — 22 + all 3 = 25

Answers:
  1. Does RPI add signal beyond pyth_wp_combined? (R1 vs B0)
  2. Was hold_rate the culprit in session-18 bundle? (H1 vs B0)
  3. Does close_game_wp help O/U prediction? (C1 vs B0)
  4. Do the 3 features synergize or interfere? (RHC vs B0)

Decision gates (pre-specified):
  PASS:        ROI >= B0 - 2pp AND AUC >= B0 - 0.003
  STRONG PASS: ROI >  B0 + 3pp AND AUC >  B0
  FAIL:        ROI <  B0 - 5pp OR  AUC <  B0 - 0.005
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import warnings

import numpy as np
import pandas as pd

from src.data_loader import (
    add_derived_odds,
    apply_data_filters,
    enrich_innings_from_retrosheet,
    load_all_seasons,
)
from src.features import (
    OU_FEATURES,
    OU_FEATURES_C1,
    OU_FEATURES_H1,
    OU_FEATURES_R1,
    OU_FEATURES_RHC,
    build_all_features,
    build_ou_features,
)
from src.model import UnderModelConfig, run_walk_forward_under, train_under_model

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

ODDS_UNDER = 1.909  # -110 decimal
THRESHOLDS = [0.52, 0.55, 0.58, 0.60]


def simulate_betting(results, threshold: float) -> dict:
    """Simulate flat-bet at P(under) >= threshold at -110 odds."""
    all_preds = pd.concat(
        [r.test_predictions for r in results if r.test_predictions is not None],
        ignore_index=True,
    )
    mask = (
        all_preds["is_push"] == False  # noqa: E712
        if "is_push" in all_preds.columns
        else pd.Series(True, index=all_preds.index)
    )
    preds = all_preds[mask]
    bets = preds[preds["p_under"] >= threshold]
    if len(bets) == 0:
        return {"n_bets": 0, "hit_rate": 0.0, "roi": 0.0, "profit": 0.0}
    wins = bets["under_hit"].sum()
    n = len(bets)
    profit = wins * (ODDS_UNDER - 1) - (n - wins) * 1
    return {"n_bets": n, "hit_rate": wins / n, "roi": profit / n, "profit": profit}


def sign_test_vs_baseline(baseline_results, variant_results) -> dict:
    """Paired sign test: how many folds does the variant beat baseline on AUC."""
    n_folds = min(len(baseline_results), len(variant_results))
    wins = 0
    losses = 0
    ties = 0
    for i in range(n_folds):
        diff = variant_results[i].test_auc - baseline_results[i].test_auc
        if diff > 0.0001:
            wins += 1
        elif diff < -0.0001:
            losses += 1
        else:
            ties += 1
    return {"wins": wins, "losses": losses, "ties": ties, "n_folds": n_folds}


def get_feature_importance(df, features, cfg):
    """Train one model on latest seasons and return feature importance."""
    seasons = sorted(df["season"].unique().tolist())
    train_s = seasons[:-2]
    val_s = [seasons[-2]]
    cb, _, _, _ = train_under_model(df, features, train_s, val_s, cfg=cfg)
    importances = cb.get_feature_importance()
    fi = sorted(zip(features, importances), key=lambda x: -x[1])
    return fi


def apply_gate(baseline_roi, baseline_auc, variant_roi, variant_auc) -> str:
    """Apply pre-specified decision gates."""
    d_roi = variant_roi - baseline_roi
    d_auc = variant_auc - baseline_auc

    if variant_roi < baseline_roi - 0.05 or variant_auc < baseline_auc - 0.005:
        return "FAIL"
    if variant_roi > baseline_roi + 0.03 and variant_auc > baseline_auc:
        return "STRONG PASS"
    if variant_roi >= baseline_roi - 0.02 and variant_auc >= baseline_auc - 0.003:
        return "PASS"
    return "MARGINAL"


def main():
    print("=" * 110)
    print("UNDER MODEL A/B: Team Quality Features (RPI, Hold Rate, Close Game WP)")
    print("=" * 110)

    # ── Load data once ─────────────────────────────────────────────────────
    logger.info("Loading and enriching data...")
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    # ── Build feature set (single call — all combined features computed) ───
    logger.info("Building O/U features...")
    ou = build_ou_features(enriched=enriched)

    # ── Resolve available features per variant ─────────────────────────────
    def resolve_features(feature_list, label):
        available = [
            f for f in feature_list
            if f in ou.columns and ou[f].notna().mean() > 0.3
        ]
        missing = [f for f in feature_list if f not in available]
        coverage = {
            f: f"{ou[f].notna().mean() * 100:.0f}%"
            for f in feature_list if f in ou.columns
        }
        print(f"  {label}: {len(available)}/{len(feature_list)} features")
        if missing:
            print(f"    Missing/low coverage: {missing}")
        # Show coverage for new features only
        new_feats = [f for f in feature_list if f not in OU_FEATURES]
        if new_feats:
            for f in new_feats:
                cov = coverage.get(f, "N/A")
                print(f"    {f}: {cov} non-null")
        return available

    print("\nFeature availability:")
    feats_b0 = resolve_features(OU_FEATURES, "B0 (baseline)")
    feats_r1 = resolve_features(OU_FEATURES_R1, "R1 (+rpi)")
    feats_h1 = resolve_features(OU_FEATURES_H1, "H1 (+hold_rate)")
    feats_c1 = resolve_features(OU_FEATURES_C1, "C1 (+close_game_wp)")
    feats_rhc = resolve_features(OU_FEATURES_RHC, "RHC (+all 3)")

    # ── Run 5 variants ─────────────────────────────────────────────────────
    cfg = UnderModelConfig()
    variants = [
        ("B0", feats_b0),
        ("R1", feats_r1),
        ("H1", feats_h1),
        ("C1", feats_c1),
        ("RHC", feats_rhc),
    ]

    all_results = {}
    for name, feats in variants:
        logger.info(f"Running {name} walk-forward ({len(feats)} features)...")
        results = run_walk_forward_under(ou, feats, cfg=cfg)
        all_results[name] = results
        avg_auc = np.mean([r.test_auc for r in results])
        avg_brier = np.mean([r.test_brier for r in results])
        logger.info(f"  {name}: avg AUC={avg_auc:.4f}, avg Brier={avg_brier:.4f}")

    # ── Summary table ──────────────────────────────────────────────────────
    names = [n for n, _ in variants]
    b0_results = all_results["B0"]
    b0_auc = np.mean([r.test_auc for r in b0_results])
    b0_brier = np.mean([r.test_brier for r in b0_results])
    b0_roi_55 = simulate_betting(b0_results, 0.55)["roi"]

    print("\n" + "=" * 110)
    print("SUMMARY: avg test AUC / Brier across walk-forward folds")
    print("=" * 110)
    print(f"  {'Variant':<8} {'#Feat':>6} {'AUC':>8} {'dAUC':>8} "
          f"{'Brier':>8} {'Std AUC':>9} {'Sign Test':>12}")
    print("-" * 75)

    for name in names:
        results = all_results[name]
        aucs = [r.test_auc for r in results]
        briers = [r.test_brier for r in results]
        avg_auc = np.mean(aucs)
        avg_brier = np.mean(briers)
        d_auc = avg_auc - b0_auc

        if name == "B0":
            sign_str = "BASELINE"
        else:
            st = sign_test_vs_baseline(b0_results, results)
            sign_str = f"{st['wins']}W-{st['losses']}L-{st['ties']}T"

        nf_val = {"B0": len(feats_b0), "R1": len(feats_r1), "H1": len(feats_h1),
                  "C1": len(feats_c1), "RHC": len(feats_rhc)}[name]
        print(
            f"  {name:<8} {nf_val:>6} {avg_auc:>8.4f} {d_auc:>+8.4f} "
            f"{avg_brier:>8.4f} {np.std(aucs):>9.4f} {sign_str:>12}"
        )

    # ── Per-fold AUC detail ───────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("PER-FOLD AUC COMPARISON")
    print("=" * 110)
    header = f"  {'Fold':<30}" + "".join(f" {n:>8}" for n in names)
    print(header)
    print("-" * 110)

    n_folds = len(b0_results)
    for i in range(n_folds):
        fold_name = b0_results[i].fold_name
        vals = [all_results[n][i].test_auc if i < len(all_results[n]) else 0.0
                for n in names]
        best = max(vals)
        row = f"  {fold_name:<30}"
        for v in vals:
            marker = "*" if abs(v - best) < 0.0001 else " "
            row += f" {v:>7.4f}{marker}"
        print(row)

    # ── Betting simulation ─────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("BETTING SIMULATION (flat $100 at -110)")
    print("=" * 110)

    for threshold in THRESHOLDS:
        print(f"\n  P(under) >= {threshold:.2f}:")
        for name in names:
            s = simulate_betting(all_results[name], threshold)
            print(
                f"    {name:<5}: {s['n_bets']:>5} bets, "
                f"hit {s['hit_rate']*100:>5.1f}%, "
                f"ROI {s['roi']*100:>+6.1f}%, "
                f"P/L ${s['profit']:>+8.0f}"
            )

    # ── Decision gates ─────────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("DECISION GATES (primary: ROI @ P>=0.55, AUC)")
    print("=" * 110)
    print(f"  Baseline B0: AUC={b0_auc:.4f}, ROI@0.55={b0_roi_55*100:+.1f}%")
    print()

    for name in names:
        if name == "B0":
            continue
        results = all_results[name]
        v_auc = np.mean([r.test_auc for r in results])
        v_roi = simulate_betting(results, 0.55)["roi"]
        gate = apply_gate(b0_roi_55, b0_auc, v_roi, v_auc)
        d_roi = (v_roi - b0_roi_55) * 100
        d_auc = v_auc - b0_auc
        print(
            f"  {name:<5}: AUC={v_auc:.4f} ({d_auc:+.4f}), "
            f"ROI={v_roi*100:+.1f}% ({d_roi:+.1f}pp) => {gate}"
        )

    # ── Overfitting check ──────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("OVERFITTING CHECK (val AUC - test AUC gap)")
    print("=" * 110)
    for name in names:
        gaps = [r.val_auc - r.test_auc for r in all_results[name]]
        print(f"  {name:<5}: avg gap {np.mean(gaps):>+.4f} (std {np.std(gaps):.4f})")

    # ── Feature importance (last fold, per variant) ────────────────────────
    print("\n" + "=" * 110)
    print("FEATURE IMPORTANCE (trained on latest fold, top 10)")
    print("=" * 110)

    feat_map = {
        "B0": feats_b0, "R1": feats_r1, "H1": feats_h1,
        "C1": feats_c1, "RHC": feats_rhc,
    }

    for name in names:
        feats = feat_map[name]
        fi = get_feature_importance(ou, feats, cfg)
        print(f"\n  {name}:")
        for feat_name, imp in fi[:10]:
            new_marker = " *NEW*" if feat_name not in OU_FEATURES else ""
            print(f"    {feat_name:<35} {imp:>6.2f}%{new_marker}")

    # ── Final verdict ──────────────────────────────────────────────────────
    print("\n" + "=" * 110)
    print("VERDICT")
    print("=" * 110)

    passed = []
    for name in ["R1", "H1", "C1", "RHC"]:
        results = all_results[name]
        v_auc = np.mean([r.test_auc for r in results])
        v_roi = simulate_betting(results, 0.55)["roi"]
        gate = apply_gate(b0_roi_55, b0_auc, v_roi, v_auc)
        if gate in ("PASS", "STRONG PASS"):
            passed.append((name, gate, v_roi, v_auc))

    if not passed:
        print("  No variant passed decision gates.")
        print("  Current 22-feature B0 remains production default.")
    else:
        print(f"  Passed variants: {len(passed)}")
        for name, gate, roi, auc in passed:
            print(f"    {name}: {gate} (ROI={roi*100:+.1f}%, AUC={auc:.4f})")
        best = max(passed, key=lambda x: x[2])
        print(f"\n  RECOMMENDED: {best[0]} ({best[1]})")
        if len(passed) >= 2:
            print("  Phase 2: test pairwise combinations of passing features.")


if __name__ == "__main__":
    main()
