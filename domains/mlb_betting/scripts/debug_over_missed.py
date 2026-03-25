"""Debug missed OVER games: dump analyst scenarios with enriched card.

Targets: games where P(over) >= 0.52 AND actual result was OVER.
"""

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

TARGET_DATES = ["2024-04-06", "2024-04-23", "2024-06-28"]
P_OVER_MIN = 0.52


def main():
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import OU_FEATURES, build_all_features, build_ou_features
    from src.model import run_walk_forward_under
    from src.feature_card import OUFeatureCard, OUAnalystCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

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

    # Load genomes
    genome_analyst = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
    genome_offense = Genome.load(GENOMES_DIR / "ou_over_offense_v1.yaml")
    genome_fatigue = Genome.load(GENOMES_DIR / "ou_over_fatigue_v1.yaml")

    analyst = LLMAnalyst(genome_analyst, provider="openai", model="gpt-4o-mini")
    expert_a = LLMExpert(genome_offense, provider="openai", model="gpt-4o-mini")
    expert_b = LLMExpert(genome_fatigue, provider="openai", model="gpt-4o-mini")
    engine = DuelEngine(expert_a, expert_b, analyst=analyst)

    for date_str in TARGET_DATES:
        target_date = pd.Timestamp(date_str)
        day_df = full[full["date"] == target_date].copy()
        if len(day_df) == 0:
            continue

        # Filter: P(over) >= threshold AND actual OVER
        eligible = day_df[day_df["p_over"] >= P_OVER_MIN].copy()
        over_games = []
        for _, row in eligible.iterrows():
            total = row["home_final"] + row["away_final"]
            if total > row["close_ou"]:
                over_games.append(row)

        if not over_games:
            continue

        for row in over_games:
            p_over = 1 - row["p_under"]
            close_ou = row["close_ou"]
            total_runs = row["home_final"] + row["away_final"]
            away = row["away_team"]
            home = row["home_team"]

            print(f"\n{'='*80}")
            print(f"GAME: {away} @ {home} -- {date_str}")
            print(f"O/U Line: {close_ou:.1f} | P(over): {p_over:.4f}")
            print(f"Actual: {row['away_final']:.0f}-{row['home_final']:.0f} = {total_runs:.0f} runs (OVER +{total_runs - close_ou:.1f})")
            print(f"{'='*80}")

            # Key features
            print("\n--- KEY FEATURES ---")
            bp_osc = None
            for feat in ["bp_fip_osc_combined", "bullpen_ip_3d_combined", "sp_fip_combined",
                         "combined_rapg", "rpg_vs_line", "combined_rpg", "offense_vs_league_combined"]:
                if feat in full.columns:
                    val = row.get(feat)
                    if pd.notna(val):
                        print(f"  {feat}: {val:.4f}")
                        if feat == "bp_fip_osc_combined":
                            bp_osc = val

            # Analyst card (enriched with OVER summary)
            analyst_card = OUAnalystCard.from_row_over(row)
            print("\n--- ANALYST CARD (enriched) ---")
            print(analyst_card.to_prompt())

            # Run analyst
            print("\n--- ANALYST SCENARIO ---")
            scenario = analyst.predict_ou(analyst_card)
            print(f"Predicted total: {scenario.predicted_total}")
            print(f"Scoring pattern: {scenario.scoring_pattern}")
            print(f"Narrative: {scenario.key_narrative}")
            print(f"Factors: {scenario.decisive_factors}")

            # Build expert card with scenario
            betting_card = OUFeatureCard.from_row_over(row, p_over=p_over)
            expert_card = OUFeatureCard(
                game_id=betting_card.game_id,
                prompt_text=(
                    betting_card.prompt_text
                    + "\n\n-- Analyst Scoring Scenario --\n"
                    + scenario.to_text()
                ),
            )

            # Run experts
            print("\n--- OFFENSEFIRST VERDICT ---")
            verdict_a = expert_a.analyze_over(expert_card)
            print(f"Action: {verdict_a.action} | Confidence: {verdict_a.confidence}")
            print(f"Predicted total: {verdict_a.predicted_total}")
            print(f"Key factors: {verdict_a.key_factors}")
            print(f"Risk flags: {verdict_a.risk_flags}")
            print(f"Reasoning: {verdict_a.reasoning}")

            print("\n--- FATIGUEEXPLOIT VERDICT ---")
            verdict_b = expert_b.analyze_over(expert_card)
            print(f"Action: {verdict_b.action} | Confidence: {verdict_b.confidence}")
            print(f"Predicted total: {verdict_b.predicted_total}")
            print(f"Key factors: {verdict_b.key_factors}")
            print(f"Risk flags: {verdict_b.risk_flags}")
            print(f"Reasoning: {verdict_b.reasoning}")

            # Arbitrate
            from src.llm_duel import OUDuelResult
            result = engine._arbitrate_over(verdict_a, verdict_b, expert_card.game_id, scenario, close_ou)
            won = total_runs > close_ou
            pnl = (1.909 - 1) * 100 * result.stake_multiplier if won and result.stake_multiplier > 0 else -100 * result.stake_multiplier if result.stake_multiplier > 0 else 0

            print(f"\n--- FINAL ---")
            print(f"Arbiter: {result.final_action} ({result.stake_multiplier}x)")
            print(f"P&L: ${pnl:+.0f}")


if __name__ == "__main__":
    main()
