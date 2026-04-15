"""UNDER LLM Gate Experiment: Expert vs Devil's Advocate.

3 LLM calls per game (Analyst, Expert, DA), 2 flows from the same data:
  Flow A: Expert Solo (Analyst + Expert, ignore DA)
  Flow B: Expert vs DA (Analyst + Expert + DA arbitrage)

Usage:
    python scripts/run_under_gate_experiment.py --dry-run
    python scripts/run_under_gate_experiment.py --model gpt-5.4-mini
    python scripts/run_under_gate_experiment.py --resume
    python scripts/run_under_gate_experiment.py --report-only
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
from src.feature_card import OUAnalystCard, OUFeatureCard
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.llm_expert import Genome, LLMAnalyst, LLMExpert
from src.model import UnderModelConfig, walk_forward_splits, train_under_model, predict_under_proba

GENOMES_DIR = Path(__file__).resolve().parent.parent / "genomes"
CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "picks" / "_under_gate_experiment.json"
ODDS_UNDER = 1.909
BASE_UNIT = 100

TARGET_SEASONS = [2021, 2022, 2023, 2024, 2025]
ZONE_LO = 0.52
ZONE_HI = 0.53

ZONE_CONTEXT_EXPERT = (
    "These games are in the ML model's UNCERTAINTY ZONE — P(under) is 52-53%, "
    "barely above coin flip. The model sees a slight statistical lean toward "
    "UNDER but is not confident. Historical hit rate in this zone is around 46%.\n\n"
    "Your job: read the matchup carefully and decide if there's a genuine "
    "structural reason for a low-scoring game. If you can't find a clear "
    "edge — PASS. In this zone, PASS is often the right call.\n\n"
    "Standard O/U odds are -110 (breakeven 52.38%)."
)

ZONE_CONTEXT_DA = (
    "An UNDER expert is also analyzing this game. Your role is to find the "
    "OVER case — reasons why this game might produce MORE runs than the line. "
    "If the UNDER case looks solid to you, say PASS (you're not finding "
    "counter-arguments). If you see genuine vulnerability in the UNDER "
    "thesis — say OVER and explain why.\n\n"
    "Be specific: name the matchup, the tired arm, the hot lineup. "
    "Generic concerns don't count.\n\n"
    "Standard O/U odds are -110 (breakeven 52.38%)."
)


def load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return {"results": [], "processed_keys": []}


def save_checkpoint(data: dict):
    CHECKPOINT_PATH.parent.mkdir(exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(data, indent=2, default=str))


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


# -- Arbitration ----------------------------------------------------------

def arbitrate_flow_a(expert_verdict, scenario, close_ou):
    """Flow A: Expert Solo."""
    if expert_verdict.action != "UNDER" or expert_verdict.confidence < 0.60:
        return "PASS", 0.0, 0.0

    confidence = expert_verdict.confidence

    if scenario and close_ou > 0:
        if scenario.predicted_total > close_ou + 1.5:
            if expert_verdict.confidence >= 0.75:
                confidence *= 0.80
            else:
                return "PASS", 0.0, 0.0
        elif scenario.predicted_total < close_ou:
            confidence = min(confidence * 1.10, 0.95)

    return "UNDER", confidence, 1.0


def arbitrate_flow_b(expert_verdict, da_verdict, scenario, close_ou):
    """Flow B: Expert vs Devil's Advocate."""
    if expert_verdict.action != "UNDER":
        return "PASS", 0.0, 0.0

    if da_verdict.action != "OVER":
        confidence = expert_verdict.confidence
        stake = 1.0
    else:
        if expert_verdict.confidence > da_verdict.confidence + 0.10:
            confidence = expert_verdict.confidence * 0.7
            stake = 0.5
        else:
            return "PASS", 0.0, 0.0

    if scenario and close_ou > 0:
        if scenario.predicted_total > close_ou + 1.5:
            if expert_verdict.confidence >= 0.75:
                confidence *= 0.80
            else:
                return "PASS", 0.0, 0.0
        elif scenario.predicted_total < close_ou:
            confidence = min(confidence * 1.10, 0.95)

    action = "UNDER" if stake == 1.0 else "LEAN_UNDER"
    return action, confidence, stake


