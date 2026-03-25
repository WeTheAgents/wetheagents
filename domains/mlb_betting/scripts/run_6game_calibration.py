"""Run LLM expert duel on 6 hand-picked games per batch.

Batches:
  1   — expansion zone games (S3/RL), 2024
  2   — expansion zone games (S3/RL), 2023-2024
  cf  — coinflip/pick'em games (CF), 2023-2024

Saves full verdicts (Analyst scenario + both experts + arbiter) to a markdown
report for manual review.

Usage:
    python scripts/run_6game_calibration.py              # full run with API calls
    python scripts/run_6game_calibration.py --dry-run    # show cards only, no API
    python scripts/run_6game_calibration.py --batch cf   # coinflip batch
"""

import sys
import json
import warnings
import logging
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
REPORT_PATH = BASE_DIR / "knowledge" / "calibration_6game_report.md"

# ── Hand-picked calibration games ──────────────────────────────────────

GAMES_BATCH1 = [
    # S3 track (Away ML)
    {"date": "2024-07-05", "away": "PHI", "home": "ATL", "zone": "S3_expansion",
     "label": "S3 WIN", "actual_margin": -2, "bet_result": "WIN"},
    {"date": "2024-05-11", "away": "MIN", "home": "TOR", "zone": "S3_expansion",
     "label": "S3 LOSS", "actual_margin": 2, "bet_result": "LOSS"},
    {"date": "2024-08-21", "away": "BAL", "home": "NYM", "zone": "S3_expansion",
     "label": "S3 TIGHT", "actual_margin": 1, "bet_result": "LOSS"},
    # RL track (Away +1.5)
    {"date": "2024-07-11", "away": "TOR", "home": "SFO", "zone": "RL_expansion",
     "label": "RL WIN", "actual_margin": -2, "bet_result": "WIN"},
    {"date": "2024-08-28", "away": "BAL", "home": "LAD", "zone": "RL_expansion",
     "label": "RL LOSS", "actual_margin": 2, "bet_result": "LOSS"},
    {"date": "2024-07-10", "away": "LAD", "home": "PHI", "zone": "RL_expansion",
     "label": "RL TIGHT", "actual_margin": 1, "bet_result": "WIN"},
]

GAMES_BATCH2 = [
    # S3 track (Away ML)
    {"date": "2024-06-09", "away": "HOU", "home": "LAA", "zone": "S3_expansion",
     "label": "S3 WIN", "actual_margin": -2, "bet_result": "WIN"},
    {"date": "2023-07-18", "away": "TAM", "home": "TEX", "zone": "S3_expansion",
     "label": "S3 LOSS", "actual_margin": 2, "bet_result": "LOSS"},
    {"date": "2024-06-24", "away": "TOR", "home": "BOS", "zone": "S3_expansion",
     "label": "S3 TIGHT", "actual_margin": 1, "bet_result": "LOSS"},
    # RL track (Away +1.5)
    {"date": "2023-06-27", "away": "HOU", "home": "STL", "zone": "RL_expansion",
     "label": "RL WIN", "actual_margin": -2, "bet_result": "WIN"},
    {"date": "2024-06-12", "away": "HOU", "home": "SFO", "zone": "RL_expansion",
     "label": "RL LOSS", "actual_margin": 2, "bet_result": "LOSS"},
    {"date": "2023-07-22", "away": "CWS", "home": "MIN", "zone": "RL_expansion",
     "label": "RL TIGHT", "actual_margin": 1, "bet_result": "WIN"},
]

GAMES_BATCH_CF = [
    # Coinflip / pick'em games (odds spread ≤ 4%, confirmed in enriched data)
    # Away wins
    {"date": "2023-08-29", "away": "NYY", "home": "DET", "zone": "CF_pickem",
     "label": "CF AWAY -2", "actual_winner": "away", "actual_margin": 2},
    {"date": "2024-08-03", "away": "STL", "home": "CUB", "zone": "CF_pickem",
     "label": "CF AWAY -1", "actual_winner": "away", "actual_margin": 1},
    {"date": "2024-07-04", "away": "HOU", "home": "TOR", "zone": "CF_pickem",
     "label": "CF AWAY -2", "actual_winner": "away", "actual_margin": 2},
    # Home wins
    {"date": "2024-05-03", "away": "SEA", "home": "HOU", "zone": "CF_pickem",
     "label": "CF HOME +2", "actual_winner": "home", "actual_margin": 2},
    {"date": "2024-05-12", "away": "ATL", "home": "NYM", "zone": "CF_pickem",
     "label": "CF HOME +1", "actual_winner": "home", "actual_margin": 1},
    {"date": "2024-07-06", "away": "MIL", "home": "LAD", "zone": "CF_pickem",
     "label": "CF HOME +2", "actual_winner": "home", "actual_margin": 2},
]

BATCHES = {"1": GAMES_BATCH1, "2": GAMES_BATCH2, "cf": GAMES_BATCH_CF}
GAMES = GAMES_BATCH1  # default


