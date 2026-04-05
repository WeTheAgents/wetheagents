"""Fav -1.5 RL LLM judges calibration backtest.

Flow:
1. Build enriched data with walk-forward model
2. Apply rule filter (close_game_wp <= 0.45 + streak >= 0)
3. Sample 80 games (40 covers + 40 non-covers, stratified)
4. Run 3-judge duel: Analyst → Momentum + Value → Consensus
5. Score: STRONG_BET / LEAN / PASS accuracy and selectivity

Usage:
    python scripts/run_rl_fav_llm.py             # run 80-game calibration
    python scripts/run_rl_fav_llm.py --dry-run    # show 3 cards, no API calls
    python scripts/run_rl_fav_llm.py --n 40       # smaller sample
"""

import sys
import warnings
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Fix Windows console encoding for unicode characters in cards
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd

from src.data_loader import american_to_decimal

FAV_RL_FALLBACK = 2.40


def build_enriched():
    """Build enriched df with fav-oriented features.

    No walk-forward model — fav -1.5 uses rule filters + LLM, not regression.
    This makes the pipeline 10x faster and supports all seasons including 2025.
    """
    from src.features import build_spec_features

    logger.info("Building spec features...")
    df = build_spec_features()

    # Fav margin
    if "fav_margin" not in df.columns:
        df["fav_margin"] = np.where(
            df["fav_is_home"],
            df["home_final"] - df["away_final"],
            df["away_final"] - df["home_final"],
        )

    # RL odds
    df["rl_odds"] = np.nan
    if "home_run_line_odds" in df.columns:
        hf = df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == -1.5)
        df.loc[hf, "rl_odds"] = df.loc[hf, "home_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    if "away_run_line_odds" in df.columns:
        af = ~df["fav_is_home"] & (df.get("home_run_line", pd.Series(dtype=float)).fillna(0) == 1.5)
        df.loc[af, "rl_odds"] = df.loc[af, "away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    df["rl_odds"] = df["rl_odds"].fillna(FAV_RL_FALLBACK)

    # Universe: valid RL data OR inferred (fav exists = RL -1.5 available)
    mask = pd.Series(True, index=df.index)
    if "home_run_line" in df.columns:
        has_rl = df["home_run_line"].isin([-1.5, 1.5])
        # For seasons without RL data (2022+), infer from fav_is_home
        no_rl_data = df["home_run_line"].isna() | (~df["home_run_line"].isin([-1.5, 1.5]))
        mask = mask & (has_rl | no_rl_data)  # keep all — RL odds will use fallback
    if "involves_col" in df.columns:
        mask = mask & ~df["involves_col"]
    if "is_extreme_line" in df.columns:
        mask = mask & ~df["is_extreme_line"]
    df = df[mask].copy()

    df["fav_covers"] = df["fav_margin"] >= 2

    # Ensure month column
    if "month" not in df.columns:
        df["month"] = pd.to_datetime(df["date"]).dt.month

    # Fav-oriented columns for filtering
    fav_is_home = df["fav_is_home"]
    if "close_game_wp_home" in df.columns:
        df["fav_close_game_wp"] = np.where(
            fav_is_home, df["close_game_wp_home"], df["close_game_wp_away"]
        )
    if "streak_home" in df.columns:
        df["fav_streak"] = np.where(fav_is_home, df["streak_home"], df["streak_away"])
        df["dog_streak"] = np.where(fav_is_home, df["streak_away"], df["streak_home"])
        df["fav_streak_diff"] = df["fav_streak"] - df["dog_streak"]

    # Implied prob of fav
    if "home_implied_prob" in df.columns:
        df["fav_implied_prob"] = np.where(
            fav_is_home, df["home_implied_prob"], df["away_implied_prob"]
        )

    logger.info(f"Universe: {len(df)} games, cover rate {df['fav_covers'].mean()*100:.1f}%")
    return df


def apply_rule_filter(df, filter_name="cwp_streak"):
    """Apply a rule-based primary filter.

    filter_name:
        "cwp_streak" — close_game_wp <= 0.45 + streak >= 0 (original session 25)
        "impl65-75"  — implied prob 65-75% band (robust across seasons)
    """
    if filter_name == "impl65-75":
        mask = (df["fav_implied_prob"] >= 0.65) & (df["fav_implied_prob"] < 0.75)
    else:
        mask = pd.Series(True, index=df.index)
        if "fav_close_game_wp" in df.columns:
            mask = mask & (df["fav_close_game_wp"] <= 0.45)
        if "fav_streak_diff" in df.columns:
            mask = mask & (df["fav_streak_diff"] >= 0)
    filtered = df[mask].copy()
    cr = filtered['fav_covers'].mean() * 100 if len(filtered) > 0 else 0
    logger.info(f"Filter [{filter_name}]: {len(df)} → {len(filtered)} games (cover {cr:.1f}%)")
    return filtered


def select_sample(df, n=200, season=None, months=None):
    """Select games for evaluation.

    If season is set: filter to that season (+ optional month range), use ALL games.
    Otherwise: balanced 50/50 sample of n games across all seasons.
    """
    if season is not None:
        sub = df[df["season"] == season].copy()
        if months is not None:
            lo, hi = months
            sub = sub[(sub["month"] >= lo) & (sub["month"] <= hi)]
        logger.info(f"OOS season {season}: {len(sub)} games "
                    f"(cover rate {sub['fav_covers'].mean()*100:.1f}%)")
        return sub

    covers = df[df["fav_covers"]].copy()
    non_covers = df[~df["fav_covers"]].copy()
    n_each = n // 2

    if len(covers) > n_each:
        covers = covers.sample(n_each, random_state=42)
    if len(non_covers) > n_each:
        non_covers = non_covers.sample(n_each, random_state=42)

    sample = pd.concat([covers, non_covers], ignore_index=True).sample(frac=1, random_state=42)
    logger.info(f"Sample: {len(sample)} games ({sample['fav_covers'].sum()} covers, "
                f"{(~sample['fav_covers']).sum()} non-covers)")
    return sample


def run_calibration(games_df, *, dry_run=False, model="gpt-5.4", cache_suffix=""):
    """Run analyst (simple) + solo Momentum on sample games and score results."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    genomes_dir = Path(__file__).resolve().parent.parent / "genomes"
    genome_momentum = Genome.load(genomes_dir / "rl_momentum_v1.yaml")
    genome_analyst = Genome.load(genomes_dir / "rl_analyst_v1.yaml")

    if dry_run:
        logger.info("\n=== DRY RUN — showing feature cards ===\n")
        for _, row in games_df.head(3).iterrows():
            a_card = AnalystCard.from_row(row)
            print(f"\n{'=' * 70}")
            print("[ANALYST CARD]")
            print(a_card.to_prompt())

            b_card = FeatureCard.from_row(row, "RL_fav")
            print(f"\n[RL FAV BETTING CARD]")
            print(b_card.to_prompt())
            print(f"{'=' * 70}")
            print(f"Actual: fav_margin={row.get('fav_margin', '?')}, "
                  f"covers={row.get('fav_covers', '?')}")
        return None

    # Solo Momentum — expert_b is a dummy (DuelEngine requires two, but run_rl_fav uses only expert_a)
    expert = LLMExpert(genome_momentum, provider="openai", model=model)
    analyst = LLMAnalyst(genome_analyst, provider="openai", model=model)
    duel = DuelEngine(expert, expert, analyst=analyst)  # expert_b unused by run_rl_fav

    # Cache: resume from previous partial run (separate per suffix)
    cache_name = f"rl_fav_cache{cache_suffix}.json"
    cache_path = Path(__file__).resolve().parent.parent / "picks" / cache_name
    cache_path.parent.mkdir(exist_ok=True)
    cached = {}
    if cache_path.exists():
        import json as _json
        cached = {r["game_id"]: r for r in _json.loads(cache_path.read_text())}
        logger.info(f"Loaded {len(cached)} cached results from {cache_path}")

    results = []
    for i, (_, row) in enumerate(games_df.iterrows()):
        card = FeatureCard.from_row(row, "RL_fav")
        analyst_card = AnalystCard.from_row(row)

        # Skip if already cached
        if card.game_id in cached:
            results.append(cached[card.game_id])
            logger.info(f"[{i + 1}/{len(games_df)}] {card.game_id} (cached)")
            continue

        logger.info(f"\n[{i + 1}/{len(games_df)}] {card.game_id}")
        duel_result = duel.run_rl_fav(card, analyst_card=analyst_card)

        fav_margin = int(row.get("fav_margin", 0))
        fav_covers = fav_margin >= 2

        # Extract analyst predicted margin from score
        analyst_score = duel_result.scenario.predicted_score if duel_result.scenario else "0-0"
        try:
            parts = analyst_score.replace("-", " ").split()
            analyst_margin = abs(int(parts[0]) - int(parts[1]))
        except (ValueError, IndexError):
            analyst_margin = 0

        entry = {
            "game_id": card.game_id,
            "season": int(row.get("season", 0)),
            "month": int(row.get("month", 0)),
            "final_action": duel_result.final_action,
            "confidence": duel_result.combined_confidence,
            "fav_margin": fav_margin,
            "fav_covers": fav_covers,
            "rl_odds": float(row.get("rl_odds", FAV_RL_FALLBACK)),
            "momentum_action": duel_result.verdict_a.action,
            "momentum_conf": duel_result.verdict_a.confidence,
            "analyst_score": analyst_score,
            "analyst_margin": analyst_margin,
            "analyst_winner": (
                duel_result.scenario.predicted_winner if duel_result.scenario else "N/A"
            ),
        }
        results.append(entry)

        # Save cache incrementally
        all_cached = list(cached.values()) + [e for e in results if e["game_id"] not in cached]
        import json as _json
        cache_path.write_text(_json.dumps(all_cached, indent=2))

    rdf = pd.DataFrame(results)
    _print_report(rdf)
    return rdf


def _print_report(rdf):
    """Print calibration results — Analyst + solo Momentum."""
    total = len(rdf)
    baseline_cr = rdf["fav_covers"].mean()

    print(f"\n{'=' * 70}")
    print("RL FAV -1.5 — ANALYST + SOLO MOMENTUM CALIBRATION")
    print(f"{'=' * 70}")
    print(f"Total games: {total}")
    print(f"Sample baseline cover rate: {baseline_cr * 100:.1f}% (balanced sample)")

    # BET vs PASS
    for action in ["BET", "PASS"]:
        sub = rdf[rdf["final_action"] == action]
        if len(sub) == 0:
            continue
        cr = sub["fav_covers"].mean()
        pnl = np.where(sub["fav_covers"], (sub["rl_odds"] - 1) * 100, -100)
        roi = pnl.sum() / (len(sub) * 100) * 100
        print(f"\n  {action}: {len(sub)} games ({len(sub)/total*100:.0f}%)")
        print(f"    Cover rate: {cr * 100:.1f}%")
        print(f"    ROI (flat): {roi:+.1f}%")
        print(f"    Avg confidence: {sub['confidence'].mean():.2f}")

    # Selectivity
    bets = rdf[rdf["final_action"] == "BET"]
    passes = rdf[rdf["final_action"] == "PASS"]

    if len(bets) > 0 and len(passes) > 0:
        bet_cr = bets["fav_covers"].mean()
        pass_cr = passes["fav_covers"].mean()
        lift = bet_cr - pass_cr
        print(f"\n  SELECTIVITY:")
        print(f"    BET pool:  {len(bets)} games, cover {bet_cr * 100:.1f}%")
        print(f"    PASS pool: {len(passes)} games, cover {pass_cr * 100:.1f}%")
        print(f"    Lift: {lift * 100:+.1f}pp")

    # Analyst predicted margin vs actual
    print(f"\n  ANALYST PREDICTED SCORES:")
    for margin_range, lo, hi in [("1 run", 0, 2), ("2-3 runs", 2, 4), ("4+ runs", 4, 99)]:
        sub = rdf[(rdf["analyst_margin"] >= lo) & (rdf["analyst_margin"] < hi)]
        if len(sub) == 0:
            continue
        cr = sub["fav_covers"].mean()
        bet_n = (sub["final_action"] == "BET").sum()
        bet_sub = sub[sub["final_action"] == "BET"]
        bet_cr = bet_sub["fav_covers"].mean() if len(bet_sub) > 0 else 0
        print(f"    Analyst margin {margin_range}: {len(sub)} games, "
              f"actual cover {cr*100:.1f}%, "
              f"Momentum bets {bet_n} ({bet_cr*100:.0f}% cover)")

    # Analyst margin correlation with actual margin
    corr = rdf[["analyst_margin", "fav_margin"]].corr().iloc[0, 1]
    print(f"\n  Analyst margin vs actual margin correlation: r = {corr:.3f}")

    # By confidence band
    print(f"\n  BY MOMENTUM CONFIDENCE:")
    for lo, hi, label in [(0.7, 1.0, "high (>=0.70)"), (0.5, 0.7, "medium (0.50-0.69)"), (0, 0.5, "low (<0.50)")]:
        sub = rdf[(rdf["confidence"] >= lo) & (rdf["confidence"] < hi) & (rdf["final_action"] == "BET")]
        if len(sub) > 0:
            cr = sub["fav_covers"].mean()
            print(f"    Conf {label}: {len(sub)} bets, cover {cr*100:.1f}%")

    # By season
    print(f"\n  BY SEASON:")
    for s in sorted(rdf["season"].unique()):
        sub = rdf[rdf["season"] == s]
        if len(sub) < 3:
            continue
        bets_s = sub[sub["final_action"] == "BET"]
        if len(bets_s) > 0:
            cr = bets_s["fav_covers"].mean()
            pnl = np.where(bets_s["fav_covers"], (bets_s["rl_odds"] - 1) * 100, -100)
            roi = pnl.sum() / (len(bets_s) * 100) * 100
            print(f"    {s}: {len(bets_s)}/{len(sub)} bets, "
                  f"cover {cr * 100:.1f}%, ROI {roi:+.1f}%")

    # By month (useful for single-season OOS)
    if "month" in rdf.columns and rdf["season"].nunique() == 1:
        print(f"\n  BY MONTH:")
        for m in sorted(rdf["month"].unique()):
            sub = rdf[rdf["month"] == m]
            bets_m = sub[sub["final_action"] == "BET"]
            base_cr = sub["fav_covers"].mean()
            if len(bets_m) > 0:
                cr = bets_m["fav_covers"].mean()
                pnl = np.where(bets_m["fav_covers"], (bets_m["rl_odds"] - 1) * 100, -100)
                roi = pnl.sum() / (len(bets_m) * 100) * 100
                print(f"    Month {m}: {len(bets_m)}/{len(sub)} bets "
                      f"({len(bets_m)/len(sub)*100:.0f}% rate), "
                      f"cover {cr*100:.1f}%, ROI {roi:+.1f}%  "
                      f"(baseline {base_cr*100:.0f}%)")
            else:
                print(f"    Month {m}: 0/{len(sub)} bets (baseline {base_cr*100:.0f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--season", type=int, default=None,
                        help="Single season for OOS validation (uses all games, no sampling)")
    parser.add_argument("--months", type=str, default=None,
                        help="Month range, e.g. '5-9' for May-Sep (requires --season)")
    parser.add_argument("--filter", type=str, default="cwp_streak",
                        help="Filter: 'cwp_streak' (default) or 'impl65-75'")
    args = parser.parse_args()

    months = None
    if args.months:
        lo, hi = args.months.split("-")
        months = (int(lo), int(hi))

    cache_suffix = f"_{args.season}" if args.season else ""

    df = build_enriched()
    filtered = apply_rule_filter(df, filter_name=args.filter)
    sample = select_sample(filtered, n=args.n, season=args.season, months=months)
    run_calibration(sample, dry_run=args.dry_run, model=args.model, cache_suffix=cache_suffix)


if __name__ == "__main__":
    main()
