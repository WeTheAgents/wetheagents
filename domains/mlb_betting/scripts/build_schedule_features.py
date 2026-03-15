"""Build travel and fatigue features from game schedule.

Usage:
    python scripts/build_schedule_features.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_loader import apply_data_filters, load_all_seasons
from src.schedule_features import compute_travel_features, save_travel_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/schedule"),
        help="Output directory",
    )
    p.add_argument(
        "--venues",
        type=Path,
        default=None,
        help="Path to venues.json (default: data/static/venues.json)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("Building travel/fatigue features...")

    games = load_all_seasons()
    games = apply_data_filters(games)
    logger.info(f"Loaded {len(games)} games")

    df = compute_travel_features(games, venues_path=args.venues)

    out_path = save_travel_features(df, output_dir=args.out)
    logger.info(f"Done. Output: {out_path}")

    # Quick stats
    logger.info(f"Rows: {len(df)}, Teams: {df['team'].nunique()}")
    for col in ["rest_days", "travel_miles_3d", "road_trip_len", "tz_changes_3d"]:
        valid = df[col].dropna()
        logger.info(f"  {col}: mean={valid.mean():.2f}, max={valid.max():.0f}")


if __name__ == "__main__":
    main()
