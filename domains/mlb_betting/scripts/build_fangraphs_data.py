"""Build team batting data (wRC+, OBP) from Retrosheet boxscore CSVs.

Usage:
    python scripts/build_fangraphs_data.py
    python scripts/build_fangraphs_data.py --start 2010 --end 2025
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fangraphs_data import (
    build_team_batting_all_seasons,
    save_team_batting,
    validate_team_batting,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2010, help="First season (inclusive)")
    p.add_argument("--end", type=int, default=2025, help="Last season (inclusive)")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/fangraphs"),
        help="Output directory",
    )
    # --delay kept for CLI compatibility but unused (no API calls needed)
    p.add_argument("--delay", type=float, default=2.0, help="(unused, kept for compatibility)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    seasons = list(range(args.start, args.end + 1))
    logger.info(f"Building team batting for seasons: {seasons[0]}..{seasons[-1]}")

    df = build_team_batting_all_seasons(seasons)

    # Validate
    report = validate_team_batting(df)
    logger.info(f"Validation: {report}")

    # Save
    out_path = save_team_batting(df, output_dir=args.out)
    logger.info(f"Done. Output: {out_path}")


if __name__ == "__main__":
    main()
