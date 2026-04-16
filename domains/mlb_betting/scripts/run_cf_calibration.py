"""Calibration for CF (coinflip/pick'em) zone — propose-then-challenge model.

Structure expert proposes BET/PASS, Devil's Advocate challenges proposals.
Scores results to measure: accuracy, kill rate, and quality of kills.

Uses build_all_features() instead of build_spec_features() because the latter
excludes CF games (fav_ml > 105 filter).

Usage:
    python scripts/run_cf_calibration.py
    python scripts/run_cf_calibration.py --dry-run   # show cards without API calls
    python scripts/run_cf_calibration.py --n-per-season 8  # fewer games (faster)
    python scripts/run_cf_calibration.py --season 2024 --months 6,8,9 --model gpt-5.4
    python scripts/run_cf_calibration.py --season 2024 --months 6,8,9 --save picks/cf_cal.json
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

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import numpy as np
import pandas as pd

# Seasons for calibration (spread across eras to test stability)
CALIBRATION_SEASONS = [2017, 2018, 2019, 2021, 2024]
GAMES_PER_SEASON = 16  # 8 home wins + 8 away wins

MONTH_NAMES = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def build_cf_data():
    """Build enriched DataFrame with all features for CF games."""
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds
    from src.features import build_all_features

    logger.info("Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building all features (~3 min)...")
    enriched = build_all_features(games)

    # Filter to CF games only
    cf_mask = (
        enriched["is_coinflip"]
        & ~enriched.get("involves_col", pd.Series(False, index=enriched.index))
        & ~enriched.get("is_extreme_line", pd.Series(False, index=enriched.index))
    )
    cf = enriched[cf_mask].copy()
    logger.info(f"CF games (bettable): {len(cf)}")

    return cf


def select_calibration_games(cf, n_per_season=GAMES_PER_SEASON):
    """Select stratified calibration games across seasons and outcomes.

    For each season: n_per_season/2 home wins + n_per_season/2 away wins.
    Within each group, prefer feature diversity (strong RPI, strong pitcher,
    strong streak, neutral).
    """
    half = n_per_season // 2
    selected = []

    for season in CALIBRATION_SEASONS:
        s_cf = cf[cf["season"] == season].copy()
        if len(s_cf) < 10:
            logger.warning(f"Season {season}: only {len(s_cf)} CF games, skipping")
            continue

        # Split by outcome
        home_wins = s_cf[s_cf["home_win"] == True]
        away_wins = s_cf[s_cf["home_win"] == False]

        # Sample from each bucket
        n_hw = min(half, len(home_wins))
        n_aw = min(half, len(away_wins))

        if n_hw > 0:
            selected.append(home_wins.sample(n_hw, random_state=42 + season))
        if n_aw > 0:
            selected.append(away_wins.sample(n_aw, random_state=43 + season))

    if not selected:
        logger.error("No calibration games selected!")
        return pd.DataFrame()

    combined = pd.concat(selected, ignore_index=True)
    combined["zone"] = "CF_pickem"
    logger.info(f"Calibration set: {len(combined)} games across "
                f"{combined['season'].nunique()} seasons")

    # Summary
    for season in sorted(combined["season"].unique()):
        s = combined[combined["season"] == season]
        hw = s["home_win"].sum()
        aw = len(s) - hw
        logger.info(f"  {season}: {len(s)} games ({hw} home wins, {aw} away wins)")

    return combined


def select_season_games(cf, season, months=None):
    """Select ALL CF games for a single season, optionally filtered by months."""
    s_cf = cf[cf["season"] == season].copy()
    if len(s_cf) == 0:
        logger.error(f"No CF games found for season {season}")
        return pd.DataFrame()

    if months:
        s_cf = s_cf[s_cf["date"].dt.month.isin(months)]
        month_str = ", ".join(MONTH_NAMES.get(m, str(m)) for m in sorted(months))
        logger.info(f"Filtered to months: {month_str}")

    if len(s_cf) == 0:
        logger.error(f"No CF games after month filter")
        return pd.DataFrame()

    s_cf["zone"] = "CF_pickem"
    s_cf["month"] = s_cf["date"].dt.month

    logger.info(f"Season {season}: {len(s_cf)} CF games total")
    for m in sorted(s_cf["month"].unique()):
        m_games = s_cf[s_cf["month"] == m]
        hw = m_games["home_win"].sum()
        aw = len(m_games) - hw
        logger.info(f"  {MONTH_NAMES.get(m, m)}: {len(m_games)} games "
                    f"({hw} home wins, {aw} away wins)")

    return s_cf


def run_calibration(games_df, *, dry_run=False, model="gpt-4o-mini",
                    advocate_model=None):
    """Run analyst + CF duel engine on calibration games and score results."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    advocate_model = advocate_model or model

    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"

    # Load CF genomes: Structure (proposer) + Advocate (challenger)
    genome_a = Genome.load(genomes_dir / "cf_structure_v1.yaml")
    genome_b = Genome.load(genomes_dir / "cf_advocate_v1.yaml")
    genome_analyst = Genome.load(genomes_dir / "analyst_v1.yaml")

    if dry_run:
        logger.info("\n=== DRY RUN — showing CF feature cards ===\n")
        for _, row in games_df.head(3).iterrows():
            a_card = AnalystCard.from_row(row)
            print(f"\n{'=' * 70}")
            print("[ANALYST CARD — no betting context]")
            print(a_card.to_prompt())

            b_card = FeatureCard.from_row(row, "CF_pickem")
            print(f"\n[CF BETTING CARD — symmetric pick'em framing]")
            print(b_card.to_prompt())
            print(f"{'=' * 70}")
            print(f"Actual outcome: home_win={row.get('home_win', '?')}, "
                  f"home_final={row.get('home_final', '?')}, "
                  f"away_final={row.get('away_final', '?')}")
        return

    logger.info(f"Using model: Structure={model}, Advocate={advocate_model}")
    expert_a = LLMExpert(genome_a, provider="openai", model=model)
    expert_b = LLMExpert(genome_b, provider="openai", model=advocate_model)
    analyst = LLMAnalyst(genome_analyst, provider="openai", model=model)
    duel = DuelEngine(expert_a, expert_b, analyst=analyst)

    results = []
    for i, (_, row) in enumerate(games_df.iterrows()):
        card = FeatureCard.from_row(row, "CF_pickem")
        analyst_card = AnalystCard.from_row(row)

        logger.info(f"\n[{i + 1}/{len(games_df)}] {card.game_id}")
        duel_result = duel.run(card, analyst_card=analyst_card)

        # Determine actual outcome based on target_side
        home_won = bool(row.get("home_win", False))
        target_side = duel_result.target_side  # "home" | "away" | ""

        if duel_result.final_action == "PASS" or not target_side:
            pick_correct = None
        else:
            pick_correct = (target_side == "home") == home_won

        # Calculate P&L for this bet
        if pick_correct is not None:
            if target_side == "home":
                odds = row.get("home_decimal_odds", 1.90)
            else:
                odds = row.get("away_decimal_odds", 1.90)
            pnl = (odds - 1) * 100 if pick_correct else -100
        else:
            odds = 0
            pnl = 0

        # Advocate fields
        cv = duel_result.challenge_verdict
        advocate_action = cv.action if cv else "NOT_CALLED"
        advocate_severity = cv.severity if cv else ""

        results.append({
            "game_id": card.game_id,
            "season": row.get("season"),
            "month": row["date"].month if hasattr(row.get("date", None), "month") else None,
            "zone": "CF_pickem",
            "final_action": duel_result.final_action,
            "target_side": target_side,
            "confidence": duel_result.combined_confidence,
            "stake": duel_result.stake_multiplier,
            "home_won": home_won,
            "pick_correct": pick_correct,
            "odds": odds,
            "pnl": pnl,
            "verdict_a": duel_result.verdict_a.action,
            "conf_a": duel_result.verdict_a.confidence,
            "advocate_action": advocate_action,
            "advocate_severity": advocate_severity,
            # Structure's proposed side (for solo analysis)
            "structure_side": duel_result.verdict_a.action.replace("BET_", "").lower()
                if duel_result.verdict_a.action.startswith("BET_") else "",
            "structure_correct": (
                (duel_result.verdict_a.action == "BET_HOME") == home_won
                if duel_result.verdict_a.action.startswith("BET_") else None
            ),
        })

    rdf = pd.DataFrame(results)
    _print_cf_calibration_report(rdf)
    return rdf


