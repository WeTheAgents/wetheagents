"""LLM Expert Backtest -- Turkish Super Lig.

Pipeline:
  1. Load data, build features, train ensemble (reuse existing pipeline)
  2. For each test match: build MatchCard -> Analyst -> build BettingCard -> Expert -> Verdict
  3. Simulate: only bet where Expert says BET
  4. Report: selection rate, hit rate, ROI, yield, per-market/regime breakdown

Usage:
    python scripts/run_llm_backtest.py                   # full backtest
    python scripts/run_llm_backtest.py --dry-run         # print cards, no API calls
    python scripts/run_llm_backtest.py --sample 20       # run on 20 random matches
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from tqdm import tqdm

from src.data_loader import add_derived_odds, add_line_movement, apply_data_filters, load_all_seasons
from src.ensemble import make_default_ensemble_config, predict_ensemble, train_and_evaluate_ensemble
from src.features import BIG_3, build_all_features, build_team_level_dataset
from src.markets import match_probabilities
from src.match_card import BettingCard, MatchCard

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
PICKS_DIR = Path(__file__).parent.parent / "picks"


def build_test_data() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load data, build features, train ensemble. Return test games + ensemble results."""
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = add_line_movement(games)
    games = build_all_features(games)
    team_df = build_team_level_dataset(games)

    config = make_default_ensemble_config()
    results = train_and_evaluate_ensemble(team_df, games, config)

    return games, team_df, results


def extract_match_predictions(
    games: pd.DataFrame,
    team_df: pd.DataFrame,
    results: dict,
) -> pd.DataFrame:
    """Extract per-match ensemble lambda predictions for test set.

    Returns test_games DataFrame with added columns:
      lambda_home, lambda_away
    """
    config = results["baseline"]["config"]
    test_seasons = config.test_seasons
    ensemble = results["ensemble"]

    test_games = games[games["season"].isin(test_seasons)].copy().reset_index(drop=True)
    test_df = team_df[team_df["season"].isin(test_seasons)].copy()

    is_home_test = test_df["is_home"].values
    test_home_mask = is_home_test == 1

    test_games["lambda_home"] = ensemble["test_lambda"][test_home_mask]
    test_games["lambda_away"] = ensemble["test_lambda"][~test_home_mask]

    return test_games


def run_dry_run(test_games: pd.DataFrame, rho: float) -> None:
    """Print sample cards without making API calls."""
    print("\n" + "=" * 80)
    print("  DRY RUN -- Sample Cards (no API calls)")
    print("=" * 80)

    sample = test_games.sample(min(3, len(test_games)), random_state=42)

    for _, row in sample.iterrows():
        # MatchCard
        card = MatchCard.from_row(row)
        print(f"\n{'-' * 60}")
        print(f"  MATCH CARD: {card.match_id}")
        print(f"{'-' * 60}")
        print(card.to_prompt())

        # Model probabilities
        probs = match_probabilities(row["lambda_home"], row["lambda_away"], rho)

        # BettingCard (without scenario -- dry run)
        bcard = BettingCard.from_row(row, probs, scenario_text="[Analyst scenario would go here]")
        print(f"\n{'-' * 60}")
        print(f"  BETTING CARD: {bcard.match_id}")
        print(f"{'-' * 60}")
        print(bcard.to_prompt())

        # Actual result
        print(f"\n  Actual: {row['home_team']} {int(row['home_goals'])}-{int(row['away_goals'])} {row['away_team']} ({row['result']})")


