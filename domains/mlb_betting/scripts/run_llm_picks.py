"""Daily LLM expert picks from expansion zone.

Modes:
  default    — analyze today's (or --date) games from expansion zone
  --retro    — score yesterday's picks against actual outcomes
  --evolve   — run weekly retrospective on last 7 days of resolved picks

Usage:
    python scripts/run_llm_picks.py                     # today's games
    python scripts/run_llm_picks.py --date 2026-04-15   # specific date
    python scripts/run_llm_picks.py --retro             # score yesterday
    python scripts/run_llm_picks.py --evolve            # weekly evolution
    python scripts/run_llm_picks.py --dry-run           # show cards only
"""

import sys
import json
import warnings
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
PICKS_DIR = BASE_DIR / "picks"

ASG_CUTOFF_DAY = 15

# ── Expansion zone thresholds (same as calibration) ──────────────────────

S3_STRICT_EDGE = -0.05
S3_STRICT_RPI = 0.0
S3_STRICT_ELO = 30

RL_STRICT_EDGE = 0.10

S3_WIDE_EDGE = -0.02
S3_WIDE_RPI = 0.02
S3_WIDE_ELO = 40

RL_WIDE_EDGE = 0.05


def load_genome_latest(name: str):
    """Load the latest version of a genome by name prefix."""
    from src.llm_expert import Genome

    candidates = sorted(GENOMES_DIR.glob(f"{name}_v*.yaml"))
    if not candidates:
        raise FileNotFoundError(f"No genome found for {name} in {GENOMES_DIR}")
    path = candidates[-1]  # highest version
    return Genome.load(path)


def build_daily_data(target_date: str | None = None):
    """Build enriched DataFrame with model predictions.

    For production: would load from a pre-computed parquet.
    For now: full pipeline rebuild (slow but correct).
    """
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

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
    df["is_first_half"] = (df["month"] < 7) | (
        (df["month"] == 7) & (df["day"] <= ASG_CUTOFF_DAY)
    )

    if target_date:
        df = df[df["date"] == target_date]
        logger.info(f"Filtered to date {target_date}: {len(df)} games")

    return df


def get_expansion_zone(df):
    """Extract expansion zone games (wide minus strict)."""
    away_dog = df[df["fav_is_home"] == True].copy()
    away_dog["dog_won"] = away_dog["fav_margin"] < 0
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]
    away_dog["home_margin"] = away_dog.get("fav_margin", 0)

    # S3 expansion
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
    s3_exp = away_dog[s3_wide & ~s3_strict].copy()
    s3_exp["zone"] = "S3_expansion"

    # RL expansion
    rl_strict = (
        (away_dog["edge_consensus"] > RL_STRICT_EDGE)
        & away_dog["is_first_half"]
    )
    rl_wide = away_dog["edge_consensus"] > RL_WIDE_EDGE
    rl_exp = away_dog[rl_wide & ~rl_strict].copy()
    rl_exp["zone"] = "RL_expansion"

    expansion = pd.concat([s3_exp, rl_exp], ignore_index=True)
    return expansion