def _print_cf_calibration_report(rdf):
    """Print CF calibration results summary."""
    total = len(rdf)
    bets = rdf[rdf["final_action"] != "PASS"]
    passes = rdf[rdf["final_action"] == "PASS"]

    print(f"\n{'=' * 60}")
    print("CF CALIBRATION REPORT")
    print(f"{'=' * 60}")
    print(f"Total games: {total}")
    print(f"Bets placed: {len(bets)} ({len(bets) / total * 100:.0f}%)")
    print(f"Passed: {len(passes)} ({len(passes) / total * 100:.0f}%)")

    if len(bets) > 0:
        correct = bets["pick_correct"].sum()
        accuracy = correct / len(bets) * 100
        total_pnl = bets["pnl"].sum()
        roi = total_pnl / (len(bets) * 100) * 100
        avg_odds = bets["odds"].mean()

        print(f"\nBet accuracy: {int(correct)}/{len(bets)} ({accuracy:.1f}%)")
        print(f"Total P&L: {total_pnl:+.0f} units")
        print(f"ROI: {roi:+.1f}%")
        print(f"Avg odds on bets: {avg_odds:.3f}")

        # By target side
        for side in ["home", "away"]:
            sub = bets[bets["target_side"] == side]
            if len(sub) > 0:
                acc = sub["pick_correct"].sum() / len(sub) * 100
                sub_pnl = sub["pnl"].sum()
                print(f"  Target {side}: {len(sub)} bets, {acc:.0f}% correct, P&L {sub_pnl:+.0f}")

        # By season
        seasons = sorted(rdf["season"].dropna().unique())
        if len(seasons) > 1:
            print(f"\nPer-season breakdown:")
            for season in seasons:
                s_all = rdf[rdf["season"] == season]
                s_bets = bets[bets["season"] == season]
                if len(s_bets) > 0:
                    acc = s_bets["pick_correct"].sum() / len(s_bets) * 100
                    s_pnl = s_bets["pnl"].sum()
                    print(f"  {int(season)}: {len(s_all)} games, {len(s_bets)} bets, "
                          f"{acc:.0f}% correct, P&L {s_pnl:+.0f}")
                else:
                    print(f"  {int(season)}: {len(s_all)} games, 0 bets (all PASS)")

        # By month (useful for single-season runs)
        if "month" in rdf.columns:
            print(f"\nPer-month breakdown:")
            for m in sorted(rdf["month"].dropna().unique()):
                m_all = rdf[rdf["month"] == m]
                m_bets = bets[bets["month"] == m] if "month" in bets.columns else pd.DataFrame()
                m_name = MONTH_NAMES.get(int(m), str(int(m)))
                if len(m_bets) > 0:
                    acc = m_bets["pick_correct"].sum() / len(m_bets) * 100
                    m_pnl = m_bets["pnl"].sum()
                    m_pass = len(m_all) - len(m_bets)
                    print(f"  {m_name}: {len(m_all)} games, {len(m_bets)} bets, "
                          f"{m_pass} pass, {acc:.0f}% correct, P&L {m_pnl:+.0f}")
                else:
                    print(f"  {m_name}: {len(m_all)} games, 0 bets (all PASS)")

        # By confidence bucket
        if len(bets) >= 5:
            print(f"\nConfidence calibration:")
            for lo, hi, label in [(0.0, 0.55, "Low"), (0.55, 0.65, "Medium"), (0.65, 1.0, "High")]:
                sub = bets[(bets["confidence"] >= lo) & (bets["confidence"] < hi)]
                if len(sub) > 0:
                    acc = sub["pick_correct"].sum() / len(sub) * 100
                    print(f"  {label} ({lo:.2f}-{hi:.2f}): {len(sub)} bets, {acc:.0f}% correct")

    # Home bias check
    if len(bets) > 0:
        home_pct = (bets["target_side"] == "home").mean() * 100
        print(f"\nHome bias check: {home_pct:.0f}% of bets target home "
              f"({'WARNING: possible home bias' if home_pct > 70 else 'OK'})")

    # Propose-Challenge breakdown
    structure_bets = rdf[rdf["verdict_a"] != "PASS"]
    structure_pass = rdf[rdf["verdict_a"] == "PASS"]
    advocate_conceded = rdf[rdf["advocate_action"] == "CONCEDE"]
    advocate_challenged = rdf[rdf["advocate_action"] == "CHALLENGE"]

    print(f"\nPropose-Challenge breakdown:")
    print(f"  Structure PASS: {len(structure_pass)} ({len(structure_pass) / total * 100:.0f}%)")
    print(f"  Structure BET -> Advocate CONCEDE: {len(advocate_conceded)} ({len(advocate_conceded) / total * 100:.0f}%)")
    print(f"  Structure BET -> Advocate CHALLENGE: {len(advocate_challenged)} ({len(advocate_challenged) / total * 100:.0f}%)")

    if len(structure_bets) > 0:
        kill_rate = len(advocate_challenged) / len(structure_bets) * 100
        print(f"  Advocate kill rate: {kill_rate:.0f}% of Structure's proposals blocked")

    # Structure solo baseline (what would have happened without Advocate)
    if len(structure_bets) > 0:
        solo_correct = structure_bets[structure_bets["structure_correct"] == True]
        solo_wrong = structure_bets[structure_bets["structure_correct"] == False]
        solo_acc = len(solo_correct) / len(structure_bets) * 100
        print(f"\n  Structure solo baseline: {len(structure_bets)} bets, "
              f"{solo_acc:.1f}% accuracy")

    # Quality of Advocate's kills (did it kill good or bad bets?)
    if len(advocate_challenged) > 0:
        killed_good = advocate_challenged[advocate_challenged["structure_correct"] == True]
        killed_bad = advocate_challenged[advocate_challenged["structure_correct"] == False]
        print(f"  Advocate killed: {len(killed_bad)} bad bets + {len(killed_good)} good bets")
        if len(killed_bad) + len(killed_good) > 0:
            kill_precision = len(killed_bad) / (len(killed_bad) + len(killed_good)) * 100
            print(f"  Kill precision: {kill_precision:.0f}% (% of kills that were correct)")

    # Severity distribution
    if len(advocate_challenged) > 0:
        print(f"\n  Challenge severity distribution:")
        for sev in ["fatal", "moderate", "minor"]:
            n = (advocate_challenged["advocate_severity"] == sev).sum()
            if n > 0:
                print(f"    {sev}: {n}")

    # Gate 2 assessment
    print(f"\n{'=' * 60}")
    print("GATE 2 ASSESSMENT")
    print(f"{'=' * 60}")
    if len(bets) > 0:
        accuracy = bets["pick_correct"].sum() / len(bets) * 100
        roi = bets["pnl"].sum() / (len(bets) * 100) * 100
        pass_rate = len(passes) / total * 100

        if accuracy > 55 and roi > 0:
            print(f"  RESULT: GO (accuracy {accuracy:.1f}% > 55%, ROI {roi:+.1f}% > 0%)")
        elif accuracy >= 52:
            print(f"  RESULT: TUNE (accuracy {accuracy:.1f}%, ROI {roi:+.1f}%)")
            print(f"  -> Consider adjusting Advocate severity thresholds")
        else:
            print(f"  RESULT: KILL (accuracy {accuracy:.1f}% < 52%)")

        if pass_rate > 85:
            print(f"  WARNING: pass rate {pass_rate:.0f}% > 85% — experts too conservative")
        elif pass_rate < 40:
            print(f"  WARNING: pass rate {pass_rate:.0f}% < 40% — experts too aggressive")
    else:
        print("  RESULT: KILL (no bets placed — 100% PASS rate)")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="CF zone LLM expert calibration")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show feature cards without API calls")
    parser.add_argument("--n-per-season", type=int, default=GAMES_PER_SEASON,
                        help=f"Games per season (default: {GAMES_PER_SEASON})")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="LLM model for Structure + Analyst (default: gpt-4o-mini)")
    parser.add_argument("--advocate-model", type=str, default=None,
                        help="LLM model for Advocate (default: same as --model)")
    parser.add_argument("--season", type=int, default=None,
                        help="Single season — use ALL CF games (overrides multi-season sampling)")
    parser.add_argument("--months", type=str, default=None,
                        help="Comma-separated months to include, e.g. 6,8,9")
    parser.add_argument("--save", type=str, default=None,
                        help="Save results DataFrame to JSON file")
    args = parser.parse_args()

    logger.info("Building CF data with all features...")
    cf = build_cf_data()

    if args.season:
        months = [int(m) for m in args.months.split(",")] if args.months else None
        cal_games = select_season_games(cf, args.season, months)
    else:
        logger.info("Selecting calibration games...")
        cal_games = select_calibration_games(cf, n_per_season=args.n_per_season)

    if cal_games.empty:
        logger.error("No calibration games selected. Aborting.")
        return

    adv_model = args.advocate_model or args.model
    logger.info(f"\nRunning CF calibration on {len(cal_games)} games "
                f"(structure={args.model}, advocate={adv_model})...")
    rdf = run_calibration(cal_games, dry_run=args.dry_run, model=args.model,
                          advocate_model=adv_model)

    if args.save and rdf is not None:
        save_path = Path(__file__).resolve().parent.parent / args.save
        save_path.parent.mkdir(parents=True, exist_ok=True)
        rdf.to_json(save_path, orient="records", indent=2)
        logger.info(f"\nResults saved to {save_path}")


if __name__ == "__main__":
    main()
