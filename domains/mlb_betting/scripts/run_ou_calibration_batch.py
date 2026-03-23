"""Batch O/U calibration: run LLM expert ensemble on multiple dates and thresholds.

Loads data ONCE, then runs the LLM pipeline for each (date, threshold) pair.

Usage:
    python scripts/run_ou_calibration_batch.py
    python scripts/run_ou_calibration_batch.py --dry-run
    python scripts/run_ou_calibration_batch.py --model gpt-4o-mini
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

OU_DECIMAL_ODDS = 1.909  # -110 standard
BREAKEVEN = 1 / OU_DECIMAL_ODDS  # 52.38%
BASE_UNIT = 100

# Configuration
TARGET_DATES = ["2024-04-06", "2024-04-23", "2024-06-28"]
THRESHOLDS = [0.55, 0.52]


def load_data_once():
    """Load and process all data, run walk-forward. Returns (full_ou_df, pred_df)."""
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import OU_FEATURES, build_all_features, build_ou_features
    from src.model import UnderModelConfig, run_walk_forward_under

    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building all features...")
    enriched = build_all_features(games)

    logger.info("Building O/U features...")
    full = build_ou_features(enriched=enriched)

    features_available = [
        f for f in OU_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    logger.info(f"O/U features: {len(features_available)}")

    logger.info("Running walk-forward UNDER classifier...")
    fold_results = run_walk_forward_under(full, features_available)

    # Collect all predictions
    preds = []
    for fr in fold_results:
        if fr.test_predictions is not None:
            preds.append(fr.test_predictions)
    pred_df = pd.concat(preds, ignore_index=True)
    pred_df = pred_df.sort_values(["season", "date"]).drop_duplicates(
        subset=["date", "home_team", "away_team"], keep="last"
    )

    # Merge P(under) into full dataset
    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_subset = pred_df[merge_keys + ["p_under"]].drop_duplicates(
        subset=merge_keys, keep="last"
    )
    full = full.merge(pred_subset, on=merge_keys, how="left")
    full = full.drop_duplicates(subset=merge_keys, keep="first")
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()

    return full, pred_df


def compute_ou_pnl(duel_result, row: pd.Series) -> dict:
    """Compute P&L for an O/U bet."""
    stake = duel_result.stake_multiplier
    if stake == 0:
        return {"pnl": 0.0, "won": None, "stake": 0.0, "bet_placed": False}

    total_runs = row["home_final"] + row["away_final"]
    close_ou = row["close_ou"]

    if total_runs == close_ou:
        return {"pnl": 0.0, "won": None, "stake": stake, "bet_placed": True,
                "is_push": True}

    won = total_runs < close_ou
    pnl = (OU_DECIMAL_ODDS - 1) * BASE_UNIT * stake if won else -BASE_UNIT * stake

    return {"pnl": pnl, "won": won, "stake": stake, "bet_placed": True,
            "is_push": False}


def run_llm_for_games(eligible_df, engine, dry_run=False):
    """Run LLM duel for each eligible game. Returns list of result dicts."""
    from src.feature_card import OUFeatureCard, OUAnalystCard

    results = []
    for idx, row in eligible_df.iterrows():
        p_under = row["p_under"]
        close_ou = row["close_ou"]

        if dry_run:
            away = row.get("away_team", "?")
            home = row.get("home_team", "?")
            total = row.get("home_final", 0) + row.get("away_final", 0)
            hit = "U" if total < close_ou else "O" if total > close_ou else "P"
            logger.info(f"  [DRY] {away}@{home}: O/U={close_ou:.1f} P(u)={p_under:.0%} "
                        f"actual={total} ({hit})")
            continue

        analyst_card = OUAnalystCard.from_row(row)
        betting_card = OUFeatureCard.from_row(row, p_under=p_under)
        duel_result = engine.run_ou(betting_card, analyst_card=analyst_card, close_ou=close_ou)
        pnl_info = compute_ou_pnl(duel_result, row)

        results.append({
            "row": row,
            "duel_result": duel_result,
            "pnl": pnl_info,
        })

    return results


def generate_batch_report(all_runs: list[dict]) -> str:
    """Generate combined markdown report for all date/threshold combos."""
    lines = [
        "# O/U Batch Calibration Report",
        "",
        f"**Dates**: {', '.join(TARGET_DATES)}",
        f"**Thresholds**: {', '.join(f'P(u)>={t}' for t in THRESHOLDS)}",
        f"**Odds**: -110 ({OU_DECIMAL_ODDS:.3f} decimal, {BREAKEVEN * 100:.1f}% breakeven)",
        f"**Base unit**: ${BASE_UNIT}",
        "",
    ]

    # Per-run details
    for run in all_runs:
        date_str = run["date"]
        threshold = run["threshold"]
        results = run["results"]
        eligible = run["eligible"]

        lines.append(f"## {date_str} -- P(u)>={threshold}")
        lines.append("")
        lines.append(f"Eligible games: {len(eligible)}")
        lines.append("")

        if not results:
            lines.append("*No LLM results (dry-run or no eligible games)*")
            lines.append("")
            continue

        lines.append("| Game | O/U | P(u) | Analyst | Expert A | Expert B | "
                     "Arbiter | Actual | P&L |")
        lines.append("|------|-----|------|---------|----------|----------|"
                     "---------|--------|-----|")

        for r in results:
            row = r["row"]
            duel = r["duel_result"]
            pnl_info = r["pnl"]

            game_label = f"{row.get('away_team','?')}@{row.get('home_team','?')}"
            ou_line = row.get("close_ou", 0)
            p_under = row.get("p_under", 0)
            actual_total = row.get("home_final", 0) + row.get("away_final", 0)

            analyst_total = ""
            if duel.scenario:
                analyst_total = f"{duel.scenario.predicted_total:.1f}"

            expert_a = f"{duel.verdict_a.action} ({duel.verdict_a.confidence:.0%})"
            expert_b = f"{duel.verdict_b.action} ({duel.verdict_b.confidence:.0%})"

            action_str = duel.final_action
            if duel.stake_multiplier > 0:
                action_str += f" ({duel.stake_multiplier}x)"

            if pnl_info["bet_placed"]:
                if pnl_info.get("is_push"):
                    pnl_str = "PUSH"
                elif pnl_info["won"]:
                    pnl_str = f"+${pnl_info['pnl']:.0f}"
                else:
                    pnl_str = f"-${abs(pnl_info['pnl']):.0f}"
            else:
                pnl_str = "---"

            actual_label = f"{actual_total}"
            if actual_total < ou_line:
                actual_label += " (U)"
            elif actual_total > ou_line:
                actual_label += " (O)"
            else:
                actual_label += " (P)"

            lines.append(
                f"| {game_label} | {ou_line:.1f} | {p_under:.0%} | {analyst_total} | "
                f"{expert_a} | {expert_b} | {action_str} | {actual_label} | {pnl_str} |"
            )

        lines.append("")

        # Summary for this run
        bets = [r for r in results if r["pnl"]["bet_placed"]]
        passes = [r for r in results if not r["pnl"]["bet_placed"]]
        wins = sum(1 for r in bets if r["pnl"].get("won"))
        losses = sum(1 for r in bets if r["pnl"].get("won") is False)
        total_pnl = sum(r["pnl"]["pnl"] for r in bets)

        lines.append(f"**Bets**: {len(bets)} | **Passed**: {len(passes)} | "
                     f"**Record**: {wins}W-{losses}L | "
                     f"**P&L**: ${total_pnl:+.0f}")
        if bets:
            roi = total_pnl / (len(bets) * BASE_UNIT) * 100
            lines.append(f"**ROI**: {roi:+.1f}%")
        lines.append("")

    # Grand summary table
    lines.append("## Grand Summary")
    lines.append("")
    lines.append("| Threshold | Dates | Eligible | Bets | Record | P&L | ROI |")
    lines.append("|-----------|-------|----------|------|--------|-----|-----|")

    for threshold in THRESHOLDS:
        t_runs = [r for r in all_runs if r["threshold"] == threshold]
        total_eligible = sum(len(r["eligible"]) for r in t_runs)
        all_results = []
        for r in t_runs:
            all_results.extend(r["results"])
        bets = [r for r in all_results if r["pnl"]["bet_placed"]]
        wins = sum(1 for r in bets if r["pnl"].get("won"))
        losses = sum(1 for r in bets if r["pnl"].get("won") is False)
        total_pnl = sum(r["pnl"]["pnl"] for r in bets)
        roi_str = f"{total_pnl / (len(bets) * BASE_UNIT) * 100:+.1f}%" if bets else "N/A"

        lines.append(
            f"| P(u)>={threshold} | {len(t_runs)} | {total_eligible} | "
            f"{len(bets)} | {wins}W-{losses}L | ${total_pnl:+.0f} | {roi_str} |"
        )

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch O/U calibration with LLM experts")
    p.add_argument("--dry-run", action="store_true", help="Build data but skip LLM calls")
    p.add_argument("--model", default="gpt-4o-mini", help="LLM model for experts")
    p.add_argument("--provider", default="openai", help="LLM provider")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Load data ONCE
    full_df, pred_df = load_data_once()

    # Set up LLM engine (once)
    engine = None
    if not args.dry_run:
        from src.llm_expert import Genome, LLMAnalyst, LLMExpert
        from src.llm_duel import DuelEngine

        genome_analyst = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
        genome_pitching = Genome.load(GENOMES_DIR / "ou_pitching_v1.yaml")
        genome_scoring = Genome.load(GENOMES_DIR / "ou_scoring_v1.yaml")

        analyst = LLMAnalyst(genome_analyst, provider=args.provider, model=args.model)
        expert_a = LLMExpert(genome_pitching, provider=args.provider, model=args.model)
        expert_b = LLMExpert(genome_scoring, provider=args.provider, model=args.model)
        engine = DuelEngine(expert_a, expert_b, analyst=analyst)

    all_runs = []

    for date_str in TARGET_DATES:
        target_date = pd.Timestamp(date_str)
        day_df = full_df[full_df["date"] == target_date].copy()

        if len(day_df) == 0:
            logger.warning(f"No games for {date_str}")
            continue

        logger.info(f"\n{'='*60}")
        logger.info(f"DATE: {date_str} ({len(day_df)} games)")
        logger.info(f"{'='*60}")

        for threshold in THRESHOLDS:
            if "p_under" not in day_df.columns:
                logger.warning(f"  No p_under for {date_str}")
                continue

            eligible = day_df[day_df["p_under"] >= threshold].copy()
            logger.info(f"  P(u)>={threshold}: {len(eligible)} eligible games")

            if len(eligible) == 0:
                all_runs.append({
                    "date": date_str,
                    "threshold": threshold,
                    "eligible": eligible,
                    "results": [],
                })
                continue

            # Log eligible games
            for _, row in eligible.iterrows():
                away = row.get("away_team", "?")
                home = row.get("home_team", "?")
                ou = row.get("close_ou", 0)
                pu = row.get("p_under", 0)
                total = row.get("home_final", 0) + row.get("away_final", 0)
                hit = "U" if total < ou else "O" if total > ou else "P"
                logger.info(f"    {away}@{home}: O/U={ou:.1f} P(u)={pu:.2f} "
                            f"actual={total} ({hit})")

            results = run_llm_for_games(eligible, engine, dry_run=args.dry_run)

            all_runs.append({
                "date": date_str,
                "threshold": threshold,
                "eligible": eligible,
                "results": results,
            })

    # Generate report
    if not args.dry_run and all_runs:
        report = generate_batch_report(all_runs)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = RESULTS_DIR / "ou_batch_calibration_2024.md"
        report_path.write_text(report, encoding="utf-8")
        logger.info(f"\nReport saved: {report_path}")

    # Console summary
    logger.info(f"\n{'='*60}")
    logger.info("BATCH CALIBRATION SUMMARY")
    logger.info(f"{'='*60}")
    for threshold in THRESHOLDS:
        t_runs = [r for r in all_runs if r["threshold"] == threshold]
        total_eligible = sum(len(r["eligible"]) for r in t_runs)
        all_results = []
        for r in t_runs:
            all_results.extend(r["results"])
        bets = [r for r in all_results if r["pnl"]["bet_placed"]]
        wins = sum(1 for r in bets if r["pnl"].get("won"))
        losses = sum(1 for r in bets if r["pnl"].get("won") is False)
        total_pnl = sum(r["pnl"]["pnl"] for r in bets)
        roi_str = f"{total_pnl / (len(bets) * BASE_UNIT) * 100:+.1f}%" if bets else "N/A"
        logger.info(f"  P(u)>={threshold}: {total_eligible} eligible, "
                    f"{len(bets)} bets, {wins}W-{losses}L, "
                    f"P&L=${total_pnl:+.0f}, ROI={roi_str}")


if __name__ == "__main__":
    main()