def run_daily_picks(df, *, dry_run=False):
    """Run analyst + duel on expansion zone games and save picks."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine
    from src.llm_evolution import save_picks

    expansion = get_expansion_zone(df)
    if expansion.empty:
        logger.info("No expansion zone games today.")
        return

    logger.info(f"\nExpansion zone: {len(expansion)} games")

    if dry_run:
        for _, row in expansion.iterrows():
            card = FeatureCard.from_row(row, row["zone"])
            print(f"\n{'=' * 70}")
            print(card.to_prompt())
            print(f"{'=' * 70}\n")
        return

    # Load S3 genomes (underdog ML)
    genome_s3_a = load_genome_latest("momentum")
    genome_s3_b = load_genome_latest("value")
    genome_analyst = load_genome_latest("analyst")

    # Load RL Away +1.5 genomes
    genome_rl_a = load_genome_latest("rl_tightgame")
    genome_rl_b = load_genome_latest("rl_away_value")

    analyst = LLMAnalyst(genome_analyst, provider="openai", model="gpt-4o-mini")

    # Separate S3 and RL zones
    s3_games = expansion[expansion["zone"] == "S3_expansion"]
    rl_games = expansion[expansion["zone"] == "RL_expansion"]

    # Build zone-specific duel engines
    s3_expert_a = LLMExpert(genome_s3_a, provider="openai", model="gpt-4o-mini")
    s3_expert_b = LLMExpert(genome_s3_b, provider="openai", model="gpt-4o-mini")
    s3_duel = DuelEngine(s3_expert_a, s3_expert_b, analyst=analyst)

    rl_expert_a = LLMExpert(genome_rl_a, provider="openai", model="gpt-4o-mini")
    rl_expert_b = LLMExpert(genome_rl_b, provider="openai", model="gpt-4o-mini")
    rl_duel = DuelEngine(rl_expert_a, rl_expert_b, analyst=analyst)

    picks = []

    # Run S3 zone with ML-focused experts
    for _, row in s3_games.iterrows():
        card = FeatureCard.from_row(row, row["zone"])
        analyst_card = AnalystCard.from_row(row)
        result = s3_duel.run(card, analyst_card=analyst_card)
        picks.append({
            **result.to_dict(),
            "dog_decimal": float(row.get("dog_decimal", 0)),
            "away_team": row.get("away_team", "?"),
            "home_team": row.get("home_team", "?"),
            "season": int(row.get("season", 0)),
        })

    # Run RL zone with Away +1.5 tight-game experts
    for _, row in rl_games.iterrows():
        card = FeatureCard.from_row(row, row["zone"])
        analyst_card = AnalystCard.from_row(row)
        result = rl_duel.run_rl(card, analyst_card=analyst_card)
        picks.append({
            **result.to_dict(),
            "dog_decimal": float(row.get("dog_decimal", 0)),
            "away_team": row.get("away_team", "?"),
            "home_team": row.get("home_team", "?"),
            "season": int(row.get("season", 0)),
        })

    # Print summary
    _print_daily_summary(picks)

    # Save picks
    dates = expansion["date"].unique()
    for d in dates:
        day_picks = [p for p in picks if d in p.get("game_id", "")]
        if day_picks:
            save_picks(day_picks, str(d), PICKS_DIR)


def run_retrospective(date: str):
    """Score a day's picks against actual outcomes."""
    from src.llm_evolution import load_picks

    picks = load_picks(date, PICKS_DIR)
    if not picks:
        logger.info(f"No picks found for {date}")
        return

    # Load actual results for that date
    df = build_daily_data(date)
    if df.empty:
        logger.info(f"No game data for {date}")
        return

    logger.info(f"\nRetrospective for {date}: {len(picks)} picks")

    for pick in picks:
        game_id = pick.get("game_id", "")
        action = pick.get("final_action", "PASS")
        bet_type = pick.get("final_bet_type", "")

        # Find matching game
        parts = game_id.split("_")
        if len(parts) >= 3:
            away = parts[1]
            home = parts[2]
            match = df[(df["away_team"] == away) & (df["home_team"] == home)]
            if not match.empty:
                row = match.iloc[0]
                dog_won = bool(row.get("fav_margin", 0) < 0)
                margin = int(row.get("fav_margin", 0))
                covered = margin <= 1

                if action == "PASS":
                    outcome = "SKIPPED"
                elif bet_type == "ML":
                    outcome = "WIN" if dog_won else "LOSS"
                else:
                    outcome = "WIN" if covered else "LOSS"

                pick["outcome"] = outcome
                pick["dog_won"] = dog_won
                pick["home_margin"] = margin

                emoji = "+" if outcome == "WIN" else "-" if outcome == "LOSS" else " "
                conf = pick.get("combined_confidence", 0)
                print(f"  [{emoji}] {game_id}: {action} {bet_type} "
                      f"(conf={conf:.2f}) → {outcome} (margin={margin:+d})")

    # Save updated picks with outcomes
    from src.llm_evolution import save_picks
    save_picks(picks, date, PICKS_DIR)


