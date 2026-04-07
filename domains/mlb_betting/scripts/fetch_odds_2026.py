"""Capture pre-game odds from ESPN for today's MLB games.

Run multiple times before first pitch to ensure odds are captured.
Saves snapshots to data/raw/odds_2026/pregame_YYYYMMDD.json.
Later snapshots overwrite earlier ones (latest odds = best approximation of closing line).

Usage:
    python scripts/fetch_odds_2026.py              # today
    python scripts/fetch_odds_2026.py --date 2026-03-28  # specific date
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.orchestrator import run_pregame


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture MLB pre-game odds")
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
    count = run_pregame(dt)
    print(f"Odds captured: {count} rows for {dt}")


if __name__ == "__main__":
    main()
