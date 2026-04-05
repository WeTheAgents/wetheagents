"""Calibration script for Away +1.5 Run Line LLM judge pipeline (v2).

v2 architecture: neutral analyst (predict_simple) -> solo expert -> margin gate.
No edge_consensus on the card. Real away +1.5 odds from SBR data.

Score: COVER = margin_home <= 1 (away team loses by <=1 or wins)
ROI: computed at actual per-game RL odds

Usage:
    python scripts/run_rl_calibration.py --season 2024 --n 200
    python scripts/run_rl_calibration.py --dry-run --season 2024 --n 3
    python scripts/run_rl_calibration.py --season 2024 --save picks/rl_v2.json
    python scripts/run_rl_calibration.py --model gpt-4o
"""

import sys
import warnings
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows cp1251 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import json
import numpy as np
import pandas as pd

# ── Config ───────────────────────────────────────────────────────────────────

CALIBRATION_SEASONS = [2024, 2025]  # seasons with real away RL odds
RL_COARSE_EDGE = 0.05         # pre-filter (LLM never sees this value)
RL_FALLBACK_ODDS = 1.60       # median away +1.5 odds (real data)

MONTH_NAMES = {
    4: "Apr", 5: "May", 6: "Jun", 7: "Jul",
    8: "Aug", 9: "Sep", 10: "Oct"
}

# SBR JSON paths (for real away RL odds)
SBR_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "sbr_odds_full.json"
# Team abbreviation mapping from SBR shortName to our format
SBR_TEAM_MAP = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CUB", "CHW": "CWS", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KC": "KCR",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL",
    "MIN": "MIN", "NYM": "NYM", "NYY": "NYY", "OAK": "OAK",
    "PHI": "PHI", "PIT": "PIT", "SD": "SDP", "SEA": "SEA",
    "SF": "SFO", "STL": "STL", "TB": "TBR", "TEX": "TEX",
    "TOR": "TOR", "WSH": "WSN",
}


def american_to_decimal(odds):
    """Convert American odds to decimal."""
    if odds > 0:
        return 1 + odds / 100
    elif odds < 0:
        return 1 - 100 / odds
    return np.nan


def _load_sbr_rl_odds() -> pd.DataFrame:
    """Load away +1.5 RL odds from SBR JSON for 2021-2025.

    Returns DataFrame with columns: date, away_team, home_team, away_rl_odds_american.
    """
    if not SBR_JSON_PATH.exists():
        logger.warning(f"SBR JSON not found: {SBR_JSON_PATH}")
        return pd.DataFrame()

    import json as json_mod
    logger.info("Loading away RL odds from SBR JSON...")
    with open(SBR_JSON_PATH) as f:
        data = json_mod.load(f)

    book_priority = ["draftkings", "fanduel", "bet365", "caesars", "betmgm"]
    rows = []
    for date_str, games in data.items():
        if not isinstance(games, list):
            continue
        for game in games:
            gv = game.get("gameView", {})
            if gv.get("gameType") != "R":
                continue

            away_short = gv.get("awayTeam", {}).get("shortName", "")
            home_short = gv.get("homeTeam", {}).get("shortName", "")
            away_abbr = SBR_TEAM_MAP.get(away_short, away_short)
            home_abbr = SBR_TEAM_MAP.get(home_short, home_short)

            # Extract away +1.5 odds (awaySpread must be exactly 1.5 = away is underdog)
            spread_data = game.get("odds", {}).get("pointspread", [])
            away_rl_american = np.nan
            for book_name in book_priority:
                for entry in spread_data:
                    if entry.get("sportsbook") == book_name:
                        cl = entry.get("currentLine", {})
                        if cl.get("awaySpread") == 1.5 and cl.get("awayOdds") is not None:
                            away_rl_american = cl["awayOdds"]
                            break
                if not pd.isna(away_rl_american):
                    break

            if pd.notna(away_rl_american):
                rows.append({
                    "date_str": date_str,
                    "away_team": away_abbr,
                    "home_team": home_abbr,
                    "away_rl_american": away_rl_american,
                })

    sbr = pd.DataFrame(rows)
    if len(sbr) > 0:
        sbr["date"] = pd.to_datetime(sbr["date_str"]).dt.normalize()
        logger.info(f"  Loaded {len(sbr)} games with away RL odds from SBR")
    return sbr


