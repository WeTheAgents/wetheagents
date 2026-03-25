"""Initial calibration for LLM expert genomes.

Selects ~50 representative games from the expansion zone (games that passed
wide filters but NOT strict filters), runs both experts, and scores results.

Usage:
    python scripts/run_llm_calibration.py
    python scripts/run_llm_calibration.py --dry-run   # show cards without API calls
"""

import sys
import warnings
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd

ASG_CUTOFF_DAY = 15  # July 15

# ── Expansion zone thresholds ────────────────────────────────────────────

# Strict thresholds (existing production strategies)
S3_STRICT_EDGE = -0.05
S3_STRICT_RPI = 0.0
S3_STRICT_ELO = 30

RL_STRICT_EDGE = 0.10

# Wide thresholds (expansion zone boundaries)
S3_WIDE_EDGE = -0.02
S3_WIDE_RPI = 0.02
S3_WIDE_ELO = 40

RL_WIDE_EDGE = 0.05


def build_enriched_with_model():
    """Build full enriched DataFrame with walk-forward model predictions."""
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    logger.info("Building spec features (this takes ~3 min)...")
    full = build_spec_features()
    logger.info(f"Games: {len(full)}")

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()

    logger.info("Running walk-forward model...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    # Merge model predictions back to full data
    merge_keys = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep_cols = [c for c in full.columns if c not in div.columns or c in merge_keys]
    full_sub = full[keep_cols].drop_duplicates(subset=merge_keys)
    df = div.merge(full_sub, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # Compute edge_consensus
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]

    # Half-season flag
    df["is_first_half"] = (df["month"] < 7) | (
        (df["month"] == 7) & (df["day"] <= ASG_CUTOFF_DAY)
    )

    return df


def identify_expansion_zones(df):
    """Identify S3 and RL expansion zone games.

    Returns: (s3_expansion, rl_expansion) DataFrames
    """
    # Away underdog universe: fav_is_home (away team is dog)
    away_dog = df[df["fav_is_home"] == True].copy()
    away_dog["dog_won"] = away_dog["fav_margin"] < 0
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]
    away_dog["home_margin"] = away_dog["fav_margin"]

    # S3 filters
    s3_strict = (
        (away_dog["edge_consensus"] < S3_STRICT_EDGE)
        & (away_dog["rpi_diff"] <= S3_STRICT_RPI)
        & (away_dog["elo_diff"] <= S3_STRICT_ELO)
    )
    s3_wide = (
        (away_dog["edge_consensus"] < S3_WIDE_EDGE)
        & (away_dog["rpi_diff"] <= S3_WIDE_RPI)
        & (away_dog["elo_diff"] <= S3_WIDE_ELO)
    )
    s3_expansion = away_dog[s3_wide & ~s3_strict].copy()
    s3_expansion["zone"] = "S3_expansion"

    # RL filters (need run line data)
    rl_strict = (
        (away_dog["edge_consensus"] > RL_STRICT_EDGE)
        & away_dog["is_first_half"]
    )
    rl_wide = away_dog["edge_consensus"] > RL_WIDE_EDGE
    rl_expansion = away_dog[rl_wide & ~rl_strict].copy()
    rl_expansion["zone"] = "RL_expansion"

    # Add RL cover info
    if "home_margin" in rl_expansion.columns:
        rl_expansion["dog_covered_rl"] = rl_expansion["home_margin"] <= 1

    logger.info(f"S3 expansion: {len(s3_expansion)} games")
    logger.info(f"RL expansion: {len(rl_expansion)} games")

    return s3_expansion, rl_expansion


def select_calibration_games(s3_exp, rl_exp, n_per_bucket=10):
    """Select ~50 representative games across outcomes and seasons.

    Buckets:
    - 15 S3 expansion wins (dog won ML)
    - 15 S3 expansion losses
    - 10 RL expansion covers (dog covered +1.5)
    - 10 RL expansion non-covers
    """
    selected = []

    # S3 wins — dog won outright
    s3_wins = s3_exp[s3_exp["dog_won"]].copy()
    if len(s3_wins) > 15:
        s3_wins = s3_wins.sample(15, random_state=42)
    selected.append(s3_wins)

    # S3 losses — dog lost
    s3_losses = s3_exp[~s3_exp["dog_won"]].copy()
    if len(s3_losses) > 15:
        s3_losses = s3_losses.sample(15, random_state=42)
    selected.append(s3_losses)

    # RL covers
    if "dog_covered_rl" in rl_exp.columns:
        rl_covers = rl_exp[rl_exp["dog_covered_rl"]].copy()
        if len(rl_covers) > 10:
            rl_covers = rl_covers.sample(10, random_state=42)
        selected.append(rl_covers)

        rl_non = rl_exp[~rl_exp["dog_covered_rl"]].copy()
        if len(rl_non) > 10:
            rl_non = rl_non.sample(10, random_state=42)
        selected.append(rl_non)
    else:
        # No RL cover data — use dog_won as proxy
        rl_wins = rl_exp[rl_exp["dog_won"]].copy()
        if len(rl_wins) > 10:
            rl_wins = rl_wins.sample(10, random_state=42)
        selected.append(rl_wins)

        rl_losses = rl_exp[~rl_exp["dog_won"]].copy()
        if len(rl_losses) > 10:
            rl_losses = rl_losses.sample(10, random_state=42)
        selected.append(rl_losses)

    combined = pd.concat(selected, ignore_index=True)
    logger.info(f"Calibration set: {len(combined)} games selected")
    return combined


