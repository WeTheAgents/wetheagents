"""Debug a single OVER game: dump full cards, analyst and expert prompts+responses."""

import sys
import warnings
import logging
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"

TARGET_DATE = "2024-04-23"
TARGET_AWAY = "CWS"
TARGET_HOME = "MIN"


def main():
    # --- Load data ---
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import OU_FEATURES, build_all_features, build_ou_features
    from src.model import run_walk_forward_under

    logger.info("Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    full = build_ou_features(enriched=enriched)

    features_available = [f for f in OU_FEATURES if f in full.columns and full[f].notna().mean() > 0.3]
    fold_results = run_walk_forward_under(full, features_available)

    preds = []
    for fr in fold_results:
        if fr.test_predictions is not None:
            preds.append(fr.test_predictions)
    pred_df = pd.concat(preds, ignore_index=True)
    pred_df = pred_df.sort_values(["season", "date"]).drop_duplicates(
        subset=["date", "home_team", "away_team"], keep="last"
    )

    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_subset = pred_df[merge_keys + ["p_under"]].drop_duplicates(subset=merge_keys, keep="last")
    full = full.merge(pred_subset, on=merge_keys, how="left")
    full = full.drop_duplicates(subset=merge_keys, keep="first")
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()
    full["p_over"] = 1 - full["p_under"]

    # --- Find the game ---
    target_date = pd.Timestamp(TARGET_DATE)
    game = full[(full["date"] == target_date) &
                (full["away_team"] == TARGET_AWAY) &
                (full["home_team"] == TARGET_HOME)]

    if len(game) == 0:
        logger.error(f"Game not found: {TARGET_AWAY}@{TARGET_HOME} on {TARGET_DATE}")
        return

    row = game.iloc[0]
    p_under = row["p_under"]
    p_over = 1 - p_under
    close_ou = row["close_ou"]
    total_runs = row["home_final"] + row["away_final"]

    print(f"\n{'='*80}")
    print(f"GAME: {TARGET_AWAY} @ {TARGET_HOME} — {TARGET_DATE}")
    print(f"O/U Line: {close_ou:.1f} | P(under): {p_under:.4f} | P(over): {p_over:.4f}")
    print(f"Actual: {row['away_final']:.0f}-{row['home_final']:.0f} = {total_runs:.0f} runs "
          f"({'OVER' if total_runs > close_ou else 'UNDER' if total_runs < close_ou else 'PUSH'})")
    print(f"{'='*80}")

    # --- Key feature values ---
    print(f"\n{'='*80}")
    print("KEY ML FEATURES")
    print(f"{'='*80}")
    for feat in OU_FEATURES:
        if feat in full.columns:
            val = row.get(feat)
            if pd.notna(val):
                print(f"  {feat}: {val:.4f}")

    # --- Build cards ---
    from src.feature_card import OUFeatureCard, OUAnalystCard

    analyst_card = OUAnalystCard.from_row(row)
    over_card = OUFeatureCard.from_row_over(row, p_over=p_over)

    print(f"\n{'='*80}")
    print("ANALYST CARD (what analyst sees)")
    print(f"{'='*80}")
    print(analyst_card.to_prompt())

    print(f"\n{'='*80}")
    print("OVER FEATURE CARD (what experts see, before analyst scenario)")
    print(f"{'='*80}")
    print(over_card.to_prompt())

    # --- Run analyst ---
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert

    genome_analyst = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
    genome_offense = Genome.load(GENOMES_DIR / "ou_over_offense_v1.yaml")
    genome_fatigue = Genome.load(GENOMES_DIR / "ou_over_fatigue_v1.yaml")

    analyst = LLMAnalyst(genome_analyst, provider="openai", model="gpt-4o-mini")

    print(f"\n{'='*80}")
    print("ANALYST SYSTEM PROMPT")
    print(f"{'='*80}")
    analyst_sys = analyst._build_system_prompt_ou()
    print(analyst_sys)

    print(f"\n{'='*80}")
    print("ANALYST RESPONSE")
    print(f"{'='*80}")
    scenario = analyst.predict_ou(analyst_card)
    print(f"Predicted total: {scenario.predicted_total}")
    print(f"Scoring pattern: {scenario.scoring_pattern}")
    print(f"Narrative: {scenario.key_narrative}")
    print(f"Key factors: {scenario.decisive_factors}")

    # Inject scenario into expert card
    expert_card = OUFeatureCard(
        game_id=over_card.game_id,
        prompt_text=(
            over_card.prompt_text
            + "\n\n── Analyst Scoring Scenario ──\n"
            + scenario.to_text()
        ),
    )

    print(f"\n{'='*80}")
    print("EXPERT CARD (with analyst scenario injected)")
    print(f"{'='*80}")
    print(expert_card.to_prompt())

    # --- Run experts ---
    expert_a = LLMExpert(genome_offense, provider="openai", model="gpt-4o-mini")
    expert_b = LLMExpert(genome_fatigue, provider="openai", model="gpt-4o-mini")

    print(f"\n{'='*80}")
    print("OFFENSEFIRST SYSTEM PROMPT")
    print(f"{'='*80}")
    print(expert_a._build_system_prompt_over())

    print(f"\n{'='*80}")
    print("OFFENSEFIRST VERDICT")
    print(f"{'='*80}")
    verdict_a = expert_a.analyze_over(expert_card)
    print(f"Action: {verdict_a.action}")
    print(f"Confidence: {verdict_a.confidence}")
    print(f"Predicted total: {verdict_a.predicted_total}")
    print(f"Key factors: {verdict_a.key_factors}")
    print(f"Risk flags: {verdict_a.risk_flags}")
    print(f"Reasoning: {verdict_a.reasoning}")

    print(f"\n{'='*80}")
    print("FATIGUEEXPLOIT SYSTEM PROMPT")
    print(f"{'='*80}")
    print(expert_b._build_system_prompt_over())

    print(f"\n{'='*80}")
    print("FATIGUEEXPLOIT VERDICT")
    print(f"{'='*80}")
    verdict_b = expert_b.analyze_over(expert_card)
    print(f"Action: {verdict_b.action}")
    print(f"Confidence: {verdict_b.confidence}")
    print(f"Predicted total: {verdict_b.predicted_total}")
    print(f"Key factors: {verdict_b.key_factors}")
    print(f"Risk flags: {verdict_b.risk_flags}")
    print(f"Reasoning: {verdict_b.reasoning}")


if __name__ == "__main__":
    main()
