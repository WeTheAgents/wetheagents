"""LLM Expert Backtest -- UNDER Expansion Zone (0.51-0.55).

Tests whether LLM experts can profitably filter borderline UNDER bets
in the expansion zone where the ML model is uncertain.

Scope: May-Sep 2023/2024/2025, P(under) in [0.51, 0.55).
Model: gpt-5.4 (configurable via --model).

Features checkpoint/resume for long-running backtests (~2,200 games).

Usage:
    python scripts/run_under_expansion_backtest.py
    python scripts/run_under_expansion_backtest.py --resume
    python scripts/run_under_expansion_backtest.py --report-only
    python scripts/run_under_expansion_backtest.py --report-only --min-p 0.52 --months 6,7,8
"""

import argparse
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
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
    add_derived_odds,
    apply_data_filters,
    enrich_innings_from_retrosheet,
    load_all_seasons,
)
from src.feature_card import OUAnalystCard, OUFeatureCard
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.llm_duel import DuelEngine
from src.llm_expert import Genome, LLMAnalyst, LLMExpert
from src.model import UnderModelConfig, run_walk_forward_under

GENOMES_DIR = Path(__file__).resolve().parent.parent / "genomes"
CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "picks" / "_under_expansion_checkpoint.json"
ODDS_UNDER = 1.909  # -110 decimal

# Scope
TARGET_SEASONS = [2023, 2024, 2025]
TARGET_MONTHS = [5, 6, 7, 8, 9]
P_UNDER_MIN = 0.51
P_UNDER_MAX = 0.55


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {"results": [], "processed_keys": []}


def save_checkpoint(data: dict):
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2, default=str))


def build_data():
    """Load data, run walk-forward, merge predictions with enriched rows."""
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building features...")
    enriched = build_all_features(games)
    ou = build_ou_features(enriched=enriched)

    feats = [f for f in OU_FEATURES if f in ou.columns and ou[f].notna().mean() > 0.3]
    logger.info(f"Running walk-forward with {len(feats)} features...")
    fold_results = run_walk_forward_under(ou, feats)

    # Collect all test predictions
    all_preds = pd.concat(
        [r.test_predictions for r in fold_results if r.test_predictions is not None],
        ignore_index=True,
    )
    if "is_push" in all_preds.columns:
        all_preds = all_preds[all_preds["is_push"] == False].copy()  # noqa: E712

    all_preds["month"] = pd.to_datetime(all_preds["date"]).dt.month

    # Filter to scope
    scope = all_preds[
        (all_preds["season"].isin(TARGET_SEASONS))
        & (all_preds["month"].isin(TARGET_MONTHS))
        & (all_preds["p_under"] >= P_UNDER_MIN)
        & (all_preds["p_under"] < P_UNDER_MAX)
    ].copy()

    logger.info(f"Scope: {len(scope)} games in expansion zone")

    # Merge enriched rows for feature card building
    enriched["date_str"] = pd.to_datetime(enriched["date"]).dt.strftime("%Y-%m-%d")
    scope["date_str"] = pd.to_datetime(scope["date"]).dt.strftime("%Y-%m-%d")

    # Build a lookup from enriched
    enriched_lookup = enriched.set_index(["date_str", "home_team", "away_team"])

    return scope, enriched_lookup


