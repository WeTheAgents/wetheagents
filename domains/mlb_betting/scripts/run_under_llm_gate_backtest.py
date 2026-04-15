"""LLM Expert Gate Backtest for UNDER expansion zone [0.50-0.52).

Tests whether LLM expert consensus can profitably filter borderline bets
where the ML model has low confidence but potential signal.

Prerequisite: run_under_2021_2025_backtest.py confirms ROI > 0% at P>=0.52.

Usage:
    python scripts/run_under_llm_gate_backtest.py --dry-run     # cost estimate only
    python scripts/run_under_llm_gate_backtest.py               # run full backtest
    python scripts/run_under_llm_gate_backtest.py --resume       # resume from checkpoint
    python scripts/run_under_llm_gate_backtest.py --report-only  # analyze existing results
"""

import argparse
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

# Load .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.feature_card import OUAnalystCard, OUFeatureCard
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.llm_duel import DuelEngine
from src.llm_expert import Genome, LLMAnalyst, LLMExpert
from src.model import UnderModelConfig, walk_forward_splits, train_under_model, predict_under_proba

GENOMES_DIR = Path(__file__).resolve().parent.parent / "genomes"
CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "picks" / "_under_gate_checkpoint.json"
ODDS_UNDER = 1.909  # -110 decimal
BASE_UNIT = 100

# Expansion zones to test
EXPANSION_ZONES = [
    (0.520, 0.530, "Z_PRIMARY: [0.52-0.53)"),
    (0.510, 0.520, "Z_NEXT: [0.51-0.52)"),
    (0.500, 0.510, "Z_DEEP: [0.50-0.51)"),
    (0.500, 0.530, "Z_ALL: [0.50-0.53)"),
]
TARGET_SEASONS = [2021, 2022, 2023, 2024, 2025]
COST_PER_GAME = 0.003  # 3 LLM calls × ~$0.001 each (batch API)

# Default zone for --run mode
DEFAULT_ZONE_LO = 0.52
DEFAULT_ZONE_HI = 0.53


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {"results": [], "processed_keys": []}


def save_checkpoint(data: dict):
    CHECKPOINT_PATH.parent.mkdir(exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2, default=str))


