"""UNDER LLM Gate Experiment v2: Neutral Scorer + DA reuse.

Instead of asking "should I bet UNDER?" (biased), ask "how many runs?"
and decide mechanically. DA data reused from v1 checkpoint.

Usage:
    python scripts/run_under_gate_experiment_v2.py --dry-run
    python scripts/run_under_gate_experiment_v2.py --model gpt-5.4
    python scripts/run_under_gate_experiment_v2.py --resume
    python scripts/run_under_gate_experiment_v2.py --report-only
"""

import argparse
import json
import logging
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.feature_card import OUFeatureCard  # uses from_row_neutral
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.llm_expert import Genome, LLMExpert
from src.model import UnderModelConfig, walk_forward_splits, train_under_model, predict_under_proba

GENOMES_DIR = Path(__file__).resolve().parent.parent / "genomes"
PICKS_DIR = Path(__file__).resolve().parent.parent / "picks"
CHECKPOINT_PATH = PICKS_DIR / "_under_gate_experiment_v2.json"
V1_CHECKPOINT_PATH = PICKS_DIR / "_under_gate_experiment.json"


def _set_checkpoint(suffix: str | None):
    global CHECKPOINT_PATH
    if suffix:
        CHECKPOINT_PATH = PICKS_DIR / f"_under_gate_experiment_v2_{suffix}.json"
ODDS_UNDER = 1.909
BASE_UNIT = 100

TARGET_SEASONS = [2021, 2022, 2023, 2024, 2025]
ZONE_LO = 0.52
ZONE_HI = 0.53


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {"results": [], "processed_keys": []}


def save_checkpoint(data):
    PICKS_DIR.mkdir(exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2, default=str))


def load_v1_da_data():
    """Load DA verdicts from v1 experiment, keyed by game_key."""
    if not V1_CHECKPOINT_PATH.exists():
        logger.warning("v1 checkpoint not found, DA data unavailable")
        return {}
    v1 = json.loads(V1_CHECKPOINT_PATH.read_text())
    da_lookup = {}
    for r in v1["results"]:
        da_lookup[r["game_key"]] = {
            "da_action": r.get("da_action", "PASS"),
            "da_conf": r.get("da_conf", 0.0),
            "da_total": r.get("da_total", 0.0),
            "da_reasoning": r.get("da_reasoning", ""),
        }
    return da_lookup


