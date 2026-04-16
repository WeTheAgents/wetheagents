"""OVER LLM Duel Pilot — validate LLM expert gate on OVER candidates.

Pipeline:
  1. Walk-forward -> P(under) for target season
  2. Filter to P(under) < threshold -> OVER candidates
  3. Run OVER LLM duel (OffenseFirst + FatigueExploit)
  4. Score BET decisions against actual results

Usage:
    python scripts/run_over_llm_pilot.py --season 2024 --threshold 0.49 --dry-run
    python scripts/run_over_llm_pilot.py --season 2024 --threshold 0.49
    python scripts/run_over_llm_pilot.py --season 2025 --threshold 0.49 --months 5,6,7,8,9
    python scripts/run_over_llm_pilot.py --season 2025 --threshold 0.49 --resume
"""

import sys
import logging
import warnings
import os
import argparse
import json
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

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
RESULTS_DIR = BASE_DIR / "knowledge" / "over_pilot"
OU_DECIMAL_ODDS = 1.909  # -110 standard


def load_checkpoint(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_checkpoint(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def get_season_predictions(season: int, ou, feats):
    """Train walk-forward model and get P(under) for a given season."""
    seasons = sorted(ou["season"].unique().tolist())
    splits = walk_forward_splits(seasons)
    cfg = UnderModelConfig()

    for train_s, val_s, test_s in splits:
        if season in test_s:
            cb, lr_model, calibrator, metrics = train_under_model(
                ou, feats, train_s, val_s, cfg=cfg
            )
            train_medians = metrics["train_medians"]

            push_mask = (
                ou["is_push"]
                if "is_push" in ou.columns
                else pd.Series(False, index=ou.index)
            )
            test_mask = ou["season"].isin([season]) & ~push_mask
            X_test = ou.loc[test_mask, feats].values.astype(float)
            p = predict_under_proba(
                X_test, cb, lr_model, calibrator, train_medians, cfg=cfg
            )

            test_df = ou.loc[test_mask].copy()
            test_df["p_under"] = p
            test_df["p_over"] = 1 - p
            return test_df

    raise RuntimeError(f"No fold contains {season}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show eligible games without API calls")
    parser.add_argument("--threshold", type=float, default=0.48,
                        help="P(under) threshold: bet OVER when P(u) < this (default: 0.48)")
    parser.add_argument("--months", type=str, default="4,5,6,7,8,9",
                        help="Months to include (default: 4,5,6,7,8,9)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="LLM model for experts")
    parser.add_argument("--season", type=int, default=2024,
                        help="Season to test (default: 2024)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint")
    args = parser.parse_args()

    checkpoint_path = BASE_DIR / "picks" / f"_over_pilot_{args.season}_checkpoint.json"

    months = [int(m) for m in args.months.split(",")]

    # ── Data pipeline ─────────────────────────────────────────────────────
    logging.info("Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    ou = build_ou_features_v3(enriched=enriched)

    # Feature list (Session 19: 21 features)
    removed = {
        "close_ou", "combined_rpg_last10", "combined_rapg",
        "combined_rapg_last10", "pyth_wp_combined",
    }
    v3_interactions = [
        "bp_fip_osc_x_rpg", "matchup_rpg_x_bp_fip",
        "sp_quality_gap", "effective_obp_x_sp_fip",
    ]
    feats = [
        f for f in OU_FEATURES
        if f not in removed and f in ou.columns and ou[f].notna().mean() > 0.3
    ]
    feats += [
        f for f in v3_interactions
        if f in ou.columns and ou[f].notna().mean() > 0.3
    ]
    logging.info(f"Features: {len(feats)}")

    # ── Get predictions for target season ─────────────────────────────────
    logging.info(f"Running walk-forward for {args.season}...")
    test_df = get_season_predictions(args.season, ou, feats)

    # ── Filter OVER candidates ────────────────────────────────────────────
    test_df["month"] = pd.to_datetime(test_df["date"]).dt.month
    candidates = test_df[
        (test_df["p_under"] < args.threshold)
        & test_df["month"].isin(months)
    ].sort_values("date").copy()

    candidates["actual_total"] = candidates["home_final"] + candidates["away_final"]
    candidates["over_hit"] = (candidates["actual_total"] > candidates["close_ou"]).astype(int)

    n_total = len(candidates)
    n_over = candidates["over_hit"].sum()
    base_hr = n_over / n_total if n_total else 0

    print("=" * 100)
    print(f"OVER LLM PILOT — {args.season} season, P(under) < {args.threshold}")
    print(f"Months: {months}")
    print(f"Eligible games: {n_total}")
    print(f"Baseline: {n_over}/{n_total} OVER ({base_hr*100:.1f}%)")
    base_roi = base_hr * (OU_DECIMAL_ODDS - 1) - (1 - base_hr)
    print(f"Baseline ROI (bet all): {base_roi*100:+.1f}%")
    print("=" * 100)

    if args.dry_run:
        # Show monthly distribution
        print(f"\n  Monthly distribution:")
        month_names = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul",
                       8: "Aug", 9: "Sep", 10: "Oct"}
        print(f"  {'Month':<6} {'Games':>5} {'OVER':>5} {'Hit%':>6}")
        print(f"  {'-'*25}")
        for m in months:
            mc = candidates[candidates["month"] == m]
            mn = len(mc)
            mo = mc["over_hit"].sum()
            print(f"  {month_names.get(m, str(m)):<6} {mn:>5} {mo:>5} {mo/mn*100 if mn else 0:>5.1f}%")

        # Show P(under) distribution
        print(f"\n  P(under) distribution:")
        for lo, hi in [(0.40, 0.44), (0.44, 0.46), (0.46, 0.47), (0.47, 0.48)]:
            mask = (candidates["p_under"] >= lo) & (candidates["p_under"] < hi)
            sub = candidates[mask]
            sn = len(sub)
            if sn > 0:
                so = sub["over_hit"].sum()
                print(f"  P(u) [{lo:.2f}, {hi:.2f}): {sn:>4} games, "
                      f"{so}/{sn} OVER ({so/sn*100:.1f}%)")

        # Estimate bet volume at different bet rates
        print(f"\n  Projected bets at different bet rates:")
        for rate in [0.20, 0.25, 0.30, 0.35]:
            print(f"  {rate*100:.0f}% bet rate: ~{int(n_total * rate)} bets")

        print(f"\n  API cost estimate: {n_total} games x 3 calls = {n_total*3} calls")
        print(f"  GPT-4o-mini batch: ~${n_total * 3 * 0.0003:.2f}")
        return

    # ── Setup LLM duel engine ─────────────────────────────────────────────
    over_offense_genome = Genome.load(GENOMES_DIR / "ou_over_offense_v1.yaml")
    over_fatigue_genome = Genome.load(GENOMES_DIR / "ou_over_fatigue_v1.yaml")
    ou_analyst_genome = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")

    over_engine = DuelEngine(
        LLMExpert(over_offense_genome, model=args.model),
        LLMExpert(over_fatigue_genome, model=args.model),
        analyst=LLMAnalyst(ou_analyst_genome, model=args.model),
    )

    enriched_season = enriched[enriched["season"] == args.season].copy()

    # ── Load checkpoint if resuming ───────────────────────────────────────
    checkpoint = load_checkpoint(checkpoint_path) if args.resume else {}
    processed_keys = set(checkpoint.get("processed", []))
    results = checkpoint.get("results", [])

    # ── Run duel on each game ─────────────────────────────────────────────
    total_games = len(candidates)
    for game_num, (idx, game) in enumerate(candidates.iterrows(), 1):
        date = str(game["date"])[:10]
        home = game["home_team"]
        away = game["away_team"]
        game_key = f"{date}_{away}@{home}"

        if game_key in processed_keys:
            continue

        logging.info(f"[{game_num}/{total_games}] {date} {away}@{home} "
                     f"P(u)={game['p_under']:.3f} O/U={game['close_ou']:.1f}")

        # Find in enriched
        match = enriched_season[
            (enriched_season["date"].astype(str).str[:10] == date)
            & (enriched_season["home_team"] == home)
            & (enriched_season["away_team"] == away)
        ]
        if len(match) == 0:
            logging.warning(f"  Not found in enriched, skipping")
            continue

        game_row = match.iloc[0]
        p_over = float(game["p_over"])
        ou_line = float(game["close_ou"])

        try:
            analyst_card = OUAnalystCard.from_row_over(game_row)
            betting_card = OUFeatureCard.from_row_over(game_row, p_over=p_over)

            duel_result = over_engine.run_over(
                betting_card, analyst_card=analyst_card, close_ou=ou_line
            )

            result = {
                "date": date,
                "month": int(game["month"]),
                "game": f"{away}@{home}",
                "home": home,
                "away": away,
                "ou_line": ou_line,
                "p_under": float(game["p_under"]),
                "p_over": p_over,
                "actual_total": int(game["actual_total"]),
                "over_hit": int(game["over_hit"]),
                "actual": "OVER" if game["over_hit"] else "UNDER",
                "expert_a": duel_result.verdict_a.action if duel_result.verdict_a else None,
                "expert_a_conf": duel_result.verdict_a.confidence if duel_result.verdict_a else None,
                "expert_b": duel_result.verdict_b.action if duel_result.verdict_b else None,
                "expert_b_conf": duel_result.verdict_b.confidence if duel_result.verdict_b else None,
                "consensus": duel_result.final_action,
                "consensus_conf": duel_result.combined_confidence,
                "stake": duel_result.stake_multiplier,
                "scenario_total": (
                    duel_result.scenario.predicted_total
                    if duel_result.scenario else None
                ),
            }
            results.append(result)
            processed_keys.add(game_key)

            # Checkpoint every 10 games
            if len(processed_keys) % 10 == 0:
                save_checkpoint(checkpoint_path, {"processed": list(processed_keys), "results": results})

            logging.info(f"  -> {duel_result.final_action} "
                         f"(A={result['expert_a']}, B={result['expert_b']}) "
                         f"actual={result['actual']}")

        except Exception as e:
            logging.error(f"  Error: {e}")
            import traceback
            traceback.print_exc()

    # Final checkpoint
    save_checkpoint(checkpoint_path, {"processed": list(processed_keys), "results": results})

    # ── Print results ─────────────────────────────────────────────────────
    print()
    print("=" * 110)
    print(f"OVER LLM PILOT RESULTS — {args.season} season, P(under) < {args.threshold}")
    print(f"Games evaluated: {len(results)}")
    print("=" * 110)

    # Determine which consensus values count as OVER bet
    over_actions = {"OVER", "LEAN_OVER"}

    bets = [r for r in results if r["consensus"] in over_actions]
    passes = [r for r in results if r["consensus"] not in over_actions]

    wins = [r for r in bets if r["over_hit"]]
    losses = [r for r in bets if not r["over_hit"]]

    print(f"\n  Evaluated: {len(results)} games")
    print(f"  Bets: {len(bets)} ({len(bets)/len(results)*100:.0f}% bet rate)" if results else "  No results")
    print(f"  Record: {len(wins)}W-{len(losses)}L")

    if bets:
        hr = len(wins) / len(bets)
        total_pl = sum(
            (OU_DECIMAL_ODDS - 1) * 100 * r["stake"] if r["over_hit"]
            else -100 * r["stake"]
            for r in bets
        )
        total_risked = sum(100 * r["stake"] for r in bets)
        roi = total_pl / total_risked * 100

        print(f"  Hit rate: {hr*100:.1f}%  (breakeven: {1/OU_DECIMAL_ODDS*100:.1f}%)")
        print(f"  ROI: {roi:+.1f}%")
        print(f"  P/L: ${total_pl:+.0f}")
    else:
        print("  No bets placed (all PASS)")

    # Filtering quality
    over_games = [r for r in results if r["over_hit"]]
    under_games = [r for r in results if not r["over_hit"]]
    over_bet = [r for r in over_games if r["consensus"] in over_actions]
    under_bet = [r for r in under_games if r["consensus"] in over_actions]
    print(f"\n  Filtering quality:")
    print(f"    OVER games captured: {len(over_bet)}/{len(over_games)} "
          f"({len(over_bet)/len(over_games)*100:.0f}%)" if over_games else "")
    print(f"    UNDER games filtered: {len(under_games) - len(under_bet)}/{len(under_games)} "
          f"({(len(under_games)-len(under_bet))/len(under_games)*100:.0f}%)" if under_games else "")

    # Baseline comparison
    print(f"\n  Baseline (bet ALL {len(results)} games):")
    all_over = sum(1 for r in results if r["over_hit"])
    all_hr = all_over / len(results) if results else 0
    all_roi = (all_hr * (OU_DECIMAL_ODDS - 1) - (1 - all_hr)) * 100
    print(f"    Hit: {all_hr*100:.1f}%, ROI: {all_roi:+.1f}%")

    # ── Per-month breakdown ───────────────────────────────────────────────
    month_names = {4: "Apr", 5: "May", 6: "Jun", 7: "Jul",
                   8: "Aug", 9: "Sep", 10: "Oct"}
    print(f"\n  {'Month':<6} {'Games':>5} {'Bets':>5} {'Wins':>5} {'Hit%':>6} "
          f"{'ROI%':>7} {'P/L':>9}")
    print(f"  {'-'*55}")

    for m in sorted(months):
        mr = [r for r in results if r["month"] == m]
        if not mr:
            continue
        m_bets = [r for r in mr if r["consensus"] in over_actions]
        m_wins = [r for r in m_bets if r["over_hit"]]
        m_n = len(m_bets)
        if m_n > 0:
            m_hr = len(m_wins) / m_n
            m_pl = sum(
                (OU_DECIMAL_ODDS - 1) * 100 * r["stake"] if r["over_hit"]
                else -100 * r["stake"]
                for r in m_bets
            )
            m_risked = sum(100 * r["stake"] for r in m_bets)
            m_roi = m_pl / m_risked * 100 if m_risked else 0
            print(f"  {month_names.get(m, str(m)):<6} {len(mr):>5} {m_n:>5} "
                  f"{len(m_wins):>5} {m_hr*100:>5.0f}% {m_roi:>+6.1f}% ${m_pl:>+8.0f}")
        else:
            print(f"  {month_names.get(m, str(m)):<6} {len(mr):>5}     0")

    # ── Confidence breakdown ──────────────────────────────────────────────
    print(f"\n  Confidence breakdown (bets only):")
    if bets:
        high_conf = [r for r in bets if (r["consensus_conf"] or 0) >= 70]
        mid_conf = [r for r in bets if 50 <= (r["consensus_conf"] or 0) < 70]
        low_conf = [r for r in bets if (r["consensus_conf"] or 0) < 50]
        for label, group in [("High (>=70)", high_conf), ("Mid (50-69)", mid_conf), ("Low (<50)", low_conf)]:
            gn = len(group)
            if gn == 0:
                continue
            gw = sum(1 for r in group if r["over_hit"])
            ghr = gw / gn
            gpl = sum(
                (OU_DECIMAL_ODDS - 1) * 100 * r["stake"] if r["over_hit"]
                else -100 * r["stake"]
                for r in group
            )
            print(f"    {label:<15}: {gn:>3} bets, {gw}W-{gn-gw}L, "
                  f"hit {ghr*100:.0f}%, P/L ${gpl:+.0f}")

    # ── Save full report ──────────────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"over_pilot_{args.season}_t{args.threshold}.json"
    report_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n  Full results saved to: {report_path}")


if __name__ == "__main__":
    main()
