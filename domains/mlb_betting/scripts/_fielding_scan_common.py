"""Shared helpers for MLB fielding research scans."""

from __future__ import annotations

import contextlib
import io
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from data.fetch_2026.team_mapping import ESPN_TO_CODE
from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features
from src.strategies import ACTIVE_STRATEGIES, add_derived_for_strategies

FIELDING_DIR = BASE_DIR / "data" / "fangraphs_fielding"

UNDERDOG_STRATEGIES = (
    "tier1_bullpen_day",
    "tier2_fatigue_gap",
    "tier3_pitcher_advantage",
    "tier4_ml_depth_load",
    "tier5_ml_obp_recovery",
)

RETENTION_MIN = 0.75
LOSS_FILTER_EDGE_MIN = 0.02
MAX_WORSE_SEASONS = 1
CANON_TEAM_CODES = set(ESPN_TO_CODE.values())


def _to_float(token: str) -> float:
    token = token.strip()
    if not token:
        return np.nan
    return float(token)


def normalize_fielding_team(team: str) -> str:
    code = team.strip().upper()
    if code in CANON_TEAM_CODES:
        return code
    mapped = ESPN_TO_CODE.get(code)
    if mapped is None:
        raise KeyError(f"Unknown FanGraphs team code: {team!r}")
    return mapped


def parse_fangraphs_fielding_txt(path: Path) -> pd.DataFrame:
    season = int(path.stem)
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 23 or not parts[0].strip().isdigit():
            continue
        rows.append(
            {
                "season_prior": season,
                "team": normalize_fielding_team(parts[1]),
                "drs_prev": _to_float(parts[12]),
                "uzr_prev": _to_float(parts[17]),
                "oaa_prev": _to_float(parts[20]),
                "def_prev": _to_float(parts[22]),
            }
        )
    out = pd.DataFrame(rows).drop_duplicates(subset=["season_prior", "team"])
    return out.sort_values(["season_prior", "team"]).reset_index(drop=True)


def load_fielding_snapshots(fielding_dir: Path = FIELDING_DIR) -> pd.DataFrame:
    frames = []
    for path in sorted(fielding_dir.glob("*.txt")):
        frames.append(parse_fangraphs_fielding_txt(path))
    if not frames:
        raise FileNotFoundError(f"No fielding txt files found in {fielding_dir}")
    out = pd.concat(frames, ignore_index=True)
    out["season_target"] = out["season_prior"] + 1
    return out.sort_values(["season_prior", "team"]).reset_index(drop=True)


def infer_target_seasons_from_fielding(
    games: pd.DataFrame,
    fielding: pd.DataFrame,
    *,
    fielding_season_col: str,
    include_current_season: bool = False,
) -> list[int]:
    seasons = sorted(
        set(games["season"].astype(int).unique())
        & set(fielding[fielding_season_col].astype(int).unique())
    )
    if include_current_season:
        return seasons
    current_year = date.today().year
    return [season for season in seasons if season < current_year]


def _run_maybe_quiet(callable_obj, *args, verbose_logs: bool = False, **kwargs):
    if verbose_logs:
        return callable_obj(*args, **kwargs)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        return callable_obj(*args, **kwargs)


def build_historical_enriched(
    target_seasons: list[int],
    *,
    verbose_logs: bool = False,
) -> pd.DataFrame:
    games = _run_maybe_quiet(load_all_seasons, verbose_logs=verbose_logs)
    games = _run_maybe_quiet(apply_data_filters, games, verbose_logs=verbose_logs)
    games = add_derived_odds(games)
    games = games[games["season"].isin(target_seasons)].copy()
    enriched = _run_maybe_quiet(build_all_features, games, verbose_logs=verbose_logs)
    return add_derived_for_strategies(enriched)


def _target_dates(enriched: pd.DataFrame) -> list[date]:
    return sorted(enriched["date"].dt.date.unique().tolist())


def pick_slice_label(strategy_name: str, tier: str, market: str) -> str:
    if strategy_name != "tier1_bullpen_day":
        return "all"
    if market == "ML_dog":
        return "tier1_ml"
    if tier == "tier1_bullpen_day_flipped":
        return "tier1_rl_flipped"
    return "tier1_rl_standard"


def collect_strategy_pick_rows(
    enriched: pd.DataFrame,
    strategy_name: str,
    *,
    extra_game_fields: tuple[str, ...] = (),
    verbose_logs: bool = False,
) -> pd.DataFrame:
    finder = ACTIVE_STRATEGIES[strategy_name]
    game_fields = list(
        dict.fromkeys(
            [
                "season",
                "date",
                "away_team",
                "home_team",
                "away_final",
                "home_final",
                *extra_game_fields,
            ]
        )
    )
    rows: list[dict[str, object]] = []
    for target_date in _target_dates(enriched):
        picks = _run_maybe_quiet(
            finder,
            enriched,
            target_date,
            verbose_logs=verbose_logs,
        )
        for pick in picks:
            rows.append(
                {
                    "strategy_name": strategy_name,
                    "tier": pick.tier,
                    "date": pd.Timestamp(pick.date),
                    "away_team": pick.away,
                    "home_team": pick.home,
                    "market": pick.market,
                    "side": pick.side,
                    "historical_p": pick.historical_p,
                    "ref_odds_espn": pick.ref_odds_espn,
                    "analysis_slice": pick_slice_label(
                        strategy_name, pick.tier, pick.market
                    ),
                }
            )
    picks_df = pd.DataFrame(rows)
    if picks_df.empty:
        return picks_df
    out = picks_df.merge(
        enriched[game_fields].drop_duplicates(),
        on=["date", "away_team", "home_team"],
        how="left",
        validate="many_to_one",
    )
    return settle_pick_rows(out)