def build_predictions():
    """Build walk-forward predictions with test_size=1."""
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building features...")
    enriched = build_all_features(games)
    ou = build_ou_features(enriched=enriched)
    ou = ou[ou["season"] <= 2025].copy()

    feats = [f for f in OU_FEATURES if f in ou.columns and ou[f].notna().mean() > 0.3]
    cfg = UnderModelConfig()

    logger.info(f"Walk-forward (test_size=1) with {len(feats)} features...")
    seasons = sorted(ou["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=5, max_train=cfg.max_train_seasons,
                                test_size=1)

    all_preds = []
    push_mask = ou["is_push"] if "is_push" in ou.columns else pd.Series(False, index=ou.index)

    for i, (train_s, val_s, test_s) in enumerate(folds):
        logger.info(f"  fold_{i}: train={train_s[0]}-{train_s[-1]}, val={val_s}, test={test_s}")
        cb, lr, cal, metrics = train_under_model(ou, feats, train_s, val_s, cfg=cfg)
        test_mask = ou["season"].isin(test_s) & ~push_mask
        if test_mask.sum() < 10:
            continue
        X_test = ou.loc[test_mask, feats].values.astype(float)
        p_under = predict_under_proba(X_test, cb, lr, cal, metrics["train_medians"], cfg=cfg)
        meta = ["season", "date", "home_team", "away_team", "close_ou", "total_runs", "under_hit"]
        preds_df = ou.loc[test_mask, meta].copy()
        preds_df["p_under"] = p_under
        all_preds.append(preds_df)

    preds = pd.concat(all_preds, ignore_index=True)

    enriched["date_str"] = pd.to_datetime(enriched["date"]).dt.strftime("%Y-%m-%d")
    enriched_lookup = enriched.set_index(["date_str", "home_team", "away_team"])

    return preds, enriched_lookup


# -- Main Loop ------------------------------------------------------------

def run_experiment(scope, enriched_lookup, model, resume):
    """Run 1 LLM call per game: Scorer only."""
    scorer_genome = Genome.load(GENOMES_DIR / "ou_scorer_v1.yaml")
    scorer = LLMExpert(scorer_genome, model=model)

    checkpoint = load_checkpoint() if resume else {"results": [], "processed_keys": []}
    processed = set(checkpoint["processed_keys"])
    results = checkpoint["results"]

    logger.info(f"Checkpoint: {len(processed)} done, {len(scope) - len(processed)} remaining")

    total = len(scope)
    errors = 0
    done = len(processed)

    for i, (idx, game) in enumerate(scope.iterrows()):
        date_str = pd.to_datetime(game["date"]).strftime("%Y-%m-%d")
        home = game["home_team"]
        away = game["away_team"]
        game_key = f"{date_str}_{home}_{away}"

        if game_key in processed:
            continue

        try:
            game_row = enriched_lookup.loc[(date_str, home, away)]
            if isinstance(game_row, pd.DataFrame):
                game_row = game_row.iloc[0]
        except KeyError:
            logger.warning(f"  [{i+1}/{total}] {date_str} {away}@{home}: not in enriched")
            errors += 1
            continue

        p_u = float(game["p_under"])
        ou_line = float(game["close_ou"])

        try:
            card = OUFeatureCard.from_row_blind(game_row)
            scoring = scorer.analyze_ou_scoring(card)

            result = {
                "game_key": game_key,
                "date": date_str,
                "season": int(game["season"]),
                "home_team": home,
                "away_team": away,
                "ou_line": ou_line,
                "p_under": round(p_u, 4),
                "total_runs": int(game["total_runs"]),
                "under_hit": int(game["under_hit"]),
                "scorer_total": round(scoring["predicted_total"], 1),
                "scorer_delta": round(scoring["probable_delta"], 1),
                "scorer_factors": scoring["key_factors"],
                "scorer_reasoning": scoring["reasoning"],
            }

            results.append(result)
            processed.add(game_key)
            done += 1

            gap = ou_line - scoring["predicted_total"]
            logger.info(
                f"  [{done}/{total}] {date_str} {away}@{home}: "
                f"scorer={scoring['predicted_total']:.1f} +/-{scoring['probable_delta']:.1f} "
                f"line={ou_line} gap={gap:+.1f}"
            )

            if done % 25 == 0:
                save_checkpoint({"results": results, "processed_keys": list(processed)})
                logger.info(f"  Checkpoint saved ({done} games)")

        except Exception as e:
            logger.error(f"  [{i+1}/{total}] {date_str} {away}@{home}: {e}")
            errors += 1
            if errors > 30:
                logger.error("Too many errors, stopping")
                break

    save_checkpoint({"results": results, "processed_keys": list(processed)})
    logger.info(f"Complete: {len(results)} results, {errors} errors")
    return results


# -- Report ---------------------------------------------------------------

def compute_metrics(df, label):
    n = len(df)
    if n < 5:
        return {"label": label, "n": n, "hit_rate": 0, "roi": 0}
    hit = df["under_hit"].values.astype(float)
    pnl = np.where(hit, (ODDS_UNDER - 1) * BASE_UNIT, -BASE_UNIT)
    roi = pnl.sum() / (n * BASE_UNIT) * 100
    return {"label": label, "n": n, "hit_rate": hit.mean() * 100, "roi": roi}


def generate_report(results):
    if not results:
        print("No results to report.")
        return

    df = pd.DataFrame(results)
    n_total = len(df)

    # Load DA data from v1
    da_lookup = load_v1_da_data()
    df["da_action"] = df["game_key"].map(lambda k: da_lookup.get(k, {}).get("da_action", "N/A"))
    df["da_conf"] = df["game_key"].map(lambda k: da_lookup.get(k, {}).get("da_conf", 0.0))
    da_available = (df["da_action"] != "N/A").sum()

    print("\n" + "=" * 90)
    print("UNDER GATE EXPERIMENT v2 -- NEUTRAL SCORER")
    print(f"Zone: [{ZONE_LO:.2f}-{ZONE_HI:.2f}) | Games: {n_total}")
    print(f"Base under rate: {df['under_hit'].mean()*100:.1f}%")
    print(f"DA data available: {da_available}/{n_total} games")
    print("=" * 90)

    # -- Scorer distribution -----------------------------------------------
    print(f"\n{'-' * 90}")
    print("SCORER DISTRIBUTION")
    print(f"{'-' * 90}")
    print(f"  predicted_total: mean={df['scorer_total'].mean():.2f}, "
          f"median={df['scorer_total'].median():.2f}")
    print(f"  probable_delta:  mean={df['scorer_delta'].mean():.2f}, "
          f"median={df['scorer_delta'].median():.2f}")
    gap = df["ou_line"] - df["scorer_total"]
    print(f"  gap (line - pred): mean={gap.mean():.2f}, median={gap.median():.2f}")

    # -- Strategy grid: gap thresholds ------------------------------------
    print(f"\n{'-' * 90}")
    print("STRATEGY 1: SIMPLE GAP (scorer_total < line - gap_min)")
    print(f"{'-' * 90}")
    print(f"  {'Gap >=':<10} {'N':>5} {'Under%':>7} {'ROI':>8}")
    print("  " + "-" * 35)
    for gap_min in [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        sub = df[gap >= gap_min]
        if len(sub) >= 5:
            m = compute_metrics(sub, "")
            marker = " <--" if m["hit_rate"] > 52.38 else ""
            print(f"  {gap_min:>+5.1f}     {m['n']:5d} {m['hit_rate']:6.1f}% {m['roi']:+7.1f}%{marker}")

    # -- Strategy grid: gap x delta ---------------------------------------
    print(f"\n{'-' * 90}")
    print("STRATEGY 2: GAP x DELTA GRID")
    print(f"{'-' * 90}")
    header = f"  {'':12}"
    for delta_max in [1.5, 2.0, 2.5, 3.0, 99]:
        label = f"d<={delta_max:.1f}" if delta_max < 99 else "d=any"
        header += f" {label:>12}"
    print(header)
    print("  " + "-" * (12 + 13 * 5))

    for gap_min in [0.0, 0.5, 1.0, 1.5, 2.0]:
        row = f"  gap>={gap_min:>+4.1f}  "
        for delta_max in [1.5, 2.0, 2.5, 3.0, 99]:
            mask = (gap >= gap_min)
            if delta_max < 99:
                mask = mask & (df["scorer_delta"] <= delta_max)
            sub = df[mask]
            if len(sub) >= 10:
                m = compute_metrics(sub, "")
                cell = f"{m['n']:3d}/{m['hit_rate']:.0f}%/{m['roi']:+.0f}%"
            elif len(sub) >= 5:
                m = compute_metrics(sub, "")
                cell = f"{m['n']:3d}/{m['hit_rate']:.0f}%"
            else:
                cell = f"{len(sub):3d}/--"
            row += f" {cell:>12}"
        print(row)

    # -- Strategy grid: conservative (pred + delta < line) ----------------
    print(f"\n{'-' * 90}")
    print("STRATEGY 3: CONSERVATIVE (predicted + delta < line)")
    print(f"{'-' * 90}")
    ceiling = df["scorer_total"] + df["scorer_delta"]
    ceiling_gap = df["ou_line"] - ceiling
    print(f"  {'Ceil gap >=':<12} {'N':>5} {'Under%':>7} {'ROI':>8}")
    print("  " + "-" * 37)
    for cg_min in [-2.0, -1.0, 0.0, 0.5, 1.0, 1.5, 2.0]:
        sub = df[ceiling_gap >= cg_min]
        if len(sub) >= 5:
            m = compute_metrics(sub, "")
            marker = " <--" if m["hit_rate"] > 52.38 else ""
            print(f"  {cg_min:>+6.1f}      {m['n']:5d} {m['hit_rate']:6.1f}% {m['roi']:+7.1f}%{marker}")

    # -- DA combo strategies (only if DA data available) ------------------
    if da_available > 0:
        print(f"\n{'-' * 90}")
        print("STRATEGY 4: SCORER + DA COMBO")
        print(f"{'-' * 90}")
        da_mask = df["da_action"] != "N/A"

        combos = [
            ("DA=UNDER (any gap)", da_mask & (df["da_action"] == "UNDER")),
            ("DA=UNDER + gap>=0.5", da_mask & (df["da_action"] == "UNDER") & (gap >= 0.5)),
            ("DA=UNDER + gap>=1.0", da_mask & (df["da_action"] == "UNDER") & (gap >= 1.0)),
            ("DA!=OVER + gap>=0.5", da_mask & (df["da_action"] != "OVER") & (gap >= 0.5)),
            ("DA!=OVER + gap>=1.0", da_mask & (df["da_action"] != "OVER") & (gap >= 1.0)),
            ("DA!=OVER + gap>=1.0 + d<=2.5",
             da_mask & (df["da_action"] != "OVER") & (gap >= 1.0) & (df["scorer_delta"] <= 2.5)),
            ("DA=UNDER + gap>=0.5 + d<=2.5",
             da_mask & (df["da_action"] == "UNDER") & (gap >= 0.5) & (df["scorer_delta"] <= 2.5)),
        ]

        print(f"  {'Strategy':<38} {'N':>5} {'Under%':>7} {'ROI':>8}")
        print("  " + "-" * 62)
        for label, mask in combos:
            sub = df[mask]
            if len(sub) >= 5:
                m = compute_metrics(sub, "")
                marker = " <--" if m["hit_rate"] > 52.38 else ""
                print(f"  {label:<38} {m['n']:5d} {m['hit_rate']:6.1f}% {m['roi']:+7.1f}%{marker}")
            else:
                print(f"  {label:<38} {len(sub):5d}   (too few)")

    # -- Per-season best strategies ---------------------------------------
    print(f"\n{'-' * 90}")
    print("PER-SEASON: gap >= 1.0")
    print(f"{'-' * 90}")
    sub = df[gap >= 1.0]
    if not sub.empty:
        for s in sorted(sub["season"].unique()):
            sy = sub[sub["season"] == s]
            m = compute_metrics(sy, str(s))
            if m["n"] >= 5:
                print(f"  {s}: {m['n']} games, {m['hit_rate']:.1f}% hit, {m['roi']:+.1f}% ROI")

    # -- Delta distribution -----------------------------------------------
    print(f"\n{'-' * 90}")
    print("DELTA DISTRIBUTION")
    print(f"{'-' * 90}")
    for lo, hi in [(0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 99)]:
        sub = df[(df["scorer_delta"] >= lo) & (df["scorer_delta"] < hi)]
        if len(sub) >= 5:
            m = compute_metrics(sub, "")
            label = f"delta [{lo:.1f}-{hi:.1f})" if hi < 99 else f"delta >= {lo:.1f}"
            print(f"  {label:<20}: {m['n']:4d} games, under={m['hit_rate']:.1f}%, ROI={m['roi']:+.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--limit", type=int, default=0, help="Limit scope to first N games")
    parser.add_argument("--checkpoint-suffix", default="", help="Suffix for checkpoint filename")
    args = parser.parse_args()

    _set_checkpoint(args.checkpoint_suffix or None)

    if args.report_only:
        checkpoint = load_checkpoint()
        generate_report(checkpoint["results"])
        return

    print("=" * 90)
    print(f"UNDER GATE EXPERIMENT v2 -- NEUTRAL SCORER")
    print(f"Zone: [{ZONE_LO:.2f}-{ZONE_HI:.2f}) | Model: {args.model}")
    print("=" * 90)

    preds, enriched_lookup = build_predictions()

    scope = preds[
        (preds["season"].isin(TARGET_SEASONS))
        & (preds["p_under"] >= ZONE_LO)
        & (preds["p_under"] < ZONE_HI)
    ].copy()

    if args.limit and args.limit > 0:
        scope = scope.head(args.limit).copy()
        print(f"\n[LIMIT] scope sliced to first {args.limit} games")

    print(f"\nScope: {len(scope)} games in zone [{ZONE_LO}-{ZONE_HI})")
    print(f"Checkpoint: {CHECKPOINT_PATH.name}")
    print(f"Under rate: {scope['under_hit'].mean()*100:.1f}%")
    est_cost = len(scope) * 0.008  # gpt-5.4 ~$0.008/call
    print(f"Estimated cost: ${est_cost:.2f} ({len(scope)} games x ~$0.008)")

    if args.dry_run:
        print("\n[DRY RUN] Would process above games. Exiting.")
        return

    results = run_experiment(scope, enriched_lookup, args.model, args.resume)
    generate_report(results)


if __name__ == "__main__":
    main()
