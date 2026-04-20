from __future__ import annotations

import argparse
import importlib
import importlib.machinery
import importlib.util
import json
import logging
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
for _path in (SCRIPT_DIR, BASE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PICKS_DIR = BASE_DIR / "picks"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
JSON_PATH = PICKS_DIR / "repeat_series_signal_analysis.json"
CSV_PATH = PICKS_DIR / "repeat_series_transition_rows.csv"
REPORT_PATH = KNOWLEDGE_DIR / "session_report_repeat_series_signal.md"

HEADLINE_SEASONS = [2024, 2025]
DEFAULT_SEASONS = [2024, 2025, 2026]
FORWARD_CHECK_MIN_TRANSITIONS = 10
LOGIT_MIN_SAMPLE = 150
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 42

STRATEGY_MODULES = [
    "tier1_bullpen_day",
    "tier2_fatigue_gap",
    "tier3_pitcher_advantage",
    "tier4_ml_depth_load",
    "tier5_ml_obp_recovery",
]

TEAM_METRIC_COLUMNS = {
    "streak": ("streak_home", "streak_away"),
    "wp_last3": ("wp_last3_home", "wp_last3_away"),
    "wp_last6": ("wp_last6_home", "wp_last6_away"),
    "wp_last10": ("wp_last10_home", "wp_last10_away"),
    "rpg_last10": ("rpg_last10_home", "rpg_last10_away"),
    "rapg_last10": ("rapg_last10_home", "rapg_last10_away"),
    "rpi": ("rpi_home", "rpi_away"),
    "bp_ip_3d": ("bp_ip_3d_home", "bp_ip_3d_away"),
    "bp_fip_short": ("bp_fip_short_home", "bp_fip_short_away"),
    "bp_fip_7g": ("bp_fip_7g_home", "bp_fip_7g_away"),
    "sp_fip_short": ("home_sp_fip_short", "away_sp_fip_short"),
    "sp_ip_per_start_short": (
        "home_sp_ip_per_start_short",
        "away_sp_ip_per_start_short",
    ),
}

FAVORABLE_DIFF_ORIENTATION = {
    "streak": 1.0,
    "wp_last3": 1.0,
    "wp_last6": 1.0,
    "wp_last10": 1.0,
    "rpg_last10": 1.0,
    "rapg_last10": -1.0,
    "rpi": 1.0,
    "bp_ip_3d": -1.0,
    "bp_fip_short": -1.0,
    "bp_fip_7g": -1.0,
    "sp_fip_short": -1.0,
    "sp_ip_per_start_short": 1.0,
}


@dataclass(frozen=True)
class StrategyHandle:
    name: str
    module_name: str
    find_picks: Callable[[pd.DataFrame, date], list]
    loaded_from: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze repeat-series ML/RL team signals across MLB series."
    )
    parser.add_argument(
        "--seasons",
        type=str,
        default="2024,2025,2026",
        help="Comma-separated seasons to load (default: 2024,2025,2026).",
    )
    parser.add_argument(
        "--headline-seasons",
        type=str,
        default="2024,2025",
        help="Comma-separated seasons for headline analysis (default: 2024,2025).",
    )
    parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=BOOTSTRAP_SAMPLES,
        help="Bootstrap resamples for ROI confidence intervals.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute analysis without writing JSON/CSV/markdown artifacts.",
    )
    return parser.parse_args()


def _parse_season_list(raw: str) -> list[int]:
    seasons = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            seasons.append(int(token))
    return seasons