def build_predictions():
    """Build walk-forward predictions with test_size=1 for 2021-2025."""
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building features...")
    enriched = build_all_features(games)
    ou = build_ou_features(enriched=enriched)
    ou = ou[ou["season"] <= 2025].copy()

    feats = [f for f in OU_FEATURES if f in ou.columns and ou[f].notna().mean() > 0.3]
    cfg = UnderModelConfig()

    logger.info(f"Running walk-forward (test_size=1) with {len(feats)} features...")
    seasons = sorted(ou["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=5, max_train=cfg.max_train_seasons,
                                test_size=1)

    all_preds = []
    push_mask = ou["is_push"] if "is_push" in ou.columns else pd.Series(False, index=ou.index)

    for i, (train_s, val_s, test_s) in enumerate(folds):
        fold_name = f"fold_{i}_{val_s[0]}_{test_s[0]}"
        logger.info(f"  {fold_name}: train={train_s[0]}-{train_s[-1]}, val={val_s}, test={test_s}")

        cb, lr_model, calibrator, metrics = train_under_model(ou, feats, train_s, val_s, cfg=cfg)
        train_medians = metrics["train_medians"]

        test_mask = ou["season"].isin(test_s) & ~push_mask
        n_test = int(test_mask.sum())
        if n_test < 10:
            continue

        X_test = ou.loc[test_mask, feats].values.astype(float)
        p_under = predict_under_proba(X_test, cb, lr_model, calibrator, train_medians, cfg=cfg)

        meta_cols = ["season", "date", "home_team", "away_team", "close_ou",
                     "total_runs", "under_hit"]
        preds_df = ou.loc[test_mask, meta_cols].copy()
        preds_df["p_under"] = p_under
        all_preds.append(preds_df)

    preds = pd.concat(all_preds, ignore_index=True)

    # Also build enriched lookup for feature cards
    enriched["date_str"] = pd.to_datetime(enriched["date"]).dt.strftime("%Y-%m-%d")
    enriched_lookup = enriched.set_index(["date_str", "home_team", "away_team"])

    return preds, enriched_lookup


def zone_analysis(preds):
    """Count games per expansion zone, estimate cost."""
    print("\n" + "=" * 80)
    print("EXPANSION ZONE SIZING & COST ESTIMATE")
    print("=" * 80)

    scope = preds[preds["season"].isin(TARGET_SEASONS)]
    print(f"\nTotal 2022-2025 predictions: {len(scope)}")

    print(f"\n  {'Zone':<25} {'Games':>6} {'Under%':>7} {'Est. Cost':>10}")
    print("  " + "-" * 55)

    for lo, hi, label in EXPANSION_ZONES:
        zone = scope[(scope["p_under"] >= lo) & (scope["p_under"] < hi)]
        n = len(zone)
        ur = zone["under_hit"].mean() * 100 if n > 0 else 0
        cost = n * COST_PER_GAME
        print(f"  {label:<25} {n:6d} {ur:6.1f}% ${cost:9.2f}")

    # Per-year breakdown for main zone [0.50-0.52)
    print("\n  Per-year: zone [0.50-0.52)")
    main_zone = scope[(scope["p_under"] >= 0.50) & (scope["p_under"] < 0.52)]
    for s in TARGET_SEASONS:
        sy = main_zone[main_zone["season"] == s]
        ur = sy["under_hit"].mean() * 100 if len(sy) > 0 else 0
        print(f"    {s}: {len(sy)} games, under_rate={ur:.1f}%")

    total_cost = len(main_zone) * COST_PER_GAME
    print(f"\n  TOTAL estimated cost for [0.50-0.52): ${total_cost:.2f}")
    return main_zone


def run_llm_backtest(scope, enriched_lookup, model, resume):
    """Run LLM expert duel on each game in scope."""
    analyst_genome = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
    pitching_genome = Genome.load(GENOMES_DIR / "ou_pitching_v1.yaml")
    scoring_genome = Genome.load(GENOMES_DIR / "ou_scoring_v1.yaml")

    engine = DuelEngine(
        LLMExpert(pitching_genome, model=model),
        LLMExpert(scoring_genome, model=model),
        analyst=LLMAnalyst(analyst_genome, model=model),
    )

    checkpoint = load_checkpoint() if resume else {"results": [], "processed_keys": []}
    processed = set(checkpoint["processed_keys"])
    results = checkpoint["results"]

    logger.info(f"Checkpoint: {len(processed)} done, {len(scope) - len(processed)} remaining")

    total = len(scope)
    errors = 0

    for i, (idx, game) in enumerate(scope.iterrows()):
        date_str = pd.to_datetime(game["date"]).strftime("%Y-%m-%d")
        home = game["home_team"]
        away = game["away_team"]
        game_key = f"{date_str}_{home}_{away}"

        if game_key in processed:
            continue

        try:
            game_row = enriched_lookup.loc[(date_str, home, away)]
            if isinstance(game_row, pd.DataFrame):
                game_row = game_row.iloc[0]
        except KeyError:
            logger.warning(f"  [{i+1}/{total}] {date_str} {away}@{home}: not in enriched")
            errors += 1
            continue

        try:
            analyst_card = OUAnalystCard.from_row(game_row)
            betting_card = OUFeatureCard.from_row(game_row, p_under=float(game["p_under"]))
            duel = engine.run_ou(betting_card, analyst_card=analyst_card,
                                 close_ou=float(game["close_ou"]))

            result = {
                "game_key": game_key,
                "date": date_str,
                "season": int(game["season"]),
                "home_team": home,
                "away_team": away,
                "ou_line": float(game["close_ou"]),
                "p_under": round(float(game["p_under"]), 4),
                "total_runs": int(game["total_runs"]),
                "under_hit": int(game["under_hit"]),
                "expert_a_action": duel.verdict_a.action if duel.verdict_a else None,
                "expert_a_conf": round(duel.verdict_a.confidence, 3) if duel.verdict_a else None,
                "expert_b_action": duel.verdict_b.action if duel.verdict_b else None,
                "expert_b_conf": round(duel.verdict_b.confidence, 3) if duel.verdict_b else None,
                "consensus": duel.final_action,
                "consensus_conf": round(duel.combined_confidence, 3),
                "scenario_total": round(duel.scenario.predicted_total, 1) if duel.scenario else None,
            }
            results.append(result)
            processed.add(game_key)

            done = len(processed)
            hit_str = "U" if game["under_hit"] else "O"
            logger.info(f"  [{done}/{total}] {date_str} {away}@{home} "
                         f"p={game['p_under']:.3f} act={hit_str} => {duel.final_action}")

            if done % 25 == 0:
                save_checkpoint({"results": results, "processed_keys": list(processed)})

        except Exception as e:
            logger.error(f"  [{i+1}/{total}] {date_str} {away}@{home}: {e}")
            errors += 1
            if errors > 20:
                logger.error("Too many errors, stopping")
                break

    save_checkpoint({"results": results, "processed_keys": list(processed)})
    logger.info(f"Complete: {len(results)} results, {errors} errors")
    return results


def generate_report(results):
    """Compare filtered vs unfiltered hit rates."""
    if not results:
        print("No results to report.")
        return

    df = pd.DataFrame(results)
    print("\n" + "=" * 80)
    print("LLM GATE BACKTEST RESULTS")
    print("=" * 80)

    print(f"\nTotal games evaluated: {len(df)}")
    print(f"Seasons: {sorted(df['season'].unique().tolist())}")

    # Overall split
    under_votes = df[df["consensus"] == "UNDER"]
    pass_votes = df[df["consensus"] != "UNDER"]

    print(f"\n  {'Category':<25} {'N':>5} {'Under%':>7} {'ROI':>8}")
    print("  " + "-" * 50)

    for label, subset in [("ALL (unfiltered)", df),
                           ("LLM → UNDER", under_votes),
                           ("LLM → PASS/OVER", pass_votes)]:
        n = len(subset)
        if n < 5:
            print(f"  {label:<25} {n:5d}   n/a     n/a")
            continue
        hr = subset["under_hit"].mean()
        pnl = np.where(subset["under_hit"].values, (ODDS_UNDER - 1) * BASE_UNIT, -BASE_UNIT)
        roi = pnl.sum() / (n * BASE_UNIT) * 100
        print(f"  {label:<25} {n:5d} {hr*100:6.1f}% {roi:+7.1f}%")

    # Per-zone analysis
    for lo, hi, label in EXPANSION_ZONES:
        zone = df[(df["p_under"] >= lo) & (df["p_under"] < hi)]
        if len(zone) < 5:
            continue
        under_z = zone[zone["consensus"] == "UNDER"]
        pass_z = zone[zone["consensus"] != "UNDER"]

        print(f"\n  {label}:")
        for sub_label, subset in [("  Unfiltered", zone),
                                   ("  LLM → UNDER", under_z),
                                   ("  LLM → PASS/OVER", pass_z)]:
            n = len(subset)
            if n < 3:
                continue
            hr = subset["under_hit"].mean()
            pnl = np.where(subset["under_hit"].values, (ODDS_UNDER - 1) * BASE_UNIT, -BASE_UNIT)
            roi = pnl.sum() / (n * BASE_UNIT) * 100
            filter_rate = len(under_z) / len(zone) * 100 if sub_label == "  LLM → UNDER" else 0
            extra = f" (filter: {filter_rate:.0f}%)" if sub_label == "  LLM → UNDER" else ""
            print(f"    {sub_label:<23} {n:5d} {hr*100:6.1f}% {roi:+7.1f}%{extra}")

    # Per-season
    print("\n  Per-season hit rate (LLM → UNDER):")
    for s in sorted(df["season"].unique()):
        sy = df[(df["season"] == s) & (df["consensus"] == "UNDER")]
        if len(sy) < 3:
            continue
        hr = sy["under_hit"].mean()
        print(f"    {s}: {len(sy)} bets, {hr*100:.1f}% hit")


def main():
    parser = argparse.ArgumentParser(description="UNDER LLM Gate Backtest")
    parser.add_argument("--dry-run", action="store_true", help="Zone sizing and cost estimate only")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--report-only", action="store_true", help="Analyze existing checkpoint")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model (default: gpt-4o-mini)")
    parser.add_argument("--zone-lo", type=float, default=DEFAULT_ZONE_LO, help="Zone lower bound")
    parser.add_argument("--zone-hi", type=float, default=DEFAULT_ZONE_HI, help="Zone upper bound")
    args = parser.parse_args()

    if args.report_only:
        checkpoint = load_checkpoint()
        generate_report(checkpoint["results"])
        return

    # Build predictions
    print("=" * 80)
    print(f"UNDER LLM GATE BACKTEST — Zone [{args.zone_lo:.2f}-{args.zone_hi:.2f})")
    print("=" * 80)

    preds, enriched_lookup = build_predictions()
    scope = zone_analysis(preds)

    if args.dry_run:
        print("\n--dry-run: stopping before LLM calls.")
        return

    # Run LLM backtest on selected zone
    scope_filtered = preds[
        (preds["season"].isin(TARGET_SEASONS))
        & (preds["p_under"] >= args.zone_lo)
        & (preds["p_under"] < args.zone_hi)
    ].copy()

    results = run_llm_backtest(scope_filtered, enriched_lookup,
                                model=args.model, resume=args.resume)
    generate_report(results)


if __name__ == "__main__":
    main()