def settle_pick_rows(picks_df: pd.DataFrame) -> pd.DataFrame:
    if picks_df.empty:
        return picks_df.copy()

    out = picks_df.copy()
    away_margin = out["away_final"] - out["home_final"]

    if "won" not in out.columns:
        out["won"] = False

    ml_mask = out["market"] == "ML_dog"
    rl_plus_mask = out["market"] == "RL_+1.5"
    rl_minus_mask = out["market"] == "RL_-1.5"

    out.loc[ml_mask & (out["side"] == "away"), "won"] = away_margin[ml_mask] > 0
    out.loc[ml_mask & (out["side"] == "home"), "won"] = away_margin[ml_mask] < 0
    out.loc[rl_plus_mask & (out["side"] == "away"), "won"] = (
        away_margin[rl_plus_mask] >= -1
    )
    out.loc[rl_plus_mask & (out["side"] == "home"), "won"] = (
        away_margin[rl_plus_mask] <= 1
    )
    out.loc[rl_minus_mask & (out["side"] == "away"), "won"] = (
        away_margin[rl_minus_mask] >= 2
    )
    out.loc[rl_minus_mask & (out["side"] == "home"), "won"] = (
        away_margin[rl_minus_mask] <= -2
    )

    out["pnl"] = np.where(
        out["ref_odds_espn"].notna(),
        np.where(out["won"], (out["ref_odds_espn"] - 1.0) * 100.0, -100.0),
        np.nan,
    )
    return out


def pass_diagnostics(selected: pd.DataFrame, pass_mask: pd.Series) -> dict[str, float]:
    if selected.empty:
        return {
            "winner_pass_rate": 0.0,
            "loser_pass_rate": 0.0,
            "winner_removed_share": 0.0,
            "loser_removed_share": 0.0,
            "loss_filter_edge": 0.0,
        }
    aligned = pass_mask.reindex(selected.index).fillna(False).astype(bool)
    winners = selected["won"].astype(bool)
    losers = ~winners
    winner_pass_rate = float(aligned[winners].mean()) if winners.any() else 0.0
    loser_pass_rate = float(aligned[losers].mean()) if losers.any() else 0.0
    winner_removed_share = 1.0 - winner_pass_rate
    loser_removed_share = 1.0 - loser_pass_rate
    return {
        "winner_pass_rate": winner_pass_rate,
        "loser_pass_rate": loser_pass_rate,
        "winner_removed_share": winner_removed_share,
        "loser_removed_share": loser_removed_share,
        "loss_filter_edge": loser_removed_share - winner_removed_share,
    }


def roi(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    return float(df["pnl"].mean())


def season_roi_columns(
    baseline: pd.DataFrame,
    filtered: pd.DataFrame,
    seasons: list[int],
) -> dict[str, float]:
    rows: dict[str, float] = {}
    for season in seasons:
        base_season = baseline[baseline["season"] == season]
        filtered_season = filtered[filtered["season"] == season]
        rows[f"base_roi_{season}"] = roi(base_season)
        rows[f"filtered_roi_{season}"] = roi(filtered_season)
    return rows


def season_worse_count(
    baseline: pd.DataFrame,
    filtered: pd.DataFrame,
    seasons: list[int],
) -> int:
    worse = 0
    for season in seasons:
        base_season = baseline[baseline["season"] == season]
        filtered_season = filtered[filtered["season"] == season]
        base_roi = roi(base_season)
        filtered_roi = roi(filtered_season)
        if np.isnan(base_roi):
            continue
        if filtered_season.empty or (
            not np.isnan(filtered_roi) and filtered_roi < base_roi
        ):
            worse += 1
    return worse


def tier1_lane_breakout_from_mask(
    baseline: pd.DataFrame,
    pass_mask: pd.Series,
    family_key: str,
) -> pd.DataFrame:
    if baseline.empty:
        return pd.DataFrame()
    if "strategy_name" in baseline.columns:
        tier1 = baseline[baseline["strategy_name"] == "tier1_bullpen_day"].copy()
    else:
        tier1 = baseline.copy()
    if tier1.empty:
        return pd.DataFrame()

    aligned = pass_mask.reindex(tier1.index).fillna(False).astype(bool)
    filtered = tier1[aligned]
    rows = []
    for lane in ("tier1_ml", "tier1_rl_standard", "tier1_rl_flipped"):
        lane_base = tier1[tier1["analysis_slice"] == lane].copy()
        if lane_base.empty:
            continue
        lane_filtered = filtered[filtered["analysis_slice"] == lane].copy()
        lane_mask = aligned.reindex(lane_base.index).fillna(False).astype(bool)
        diagnostics = pass_diagnostics(lane_base, lane_mask)
        rows.append(
            {
                "strategy_name": "tier1_bullpen_day",
                "family": family_key,
                "analysis_slice": lane,
                "base_bets": int(len(lane_base)),
                "base_roi": roi(lane_base),
                "filtered_bets": int(len(lane_filtered)),
                "filtered_roi": roi(lane_filtered),
                "retention": len(lane_filtered) / len(lane_base),
                "loss_filter_edge": diagnostics["loss_filter_edge"],
            }
        )
    return pd.DataFrame(rows)
