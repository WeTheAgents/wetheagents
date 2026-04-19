"""Session 42 -- Streak ML momentum research.

Goal:
    Evaluate three questions in one pass:
      1. Do entering-game win/loss streaks show raw continuation?
      2. Does the closing ML market already price that continuation?
      3. Can a narrow, bettable streak subset survive discovery + frozen checks?

Default workflow:
    - Build enriched games via ``build_all_features()``.
    - Normalize each game into two team-side rows.
    - Produce raw tables on the standard filtered universe.
    - Produce pricing tables and candidate scans on the bettable subset.
    - Write:
        picks/streak_ml_edge_discovery.json
        knowledge/session_report_42_streak_ml.md

Usage:
    python scripts/streak_ml_edge_discovery.py
    python scripts/streak_ml_edge_discovery.py --season-min 2022 --season-max 2025
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.edge_discovery import bootstrap_roi_ci, passes_gate, wilson_interval
from src.features import build_all_features

DEFAULT_ARTIFACT_PATH = ROOT / "picks" / "streak_ml_edge_discovery.json"
DEFAULT_REPORT_PATH = ROOT / "knowledge" / "session_report_42_streak_ml.md"

EXACT_STREAKS = [*range(-10, 0), *range(1, 11)]
THRESHOLD_BUCKETS = list(range(1, 9))
SCAN_THRESHOLDS = [2, 3, 4, 5, 6, 7]

IMPLIED_BANDS: list[tuple[str, float, float]] = [
    ("[0.35,0.45)", 0.35, 0.45),
    ("[0.45,0.55)", 0.45, 0.55),
    ("[0.55,0.65)", 0.55, 0.65),
    ("[0.65,0.75)", 0.65, 0.75),
]
THESES = ("back_hot", "fade_hot", "back_cold", "fade_cold")
DISCOVERY_TOP_PER_THESIS = 6
MIN_SCAN_N = 20
MIN_GATE_N = 50
BOOTSTRAP_N = 1000


def _section(title: str) -> None:
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def season_phase_for_month(month: int) -> str:
    """Collapse MLB calendar into broad seasonal buckets.

    March opening days are grouped into the early-season bucket and
    October regular-season tail is grouped with late season.
    """
    if month in {3, 4, 5}:
        return "Apr-May"
    if month in {6, 7}:
        return "Jun-Jul"
    return "Aug-Sep"


def back_team_pnl(team_won, team_decimal_odds):
    """Flat-stake PnL for backing the streak team on ML."""
    won = np.asarray(team_won, dtype=bool)
    odds = np.asarray(team_decimal_odds, dtype=float)
    pnl = np.where(won, odds - 1.0, -1.0)
    if np.ndim(pnl) == 0:
        return float(pnl)
    return pnl


def fade_team_pnl(team_won, opponent_decimal_odds):
    """Flat-stake PnL for fading the streak team and betting the opponent ML."""
    won = np.asarray(team_won, dtype=bool)
    odds = np.asarray(opponent_decimal_odds, dtype=float)
    pnl = np.where(~won, odds - 1.0, -1.0)
    if np.ndim(pnl) == 0:
        return float(pnl)
    return pnl


def _load_enriched_games(season_min: int, season_max: int) -> pd.DataFrame:
    """Load filtered MLB games and attach rolling features."""
    games = load_all_seasons()
    games = games[(games["season"] >= season_min) & (games["season"] <= season_max)].copy()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    return build_all_features(games)


def normalize_team_side_frame(enriched: pd.DataFrame) -> pd.DataFrame:
    """Convert a game-level frame into team-side rows for streak research."""
    required = [
        "season",
        "date",
        "home_team",
        "away_team",
        "home_win",
        "home_decimal_odds",
        "away_decimal_odds",
        "home_implied_prob",
        "away_implied_prob",
        "streak_home",
        "streak_away",
        "wp_last3_home",
        "wp_last3_away",
        "wp_last6_home",
        "wp_last6_away",
        "is_september",
        "is_extreme_line",
        "involves_col",
    ]
    missing = [col for col in required if col not in enriched.columns]
    if missing:
        raise KeyError(f"normalize_team_side_frame missing required columns: {missing}")

    date_series = pd.to_datetime(enriched["date"]).dt.normalize()
    month = date_series.dt.month

    home = pd.DataFrame(
        {
            "season": enriched["season"].values,
            "date": date_series.values,
            "month": month.values,
            "season_phase": [season_phase_for_month(int(m)) for m in month],
            "team": enriched["home_team"].values,
            "opponent": enriched["away_team"].values,
            "team_is_home": True,
            "team_won": enriched["home_win"].astype(bool).values,
            "opp_won": (~enriched["home_win"].astype(bool)).values,
            "team_decimal_odds": enriched["home_decimal_odds"].values,
            "opp_decimal_odds": enriched["away_decimal_odds"].values,
            "team_implied_prob": enriched["home_implied_prob"].values,
            "opp_implied_prob": enriched["away_implied_prob"].values,
            "team_is_favorite": (
                enriched["home_implied_prob"].values > enriched["away_implied_prob"].values
            ),
            "team_signed_streak": enriched["streak_home"].values,
            "opp_signed_streak": enriched["streak_away"].values,
            "wp_last3": enriched["wp_last3_home"].values,
            "opp_wp_last3": enriched["wp_last3_away"].values,
            "wp_last6": enriched["wp_last6_home"].values,
            "opp_wp_last6": enriched["wp_last6_away"].values,
            "elo_edge": enriched["elo_diff"].values if "elo_diff" in enriched.columns else np.nan,
            "rpi_edge": enriched["rpi_diff"].values if "rpi_diff" in enriched.columns else np.nan,
            "streak_diff": enriched["streak_diff"].values if "streak_diff" in enriched.columns else np.nan,
            "is_september": enriched["is_september"].values,
            "is_extreme_line": enriched["is_extreme_line"].values,
            "involves_col": enriched["involves_col"].values,
        }
    )
    away = pd.DataFrame(
        {
            "season": enriched["season"].values,
            "date": date_series.values,
            "month": month.values,
            "season_phase": [season_phase_for_month(int(m)) for m in month],
            "team": enriched["away_team"].values,
            "opponent": enriched["home_team"].values,
            "team_is_home": False,
            "team_won": (~enriched["home_win"].astype(bool)).values,
            "opp_won": enriched["home_win"].astype(bool).values,
            "team_decimal_odds": enriched["away_decimal_odds"].values,
            "opp_decimal_odds": enriched["home_decimal_odds"].values,
            "team_implied_prob": enriched["away_implied_prob"].values,
            "opp_implied_prob": enriched["home_implied_prob"].values,
            "team_is_favorite": (
                enriched["away_implied_prob"].values > enriched["home_implied_prob"].values
            ),
            "team_signed_streak": enriched["streak_away"].values,
            "opp_signed_streak": enriched["streak_home"].values,
            "wp_last3": enriched["wp_last3_away"].values,
            "opp_wp_last3": enriched["wp_last3_home"].values,
            "wp_last6": enriched["wp_last6_away"].values,
            "opp_wp_last6": enriched["wp_last6_home"].values,
            "elo_edge": (
                -enriched["elo_diff"].values if "elo_diff" in enriched.columns else np.nan
            ),
            "rpi_edge": (
                -enriched["rpi_diff"].values if "rpi_diff" in enriched.columns else np.nan
            ),
            "streak_diff": (
                -enriched["streak_diff"].values
                if "streak_diff" in enriched.columns
                else np.nan
            ),
            "is_september": enriched["is_september"].values,
            "is_extreme_line": enriched["is_extreme_line"].values,
            "involves_col": enriched["involves_col"].values,
        }
    )
    out = pd.concat([home, away], ignore_index=True)
    out["team_role"] = np.where(out["team_is_favorite"], "favorite", "underdog")
    out["location"] = np.where(out["team_is_home"], "home", "away")
    out["wp_last6_bucket"] = np.where(out["wp_last6"] >= 0.5, ">=.500", "<.500")
    out["opp_streak_bucket"] = np.select(
        [
            out["opp_signed_streak"] <= -2,
            out["opp_signed_streak"].between(-1, 1, inclusive="both"),
            out["opp_signed_streak"] >= 2,
        ],
        ["opp_cold", "opp_flat", "opp_hot"],
        default="opp_other",
    )
    out["implied_band"] = "outside"
    for label, lo, hi in IMPLIED_BANDS:
        mask = (out["team_implied_prob"] >= lo) & (out["team_implied_prob"] < hi)
        out.loc[mask, "implied_band"] = label
    out["back_pnl"] = back_team_pnl(out["team_won"], out["team_decimal_odds"])
    out["fade_pnl"] = fade_team_pnl(out["team_won"], out["opp_decimal_odds"])
    out["game_key"] = (
        out["season"].astype(str)
        + "::"
        + out["date"].dt.strftime("%Y-%m-%d")
        + "::"
        + out["team"]
        + "::"
        + out["opponent"]
    )
    return out


def _serialize_metric_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _serialize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize_metric_value(value) for key, value in metrics.items()}


def summarize_market_subset(
    sub: pd.DataFrame,
    *,
    win_col: str,
    odds_col: str,
    implied_col: str,
    pnl_col: str,
    include_bootstrap: bool,
) -> dict[str, Any]:
    """Summarize a DataFrame subset for a specific betting direction."""
    return summarize_market_arrays(
        wins=sub[win_col].astype(bool).values,
        odds=sub[odds_col].astype(float).values,
        implied=sub[implied_col].astype(float).values,
        pnl=sub[pnl_col].astype(float).values,
        include_bootstrap=include_bootstrap,
    )


def summarize_market_arrays(
    *,
    wins: np.ndarray,
    odds: np.ndarray,
    implied: np.ndarray,
    pnl: np.ndarray,
    include_bootstrap: bool,
) -> dict[str, Any]:
    """Summarize numpy arrays for a specific betting direction."""
    n = int(len(wins))
    if n == 0:
        return {
            "n": 0,
            "win_rate": None,
            "mean_odds": None,
            "mean_implied_prob": None,
            "actual_minus_implied": None,
            "break_even": None,
            "wilson_lo": None,
            "wilson_hi": None,
            "roi": None,
            "bootstrap_p5": None,
            "bootstrap_p95": None,
            "passes_gate": False,
        }

    win_rate = float(wins.mean())
    mean_odds = float(odds.mean())
    mean_implied = float(implied.mean())
    break_even = float(1.0 / mean_odds)
    wilson_lo, wilson_hi = wilson_interval(int(wins.sum()), n)
    roi = float(pnl.mean())

    should_bootstrap = (
        include_bootstrap
        and n >= MIN_GATE_N
        and roi > 0
        and wilson_lo > break_even
        and (win_rate - mean_implied) > 0
    )

    if should_bootstrap:
        bootstrap_p5, bootstrap_p95 = bootstrap_roi_ci(
            wins.astype(int),
            odds,
            n_boot=BOOTSTRAP_N,
        )
    else:
        bootstrap_p5, bootstrap_p95 = None, None

    row = {
        "n": n,
        "win_rate": win_rate,
        "mean_odds": mean_odds,
        "mean_implied_prob": mean_implied,
        "actual_minus_implied": win_rate - mean_implied,
        "break_even": break_even,
        "wilson_lo": float(wilson_lo),
        "wilson_hi": float(wilson_hi),
        "roi": roi,
        "bootstrap_p5": None if bootstrap_p5 is None else float(bootstrap_p5),
        "bootstrap_p95": None if bootstrap_p95 is None else float(bootstrap_p95),
    }
    row["passes_gate"] = bool(
        row["bootstrap_p5"] is not None and passes_gate(row, min_n=MIN_GATE_N)
    )
    return row


def _build_raw_exact_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for streak in EXACT_STREAKS:
        sub = frame[frame["team_signed_streak"] == streak]
        if sub.empty:
            continue
        wins = sub["team_won"].astype(bool).values
        n = int(len(sub))
        win_rate = float(wins.mean())
        wilson_lo, wilson_hi = wilson_interval(int(wins.sum()), n)
        rows.append(
            {
                "bucket": f"W{streak}" if streak > 0 else f"L{abs(streak)}",
                "signed_streak": streak,
                "n": n,
                "win_rate": win_rate,
                "wilson_lo": float(wilson_lo),
                "wilson_hi": float(wilson_hi),
                "avg_odds": float(sub["team_decimal_odds"].mean()),
                "avg_implied_prob": float(sub["team_implied_prob"].mean()),
            }
        )
    return rows


def _build_raw_threshold_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for k in THRESHOLD_BUCKETS:
        for bucket, mask in [
            (f"W{k}+", frame["team_signed_streak"] >= k),
            (f"L{k}+", frame["team_signed_streak"] <= -k),
        ]:
            sub = frame[mask]
            if sub.empty:
                continue
            wins = sub["team_won"].astype(bool).values
            n = int(len(sub))
            win_rate = float(wins.mean())
            wilson_lo, wilson_hi = wilson_interval(int(wins.sum()), n)
            rows.append(
                {
                    "bucket": bucket,
                    "n": n,
                    "win_rate": win_rate,
                    "wilson_lo": float(wilson_lo),
                    "wilson_hi": float(wilson_hi),
                    "avg_odds": float(sub["team_decimal_odds"].mean()),
                    "avg_implied_prob": float(sub["team_implied_prob"].mean()),
                }
            )
    return rows


def _build_pricing_exact_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for streak in EXACT_STREAKS:
        sub = frame[frame["team_signed_streak"] == streak]
        if sub.empty:
            continue
        rows.append(
            {
                "bucket": f"W{streak}" if streak > 0 else f"L{abs(streak)}",
                "signed_streak": streak,
                "n": int(len(sub)),
                "actual_win_rate": float(sub["team_won"].mean()),
                "avg_implied_prob": float(sub["team_implied_prob"].mean()),
                "actual_minus_implied": float(
                    sub["team_won"].mean() - sub["team_implied_prob"].mean()
                ),
                "fade_win_rate": float(sub["opp_won"].mean()),
                "fade_avg_implied_prob": float(sub["opp_implied_prob"].mean()),
                "fade_actual_minus_implied": float(
                    sub["opp_won"].mean() - sub["opp_implied_prob"].mean()
                ),
                "back_roi": float(sub["back_pnl"].mean()),
                "fade_roi": float(sub["fade_pnl"].mean()),
            }
        )
    return rows


def _build_pricing_threshold_table(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for k in THRESHOLD_BUCKETS:
        for bucket, mask in [
            (f"W{k}+", frame["team_signed_streak"] >= k),
            (f"L{k}+", frame["team_signed_streak"] <= -k),
        ]:
            sub = frame[mask]
            if sub.empty:
                continue
            rows.append(
                {
                    "bucket": bucket,
                "n": int(len(sub)),
                "actual_win_rate": float(sub["team_won"].mean()),
                "avg_implied_prob": float(sub["team_implied_prob"].mean()),
                "actual_minus_implied": float(
                    sub["team_won"].mean() - sub["team_implied_prob"].mean()
                ),
                "fade_win_rate": float(sub["opp_won"].mean()),
                "fade_avg_implied_prob": float(sub["opp_implied_prob"].mean()),
                "fade_actual_minus_implied": float(
                    sub["opp_won"].mean() - sub["opp_implied_prob"].mean()
                ),
                "back_roi": float(sub["back_pnl"].mean()),
                "fade_roi": float(sub["fade_pnl"].mean()),
            }
        )
    return rows


def _slice_frame(frame: pd.DataFrame, seasons: list[int], *, exclude_september: bool = False) -> pd.DataFrame:
    out = frame[frame["season"].isin(seasons)].copy()
    if exclude_september:
        out = out[~out["is_september"]].copy()
    return out


def _slice_definition(
    season_min: int,
    season_max: int,
    discovery_start: int,
    discovery_end: int,
    test_season: int,
    live_season: int,
) -> dict[str, dict[str, Any]]:
    full = [s for s in range(season_min, season_max + 1) if s != 2020]
    main = [s for s in full if 2015 <= s <= 2025]
    recent = [s for s in full if 2022 <= s <= 2025]
    discovery = [s for s in full if discovery_start <= s <= discovery_end]
    test = [test_season] if test_season in full else []
    live = [live_season] if live_season in full else []
    return {
        "appendix": {"label": "Appendix", "season_label": "2004-2025", "seasons": full},
        "main": {"label": "Main", "season_label": "2015-2025", "seasons": main},
        "recent": {"label": "Recent", "season_label": "2022-2025", "seasons": recent},
        "discovery": {
            "label": "Discovery",
            "season_label": f"{discovery_start}-{discovery_end}",
            "seasons": discovery,
        },
        "test": {"label": "Frozen Test", "season_label": str(test_season), "seasons": test},
        "live": {"label": "Live Forward", "season_label": str(live_season), "seasons": live},
    }


def build_raw_tables(frame: pd.DataFrame, slices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("appendix", "main", "recent"):
        sub = _slice_frame(frame, slices[key]["seasons"])
        out[key] = {
            "label": slices[key]["label"],
            "season_label": slices[key]["season_label"],
            "seasons": slices[key]["seasons"],
            "exact": _build_raw_exact_table(sub),
            "threshold": _build_raw_threshold_table(sub),
        }
    return out


def build_pricing_tables(frame: pd.DataFrame, slices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    main = _slice_frame(frame, slices["main"]["seasons"])
    recent = _slice_frame(frame, slices["recent"]["seasons"])
    appendix = _slice_frame(frame, slices["appendix"]["seasons"])

    main_bands = {}
    for label, _, _ in IMPLIED_BANDS:
        band_frame = main[main["implied_band"] == label]
        main_bands[label] = {
            "exact": _build_pricing_exact_table(band_frame),
            "threshold": _build_pricing_threshold_table(band_frame),
        }

    return {
        "appendix": {
            "label": slices["appendix"]["label"],
            "season_label": slices["appendix"]["season_label"],
            "overall": {
                "exact": _build_pricing_exact_table(appendix),
                "threshold": _build_pricing_threshold_table(appendix),
            },
        },
        "main": {
            "label": slices["main"]["label"],
            "season_label": slices["main"]["season_label"],
            "overall": {
                "exact": _build_pricing_exact_table(main),
                "threshold": _build_pricing_threshold_table(main),
            },
            "favorite": {
                "exact": _build_pricing_exact_table(main[main["team_role"] == "favorite"]),
                "threshold": _build_pricing_threshold_table(main[main["team_role"] == "favorite"]),
            },
            "underdog": {
                "exact": _build_pricing_exact_table(main[main["team_role"] == "underdog"]),
                "threshold": _build_pricing_threshold_table(main[main["team_role"] == "underdog"]),
            },
            "home": {
                "exact": _build_pricing_exact_table(main[main["location"] == "home"]),
                "threshold": _build_pricing_threshold_table(main[main["location"] == "home"]),
            },
            "away": {
                "exact": _build_pricing_exact_table(main[main["location"] == "away"]),
                "threshold": _build_pricing_threshold_table(main[main["location"] == "away"]),
            },
            "implied_bands": main_bands,
            "september_sensitivity": {
                "with_september": {
                    "exact": _build_pricing_exact_table(main),
                    "threshold": _build_pricing_threshold_table(main),
                },
                "without_september": {
                    "exact": _build_pricing_exact_table(main[~main["is_september"]]),
                    "threshold": _build_pricing_threshold_table(main[~main["is_september"]]),
                },
            },
        },
        "recent": {
            "label": slices["recent"]["label"],
            "season_label": slices["recent"]["season_label"],
            "overall": {
                "exact": _build_pricing_exact_table(recent),
                "threshold": _build_pricing_threshold_table(recent),
            },
        },
    }


def _bet_columns_for_thesis(thesis: str) -> tuple[str, str, str, str]:
    if thesis.startswith("back"):
        return ("team_won", "team_decimal_odds", "team_implied_prob", "back_pnl")
    return ("opp_won", "opp_decimal_odds", "opp_implied_prob", "fade_pnl")


def _candidate_mask(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    thesis = spec["thesis"]
    k = int(spec["streak_threshold"])
    if thesis.endswith("hot"):
        mask = frame["team_signed_streak"] >= k
    else:
        mask = frame["team_signed_streak"] <= -k

    if spec["team_role"] != "any":
        mask &= frame["team_role"] == spec["team_role"]
    if spec["location"] != "any":
        mask &= frame["location"] == spec["location"]
    if spec["implied_band"] != "any":
        mask &= frame["implied_band"] == spec["implied_band"]
    if spec["wp_last6_bucket"] != "any":
        mask &= frame["wp_last6_bucket"] == spec["wp_last6_bucket"]
    if spec["opp_streak_bucket"] != "any":
        mask &= frame["opp_streak_bucket"] == spec["opp_streak_bucket"]
    if spec["season_phase"] != "any":
        mask &= frame["season_phase"] == spec["season_phase"]
    return mask.fillna(False)


def _candidate_label(spec: dict[str, Any]) -> str:
    parts = [spec["thesis"], f"{'W' if spec['thesis'].endswith('hot') else 'L'}{spec['streak_threshold']}+"]
    for key in ("team_role", "location", "implied_band", "wp_last6_bucket", "opp_streak_bucket", "season_phase"):
        value = spec[key]
        if value != "any":
            parts.append(str(value))
    return " | ".join(parts)


def _candidate_metrics(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    *,
    include_bootstrap: bool,
) -> dict[str, Any]:
    mask = _candidate_mask(frame, spec)
    sub = frame[mask].copy()
    win_col, odds_col, implied_col, pnl_col = _bet_columns_for_thesis(spec["thesis"])
    metrics = summarize_market_subset(
        sub,
        win_col=win_col,
        odds_col=odds_col,
        implied_col=implied_col,
        pnl_col=pnl_col,
        include_bootstrap=include_bootstrap,
    )
    out = dict(spec)
    out["label"] = _candidate_label(spec)
    out.update(metrics)
    return out


def _candidate_specs() -> list[dict[str, Any]]:
    specs = []
    for thesis, k, team_role, location, implied_band, wp_bucket, opp_bucket, phase in product(
        THESES,
        SCAN_THRESHOLDS,
        ("any", "favorite", "underdog"),
        ("any", "home", "away"),
        ("any", *[label for label, _, _ in IMPLIED_BANDS]),
        ("any", "<.500", ">=.500"),
        ("any", "opp_cold", "opp_flat", "opp_hot"),
        ("any", "Apr-May", "Jun-Jul", "Aug-Sep"),
    ):
        specs.append(
            {
                "thesis": thesis,
                "streak_threshold": k,
                "team_role": team_role,
                "location": location,
                "implied_band": implied_band,
                "wp_last6_bucket": wp_bucket,
                "opp_streak_bucket": opp_bucket,
                "season_phase": phase,
            }
        )
    return specs


def scan_candidate_filters(
    discovery: pd.DataFrame,
    test: pd.DataFrame,
    live: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run a staged scan: cheap pass over all specs, bootstrap on shortlist."""
    _section("LAYER C -- Candidate filter scan")
    specs = _candidate_specs()

    n = len(discovery)
    ones = np.ones(n, dtype=bool)
    discovery_masks = {
        "team_role": {
            "any": ones,
            "favorite": (discovery["team_role"].values == "favorite"),
            "underdog": (discovery["team_role"].values == "underdog"),
        },
        "location": {
            "any": ones,
            "home": (discovery["location"].values == "home"),
            "away": (discovery["location"].values == "away"),
        },
        "implied_band": {
            "any": ones,
            **{
                label: (discovery["implied_band"].values == label)
                for label, _, _ in IMPLIED_BANDS
            },
        },
        "wp_last6_bucket": {
            "any": ones,
            "<.500": (discovery["wp_last6_bucket"].values == "<.500"),
            ">=.500": (discovery["wp_last6_bucket"].values == ">=.500"),
        },
        "opp_streak_bucket": {
            "any": ones,
            "opp_cold": (discovery["opp_streak_bucket"].values == "opp_cold"),
            "opp_flat": (discovery["opp_streak_bucket"].values == "opp_flat"),
            "opp_hot": (discovery["opp_streak_bucket"].values == "opp_hot"),
        },
        "season_phase": {
            "any": ones,
            "Apr-May": (discovery["season_phase"].values == "Apr-May"),
            "Jun-Jul": (discovery["season_phase"].values == "Jun-Jul"),
            "Aug-Sep": (discovery["season_phase"].values == "Aug-Sep"),
        },
        "base": {
            **{f"hot_{k}": (discovery["team_signed_streak"].values >= k) for k in SCAN_THRESHOLDS},
            **{f"cold_{k}": (discovery["team_signed_streak"].values <= -k) for k in SCAN_THRESHOLDS},
        },
    }
    discovery_arrays = {
        "team_won": discovery["team_won"].astype(bool).values,
        "opp_won": discovery["opp_won"].astype(bool).values,
        "team_decimal_odds": discovery["team_decimal_odds"].astype(float).values,
        "opp_decimal_odds": discovery["opp_decimal_odds"].astype(float).values,
        "team_implied_prob": discovery["team_implied_prob"].astype(float).values,
        "opp_implied_prob": discovery["opp_implied_prob"].astype(float).values,
        "back_pnl": discovery["back_pnl"].astype(float).values,
        "fade_pnl": discovery["fade_pnl"].astype(float).values,
    }

    quick_rows = []
    for spec in specs:
        base_key = (
            f"hot_{spec['streak_threshold']}"
            if spec["thesis"].endswith("hot")
            else f"cold_{spec['streak_threshold']}"
        )
        mask = (
            discovery_masks["base"][base_key]
            & discovery_masks["team_role"][spec["team_role"]]
            & discovery_masks["location"][spec["location"]]
            & discovery_masks["implied_band"][spec["implied_band"]]
            & discovery_masks["wp_last6_bucket"][spec["wp_last6_bucket"]]
            & discovery_masks["opp_streak_bucket"][spec["opp_streak_bucket"]]
            & discovery_masks["season_phase"][spec["season_phase"]]
        )
        n_mask = int(mask.sum())
        if n_mask < MIN_SCAN_N:
            continue

        win_col, odds_col, implied_col, pnl_col = _bet_columns_for_thesis(spec["thesis"])
        metrics = summarize_market_arrays(
            wins=discovery_arrays[win_col][mask],
            odds=discovery_arrays[odds_col][mask],
            implied=discovery_arrays[implied_col][mask],
            pnl=discovery_arrays[pnl_col][mask],
            include_bootstrap=False,
        )
        row = dict(spec)
        row["label"] = _candidate_label(spec)
        row.update(metrics)
        quick_rows.append(row)

    quick_df = pd.DataFrame(quick_rows)
    if quick_df.empty:
        return (
            {"scan_size": len(specs), "eligible_candidates": 0, "shortlist_size": 0},
            {"top_by_thesis": {}, "gate_passers": []},
            [],
            [],
        )

    shortlist_idx: set[int] = set()
    for thesis in THESES:
        subset = quick_df[(quick_df["thesis"] == thesis) & (quick_df["n"] >= MIN_GATE_N)].copy()
        subset = subset.sort_values(
            ["roi", "actual_minus_implied", "n"],
            ascending=[False, False, False],
        )
        shortlist_idx.update(subset.head(DISCOVERY_TOP_PER_THESIS).index.tolist())
        strong_wilson = subset[subset["wilson_lo"] > subset["break_even"]]
        shortlist_idx.update(strong_wilson.index.tolist())

    shortlisted = []
    for idx in sorted(shortlist_idx):
        spec = {
            key: quick_df.loc[idx, key]
            for key in (
                "thesis",
                "streak_threshold",
                "team_role",
                "location",
                "implied_band",
                "wp_last6_bucket",
                "opp_streak_bucket",
                "season_phase",
            )
        }
        shortlisted.append(_candidate_metrics(discovery, spec, include_bootstrap=True))

    shortlist_df = pd.DataFrame(shortlisted).sort_values(
        ["passes_gate", "roi", "actual_minus_implied", "n"],
        ascending=[False, False, False, False],
    )

    gate_passers = shortlist_df[shortlist_df["passes_gate"]].copy()
    top_by_thesis: dict[str, list[dict[str, Any]]] = {}
    validation_specs: list[dict[str, Any]] = []
    for thesis in THESES:
        thesis_top = shortlist_df[shortlist_df["thesis"] == thesis].head(3)
        top_by_thesis[thesis] = [_serialize_metrics(row) for row in thesis_top.to_dict("records")]
        validation_specs.extend(
            {
                key: row[key]
                for key in (
                    "thesis",
                    "streak_threshold",
                    "team_role",
                    "location",
                    "implied_band",
                    "wp_last6_bucket",
                    "opp_streak_bucket",
                    "season_phase",
                )
            }
            for _, row in thesis_top.iterrows()
        )
    validation_specs.extend(
        {
            key: row[key]
            for key in (
                "thesis",
                "streak_threshold",
                "team_role",
                "location",
                "implied_band",
                "wp_last6_bucket",
                "opp_streak_bucket",
                "season_phase",
            )
        }
        for _, row in gate_passers.iterrows()
    )

    dedup_specs = []
    seen = set()
    for spec in validation_specs:
        key = tuple(spec.items())
        if key in seen:
            continue
        seen.add(key)
        dedup_specs.append(spec)

    validation_rows = []
    for spec in dedup_specs:
        discovery_metrics = _candidate_metrics(discovery, spec, include_bootstrap=True)
        test_metrics = _candidate_metrics(test, spec, include_bootstrap=True)
        live_metrics = _candidate_metrics(live, spec, include_bootstrap=True)
        survives = bool(
            discovery_metrics["passes_gate"]
            and (test_metrics["n"] or 0) >= MIN_GATE_N
            and (live_metrics["n"] or 0) >= MIN_GATE_N
            and (test_metrics["roi"] or -999) > 0
            and (live_metrics["roi"] or -999) > 0
            and (test_metrics["actual_minus_implied"] or -999) > 0
            and (live_metrics["actual_minus_implied"] or -999) > 0
        )
        validation_rows.append(
            {
                "label": discovery_metrics["label"],
                "thesis": discovery_metrics["thesis"],
                "filters": {
                    key: discovery_metrics[key]
                    for key in (
                        "streak_threshold",
                        "team_role",
                        "location",
                        "implied_band",
                        "wp_last6_bucket",
                        "opp_streak_bucket",
                        "season_phase",
                    )
                },
                "discovery": _serialize_metrics(discovery_metrics),
                "test_2024": _serialize_metrics(test_metrics),
                "live_2025": _serialize_metrics(live_metrics),
                "survives_validation": survives,
            }
        )

    survivors = [row for row in validation_rows if row["survives_validation"]]
    summary = {
        "scan_size": len(specs),
        "eligible_candidates": int(len(quick_df)),
        "shortlist_size": int(len(shortlist_df)),
        "gate_passers": int(len(gate_passers)),
        "validated_candidates": int(len(validation_rows)),
        "survivors": int(len(survivors)),
    }
    shortlist_payload = {
        "top_by_thesis": top_by_thesis,
        "gate_passers": [
            _serialize_metrics(row)
            for row in gate_passers.head(10).to_dict("records")
        ],
    }
    return summary, shortlist_payload, validation_rows, survivors