# -- Main Loop ------------------------------------------------------------

def run_experiment(scope, enriched_lookup, model, resume):
    """Run 3 LLM calls per game: Analyst, Expert, DA."""
    analyst_genome = Genome.load(GENOMES_DIR / "ou_analyst_v1.yaml")
    expert_genome = Genome.load(GENOMES_DIR / "ou_gatekeeper_v1.yaml")
    da_genome = Genome.load(GENOMES_DIR / "ou_devils_advocate_v1.yaml")

    analyst = LLMAnalyst(analyst_genome, model=model)
    expert = LLMExpert(expert_genome, model=model)
    devil = LLMExpert(da_genome, model=model)

    checkpoint = load_checkpoint() if resume else {"results": [], "processed_keys": []}
    processed = set(checkpoint["processed_keys"])
    results = checkpoint["results"]

    logger.info(f"Checkpoint: {len(processed)} done, {len(scope) - len(processed)} remaining")

    total = len(scope)
    errors = 0

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
            # 1. Analyst scenario
            analyst_card = OUAnalystCard.from_row(game_row)
            scenario = analyst.predict_ou(analyst_card)

            # 2. Build expert card with scenario injected
            betting_card = OUFeatureCard.from_row(game_row, p_under=p_u)
            expert_card_text = (
                betting_card.prompt_text
                + "\n\n-- Analyst Scoring Scenario --\n"
                + scenario.to_text()
            )
            expert_card = OUFeatureCard(game_id=betting_card.game_id,
                                         prompt_text=expert_card_text)

            # 3. Expert verdict
            expert_verdict = expert.analyze_ou(expert_card, zone_context=ZONE_CONTEXT_EXPERT)

            # 4. DA verdict (same card)
            da_verdict = devil.analyze_ou(expert_card, zone_context=ZONE_CONTEXT_DA)

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
                # Analyst
                "analyst_total": round(scenario.predicted_total, 1),
                "analyst_pattern": scenario.scoring_pattern,
                "analyst_narrative": scenario.key_narrative,
                "analyst_factors": scenario.decisive_factors,
                # Expert
                "expert_action": expert_verdict.action,
                "expert_conf": round(expert_verdict.confidence, 3),
                "expert_total": round(expert_verdict.predicted_total, 1),
                "expert_reasoning": expert_verdict.reasoning,
                "expert_factors": expert_verdict.key_factors,
                "expert_risks": expert_verdict.risk_flags,
                # DA
                "da_action": da_verdict.action,
                "da_conf": round(da_verdict.confidence, 3),
                "da_total": round(da_verdict.predicted_total, 1),
                "da_reasoning": da_verdict.reasoning,
                "da_factors": da_verdict.key_factors,
                "da_risks": da_verdict.risk_flags,
            }
            results.append(result)
            processed.add(game_key)

            done = len(processed)
            hit_str = "U" if game["under_hit"] else "O"
            logger.info(
                f"  [{done}/{total}] {date_str} {away}@{home} "
                f"p={p_u:.3f} ou={ou_line:.1f} actual={hit_str} | "
                f"expert={expert_verdict.action}({expert_verdict.confidence:.2f}) "
                f"da={da_verdict.action}({da_verdict.confidence:.2f}) "
                f"analyst={scenario.predicted_total:.1f}"
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

    print("\n" + "=" * 90)
    print("UNDER GATE EXPERIMENT — RESULTS")
    print(f"Zone: [{ZONE_LO:.2f}-{ZONE_HI:.2f}) | Games: {n_total}")
    print(f"Base under rate: {df['under_hit'].mean()*100:.1f}%")
    print("=" * 90)

    # -- Flow A: Expert Solo ------------------------------------------
    print(f"\n{'-' * 90}")
    print("FLOW A: Expert Solo (Analyst + Expert, DA ignored)")
    print(f"{'-' * 90}")

    flow_a_bets = []
    flow_a_pass = []
    for _, r in df.iterrows():
        from types import SimpleNamespace
        ev = SimpleNamespace(action=r["expert_action"], confidence=r["expert_conf"])
        sc = SimpleNamespace(predicted_total=r["analyst_total"]) if r["analyst_total"] > 0 else None
        action, conf, stake = arbitrate_flow_a(ev, sc, r["ou_line"])
        if action != "PASS":
            flow_a_bets.append(r)
        else:
            flow_a_pass.append(r)

    bets_a = pd.DataFrame(flow_a_bets) if flow_a_bets else pd.DataFrame()
    pass_a = pd.DataFrame(flow_a_pass) if flow_a_pass else pd.DataFrame()

    print(f"\n  {'Category':<30} {'N':>5} {'Under%':>7} {'ROI':>8}")
    print("  " + "-" * 55)
    for label, sub in [("ALL (unfiltered)", df), ("BET (filtered)", bets_a), ("PASS (rejected)", pass_a)]:
        m = compute_metrics(sub, label)
        print(f"  {m['label']:<30} {m['n']:5d} {m['hit_rate']:6.1f}% {m['roi']:+7.1f}%")

    if len(bets_a) > 0 and len(pass_a) > 0:
        sep = compute_metrics(bets_a, "")["hit_rate"] - compute_metrics(pass_a, "")["hit_rate"]
        fr = len(bets_a) / n_total * 100
        print(f"\n  Filter rate: {fr:.1f}% | Separation: {sep:+.1f}pp")

    # -- Flow B: Expert vs DA -----------------------------------------
    print(f"\n{'-' * 90}")
    print("FLOW B: Expert vs Devil's Advocate")
    print(f"{'-' * 90}")

    flow_b_bets = []
    flow_b_pass = []
    for _, r in df.iterrows():
        ev = SimpleNamespace(action=r["expert_action"], confidence=r["expert_conf"])
        dv = SimpleNamespace(action=r["da_action"], confidence=r["da_conf"])
        sc = SimpleNamespace(predicted_total=r["analyst_total"]) if r["analyst_total"] > 0 else None
        action, conf, stake = arbitrate_flow_b(ev, dv, sc, r["ou_line"])
        if action != "PASS":
            flow_b_bets.append(r)
        else:
            flow_b_pass.append(r)

    bets_b = pd.DataFrame(flow_b_bets) if flow_b_bets else pd.DataFrame()
    pass_b = pd.DataFrame(flow_b_pass) if flow_b_pass else pd.DataFrame()

    print(f"\n  {'Category':<30} {'N':>5} {'Under%':>7} {'ROI':>8}")
    print("  " + "-" * 55)
    for label, sub in [("ALL (unfiltered)", df), ("BET (filtered)", bets_b), ("PASS (rejected)", pass_b)]:
        m = compute_metrics(sub, label)
        print(f"  {m['label']:<30} {m['n']:5d} {m['hit_rate']:6.1f}% {m['roi']:+7.1f}%")

    if len(bets_b) > 0 and len(pass_b) > 0:
        sep = compute_metrics(bets_b, "")["hit_rate"] - compute_metrics(pass_b, "")["hit_rate"]
        fr = len(bets_b) / n_total * 100
        print(f"\n  Filter rate: {fr:.1f}% | Separation: {sep:+.1f}pp")

    # -- DA Impact ----------------------------------------------------
    print(f"\n{'-' * 90}")
    print("DA IMPACT ANALYSIS")
    print(f"{'-' * 90}")

    da_saves = 0
    da_false_alarms = 0
    da_agreed = 0
    for _, r in df.iterrows():
        ev = SimpleNamespace(action=r["expert_action"], confidence=r["expert_conf"])
        dv = SimpleNamespace(action=r["da_action"], confidence=r["da_conf"])
        sc = SimpleNamespace(predicted_total=r["analyst_total"]) if r["analyst_total"] > 0 else None

        a_action, _, _ = arbitrate_flow_a(ev, sc, r["ou_line"])
        b_action, _, _ = arbitrate_flow_b(ev, dv, sc, r["ou_line"])

        if a_action != "PASS" and b_action == "PASS":
            # DA caused a rejection
            if not r["under_hit"]:
                da_saves += 1  # DA was right to block
            else:
                da_false_alarms += 1  # DA wrongly blocked a winner
        elif a_action != "PASS" and b_action != "PASS":
            da_agreed += 1

    print(f"  DA saves (blocked OVER correctly): {da_saves}")
    print(f"  DA false alarms (blocked UNDER incorrectly): {da_false_alarms}")
    print(f"  DA agreed with Expert: {da_agreed}")
    if da_saves + da_false_alarms > 0:
        da_precision = da_saves / (da_saves + da_false_alarms) * 100
        print(f"  DA precision: {da_precision:.1f}% (saves / (saves + false alarms))")

    # -- Expert Action Distribution -----------------------------------
    print(f"\n{'-' * 90}")
    print("EXPERT ACTION DISTRIBUTION")
    print(f"{'-' * 90}")
    for action in ["UNDER", "OVER", "PASS"]:
        sub = df[df["expert_action"] == action]
        n = len(sub)
        ur = sub["under_hit"].mean() * 100 if n > 0 else 0
        print(f"  Expert={action:<7}: {n:4d} games ({n/n_total*100:5.1f}%), under_rate={ur:.1f}%")

    print(f"\n{'-' * 90}")
    print("DA ACTION DISTRIBUTION")
    print(f"{'-' * 90}")
    for action in ["UNDER", "OVER", "PASS"]:
        sub = df[df["da_action"] == action]
        n = len(sub)
        ur = sub["under_hit"].mean() * 100 if n > 0 else 0
        print(f"  DA={action:<7}: {n:4d} games ({n/n_total*100:5.1f}%), under_rate={ur:.1f}%")

    # -- Per Season ---------------------------------------------------
    print(f"\n{'-' * 90}")
    print("PER-SEASON FLOW A RESULTS")
    print(f"{'-' * 90}")
    if not bets_a.empty:
        for s in sorted(bets_a["season"].unique()):
            sy = bets_a[bets_a["season"] == s]
            m = compute_metrics(sy, str(s))
            print(f"  {s}: {m['n']} bets, {m['hit_rate']:.1f}% hit, {m['roi']:+.1f}% ROI")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--model", default="gpt-5.4-mini")
    args = parser.parse_args()

    if args.report_only:
        checkpoint = load_checkpoint()
        generate_report(checkpoint["results"])
        return

    print("=" * 90)
    print(f"UNDER GATE EXPERIMENT — Zone [{ZONE_LO:.2f}-{ZONE_HI:.2f})")
    print(f"Model: {args.model}")
    print("=" * 90)

    preds, enriched_lookup = build_predictions()

    scope = preds[
        (preds["season"].isin(TARGET_SEASONS))
        & (preds["p_under"] >= ZONE_LO)
        & (preds["p_under"] < ZONE_HI)
    ].copy()

    print(f"\nScope: {len(scope)} games in zone [{ZONE_LO}-{ZONE_HI})")
    print(f"Under rate: {scope['under_hit'].mean()*100:.1f}%")
    est_cost = len(scope) * 3 * 0.001
    print(f"Estimated cost: ${est_cost:.2f} (3 calls x {len(scope)} games x ~$0.001)")

    if args.dry_run:
        print("\n--dry-run: stopping before LLM calls.")

        # Per-season breakdown
        for s in TARGET_SEASONS:
            sy = scope[scope["season"] == s]
            ur = sy["under_hit"].mean() * 100 if len(sy) > 0 else 0
            print(f"  {s}: {len(sy)} games, under={ur:.1f}%")
        return

    results = run_experiment(scope, enriched_lookup, model=args.model, resume=args.resume)
    generate_report(results)


if __name__ == "__main__":
    main()
