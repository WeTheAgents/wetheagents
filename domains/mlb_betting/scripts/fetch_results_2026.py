"""Capture game results (scores + innings) from ESPN for yesterday's MLB games.

Merges with pre-captured odds and pitcher snapshots, exports xlsx.
Run once per day in the morning (after all games finished).

Usage:
    python scripts/fetch_results_2026.py              # yesterday's games
    python scripts/fetch_results_2026.py --date 2026-03-27  # specific date
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.orchestrator import run_postgame


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture MLB game results")
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to fetch (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    dt = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    count = run_postgame(dt)
    print(f"Results captured: {count} game rows for {dt}")


if __name__ == "__main__":
    main()