def run_backtest(scope: pd.DataFrame, enriched_lookup, model: str, resume: bool):
    """Run LLM duel on each game in scope with checkpoint/resume."""
    # Load genomes
    analyst_genome = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
    pitching_genome = Genome.load(GENOMES_DIR / "ou_pitching_v1.yaml")
    scoring_genome = Genome.load(GENOMES_DIR / "ou_scoring_v1.yaml")

    engine = DuelEngine(
        LLMExpert(pitching_genome, model=model),
        LLMExpert(scoring_genome, model=model),
        analyst=LLMAnalyst(analyst_genome, model=model),
    )

    # Load checkpoint
    checkpoint = load_checkpoint() if resume else {"results": [], "processed_keys": []}
    processed = set(checkpoint["processed_keys"])
    results = checkpoint["results"]

    logger.info(f"Checkpoint: {len(processed)} already processed, {len(scope) - len(processed)} remaining")

    total = len(scope)
    errors = 0

    for i, (idx, game) in enumerate(scope.iterrows()):
        date_str = pd.to_datetime(game["date"]).strftime("%Y-%m-%d")
        home = game["home_team"]
        away = game["away_team"]
        game_key = f"{date_str}_{home}_{away}"

        if game_key in processed:
            continue

        p_u = game["p_under"]
        ou_line = game["close_ou"]
        total_runs = game["total_runs"]
        under_hit = int(game["under_hit"])

        # Find enriched row
        try:
            game_row = enriched_lookup.loc[(date_str, home, away)]
            if isinstance(game_row, pd.DataFrame):
                game_row = game_row.iloc[0]
        except KeyError:
            logger.warning(f"  [{i+1}/{total}] {date_str} {away}@{home}: not found in enriched, skipping")
            errors += 1
            continue

        # Run duel
        try:
            analyst_card = OUAnalystCard.from_row(game_row)
            betting_card = OUFeatureCard.from_row(game_row, p_under=p_u)
            duel = engine.run_ou(betting_card, analyst_card=analyst_card, close_ou=float(ou_line))

            result = {
                "game_key": game_key,
                "date": date_str,
                "season": int(game["season"]),
                "month": int(game["month"]),
                "home_team": home,
                "away_team": away,
                "ou_line": float(ou_line),
                "p_under": round(float(p_u), 4),
                "total_runs": int(total_runs),
                "under_hit": under_hit,
                "expert_a_action": duel.verdict_a.action if duel.verdict_a else None,
                "expert_a_conf": round(duel.verdict_a.confidence, 3) if duel.verdict_a else None,
                "expert_b_action": duel.verdict_b.action if duel.verdict_b else None,
                "expert_b_conf": round(duel.verdict_b.confidence, 3) if duel.verdict_b else None,
                "consensus": duel.final_action,
                "consensus_conf": round(duel.combined_confidence, 3),
                "stake_mult": duel.stake_multiplier,
                "scenario_total": round(duel.scenario.predicted_total, 1) if duel.scenario else None,
            }
            results.append(result)
            processed.add(game_key)

            done = len(processed)
            action_short = duel.final_action[:5]
            hit_str = "U" if under_hit else "O"
            logger.info(
                f"  [{done}/{total}] {date_str} {away}@{home} "
                f"p={p_u:.3f} ou={ou_line:.1f} act={hit_str} => {action_short}"
            )

            # Save checkpoint every 25 games
            if done % 25 == 0:
                save_checkpoint({"results": results, "processed_keys": list(processed)})
                logger.info(f"  Checkpoint saved ({done} games)")

        except Exception as e:
            logger.error(f"  [{i+1}/{total}] {date_str} {away}@{home}: {e}")
            errors += 1
            if errors > 20:
                logger.error("Too many errors, stopping")
                break

    # Final save
    save_checkpoint({"results": results, "processed_keys": list(processed)})
    logger.info(f"Backtest complete: {len(results)} results, {errors} errors")
    return results


