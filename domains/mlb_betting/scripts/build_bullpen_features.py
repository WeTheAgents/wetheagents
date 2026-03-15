"""Build bullpen features from Retrosheet pitching data.

Usage:
    python scripts/build_bullpen_features.py
    python scripts/build_bullpen_features.py --use-odds-data
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bullpen_features import (
    build_bullpen_features,
    build_with_odds_data,
    save_bullpen_features,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--retrosheets-dir",
        type=Path,
        default=Path("retrosheets"),
        help="Directory with YYYYcsvs.zip archives",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/retrosheet"),
        help="Output directory",
    )
    p.add_argument("--short", type=int, default=5, help="Short window (team games)")
    p.add_argument("--long", type=int, default=15, help="Long window (team games)")
    p.add_argument("--close-window", type=int, default=20, help="Close-game rolling window")
    p.add_argument(
        "--use-odds-data",
        action="store_true",
        help="Use odds data for close-game win% (more reliable scores)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("Building bullpen features from Retrosheet...")

    if args.use_odds_data:
        df = build_with_odds_data(
            retrosheets_dir=args.retrosheets_dir,
            short_window=args.short,
            long_window=args.long,
            close_game_window=args.close_window,
        )
    else:
        df = build_bullpen_features(
            retrosheets_dir=args.retrosheets_dir,
            short_window=args.short,
            long_window=args.long,
            close_game_window=args.close_window,
        )

    out_path = save_bullpen_features(df, output_dir=args.out)
    logger.info(f"Done. Output: {out_path}")

    # Quick stats
    logger.info(f"Rows: {len(df)}, Teams: {df['team'].nunique()}")
    logger.info(f"Seasons: {sorted(df['season'].unique())}")
    for col in ["bp_whip_short", "bp_kbb_short", "bp_close_win_pct", "bp_ip_3d"]:
        if col in df.columns:
            non_null = df[col].notna().sum()
            logger.info(f"  {col}: {non_null}/{len(df)} non-null ({100*non_null/len(df):.1f}%)")


if __name__ == "__main__":
    main()
