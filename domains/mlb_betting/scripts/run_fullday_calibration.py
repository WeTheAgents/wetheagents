"""Run LLM expert duel on a full day's MLB slate.

Extends run_6game_calibration.py from hand-picked games to automatic
date-based selection with zone auto-assignment (CF / S3 / RL).

Usage:
    python scripts/run_fullday_calibration.py --date 2024-07-15 --dry-run
    python scripts/run_fullday_calibration.py --date 2024-07-15
    python scripts/run_fullday_calibration.py --date 2024-07-15 --model gpt-5.4

Good test dates (mid-season, full slates, 14-15 games):
    2024-06-01, 2024-06-15, 2024-07-05, 2024-08-05, 2023-08-01
Data covers Mar-Aug only (no September). All-Star break mid-July has no games.
"""

import sys
import json
import warnings
import logging
import argparse
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
GENOMES_DIR = BASE_DIR / "genomes"
RESULTS_DIR = BASE_DIR / "knowledge" / "fullday_tests"

# Fallback run line odds when real RL odds unavailable
RL_FALLBACK_ODDS = 1.87
BASE_UNIT = 100  # dollars per unit

# Our team codes → ESPN abbreviations
_TEAM_TO_ESPN = {
    "TAM": "TB", "KAN": "KC", "SDG": "SD", "SFO": "SF",
    "CWS": "CHW", "CUB": "CHC", "WAS": "WSH",
}


# ── ESPN box score links ──────────────────────────────────────────────────

