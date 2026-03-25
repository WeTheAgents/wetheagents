"""O/U calibration: ML pre-filter P(u)>=0.60 → LLM expert ensemble → UNDER bets.

Pipeline:
1. Build enriched data + O/U features for target date
2. Run classifier → P(under) per game
3. Filter to P(u)>=0.60
4. For each: Analyst predicts scoring → 2 Experts evaluate → Consensus
5. Score P&L at -110 odds, produce markdown report

Usage:
    python scripts/run_ou_calibration.py --date 2024-06-12
    python scripts/run_ou_calibration.py --date 2024-06-12 --dry-run
    python scripts/run_ou_calibration.py --date 2024-06-12 --model gpt-4o-mini
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
P_UNDER_THRESHOLD = 0.60


# ── Data pipeline ─────────────────────────────────────────────────────────

def build_enriched_ou_day(date_str: str) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Build enriched O/U data for a single date.

    Returns:
        (day_df, full_ou_df, threshold) — day's games with P(under), full dataset,
        and the adaptive P(u) threshold (top 25%) from the covering fold.
    """
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import OU_FEATURES, build_all_features, build_ou_features
    from src.model import UnderModelConfig, run_walk_forward_under

    target_season = int(date_str[:4])

    # Step 1-2: Full enriched data → O/U features
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building all features...")
    enriched = build_all_features(games)

    logger.info("Building O/U features...")
    full = build_ou_features(enriched=enriched)

    # Step 3: Walk-forward binary classifier
    features_available = [
        f for f in OU_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    logger.info(f"O/U features available for classifier: {len(features_available)}")

    # Add regime column for compatibility with walk_forward_splits
    full["regime"] = full["ou_regime"]

    cfg = UnderModelConfig()
    logger.info("Running walk-forward UNDER classifier...")
    fold_results = run_walk_forward_under(full, features_available, cfg=cfg)

    # Find adaptive threshold from the fold covering this date
    threshold = P_UNDER_THRESHOLD  # fallback
    for fr in fold_results:
        if target_season in fr.test_seasons:
            threshold = fr.p_under_threshold
    logger.info(f"Adaptive threshold (top 25%%): P(u)>={threshold:.3f}")

    # Collect predictions from all folds
    preds = []
    for fr in fold_results:
        if fr.test_predictions is not None:
            preds.append(fr.test_predictions)
    pred_df = pd.concat(preds, ignore_index=True)

    # Merge P(under) back
    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_subset = pred_df[merge_keys + ["p_under"]].drop_duplicates(
        subset=merge_keys, keep="last"
    )

    full = full.merge(pred_subset, on=merge_keys, how="left")
    full = full.drop_duplicates(subset=merge_keys, keep="first")

    # Filter to target date
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()
    target_date = pd.Timestamp(date_str)
    day_df = full[full["date"] == target_date].copy()

    logger.info(f"Date {date_str}: {len(day_df)} games found")

    if "p_under" in day_df.columns:
        n_eligible = (day_df["p_under"] >= threshold).sum()
        logger.info(f"  P(u)>={threshold:.3f}: {n_eligible} games")
    else:
        logger.warning("  p_under column missing -- classifier may not cover this date")

    return day_df, full, threshold


# ── P&L scoring ───────────────────────────────────────────────────────────

def compute_ou_pnl(duel_result, row: pd.Series) -> dict:
    """Compute P&L for an O/U bet."""
    stake = duel_result.stake_multiplier
    if stake == 0:
        return {"pnl": 0.0, "won": None, "stake": 0.0, "bet_placed": False}

    total_runs = row["home_final"] + row["away_final"]
    close_ou = row["close_ou"]

    if total_runs == close_ou:
        # Push
        return {"pnl": 0.0, "won": None, "stake": stake, "bet_placed": True,
                "is_push": True}

    won = total_runs < close_ou  # UNDER hits
    pnl = (OU_DECIMAL_ODDS - 1) * BASE_UNIT * stake if won else -BASE_UNIT * stake

    return {
        "pnl": pnl,
        "won": won,
        "stake": stake,
        "bet_placed": True,
        "is_push": False,
    }


# ── Report generation ─────────────────────────────────────────────────────

def generate_report(
    date_str: str,
    day_df: pd.DataFrame,
    eligible_df: pd.DataFrame,
    results: list[dict],
    dry_run: bool = False,
    threshold: float = P_UNDER_THRESHOLD,
) -> str:
    """Generate markdown calibration report."""
    lines = [
        f"# O/U Calibration Report -- {date_str}",
        "",
        f"**Pre-filter**: P(under) >= {threshold:.1%} (adaptive top 25%)",
        f"**Odds**: -110 ({OU_DECIMAL_ODDS:.3f} decimal, {BREAKEVEN * 100:.1f}% breakeven)",
        f"**Base unit**: ${BASE_UNIT}",
        "",
        "## Date Overview",
        "",
        f"- Total games: {len(day_df)}",
        f"- P(u)>=0.60 games: {len(eligible_df)}",
    ]

    if "close_ou" in eligible_df.columns:
        ou_dist = eligible_df["close_ou"].describe()
        lines.append(f"- O/U line range: {ou_dist['min']:.1f} — {ou_dist['max']:.1f} "
                      f"(mean {ou_dist['mean']:.1f})")

    lines.append("")
    lines.append("## Per-Game Results")
    lines.append("")
    lines.append("| Game | O/U Line | P(u) | Analyst Total | Expert A | Expert B | "
                 "Arbiter | Actual | P&L |")
    lines.append("|------|----------|------|---------------|----------|----------|"
                 "---------|--------|-----|")

    total_pnl = 0.0
    bets_placed = 0
    wins = 0
    losses = 0
    passes = 0

    for r in results:
        row = r["row"]
        duel = r["duel_result"]
        pnl_info = r["pnl"]

        away = row.get("away_team", "?")
        home = row.get("home_team", "?")
        game_label = f"{away}@{home}"
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

        pnl_str = ""
        if pnl_info["bet_placed"]:
            bets_placed += 1
            total_pnl += pnl_info["pnl"]
            if pnl_info.get("is_push"):
                pnl_str = "PUSH"
            elif pnl_info["won"]:
                wins += 1
                pnl_str = f"+${pnl_info['pnl']:.0f}"
            else:
                losses += 1
                pnl_str = f"-${abs(pnl_info['pnl']):.0f}"
        else:
            passes += 1
            pnl_str = "—"

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
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Eligible games**: {len(eligible_df)}")
    lines.append(f"- **Bets placed**: {bets_placed}")
    lines.append(f"- **Expert PASS**: {passes}")
    lines.append(f"- **Record**: {wins}W-{losses}L")
    if bets_placed > 0:
        accuracy = wins / bets_placed * 100
        roi = total_pnl / (bets_placed * BASE_UNIT) * 100
        lines.append(f"- **Accuracy**: {accuracy:.0f}%")
        lines.append(f"- **Total P&L**: ${total_pnl:+.0f}")
        lines.append(f"- **ROI**: {roi:+.1f}%")
    lines.append("")

    # PASS pool analysis (games experts skipped)
    pass_games = [r for r in results if not r["pnl"]["bet_placed"]]
    if pass_games:
        under_in_pass = sum(
            1 for r in pass_games
            if r["row"]["home_final"] + r["row"]["away_final"] < r["row"]["close_ou"]
        )
        lines.append("## PASS Pool Analysis")
        lines.append("")
        lines.append(f"- Games passed: {len(pass_games)}")
        lines.append(f"- Would-be UNDER hits in PASS pool: {under_in_pass}/{len(pass_games)}")
        if len(pass_games) > 0:
            lines.append(f"- PASS pool under rate: {under_in_pass / len(pass_games) * 100:.0f}%")
        lines.append("")

    # Expert agreement
    agree = sum(1 for r in results if r["duel_result"].verdict_a.action == r["duel_result"].verdict_b.action)
    lines.append("## Expert Agreement")
    lines.append("")
    lines.append(f"- Same verdict: {agree}/{len(results)} ({agree / len(results) * 100:.0f}%)")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="O/U calibration with LLM experts")
    p.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    p.add_argument("--dry-run", action="store_true", help="Build data but skip LLM calls")
    p.add_argument("--model", default="gpt-4o-mini", help="LLM model for experts")
    p.add_argument("--provider", default="openai", help="LLM provider (openai/anthropic)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    date_str = args.date

    # Step 1: Build enriched data
    day_df, _, threshold = build_enriched_ou_day(date_str)

    if len(day_df) == 0:
        logger.error(f"No games found for {date_str}")
        return

    # Step 2: Filter to adaptive top-25% threshold
    if "p_under" not in day_df.columns:
        logger.error("p_under column not found -- classifier didn't produce predictions for this date")
        return

    eligible = day_df[day_df["p_under"] >= threshold].copy()
    logger.info(f"P(u)>={threshold:.3f} games: {len(eligible)}")

    if len(eligible) == 0:
        logger.warning(f"No games pass the P(u)>={threshold:.3f} filter on this date")
        return

    if args.dry_run:
        logger.info("=== DRY RUN — skipping LLM calls ===")
        for _, row in eligible.iterrows():
            away = row.get("away_team", "?")
            home = row.get("home_team", "?")
            ou = row.get("close_ou", 0)
            pu = row.get("p_under", 0)
            total = row.get("home_final", 0) + row.get("away_final", 0)
            hit = "U" if total < ou else "O" if total > ou else "P"
            logger.info(f"  {away}@{home}: O/U={ou:.1f} P(u)={pu:.0%} actual={total} ({hit})")
        return

    # Step 3: Load genomes and create experts
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

    # Step 4: Run duel for each eligible game
    results = []
    for idx, row in eligible.iterrows():
        p_under = row["p_under"]
        close_ou = row["close_ou"]

        # Build cards
        analyst_card = OUAnalystCard.from_row(row)
        betting_card = OUFeatureCard.from_row(row, p_under=p_under)

        # Run duel
        duel_result = engine.run_ou(betting_card, analyst_card=analyst_card, close_ou=close_ou)

        # Score P&L
        pnl_info = compute_ou_pnl(duel_result, row)

        results.append({
            "row": row,
            "duel_result": duel_result,
            "pnl": pnl_info,
        })

    # Step 5: Generate report
    report = generate_report(date_str, day_df, eligible, results, threshold=threshold)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"ou_calibration_{date_str}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info(f"Report saved: {report_path}")

    # Print summary to console
    bets = [r for r in results if r["pnl"]["bet_placed"]]
    total_pnl = sum(r["pnl"]["pnl"] for r in bets)
    wins = sum(1 for r in bets if r["pnl"].get("won"))
    logger.info(f"\n{'=' * 50}")
    logger.info(f"O/U CALIBRATION SUMMARY — {date_str}")
    logger.info(f"Eligible: {len(eligible)} | Bets: {len(bets)} | "
                f"Record: {wins}W-{len(bets) - wins}L | P&L: ${total_pnl:+.0f}")
    if bets:
        logger.info(f"ROI: {total_pnl / (len(bets) * BASE_UNIT) * 100:+.1f}%")
    logger.info(f"{'=' * 50}")


if __name__ == "__main__":
    main()