def run_backtest(
    test_games: pd.DataFrame,
    rho: float,
    sample_n: int | None = None,
) -> list[dict]:
    """Run full LLM backtest: Analyst -> Expert -> collect verdicts."""
    from src.llm_expert import Genome, LLMAnalyst, LLMBettingExpert

    # Load genomes
    genome_analyst = Genome.load_latest("analyst")
    genome_expert = Genome.load_latest("edge_hunter")

    analyst = LLMAnalyst(genome_analyst)
    expert = LLMBettingExpert(genome_expert)

    if sample_n:
        test_games = test_games.sample(min(sample_n, len(test_games)), random_state=42)
        test_games = test_games.reset_index(drop=True)

    picks = []
    total = len(test_games)

    for i, (_, row) in enumerate(tqdm(test_games.iterrows(), total=total, desc="LLM Backtest")):
        match_id = f"{row['date'].strftime('%Y-%m-%d')}_{row['home_team']}_{row['away_team']}"

        # Step 1: Analyst (neutral card)
        match_card = MatchCard.from_row(row)
        scenario = analyst.predict(match_card)

        # Step 2: Model probabilities
        probs = match_probabilities(row["lambda_home"], row["lambda_away"], rho)

        # Step 3: Betting Expert (full card + scenario)
        betting_card = BettingCard.from_row(row, probs, scenario.to_text())
        verdict = expert.analyze(betting_card)

        pick = {
            "match_id": match_id,
            "date": row["date"].strftime("%Y-%m-%d"),
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "home_goals": int(row["home_goals"]),
            "away_goals": int(row["away_goals"]),
            "result": row["result"],
            "lambda_home": float(row["lambda_home"]),
            "lambda_away": float(row["lambda_away"]),
            "home_odds": float(row["home_odds"]),
            "draw_odds": float(row["draw_odds"]),
            "away_odds": float(row["away_odds"]),
            "home_implied": float(row["home_implied"]),
            "draw_implied": float(row["draw_implied"]),
            "away_implied": float(row["away_implied"]),
            "model_home_win": probs["home_win"],
            "model_draw": probs["draw"],
            "model_away_win": probs["away_win"],
            "model_over_25": probs["over_2.5"],
            "scenario": scenario.to_dict(),
            "verdict": verdict.to_dict(),
            # Regime flags
            "is_big3": bool((row.get("is_big3_home", 0) == 1) or (row.get("is_big3_away", 0) == 1)),
            "sss_diff_abs": abs(float(row.get("sss_cum_diff", 0) or 0)),
            "min_days_rest": min(
                float(row.get("days_rest_home", 99) or 99),
                float(row.get("days_rest_away", 99) or 99),
            ),
        }
        picks.append(pick)

        # Rate limiting -- be gentle
        if (i + 1) % 50 == 0:
            time.sleep(1)

    return picks


def evaluate_picks(picks: list[dict]) -> None:
    """Evaluate backtest results: selection rate, hit rate, ROI, yield."""
    total = len(picks)
    bets = [p for p in picks if p["verdict"]["action"] == "BET"]
    n_bets = len(bets)

    print("\n" + "=" * 80)
    print("  LLM EXPERT BACKTEST RESULTS")
    print("=" * 80)

    print(f"\n  Total matches analyzed: {total}")
    print(f"  Bets placed: {n_bets} ({n_bets / total:.1%} selection rate)")

    if n_bets == 0:
        print("  No bets placed -- expert passed on all matches.")
        return

    # Simulate P&L
    total_staked = 0.0
    total_profit = 0.0
    wins = 0
    market_breakdown: dict[str, dict] = {}

    for bet in bets:
        v = bet["verdict"]
        market = v["market"]
        confidence = v["confidence"]

        # Stake = 1 unit (flat)
        stake = 1.0
        total_staked += stake

        # Determine if bet won
        won = _did_bet_win(bet, market)
        odds = _get_odds_for_market(bet, market)

        if won:
            profit = stake * (odds - 1)
            wins += 1
        else:
            profit = -stake

        total_profit += profit

        # Per-market breakdown
        if market not in market_breakdown:
            market_breakdown[market] = {"n": 0, "wins": 0, "profit": 0.0, "staked": 0.0}
        market_breakdown[market]["n"] += 1
        market_breakdown[market]["staked"] += stake
        market_breakdown[market]["profit"] += profit
        if won:
            market_breakdown[market]["wins"] += 1

    roi = total_profit / total_staked if total_staked > 0 else 0
    hit_rate = wins / n_bets if n_bets > 0 else 0
    yield_per_bet = total_profit / n_bets if n_bets > 0 else 0

    print(f"\n  --- Overall Results ---")
    print(f"  Hit rate:     {hit_rate:.1%} ({wins}/{n_bets})")
    print(f"  ROI:          {roi:+.1%}")
    print(f"  Yield/bet:    {yield_per_bet:+.3f} units")
    print(f"  Total P&L:    {total_profit:+.1f} units (on {total_staked:.0f} staked)")

    # Per-market breakdown
    print(f"\n  --- Per-Market Breakdown ---")
    print(f"  {'Market':10s} {'N':>5s} {'Wins':>5s} {'Hit%':>7s} {'ROI':>8s} {'P&L':>8s}")
    print(f"  {'-' * 10} {'-' * 5} {'-' * 5} {'-' * 7} {'-' * 8} {'-' * 8}")
    for market, stats in sorted(market_breakdown.items()):
        mhr = stats["wins"] / stats["n"] if stats["n"] > 0 else 0
        mroi = stats["profit"] / stats["staked"] if stats["staked"] > 0 else 0
        print(
            f"  {market:10s} {stats['n']:5d} {stats['wins']:5d} "
            f"{mhr:6.1%} {mroi:+7.1%} {stats['profit']:+7.1f}"
        )

    # Per-regime breakdown
    print(f"\n  --- Per-Regime Breakdown ---")
    regimes = {
        "Big-3": [p for p in bets if p["is_big3"]],
        "No Big-3": [p for p in bets if not p["is_big3"]],
        "SSS diff>0.15": [p for p in bets if p["sss_diff_abs"] > 0.15],
        "Short rest": [p for p in bets if p["min_days_rest"] <= 3],
    }
    print(f"  {'Regime':15s} {'N':>5s} {'Wins':>5s} {'Hit%':>7s} {'ROI':>8s}")
    print(f"  {'-' * 15} {'-' * 5} {'-' * 5} {'-' * 7} {'-' * 8}")
    for name, regime_bets in regimes.items():
        if not regime_bets:
            continue
        rn = len(regime_bets)
        rw = sum(1 for b in regime_bets if _did_bet_win(b, b["verdict"]["market"]))
        rhr = rw / rn if rn > 0 else 0
        rp = sum(
            (1.0 * (_get_odds_for_market(b, b["verdict"]["market"]) - 1) if _did_bet_win(b, b["verdict"]["market"]) else -1.0)
            for b in regime_bets
        )
        rroi = rp / rn if rn > 0 else 0
        print(f"  {name:15s} {rn:5d} {rw:5d} {rhr:6.1%} {rroi:+7.1%}")

    # Confidence calibration
    print(f"\n  --- Confidence Calibration ---")
    buckets = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)]
    print(f"  {'Bucket':12s} {'N':>5s} {'Hit%':>7s} {'ROI':>8s}")
    print(f"  {'-' * 12} {'-' * 5} {'-' * 7} {'-' * 8}")
    for lo, hi in buckets:
        bucket_bets = [b for b in bets if lo <= b["verdict"]["confidence"] < hi]
        if not bucket_bets:
            continue
        bn = len(bucket_bets)
        bw = sum(1 for b in bucket_bets if _did_bet_win(b, b["verdict"]["market"]))
        bhr = bw / bn if bn > 0 else 0
        bp = sum(
            (1.0 * (_get_odds_for_market(b, b["verdict"]["market"]) - 1) if _did_bet_win(b, b["verdict"]["market"]) else -1.0)
            for b in bucket_bets
        )
        broi = bp / bn if bn > 0 else 0
        print(f"  [{lo:.1f}-{hi:.1f})   {bn:5d} {bhr:6.1%} {broi:+7.1%}")