def _merge_sbr_rl_odds(rl: pd.DataFrame) -> pd.DataFrame:
    """Merge SBR away RL odds into the RL candidates DataFrame."""
    sbr = _load_sbr_rl_odds()
    if sbr.empty:
        return rl

    # Normalize date for join
    rl["date_norm"] = pd.to_datetime(rl["date"]).dt.normalize()
    sbr_sub = sbr[["date", "away_team", "home_team", "away_rl_american"]].rename(
        columns={"date": "date_norm"}
    )

    merged = rl.merge(
        sbr_sub, on=["date_norm", "away_team", "home_team"], how="left"
    )

    # Fill rl_odds from SBR where missing
    sbr_odds = merged["away_rl_american"].apply(
        lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
    )
    merged["rl_odds"] = merged["rl_odds"].fillna(sbr_odds)
    merged = merged.drop(columns=["date_norm", "away_rl_american"])

    filled = merged["rl_odds"].notna().sum() - rl["rl_odds"].notna().sum()
    logger.info(f"  Filled {filled} games with SBR away RL odds")

    return merged


def build_rl_data():
    """Build enriched DataFrame with walk-forward predictions for RL calibration.

    Returns games with edge_consensus computed from walk-forward CatBoost
    model, filtered to plausible RL candidates (fav is home, edge > coarse).
    Real away +1.5 RL odds are computed from away_run_line_odds column.
    """
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    logger.info("Loading and filtering data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building spec features...")
    full = build_spec_features(games)

    features_available = [
        f for f in SPEC_FEATURES
        if f in full.columns and full[f].notna().mean() > 0.3
    ]
    logger.info(f"Features: {len(features_available)}/{len(SPEC_FEATURES)} available")

    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()

    logger.info("Running walk-forward model (~2 min)...")
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

    # RL candidates: home fav, edge > coarse threshold, not Colorado, not extreme
    rl_mask = (
        (df.get("fav_is_home", pd.Series(True, index=df.index)) == True)
        & (df["edge_consensus"] > RL_COARSE_EDGE)
        & ~df.get("involves_col", pd.Series(False, index=df.index))
        & ~df.get("is_extreme_line", pd.Series(False, index=df.index))
    )
    rl = df[rl_mask].copy()

    # Cover label: away team covers +1.5 when home margin <= 1
    rl["fav_margin"] = rl.get("fav_margin", rl["home_final"] - rl["away_final"])
    rl["covers"] = rl["fav_margin"] <= 1

    # Real away +1.5 RL odds: merge from SBR JSON (xlsx may lack them)
    rl["rl_odds"] = np.nan
    if "away_run_line_odds" in rl.columns:
        rl["rl_odds"] = rl["away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )

    # If most RL odds are missing, try loading from SBR JSON directly
    if rl["rl_odds"].isna().mean() > 0.5:
        rl = _merge_sbr_rl_odds(rl)

    rl["rl_odds_adj"] = rl["rl_odds"].fillna(RL_FALLBACK_ODDS)

    real_odds_pct = rl["rl_odds"].notna().mean()
    logger.info(
        f"RL candidate games: {len(rl)} total | "
        f"cover rate: {rl['covers'].mean():.1%} | "
        f"real RL odds: {real_odds_pct:.0%}"
    )

    return rl


def select_calibration_games(rl, seasons, n_per_season=None):
    """Select calibration games with NATURAL distribution (not stratified).

    If n_per_season is given, randomly sample that many games per season.
    Otherwise, use all games in the season.
    """
    selected = []

    for season in seasons:
        s_rl = rl[rl["season"] == season].copy()
        if len(s_rl) < 10:
            logger.warning(f"Season {season}: only {len(s_rl)} RL games, skipping")
            continue

        if n_per_season and len(s_rl) > n_per_season:
            s_rl = s_rl.sample(n_per_season, random_state=42 + season)

        selected.append(s_rl)

    if not selected:
        logger.error("No calibration games selected!")
        return pd.DataFrame()

    combined = pd.concat(selected, ignore_index=True)
    combined["zone"] = "RL_away_v2"
    combined["month"] = pd.to_datetime(combined["date"]).dt.month

    logger.info(
        f"Calibration set: {len(combined)} games across "
        f"{combined['season'].nunique()} seasons | "
        f"cover rate: {combined['covers'].mean():.1%}"
    )

    for season in sorted(combined["season"].unique()):
        s = combined[combined["season"] == season]
        cv = s["covers"].sum()
        avg_odds = s["rl_odds_adj"].mean()
        logger.info(
            f"  {season}: {len(s)} games ({cv} covers, "
            f"{len(s) - cv} non-covers), avg RL odds: {avg_odds:.3f}"
        )

    return combined


def run_calibration(games_df, *, dry_run=False, model="gpt-4o-mini", save_path=None):
    """Run v2 RL Away +1.5 pipeline: analyst predict_simple -> solo expert -> margin gate.

    Each game goes through:
    1. Analyst predicts score (predict_simple, neutral)
    2. Solo expert evaluates Away +1.5 cover potential
    3. Analyst margin gate adjusts verdict
    4. Score against actual cover result at real RL odds
    """
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"

    if dry_run:
        logger.info("\n=== DRY RUN -- showing v2 feature cards ===\n")
        for _, row in games_df.head(3).iterrows():
            a_card = AnalystCard.from_row(row)
            print(f"\n{'=' * 70}")
            print("[ANALYST CARD -- neutral framing]")
            print(a_card.to_prompt())

            b_card = FeatureCard.from_row(row, "RL_away_v2")
            print(f"\n[RL AWAY v2 CARD -- no edge_consensus]")
            print(b_card.to_prompt())
            print(f"{'=' * 70}")
            covers = bool(row.get("covers", False))
            margin = row.get("fav_margin", "?")
            rl_odds = row.get("rl_odds_adj", RL_FALLBACK_ODDS)
            print(
                f"Actual: covers={covers}, fav_margin={margin}, "
                f"rl_odds={rl_odds:.3f}, "
                f"edge={row.get('edge_consensus', '?'):.3f} (hidden from LLM)"
            )
        return

    # Load v3 genome: strong underdog finder + analyst
    genome_expert = Genome.load(genomes_dir / "rl_away_v3.yaml")
    genome_analyst = Genome.load(genomes_dir / "rl_analyst_v1.yaml")

    logger.info(f"\nUsing model: {model}")
    logger.info(f"Expert: {genome_expert.name} (solo)")
    logger.info(f"Analyst: {genome_analyst.name}")
    logger.info(f"Games: {len(games_df)}\n")

    expert = LLMExpert(genome_expert, provider="openai", model=model)
    analyst = LLMAnalyst(genome_analyst, provider="openai", model=model)
    # DuelEngine needs expert_a and expert_b; pass same expert for both (only expert_a used)
    duel = DuelEngine(expert, expert, analyst=analyst)

    results = []
    for i, (_, row) in enumerate(games_df.iterrows()):
        card = FeatureCard.from_row(row, "RL_away_v2")
        analyst_card = AnalystCard.from_row(row)

        logger.info(f"\n[{i + 1}/{len(games_df)}] {card.game_id}")
        duel_result = duel.run_rl_away_v2(card, analyst_card=analyst_card)

        covers = bool(row.get("covers", False))
        rl_odds = float(row.get("rl_odds_adj", RL_FALLBACK_ODDS))

        if duel_result.final_action == "PASS":
            bet = False
            pnl = 0.0
            correct = None
        else:
            bet = True
            correct = covers
            pnl = (rl_odds - 1) * 100 if covers else -100.0

        # Extract analyst margin for gate analysis
        scenario = duel_result.scenario
        analyst_margin = None
        analyst_score = ""
        analyst_winner = ""
        if scenario:
            analyst_winner = scenario.predicted_winner
            analyst_score = scenario.predicted_score
            try:
                parts = scenario.predicted_score.replace("-", " ").split()
                analyst_margin = abs(int(parts[0]) - int(parts[1]))
            except (ValueError, IndexError):
                pass

        results.append({
            "game_id": card.game_id,
            "season": row.get("season"),
            "month": row.get("month"),
            "final_action": duel_result.final_action,
            "confidence": duel_result.combined_confidence,
            "expert_action": duel_result.verdict_a.action,
            "expert_conf": duel_result.verdict_a.confidence,
            "analyst_winner": analyst_winner,
            "analyst_score": analyst_score,
            "analyst_margin": analyst_margin,
            "covers": covers,
            "fav_margin": float(row.get("fav_margin", 0)),
            "rl_odds": rl_odds,
            "rl_odds_real": bool(pd.notna(row.get("rl_odds"))),
            "edge_consensus": float(row.get("edge_consensus", 0)),
            "bet": bet,
            "correct": correct,
            "pnl": pnl,
        })

    rdf = pd.DataFrame(results)
    _print_rl_calibration_report(rdf)

    if save_path:
        out = Path(save_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        rdf.to_json(out, orient="records", indent=2)
        logger.info(f"\nResults saved to {out}")

    return rdf


def _print_rl_calibration_report(rdf: pd.DataFrame):
    """Print Away +1.5 v2 calibration results summary."""
    total = len(rdf)
    bets = rdf[rdf["bet"] == True]
    passes = rdf[rdf["bet"] == False]

    baseline_cover = rdf["covers"].mean()

    print(f"\n{'=' * 62}")
    print("  RL AWAY +1.5 v2 CALIBRATION REPORT")
    print(f"{'=' * 62}")
    print(f"Total games evaluated: {total}")
    print(f"Baseline cover rate:   {baseline_cover:.1%} (natural distribution)")
    print(f"Bets placed:  {len(bets)} ({len(bets) / total * 100:.0f}%)")
    print(f"Passed:       {len(passes)} ({len(passes) / total * 100:.0f}%)")
    print(f"Bet rate:     {len(bets) / total * 100:.0f}% (target: 30-40%)")

    if len(bets) > 0:
        n_correct = bets["correct"].sum()
        cover_acc = n_correct / len(bets)
        total_pnl = bets["pnl"].sum()
        roi = total_pnl / (len(bets) * 100) * 100
        avg_odds = bets["rl_odds"].mean()
        breakeven = 1 / avg_odds

        print(f"\n--- Bet Results ---")
        print(f"Cover accuracy: {int(n_correct)}/{len(bets)} ({cover_acc:.1%})")
        print(f"Avg RL odds:    {avg_odds:.3f} (breakeven {breakeven:.1%})")
        print(f"Cover edge:     {cover_acc - breakeven:+.1%}")
        print(f"Total P&L:      {total_pnl:+.0f} units")
        print(f"ROI:            {roi:+.1f}%")

        # Real vs fallback odds
        real = bets[bets["rl_odds_real"] == True]
        fallback = bets[bets["rl_odds_real"] == False]
        if len(real) > 0 and len(fallback) > 0:
            print(f"\n  Real odds:     {len(real)} bets, {real['correct'].mean():.1%} cover")
            print(f"  Fallback odds: {len(fallback)} bets, {fallback['correct'].mean():.1%} cover")

    if len(passes) > 0:
        pass_cover = passes["covers"].mean()
        print(f"\nPASS pool cover: {pass_cover:.1%} (should be < baseline {baseline_cover:.1%})")

    # Analyst margin gate analysis
    if "analyst_margin" in rdf.columns:
        print(f"\n--- Analyst Margin Gate ---")
        for margin_range, label in [
            (lambda m: m is not None and m <= 1, "margin<=1 (tight)"),
            (lambda m: m is not None and m == 2, "margin=2 (border)"),
            (lambda m: m is not None and m >= 3, "margin>=3 (blowout)"),
        ]:
            subset = rdf[rdf["analyst_margin"].apply(margin_range)]
            if len(subset) == 0:
                continue
            n_bet = subset["bet"].sum()
            n_cover = subset["covers"].sum()
            bet_rate = n_bet / len(subset) * 100
            cover_rate = n_cover / len(subset) * 100
            # Cover rate for BETS only in this margin bucket
            bet_subset = subset[subset["bet"] == True]
            bet_cover = bet_subset["correct"].mean() if len(bet_subset) > 0 else 0
            print(
                f"  {label}: {len(subset)} games, "
                f"{bet_rate:.0f}% bet, "
                f"{cover_rate:.0f}% overall cover, "
                f"BET cover: {bet_cover:.0%} ({len(bet_subset)} bets)"
            )

    # Expert action distribution
    print(f"\n--- Expert Decision ---")
    for action in sorted(rdf["expert_action"].dropna().unique()):
        subset = rdf[rdf["expert_action"] == action]
        cover_rate = subset["covers"].mean()
        print(f"  {action}: {len(subset)} ({len(subset)/total*100:.0f}%), cover rate {cover_rate:.1%}")

    # Analyst predicted winner breakdown
    if "analyst_winner" in rdf.columns:
        print(f"\n--- Analyst Predicted Winner ---")
        for winner in ["away", "home"]:
            subset = rdf[rdf["analyst_winner"] == winner]
            if len(subset) == 0:
                continue
            n_bet = subset["bet"].sum()
            bet_rate = n_bet / len(subset) * 100
            cover_rate = subset["covers"].mean()
            dog_wins = (subset["fav_margin"] < 0).sum()
            dog_rate = dog_wins / len(subset) * 100
            # BET pool cover rate
            bet_sub = subset[subset["bet"] == True]
            bet_cover = bet_sub["correct"].mean() if len(bet_sub) > 0 else 0
            print(
                f"  analyst={winner}: {len(subset)} games, "
                f"dog wins {dog_rate:.0f}%, cover {cover_rate:.0f}%, "
                f"bet rate {bet_rate:.0f}%, BET cover {bet_cover:.0%}"
            )

    # Per-season breakdown
    print(f"\n--- Per-Season ---")
    seasons = sorted(rdf["season"].dropna().unique())
    for season in seasons:
        s_all = rdf[rdf["season"] == season]
        s_bets = s_all[s_all["bet"] == True]
        baseline = s_all["covers"].mean()
        if len(s_bets) > 0:
            cover_acc = s_bets["correct"].mean()
            s_pnl = s_bets["pnl"].sum()
            s_roi = s_pnl / (len(s_bets) * 100) * 100
            avg_odds = s_bets["rl_odds"].mean()
            print(
                f"  {int(season)}: {len(s_all)} eligible, {len(s_bets)} bets, "
                f"{cover_acc:.1%} cover (baseline {baseline:.1%}), "
                f"avg odds {avg_odds:.3f}, ROI {s_roi:+.1f}%"
            )
        else:
            print(f"  {int(season)}: {len(s_all)} eligible, 0 bets (all PASS)")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="RL Away +1.5 v2 LLM calibration"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show feature cards without making API calls"
    )
    parser.add_argument(
        "--n", type=int, default=None,
        help="Games per season (default: all)"
    )
    parser.add_argument(
        "--season", type=int,
        help="Single season to run (default: calibration set)"
    )
    parser.add_argument(
        "--months", type=str,
        help="Comma-separated month numbers (e.g. 6,7,8,9)"
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o-mini",
        help="OpenAI model to use"
    )
    parser.add_argument(
        "--save", type=str,
        help="Save results to JSON file"
    )
    args = parser.parse_args()

    months = None
    if args.months:
        months = [int(m) for m in args.months.split(",")]

    logger.info("Building RL calibration data...")
    rl = build_rl_data()

    seasons = [args.season] if args.season else CALIBRATION_SEASONS

    # Filter months if specified
    if months:
        rl["month"] = pd.to_datetime(rl["date"]).dt.month
        rl = rl[rl["month"].isin(months)]
        month_str = ", ".join(MONTH_NAMES.get(m, str(m)) for m in sorted(months))
        logger.info(f"Filtered to months: {month_str}")

    games_df = select_calibration_games(rl, seasons, n_per_season=args.n)

    if games_df.empty:
        logger.error("No games selected. Exiting.")
        return

    run_calibration(
        games_df,
        dry_run=args.dry_run,
        model=args.model,
        save_path=args.save,
    )


if __name__ == "__main__":
    main()
