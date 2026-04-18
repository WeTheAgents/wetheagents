"""Scan soft prior-season fielding filters for active underdog strategies.

This research script evaluates two global fielding families on top of the
active underdog strategies:

  - away_oaa_edge_prev
  - away_def_edge_prev

The scan is preseason-safe: each target season Y uses team fielding from
season Y-1 only. No production strategy code is changed.
"""

from __future__ import annotations

import argparse
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
    ACTIVE_STRATEGIES,
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
    pick_slice_label,
    roi,
    season_roi_columns,
    season_worse_count,
    settle_pick_rows,
    tier1_lane_breakout_from_mask,
)
from src.data_loader import load_all_seasons

DEFAULT_OUTPUT = BASE_DIR / "picks" / "underdog_fielding_soft_filters.csv"

FIELDING_FAMILIES = {
    "oaa_guard": "away_oaa_edge_prev",
    "def_guard": "away_def_edge_prev",
}
QUANTILES = (0.10, 0.15, 0.20, 0.25)


def infer_target_seasons(
    games: pd.DataFrame,
    fielding: pd.DataFrame,
    *,
    include_current_season: bool = False,
) -> list[int]:
    return infer_target_seasons_from_fielding(
        games,
        fielding,
        fielding_season_col="season_target",
        include_current_season=include_current_season,
    )


def join_prior_season_fielding(
    enriched: pd.DataFrame,
    fielding: pd.DataFrame,
) -> pd.DataFrame:
    home = fielding.rename(
        columns={
            "season_target": "season",
            "team": "home_team",
            "drs_prev": "home_drs_prev",
            "uzr_prev": "home_uzr_prev",
            "oaa_prev": "home_oaa_prev",
            "def_prev": "home_def_prev",
        }
    )[
        [
            "season",
            "home_team",
            "home_drs_prev",
            "home_uzr_prev",
            "home_oaa_prev",
            "home_def_prev",
        ]
    ]
    away = fielding.rename(
        columns={
            "season_target": "season",
            "team": "away_team",
            "drs_prev": "away_drs_prev",
            "uzr_prev": "away_uzr_prev",
            "oaa_prev": "away_oaa_prev",
            "def_prev": "away_def_prev",
        }
    )[
        [
            "season",
            "away_team",
            "away_drs_prev",
            "away_uzr_prev",
            "away_oaa_prev",
            "away_def_prev",
        ]
    ]
    out = enriched.merge(home, on=["season", "home_team"], how="left").merge(
        away, on=["season", "away_team"], how="left"
    )
    out["away_oaa_edge_prev"] = out["away_oaa_prev"] - out["home_oaa_prev"]
    out["away_def_edge_prev"] = out["away_def_prev"] - out["home_def_prev"]
    return out


