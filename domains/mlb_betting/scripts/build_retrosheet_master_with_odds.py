"""Build Retrosheet master games and merge odds from sports-statistics dataset.

Goal: Retrosheet as source-of-truth for game outcomes + starters/IDs, while
keeping bookmaker odds from our existing xlsx-derived dataset.

Outputs:
  - data/processed/retrosheet/retrosheet_master_games.parquet
  - data/processed/retrosheet/retrosheet_master_games_with_odds.parquet
  - data/processed/retrosheet/match_report.md
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_loader import (
    _map_team_code_to_retrosheet,
    add_derived_odds,
    apply_data_filters,
    load_all_seasons,
)
from src.retrosheet_games import GamelogSources, drop_doubleheaders, load_retrosheet_gamelogs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _df_to_markdown_table(df: pd.DataFrame, *, max_rows: int = 25) -> str:
    """Render a small DataFrame as a markdown table without optional deps."""
    if df is None or df.empty:
        return ""
    d = df.head(max_rows).copy()
    cols = list(d.columns)
    # Convert everything to string and escape pipes minimally.
    rows = []
    for _, r in d.iterrows():
        rows.append([str(r[c]).replace("|", "\\|") for c in cols])
    out = []
    out.append("| " + " | ".join(cols) + " |\n")
    out.append("|" + "|".join(["---"] * len(cols)) + "|\n")
    for row in rows:
        out.append("| " + " | ".join(row) + " |\n")
    return "".join(out)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2010)
    p.add_argument("--end", type=int, default=2025)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/retrosheet"),
        help="Output directory for parquet + report",
    )
    p.add_argument(
        "--include-seasons",
        type=str,
        default="",
        help="Optional comma-separated season list (overrides start/end)",
    )
    p.add_argument(
        "--include-postseason-odds",
        action="store_true",
        help="If set, keep October+ games in the odds dataset (Retrosheet GL often excludes postseason).",
    )
    return p.parse_args()


def _report_markdown(
    *,
    n_odds: int,
    n_matched: int,
    unmatched: pd.DataFrame,
    by_season: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# Retrosheet master + odds match report\n\n")
    lines.append(f"- odds games (after hard filters): **{n_odds:,}**\n")
    lines.append(f"- matched to retrosheet master: **{n_matched:,}** (**{n_matched / max(n_odds, 1):.2%}**)\n\n")

    lines.append("## Match rate by season\n\n")
    lines.append("| season | odds_games | matched | match_rate |\n")
    lines.append("|---:|---:|---:|---:|\n")
    for _, r in by_season.sort_values("season").iterrows():
        lines.append(
            f"| {int(r['season'])} | {int(r['odds_games'])} | {int(r['matched'])} | {float(r['match_rate']):.4f} |\n"
        )

    if not unmatched.empty:
        lines.append("\n## Sample unmatched games (first 25)\n\n")
        cols = [c for c in ["season", "date", "home_team", "away_team", "home_team_rs", "away_team_rs"] if c in unmatched.columns]
        sample = unmatched[cols].head(25)
        lines.append(_df_to_markdown_table(sample, max_rows=25))
        lines.append("\n")

    return "".join(lines)


def main() -> None:
    args = parse_args()
    if args.include_seasons.strip():
        seasons = [int(x.strip()) for x in args.include_seasons.split(",") if x.strip()]
    else:
        seasons = list(range(args.start, args.end + 1))

    # Build Retrosheet master from gamelogs.
    logger.info(f"Loading Retrosheet gamelogs for seasons: {seasons[0]}..{seasons[-1]}")
    retro = load_retrosheet_gamelogs(seasons, sources=GamelogSources())
    retro = drop_doubleheaders(retro)

    # Load our odds dataset (sports-statistics xlsx) and hard-filter it.
    logger.info("Loading sports-statistics odds dataset...")
    odds = load_all_seasons()
    odds = apply_data_filters(odds)
    odds = add_derived_odds(odds)
    if not args.include_postseason_odds:
        # Retrosheet GL files typically cover regular season only; odds xlsx may include postseason.
        odds = odds[odds["date"].dt.month < 10].copy()

    # Map team codes to Retrosheet codes for join.
    odds = odds.copy()
    odds["home_team_rs"] = odds.apply(lambda r: _map_team_code_to_retrosheet(r["home_team"], r["season"]), axis=1)
    odds["away_team_rs"] = odds.apply(lambda r: _map_team_code_to_retrosheet(r["away_team"], r["season"]), axis=1)

    # Deduplicate after mapping: different upstream abbreviations can collapse to the same Retrosheet code.
    key_cols = ["season", "date", "home_team_rs", "away_team_rs"]
    dup_mask = odds.duplicated(subset=key_cols, keep=False)
    n_dup = int(dup_mask.sum())
    if n_dup:
        logger.warning(
            "Found duplicate odds rows after team-code mapping: %s rows (key=%s). "
            "Keeping first occurrence per key for merge; investigate if large.",
            n_dup,
            key_cols,
        )
        odds = odds.drop_duplicates(subset=key_cols, keep="first").copy()

    # Keep only seasons present in Retrosheet master for reporting.
    retro_seasons = set(retro["season"].unique().tolist())
    odds = odds[odds["season"].isin(sorted(retro_seasons))].copy()

    # Join odds → retrosheet master on (date, home_team, away_team) after mapping.
    retro_key = retro.rename(columns={"home_team": "home_team_rs", "away_team": "away_team_rs"})
    merged = odds.merge(
        retro_key[
            [
                "gid",
                "season",
                "date",
                "home_team_rs",
                "away_team_rs",
                "game_num",
                "home_final",
                "away_final",
            ]
        ],
        on=["season", "date", "home_team_rs", "away_team_rs"],
        how="left",
        validate="m:1",
    )

    n_odds = len(merged)
    n_matched = int(merged["gid"].notna().sum())
    unmatched = merged[merged["gid"].isna()].copy()

    # Diagnose common data issue: home/away swapped in odds source for some games.
    swap_join = unmatched.merge(
        retro_key[["gid", "season", "date", "home_team_rs", "away_team_rs"]],
        left_on=["season", "date", "home_team_rs", "away_team_rs"],
        right_on=["season", "date", "away_team_rs", "home_team_rs"],
        how="left",
        suffixes=("", "_swap"),
    )
    swap_candidates = swap_join[swap_join["gid_swap"].notna()].copy() if "gid_swap" in swap_join.columns else pd.DataFrame()

    # Quick sanity: score agreement (should match for correctly joined games).
    score_mismatch = merged[
        merged["gid"].notna()
        & (
            (merged["home_final_x"] != merged["home_final_y"])
            | (merged["away_final_x"] != merged["away_final_y"])
        )
    ] if ("home_final_x" in merged.columns and "home_final_y" in merged.columns) else pd.DataFrame()

    by_season = (
        merged.assign(matched=merged["gid"].notna())
        .groupby("season")
        .agg(odds_games=("matched", "size"), matched=("matched", "sum"))
        .reset_index()
    )
    by_season["match_rate"] = by_season["matched"] / by_season["odds_games"].clip(lower=1)

    # Build a retrosheet master + odds table (start from retrosheet master; left-join odds columns).
    # We keep the original retrosheet game structure, but attach our odds columns where available.
    odds_cols = [
        "home_open_ml",
        "home_close_ml",
        "away_open_ml",
        "away_close_ml",
        "home_decimal_odds",
        "away_decimal_odds",
        "home_implied_prob",
        "away_implied_prob",
        "home_run_line",
        "home_run_line_odds",
        "open_ou",
        "close_ou",
    ]
    odds_small = merged[["gid"] + [c for c in odds_cols if c in merged.columns]].copy()
    if odds_small["gid"].duplicated().any():
        # Defensive: should not happen after key dedupe, but keep stable output.
        odds_small = odds_small.drop_duplicates(subset=["gid"], keep="first").copy()

    retro_master = retro.copy()
    retro_master_with_odds = retro_master.merge(odds_small, on="gid", how="left", validate="1:1")

    args.out.mkdir(parents=True, exist_ok=True)
    retro_master.to_parquet(args.out / "retrosheet_master_games.parquet", index=False)
    retro_master_with_odds.to_parquet(args.out / "retrosheet_master_games_with_odds.parquet", index=False)

    report = _report_markdown(
        n_odds=n_odds,
        n_matched=n_matched,
        unmatched=unmatched,
        by_season=by_season,
    )
    if not swap_candidates.empty:
        report += "\n## Unmatched but matchable by swapping home/away (first 25)\n\n"
        cols = [
            "season",
            "date",
            "home_team",
            "away_team",
            "home_team_rs",
            "away_team_rs",
            "gid_swap",
        ]
        cols = [c for c in cols if c in swap_candidates.columns]
        report += _df_to_markdown_table(swap_candidates[cols], max_rows=25) + "\n"
    if not score_mismatch.empty:
        report += "\n## Score mismatches (joined but different final scores)\n\n"
        cols = [
            "season",
            "date",
            "home_team",
            "away_team",
            "home_team_rs",
            "away_team_rs",
            "home_final_x",
            "away_final_x",
            "home_final_y",
            "away_final_y",
        ]
        cols = [c for c in cols if c in score_mismatch.columns]
        report += _df_to_markdown_table(score_mismatch[cols], max_rows=25) + "\n"
    (args.out / "match_report.md").write_text(report, encoding="utf-8")

    logger.info(f"Saved retrosheet master to: {args.out.resolve()}")
    logger.info(f"Match rate: {n_matched}/{n_odds} = {n_matched / max(n_odds, 1):.2%}")


if __name__ == "__main__":
    main()

