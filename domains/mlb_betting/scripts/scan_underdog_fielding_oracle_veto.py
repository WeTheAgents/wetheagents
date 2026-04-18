"""Run full-season oracle fielding veto scans for active underdog strategies.

This pass is intentionally leaky ceiling research. It uses final same-season
team fielding values to veto away-dog picks when the away team lands in the
MLB bottom decile for that season.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
for path in (SCRIPT_DIR, BASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _fielding_scan_common import (  # re-exported for tests
    CANON_TEAM_CODES,
    FIELDING_DIR,
    LOSS_FILTER_EDGE_MIN,
    MAX_WORSE_SEASONS,
    RETENTION_MIN,
    UNDERDOG_STRATEGIES,
    _run_maybe_quiet,
    build_historical_enriched,
    collect_strategy_pick_rows,
    infer_target_seasons_from_fielding,
    load_fielding_snapshots,
    parse_fangraphs_fielding_txt,
    pass_diagnostics,
    roi,
    season_roi_columns,
    season_worse_count,
    tier1_lane_breakout_from_mask,
)
from src.data_loader import load_all_seasons

DEFAULT_OUTPUT = BASE_DIR / "picks" / "underdog_fielding_oracle_veto.csv"

ORACLE_FAMILIES = {
    "oaa_bottom10_oracle": "away_oaa_oracle_bottom10",
    "def_bottom10_oracle": "away_def_oracle_bottom10",
}
ORACLE_METRICS = {
    "away_oaa_oracle_bottom10": "oaa_prev",
    "away_def_oracle_bottom10": "def_prev",
}
AGGREGATE_STRATEGY = "ALL_UNDERDOGS"


def infer_target_seasons(
    games: pd.DataFrame,
    fielding: pd.DataFrame,
    *,
    include_current_season: bool = False,
) -> list[int]:
    return infer_target_seasons_from_fielding(
        games,
        fielding,
        fielding_season_col="season_prior",
        include_current_season=include_current_season,
    )


def bottom_decile_membership(values: pd.Series) -> pd.Series:
    valid = values.dropna().sort_values(kind="mergesort")
    out = pd.Series(False, index=values.index, dtype=bool)
    if valid.empty:
        return out
    cutoff_rank = max(1, math.ceil(0.10 * len(valid)))
    cutoff_value = float(valid.iloc[cutoff_rank - 1])
    out.loc[valid.index] = values.loc[valid.index] <= cutoff_value
    return out


def build_same_season_oracle_flags(fielding: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for season, season_df in fielding.groupby("season_prior", sort=True):
        season_flags = season_df[["team"]].copy()
        season_flags["season"] = int(season)
        for flag_col, metric_col in ORACLE_METRICS.items():
            season_flags[flag_col] = bottom_decile_membership(season_df[metric_col])
        rows.append(season_flags)
    if not rows:
        return pd.DataFrame(
            columns=["season", "team", *ORACLE_FAMILIES.values()],
        )
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(["season", "team"]).reset_index(drop=True)


def join_same_season_oracle_flags(
    enriched: pd.DataFrame,
    fielding: pd.DataFrame,
) -> pd.DataFrame:
    away_flags = build_same_season_oracle_flags(fielding).rename(
        columns={"team": "away_team"}
    )
    out = enriched.merge(away_flags, on=["season", "away_team"], how="left")
    for flag_col in ORACLE_FAMILIES.values():
        out[flag_col] = out[flag_col].eq(True)
    return out


def _fail_reasons(
    *,
    retention: float,
    loss_filter_edge: float,
    base_roi: float,
    filtered_roi: float,
    worse_season_count: int,
) -> str:
    failures = []
    if retention < RETENTION_MIN:
        failures.append("retention")
    if loss_filter_edge < LOSS_FILTER_EDGE_MIN:
        failures.append("loss_filter_edge")
    if filtered_roi < base_roi:
        failures.append("roi")
    if worse_season_count > MAX_WORSE_SEASONS:
        failures.append("season_stability")
    return ",".join(failures)


def evaluate_oracle_family(
    baseline: pd.DataFrame,
    strategy_name: str,
    family_key: str,
    flag_col: str,
) -> dict[str, object]:
    if baseline.empty:
        return {
            "strategy_name": strategy_name,
            "family": family_key,
            "status": "no_signal",
            "fail_reasons": "no_baseline",
            "flag_col": flag_col,
            "rule": "exclude_bottom10",
        }

    pass_mask = ~baseline[flag_col].fillna(False).astype(bool)
    filtered = baseline[pass_mask].copy()
    seasons = sorted(baseline["season"].unique().tolist())
    diagnostics = pass_diagnostics(baseline, pass_mask)
    base_bets = int(len(baseline))
    filtered_bets = int(len(filtered))
    base_wins = int(baseline["won"].sum())
    filtered_wins = int(filtered["won"].sum()) if filtered_bets else 0
    base_losses = base_bets - base_wins
    filtered_losses = filtered_bets - filtered_wins
    base_roi = roi(baseline)
    filtered_roi = roi(filtered)
    worse_count = season_worse_count(baseline, filtered, seasons)
    retention = filtered_bets / base_bets if base_bets else float("nan")
    fail_reasons = _fail_reasons(
        retention=retention,
        loss_filter_edge=diagnostics["loss_filter_edge"],
        base_roi=base_roi,
        filtered_roi=filtered_roi,
        worse_season_count=worse_count,
    )
    eligible = fail_reasons == ""

    return {
        "strategy_name": strategy_name,
        "family": family_key,
        "flag_col": flag_col,
        "rule": "exclude_bottom10",
        "status": "oracle_signal" if eligible else "no_signal",
        "fail_reasons": fail_reasons,
        "base_bets": base_bets,
        "base_wins": base_wins,
        "base_losses": base_losses,
        "base_win_rate": float(baseline["won"].mean()),
        "base_roi": base_roi,
        "filtered_bets": filtered_bets,
        "filtered_wins": filtered_wins,
        "filtered_losses": filtered_losses,
        "filtered_win_rate": float(filtered["won"].mean())
        if filtered_bets
        else float("nan"),
        "filtered_roi": filtered_roi,
        "retention": retention,
        "winner_pass_rate": diagnostics["winner_pass_rate"],
        "loser_pass_rate": diagnostics["loser_pass_rate"],
        "winner_removed_share": diagnostics["winner_removed_share"],
        "loser_removed_share": diagnostics["loser_removed_share"],
        "loss_filter_edge": diagnostics["loss_filter_edge"],
        "worse_season_count": worse_count,
        "eligible": eligible,
        **season_roi_columns(baseline, filtered, seasons),
    }


def build_oracle_summary(
    baseline_by_strategy: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []
    for strategy_name in UNDERDOG_STRATEGIES:
        baseline = baseline_by_strategy.get(strategy_name, pd.DataFrame())
        for family_key, flag_col in ORACLE_FAMILIES.items():
            rows.append(
                evaluate_oracle_family(
                    baseline,
                    strategy_name=strategy_name,
                    family_key=family_key,
                    flag_col=flag_col,
                )
            )

    aggregate_baseline = pd.concat(
        [
            df
            for strategy_name, df in baseline_by_strategy.items()
            if strategy_name in UNDERDOG_STRATEGIES and not df.empty
        ],
        ignore_index=True,
    )
    for family_key, flag_col in ORACLE_FAMILIES.items():
        rows.append(
            evaluate_oracle_family(
                aggregate_baseline,
                strategy_name=AGGREGATE_STRATEGY,
                family_key=family_key,
                flag_col=flag_col,
            )
        )
    return pd.DataFrame(rows)


def _print_aggregate_summary(summary: pd.DataFrame) -> None:
    aggregate = summary[summary["strategy_name"] == AGGREGATE_STRATEGY].copy()
    if aggregate.empty:
        return
    print("\n=== ORACLE AGGREGATE SUMMARY ===")
    print(
        aggregate.to_string(
            index=False,
            formatters={
                "retention": lambda x: f"{x:.1%}" if pd.notna(x) else "",
                "loss_filter_edge": lambda x: f"{x:+.1%}" if pd.notna(x) else "",
                "base_roi": lambda x: f"{x:+.2f}%" if pd.notna(x) else "",
                "filtered_roi": lambda x: f"{x:+.2f}%" if pd.notna(x) else "",
            },
        )
    )


def _print_strategy_summary(summary: pd.DataFrame) -> None:
    strategies = summary[summary["strategy_name"] != AGGREGATE_STRATEGY].copy()
    if strategies.empty:
        print("No oracle summary rows produced.")
        return
    print("\n=== ORACLE PER-STRATEGY SUMMARY ===")
    print(
        strategies.to_string(
            index=False,
            formatters={
                "retention": lambda x: f"{x:.1%}" if pd.notna(x) else "",
                "loss_filter_edge": lambda x: f"{x:+.1%}" if pd.notna(x) else "",
                "base_roi": lambda x: f"{x:+.2f}%" if pd.notna(x) else "",
                "filtered_roi": lambda x: f"{x:+.2f}%" if pd.notna(x) else "",
            },
        )
    )


def _print_tier1_breakouts(baseline_by_strategy: dict[str, pd.DataFrame]) -> None:
    tier1 = baseline_by_strategy.get("tier1_bullpen_day")
    if tier1 is None or tier1.empty:
        return
    print("\n=== TIER1 ORACLE LANE BREAKOUT ===")
    for family_key, flag_col in ORACLE_FAMILIES.items():
        pass_mask = ~tier1[flag_col].fillna(False).astype(bool)
        breakout = tier1_lane_breakout_from_mask(
            tier1,
            pass_mask=pass_mask,
            family_key=family_key,
        )
        if breakout.empty:
            continue
        print(f"\n{family_key}")
        print(
            breakout.to_string(
                index=False,
                formatters={
                    "base_roi": lambda x: f"{x:+.2f}%",
                    "filtered_roi": lambda x: f"{x:+.2f}%",
                    "retention": lambda x: f"{x:.1%}",
                    "loss_filter_edge": lambda x: f"{x:+.1%}",
                },
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=None)
    parser.add_argument("--end-season", type=int, default=None)
    parser.add_argument("--include-current-season", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verbose-logs", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fielding = load_fielding_snapshots()
    games = _run_maybe_quiet(load_all_seasons, verbose_logs=args.verbose_logs)
    target_seasons = infer_target_seasons(
        games,
        fielding,
        include_current_season=args.include_current_season,
    )
    target_seasons = [int(season) for season in target_seasons]
    if args.start_season is not None:
        target_seasons = [s for s in target_seasons if s >= args.start_season]
    if args.end_season is not None:
        target_seasons = [s for s in target_seasons if s <= args.end_season]
    if not target_seasons:
        raise ValueError("No target seasons available for oracle fielding scan")

    print(f"Target seasons: {target_seasons}")
    print("Oracle mode: full-season same-season MLB bottom10 away-team veto")

    enriched = build_historical_enriched(
        target_seasons,
        verbose_logs=args.verbose_logs,
    )
    enriched = join_same_season_oracle_flags(enriched, fielding)

    baseline_by_strategy = {
        strategy_name: collect_strategy_pick_rows(
            enriched,
            strategy_name,
            extra_game_fields=tuple(ORACLE_FAMILIES.values()),
            verbose_logs=args.verbose_logs,
        )
        for strategy_name in UNDERDOG_STRATEGIES
    }
    summary = build_oracle_summary(baseline_by_strategy)
    if summary.empty:
        raise ValueError("No oracle summary rows produced")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out, index=False)

    print(f"Wrote oracle summary to {args.out}")
    _print_aggregate_summary(summary)
    _print_strategy_summary(summary)
    _print_tier1_breakouts(baseline_by_strategy)


if __name__ == "__main__":
    main()
