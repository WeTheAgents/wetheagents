"""Debug a single CF game — show full cards, analyst, expert verdicts."""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import numpy as np
import pandas as pd

MODEL = "gpt-5.4"

# Pick a specific 2024 game
TARGET_DATE = "2024-09-21"
TARGET_AWAY = "PHI"
TARGET_HOME = "NYM"


def main():
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds
    from src.features import build_all_features
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    print("Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    # Find the game
    mask = (
        (enriched["date"] == TARGET_DATE)
        & (enriched["away_team"] == TARGET_AWAY)
        & (enriched["home_team"] == TARGET_HOME)
    )
    match = enriched[mask]
    if match.empty:
        print(f"Game not found: {TARGET_AWAY} @ {TARGET_HOME} on {TARGET_DATE}")
        return

    row = match.iloc[0]

    # ══════════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"  CF GAME DEBUG: {TARGET_AWAY} @ {TARGET_HOME} — {TARGET_DATE}")
    print(f"  Actual result: {'Home win' if row.get('home_win') else 'Away win'} "
          f"({int(row.get('away_final', 0))}-{int(row.get('home_final', 0))})")
    print(f"{'='*70}")

    # 1. Analyst Card
    analyst_card = AnalystCard.from_row(row)
    print(f"\n{'─'*70}")
    print("  [1] ANALYST CARD (no betting context)")
    print(f"{'─'*70}")
    print(analyst_card.to_prompt())

    # 2. CF Feature Card
    cf_card = FeatureCard.from_row(row, "CF_pickem")
    print(f"\n{'─'*70}")
    print("  [2] CF BETTING CARD (symmetric pick'em)")
    print(f"{'─'*70}")
    print(cf_card.to_prompt())

    # 3. Run through LLM pipeline
    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"
    genome_a = Genome.load(genomes_dir / "cf_structure_v1.yaml")
    genome_b = Genome.load(genomes_dir / "cf_advocate_v1.yaml")
    genome_analyst = Genome.load(genomes_dir / "analyst_v1.yaml")

    analyst = LLMAnalyst(genome_analyst, provider="openai", model=MODEL)
    expert_a = LLMExpert(genome_a, provider="openai", model=MODEL)
    expert_b = LLMExpert(genome_b, provider="openai", model=MODEL)

    # Analyst prediction
    print(f"\n{'─'*70}")
    print(f"  [3] ANALYST PREDICTION (model={MODEL})")
    print(f"{'─'*70}")
    scenario = analyst.predict(analyst_card)
    print(f"  Winner: {scenario.predicted_winner} (confidence: {scenario.winner_confidence:.0%})")
    print(f"  Tightness: {scenario.tightness}")
    print(f"  Predicted score: {scenario.predicted_score}")
    print(f"  Narrative: {scenario.key_narrative}")
    print(f"  Decisive factors:")
    for f in scenario.decisive_factors:
        print(f"    * {f}")

    # Inject scenario into card
    scenario_text = scenario.to_text()
    card_with_scenario = cf_card.with_scenario(scenario_text)

    # Expert A (CF-Structure) — proposes BET/PASS
    print(f"\n{'─'*70}")
    print(f"  [4] CF-STRUCTURE PROPOSAL")
    print(f"{'─'*70}")
    verdict_a = expert_a.analyze(card_with_scenario)
    print(f"  Action: {verdict_a.action}")
    print(f"  Confidence: {verdict_a.confidence:.2f}")
    print(f"  Key factors:")
    for f in verdict_a.key_factors:
        print(f"    + {f}")
    print(f"  Risk flags:")
    for f in verdict_a.risk_flags:
        print(f"    - {f}")
    print(f"  Reasoning: {verdict_a.reasoning}")

    # Expert B (CF-Advocate) — challenges if Structure bets
    print(f"\n{'─'*70}")
    print(f"  [5] CF-ADVOCATE CHALLENGE")
    print(f"{'─'*70}")
    if verdict_a.action.startswith("BET_"):
        challenge = expert_b.challenge_cf(card_with_scenario, verdict_a)
        print(f"  Action: {challenge.action}")
        print(f"  Severity: {challenge.severity}")
        print(f"  Challenge reasons:")
        for r in challenge.challenge_reasons:
            print(f"    ! {r}")
        print(f"  Concessions:")
        for c in challenge.concessions:
            print(f"    ~ {c}")
        print(f"  Reasoning: {challenge.reasoning}")
    else:
        print(f"  SKIPPED (Structure passed — no proposal to challenge)")

    # Duel result (uses propose-then-challenge internally)
    print(f"\n{'─'*70}")
    print(f"  [6] DUEL RESULT")
    print(f"{'─'*70}")
    duel = DuelEngine(expert_a, expert_b, analyst=analyst)
    result = duel.run(cf_card, analyst_card=analyst_card)
    print(f"  Final action: {result.final_action}")
    print(f"  Target side: {result.target_side}")
    print(f"  Combined confidence: {result.combined_confidence:.2f}")
    print(f"  Stake multiplier: {result.stake_multiplier}x")
    if result.challenge_verdict:
        print(f"  Advocate: {result.challenge_verdict.action} "
              f"(severity={result.challenge_verdict.severity})")

    # Outcome
    home_won = bool(row.get("home_win", False))
    if result.final_action != "PASS" and result.target_side:
        correct = (result.target_side == "home") == home_won
        print(f"\n  OUTCOME: {'WIN' if correct else 'LOSS'}")
    else:
        print(f"\n  OUTCOME: PASS (no bet)")

    print(f"{'='*70}")


if __name__ == "__main__":
    main()
