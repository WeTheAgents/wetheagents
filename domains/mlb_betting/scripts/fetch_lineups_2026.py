"""Capture live 2026 lineup / inning-1 BABIP history from MLB Stats API.

Usage:
    python scripts/fetch_lineups_2026.py
    python scripts/fetch_lineups_2026.py --date 2026-04-16
    python scripts/fetch_lineups_2026.py --backfill 2026-03-27 2026-04-16
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.mlb_lineups import run_lineup_backfill, run_lineup_fetch


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch MLB 2026 lineup / BABIP data")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to fetch (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        help="Backfill a date range: START END (YYYY-MM-DD)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.backfill:
        start = date.fromisoformat(args.backfill[0])
        end = date.fromisoformat(args.backfill[1])
        count = run_lineup_backfill(start, end)
        print(f"Lineup backfill complete: {count} starter batter rows ({start} -> {end})")
        return

    dt = date.fromisoformat(args.date) if args.date else date.today()
    count = run_lineup_fetch(dt)
    print(f"Lineups captured: {count} starter batter rows for {dt}")


if __name__ == "__main__":
    main()
