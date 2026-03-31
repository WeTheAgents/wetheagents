"""CLI for daily 2026 MLB data fetching.

Usage:
    # Capture pre-game odds (run before first pitch, ~2 PM ET)
    python scripts/fetch_daily_2026.py --phase pregame

    # Capture post-game results + merge with odds (run after games, ~midnight ET)
    python scripts/fetch_daily_2026.py --phase postgame

    # Backfill results for a date range (odds will be NaN for days without snapshots)
    python scripts/fetch_daily_2026.py --backfill 2026-03-27 2026-04-01

    # Specific date instead of today
    python scripts/fetch_daily_2026.py --phase pregame --date 2026-03-28
"""

import argparse
import logging
import sys
from datetime import date, timedelta

# Add project root to path
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.orchestrator import run_backfill, run_postgame, run_pregame


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch 2026 MLB season data")
    parser.add_argument(
        "--phase",
        choices=["pregame", "postgame"],
        help="Which phase to run",
    )
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
        help="Backfill date range: START END (YYYY-MM-DD)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.backfill:
        start = date.fromisoformat(args.backfill[0])
        end = date.fromisoformat(args.backfill[1])
        total = run_backfill(start, end)
        print(f"\nBackfill complete: {total} rows added ({start} → {end})")
        return

    if not args.phase:
        parser.error("Either --phase or --backfill is required")

    dt = date.fromisoformat(args.date) if args.date else date.today()

    if args.phase == "pregame":
        count = run_pregame(dt)
        print(f"\nPregame: captured {count} odds rows for {dt}")
    elif args.phase == "postgame":
        count = run_postgame(dt)
        print(f"\nPostgame: added {count} game rows for {dt}")


if __name__ == "__main__":
    main()
