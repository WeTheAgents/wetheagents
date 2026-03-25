"""Generate a detailed MD report for a single LLM Expert Duel.

Picks KCR vs ARI on 2024-07-23 (Zone A game, actual UNDER).
Outputs full analyst card, betting card, expert verdicts, and consensus.
"""

import sys
import logging
import warnings
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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
from src.data_loader import (
    load_all_seasons, enrich_innings_from_retrosheet,
    apply_data_filters, add_derived_odds,
)
from src.features import build_all_features, build_ou_features_v3, OU_FEATURES
from src.model import (
    walk_forward_splits, UnderModelConfig,
    train_under_model, predict_under_proba,
)
from src.feature_card import OUFeatureCard, OUAnalystCard
from src.llm_expert import Genome, LLMExpert, LLMAnalyst
from src.llm_duel import DuelEngine


def main():
    # Data pipeline
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    ou = build_ou_features_v3(enriched=enriched)

    seasons = sorted(ou["season"].unique().tolist())
    splits = walk_forward_splits(seasons)
    cfg = UnderModelConfig()

    removed = {"close_ou", "combined_rpg_last10", "combined_rapg",
               "combined_rapg_last10", "pyth_wp_combined"}
    v3_interactions = ["bp_fip_osc_x_rpg", "matchup_rpg_x_bp_fip",
                       "sp_quality_gap", "effective_obp_x_sp_fip"]
    feats = [f for f in OU_FEATURES
             if f not in removed and f in ou.columns and ou[f].notna().mean() > 0.3]
    feats += [f for f in v3_interactions
              if f in ou.columns and ou[f].notna().mean() > 0.3]

    # 2024 fold
    for fold_idx, (train_s, val_s, test_s) in enumerate(splits):
        if 2024 in test_s:
            cb, lr_model, calibrator, metrics = train_under_model(
                ou, feats, train_s, val_s, cfg=cfg)
            train_medians = metrics["train_medians"]
            push_mask = ou["is_push"] if "is_push" in ou.columns else pd.Series(False, index=ou.index)
            test_mask = ou["season"].isin([2024]) & ~push_mask
            X_test = ou.loc[test_mask, feats].values.astype(float)
            p = predict_under_proba(X_test, cb, lr_model, calibrator, train_medians, cfg=cfg)
            test_df = ou.loc[test_mask].copy()
            test_df["p_under"] = p
            test_df["month"] = pd.to_datetime(test_df["date"]).dt.month
            break

    # Pick KCR game from July Zone A
    zone_a = test_df[(test_df["p_under"] >= 0.51) & (test_df["p_under"] < 0.52)]
    zone_a_jul = zone_a[zone_a["month"] == 7]
    target = zone_a_jul[
        (zone_a_jul["home_team"] == "KCR") | (zone_a_jul["away_team"] == "KCR")
    ]
    game_ou = target.iloc[0]

    date_str = str(game_ou["date"])[:10]
    home = game_ou["home_team"]
    away = game_ou["away_team"]

    enriched_2024 = enriched[enriched["season"] == 2024].copy()
    match = enriched_2024[
        (enriched_2024["date"].astype(str).str[:10] == date_str)
        & (enriched_2024["home_team"] == home)
        & (enriched_2024["away_team"] == away)
    ]
    game_row = match.iloc[0]

    # Build cards
    analyst_card = OUAnalystCard.from_row(game_row)
    betting_card = OUFeatureCard.from_row(game_row, p_under=game_ou["p_under"])

    # Genomes
    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"
    ou_analyst_genome = Genome.load(genomes_dir / "ou_analyst_v1.yaml")
    ou_pitching_genome = Genome.load(genomes_dir / "ou_pitching_v1.yaml")
    ou_scoring_genome = Genome.load(genomes_dir / "ou_scoring_v1.yaml")

    analyst_obj = LLMAnalyst(ou_analyst_genome, model="gpt-4o-mini")
    expert_a = LLMExpert(ou_pitching_genome, model="gpt-4o-mini")
    expert_b = LLMExpert(ou_scoring_genome, model="gpt-4o-mini")
    under_engine = DuelEngine(expert_a, expert_b, analyst=analyst_obj)

    # Run individually
    logging.info("Running analyst...")
    scenario = analyst_obj.predict_ou(analyst_card)
    logging.info("Running expert A (PitchingFirst)...")
    verdict_a = expert_a.analyze_ou(betting_card)
    logging.info("Running expert B (RunEnvironment)...")
    verdict_b = expert_b.analyze_ou(betting_card)

    # Full duel for consensus
    duel_result = under_engine.run_ou(
        betting_card, analyst_card=analyst_card, close_ou=game_ou["close_ou"]
    )

    actual_total = int(game_ou["home_final"] + game_ou["away_final"])
    actual = "UNDER" if game_ou["under_hit"] else "OVER"
    would_bet = duel_result.final_action in ("UNDER", "LEAN_UNDER")
    is_correct = (would_bet and actual == "UNDER") or (not would_bet and actual == "OVER")

    # Build MD
    lines = []
    lines.append(f"# LLM Expert Duel Report: {home} vs {away} ({date_str})")
    lines.append("")
    lines.append("## Game Info")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Date | {date_str} |")
    lines.append(f"| Home | {home} |")
    lines.append(f"| Away | {away} |")
    lines.append(f"| O/U Line | {game_ou['close_ou']:.1f} |")
    lines.append(f"| P(under) | {game_ou['p_under']:.3f} |")
    lines.append(f"| **Actual Total** | **{actual_total}** |")
    lines.append(f"| **Actual Result** | **{actual}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Analyst Card (neutral, no betting context)")
    lines.append("")
    lines.append("```")
    lines.append(analyst_card.prompt_text)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Analyst Scenario")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Predicted Total | {scenario.predicted_total} |")
    lines.append(f"| Scoring Pattern | {scenario.scoring_pattern} |")
    lines.append(f"| Key Narrative | {scenario.key_narrative} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Betting Card (with P(under))")
    lines.append("")
    lines.append("```")
    lines.append(betting_card.prompt_text)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Expert A: PitchingFirst")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Action | **{verdict_a.action}** |")
    lines.append(f"| Confidence | {verdict_a.confidence:.2f} |")
    lines.append(f"| Predicted Total | {verdict_a.predicted_total} |")
    lines.append(f"| Key Factors | {'; '.join(verdict_a.key_factors)} |")
    lines.append(f"| Risk Flags | {'; '.join(verdict_a.risk_flags)} |")
    lines.append(f"| Reasoning | {verdict_a.reasoning} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Expert B: RunEnvironment")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Action | **{verdict_b.action}** |")
    lines.append(f"| Confidence | {verdict_b.confidence:.2f} |")
    lines.append(f"| Predicted Total | {verdict_b.predicted_total} |")
    lines.append(f"| Key Factors | {'; '.join(verdict_b.key_factors)} |")
    lines.append(f"| Risk Flags | {'; '.join(verdict_b.risk_flags)} |")
    lines.append(f"| Reasoning | {verdict_b.reasoning} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Consensus Decision")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Final Action | **{duel_result.final_action}** |")
    lines.append(f"| Combined Confidence | {duel_result.combined_confidence:.2f} |")
    lines.append(f"| Avg Predicted Total | {duel_result.predicted_total_avg:.1f} |")
    lines.append(f"| Stake Multiplier | {duel_result.stake_multiplier:.1f}x |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Outcome")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Would bet? | {'YES' if would_bet else 'NO (PASS)'} |")
    lines.append(f"| Actual result | {actual} (total={actual_total} vs line={game_ou['close_ou']:.1f}) |")
    lines.append(f"| Correct? | {'YES' if is_correct else 'NO'} |")
    lines.append("")

    md = "\n".join(lines)

    report_path = Path(__file__).resolve().parent.parent / "knowledge" / "llm_duel_report_KCR_ARI_20240723.md"
    report_path.write_text(md, encoding="utf-8")
    logging.info(f"Report written to {report_path}")
    print(md)


if __name__ == "__main__":
    main()
