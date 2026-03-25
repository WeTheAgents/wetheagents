"""A/B matrix: UNDER model V1 vs V3 (hybrid) x depth 4 vs 5.

4 variants tested:
  V1-d5 (baseline)  — 22 combined features, depth=5
  V3-d5             — 22 combined + 4 interactions = 26, depth=5
  V3-d4             — 26 features, depth=4 (more regularized)
  V1-d4 (control)   — 22 features, depth=4

Answers two independent questions:
  1. Do the 4 interactions help? (V3 vs V1 at same depth)
  2. Does depth=4 help? (d4 vs d5 with same features)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import copy
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
    OU_FEATURES_V3,
    build_all_features,
    build_ou_features,
    build_ou_features_v3,
)
from src.model import UnderModelConfig, run_walk_forward_under

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

ODDS_UNDER = 1.909  # -110 decimal


def simulate_betting(results, threshold: float) -> dict:
    """Simulate flat-bet at P(under) >= threshold at -110 odds."""
    all_preds = pd.concat(
        [r.test_predictions for r in results if r.test_predictions is not None],
        ignore_index=True,
    )
    mask = all_preds["is_push"] == False if "is_push" in all_preds.columns else pd.Series(True, index=all_preds.index)  # noqa: E712
    preds = all_preds[mask]
    bets = preds[preds["p_under"] >= threshold]
    if len(bets) == 0:
        return {"n_bets": 0, "hit_rate": 0.0, "roi": 0.0, "profit": 0.0}
    wins = bets["under_hit"].sum()
    n = len(bets)
    profit = wins * (ODDS_UNDER - 1) - (n - wins) * 1
    return {"n_bets": n, "hit_rate": wins / n, "roi": profit / n, "profit": profit}


def make_cfg(depth: int) -> UnderModelConfig:
    """Create UnderModelConfig with custom depth."""
    cfg = UnderModelConfig()
    params = copy.deepcopy(cfg.catboost_params)
    params["depth"] = depth
    cfg.catboost_params = params
    return cfg


def main():
    print("=" * 100)
    print("UNDER MODEL A/B MATRIX: V1 vs V3 (hybrid) x depth 4 vs 5")
    print("=" * 100)

    # ── Load data once ─────────────────────────────────────────────────────
    logger.info("Loading and enriching data...")
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    # ── Build feature sets ─────────────────────────────────────────────────
    logger.info("Building V1 features...")
    ou_v1 = build_ou_features(enriched=enriched)
    feats_v1 = [f for f in OU_FEATURES if f in ou_v1.columns and ou_v1[f].notna().mean() > 0.3]

    logger.info("Building V3 features...")
    ou_v3 = build_ou_features_v3(enriched=enriched)
    feats_v3 = [f for f in OU_FEATURES_V3 if f in ou_v3.columns and ou_v3[f].notna().mean() > 0.3]

    print(f"\nV1 features: {len(feats_v1)}/{len(OU_FEATURES)}")
    print(f"V3 features: {len(feats_v3)}/{len(OU_FEATURES_V3)}")
    print(f"V3 additions: {[f for f in feats_v3 if f not in feats_v1]}")

    # ── Run 4 variants ─────────────────────────────────────────────────────
    variants = [
        ("V1-d5", ou_v1, feats_v1, make_cfg(5)),
        ("V3-d5", ou_v3, feats_v3, make_cfg(5)),
        ("V3-d4", ou_v3, feats_v3, make_cfg(4)),
        ("V1-d4", ou_v1, feats_v1, make_cfg(4)),
    ]

    all_results = {}
    for name, df, feats, cfg in variants:
        logger.info(f"Running {name} walk-forward ({len(feats)} features, depth={cfg.catboost_params['depth']})...")
        results = run_walk_forward_under(df, feats, cfg=cfg)
        all_results[name] = results
        avg_auc = np.mean([r.test_auc for r in results])
        avg_brier = np.mean([r.test_brier for r in results])
        logger.info(f"  {name}: avg AUC={avg_auc:.4f}, avg Brier={avg_brier:.4f}")

    # ── Summary table ──────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("SUMMARY: avg test AUC / Brier across 14 folds")
    print("=" * 100)
    print(f"  {'Variant':<12} {'Features':>8} {'Depth':>6} {'AUC':>8} {'Brier':>8} {'Std AUC':>9}")
    print("-" * 60)

    baseline_auc = np.mean([r.test_auc for r in all_results["V1-d5"]])
    baseline_brier = np.mean([r.test_brier for r in all_results["V1-d5"]])

    for name in ["V1-d5", "V3-d5", "V3-d4", "V1-d4"]:
        results = all_results[name]
        aucs = [r.test_auc for r in results]
        briers = [r.test_brier for r in results]
        nf = len(feats_v3) if "V3" in name else len(feats_v1)
        d = 4 if "d4" in name else 5
        avg_auc = np.mean(aucs)
        avg_brier = np.mean(briers)
        d_auc = avg_auc - baseline_auc
        marker = "BASELINE" if name == "V1-d5" else (
            "BETTER" if d_auc > 0.001 else "WORSE" if d_auc < -0.001 else "FLAT"
        )
        print(
            f"  {name:<12} {nf:>8} {d:>6} {avg_auc:>8.4f} {avg_brier:>8.4f} "
            f"{np.std(aucs):>9.4f}  {d_auc:>+.4f} {marker}"
        )

    # ── Per-fold detail for all variants ───────────────────────────────────
    print("\n" + "=" * 100)
    print("PER-FOLD AUC COMPARISON")
    print("=" * 100)
    names = ["V1-d5", "V3-d5", "V3-d4", "V1-d4"]
    header = f"  {'Fold':<25}" + "".join(f" {n:>8}" for n in names)
    print(header)
    print("-" * 100)

    n_folds = len(all_results["V1-d5"])
    for i in range(n_folds):
        fold_name = all_results["V1-d5"][i].fold_name
        vals = [all_results[n][i].test_auc for n in names]
        best = max(vals)
        row = f"  {fold_name:<25}"
        for v in vals:
            marker = "*" if v == best else " "
            row += f" {v:>7.4f}{marker}"
        print(row)

    # ── Betting simulation ─────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("BETTING SIMULATION (flat $100 at -110)")
    print("=" * 100)

    for threshold in [0.52, 0.55, 0.58, 0.60]:
        print(f"\n  P(under) >= {threshold:.2f}:")
        for name in names:
            s = simulate_betting(all_results[name], threshold)
            print(
                f"    {name:<8}: {s['n_bets']:>5} bets, "
                f"hit {s['hit_rate']*100:>5.1f}%, "
                f"ROI {s['roi']*100:>+6.1f}%, "
                f"P/L ${s['profit']:>+8.0f}"
            )

    # ── Overfitting check ──────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("OVERFITTING CHECK (val AUC - test AUC gap)")
    print("=" * 100)
    for name in names:
        gaps = [r.val_auc - r.test_auc for r in all_results[name]]
        print(f"  {name:<8}: avg gap {np.mean(gaps):>+.4f} (std {np.std(gaps):.4f})")

    # ── Factorial analysis ─────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("FACTORIAL ANALYSIS")
    print("=" * 100)

    v1d5 = np.mean([r.test_auc for r in all_results["V1-d5"]])
    v3d5 = np.mean([r.test_auc for r in all_results["V3-d5"]])
    v3d4 = np.mean([r.test_auc for r in all_results["V3-d4"]])
    v1d4 = np.mean([r.test_auc for r in all_results["V1-d4"]])

    interaction_effect = ((v3d5 - v1d5) + (v3d4 - v1d4)) / 2
    depth_effect = ((v1d4 - v1d5) + (v3d4 - v3d5)) / 2
    print(f"  Interaction features effect (avg): {interaction_effect:>+.4f} AUC")
    print(f"  Depth 4 vs 5 effect (avg):         {depth_effect:>+.4f} AUC")

    # ── Final verdict ──────────────────────────────────────────────────────
    best_name = max(names, key=lambda n: np.mean([r.test_auc for r in all_results[n]]))
    best_auc = np.mean([r.test_auc for r in all_results[best_name]])
    print(f"\n  BEST VARIANT: {best_name} (AUC={best_auc:.4f})")
    if best_name == "V1-d5":
        print("  V1-d5 remains production default. No change needed.")
    else:
        print(f"  {best_name} beats baseline by {best_auc - v1d5:+.4f} AUC.")
        print("  Operator decision required to adopt.")


if __name__ == "__main__":
    main()
