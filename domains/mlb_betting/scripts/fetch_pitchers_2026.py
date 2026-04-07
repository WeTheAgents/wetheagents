"""Capture probable starting pitchers from ESPN for today's MLB games.

Resolves handedness via MLB Stats API and caches results.
Run once per day, before games start.

Usage:
    python scripts/fetch_pitchers_2026.py
    python scripts/fetch_pitchers_2026.py --date 2026-03-28
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.orchestrator import run_pitchers


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture MLB probable pitchers")
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to fetch (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    dt = date.fromisoformat(args.date) if args.date else date.today()
    count = run_pitchers(dt)
    print(f"Pitchers captured: {count} rows for {dt}")


if __name__ == "__main__":
    main()
