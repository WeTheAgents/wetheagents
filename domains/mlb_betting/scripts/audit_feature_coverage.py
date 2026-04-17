"""Audit MLB betting feature coverage for historical and live pipelines.

Usage:
    python scripts/audit_feature_coverage.py
    python scripts/audit_feature_coverage.py --live-date 2026-04-16
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import (
    NRFI_FEATURES_A,
    OU_FEATURES,
    OU_FEATURES_OVER,
    OU_FEATURES_V2,
    OU_FEATURES_V3,
    SPEC_FEATURES,
    build_all_features,
    build_ou_features,
    build_ou_features_over,
    build_ou_features_v2,
    build_ou_features_v3,
    build_spec_features,
    build_yrfi_features,
)
from src.live_feature_forward import forward_project_features
from src.live_pregame import load_pregame_overlay
from src.strategies import add_derived_for_strategies

WRC_MIN_COLUMNS = {"team_wrc_plus_diff", "team_obp_diff", "wrc_plus_combined"}
DEFAULT_MIN_COVERAGE = 0.65
LIVE_REQUIRED_FIELDS = [
    "home_sp_fip_short",
    "away_sp_fip_short",
    "starter_depth_diff_short",
    "fav_starter_fip_diff",
    "effective_obp_home",
    "effective_obp_away",
]
LIVE_FLAG_FIELDS = [
    "insufficient_starter_history",
    "starter_feature_source_missing",
    "insufficient_lineup_history",
    "lineup_feature_source_missing",
    "unsupported_live_yrfi_features",
]


def _coverage(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return -1.0
    if df.empty:
        return 0.0
    return float(df[col].notna().mean())


def _report_family(name: str, df: pd.DataFrame, columns: list[str]) -> list[str]:
    failures: list[str] = []
    logger.info("Family %s: %d rows", name, len(df))
    for col in columns:
        cov = _coverage(df, col)
        if cov < 0:
            failures.append(f"{name}: missing column {col}")
            logger.error("  %-32s MISSING", col)
            continue

        min_cov = 0.95 if col in WRC_MIN_COLUMNS else DEFAULT_MIN_COVERAGE
        logger.info("  %-32s %6.1f%%", col, cov * 100)
        if cov < min_cov:
            failures.append(
                f"{name}: {col} coverage {cov:.1%} below minimum {min_cov:.0%}"
            )
    return failures


def _build_historical(start_season: int, end_season: int) -> dict[str, tuple[pd.DataFrame, list[str]]]:
    games = load_all_seasons(seasons=list(range(start_season, end_season + 1)))
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)

    return {
        "SPEC": (build_spec_features(enriched=enriched), SPEC_FEATURES),
        "OU": (build_ou_features(enriched=enriched), OU_FEATURES),
        "OU_V2": (build_ou_features_v2(enriched=enriched), OU_FEATURES_V2),
        "OU_V3": (build_ou_features_v3(enriched=enriched), OU_FEATURES_V3),
        "OU_OVER": (build_ou_features_over(enriched=enriched), OU_FEATURES_OVER),
        "YRFI_NRFI": (build_yrfi_features(enriched=enriched), NRFI_FEATURES_A),
    }


def _build_live(target: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    games = load_all_seasons(seasons=[2025, 2026])
    overlay = load_pregame_overlay(target, allow_network_pitcher_fallback=False)
    mask_existing = games["date"].dt.date == target
    games = pd.concat([games.loc[~mask_existing].copy(), overlay], ignore_index=True, sort=False)
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    enriched = build_all_features(games)
    enriched = forward_project_features(enriched, target)
    enriched = add_derived_for_strategies(enriched)
    day = enriched[enriched["date"].dt.date == target].copy()

    yrfi = build_yrfi_features(enriched=day)
    return day, yrfi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2022)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--live-date", type=str, default=None)
    args = parser.parse_args()

    failures: list[str] = []
    families = _build_historical(args.start_season, args.end_season)
    for name, (df, columns) in families.items():
        failures.extend(_report_family(name, df, columns))

    if args.live_date:
        target = date.fromisoformat(args.live_date)
        live_day, live_yrfi = _build_live(target)
        logger.info("Live day %s: %d rows", target, len(live_day))
        if len(live_day) == 0:
            failures.append(f"LIVE {target}: no rows after overlay/filter pipeline")
        for col in LIVE_REQUIRED_FIELDS:
            if col not in live_day.columns:
                failures.append(f"LIVE {target}: missing column {col}")
                continue
            ok_mask = live_day[col].notna()
            if "sp_" in col or "starter_" in col:
                ok_mask = ok_mask | live_day.get("insufficient_starter_history", False) | live_day.get("starter_feature_source_missing", False)
            if "effective_obp" in col:
                ok_mask = ok_mask | live_day.get("insufficient_lineup_history", False) | live_day.get("lineup_feature_source_missing", False)
            if not bool(pd.Series(ok_mask).all()):
                failures.append(f"LIVE {target}: {col} has rows that are neither filled nor flagged")
            logger.info("  %-32s %d/%d usable-or-flagged", col, int(pd.Series(ok_mask).sum()), len(live_day))

        for col in LIVE_FLAG_FIELDS:
            if col in live_day.columns:
                logger.info("  %-32s %d/%d flagged", col, int(live_day[col].fillna(False).astype(bool).sum()), len(live_day))

        if len(live_yrfi) == 0:
            failures.append(f"LIVE {target}: build_yrfi_features returned zero rows")
        elif "unsupported_live_yrfi_features" not in live_yrfi.columns:
            failures.append(f"LIVE {target}: missing unsupported_live_yrfi_features flag")

    if failures:
        logger.error("Coverage audit failed:")
        for failure in failures:
            logger.error("  %s", failure)
        return 1

    logger.info("Coverage audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