def generate_report(results: list, min_p: float = 0.51, max_p: float = 0.55,
                    months: list | None = None, seasons: list | None = None):
    """Generate filterable report from results."""
    if not results:
        print("No results to report.")
        return

    df = pd.DataFrame(results)

    # Apply filters
    mask = pd.Series(True, index=df.index)
    if min_p > 0.51:
        mask &= df["p_under"] >= min_p
    if max_p < 0.55:
        mask &= df["p_under"] < max_p
    if months:
        mask &= df["month"].isin(months)
    if seasons:
        mask &= df["season"].isin(seasons)

    filtered = df[mask].copy()
    n_total = len(filtered)

    filter_desc = f"p=[{min_p:.2f}, {max_p:.2f})"
    if months:
        mnames = {5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}
        filter_desc += f" months={[mnames.get(m,m) for m in months]}"
    if seasons:
        filter_desc += f" seasons={seasons}"

    print()
    print("=" * 110)
    print(f"UNDER EXPANSION ZONE LLM BACKTEST -- {filter_desc}")
    print(f"Total games: {n_total} (filtered from {len(df)})")
    print("=" * 110)

    if n_total == 0:
        print("  No games match filters.")
        return

    # Baseline: bet all games without LLM filter
    baseline_hits = filtered["under_hit"].sum()
    baseline_hit_rate = baseline_hits / n_total
    baseline_profit = baseline_hits * (ODDS_UNDER - 1) - (n_total - baseline_hits)
    baseline_roi = baseline_profit / n_total

    print(f"\n  BASELINE (bet all {n_total}): hit={baseline_hit_rate:.1%}, "
          f"ROI={baseline_roi:.1%}, P/L=${baseline_profit:+.0f}")

    # LLM-filtered: bet only UNDER/LEAN_UNDER
    bet_mask = filtered["consensus"].isin(["UNDER", "LEAN_UNDER"])
    bets = filtered[bet_mask]
    n_bets = len(bets)
    passes = filtered[~bet_mask]
    n_pass = len(passes)

    print(f"  LLM FILTER: {n_bets} bets ({n_bets/n_total:.0%} selectivity), {n_pass} passes")

    if n_bets > 0:
        bet_hits = bets["under_hit"].sum()
        bet_hit_rate = bet_hits / n_bets
        # PnL with stake multiplier
        bet_profit = sum(
            r["stake_mult"] * (ODDS_UNDER - 1) if r["under_hit"] else -r["stake_mult"]
            for _, r in bets.iterrows()
        )
        bet_roi = bet_profit / bets["stake_mult"].sum()
        print(f"  BET POOL:  {n_bets} bets, hit={bet_hit_rate:.1%}, "
              f"ROI={bet_roi:.1%}, P/L=${bet_profit*100:+.0f}")
    else:
        print("  BET POOL: 0 bets (all PASS)")

    if n_pass > 0:
        pass_hits = passes["under_hit"].sum()
        pass_hit_rate = pass_hits / n_pass
        print(f"  PASS POOL: {n_pass} games, under_hit={pass_hit_rate:.1%} "
              f"({'good filtering' if pass_hit_rate < 0.50 else 'WEAK filtering'})")

    # Expert agreement
    agree = (filtered["expert_a_action"] == filtered["expert_b_action"]).sum()
    print(f"  Expert agreement: {agree}/{n_total} ({agree/n_total:.0%})")

    # By consensus action
    print(f"\n  BY CONSENSUS ACTION:")
    print(f"  {'Action':<15} {'N':>5} {'Under%':>7} {'Avg Conf':>9}")
    print(f"  {'-'*40}")
    for action in ["UNDER", "LEAN_UNDER", "PASS"]:
        sub = filtered[filtered["consensus"] == action]
        if len(sub) == 0:
            continue
        hit = sub["under_hit"].mean()
        conf = sub["consensus_conf"].mean()
        print(f"  {action:<15} {len(sub):>5} {hit:>6.1%} {conf:>9.3f}")

    # By p_under band (0.01 increments)
    print(f"\n  BY P(UNDER) BAND:")
    print(f"  {'Band':<12} {'Games':>6} {'Bets':>5} {'Sel%':>5} "
          f"{'Base Hit':>9} {'LLM Hit':>8} {'LLM ROI':>8} {'Pass Hit':>9}")
    print(f"  {'-'*75}")
    for lo_p in np.arange(0.51, 0.55, 0.01):
        hi_p = lo_p + 0.01
        band = filtered[(filtered["p_under"] >= lo_p) & (filtered["p_under"] < hi_p)]
        if len(band) == 0:
            continue
        band_bets = band[band["consensus"].isin(["UNDER", "LEAN_UNDER"])]
        band_pass = band[~band["consensus"].isin(["UNDER", "LEAN_UNDER"])]
        base_hit = band["under_hit"].mean()
        llm_hit = band_bets["under_hit"].mean() if len(band_bets) > 0 else 0
        llm_profit = sum(
            r["stake_mult"] * (ODDS_UNDER - 1) if r["under_hit"] else -r["stake_mult"]
            for _, r in band_bets.iterrows()
        ) if len(band_bets) > 0 else 0
        llm_roi = llm_profit / band_bets["stake_mult"].sum() if len(band_bets) > 0 else 0
        pass_hit = band_pass["under_hit"].mean() if len(band_pass) > 0 else 0
        sel = len(band_bets) / len(band)
        print(f"  [{lo_p:.2f},{hi_p:.2f}) {len(band):>6} {len(band_bets):>5} {sel:>4.0%} "
              f"{base_hit:>8.1%} {llm_hit:>7.1%} {llm_roi:>+7.1%} {pass_hit:>8.1%}")

    # By month
    mnames = {5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}
    print(f"\n  BY MONTH:")
    print(f"  {'Month':<6} {'Games':>6} {'Bets':>5} {'Sel%':>5} "
          f"{'Base Hit':>9} {'LLM Hit':>8} {'LLM ROI':>8}")
    print(f"  {'-'*55}")
    for m in sorted(filtered["month"].unique()):
        mg = filtered[filtered["month"] == m]
        mb = mg[mg["consensus"].isin(["UNDER", "LEAN_UNDER"])]
        base_hit = mg["under_hit"].mean()
        llm_hit = mb["under_hit"].mean() if len(mb) > 0 else 0
        llm_profit = sum(
            r["stake_mult"] * (ODDS_UNDER - 1) if r["under_hit"] else -r["stake_mult"]
            for _, r in mb.iterrows()
        ) if len(mb) > 0 else 0
        llm_roi = llm_profit / mb["stake_mult"].sum() if len(mb) > 0 else 0
        sel = len(mb) / len(mg)
        print(f"  {mnames.get(m,m):<6} {len(mg):>6} {len(mb):>5} {sel:>4.0%} "
              f"{base_hit:>8.1%} {llm_hit:>7.1%} {llm_roi:>+7.1%}")

    # By season
    print(f"\n  BY SEASON:")
    print(f"  {'Season':<8} {'Games':>6} {'Bets':>5} {'Sel%':>5} "
          f"{'Base Hit':>9} {'LLM Hit':>8} {'LLM ROI':>8}")
    print(f"  {'-'*55}")
    for s in sorted(filtered["season"].unique()):
        sg = filtered[filtered["season"] == s]
        sb = sg[sg["consensus"].isin(["UNDER", "LEAN_UNDER"])]
        base_hit = sg["under_hit"].mean()
        llm_hit = sb["under_hit"].mean() if len(sb) > 0 else 0
        llm_profit = sum(
            r["stake_mult"] * (ODDS_UNDER - 1) if r["under_hit"] else -r["stake_mult"]
            for _, r in sb.iterrows()
        ) if len(sb) > 0 else 0
        llm_roi = llm_profit / sb["stake_mult"].sum() if len(sb) > 0 else 0
        sel = len(sb) / len(sg)
        print(f"  {s:<8} {len(sg):>6} {len(sb):>5} {sel:>4.0%} "
              f"{base_hit:>8.1%} {llm_hit:>7.1%} {llm_roi:>+7.1%}")

    # By team (home) -- top/bottom 5
    print(f"\n  BY HOME TEAM (top 5 / bottom 5 by LLM ROI, min 10 bets):")
    team_stats = []
    for team in filtered["home_team"].unique():
        tg = filtered[filtered["home_team"] == team]
        tb = tg[tg["consensus"].isin(["UNDER", "LEAN_UNDER"])]
        if len(tb) < 10:
            continue
        profit = sum(
            r["stake_mult"] * (ODDS_UNDER - 1) if r["under_hit"] else -r["stake_mult"]
            for _, r in tb.iterrows()
        )
        roi = profit / tb["stake_mult"].sum()
        team_stats.append({"team": team, "bets": len(tb), "hit": tb["under_hit"].mean(), "roi": roi})

    if team_stats:
        team_stats.sort(key=lambda x: -x["roi"])
        print(f"  {'Team':<6} {'Bets':>5} {'Hit%':>6} {'ROI':>7}")
        for t in team_stats[:5]:
            print(f"  {t['team']:<6} {t['bets']:>5} {t['hit']:>5.0%} {t['roi']:>+6.1%}")
        print(f"  {'...':^25}")
        for t in team_stats[-5:]:
            print(f"  {t['team']:<6} {t['bets']:>5} {t['hit']:>5.0%} {t['roi']:>+6.1%}")


