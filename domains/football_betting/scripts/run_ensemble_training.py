"""Phase 2: Bias-Trained Ensemble — Turkish Super Lig.

Pipeline:
  1. Load data + build features (same as Phase 1)
  2. Add line movement features
  3. Train baseline + 4 biased models + RidgeCV meta-learner
  4. Estimate bivariate Poisson ρ on validation set
  5. Evaluate: goals MAE, match RPS vs Pinnacle (independent vs bivariate)
  6. Print comparison table + per-regime breakdown
  7. Save report

Usage:
    python scripts/run_ensemble_training.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from src.data_loader import add_derived_odds, add_line_movement, apply_data_filters, load_all_seasons
from src.ensemble import make_default_ensemble_config, train_and_evaluate_ensemble
from src.features import MODEL_FEATURES, build_all_features, build_team_level_dataset
from src.model import evaluate_goals, evaluate_match_probabilities

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


def print_comparison(results: dict) -> None:
    """Print side-by-side comparison table."""
    baseline = results["baseline"]
    ensemble = results["ensemble"]
    biased = results["biased"]

    print("\n" + "=" * 80)
    print("  COMPARISON: Baseline vs Biased Models vs Ensemble")
    print("=" * 80)

    # Goals MAE
    print("\n--- Goals MAE (Test Set) ---")
    print(f"  {'Model':25s} {'MAE':>7s} {'vs Naive':>10s}")
    print(f"  {'-'*25} {'-'*7} {'-'*10}")
    print(
        f"  {'Baseline':25s} {baseline['test_goals']['mae']:7.3f} "
        f"{baseline['test_goals']['mae_improvement']:+9.1%}"
    )
    for name, res in biased.items():
        mae = np.mean(np.abs(res["y_test"] - res["pred_test"]))
        naive_mae = np.mean(np.abs(res["y_test"] - np.mean(res["y_test"])))
        imp = 1 - mae / naive_mae if naive_mae > 0 else 0
        print(f"  {name:25s} {mae:7.3f} {imp:+9.1%}")
    if ensemble:
        print(
            f"  {'ENSEMBLE':25s} {ensemble['test_goals']['mae']:7.3f} "
            f"{ensemble['test_goals']['mae_improvement']:+9.1%}"
        )

    # Match RPS — bivariate (primary) vs Pinnacle
    print("\n--- Match RPS vs Pinnacle (Test Set) ---")
    print(f"  {'Model':25s} {'RPS':>8s} {'Pinnacle':>10s} {'vs Pinnacle':>12s}")
    print(f"  {'-'*25} {'-'*8} {'-'*10} {'-'*12}")
    print(
        f"  {'Baseline':25s} {baseline['test_rps']['model_rps']:8.4f} "
        f"{baseline['test_rps']['pinnacle_rps']:10.4f} "
        f"{baseline['test_rps']['rps_improvement']:+11.1%}"
    )
    if ensemble:
        # Independent Poisson ensemble
        indep = ensemble.get("test_rps_independent")
        if indep:
            print(
                f"  {'ENSEMBLE (indep)':25s} {indep['model_rps']:8.4f} "
                f"{indep['pinnacle_rps']:10.4f} "
                f"{indep['rps_improvement']:+11.1%}"
            )
        # Bivariate Poisson ensemble (primary result)
        rho = ensemble.get("rho", 0.0)
        label = f"ENSEMBLE (biv rho={rho:.2f})"
        print(
            f"  {label:25s} {ensemble['test_rps']['model_rps']:8.4f} "
            f"{ensemble['test_rps']['pinnacle_rps']:10.4f} "
            f"{ensemble['test_rps']['rps_improvement']:+11.1%}"
        )

    # Bivariate Poisson impact
    if ensemble and ensemble.get("test_rps_independent"):
        indep_rps = ensemble["test_rps_independent"]["model_rps"]
        biv_rps = ensemble["test_rps"]["model_rps"]
        rho = ensemble.get("rho", 0.0)
        if indep_rps > 0:
            biv_improvement = 1 - biv_rps / indep_rps
        else:
            biv_improvement = 0.0

        print(f"\n--- Bivariate Poisson Impact ---")
        print(f"  Independent RPS:   {indep_rps:.5f}")
        print(f"  Bivariate RPS:     {biv_rps:.5f}  (rho={rho:.3f})")
        print(f"  Improvement:       {biv_improvement:+.2%}")

    # Meta-learner alpha selection
    if ensemble:
        alpha_h = ensemble.get("meta_alpha_home")
        alpha_a = ensemble.get("meta_alpha_away")
        if alpha_h is not None:
            print(f"\n--- Meta-Learner Alpha Selection ---")
            print(f"  Home alpha: {alpha_h:.4f}")
            print(f"  Away alpha: {alpha_a:.4f}")

    # Meta-learner coefficients
    if ensemble and "meta_coefs" in ensemble:
        print("\n--- Meta-Learner Coefficients ---")
        print(f"  {'Model':25s} {'Home coef':>12s} {'Away coef':>12s}")
        print(f"  {'-'*25} {'-'*12} {'-'*12}")
        for name, coefs in ensemble["meta_coefs"].items():
            print(f"  {name:25s} {coefs['home_coef']:+11.3f} {coefs['away_coef']:+11.3f}")
        print(f"  {'intercept (home)':25s} {ensemble['ridge_home'].intercept_:+11.3f}")
        print(f"  {'intercept (away)':25s} {ensemble['ridge_away'].intercept_:+11.3f}")


def print_regime_analysis(results: dict, team_df, games) -> None:
    """Print per-regime RPS breakdown on test set."""
    ensemble = results["ensemble"]
    if not ensemble:
        return

    base_cfg = results["baseline"]["config"]
    test_df = team_df[team_df["season"].isin(base_cfg.test_seasons)].copy()
    test_games = games[games["season"].isin(base_cfg.test_seasons)].copy()

    is_home_test = test_df["is_home"].values
    test_home_mask = is_home_test == 1

    rho = ensemble.get("rho", 0.0)

    # Get ensemble lambdas
    ens_home_lambda = ensemble["test_lambda"][test_home_mask]
    ens_away_lambda = ensemble["test_lambda"][~test_home_mask]

    # Baseline lambdas
    bl_home_lambda = results["baseline"]["predictions"]["test_home_lambda"]
    bl_away_lambda = results["baseline"]["predictions"]["test_away_lambda"]

    print(f"\n--- Per-Regime RPS Breakdown (Test Set, rho={rho:.3f}) ---")

    # Define regimes on match-level data
    regimes = {}

    # Squad disruption matches
    sss_diff = (test_games["sss_cum_home"] - test_games["sss_cum_away"]).abs()
    regimes["SSS diff > 0.15"] = sss_diff > 0.15

    # Congestion matches
    rest_home = test_games["days_rest_home"].fillna(99)
    rest_away = test_games["days_rest_away"].fillna(99)
    regimes["Short rest (<=3d)"] = (rest_home <= 3) | (rest_away <= 3)

    # Big-3 involvement
    regimes["Big-3 involved"] = (test_games["is_big3_home"] == 1) | (test_games["is_big3_away"] == 1)

    # Non-big-3
    regimes["No Big-3"] = (test_games["is_big3_home"] == 0) & (test_games["is_big3_away"] == 0)

    print(f"  {'Regime':25s} {'N':>5s} {'Baseline RPS':>13s} {'Ensemble RPS':>13s} {'Delta':>8s}")
    print(f"  {'-'*25} {'-'*5} {'-'*13} {'-'*13} {'-'*8}")

    for regime_name, mask in regimes.items():
        mask_arr = mask.values if hasattr(mask, "values") else mask
        n = mask_arr.sum()
        if n < 10:
            continue

        regime_games = test_games[mask_arr]
        regime_bl_home = bl_home_lambda[mask_arr]
        regime_bl_away = bl_away_lambda[mask_arr]
        regime_ens_home = ens_home_lambda[mask_arr]
        regime_ens_away = ens_away_lambda[mask_arr]

        bl_rps = evaluate_match_probabilities(regime_games, regime_bl_home, regime_bl_away, "")
        ens_rps = evaluate_match_probabilities(
            regime_games, regime_ens_home, regime_ens_away, "", rho
        )

        delta = ens_rps["model_rps"] - bl_rps["model_rps"]
        print(
            f"  {regime_name:25s} {n:5d} {bl_rps['model_rps']:13.4f} "
            f"{ens_rps['model_rps']:13.4f} {delta:+7.4f}"
        )


def save_report(results: dict, path: Path) -> None:
    """Save Phase 2 ensemble report."""
    baseline = results["baseline"]
    ensemble = results["ensemble"]
    biased = results["biased"]

    lines = [
        "# Phase 2 — Bias-Trained Ensemble Report",
        "",
        "## Configuration",
        f"- Train: {baseline['config'].train_seasons}",
        f"- Val: {baseline['config'].val_seasons}",
        f"- Test: {baseline['config'].test_seasons}",
        f"- Baseline features: {len(MODEL_FEATURES)}",
        f"- Biased models trained: {len(biased)}",
        "",
    ]

    # Meta-learner tuning
    if ensemble:
        alpha_h = ensemble.get("meta_alpha_home")
        alpha_a = ensemble.get("meta_alpha_away")
        rho = ensemble.get("rho", 0.0)
        lines.extend([
            "## Tuning Results",
            f"- Meta-learner alpha (home): {alpha_h}",
            f"- Meta-learner alpha (away): {alpha_a}",
            f"- Bivariate Poisson ρ: {rho:.3f}",
            "",
        ])

    # Biased model training stats
    lines.extend(["## Biased Model Training", "", "| Model | Training Rows | Features |", "|---|---|---|"])
    for name, res in biased.items():
        lines.append(f"| {name} | {res['n_train']} | {len(res['model'].feature_names_)} |")

    # Goals comparison
    lines.extend([
        "", "## Goals Prediction (Test Set)", "",
        "| Model | MAE | vs Naive |", "|---|---|---|",
        f"| Baseline | {baseline['test_goals']['mae']:.3f} | {baseline['test_goals']['mae_improvement']:.1%} |",
    ])
    if ensemble:
        lines.append(
            f"| **Ensemble** | **{ensemble['test_goals']['mae']:.3f}** "
            f"| **{ensemble['test_goals']['mae_improvement']:.1%}** |"
        )

    # RPS comparison — independent vs bivariate
    lines.extend([
        "", "## Match Outcome RPS (Test Set)", "",
        "| Model | RPS | Pinnacle | vs Pinnacle |", "|---|---|---|---|",
        f"| Baseline | {baseline['test_rps']['model_rps']:.4f} "
        f"| {baseline['test_rps']['pinnacle_rps']:.4f} "
        f"| {baseline['test_rps']['rps_improvement']:+.1%} |",
    ])
    if ensemble:
        indep = ensemble.get("test_rps_independent")
        if indep:
            lines.append(
                f"| Ensemble (independent) | {indep['model_rps']:.4f} "
                f"| {indep['pinnacle_rps']:.4f} "
                f"| {indep['rps_improvement']:+.1%} |"
            )
        rho = ensemble.get("rho", 0.0)
        lines.append(
            f"| **Ensemble (bivariate rho={rho:.2f})** | **{ensemble['test_rps']['model_rps']:.4f}** "
            f"| {ensemble['test_rps']['pinnacle_rps']:.4f} "
            f"| **{ensemble['test_rps']['rps_improvement']:+.1%}** |"
        )

    # Meta-learner coefficients
    if ensemble and "meta_coefs" in ensemble:
        lines.extend([
            "", "## Meta-Learner Coefficients", "",
            "| Model | Home coef | Away coef |", "|---|---|---|",
        ])
        for name, coefs in ensemble["meta_coefs"].items():
            lines.append(f"| {name} | {coefs['home_coef']:+.3f} | {coefs['away_coef']:+.3f} |")
        lines.append(
            f"| *intercept* | {ensemble['ridge_home'].intercept_:+.3f} "
            f"| {ensemble['ridge_away'].intercept_:+.3f} |"
        )

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Report saved to {path}")


def main() -> None:
    print("=" * 80)
    print("  Phase 2: Bias-Trained Ensemble — Turkish Super Lig")
    print("  (with Bivariate Poisson + RidgeCV meta-learner)")
    print("=" * 80)
    print()

    # Step 1: Load data
    print("Step 1: Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = add_line_movement(games)
    print(f"  Loaded {len(games)} matches")
    print(f"  Line movement data: {games['line_move_home'].notna().sum()} matches\n")

    # Step 2: Build features
    print("Step 2: Building features...")
    games = build_all_features(games)
    print()

    # Step 3: Team-level dataset
    print("Step 3: Building team-level dataset...")
    team_df = build_team_level_dataset(games)
    print(f"  {len(team_df)} team-match rows\n")

    # Step 4: Train ensemble (now with RidgeCV + bivariate Poisson)
    print("Step 4: Training ensemble...")
    config = make_default_ensemble_config()
    results = train_and_evaluate_ensemble(team_df, games, config)
    print()

    # Step 5: Results
    print_comparison(results)
    print_regime_analysis(results, team_df, games)

    # Step 6: Save report
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    save_report(results, KNOWLEDGE_DIR / "phase2_ensemble_report.md")

    print("\nDone!")


if __name__ == "__main__":
    main()