def build_enriched(seasons=None):
    """Build enriched DataFrame with model predictions for given seasons."""
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    if seasons is None:
        seasons = [2024]

    logger.info("Building spec features...")
    full = build_spec_features()

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()

    logger.info("Running walk-forward model...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    merge_keys = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep_cols = [c for c in full.columns if c not in div.columns or c in merge_keys]
    full_sub = full[keep_cols].drop_duplicates(subset=merge_keys)
    df = div.merge(full_sub, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (df["day"] <= 15))

    df_out = df[df["season"].isin(seasons)].copy()
    logger.info(f"Seasons {seasons}: {len(df_out)} games")
    return df_out


def extract_game_rows(df):
    """Extract the 6 specific game rows from the enriched DataFrame."""
    rows = []
    for g in GAMES:
        mask = (
            (df["date"] == g["date"])
            & (df["away_team"] == g["away"])
            & (df["home_team"] == g["home"])
        )
        matches = df[mask]
        if matches.empty:
            logger.warning(f"Game not found: {g['date']} {g['away']} @ {g['home']}")
            continue
        row = matches.iloc[0]
        rows.append((g, row))
        logger.info(f"Found: {g['label']} — {g['away']} @ {g['home']} {g['date']}")
    return rows


def run_calibration(game_rows, *, dry_run=False):
    """Run analyst + duel on each game. Returns list of result dicts."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    # Load genomes
    genome_a = Genome.load(GENOMES_DIR / "momentum_v1.yaml")
    genome_b = Genome.load(GENOMES_DIR / "value_v1.yaml")
    genome_analyst = Genome.load(GENOMES_DIR / "analyst_v1.yaml")

    results = []

    for g, row in game_rows:
        zone = g["zone"]
        card = FeatureCard.from_row(row, zone)
        analyst_card = AnalystCard.from_row(row)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Game: {g['label']} — {g['away']} @ {g['home']} {g['date']}")
        logger.info(f"{'=' * 60}")

        if dry_run:
            results.append({
                "game": g,
                "analyst_card": analyst_card.to_prompt(),
                "betting_card": card.to_prompt(),
                "duel_result": None,
                "scenario": None,
            })
            continue

        expert_a = LLMExpert(genome_a, provider="openai", model="gpt-5.4")
        expert_b = LLMExpert(genome_b, provider="openai", model="gpt-5.4")
        analyst = LLMAnalyst(genome_analyst, provider="openai", model="gpt-5.4")
        duel = DuelEngine(expert_a, expert_b, analyst=analyst)

        duel_result = duel.run(card, analyst_card=analyst_card)

        results.append({
            "game": g,
            "analyst_card": analyst_card.to_prompt(),
            "betting_card": card.to_prompt(),
            "scenario": duel_result.scenario,
            "duel_result": duel_result,
        })

    return results


def write_report(results, *, dry_run=False):
    """Write detailed markdown report."""
    lines = [
        "# LLM Expert Calibration — 6 Game Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Mode: {'DRY RUN (cards only)' if dry_run else 'FULL (API calls)'}",
        "",
        "---",
        "",
    ]

    is_cf = any(r["game"].get("zone", "").startswith("CF") for r in results)

    for r in results:
        g = r["game"]
        lines.append(f"## {g['label']}: {g['away']} @ {g['home']} — {g['date']}")
        lines.append("")
        if is_cf:
            lines.append(f"**Actual result:** {g['actual_winner']} wins "
                          f"by {g['actual_margin']}")
        else:
            lines.append(f"**Actual result:** fav margin = {g['actual_margin']:+d} → "
                          f"bet {g['bet_result']}")
        lines.append("")

        # Analyst card
        lines.append("### Analyst Card (what the Analyst sees)")
        lines.append("```")
        lines.append(r["analyst_card"])
        lines.append("```")
        lines.append("")

        # Betting card
        lines.append("### Betting Card (what Momentum + Value see)")
        lines.append("```")
        lines.append(r["betting_card"])
        lines.append("```")
        lines.append("")

        if dry_run:
            lines.append("*Dry run — no API calls made.*")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        dr = r["duel_result"]
        scenario = r["scenario"]

        # Analyst scenario
        lines.append("### Analyst Scenario")
        if scenario:
            lines.append(f"- **Predicted winner:** {scenario.predicted_winner} "
                          f"(confidence: {scenario.winner_confidence:.0%})")
            lines.append(f"- **Predicted score:** {scenario.predicted_score}")
            lines.append(f"- **Tightness:** {scenario.tightness}")
            lines.append(f"- **Narrative:** {scenario.key_narrative}")
            lines.append(f"- **Decisive factors:** {'; '.join(scenario.decisive_factors)}")
        lines.append("")

        # Expert verdicts
        for name, v in [("Momentum", dr.verdict_a), ("Value", dr.verdict_b)]:
            lines.append(f"### {name} Verdict")
            lines.append(f"- **Action:** {v.action}")
            lines.append(f"- **Confidence:** {v.confidence:.2f}")
            lines.append(f"- **Key factors:** {'; '.join(v.key_factors)}")
            lines.append(f"- **Risk flags:** {'; '.join(v.risk_flags)}")
            lines.append(f"- **Reasoning:** {v.reasoning}")
            lines.append("")

        # Arbiter result
        lines.append("### Arbiter Decision")
        lines.append(f"- **Final action:** {dr.final_action}")
        if is_cf:
            lines.append(f"- **Target side:** {dr.target_side or 'none'}")
        lines.append(f"- **Bet type:** {dr.final_bet_type}")
        lines.append(f"- **Combined confidence:** {dr.combined_confidence:.3f}")
        lines.append(f"- **Stake multiplier:** {dr.stake_multiplier}x")
        lines.append("")

        # Outcome assessment
        expert_action = dr.final_action
        if is_cf:
            actual_winner = g["actual_winner"]
            if expert_action == "PASS":
                assessment = "PASS (no bet placed)"
            elif dr.target_side == actual_winner:
                assessment = "CORRECT — picked the winner"
            else:
                assessment = "INCORRECT — picked the loser"
        else:
            actual = g["bet_result"]
            if expert_action == "PASS":
                assessment = "PASS (no bet placed)"
            elif actual == "WIN":
                assessment = "CORRECT — bet placed and won"
            else:
                assessment = "INCORRECT — bet placed and lost"

            if expert_action == "PASS" and actual == "WIN":
                assessment = "MISSED OPPORTUNITY — passed on a winner"
            elif expert_action == "PASS" and actual == "LOSS":
                assessment = "CORRECT PASS — avoided a loser"

        lines.append(f"### Outcome: {assessment}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Summary table
    if not dry_run:
        lines.append("## Summary")
        lines.append("")
        if is_cf:
            lines.append("| Game | Analyst | Momentum | Value | Arbiter (side) | Winner | Assessment |")
            lines.append("|------|---------|----------|-------|----------------|--------|------------|")
            for r in results:
                g = r["game"]
                dr = r["duel_result"]
                if dr is None:
                    continue
                scenario = r["scenario"]
                analyst_call = scenario.predicted_winner if scenario else "N/A"
                picked_right = (
                    dr.target_side == g["actual_winner"]
                    if dr.final_action != "PASS" else None
                )
                if dr.final_action == "PASS":
                    mark = "-"
                elif picked_right:
                    mark = "✓"
                else:
                    mark = "✗"
                lines.append(
                    f"| {g['away']}@{g['home']} | {analyst_call} | "
                    f"{dr.verdict_a.action} ({dr.verdict_a.confidence:.2f}) | "
                    f"{dr.verdict_b.action} ({dr.verdict_b.confidence:.2f}) | "
                    f"{dr.final_action} ({dr.target_side or '-'}) | "
                    f"{g['actual_winner']} | {mark} |"
                )
        else:
            lines.append("| Game | Zone | Analyst | Momentum | Value | Arbiter | Actual | Assessment |")
            lines.append("|------|------|---------|----------|-------|---------|--------|------------|")
            for r in results:
                g = r["game"]
                dr = r["duel_result"]
                if dr is None:
                    continue
                scenario = r["scenario"]
                analyst_call = scenario.predicted_winner if scenario else "N/A"
                lines.append(
                    f"| {g['away']}@{g['home']} | {g['zone'].split('_')[0]} | "
                    f"{analyst_call} | {dr.verdict_a.action} ({dr.verdict_a.confidence:.2f}) | "
                    f"{dr.verdict_b.action} ({dr.verdict_b.confidence:.2f}) | "
                    f"{dr.final_action} | {g['bet_result']} | "
                    f"{'✓' if (dr.final_action != 'PASS') == (g['bet_result'] == 'WIN') else '✗'} |"
                )
        lines.append("")

    report = "\n".join(lines)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    logger.info(f"\nReport saved: {REPORT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="6-game LLM calibration")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show cards without API calls")
    parser.add_argument("--batch", default="1", choices=sorted(BATCHES.keys()),
                        help="Which game batch to run: 1, 2, or cf (default: 1)")
    args = parser.parse_args()

    global GAMES, REPORT_PATH
    GAMES = BATCHES[args.batch]
    if args.batch != "1":
        REPORT_PATH = BASE_DIR / "knowledge" / f"calibration_6game_report_b{args.batch}.md"

    # Determine which seasons are needed
    seasons = sorted({int(g["date"][:4]) for g in GAMES})
    logger.info(f"Batch {args.batch}: building enriched data for seasons {seasons}...")
    df = build_enriched(seasons)

    logger.info("Extracting 6 game rows...")
    game_rows = extract_game_rows(df)

    if len(game_rows) != 6:
        logger.error(f"Expected 6 games, found {len(game_rows)}. Aborting.")
        return

    logger.info(f"Running calibration (dry_run={args.dry_run})...")
    results = run_calibration(game_rows, dry_run=args.dry_run)

    logger.info("Writing report...")
    write_report(results, dry_run=args.dry_run)

    logger.info("Done.")


if __name__ == "__main__":
    main()
