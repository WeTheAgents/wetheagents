"""Phase 1: Train CatBoost Poisson model and evaluate vs Pinnacle baseline.

Pipeline:
  1. Load Turkish Super Lig data (3 seasons)
  2. Build all features (SSS + form + congestion + context)
  3. Convert to team-level dataset (2 rows per match)
  4. Train CatBoost (Poisson loss) on 2021, validate on 2022, test on 2023
  5. Evaluate: goals MAE, Poisson LL, derived match RPS vs Pinnacle
  6. Print feature importance
  7. Save report

Usage:
    python scripts/run_model_training.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import MODEL_FEATURES, build_all_features, build_team_level_dataset
from src.model import ModelConfig, train_and_evaluate

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


def main() -> None:
    print("=" * 70)
    print("  Phase 1: CatBoost Poisson Goals Model — Turkish Super Lig")
    print("=" * 70)
    print()

    # Step 1: Load data
    print("Step 1: Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    print(f"  Loaded {len(games)} matches\n")

    # Step 2: Build features
    print("Step 2: Building features...")
    games = build_all_features(games)
    print()

    # Step 3: Team-level dataset
    print("Step 3: Building team-level dataset...")
    team_df = build_team_level_dataset(games)
    print(f"  {len(team_df)} team-match rows, {len(MODEL_FEATURES)} features\n")

    # Step 4-5: Train and evaluate
    print("Step 4: Training CatBoost Poisson model...")
    config = ModelConfig(
        train_seasons=list(range(2012, 2021)),  # 2012-2020 (9 seasons)
        val_seasons=[2021],
        test_seasons=[2022, 2023],
    )

    results = train_and_evaluate(team_df, MODEL_FEATURES, games, config)
    print()

    # Step 6: Results
    print("=" * 70)
    print("  RESULTS")
    print("=" * 70)

    print("\n--- Goals Prediction ---")
    for label, metrics in [("Validation", results["val_goals"]), ("Test", results["test_goals"])]:
        print(f"  {label}:")
        print(f"    MAE:        {metrics['mae']:.3f} (naive: {metrics['naive_mae']:.3f}, improvement: {metrics['mae_improvement']:.1%})")
        print(f"    Poisson LL: {metrics['poisson_ll']:.4f} (naive: {metrics['naive_poisson_ll']:.4f}, improvement: {metrics['ll_improvement']:+.4f})")
        print(f"    Mean pred:  {metrics['mean_predicted']:.3f} (actual: {metrics['mean_actual']:.3f})")

    print("\n--- Match Outcome (RPS vs Pinnacle) ---")
    for label, metrics in [("Validation", results["val_rps"]), ("Test", results["test_rps"])]:
        print(f"  {label} (N={metrics['n_matches']}):")
        print(f"    Model RPS:    {metrics['model_rps']:.4f}")
        print(f"    Pinnacle RPS: {metrics['pinnacle_rps']:.4f}")
        improvement = metrics['rps_improvement']
        status = "BETTER" if improvement > 0 else "WORSE"
        print(f"    Improvement:  {improvement:+.1%} [{status}]")

    print("\n--- Top 10 Features ---")
    for feat, imp in results["top_features"]:
        print(f"  {feat:30s} {imp:6.1f}")

    # Step 7: Save report
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    report_path = KNOWLEDGE_DIR / "phase1_model_report.md"

    lines = [
        "# Phase 1 — CatBoost Poisson Goals Model Report",
        "",
        "## Configuration",
        f"- Train: {config.train_seasons}, Val: {config.val_seasons}, Test: {config.test_seasons}",
        f"- Features: {len(MODEL_FEATURES)}",
        f"- CatBoost iterations: {config.catboost_params.get('iterations')}",
        "",
        "## Goals Prediction",
        "",
        "| Set | MAE | Naive MAE | Improvement | Poisson LL | Naive LL |",
        "|---|---|---|---|---|---|",
    ]
    for label, m in [("Val", results["val_goals"]), ("Test", results["test_goals"])]:
        lines.append(
            f"| {label} | {m['mae']:.3f} | {m['naive_mae']:.3f} | {m['mae_improvement']:.1%} "
            f"| {m['poisson_ll']:.4f} | {m['naive_poisson_ll']:.4f} |"
        )

    lines.extend([
        "",
        "## Match Outcome (RPS)",
        "",
        "| Set | Model RPS | Pinnacle RPS | Improvement |",
        "|---|---|---|---|",
    ])
    for label, m in [("Val", results["val_rps"]), ("Test", results["test_rps"])]:
        lines.append(
            f"| {label} | {m['model_rps']:.4f} | {m['pinnacle_rps']:.4f} | {m['rps_improvement']:+.1%} |"
        )

    lines.extend([
        "",
        "## Top Features",
        "",
        "| Feature | Importance |",
        "|---|---|",
    ])
    for feat, imp in results["top_features"]:
        lines.append(f"| {feat} | {imp:.1f} |")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report saved to {report_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