def run_calibration(games_df, *, dry_run=False):
    """Run analyst + both experts on calibration games and score results."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    # Load genomes
    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"
    genome_a = Genome.load(genomes_dir / "momentum_v1.yaml")
    genome_b = Genome.load(genomes_dir / "value_v1.yaml")
    genome_analyst = Genome.load(genomes_dir / "analyst_v1.yaml")

    if dry_run:
        # Show both card types, no API calls
        logger.info("\n=== DRY RUN — showing feature cards ===\n")
        for _, row in games_df.head(3).iterrows():
            zone = row.get("zone", "S3_expansion")

            a_card = AnalystCard.from_row(row)
            print(f"\n{'=' * 70}")
            print("[ANALYST CARD — no betting context]")
            print(a_card.to_prompt())

            b_card = FeatureCard.from_row(row, zone)
            print(f"\n[BETTING CARD — with odds, edge, zone]")
            print(b_card.to_prompt())
            print(f"{'=' * 70}")
            print(f"Actual outcome: dog_won={row.get('dog_won', '?')}, "
                  f"margin={row.get('home_margin', '?')}")
        return

    expert_a = LLMExpert(genome_a, provider="openai", model="gpt-4o-mini")
    expert_b = LLMExpert(genome_b, provider="openai", model="gpt-4o-mini")
    analyst = LLMAnalyst(genome_analyst, provider="openai", model="gpt-4o-mini")
    duel = DuelEngine(expert_a, expert_b, analyst=analyst)

    results = []
    for i, (_, row) in enumerate(games_df.iterrows()):
        zone = row.get("zone", "S3_expansion")
        card = FeatureCard.from_row(row, zone)
        analyst_card = AnalystCard.from_row(row)

        logger.info(f"\n[{i + 1}/{len(games_df)}] {card.game_id}")
        duel_result = duel.run(card, analyst_card=analyst_card)

        # Determine actual outcome
        dog_won = bool(row.get("dog_won", False))
        home_margin = int(row.get("home_margin", 0))
        dog_covered_rl = home_margin <= 1

        # Score this pick
        if duel_result.final_action == "PASS":
            pick_correct = None  # didn't bet
        elif duel_result.final_bet_type == "ML":
            pick_correct = dog_won
        else:  # RL
            pick_correct = dog_covered_rl

        results.append({
            "game_id": card.game_id,
            "zone": zone,
            "final_action": duel_result.final_action,
            "final_type": duel_result.final_bet_type,
            "confidence": duel_result.combined_confidence,
            "stake": duel_result.stake_multiplier,
            "dog_won": dog_won,
            "dog_covered_rl": dog_covered_rl,
            "home_margin": home_margin,
            "pick_correct": pick_correct,
            "verdict_a": duel_result.verdict_a.action,
            "verdict_b": duel_result.verdict_b.action,
            "conf_a": duel_result.verdict_a.confidence,
            "conf_b": duel_result.verdict_b.confidence,
        })

    # Analyze results
    rdf = pd.DataFrame(results)
    _print_calibration_report(rdf)
    return rdf


def _print_calibration_report(rdf):
    """Print calibration results summary."""
    total = len(rdf)
    bets = rdf[rdf["final_action"] != "PASS"]
    passes = rdf[rdf["final_action"] == "PASS"]

    print(f"\n{'=' * 60}")
    print("CALIBRATION REPORT")
    print(f"{'=' * 60}")
    print(f"Total games: {total}")
    print(f"Bets placed: {len(bets)} ({len(bets) / total * 100:.0f}%)")
    print(f"Passed: {len(passes)} ({len(passes) / total * 100:.0f}%)")

    if len(bets) > 0:
        correct = bets["pick_correct"].sum()
        accuracy = correct / len(bets) * 100
        print(f"\nBet accuracy: {correct}/{len(bets)} ({accuracy:.1f}%)")

        # By action level
        for action in ["STRONG_BET", "BET", "LEAN"]:
            sub = bets[bets["final_action"] == action]
            if len(sub) > 0:
                acc = sub["pick_correct"].sum() / len(sub) * 100
                print(f"  {action}: {len(sub)} bets, {acc:.0f}% correct")

        # By zone
        for zone in rdf["zone"].unique():
            sub = bets[bets["zone"] == zone]
            if len(sub) > 0:
                acc = sub["pick_correct"].sum() / len(sub) * 100
                print(f"  {zone}: {len(sub)} bets, {acc:.0f}% correct")

    # Selectivity on wins/losses
    if len(bets) > 0 and len(passes) > 0:
        bet_wr = bets["dog_won"].mean()
        pass_wr = passes["dog_won"].mean()
        print(f"\nSelectivity: bet pool WR={bet_wr:.1%}, pass pool WR={pass_wr:.1%}")
        print(f"Lift: {bet_wr - pass_wr:+.1%}")

    # Expert agreement
    agree = (rdf["verdict_a"] == rdf["verdict_b"]).mean()
    print(f"\nExpert agreement: {agree:.0%}")

    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="LLM expert calibration")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show feature cards without API calls")
    args = parser.parse_args()

    logger.info("Building enriched data with model predictions...")
    df = build_enriched_with_model()

    logger.info("Identifying expansion zones...")
    s3_exp, rl_exp = identify_expansion_zones(df)

    logger.info("Selecting calibration games...")
    cal_games = select_calibration_games(s3_exp, rl_exp)

    logger.info("Running calibration...")
    run_calibration(cal_games, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