def fetch_espn_boxscore_urls(date_str: str) -> dict[str, str]:
    """Fetch ESPN game IDs for a date and return {matchup_key: box_score_url}.

    matchup_key = "AWAY@HOME" using our team codes (e.g. "PHI@BAL").
    """
    date_compact = date_str.replace("-", "")
    api_url = (
        f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
        f"scoreboard?dates={date_compact}"
    )
    espn_to_ours = {v: k for k, v in _TEAM_TO_ESPN.items()}

    try:
        with urlopen(api_url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning(f"ESPN API fetch failed: {e}")
        return {}

    urls = {}
    for event in data.get("events", []):
        game_id = event.get("id", "")
        competitors = event.get("competitions", [{}])[0].get("competitors", [])
        if len(competitors) != 2:
            continue
        teams = {}
        for c in competitors:
            abbr = c.get("team", {}).get("abbreviation", "")
            home_away = c.get("homeAway", "")
            # Map ESPN abbr back to our codes
            our_code = espn_to_ours.get(abbr, abbr)
            teams[home_away] = our_code
        away = teams.get("away", "")
        home = teams.get("home", "")
        if away and home and game_id:
            key = f"{away}@{home}"
            urls[key] = f"https://www.espn.com/mlb/boxscore/_/gameId/{game_id}"

    logger.info(f"ESPN: fetched {len(urls)} box score URLs for {date_str}")
    return urls


# ── Data pipeline ─────────────────────────────────────────────────────────

def build_enriched_fullday(date_str: str) -> pd.DataFrame:
    """Build enriched DataFrame for a single date, including CF games.

    Pipeline:
    1. load_all_seasons → apply_data_filters → add_derived_odds
    2. build_all_features (ALL games, including CF)
    3. build_spec_features(enriched=...) (drops CF/April for model training)
    4. run_walk_forward → compute_divergence (model predictions)
    5. LEFT MERGE predictions back onto full enriched data
    6. Filter to target date
    """
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import SPEC_FEATURES, build_all_features, build_spec_features
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    target_season = int(date_str[:4])

    # Step 1-2: Full enriched data (keeps CF games)
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building all features (team + pitcher + Retrosheet)...")
    enriched = build_all_features(games)

    # Step 3: Spec features for model (drops CF/April/extreme)
    logger.info("Building spec features (for model training)...")
    spec = build_spec_features(enriched=enriched)

    features_available = [
        f for f in SPEC_FEATURES if f in spec.columns and spec[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()

    # Step 4: Walk-forward model
    logger.info("Running walk-forward model...")
    fold_results = run_walk_forward(spec, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    # Step 5: Merge predictions back onto full enriched data
    merge_keys = ["season", "date", "home_team", "away_team"]
    pred_cols = [c for c in div.columns if c.startswith("pred_M")]
    div_subset = div[merge_keys + pred_cols + ["closing_decimal_odds_favorite"]].copy()
    div_subset = div_subset.drop_duplicates(subset=merge_keys, keep="first")

    df = enriched.merge(div_subset, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # Consensus prediction and edge (NaN for CF games — expected)
    available_pred = [c for c in df.columns if c.startswith("pred_M")]
    if available_pred:
        df["pred_consensus"] = df[available_pred].mean(axis=1)
        df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]

    # Favorite identification (needed for zone assignment)
    if "home_implied_prob" in df.columns and "away_implied_prob" in df.columns:
        df["fav_is_home"] = df["home_implied_prob"] > df["away_implied_prob"]

    # Step 6: Filter to target date
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    target_date = pd.Timestamp(date_str)
    day_df = df[df["date"] == target_date].copy()

    logger.info(f"Date {date_str}: {len(day_df)} games found")
    return day_df


# ── Pre-filter and zone assignment ────────────────────────────────────────

def apply_broad_filter(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove obvious junk. Keep the filter broad — experts decide BET/PASS.

    Removes: Colorado, extreme lines (>300), missing pitcher/odds.
    Keeps: September (broad per design).
    """
    n_before = len(df)
    reasons = {}

    mask = pd.Series(True, index=df.index)

    if "involves_col" in df.columns:
        col_mask = df["involves_col"]
        reasons["Colorado"] = int(col_mask.sum())
        mask &= ~col_mask

    if "is_extreme_line" in df.columns:
        ext_mask = df["is_extreme_line"]
        reasons["extreme_line"] = int(ext_mask.sum())
        mask &= ~ext_mask

    # Missing pitcher
    pitcher_mask = df["home_pitcher"].isna() | df["away_pitcher"].isna()
    reasons["missing_pitcher"] = int(pitcher_mask.sum())
    mask &= ~pitcher_mask

    # Missing odds
    odds_mask = df["home_close_ml"].isna() | df["away_close_ml"].isna()
    reasons["missing_odds"] = int(odds_mask.sum())
    mask &= ~odds_mask

    result = df[mask].copy()
    reasons["total_removed"] = n_before - len(result)
    logger.info(f"Broad filter: {n_before} -> {len(result)} games (removed: {reasons})")
    return result, reasons


def assign_zones(df: pd.DataFrame) -> pd.DataFrame:
    """Auto-assign zone to each game.

    Priority:
    1. CF_pickem: is_coinflip (odds spread <= 4%)
    2. Away underdog (fav_is_home):
       - edge_consensus < 0 → S3_expansion (dog underpriced on ML)
       - edge_consensus >= 0 → RL_expansion (fav overpriced, spread play)
       - edge_consensus NaN: away_decimal_odds >= 2.30 → S3, else RL
    3. Home underdog: SKIP
    """
    zones = []
    for _, row in df.iterrows():
        # CF takes priority
        if row.get("is_coinflip", False):
            zones.append("CF_pickem")
            continue

        # Away underdog games only
        fav_is_home = row.get("fav_is_home", True)
        if not fav_is_home:
            zones.append("SKIP")
            continue

        # S3 vs RL based on edge_consensus
        edge = row.get("edge_consensus", np.nan)
        if pd.notna(edge):
            if edge < 0:
                zones.append("S3_expansion")
            else:
                zones.append("RL_expansion")
        else:
            # Fallback: odds-based
            away_odds = row.get("away_decimal_odds", 2.0)
            if away_odds >= 2.30:
                zones.append("S3_expansion")
            else:
                zones.append("RL_expansion")

    df = df.copy()
    df["zone"] = zones

    # Log distribution
    dist = df["zone"].value_counts().to_dict()
    logger.info(f"Zone assignment: {dist}")
    return df


# ── P&L scoring ───────────────────────────────────────────────────────────

def compute_game_pnl(duel_result, row: pd.Series, zone: str) -> dict:
    """Compute P&L for a single game based on duel result and actuals.

    Returns dict with: pnl, won, odds_used, stake, bet_placed
    """
    stake = duel_result.stake_multiplier
    if stake == 0:
        return {"pnl": 0.0, "won": None, "odds_used": 0.0,
                "stake": 0.0, "bet_placed": False}

    home_win = bool(row.get("home_win", 0))
    home_final = int(row.get("home_final", 0))
    away_final = int(row.get("away_final", 0))
    margin = home_final - away_final  # positive = home won

    if zone == "CF_pickem":
        target = duel_result.target_side
        if not target:
            return {"pnl": 0.0, "won": None, "odds_used": 0.0,
                    "stake": 0.0, "bet_placed": False}
        if target == "home":
            won = home_win
            odds = float(row.get("home_decimal_odds", 2.0))
        else:
            won = not home_win
            odds = float(row.get("away_decimal_odds", 2.0))

    elif zone == "S3_expansion":
        # Away ML: dog wins outright
        won = not home_win
        odds = float(row.get("away_decimal_odds", 2.0))

    elif zone == "RL_expansion":
        # Away +1.5: dog wins OR loses by exactly 1
        won = margin <= 1  # home margin <= 1 means away covers +1.5
        # Use real RL odds if available, else fallback
        rl_odds_raw = row.get("away_run_line_odds", np.nan)
        if pd.notna(rl_odds_raw):
            from src.data_loader import american_to_decimal
            odds = american_to_decimal(float(rl_odds_raw))
        else:
            odds = RL_FALLBACK_ODDS
    else:
        return {"pnl": 0.0, "won": None, "odds_used": 0.0,
                "stake": 0.0, "bet_placed": False}

    if won:
        pnl = (odds - 1) * stake * BASE_UNIT
    else:
        pnl = -stake * BASE_UNIT

    return {"pnl": round(pnl, 2), "won": won, "odds_used": round(odds, 3),
            "stake": stake, "bet_placed": True}


# ── Duel runner ───────────────────────────────────────────────────────────

def run_fullday(day_df: pd.DataFrame, *, dry_run=False,
                provider="openai", model="gpt-5.4") -> list[dict]:
    """Run analyst + duel on each game. Returns list of result dicts."""
    from src.feature_card import AnalystCard, FeatureCard
    from src.llm_expert import Genome, LLMAnalyst, LLMExpert
    from src.llm_duel import DuelEngine

    genome_a = Genome.load(GENOMES_DIR / "momentum_v1.yaml")
    genome_b = Genome.load(GENOMES_DIR / "value_v1.yaml")
    genome_analyst = Genome.load(GENOMES_DIR / "analyst_v1.yaml")

    results = []
    bettable = day_df[day_df["zone"] != "SKIP"].copy()

    for i, (idx, row) in enumerate(bettable.iterrows()):
        zone = row["zone"]
        away = row["away_team"]
        home = row["home_team"]
        game_label = f"{away} @ {home}"

        logger.info(f"\n{'=' * 60}")
        logger.info(f"[{i + 1}/{len(bettable)}] {game_label} | Zone: {zone}")
        logger.info(f"{'=' * 60}")

        card = FeatureCard.from_row(row, zone)
        analyst_card = AnalystCard.from_row(row)

        if dry_run:
            results.append({
                "row": row,
                "zone": zone,
                "label": game_label,
                "analyst_card": analyst_card.to_prompt(),
                "betting_card": card.to_prompt(),
                "duel_result": None,
                "scenario": None,
                "pnl_info": None,
            })
            continue

        expert_a = LLMExpert(genome_a, provider=provider, model=model)
        expert_b = LLMExpert(genome_b, provider=provider, model=model)
        analyst = LLMAnalyst(genome_analyst, provider=provider, model=model)
        duel = DuelEngine(expert_a, expert_b, analyst=analyst)

        duel_result = duel.run(card, analyst_card=analyst_card)
        pnl_info = compute_game_pnl(duel_result, row, zone)

        results.append({
            "row": row,
            "zone": zone,
            "label": game_label,
            "analyst_card": analyst_card.to_prompt(),
            "betting_card": card.to_prompt(),
            "scenario": duel_result.scenario,
            "duel_result": duel_result,
            "pnl_info": pnl_info,
        })

    return results


# ── Report writer ─────────────────────────────────────────────────────────

def write_fullday_report(results: list[dict], date_str: str, *,
                         dry_run=False, filter_stats: dict | None = None,
                         total_games: int = 0, skipped: int = 0,
                         espn_urls: dict[str, str] | None = None):
    """Write detailed markdown report with per-game details and zone summaries."""
    report_path = RESULTS_DIR / f"fullday_{date_str}.md"
    lines = [
        f"# Full-Day LLM Calibration — {date_str}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Mode: {'DRY RUN (cards only)' if dry_run else 'FULL (API calls)'}",
        "",
    ]

    # Slate overview
    zone_dist = {}
    for r in results:
        z = r["zone"]
        zone_dist[z] = zone_dist.get(z, 0) + 1

    lines.append("## Slate Overview")
    lines.append("")
    lines.append(f"- Total games on date: {total_games}")
    if filter_stats:
        removed = filter_stats.get("total_removed", 0)
        lines.append(f"- After broad filter: {total_games - removed} "
                      f"(removed: {', '.join(f'{k}={v}' for k, v in filter_stats.items() if k != 'total_removed' and v > 0)})")
    lines.append(f"- Skipped (home underdog): {skipped}")
    lines.append(f"- Bettable games: {len(results)}")
    lines.append(f"- Zone distribution: {', '.join(f'{k}={v}' for k, v in sorted(zone_dist.items()))}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-game details
    lines.append("## Per-Game Details")
    lines.append("")

    for i, r in enumerate(results):
        row = r["row"]
        zone = r["zone"]
        label = r["label"]
        home_final = int(row.get("home_final", 0))
        away_final = int(row.get("away_final", 0))
        home_win = bool(row.get("home_win", 0))
        winner = "home" if home_win else "away"
        margin = home_final - away_final

        # ESPN box score link
        matchup_key = f"{row['away_team']}@{row['home_team']}"
        espn_link = (espn_urls or {}).get(matchup_key, "")
        espn_str = f" | [ESPN Box Score]({espn_link})" if espn_link else ""

        lines.append(f"### Game {i + 1}: {label} | Zone: {zone}{espn_str}")
        lines.append("")
        lines.append(f"**Final score:** {row['away_team']} {away_final} - "
                      f"{row['home_team']} {home_final} "
                      f"({winner} wins by {abs(margin)})")
        lines.append("")

        # Analyst card
        lines.append("<details><summary>Analyst Card</summary>")
        lines.append("")
        lines.append("```")
        lines.append(r["analyst_card"])
        lines.append("```")
        lines.append("</details>")
        lines.append("")

        # Betting card
        lines.append("<details><summary>Betting Card</summary>")
        lines.append("")
        lines.append("```")
        lines.append(r["betting_card"])
        lines.append("```")
        lines.append("</details>")
        lines.append("")

        if dry_run:
            lines.append("*Dry run — no API calls made.*")
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        dr = r["duel_result"]
        scenario = r["scenario"]
        pnl_info = r["pnl_info"]

        # Analyst scenario
        if scenario:
            lines.append("**Analyst Scenario:**")
            lines.append(f"- Predicted winner: {scenario.predicted_winner} "
                          f"({scenario.winner_confidence:.0%})")
            lines.append(f"- Predicted score: {scenario.predicted_score}")
            lines.append(f"- Tightness: {scenario.tightness}")
            lines.append(f"- Narrative: {scenario.key_narrative}")
            lines.append("")

        # Expert verdicts
        for name, v in [("Momentum", dr.verdict_a), ("Value", dr.verdict_b)]:
            lines.append(f"**{name}:** {v.action} ({v.confidence:.2f})")
            lines.append(f"- Factors: {'; '.join(v.key_factors[:3])}")
            lines.append(f"- Risks: {'; '.join(v.risk_flags[:2])}")
            lines.append("")

        # Arbiter
        arbiter_line = f"**Arbiter:** {dr.final_action}"
        if zone == "CF_pickem" and dr.target_side:
            arbiter_line += f" ({dr.target_side})"
        arbiter_line += f" | conf={dr.combined_confidence:.3f} | stake={dr.stake_multiplier}x"
        lines.append(arbiter_line)
        lines.append("")

        # Outcome
        if pnl_info and pnl_info["bet_placed"]:
            result_str = "WIN" if pnl_info["won"] else "LOSS"
            lines.append(f"**Outcome:** {result_str} | "
                          f"P&L: ${pnl_info['pnl']:+.0f} "
                          f"(odds {pnl_info['odds_used']:.3f}, "
                          f"stake {pnl_info['stake']}x)")
        else:
            lines.append("**Outcome:** PASS (no bet placed)")
        lines.append("")
        lines.append("---")
        lines.append("")

    if dry_run:
        report = "\n".join(lines)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        logger.info(f"\nDry-run report saved: {report_path}")
        return

    # Zone summary tables
    lines.append("## Zone Summaries")
    lines.append("")

    for zone_name in ["CF_pickem", "S3_expansion", "RL_expansion"]:
        zone_results = [r for r in results if r["zone"] == zone_name]
        if not zone_results:
            continue

        lines.append(f"### {zone_name}")
        lines.append("")

        if zone_name == "CF_pickem":
            lines.append("| Game | Analyst | Momentum | Value | Arbiter (side) | Winner | P&L |")
            lines.append("|------|---------|----------|-------|----------------|--------|-----|")
            for r in zone_results:
                dr = r["duel_result"]
                sc = r["scenario"]
                pnl = r["pnl_info"]
                analyst_call = sc.predicted_winner if sc else "N/A"
                side_str = dr.target_side or "-"
                winner = "home" if bool(r["row"].get("home_win", 0)) else "away"
                pnl_str = f"${pnl['pnl']:+.0f}" if pnl["bet_placed"] else "-"
                lines.append(
                    f"| {r['label']} | {analyst_call} | "
                    f"{dr.verdict_a.action} ({dr.verdict_a.confidence:.2f}) | "
                    f"{dr.verdict_b.action} ({dr.verdict_b.confidence:.2f}) | "
                    f"{dr.final_action} ({side_str}) | {winner} | {pnl_str} |"
                )
        else:
            win_col = "Dog Won?" if zone_name == "S3_expansion" else "Dog Covered?"
            lines.append(f"| Game | Analyst | Momentum | Value | Arbiter | {win_col} | P&L |")
            lines.append("|------|---------|----------|-------|---------|----------|-----|")
            for r in zone_results:
                dr = r["duel_result"]
                sc = r["scenario"]
                pnl = r["pnl_info"]
                analyst_call = sc.predicted_winner if sc else "N/A"
                if zone_name == "S3_expansion":
                    actual = "Yes" if not bool(r["row"].get("home_win", 0)) else "No"
                else:
                    margin = int(r["row"].get("home_final", 0)) - int(r["row"].get("away_final", 0))
                    actual = "Yes" if margin <= 1 else "No"
                pnl_str = f"${pnl['pnl']:+.0f}" if pnl["bet_placed"] else "-"
                lines.append(
                    f"| {r['label']} | {analyst_call} | "
                    f"{dr.verdict_a.action} ({dr.verdict_a.confidence:.2f}) | "
                    f"{dr.verdict_b.action} ({dr.verdict_b.confidence:.2f}) | "
                    f"{dr.final_action} | {actual} | {pnl_str} |"
                )

        # Zone totals
        zone_bets = [r for r in zone_results if r["pnl_info"]["bet_placed"]]
        zone_wins = sum(1 for r in zone_bets if r["pnl_info"]["won"])
        zone_pnl = sum(r["pnl_info"]["pnl"] for r in zone_bets)
        lines.append("")
        lines.append(f"**{zone_name} totals:** {len(zone_results)} games, "
                      f"{len(zone_bets)} bets, "
                      f"{zone_wins}/{len(zone_bets)} wins, "
                      f"P&L: ${zone_pnl:+.0f}")
        lines.append("")

    # Overall calibration metrics
    lines.append("## Calibration Metrics")
    lines.append("")

    all_bets = [r for r in results if r["pnl_info"] and r["pnl_info"]["bet_placed"]]
    all_passes = [r for r in results if not r["pnl_info"] or not r["pnl_info"]["bet_placed"]]
    total_pnl = sum(r["pnl_info"]["pnl"] for r in all_bets)
    total_risked = sum(r["pnl_info"]["stake"] * BASE_UNIT for r in all_bets)
    wins = sum(1 for r in all_bets if r["pnl_info"]["won"])

    lines.append(f"- **Total bets placed:** {len(all_bets)}/{len(results)} "
                  f"({len(all_bets) / len(results) * 100:.0f}%)" if results else "")
    lines.append(f"- **Accuracy:** {wins}/{len(all_bets)} "
                  f"({wins / len(all_bets) * 100:.0f}%)" if all_bets else "- **No bets placed**")
    lines.append(f"- **Total P&L:** ${total_pnl:+.0f}")
    if total_risked > 0:
        lines.append(f"- **ROI on risked:** {total_pnl / total_risked * 100:+.1f}%")
    lines.append(f"- **Expert agreement rate:** "
                  f"{_expert_agreement_rate(results):.0f}%")

    # Analyst accuracy
    analyst_correct = 0
    analyst_total = 0
    for r in results:
        sc = r.get("scenario")
        if sc and sc.predicted_winner:
            analyst_total += 1
            actual_winner = "home" if bool(r["row"].get("home_win", 0)) else "away"
            if sc.predicted_winner == actual_winner:
                analyst_correct += 1
    if analyst_total:
        lines.append(f"- **Analyst accuracy:** {analyst_correct}/{analyst_total} "
                      f"({analyst_correct / analyst_total * 100:.0f}%)")

    # PASS selectivity: do passes avoid losers?
    if all_passes and all_bets:
        pass_dog_wins = sum(
            1 for r in all_passes
            if r["zone"] != "CF_pickem" and not bool(r["row"].get("home_win", 0))
        )
        pass_non_cf = [r for r in all_passes if r["zone"] != "CF_pickem"]
        if pass_non_cf:
            lines.append(f"- **PASS pool dog WR:** {pass_dog_wins}/{len(pass_non_cf)} "
                          f"({pass_dog_wins / len(pass_non_cf) * 100:.0f}%)")

    lines.append("")

    report = "\n".join(lines)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    logger.info(f"\nReport saved: {report_path}")


def _expert_agreement_rate(results: list[dict]) -> float:
    """Percentage of games where both experts agreed (both BET or both PASS)."""
    agreed = 0
    total = 0
    for r in results:
        dr = r.get("duel_result")
        if not dr:
            continue
        total += 1
        a_bets = "PASS" not in dr.verdict_a.action
        b_bets = "PASS" not in dr.verdict_b.action
        if a_bets == b_bets:
            agreed += 1
    return (agreed / total * 100) if total > 0 else 0.0


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full-day LLM calibration")
    parser.add_argument("--date", required=True,
                        help="Target date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show cards without API calls")
    parser.add_argument("--provider", default="openai",
                        help="LLM provider (default: openai)")
    parser.add_argument("--model", default="gpt-5.4",
                        help="LLM model (default: gpt-5.4)")
    args = parser.parse_args()

    logger.info(f"Full-day calibration for {args.date}")

    # Fetch ESPN box score URLs (non-blocking, can fail gracefully)
    espn_urls = fetch_espn_boxscore_urls(args.date)

    # Build enriched data
    day_df = build_enriched_fullday(args.date)
    if day_df.empty:
        logger.error(f"No games found for {args.date}. Check date format and data coverage.")
        return

    total_games = len(day_df)

    # Broad pre-filter
    day_df, filter_stats = apply_broad_filter(day_df)
    if day_df.empty:
        logger.error("No games survived pre-filter.")
        return

    # Zone assignment
    day_df = assign_zones(day_df)
    skipped = int((day_df["zone"] == "SKIP").sum())
    bettable = day_df[day_df["zone"] != "SKIP"]

    if bettable.empty:
        logger.error("No bettable games (all home-underdog or skipped).")
        return

    logger.info(f"Bettable: {len(bettable)} games, Skipped: {skipped}")

    # Run calibration
    results = run_fullday(day_df, dry_run=args.dry_run,
                          provider=args.provider, model=args.model)

    # Write report
    write_fullday_report(results, args.date, dry_run=args.dry_run,
                         filter_stats=filter_stats,
                         total_games=total_games, skipped=skipped,
                         espn_urls=espn_urls)

    # Quick summary
    if not args.dry_run and results:
        bets = [r for r in results if r["pnl_info"] and r["pnl_info"]["bet_placed"]]
        total_pnl = sum(r["pnl_info"]["pnl"] for r in bets)
        wins = sum(1 for r in bets if r["pnl_info"]["won"])
        logger.info(f"\nSummary: {len(bets)}/{len(results)} bets, "
                    f"{wins} wins, P&L: ${total_pnl:+.0f}")

    logger.info("Done.")


if __name__ == "__main__":
    main()