def evaluate_strategy_family_thresholds(
    baseline: pd.DataFrame,
    strategy_name: str,
    family_key: str,
    feature_col: str,
    quantiles: tuple[float, ...] = QUANTILES,
) -> pd.DataFrame:
    if baseline.empty:
        return pd.DataFrame()
    values = baseline[feature_col].dropna()
    if values.empty:
        return pd.DataFrame()

    seasons = sorted(baseline["season"].unique().tolist())
    base_bets = int(len(baseline))
    base_wins = int(baseline["won"].sum())
    base_losses = base_bets - base_wins
    base_roi = roi(baseline)
    base_wr = float(baseline["won"].mean())

    rows: list[dict[str, object]] = []
    for q in quantiles:
        threshold = float(values.quantile(q))
        pass_mask = baseline[feature_col] >= threshold
        filtered = baseline[pass_mask].copy()
        diagnostics = pass_diagnostics(baseline, pass_mask)
        filtered_bets = int(len(filtered))
        filtered_wins = int(filtered["won"].sum()) if filtered_bets else 0
        filtered_losses = filtered_bets - filtered_wins
        filtered_roi = roi(filtered)
        worse_count = season_worse_count(baseline, filtered, seasons)
        rows.append(
            {
                "strategy_name": strategy_name,
                "family": family_key,
                "analysis_slice": "all",
                "feature_col": feature_col,
                "quantile": q,
                "threshold": threshold,
                "base_bets": base_bets,
                "base_wins": base_wins,
                "base_losses": base_losses,
                "base_win_rate": base_wr,
                "base_roi": base_roi,
                "filtered_bets": filtered_bets,
                "filtered_wins": filtered_wins,
                "filtered_losses": filtered_losses,
                "filtered_win_rate": float(filtered["won"].mean())
                if filtered_bets
                else float("nan"),
                "filtered_roi": filtered_roi,
                "retention": filtered_bets / base_bets if base_bets else float("nan"),
                "winner_pass_rate": diagnostics["winner_pass_rate"],
                "loser_pass_rate": diagnostics["loser_pass_rate"],
                "winner_removed_share": diagnostics["winner_removed_share"],
                "loser_removed_share": diagnostics["loser_removed_share"],
                "loss_filter_edge": diagnostics["loss_filter_edge"],
                "worse_season_count": worse_count,
                **season_roi_columns(baseline, filtered, seasons),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["eligible"] = (
        (out["retention"] >= RETENTION_MIN)
        & (out["loss_filter_edge"] >= LOSS_FILTER_EDGE_MIN)
        & (out["filtered_roi"] >= out["base_roi"])
        & (out["worse_season_count"] <= MAX_WORSE_SEASONS)
    )
    out["selected"] = False
    return out.sort_values(
        ["quantile", "filtered_bets"],
        ascending=[True, False],
    ).reset_index(drop=True)


def choose_family_candidate(rows: pd.DataFrame) -> pd.Series | None:
    if rows.empty:
        return None
    eligible = rows[rows["eligible"]].copy()
    if eligible.empty:
        return None
    eligible = eligible.sort_values(
        ["retention", "loss_filter_edge", "filtered_roi"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return eligible.iloc[0]


def build_threshold_table(
    baseline_by_strategy: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    frames = []
    for strategy_name, baseline in baseline_by_strategy.items():
        for family_key, feature_col in FIELDING_FAMILIES.items():
            rows = evaluate_strategy_family_thresholds(
                baseline,
                strategy_name=strategy_name,
                family_key=family_key,
                feature_col=feature_col,
            )
            if rows.empty:
                continue
            candidate = choose_family_candidate(rows)
            if candidate is not None:
                mask = (
                    (rows["strategy_name"] == candidate["strategy_name"])
                    & (rows["family"] == candidate["family"])
                    & (rows["quantile"] == candidate["quantile"])
                    & (rows["threshold"] == candidate["threshold"])
                )
                rows.loc[mask, "selected"] = True
            frames.append(rows)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_candidate_summary(threshold_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy_name in UNDERDOG_STRATEGIES:
        for family_key in FIELDING_FAMILIES:
            subset = threshold_table[
                (threshold_table["strategy_name"] == strategy_name)
                & (threshold_table["family"] == family_key)
                & (threshold_table["analysis_slice"] == "all")
            ].copy()
            candidate = choose_family_candidate(subset)
            if candidate is None:
                rows.append(
                    {
                        "strategy_name": strategy_name,
                        "family": family_key,
                        "status": "no_candidate",
                        "quantile": np.nan,
                        "threshold": np.nan,
                        "retention": np.nan,
                        "loss_filter_edge": np.nan,
                        "base_roi": subset["base_roi"].iloc[0]
                        if not subset.empty
                        else np.nan,
                        "filtered_roi": np.nan,
                        "worse_season_count": np.nan,
                    }
                )
            else:
                rows.append(
                    {
                        "strategy_name": strategy_name,
                        "family": family_key,
                        "status": "candidate",
                        "quantile": candidate["quantile"],
                        "threshold": candidate["threshold"],
                        "retention": candidate["retention"],
                        "loss_filter_edge": candidate["loss_filter_edge"],
                        "base_roi": candidate["base_roi"],
                        "filtered_roi": candidate["filtered_roi"],
                        "worse_season_count": candidate["worse_season_count"],
                    }
                )
    return pd.DataFrame(rows)


def _print_summary(summary: pd.DataFrame) -> None:
    if summary.empty:
        print("No fielding scan rows produced.")
        return
    show = summary.copy()
    with pd.option_context("display.max_rows", None, "display.max_columns", None):
        print("\n=== SOFT FIELDING CANDIDATES ===")
        print(
            show.to_string(
                index=False,
                formatters={
                    "quantile": lambda x: f"q{int(x * 100)}" if pd.notna(x) else "",
                    "threshold": lambda x: f"{x:.2f}" if pd.notna(x) else "",
                    "retention": lambda x: f"{x:.1%}" if pd.notna(x) else "",
                    "loss_filter_edge": lambda x: f"{x:+.1%}"
                    if pd.notna(x)
                    else "",
                    "base_roi": lambda x: f"{x:+.2f}%" if pd.notna(x) else "",
                    "filtered_roi": lambda x: f"{x:+.2f}%"
                    if pd.notna(x)
                    else "",
                },
            )
        )


def _print_tier1_breakouts(
    baseline_by_strategy: dict[str, pd.DataFrame],
    summary: pd.DataFrame,
) -> None:
    tier1 = baseline_by_strategy.get("tier1_bullpen_day")
    if tier1 is None or tier1.empty:
        return
    chosen = summary[
        (summary["strategy_name"] == "tier1_bullpen_day")
        & (summary["status"] == "candidate")
    ]
    if chosen.empty:
        return
    print("\n=== TIER1 LANE BREAKOUT ===")
    for _, row in chosen.iterrows():
        feature_col = FIELDING_FAMILIES[row["family"]]
        pass_mask = tier1[feature_col] >= float(row["threshold"])
        breakout = tier1_lane_breakout_from_mask(
            tier1,
            pass_mask=pass_mask,
            family_key=str(row["family"]),
        )
        if breakout.empty:
            continue
        print(f"\n{row['family']} @ q{int(float(row['quantile']) * 100)}")
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
        raise ValueError("No target seasons available for fielding scan")

    print(f"Target seasons: {target_seasons}")
    enriched = build_historical_enriched(
        target_seasons,
        verbose_logs=args.verbose_logs,
    )
    enriched = join_prior_season_fielding(enriched, fielding)

    baseline_by_strategy = {
        strategy_name: collect_strategy_pick_rows(
            enriched,
            strategy_name,
            extra_game_fields=tuple(FIELDING_FAMILIES.values()),
            verbose_logs=args.verbose_logs,
        )
        for strategy_name in UNDERDOG_STRATEGIES
    }
    threshold_table = build_threshold_table(baseline_by_strategy)
    if threshold_table.empty:
        raise ValueError("No threshold rows produced")

    summary = build_candidate_summary(threshold_table)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    threshold_table.to_csv(args.out, index=False)

    print(f"Wrote threshold table to {args.out}")
    _print_summary(summary)
    _print_tier1_breakouts(baseline_by_strategy, summary)


if __name__ == "__main__":
    main()
