"""O/U calibration for a specific P(u) band — test LLM filtering on noisy games.

Runs LLM expert ensemble only on games in [p_low, p_high) range.

Usage:
    python scripts/run_ou_calibration_band.py --p-low 0.50 --p-high 0.52
"""

import sys
import warnings
import logging
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
RESULTS_DIR = BASE_DIR / "knowledge" / "fullday_tests"

OU_DECIMAL_ODDS = 1.909
BASE_UNIT = 100

TARGET_DATES = ["2024-04-06", "2024-04-23", "2024-06-28"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--p-low", type=float, default=0.50)
    p.add_argument("--p-high", type=float, default=0.52)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--provider", default="openai")
    args = p.parse_args()

    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import OU_FEATURES, build_all_features, build_ou_features
    from src.model import run_walk_forward_under

    logger.info("Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    full = build_ou_features(enriched=enriched)

    logger.info("Running walk-forward...")
    features_available = [
        f for f in OU_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    fold_results = run_walk_forward_under(full, features_available)

    # Merge predictions
    preds = []
    for fr in fold_results:
        if fr.test_predictions is not None:
            preds.append(fr.test_predictions)
    pred_df = pd.concat(preds, ignore_index=True)
    pred_df = pred_df.sort_values(["season", "date"]).drop_duplicates(
        subset=["date", "home_team", "away_team"], keep="last"
    )

    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_subset = pred_df[merge_keys + ["p_under"]].drop_duplicates(
        subset=merge_keys, keep="last"
    )
    full = full.merge(pred_subset, on=merge_keys, how="left")
    full = full.drop_duplicates(subset=merge_keys, keep="first")
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()

    # Set up LLM engine
    engine = None
    if not args.dry_run:
        from src.llm_expert import Genome, LLMAnalyst, LLMExpert
        from src.llm_duel import DuelEngine
        from src.feature_card import OUFeatureCard, OUAnalystCard

        genome_analyst = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
        genome_pitching = Genome.load(GENOMES_DIR / "ou_pitching_v1.yaml")
        genome_scoring = Genome.load(GENOMES_DIR / "ou_scoring_v1.yaml")

        analyst = LLMAnalyst(genome_analyst, provider=args.provider, model=args.model)
        expert_a = LLMExpert(genome_pitching, provider=args.provider, model=args.model)
        expert_b = LLMExpert(genome_scoring, provider=args.provider, model=args.model)
        engine = DuelEngine(expert_a, expert_b, analyst=analyst)

    all_results = []

    for date_str in TARGET_DATES:
        target_date = pd.Timestamp(date_str)
        day_df = full[full["date"] == target_date].copy()

        if len(day_df) == 0:
            continue

        band = day_df[
            (day_df["p_under"] >= args.p_low) & (day_df["p_under"] < args.p_high)
        ].copy()

        if len(band) == 0:
            logger.info(f"{date_str}: no games in [{args.p_low}, {args.p_high})")
            continue

        logger.info(f"\n{'='*60}")
        logger.info(f"{date_str}: {len(band)} games in [{args.p_low}, {args.p_high})")
        logger.info(f"{'='*60}")

        for _, row in band.iterrows():
            away = row.get("away_team", "?")
            home = row.get("home_team", "?")
            ou = row["close_ou"]
            pu = row["p_under"]
            total = row["home_final"] + row["away_final"]
            hit = "U" if total < ou else "O" if total > ou else "P"

            logger.info(f"  {away}@{home}: O/U={ou:.1f} P(u)={pu:.4f} actual={total:.0f} ({hit})")

            if args.dry_run or engine is None:
                continue

            from src.feature_card import OUFeatureCard, OUAnalystCard

            analyst_card = OUAnalystCard.from_row(row)
            betting_card = OUFeatureCard.from_row(row, p_under=pu)
            duel_result = engine.run_ou(betting_card, analyst_card=analyst_card, close_ou=ou)

            # P&L
            stake = duel_result.stake_multiplier
            if stake == 0:
                pnl_info = {"pnl": 0.0, "won": None, "bet_placed": False}
            elif total == ou:
                pnl_info = {"pnl": 0.0, "won": None, "bet_placed": True, "is_push": True}
            else:
                won = total < ou
                pnl = (OU_DECIMAL_ODDS - 1) * BASE_UNIT * stake if won else -BASE_UNIT * stake
                pnl_info = {"pnl": pnl, "won": won, "bet_placed": True, "is_push": False}

            action_str = duel_result.final_action
            if stake > 0:
                action_str += f" ({stake}x)"

            analyst_total = ""
            if duel_result.scenario:
                analyst_total = f"{duel_result.scenario.predicted_total:.1f}"

            ea = f"{duel_result.verdict_a.action}({duel_result.verdict_a.confidence:.0%})"
            eb = f"{duel_result.verdict_b.action}({duel_result.verdict_b.confidence:.0%})"

            pnl_str = "PASS"
            if pnl_info["bet_placed"]:
                if pnl_info.get("is_push"):
                    pnl_str = "PUSH"
                elif pnl_info["won"]:
                    pnl_str = f"+${pnl_info['pnl']:.0f}"
                else:
                    pnl_str = f"-${abs(pnl_info['pnl']):.0f}"

            logger.info(f"    -> Analyst={analyst_total} | {ea} | {eb} | {action_str} | {pnl_str}")

            all_results.append({
                "date": date_str,
                "game": f"{away}@{home}",
                "ou": ou,
                "p_under": pu,
                "actual": total,
                "under_hit": total < ou,
                "analyst_total": analyst_total,
                "expert_a": ea,
                "expert_b": eb,
                "action": action_str,
                "bet_placed": pnl_info["bet_placed"],
                "won": pnl_info.get("won"),
                "pnl": pnl_info["pnl"],
            })

    if not all_results:
        logger.info("No results to summarize")
        return

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"BAND [{args.p_low}, {args.p_high}) SUMMARY")
    logger.info(f"{'='*60}")

    bets = [r for r in all_results if r["bet_placed"]]
    passes = [r for r in all_results if not r["bet_placed"]]
    wins = sum(1 for r in bets if r["won"])
    losses = sum(1 for r in bets if r["won"] is False)
    total_pnl = sum(r["pnl"] for r in bets)

    logger.info(f"Total games: {len(all_results)}")
    logger.info(f"Ground truth: {sum(1 for r in all_results if r['under_hit'])}U-"
                f"{sum(1 for r in all_results if not r['under_hit'])}O")
    logger.info(f"LLM bets: {len(bets)} | LLM pass: {len(passes)}")
    logger.info(f"Record: {wins}W-{losses}L | P&L: ${total_pnl:+.0f}")
    if bets:
        roi = total_pnl / (len(bets) * BASE_UNIT) * 100
        logger.info(f"ROI: {roi:+.1f}%")

    # Did LLM correctly pass on OVER games?
    over_games = [r for r in all_results if not r["under_hit"]]
    over_passed = [r for r in over_games if not r["bet_placed"]]
    logger.info(f"\nOVER games: {len(over_games)} | Correctly passed: {len(over_passed)}")

    under_games = [r for r in all_results if r["under_hit"]]
    under_bet = [r for r in under_games if r["bet_placed"]]
    logger.info(f"UNDER games: {len(under_games)} | Bet placed: {len(under_bet)}")


if __name__ == "__main__":
    main()