def _row_by_bucket(rows: list[dict[str, Any]], bucket: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("bucket") == bucket:
            return row
    return None


def build_verdict(
    raw_tables: dict[str, Any],
    pricing_tables: dict[str, Any],
    validation_rows: list[dict[str, Any]],
    survivors: list[dict[str, Any]],
) -> dict[str, Any]:
    main_raw = raw_tables["main"]["threshold"]
    main_pricing = pricing_tables["main"]["overall"]["threshold"]
    recent_pricing = pricing_tables["recent"]["overall"]["threshold"]

    w3_raw = _row_by_bucket(main_raw, "W3+")
    l3_raw = _row_by_bucket(main_raw, "L3+")
    w3_price = _row_by_bucket(main_pricing, "W3+")
    l3_price = _row_by_bucket(main_pricing, "L3+")
    recent_w3 = _row_by_bucket(recent_pricing, "W3+")
    recent_l3 = _row_by_bucket(recent_pricing, "L3+")

    best_candidate = None
    if validation_rows:
        ranked = sorted(
            validation_rows,
            key=lambda row: (
                row["discovery"].get("passes_gate", False),
                min(
                    row["test_2024"].get("n") or 0,
                    row["live_2025"].get("n") or 0,
                ),
                (row["test_2024"].get("roi") or -999)
                + (row["live_2025"].get("roi") or -999),
                row["discovery"].get("roi") or -999,
            ),
            reverse=True,
        )
        best_candidate = ranked[0]

    if survivors:
        headline = "research_champion_found"
        promotion = "do_not_promote_yet_follow_up_refinement_only"
    else:
        headline = "no_validated_streak_ml_champion"
        promotion = "do_not_promote"

    reasons = []
    if w3_price and w3_price["back_roi"] is not None and w3_price["back_roi"] < 0:
        reasons.append("hot teams win a bit more often, but backing them remains negative after price")
    if (
        l3_price
        and l3_price["fade_roi"] is not None
        and l3_price["back_roi"] is not None
        and l3_price["fade_roi"] > l3_price["back_roi"]
    ):
        reasons.append("fading cold teams is directionally better than backing them, but still not enough to clear vig")
    if not survivors:
        reasons.append("no discovery candidate survives frozen 2024 and live-forward 2025 checks")

    return {
        "headline": headline,
        "promotion_recommendation": promotion,
        "raw_effect": {
            "main_W3_plus": w3_raw,
            "main_L3_plus": l3_raw,
        },
        "pricing_verdict": {
            "main_W3_plus": w3_price,
            "main_L3_plus": l3_price,
            "recent_W3_plus": recent_w3,
            "recent_L3_plus": recent_l3,
        },
        "research_champion": survivors[0] if survivors else best_candidate,
        "survivor_count": len(survivors),
        "reasons": reasons,
    }


def render_report(
    *,
    slices: dict[str, dict[str, Any]],
    raw_tables: dict[str, Any],
    pricing_tables: dict[str, Any],
    candidate_summary: dict[str, Any],
    shortlist_payload: dict[str, Any],
    verdict: dict[str, Any],
) -> str:
    """Render the short markdown report required by the session plan."""
    w3_raw = verdict["raw_effect"]["main_W3_plus"]
    l3_raw = verdict["raw_effect"]["main_L3_plus"]
    w3_price = verdict["pricing_verdict"]["main_W3_plus"]
    l3_price = verdict["pricing_verdict"]["main_L3_plus"]
    champion = verdict["research_champion"]

    lines = [
        "# Session 42 -- Streak ML Momentum",
        "",
        f"**Date**: {datetime.now().date().isoformat()}",
        "**Scope**: ML-only streak continuation, market-pricing, and narrow edge search.",
        f"**Headline verdict**: **{verdict['headline'].replace('_', ' ')}**.",
        "",
        "## TL;DR",
        "",
    ]
    if w3_raw and l3_raw and w3_price and l3_price:
        lines.extend(
            [
                f"- Main slice `{slices['main']['season_label']}`: after `W3+`, team WR = **{w3_raw['win_rate']*100:.1f}%**; after `L3+`, team WR = **{l3_raw['win_rate']*100:.1f}%**.",
                f"- Pricing check: `W3+` back ROI = **{w3_price['back_roi']*100:+.2f}%**. `L3+` fade ROI = **{l3_price['fade_roi']*100:+.2f}%**, but fade actual-minus-implied = **{l3_price['fade_actual_minus_implied']*100:+.2f}pp**.",
                f"- Candidate scan: {candidate_summary['eligible_candidates']} eligible combos, {candidate_summary['shortlist_size']} shortlisted, {candidate_summary['gate_passers']} discovery gate passers, {candidate_summary['survivors']} validated survivors.",
            ]
        )
    else:
        lines.append("- Not enough rows to populate the headline W3+/L3+ tables.")

    if champion:
        lines.extend(
            [
                "",
                "## Best candidate",
                "",
                f"- `{champion['label']}`",
                f"- Discovery ROI: **{champion['discovery']['roi']*100:+.2f}%** on N={champion['discovery']['n']}",
                f"- Frozen 2024 ROI: **{(champion['test_2024']['roi'] or 0)*100:+.2f}%** on N={champion['test_2024']['n']}",
                f"- Live 2025 ROI: **{(champion['live_2025']['roi'] or 0)*100:+.2f}%** on N={champion['live_2025']['n']}",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Candidate scan",
                "",
                "- No shortlisted candidate survived the frozen and live-forward checks well enough to merit follow-up promotion.",
            ]
        )

    lines.extend(
        [
            "",
            "## Reasons not to promote",
            "",
        ]
    )
    for reason in verdict["reasons"]:
        lines.append(f"- {reason}")

    lines.extend(
        [
            "",
            "## Top discovery rows by thesis",
            "",
        ]
    )
    for thesis, rows in shortlist_payload["top_by_thesis"].items():
        lines.append(f"### {thesis}")
        if not rows:
            lines.append("- No eligible rows.")
            continue
        for row in rows[:3]:
            roi = row["roi"]
            lines.append(
                f"- `{row['label']}` -> N={row['n']}, ROI={roi*100:+.2f}%, "
                f"actual-minus-implied={row['actual_minus_implied']*100:+.2f}pp, "
                f"gate={'PASS' if row['passes_gate'] else 'fail'}"
            )

    return "\n".join(lines) + "\n"


def run_analysis(
    *,
    season_min: int = 2004,
    season_max: int = 2025,
    discovery_start: int = 2015,
    discovery_end: int = 2023,
    test_season: int = 2024,
    live_season: int = 2025,
    artifact_path: Path | None = DEFAULT_ARTIFACT_PATH,
    report_path: Path | None = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    _section("LOAD + ENRICH GAMES")
    enriched = _load_enriched_games(season_min, season_max)
    print(f"  Enriched games: {len(enriched):,}")
    print(
        f"  Seasons loaded: {sorted(int(s) for s in enriched['season'].dropna().unique())}"
    )

    _section("NORMALIZE TEAM-SIDE FRAME")
    side_frame = normalize_team_side_frame(enriched)
    print(f"  Team-side rows: {len(side_frame):,}")

    slices = _slice_definition(
        season_min=season_min,
        season_max=season_max,
        discovery_start=discovery_start,
        discovery_end=discovery_end,
        test_season=test_season,
        live_season=live_season,
    )

    raw_frame = side_frame.copy()
    bettable = side_frame[(~side_frame["involves_col"]) & (~side_frame["is_extreme_line"])].copy()
    print(f"  Bettable team-side rows: {len(bettable):,}")

    _section("LAYER A -- Raw streak tables")
    raw_tables = build_raw_tables(raw_frame, slices)
    w3_main = _row_by_bucket(raw_tables["main"]["threshold"], "W3+")
    l3_main = _row_by_bucket(raw_tables["main"]["threshold"], "L3+")
    if w3_main and l3_main:
        print(
            f"  Main {slices['main']['season_label']}: "
            f"W3+ WR={w3_main['win_rate']*100:.1f}% (N={w3_main['n']}) | "
            f"L3+ WR={l3_main['win_rate']*100:.1f}% (N={l3_main['n']})"
        )

    _section("LAYER B -- Pricing tables")
    pricing_tables = build_pricing_tables(bettable, slices)
    w3_price = _row_by_bucket(pricing_tables["main"]["overall"]["threshold"], "W3+")
    l3_price = _row_by_bucket(pricing_tables["main"]["overall"]["threshold"], "L3+")
    if w3_price and l3_price:
        print(
            f"  Main {slices['main']['season_label']}: "
            f"W3+ back ROI={w3_price['back_roi']*100:+.2f}% | "
            f"L3+ fade ROI={l3_price['fade_roi']*100:+.2f}%"
        )

    discovery = _slice_frame(bettable, slices["discovery"]["seasons"])
    test = _slice_frame(bettable, slices["test"]["seasons"])
    live = _slice_frame(bettable, slices["live"]["seasons"])
    candidate_summary, shortlist_payload, validation_rows, survivors = scan_candidate_filters(
        discovery=discovery,
        test=test,
        live=live,
    )

    verdict = build_verdict(
        raw_tables=raw_tables,
        pricing_tables=pricing_tables,
        validation_rows=validation_rows,
        survivors=survivors,
    )

    out = {
        "meta": {
            "script": "streak_ml_edge_discovery.py",
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "season_min": season_min,
            "season_max": season_max,
            "discovery_start": discovery_start,
            "discovery_end": discovery_end,
            "test_season": test_season,
            "live_season": live_season,
            "loaded_seasons": sorted(int(s) for s in enriched["season"].dropna().unique()),
            "analysis_windows": {
                key: {
                    "label": value["label"],
                    "season_label": value["season_label"],
                    "seasons": value["seasons"],
                }
                for key, value in slices.items()
            },
            "notes": [
                "Closing ML odds only; no intraday or Polymarket pricing.",
                "Raw tables use apply_data_filters universe; pricing and scan use bettable subset without COL/extreme lines.",
                "September retained in main analysis with separate sensitivity table.",
                "Candidate scan is staged: cheap metrics on full grid, bootstrap on a shortlist.",
            ],
        },
        "raw_tables": raw_tables,
        "pricing_tables": pricing_tables,
        "candidate_filters": {
            "summary": candidate_summary,
            "discovery_shortlist": shortlist_payload,
        },
        "validation": {
            "rows": validation_rows,
            "survivors": survivors,
        },
        "verdict": verdict,
    }

    report_text = render_report(
        slices=slices,
        raw_tables=raw_tables,
        pricing_tables=pricing_tables,
        candidate_summary=candidate_summary,
        shortlist_payload=shortlist_payload,
        verdict=verdict,
    )

    if artifact_path is not None:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=_serialize_metric_value),
            encoding="utf-8",
        )
        print(f"  Wrote artifact: {artifact_path}")

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"  Wrote report:   {report_path}")

    _section("VERDICT")
    print(f"  Headline: {verdict['headline']}")
    print(f"  Promotion: {verdict['promotion_recommendation']}")
    if verdict["research_champion"]:
        print(f"  Best candidate: {verdict['research_champion']['label']}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Session 42 -- streak ML edge discovery")
    parser.add_argument("--season-min", type=int, default=2004)
    parser.add_argument("--season-max", type=int, default=2025)
    parser.add_argument("--discovery-start", type=int, default=2015)
    parser.add_argument("--discovery-end", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--live-season", type=int, default=2025)
    parser.add_argument("--artifact-path", type=Path, default=DEFAULT_ARTIFACT_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    run_analysis(
        season_min=args.season_min,
        season_max=args.season_max,
        discovery_start=args.discovery_start,
        discovery_end=args.discovery_end,
        test_season=args.test_season,
        live_season=args.live_season,
        artifact_path=args.artifact_path,
        report_path=args.report_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