def _did_bet_win(pick: dict, market: str) -> bool:
    """Determine if a bet on the given market won."""
    result = pick["result"]
    hg = pick["home_goals"]
    ag = pick["away_goals"]
    total = hg + ag

    if market == "1X2_H":
        return result == "H"
    elif market == "1X2_D":
        return result == "D"
    elif market == "1X2_A":
        return result == "A"
    elif market == "O2.5":
        return total > 2.5
    elif market == "U2.5":
        return total < 2.5
    return False


def _get_odds_for_market(pick: dict, market: str) -> float:
    """Get decimal odds for the given market."""
    if market == "1X2_H":
        return pick["home_odds"]
    elif market == "1X2_D":
        return pick["draw_odds"]
    elif market == "1X2_A":
        return pick["away_odds"]
    elif market in ("O2.5", "U2.5"):
        # We don't have O/U odds in data. Use fair odds from implied probability.
        # This is approximate -- use 1/model_prob as proxy.
        if market == "O2.5":
            p = pick.get("model_over_25", 0.5)
        else:
            p = 1 - pick.get("model_over_25", 0.5)
        return 1 / max(p, 0.01)  # avoid div by zero
    return 2.0  # fallback


def save_picks(picks: list[dict], path: Path) -> None:
    """Save picks to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(picks, f, indent=2, default=str)
    logger.info(f"Saved {len(picks)} picks to {path}")


def main():
    parser = argparse.ArgumentParser(description="LLM Expert Backtest")
    parser.add_argument("--dry-run", action="store_true", help="Print cards, no API calls")
    parser.add_argument("--sample", type=int, help="Run on N random matches")
    args = parser.parse_args()

    print("=" * 80)
    print("  LLM Expert Backtest -- Turkish Super Lig")
    print("=" * 80)
    print()

    # Step 1: Build data + ensemble
    print("Step 1: Loading data + training ensemble...")
    games, team_df, results = build_test_data()
    print()

    # Step 2: Extract per-match predictions
    print("Step 2: Extracting per-match predictions...")
    rho = results["ensemble"]["rho"] if results["ensemble"] else 0.0
    test_games = extract_match_predictions(games, team_df, results)
    print(f"  Test matches: {len(test_games)}, rho={rho:.3f}")
    print()

    if args.dry_run:
        run_dry_run(test_games, rho)
        return

    # Step 3: Run LLM backtest
    print("Step 3: Running LLM backtest...")
    picks = run_backtest(test_games, rho, sample_n=args.sample)

    # Step 4: Evaluate
    evaluate_picks(picks)

    # Step 5: Save picks
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_sample{args.sample}" if args.sample else "_full"
    save_picks(picks, PICKS_DIR / f"llm_backtest{suffix}.json")

    print("\nDone!")


if __name__ == "__main__":
    main()