def load_strategy_module(
    module_name: str,
    *,
    base_dir: Path = BASE_DIR,
) -> tuple[Any, str]:
    import_error: ModuleNotFoundError | None = None
    try:
        module = importlib.import_module(module_name)
        module_path = getattr(module, "__file__", "importlib")
        return module, str(module_path)
    except ModuleNotFoundError as exc:
        import_error = exc

    if not module_name.startswith("src.strategies."):
        raise import_error if import_error is not None else ModuleNotFoundError(module_name)

    stem = module_name.rsplit(".", 1)[-1]
    source_path = base_dir / "src" / "strategies" / f"{stem}.py"
    if source_path.exists():
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load source module: {source_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module, str(source_path)

    pyc_candidates = sorted(
        (base_dir / "src" / "strategies" / "__pycache__").glob(f"{stem}.cpython-*.pyc")
    )
    if not pyc_candidates:
        raise FileNotFoundError(
            f"Strategy module {module_name} not found in source or __pycache__."
        )

    pyc_path = pyc_candidates[0]
    loader = importlib.machinery.SourcelessFileLoader(module_name, str(pyc_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Unable to load sourceless module: {pyc_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module, str(pyc_path)


def load_repeat_strategies() -> list[StrategyHandle]:
    handles: list[StrategyHandle] = []
    for name in STRATEGY_MODULES:
        module_name = f"src.strategies.{name}"
        module, loaded_from = load_strategy_module(module_name)
        if not hasattr(module, "find_picks"):
            raise AttributeError(f"{module_name} is missing find_picks()")
        handles.append(
            StrategyHandle(
                name=name,
                module_name=module_name,
                find_picks=module.find_picks,
                loaded_from=loaded_from,
            )
        )
    return handles


def load_enriched_games(seasons: Sequence[int]) -> pd.DataFrame:
    from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
    from src.features import build_all_features
    from src.strategies.base import add_derived_for_strategies

    logger.info("Loading seasons: %s", ",".join(str(s) for s in seasons))
    games = load_all_seasons(seasons=list(seasons))
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = games[games["season"].isin(list(seasons))].copy()

    settled_mask = (
        games["home_final"].notna()
        & games["away_final"].notna()
        & ((games["home_final"] + games["away_final"]) > 0)
    )
    games = games[settled_mask].copy()
    games["date"] = pd.to_datetime(games["date"]).dt.normalize()
    games = games.sort_values(["date", "away_team", "home_team"]).reset_index(drop=True)

    logger.info("Building enriched feature frame on %d settled games", len(games))
    enriched = build_all_features(games)
    enriched = add_derived_for_strategies(enriched)
    enriched["date"] = pd.to_datetime(enriched["date"]).dt.normalize()
    enriched = enriched.sort_values(["date", "away_team", "home_team"]).reset_index(drop=True)
    return enriched


def build_series_lookup(games: pd.DataFrame) -> dict[int, dict[str, Any]]:
    from src.series import identify_series

    lookup: dict[int, dict[str, Any]] = {}
    for series in identify_series(games):
        for game in series.games:
            lookup[int(game.game_idx)] = {
                "series_key": series.series_key,
                "series_start_date": series.start_date,
                "game_in_series": int(game.game_in_series),
                "series_length": int(series.length),
            }
    return lookup


def market_family(market: str) -> str:
    if market.startswith("ML"):
        return "ML"
    if market.startswith("RL"):
        return "RL"
    return market


def _pick_team(row: pd.Series, side: str) -> tuple[str, str, bool]:
    if side == "home":
        return str(row["home_team"]), str(row["away_team"]), True
    if side == "away":
        return str(row["away_team"]), str(row["home_team"]), False
    raise ValueError(f"Unsupported team side for ML/RL analysis: {side}")


def evaluate_pick_result(
    *,
    market: str,
    side: str,
    decimal_odds: float | None,
    home_final: float,
    away_final: float,
) -> dict[str, Any]:
    if side == "home":
        margin = float(home_final) - float(away_final)
    elif side == "away":
        margin = float(away_final) - float(home_final)
    else:
        raise ValueError(f"Unsupported side for ML/RL analysis: {side}")

    if market.startswith("ML"):
        won = margin > 0
    elif market == "RL_+1.5":
        won = (margin + 1.5) > 0
    elif market == "RL_-1.5":
        won = (margin - 1.5) > 0
    else:
        raise ValueError(f"Unsupported market for ML/RL analysis: {market}")

    if decimal_odds is None or pd.isna(decimal_odds):
        implied_prob = None
        flat_return = None
    else:
        implied_prob = 1.0 / float(decimal_odds)
        flat_return = float(decimal_odds - 1.0) if won else -1.0

    return {
        "won": bool(won),
        "implied_prob": implied_prob,
        "flat_return": flat_return,
        "result_label": "win" if won else "loss",
    }


def game_key(row: pd.Series) -> tuple[int, pd.Timestamp, str, str]:
    return (
        int(row["season"]),
        pd.Timestamp(row["date"]).normalize(),
        str(row["away_team"]),
        str(row["home_team"]),
    )


def build_signal_rows(
    enriched: pd.DataFrame,
    strategies: Sequence[StrategyHandle],
    series_lookup: dict[int, dict[str, Any]],
) -> pd.DataFrame:
    game_row_lookup = {
        game_key(row): row
        for _, row in enriched.iterrows()
    }
    rows: list[dict[str, Any]] = []
    unique_dates = sorted(pd.to_datetime(enriched["date"]).dt.date.unique())

    logger.info("Rebuilding historical signals across %d dates", len(unique_dates))
    for target_date in unique_dates:
        day_frame = enriched[enriched["date"].dt.date == target_date].copy()
        if day_frame.empty:
            continue

        for strategy in strategies:
            picks = strategy.find_picks(day_frame, target_date)
            for pick in picks:
                if pick.market.startswith("O/U"):
                    continue
                if pick.side not in {"home", "away"}:
                    continue

                key = (
                    int(day_frame.iloc[0]["season"]) if len(day_frame["season"].unique()) == 1 else None,
                    pd.Timestamp(pick.date).normalize(),
                    pick.away,
                    pick.home,
                )
                game_row = game_row_lookup.get(key)
                if game_row is None:
                    matches = day_frame[
                        (day_frame["away_team"] == pick.away)
                        & (day_frame["home_team"] == pick.home)
                    ]
                    if matches.empty:
                        logger.warning(
                            "Unable to match pick to game row: %s @ %s (%s)",
                            pick.away,
                            pick.home,
                            pick.tier,
                        )
                        continue
                    game_row = matches.iloc[0]

                team, opponent, team_is_home = _pick_team(game_row, pick.side)
                result = evaluate_pick_result(
                    market=pick.market,
                    side=pick.side,
                    decimal_odds=pick.ref_odds_espn,
                    home_final=float(game_row["home_final"]),
                    away_final=float(game_row["away_final"]),
                )
                series_meta = series_lookup.get(int(game_row.name), {})
                rows.append(
                    {
                        "season": int(game_row["season"]),
                        "date": pd.Timestamp(game_row["date"]).normalize(),
                        "game_index": int(game_row.name),
                        "series_key": series_meta.get("series_key"),
                        "series_start_date": series_meta.get("series_start_date"),
                        "game_in_series": series_meta.get("game_in_series"),
                        "series_length": series_meta.get("series_length"),
                        "away_team": str(game_row["away_team"]),
                        "home_team": str(game_row["home_team"]),
                        "team": team,
                        "opponent": opponent,
                        "team_is_home": bool(team_is_home),
                        "tier": pick.tier,
                        "market": pick.market,
                        "market_family": market_family(pick.market),
                        "side": pick.side,
                        "decimal_odds": (
                            None if pick.ref_odds_espn is None else float(pick.ref_odds_espn)
                        ),
                        "implied_prob": result["implied_prob"],
                        "won": result["won"],
                        "result_label": result["result_label"],
                        "flat_return": result["flat_return"],
                        "historical_p": float(pick.historical_p),
                        "pick_id": pick.pick_id,
                        "reason": pick.reason,
                    }
                )

    signal_rows = pd.DataFrame(rows)
    if signal_rows.empty:
        return signal_rows

    signal_rows = signal_rows.sort_values(
        ["date", "away_team", "home_team", "team", "market_family", "tier"]
    ).reset_index(drop=True)
    return signal_rows


def _coerce_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer, np.int64)):
        return int(value)
    if isinstance(value, (np.floating, np.float64)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def extract_team_game_context(game_row: pd.Series, team: str) -> dict[str, Any]:
    is_home = str(game_row["home_team"]) == team
    team_prefix = "home" if is_home else "away"
    opp_prefix = "away" if is_home else "home"

    context: dict[str, Any] = {
        "team_is_home": bool(is_home),
        "team_is_favorite": float(
            float(game_row.get(f"{team_prefix}_implied_prob", np.nan))
            >= float(game_row.get(f"{opp_prefix}_implied_prob", np.nan))
        )
        if pd.notna(game_row.get(f"{team_prefix}_implied_prob"))
        and pd.notna(game_row.get(f"{opp_prefix}_implied_prob"))
        else None,
        "team_close_ml": _coerce_scalar(game_row.get(f"{team_prefix}_close_ml")),
        "opp_close_ml": _coerce_scalar(game_row.get(f"{opp_prefix}_close_ml")),
        "team_implied_prob": _coerce_scalar(game_row.get(f"{team_prefix}_implied_prob")),
        "opp_implied_prob": _coerce_scalar(game_row.get(f"{opp_prefix}_implied_prob")),
        "team_decimal_odds": _coerce_scalar(game_row.get(f"{team_prefix}_decimal_odds")),
        "opp_decimal_odds": _coerce_scalar(game_row.get(f"{opp_prefix}_decimal_odds")),
    }

    for metric, (home_col, away_col) in TEAM_METRIC_COLUMNS.items():
        team_col = home_col if is_home else away_col
        opp_col = away_col if is_home else home_col
        team_val = _coerce_scalar(game_row.get(team_col))
        opp_val = _coerce_scalar(game_row.get(opp_col))
        context[f"team_{metric}"] = team_val
        context[f"opp_{metric}"] = opp_val
        if team_val is None or opp_val is None:
            context[f"diff_{metric}"] = None
        else:
            context[f"diff_{metric}"] = float(team_val) - float(opp_val)

    if context["diff_bp_ip_3d"] is not None:
        context["bp_workload_gap"] = context["diff_bp_ip_3d"]
    else:
        context["bp_workload_gap"] = None
    if context["diff_sp_fip_short"] is not None:
        context["sp_fip_gap"] = context["diff_sp_fip_short"]
    else:
        context["sp_fip_gap"] = None
    if context["diff_sp_ip_per_start_short"] is not None:
        context["sp_ip_per_start_short_gap"] = context["diff_sp_ip_per_start_short"]
    else:
        context["sp_ip_per_start_short_gap"] = None

    return context


def collapse_team_level_signals(
    signal_rows: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    if signal_rows.empty:
        return pd.DataFrame()

    game_context = {
        int(idx): extract_team_game_context(row, str(row["home_team"]))
        for idx, row in games.iterrows()
    }
    away_context = {
        int(idx): extract_team_game_context(row, str(row["away_team"]))
        for idx, row in games.iterrows()
    }

    rows: list[dict[str, Any]] = []
    group_cols = [
        "season",
        "date",
        "game_index",
        "series_key",
        "series_start_date",
        "game_in_series",
        "series_length",
        "team",
        "opponent",
        "team_is_home",
        "away_team",
        "home_team",
    ]
    for keys, grp in signal_rows.groupby(group_cols, dropna=False):
        (
            season,
            game_date,
            game_index,
            series_key,
            series_start_date,
            game_in_series,
            series_length,
            team,
            opponent,
            team_is_home,
            away_team,
            home_team,
        ) = keys
        grp = grp.sort_values(["market_family", "tier"]).reset_index(drop=True)
        context = (
            game_context.get(int(game_index))
            if bool(team_is_home)
            else away_context.get(int(game_index))
        )
        if context is None:
            game_row = games.loc[int(game_index)]
            context = extract_team_game_context(game_row, str(team))

        market_families = sorted(grp["market_family"].dropna().unique().tolist())
        tiers = sorted(grp["tier"].dropna().unique().tolist())
        valid_returns = grp["flat_return"].dropna().astype(float)
        if not valid_returns.empty:
            signal_roi = float(valid_returns.mean())
        else:
            signal_roi = None
        if signal_roi is not None:
            signal_result = "win" if signal_roi > 0 else "loss"
        else:
            signal_result = "win" if bool(grp["won"].mean() >= 0.5) else "loss"

        representative_odds = grp["decimal_odds"].dropna().astype(float)
        representative_implied = grp["implied_prob"].dropna().astype(float)

        row = {
            "season": int(season),
            "date": pd.Timestamp(game_date).normalize(),
            "game_index": int(game_index),
            "series_key": None if pd.isna(series_key) else str(series_key),
            "series_start_date": (
                None if pd.isna(series_start_date) else str(series_start_date)
            ),
            "game_in_series": None if pd.isna(game_in_series) else int(game_in_series),
            "series_length": None if pd.isna(series_length) else int(series_length),
            "team": str(team),
            "opponent": str(opponent),
            "team_is_home": bool(team_is_home),
            "away_team": str(away_team),
            "home_team": str(home_team),
            "signal_market_family": "+".join(market_families),
            "signal_markets": list(grp["market"].tolist()),
            "signal_tiers": tiers,
            "support_count": int(len(tiers)),
            "raw_pick_count": int(len(grp)),
            "signal_result": signal_result,
            "signal_roi": signal_roi,
            "signal_decimal_odds": (
                float(representative_odds.mean()) if not representative_odds.empty else None
            ),
            "signal_implied_prob": (
                float(representative_implied.mean()) if not representative_implied.empty else None
            ),
            "signal_hit_rate": float(grp["won"].mean()),
        }
        row.update(context)
        rows.append(row)

    team_rows = pd.DataFrame(rows)
    if team_rows.empty:
        return team_rows
    team_rows = team_rows.sort_values(["date", "team", "game_in_series"]).reset_index(drop=True)
    return team_rows


def _delta(second: Any, first: Any) -> float | None:
    if first is None or second is None:
        return None
    if pd.isna(first) or pd.isna(second):
        return None
    return float(second) - float(first)


def build_repeat_transitions(team_signal_rows: pd.DataFrame) -> pd.DataFrame:
    if team_signal_rows.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    grouped = team_signal_rows.dropna(subset=["series_key", "game_in_series"]).groupby(
        ["series_key", "team"], dropna=False
    )
    for (_, _), grp in grouped:
        grp = grp.sort_values("game_in_series").reset_index(drop=True)
        for idx in range(len(grp) - 1):
            first = grp.iloc[idx]
            second = grp.iloc[idx + 1]
            if int(second["game_in_series"]) != int(first["game_in_series"]) + 1:
                continue

            transition = {
                "season": int(second["season"]),
                "series_key": str(second["series_key"]),
                "series_start_date": second["series_start_date"],
                "team": str(second["team"]),
                "opponent": str(second["opponent"]),
                "from_game": int(first["game_in_series"]),
                "to_game": int(second["game_in_series"]),
                "first_signal_result": str(first["signal_result"]),
                "first_signal_market_family": str(first["signal_market_family"]),
                "first_signal_tiers": list(first["signal_tiers"]),
                "first_support_count": int(first["support_count"]),
                "first_signal_roi": _coerce_scalar(first["signal_roi"]),
                "first_decimal_odds": _coerce_scalar(first["signal_decimal_odds"]),
                "first_implied_prob": _coerce_scalar(first["signal_implied_prob"]),
                "second_signal_result": str(second["signal_result"]),
                "second_signal_market_family": str(second["signal_market_family"]),
                "second_signal_tiers": list(second["signal_tiers"]),
                "second_support_count": int(second["support_count"]),
                "second_signal_roi": _coerce_scalar(second["signal_roi"]),
                "second_decimal_odds": _coerce_scalar(second["signal_decimal_odds"]),
                "second_implied_prob": _coerce_scalar(second["signal_implied_prob"]),
                "same_strategy_repeat": bool(
                    set(first["signal_tiers"]) & set(second["signal_tiers"])
                ),
                "first_team_is_favorite": _coerce_scalar(first["team_is_favorite"]),
                "second_team_is_favorite": _coerce_scalar(second["team_is_favorite"]),
                "favorite_status_changed": (
                    None
                    if first["team_is_favorite"] is None or second["team_is_favorite"] is None
                    else bool(first["team_is_favorite"] != second["team_is_favorite"])
                ),
            }

            for metric in TEAM_METRIC_COLUMNS:
                for scope in ("team", "opp", "diff"):
                    first_key = f"{scope}_{metric}"
                    second_key = f"{scope}_{metric}"
                    transition[f"delta_{scope}_{metric}"] = _delta(
                        second.get(second_key),
                        first.get(first_key),
                    )

            for metric in [
                "bp_workload_gap",
                "sp_fip_gap",
                "sp_ip_per_start_short_gap",
                "team_close_ml",
                "opp_close_ml",
                "team_implied_prob",
                "opp_implied_prob",
                "team_decimal_odds",
                "opp_decimal_odds",
                "signal_decimal_odds",
                "signal_implied_prob",
                "team_is_favorite",
            ]:
                transition[f"delta_{metric}"] = _delta(
                    second.get(metric),
                    first.get(metric),
                )

            transition["market_shortened_for_bettor"] = (
                None
                if transition["delta_signal_decimal_odds"] is None
                else bool(transition["delta_signal_decimal_odds"] < 0)
            )
            transition["team_ml_price_shortened"] = (
                None
                if transition["delta_team_decimal_odds"] is None
                else bool(transition["delta_team_decimal_odds"] < 0)
            )
            transition["market_respected_team_more"] = (
                None
                if transition["delta_team_implied_prob"] is None
                else bool(transition["delta_team_implied_prob"] > 0)
            )
            rows.append(transition)

    transitions = pd.DataFrame(rows)
    if transitions.empty:
        return transitions
    transitions = transitions.sort_values(["season", "series_key", "from_game"]).reset_index(
        drop=True
    )
    return transitions


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denom = 1 + (z**2 / total)
    centre = p + z**2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) / total) + (z**2 / (4 * total**2)))
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return low, high


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_boot: int,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    arr = np.asarray([v for v in values if v is not None and not pd.isna(v)], dtype=float)
    if arr.size == 0:
        return None, None
    if arr.size == 1:
        val = float(arr[0])
        return val, val

    rng = np.random.default_rng(seed)
    draws = rng.choice(arr, size=(n_boot, arr.size), replace=True).mean(axis=1)
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def summarize_slice(
    frame: pd.DataFrame,
    *,
    result_col: str,
    roi_col: str,
    odds_col: str,
    implied_col: str,
    bootstrap_samples: int,
) -> dict[str, Any]:
    n = int(len(frame))
    if n == 0:
        return {
            "n": 0,
            "success_rate": None,
            "roi": None,
            "avg_decimal_odds": None,
            "avg_implied_prob": None,
            "wilson_low": None,
            "wilson_high": None,
            "roi_ci_low": None,
            "roi_ci_high": None,
        }

    successes = int((frame[result_col] == "win").sum())
    success_rate = successes / n
    rois = frame[roi_col].dropna().astype(float)
    odds = frame[odds_col].dropna().astype(float)
    implied = frame[implied_col].dropna().astype(float)
    wilson_low, wilson_high = wilson_interval(successes, n)
    roi_ci_low, roi_ci_high = bootstrap_mean_ci(
        rois.tolist(),
        n_boot=bootstrap_samples,
    )
    return {
        "n": n,
        "success_rate": float(success_rate),
        "roi": float(rois.mean()) if not rois.empty else None,
        "avg_decimal_odds": float(odds.mean()) if not odds.empty else None,
        "avg_implied_prob": float(implied.mean()) if not implied.empty else None,
        "wilson_low": wilson_low,
        "wilson_high": wilson_high,
        "roi_ci_low": roi_ci_low,
        "roi_ci_high": roi_ci_high,
    }


def summarize_feature_deltas(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    out: dict[str, Any] = {}
    delta_cols = sorted(col for col in frame.columns if col.startswith("delta_"))
    for col in delta_cols:
        values = frame[col].dropna().astype(float)
        out[col] = {
            "mean": float(values.mean()) if not values.empty else None,
            "median": float(values.median()) if not values.empty else None,
        }
    for metric, sign in FAVORABLE_DIFF_ORIENTATION.items():
        col = f"delta_diff_{metric}"
        values = frame[col].dropna().astype(float) if col in frame.columns else pd.Series(dtype=float)
        out[f"favorable_shift_{metric}"] = (
            float((values * sign).mean()) if not values.empty else None
        )
    return out


def summarize_transition_metrics(
    transitions: pd.DataFrame,
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    def _metrics(df: pd.DataFrame) -> dict[str, Any]:
        return summarize_slice(
            df,
            result_col="second_signal_result",
            roi_col="second_signal_roi",
            odds_col="second_decimal_odds",
            implied_col="second_implied_prob",
            bootstrap_samples=bootstrap_samples,
        )

    metrics = {
        "repeat_baseline": _metrics(transitions),
        "after_first_win": _metrics(transitions[transitions["first_signal_result"] == "win"]),
        "after_first_loss": _metrics(transitions[transitions["first_signal_result"] == "loss"]),
        "g1_to_g2": _metrics(transitions[transitions["from_game"] == 1]),
        "g2_to_g3": _metrics(transitions[transitions["from_game"] == 2]),
        "same_strategy_repeat": _metrics(transitions[transitions["same_strategy_repeat"]]),
        "ml_only": _metrics(transitions[transitions["second_signal_market_family"] == "ML"]),
        "rl_only": _metrics(transitions[transitions["second_signal_market_family"] == "RL"]),
        "single_support": _metrics(transitions[transitions["second_support_count"] == 1]),
        "multi_support": _metrics(transitions[transitions["second_support_count"] > 1]),
        "first_signal_baseline": summarize_slice(
            transitions,
            result_col="first_signal_result",
            roi_col="first_signal_roi",
            odds_col="first_decimal_odds",
            implied_col="first_implied_prob",
            bootstrap_samples=bootstrap_samples,
        ),
    }
    metrics["mechanism_after_first_win"] = summarize_feature_deltas(
        transitions[transitions["first_signal_result"] == "win"]
    )
    metrics["mechanism_after_first_loss"] = summarize_feature_deltas(
        transitions[transitions["first_signal_result"] == "loss"]
    )
    metrics["mechanism_all_repeats"] = summarize_feature_deltas(transitions)
    return metrics


def season_slice_metrics(
    transitions: pd.DataFrame,
    seasons: Sequence[int],
    *,
    bootstrap_samples: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for season in seasons:
        season_df = transitions[transitions["season"] == season].copy()
        out[str(season)] = {
            "repeat_baseline": summarize_slice(
                season_df,
                result_col="second_signal_result",
                roi_col="second_signal_roi",
                odds_col="second_decimal_odds",
                implied_col="second_implied_prob",
                bootstrap_samples=bootstrap_samples,
            ),
            "after_first_win": summarize_slice(
                season_df[season_df["first_signal_result"] == "win"],
                result_col="second_signal_result",
                roi_col="second_signal_roi",
                odds_col="second_decimal_odds",
                implied_col="second_implied_prob",
                bootstrap_samples=bootstrap_samples,
            ),
            "after_first_loss": summarize_slice(
                season_df[season_df["first_signal_result"] == "loss"],
                result_col="second_signal_result",
                roi_col="second_signal_roi",
                odds_col="second_decimal_odds",
                implied_col="second_implied_prob",
                bootstrap_samples=bootstrap_samples,
            ),
        }
    return out


def fit_repeat_logit(transitions: pd.DataFrame) -> dict[str, Any] | None:
    if len(transitions) < LOGIT_MIN_SAMPLE:
        return None
    if transitions["second_signal_result"].nunique() < 2:
        return None

    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        logger.warning("scikit-learn unavailable; skipping robustness model")
        return None

    df = transitions.copy()
    df["prior_win"] = (df["first_signal_result"] == "win").astype(int)
    df["target"] = (df["second_signal_result"] == "win").astype(int)
    df["second_team_is_favorite_num"] = (
        pd.to_numeric(df["second_team_is_favorite"], errors="coerce").fillna(0.0)
    )
    features = df[
        [
            "prior_win",
            "from_game",
            "second_support_count",
            "second_team_is_favorite_num",
            "second_signal_market_family",
        ]
    ].copy()
    features = pd.get_dummies(
        features,
        columns=["second_signal_market_family"],
        prefix="market",
        drop_first=False,
        dtype=float,
    )
    model = LogisticRegression(
        C=0.5,
        solver="liblinear",
        max_iter=1_000,
    )
    model.fit(features, df["target"])

    coefficients: dict[str, Any] = {}
    for name, coef in zip(features.columns, model.coef_[0], strict=True):
        coefficients[name] = {
            "coef": float(coef),
            "odds_ratio": float(np.exp(coef)),
        }

    return {
        "n": int(len(df)),
        "intercept": float(model.intercept_[0]),
        "coefficients": coefficients,
    }


def _stable_direction(
    season_metrics: dict[str, Any],
    *,
    bucket: str,
) -> tuple[bool, list[int]]:
    hit_signs: list[int] = []
    roi_signs: list[int] = []
    seasons_used: list[int] = []
    for season, metrics in season_metrics.items():
        bucket_metrics = metrics[bucket]
        base_metrics = metrics["repeat_baseline"]
        if bucket_metrics["n"] < 10 or base_metrics["n"] < 10:
            continue
        hit_diff = (bucket_metrics["success_rate"] or 0.0) - (base_metrics["success_rate"] or 0.0)
        roi_diff = (bucket_metrics["roi"] or 0.0) - (base_metrics["roi"] or 0.0)
        hit_sign = 1 if hit_diff > 0 else -1 if hit_diff < 0 else 0
        roi_sign = 1 if roi_diff > 0 else -1 if roi_diff < 0 else 0
        hit_signs.append(hit_sign)
        roi_signs.append(roi_sign)
        seasons_used.append(int(season))
    if len(seasons_used) < 2:
        return False, seasons_used
    return len(set(hit_signs)) == 1 and len(set(roi_signs)) == 1, seasons_used


def classify_after_win(
    overall: dict[str, Any],
    season_metrics: dict[str, Any],
) -> str:
    bucket = overall["after_first_win"]
    base = overall["repeat_baseline"]
    if bucket["n"] < 25:
        return "insufficient sample"

    hit_diff = (bucket["success_rate"] or 0.0) - (base["success_rate"] or 0.0)
    roi_diff = (bucket["roi"] or 0.0) - (base["roi"] or 0.0)
    stable, _ = _stable_direction(season_metrics, bucket="after_first_win")
    ci_overlap = (
        bucket["wilson_low"] is not None
        and base["wilson_high"] is not None
        and bucket["wilson_low"] > base["wilson_high"]
    )

    if hit_diff > 0 and roi_diff > 0 and stable and ci_overlap:
        return "stronger"
    if hit_diff < 0 and roi_diff < 0 and stable:
        return "weaker"
    return "no evidence of strengthening"


def classify_after_loss(
    overall: dict[str, Any],
    season_metrics: dict[str, Any],
) -> str:
    bucket = overall["after_first_loss"]
    base = overall["repeat_baseline"]
    if bucket["n"] < 25:
        return "treat cautiously (thin sample)"

    hit_diff = (bucket["success_rate"] or 0.0) - (base["success_rate"] or 0.0)
    roi_diff = (bucket["roi"] or 0.0) - (base["roi"] or 0.0)
    stable, _ = _stable_direction(season_metrics, bucket="after_first_loss")

    if hit_diff > 0 and roi_diff > 0 and stable:
        return "respect"
    if hit_diff < 0 and roi_diff < 0 and stable:
        return "treat cautiously / mild fade bias"
    return "treat cautiously"


def staking_recommendation(win_class: str, loss_class: str) -> str:
    if win_class == "stronger" and loss_class == "respect":
        return "Evidence is strong enough to consider a modest repeat-series staking bonus."
    if win_class == "weaker" or "fade" in loss_class:
        return "No staking bonus. Repeats should stay flat or slightly reduced until more evidence builds."
    return "No rule change yet. Keep repeat-series context as a note, not a staking override."


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def fmt_num(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def build_metrics_table(metrics: dict[str, Any], rows: Sequence[tuple[str, str]]) -> str:
    lines = [
        "| Slice | n | Success | ROI | Avg Odds | Wilson CI | ROI CI |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for label, key in rows:
        item = metrics[key]
        lines.append(
            "| "
            f"{label} | {item['n']} | {fmt_pct(item['success_rate'])} | "
            f"{fmt_pct(item['roi'])} | {fmt_num(item['avg_decimal_odds'], 2)} | "
            f"{fmt_pct(item['wilson_low'])} to {fmt_pct(item['wilson_high'])} | "
            f"{fmt_pct(item['roi_ci_low'])} to {fmt_pct(item['roi_ci_high'])} |"
        )
    return "\n".join(lines)


def build_mechanism_table(metrics: dict[str, Any], key: str) -> str:
    mechanism = metrics[key]
    rows = [
        ("Team ML implied prob", mechanism.get("delta_team_implied_prob", {})),
        ("Signal odds", mechanism.get("delta_signal_decimal_odds", {})),
        ("Diff wp_last10", mechanism.get("delta_diff_wp_last10", {})),
        ("Diff rpg_last10", mechanism.get("delta_diff_rpg_last10", {})),
        ("Diff rapg_last10", mechanism.get("delta_diff_rapg_last10", {})),
        ("Diff bp_ip_3d", mechanism.get("delta_diff_bp_ip_3d", {})),
        ("Diff bp_fip_short", mechanism.get("delta_diff_bp_fip_short", {})),
        ("Diff sp_fip_short", mechanism.get("delta_diff_sp_fip_short", {})),
        (
            "Diff sp_ip_per_start_short",
            mechanism.get("delta_diff_sp_ip_per_start_short", {}),
        ),
    ]
    lines = [
        "| Feature delta (second minus first) | Mean | Median |",
        "| --- | ---: | ---: |",
    ]
    for label, values in rows:
        lines.append(
            f"| {label} | {fmt_num(values.get('mean'))} | {fmt_num(values.get('median'))} |"
        )
    return "\n".join(lines)


def build_report(
    *,
    headline_metrics: dict[str, Any],
    headline_season_metrics: dict[str, Any],
    counts: dict[str, Any],
    forward_metrics: dict[str, Any] | None,
    logit_model: dict[str, Any] | None,
) -> str:
    win_class = classify_after_win(headline_metrics, headline_season_metrics)
    loss_class = classify_after_loss(headline_metrics, headline_season_metrics)
    staking = staking_recommendation(win_class, loss_class)

    after_win = headline_metrics["after_first_win"]
    after_loss = headline_metrics["after_first_loss"]
    repeat_base = headline_metrics["repeat_baseline"]
    mechanism_win = headline_metrics["mechanism_after_first_win"]
    mechanism_loss = headline_metrics["mechanism_after_first_loss"]

    if mechanism_win.get("delta_team_implied_prob", {}).get("mean") is None:
        market_line = "Market reaction was too sparse to measure cleanly."
    else:
        market_shift = mechanism_win["delta_team_implied_prob"]["mean"]
        signal_shift = mechanism_win.get("delta_signal_decimal_odds", {}).get("mean")
        if market_shift > 0:
            market_line = (
                "After prior wins, the market generally respected the repeated team more "
                f"(team ML implied prob +{market_shift:.3f}) while bettor price moved "
                f"{fmt_num(signal_shift)} in decimal odds."
            )
        else:
            market_line = (
                "After prior wins, the market did not meaningfully shorten the repeated team; "
                f"team ML implied prob moved {market_shift:.3f} and signal odds moved "
                f"{fmt_num(signal_shift)}."
            )

    first_question = (
        f"After a first win, next-game repeats look **{win_class}**: "
        f"{after_win['n']} transitions, {fmt_pct(after_win['success_rate'])} success, "
        f"{fmt_pct(after_win['roi'])} ROI versus pooled repeat baseline "
        f"{fmt_pct(repeat_base['success_rate'])} / {fmt_pct(repeat_base['roi'])}."
    )
    second_question = (
        f"After a first loss, the practical read is **{loss_class}**: "
        f"{after_loss['n']} transitions, {fmt_pct(after_loss['success_rate'])} success, "
        f"{fmt_pct(after_loss['roi'])} ROI."
    )
    fourth_question = f"Rule impact: {staking}"

    lines = [
        "# Repeat-Series Signal Analysis (ML/RL)",
        "",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Bottom Line",
        "",
        f"- {first_question}",
        f"- {second_question}",
        f"- {market_line}",
        f"- {fourth_question}",
        "",
        "## Sample",
        "",
        f"- Raw signal rows: {counts['raw_signal_rows']}",
        f"- Team-level signal rows: {counts['team_level_signal_rows']}",
        f"- Next-game repeat transitions: {counts['repeat_next_game_cases']}",
        f"- G1→G2 transitions: {counts['g1_to_g2_cases']}",
        f"- G2→G3 transitions: {counts['g2_to_g3_cases']}",
        "",
        "## Performance",
        "",
        build_metrics_table(
            headline_metrics,
            [
                ("Repeat baseline", "repeat_baseline"),
                ("After first win", "after_first_win"),
                ("After first loss", "after_first_loss"),
                ("G1→G2", "g1_to_g2"),
                ("G2→G3", "g2_to_g3"),
                ("Same-strategy repeat", "same_strategy_repeat"),
                ("ML-only", "ml_only"),
                ("RL-only", "rl_only"),
                ("Single-support", "single_support"),
                ("Multi-support", "multi_support"),
                ("Original first signal baseline", "first_signal_baseline"),
            ],
        ),
        "",
        "## Mechanism",
        "",
        "### After First Win",
        "",
        build_mechanism_table(headline_metrics, "mechanism_after_first_win"),
        "",
        "### After First Loss",
        "",
        build_mechanism_table(headline_metrics, "mechanism_after_first_loss"),
        "",
    ]

    if logit_model is None:
        lines.extend(
            [
                "## Robustness",
                "",
                "Regularized logistic regression was skipped because the repeat-transition sample was below the configured threshold or the environment lacked the dependency.",
                "",
            ]
        )
    else:
        prior = logit_model["coefficients"].get("prior_win")
        prior_line = (
            "Prior-win coefficient unavailable."
            if prior is None
            else (
                f"Regularized logistic regression on {logit_model['n']} transitions gives "
                f"`prior_win` coef {prior['coef']:.3f} "
                f"(odds ratio {prior['odds_ratio']:.3f})."
            )
        )
        lines.extend(
            [
                "## Robustness",
                "",
                prior_line,
                "",
            ]
        )

    if forward_metrics is not None:
        lines.extend(
            [
                "## 2026 Forward Check",
                "",
                build_metrics_table(
                    forward_metrics,
                    [
                        ("Repeat baseline", "repeat_baseline"),
                        ("After first win", "after_first_win"),
                        ("After first loss", "after_first_loss"),
                    ],
                ),
                "",
                "The 2026 section is an appendix only and does not drive the headline rule recommendations.",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def frame_to_json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, list):
                clean[key] = [_coerce_scalar(item) for item in value]
            else:
                clean[key] = _coerce_scalar(value)
        records.append(clean)
    return records


def count_summary(
    signal_rows: pd.DataFrame,
    team_signal_rows: pd.DataFrame,
    transitions: pd.DataFrame,
) -> dict[str, Any]:
    return {
        "raw_signal_rows": int(len(signal_rows)),
        "team_level_signal_rows": int(len(team_signal_rows)),
        "unique_series_with_team_signals": int(
            team_signal_rows["series_key"].dropna().nunique()
            if not team_signal_rows.empty
            else 0
        ),
        "repeat_next_game_cases": int(len(transitions)),
        "g1_to_g2_cases": int((transitions["from_game"] == 1).sum()) if not transitions.empty else 0,
        "g2_to_g3_cases": int((transitions["from_game"] == 2).sum()) if not transitions.empty else 0,
        "repeat_after_first_win": int(
            (transitions["first_signal_result"] == "win").sum()
        )
        if not transitions.empty
        else 0,
        "repeat_after_first_loss": int(
            (transitions["first_signal_result"] == "loss").sum()
        )
        if not transitions.empty
        else 0,
        "tier_counts": (
            signal_rows["tier"].value_counts().sort_index().astype(int).to_dict()
            if not signal_rows.empty
            else {}
        ),
    }


def write_outputs(
    *,
    signal_rows: pd.DataFrame,
    team_signal_rows: pd.DataFrame,
    transitions: pd.DataFrame,
    payload: dict[str, Any],
    report_text: str,
) -> None:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    transitions_to_write = transitions.copy()
    for col in ("first_signal_tiers", "second_signal_tiers"):
        if col in transitions_to_write.columns:
            transitions_to_write[col] = transitions_to_write[col].apply(
                lambda v: ",".join(v) if isinstance(v, list) else v
            )
    transitions_to_write.to_csv(CSV_PATH, index=False)

    payload["signal_rows"] = frame_to_json_records(signal_rows)
    payload["team_signal_rows"] = frame_to_json_records(team_signal_rows)
    payload["transition_rows_path"] = str(CSV_PATH)
    JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(report_text, encoding="utf-8")


def run_analysis(
    *,
    seasons: Sequence[int],
    headline_seasons: Sequence[int],
    bootstrap_samples: int,
) -> dict[str, Any]:
    strategies = load_repeat_strategies()
    enriched = load_enriched_games(seasons)
    series_lookup = build_series_lookup(enriched)
    signal_rows = build_signal_rows(enriched, strategies, series_lookup)
    team_signal_rows = collapse_team_level_signals(signal_rows, enriched)
    transitions = build_repeat_transitions(team_signal_rows)

    counts = count_summary(signal_rows, team_signal_rows, transitions)
    headline_transitions = transitions[transitions["season"].isin(list(headline_seasons))].copy()
    headline_metrics = summarize_transition_metrics(
        headline_transitions,
        bootstrap_samples=bootstrap_samples,
    )
    headline_season_metrics = season_slice_metrics(
        headline_transitions,
        headline_seasons,
        bootstrap_samples=bootstrap_samples,
    )

    remaining_seasons = sorted(set(seasons) - set(headline_seasons))
    forward_metrics = None
    if remaining_seasons:
        forward_transitions = transitions[transitions["season"].isin(remaining_seasons)].copy()
        if len(forward_transitions) >= FORWARD_CHECK_MIN_TRANSITIONS:
            forward_metrics = summarize_transition_metrics(
                forward_transitions,
                bootstrap_samples=bootstrap_samples,
            )

    logit_model = fit_repeat_logit(headline_transitions)
    report_text = build_report(
        headline_metrics=headline_metrics,
        headline_season_metrics=headline_season_metrics,
        counts=counts,
        forward_metrics=forward_metrics,
        logit_model=logit_model,
    )

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "seasons": list(seasons),
            "headline_seasons": list(headline_seasons),
            "bootstrap_samples": int(bootstrap_samples),
            "strategy_modules": [
                {
                    "name": handle.name,
                    "module_name": handle.module_name,
                    "loaded_from": handle.loaded_from,
                }
                for handle in strategies
            ],
        },
        "counts": counts,
        "headline_metrics": headline_metrics,
        "headline_season_metrics": headline_season_metrics,
        "forward_check_metrics": forward_metrics,
        "logit_model": logit_model,
        "report_path": str(REPORT_PATH),
    }

    return {
        "signal_rows": signal_rows,
        "team_signal_rows": team_signal_rows,
        "transitions": transitions,
        "payload": payload,
        "report_text": report_text,
    }


def main() -> int:
    args = parse_args()
    seasons = _parse_season_list(args.seasons)
    headline_seasons = _parse_season_list(args.headline_seasons)
    results = run_analysis(
        seasons=seasons,
        headline_seasons=headline_seasons,
        bootstrap_samples=args.bootstrap_samples,
    )
    if args.dry_run:
        logger.info("Dry run complete; artifacts were not written.")
        return 0

    write_outputs(
        signal_rows=results["signal_rows"],
        team_signal_rows=results["team_signal_rows"],
        transitions=results["transitions"],
        payload=results["payload"],
        report_text=results["report_text"],
    )
    logger.info("Wrote JSON -> %s", JSON_PATH)
    logger.info("Wrote CSV  -> %s", CSV_PATH)
    logger.info("Wrote MD   -> %s", REPORT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