def run_evolution():
    """Run weekly retrospective and evolve genomes."""
    from src.llm_expert import Genome, Verdict
    from src.llm_evolution import EvolutionEngine, ResolvedPick, load_picks

    # Collect last 7 days of resolved picks
    today = datetime.now()
    all_picks_a = []
    all_picks_b = []

    for days_ago in range(1, 8):
        d = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        picks = load_picks(d, PICKS_DIR)
        for p in picks:
            if "outcome" not in p or p.get("final_action") == "PASS":
                continue

            for expert_key, expert_name, pick_list in [
                ("verdict_a", "Momentum", all_picks_a),
                ("verdict_b", "Value", all_picks_b),
            ]:
                v_data = p.get(expert_key, {})
                verdict = Verdict(
                    action=v_data.get("action", "PASS"),
                    confidence=v_data.get("confidence", 0),
                    key_factors=v_data.get("key_factors", []),
                    risk_flags=v_data.get("risk_flags", []),
                    reasoning=v_data.get("reasoning", ""),
                )
                pick_list.append(ResolvedPick(
                    game_id=p.get("game_id", ""),
                    date=d,
                    zone=p.get("zone", ""),
                    expert_name=expert_name,
                    verdict=verdict,
                    outcome=p["outcome"],
                    dog_won=p.get("dog_won", False),
                    dog_covered_rl=p.get("home_margin", 99) <= 1,
                    home_margin=p.get("home_margin", 0),
                    card_summary=p.get("game_id", ""),
                ))

    if not all_picks_a and not all_picks_b:
        logger.info("No resolved picks in last 7 days.")
        return

    engine = EvolutionEngine(provider="openai", model="gpt-4o-mini")

    # Evolve each genome
    for name, picks in [("momentum", all_picks_a), ("value", all_picks_b)]:
        if not picks:
            continue
        genome = load_genome_latest(name)
        logger.info(f"\nEvolving {genome.name} v{genome.version} "
                     f"({len(picks)} resolved picks)...")
        genome = engine.weekly_retrospective(picks, genome)

        # Save new version
        new_path = GENOMES_DIR / f"{name}_v{genome.version}.yaml"
        genome.save(new_path)

    # Crossbreed if both have picks
    if all_picks_a and all_picks_b:
        genome_a = load_genome_latest("momentum")
        genome_b = load_genome_latest("value")

        fit_a = sum(1 for p in all_picks_a if p.outcome == "WIN") / max(len(all_picks_a), 1)
        fit_b = sum(1 for p in all_picks_b if p.outcome == "WIN") / max(len(all_picks_b), 1)

        engine.monthly_crossbreed(genome_a, genome_b, fit_a, fit_b)

        # Save updated genomes after crossbreed
        for name, genome in [("momentum", genome_a), ("value", genome_b)]:
            path = GENOMES_DIR / f"{name}_v{genome.version}.yaml"
            genome.save(path)


def _print_daily_summary(picks):
    """Print formatted daily picks summary."""
    print(f"\n{'=' * 60}")
    print("DAILY PICKS SUMMARY")
    print(f"{'=' * 60}")

    bets = [p for p in picks if p["final_action"] != "PASS"]
    passes = [p for p in picks if p["final_action"] == "PASS"]

    for p in bets:
        game = p.get("game_id", "?")
        action = p["final_action"]
        bet_type = p["final_bet_type"]
        conf = p["combined_confidence"]
        stake = p["stake_multiplier"]
        print(f"  [{action}] {game}: {bet_type} "
              f"(confidence={conf:.2f}, stake={stake}x)")

        # Show analyst scenario
        scenario = p.get("scenario")
        if scenario:
            print(f"    Analyst: {scenario.get('predicted_winner', '?')} wins "
                  f"{scenario.get('predicted_score', '?')} "
                  f"({scenario.get('tightness', '?')})")

        # Show expert reasoning
        for key, name in [("verdict_a", "Momentum"), ("verdict_b", "Value")]:
            v = p.get(key, {})
            print(f"    {name}: {v.get('action', '?')} "
                  f"({v.get('confidence', 0):.2f}) -- {v.get('reasoning', '')[:80]}")

    if passes:
        print(f"\n  PASS: {len(passes)} game(s) skipped")

    print(f"\nTotal: {len(bets)} bets, {len(passes)} passes")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Daily LLM expert picks")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--retro", action="store_true",
                        help="Score yesterday's picks")
    parser.add_argument("--evolve", action="store_true",
                        help="Run weekly genome evolution")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show cards without API calls")
    args = parser.parse_args()

    if args.evolve:
        run_evolution()
    elif args.retro:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        date = args.date or yesterday
        run_retrospective(date)
    else:
        logger.info("Building data pipeline...")
        df = build_daily_data(args.date)
        run_daily_picks(df, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
