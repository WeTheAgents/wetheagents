"""LLM Expert Pilot — Zone A (0.51-0.52) games.

Tests whether LLM experts can profitably filter borderline UNDER bets
that the ML model is uncertain about (P(under) between 0.51 and 0.52).

Runs on 3 selected days from 2024 season with balanced outcomes (6W/5L).
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
    load_all_seasons,
    enrich_innings_from_retrosheet,
    apply_data_filters,
    add_derived_odds,
)
from src.features import build_all_features, build_ou_features_v3, OU_FEATURES
from src.model import (
    walk_forward_splits,
    UnderModelConfig,
    train_under_model,
    predict_under_proba,
)
from src.feature_card import OUFeatureCard, OUAnalystCard
from src.llm_expert import Genome, LLMExpert, LLMAnalyst
from src.llm_duel import DuelEngine


def main():
    # Load and prepare data
    games = load_all_seasons()
    games = enrich_innings_from_retrosheet(games)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    ou = build_ou_features_v3(enriched=enriched)

    # Get predictions for 2024 fold
    seasons = sorted(ou["season"].unique().tolist())
    splits = walk_forward_splits(seasons)
    cfg = UnderModelConfig()

    removed = {
        "close_ou",
        "combined_rpg_last10",
        "combined_rapg",
        "combined_rapg_last10",
        "pyth_wp_combined",
    }
    v3_interactions = [
        "bp_fip_osc_x_rpg",
        "matchup_rpg_x_bp_fip",
        "sp_quality_gap",
        "effective_obp_x_sp_fip",
    ]
    feats = [
        f
        for f in OU_FEATURES
        if f not in removed and f in ou.columns and ou[f].notna().mean() > 0.3
    ]
    feats += [
        f
        for f in v3_interactions
        if f in ou.columns and ou[f].notna().mean() > 0.3
    ]

    # Find fold with 2024
    for fold_idx, (train_s, val_s, test_s) in enumerate(splits):
        if 2024 in test_s:
            cb, lr_model, calibrator, metrics = train_under_model(
                ou, feats, train_s, val_s, cfg=cfg
            )
            train_medians = metrics["train_medians"]

            push_mask = (
                ou["is_push"]
                if "is_push" in ou.columns
                else pd.Series(False, index=ou.index)
            )
            test_mask = ou["season"].isin([2024]) & ~push_mask
            X_test = ou.loc[test_mask, feats].values.astype(float)
            y_test = ou.loc[test_mask, "under_hit"].values.astype(int)
            p = predict_under_proba(
                X_test, cb, lr_model, calibrator, train_medians, cfg=cfg
            )

            test_df = ou.loc[test_mask].copy()
            test_df["p_under"] = p
            break

    # Filter: Zone A (0.51-0.52), Jun-Sep 2024
    test_df["month"] = pd.to_datetime(test_df["date"]).dt.month
    zone_a = test_df[
        (test_df["p_under"] >= 0.51) & (test_df["p_under"] < 0.52)
    ].copy()
    pilot_games = zone_a[zone_a["month"].isin([6, 7, 8, 9])]

    logging.info(f"Pilot games: {len(pilot_games)} (Jun-Sep 2024 Zone A)")

    # Setup LLM duel
    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"
    ou_analyst_genome = Genome.load(genomes_dir / "ou_analyst_v1.yaml")
    ou_pitching_genome = Genome.load(genomes_dir / "ou_pitching_v1.yaml")
    ou_scoring_genome = Genome.load(genomes_dir / "ou_scoring_v1.yaml")

    under_engine = DuelEngine(
        LLMExpert(ou_pitching_genome, model="gpt-4o-mini"),
        LLMExpert(ou_scoring_genome, model="gpt-4o-mini"),
        analyst=LLMAnalyst(ou_analyst_genome, model="gpt-4o-mini"),
    )

    # Enriched for feature cards
    enriched_2024 = enriched[enriched["season"] == 2024].copy()

    # Run duel on each game
    results = []
    total_games = len(pilot_games)
    for game_num, (idx, game) in enumerate(pilot_games.iterrows(), 1):
        date = str(game["date"])
        home = game["home_team"]
        away = game["away_team"]
        logging.info(f"[{game_num}/{total_games}] {date[:10]} {home} vs {away}")
        p_u = game["p_under"]
        ou_line = game["close_ou"]
        actual_total = game["home_final"] + game["away_final"]
        under_hit = int(game["under_hit"])

        # Find game in enriched (normalize date format)
        date_normalized = str(date)[:10]  # "2024-04-15 00:00:00" -> "2024-04-15"
        match = enriched_2024[
            (enriched_2024["date"].astype(str).str[:10] == date_normalized)
            & (enriched_2024["home_team"] == home)
            & (enriched_2024["away_team"] == away)
        ]

        if len(match) == 0:
            logging.warning(f"Game not found: {date} {home} vs {away}")
            continue

        game_row = match.iloc[0]

        try:
            analyst_card = OUAnalystCard.from_row(game_row)
            betting_card = OUFeatureCard.from_row(game_row, p_under=p_u)

            duel_result = under_engine.run_ou(
                betting_card, analyst_card=analyst_card, close_ou=ou_line
            )

            results.append(
                {
                    "date": date,
                    "month": pd.to_datetime(date).month,
                    "game": f"{home} vs {away}",
                    "ou_line": ou_line,
                    "p_under": p_u,
                    "actual_total": actual_total,
                    "actual": "UNDER" if under_hit else "OVER",
                    "expert_a": (
                        duel_result.verdict_a.action
                        if duel_result.verdict_a
                        else None
                    ),
                    "expert_a_conf": (
                        duel_result.verdict_a.confidence
                        if duel_result.verdict_a
                        else None
                    ),
                    "expert_b": (
                        duel_result.verdict_b.action
                        if duel_result.verdict_b
                        else None
                    ),
                    "expert_b_conf": (
                        duel_result.verdict_b.confidence
                        if duel_result.verdict_b
                        else None
                    ),
                    "consensus": duel_result.final_action,
                    "consensus_conf": duel_result.combined_confidence,
                    "stake": duel_result.stake_multiplier,
                    "scenario_total": (
                        duel_result.scenario.predicted_total
                        if duel_result.scenario
                        else None
                    ),
                }
            )

            logging.info(
                f"{date} {home} vs {away}: "
                f"consensus={duel_result.final_action} "
                f"(A={duel_result.verdict_a.action}, "
                f"B={duel_result.verdict_b.action}) "
                f'actual={"UNDER" if under_hit else "OVER"}'
            )

        except Exception as e:
            logging.error(f"Error on {date} {home} vs {away}: {e}")
            import traceback

            traceback.print_exc()

    # Print results
    print()
    print("=" * 110)
    print("LLM EXPERT PILOT - Zone A (0.51-0.52) - 11 games across 3 days")
    print("=" * 110)
    print()
    header = (
        f"{'Date':<12} {'Game':<16} {'O/U':>5} {'P(u)':>6} "
        f"{'Total':>5} {'Actual':>7} {'ExA':>7} {'ExB':>7} "
        f"{'Consensus':>12} {'Stake':>6} {'Result':>10}"
    )
    print(header)
    print("-" * 110)

    correct = 0
    total_bets = 0
    total_pl = 0.0
    wins = 0

    for r in results:
        would_bet = r["consensus"] in ("UNDER", "LEAN_UNDER")

        if would_bet:
            total_bets += 1
            if r["actual"] == "UNDER":
                pl = 100 * r["stake"] * 0.909
                result_str = "WIN"
                wins += 1
            else:
                pl = -100 * r["stake"]
                result_str = "LOSS"
            total_pl += pl
        else:
            pl = 0
            if r["actual"] == "OVER":
                result_str = "GOOD SKIP"
            else:
                result_str = "BAD SKIP"

        is_correct = (would_bet and r["actual"] == "UNDER") or (
            not would_bet and r["actual"] == "OVER"
        )
        if is_correct:
            correct += 1

        ea = r["expert_a"] or "?"
        eb = r["expert_b"] or "?"
        print(
            f"{r['date']:<12} {r['game']:<16} {r['ou_line']:>5.1f} "
            f"{r['p_under']:>5.3f} {r['actual_total']:>5.0f} "
            f"{r['actual']:>7} {ea:>7} {eb:>7} "
            f"{r['consensus']:>12} {r['stake']:>5.1f}x "
            f"{result_str:>10}"
        )

    print()
    print(f"SUMMARY:")
    if not results:
        print("  No results — check game matching")
        return
    print(f"  Correct decisions: {correct}/{len(results)} ({correct/len(results)*100:.0f}%)")
    print(f"  Bets placed: {total_bets}/{len(results)}")
    if total_bets > 0:
        hit_rate = wins / total_bets
        roi = total_pl / (total_bets * 100)
        print(f"  Bet hit rate: {wins}/{total_bets} ({hit_rate*100:.0f}%)")
        print(f"  Total P/L: ${total_pl:+.0f}")
        print(f"  ROI: {roi*100:+.1f}%")
    else:
        print("  No bets placed (all PASS)")

    # Count PASS on OVER (good filtering)
    over_games = [r for r in results if r["actual"] == "OVER"]
    over_passed = [r for r in over_games if r["consensus"] not in ("UNDER", "LEAN_UNDER")]
    print(f"  OVER games filtered out: {len(over_passed)}/{len(over_games)}")

    under_games = [r for r in results if r["actual"] == "UNDER"]
    under_bet = [r for r in under_games if r["consensus"] in ("UNDER", "LEAN_UNDER")]
    print(f"  UNDER games kept: {len(under_bet)}/{len(under_games)}")

    # Baseline comparison: what if we bet ALL Zone A games?
    all_under = sum(1 for r in results if r["actual"] == "UNDER")
    all_n = len(results)
    all_hit = all_under / all_n if all_n else 0
    all_roi = all_hit * (100/110) - (1 - all_hit)
    all_pl = all_n * 100 * all_roi
    print()
    print(f"  BASELINE (bet all {all_n} Zone A): hit {all_hit*100:.1f}%, ROI {all_roi*100:+.1f}%, P/L ${all_pl:+.0f}")

    # Per-month breakdown
    month_names = {6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep"}
    print()
    print("  PER-MONTH BREAKDOWN:")
    print(f"  {'Month':<6} {'Games':>5} {'Bets':>5} {'Wins':>5} {'Hit%':>6} {'ROI%':>7} {'P/L':>9}")
    print(f"  {'-'*50}")
    for m in [6, 7, 8, 9]:
        mr = [r for r in results if r.get("month") == m]
        if not mr:
            continue
        m_bets = [r for r in mr if r["consensus"] in ("UNDER", "LEAN_UNDER")]
        m_wins = [r for r in m_bets if r["actual"] == "UNDER"]
        m_n = len(m_bets)
        if m_n > 0:
            m_hit = len(m_wins) / m_n
            m_roi = m_hit * (100/110) - (1 - m_hit)
            m_pl = sum(
                100 * r["stake"] * 0.909 if r["actual"] == "UNDER" else -100 * r["stake"]
                for r in m_bets
            )
            print(f"  {month_names[m]:<6} {len(mr):>5} {m_n:>5} {len(m_wins):>5} {m_hit*100:>5.0f}% {m_roi*100:>+6.1f}% ${m_pl:>+8.0f}")
        else:
            print(f"  {month_names[m]:<6} {len(mr):>5}     0     -     -       -         -")


if __name__ == "__main__":
    main()