def parse_args():
    parser = argparse.ArgumentParser(description="UNDER Expansion Zone LLM Backtest")
    parser.add_argument("--model", default="gpt-5.4", help="LLM model (default: gpt-5.4)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--report-only", action="store_true", help="Just generate report from checkpoint")
    # Report filters
    parser.add_argument("--min-p", type=float, default=0.51, help="Min P(under) filter (default: 0.51)")
    parser.add_argument("--max-p", type=float, default=0.55, help="Max P(under) filter (default: 0.55)")
    parser.add_argument("--months", type=str, default=None, help="Comma-separated months (e.g. 6,7,8)")
    parser.add_argument("--seasons", type=str, default=None, help="Comma-separated seasons (e.g. 2024,2025)")
    return parser.parse_args()


def main():
    args = parse_args()

    months_filter = [int(m) for m in args.months.split(",")] if args.months else None
    seasons_filter = [int(s) for s in args.seasons.split(",")] if args.seasons else None

    if args.report_only:
        checkpoint = load_checkpoint()
        generate_report(
            checkpoint["results"],
            min_p=args.min_p, max_p=args.max_p,
            months=months_filter, seasons=seasons_filter,
        )
        return

    scope, enriched_lookup = build_data()
    results = run_backtest(scope, enriched_lookup, model=args.model, resume=args.resume)
    generate_report(
        results,
        min_p=args.min_p, max_p=args.max_p,
        months=months_filter, seasons=seasons_filter,
    )


if __name__ == "__main__":
    main()
