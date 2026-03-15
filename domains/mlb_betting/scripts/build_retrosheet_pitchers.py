"""Build Retrosheet starter logs + entering-game pitcher features.

Usage examples:
    python scripts/build_retrosheet_pitchers.py
    python scripts/build_retrosheet_pitchers.py --start 2010 --end 2025
    python scripts/build_retrosheet_pitchers.py --start 2018 --end 2021 --out data/processed/pitchers
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Make `src` importable when running as a script: `python scripts/...`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.retrosheet_pitchers import (
    BullpenConfig,
    build_entering_features,
    build_game_id_bridge,
    build_report_markdown,
    build_starter_game_logs,
    save_outputs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=2010, help="First season (inclusive)")
    p.add_argument("--end", type=int, default=2025, help="Last season (inclusive)")
    p.add_argument(
        "--retrosheets-dir",
        type=Path,
        default=Path("retrosheets"),
        help="Directory with YYYYcsvs.zip archives",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/pitchers"),
        help="Output directory for parquet + report",
    )
    p.add_argument("--short", type=int, default=5, help="Short window (starts)")
    p.add_argument("--long", type=int, default=15, help="Long window (starts)")
    p.add_argument(
        "--bullpen-max-outs",
        type=int,
        default=12,
        help="If max outs per team-game < this → bullpen w/o designated starter (12 outs = 4.0 IP)",
    )
    p.add_argument(
        "--opener-starter-max-outs",
        type=int,
        default=6,
        help="Starter outs <= this AND bulk pitcher differs → opener game (6 outs = 2.0 IP)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    seasons = list(range(args.start, args.end + 1))
    logger.info(f"Building starter logs for seasons: {seasons[0]}..{seasons[-1]}")

    bullpen_cfg = BullpenConfig(
        no_starter_max_outs_threshold=int(args.bullpen_max_outs),
        opener_starter_max_outs=int(args.opener_starter_max_outs),
    )

    starter_logs = build_starter_game_logs(
        seasons, retrosheets_dir=args.retrosheets_dir, bullpen_cfg=bullpen_cfg
    )
    logger.info(
        f"starter_game_logs: {len(starter_logs)} rows, {starter_logs['gid'].nunique()} games"
    )

    entering = build_entering_features(starter_logs, short_window=args.short, long_window=args.long)
    logger.info(f"starter_entering_features: {len(entering)} rows")

    bridge = build_game_id_bridge(starter_logs)
    logger.info(f"game_id_bridge: {len(bridge)} rows")

    report = build_report_markdown(starter_logs, seasons=seasons)
    save_outputs(starter_logs, entering, bridge, output_dir=args.out, report_markdown=report)
    logger.info(f"Saved outputs to: {args.out.resolve()}")


if __name__ == "__main__":
    main()
