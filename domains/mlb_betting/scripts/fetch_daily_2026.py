"""CLI for daily 2026 MLB data fetching.

Usage:
    # Capture pre-game odds (run before first pitch, ~2 PM ET)
    python scripts/fetch_daily_2026.py --phase pregame

    # Capture post-game results + merge with odds (run after games, ~midnight ET)
    python scripts/fetch_daily_2026.py --phase postgame

    # Fetch pitcher boxscores (run after games complete, ~midnight ET)
    python scripts/fetch_daily_2026.py --phase boxscore

    # Run full postgame pipeline (results + boxscores in one command)
    python scripts/fetch_daily_2026.py --phase postgame-full

    # Backfill results for a date range (odds will be NaN for days without snapshots)
    python scripts/fetch_daily_2026.py --backfill 2026-03-27 2026-04-01

    # Backfill boxscores for a date range
    python scripts/fetch_daily_2026.py --backfill-boxscore 2026-03-27 2026-04-01

    # Specific date instead of today
    python scripts/fetch_daily_2026.py --phase pregame --date 2026-03-28
"""

import argparse
import logging
import sys

# Add project root to path
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.orchestrator import run_backfill, run_postgame, run_pregame
from data.fetch_2026.mlb_boxscore import run_boxscore_backfill, run_boxscore_fetch


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch 2026 MLB season data")
    parser.add_argument(
        "--phase",
        choices=["pregame", "postgame", "boxscore", "postgame-full"],
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
        help="Backfill results for a date range: START END (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--backfill-boxscore",
        nargs=2,
        metavar=("START", "END"),
        help="Backfill pitcher boxscores for a date range: START END (YYYY-MM-DD)",
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

    if args.backfill_boxscore:
        start = date.fromisoformat(args.backfill_boxscore[0])
        end = date.fromisoformat(args.backfill_boxscore[1])
        total = run_boxscore_backfill(start, end)
        print(f"\nBoxscore backfill complete: {total} pitcher lines ({start} → {end})")
        return

    if not args.phase:
        parser.error("Either --phase, --backfill, or --backfill-boxscore is required")

    dt = date.fromisoformat(args.date) if args.date else date.today()

    if args.phase == "pregame":
        count = run_pregame(dt)
        print(f"\nPregame: captured {count} odds rows for {dt}")
    elif args.phase == "postgame":
        count = run_postgame(dt)
        print(f"\nPostgame: added {count} game rows for {dt}")
    elif args.phase == "boxscore":
        count = run_boxscore_fetch(dt)
        print(f"\nBoxscore: fetched {count} pitcher lines for {dt}")
    elif args.phase == "postgame-full":
        count1 = run_postgame(dt)
        count2 = run_boxscore_fetch(dt)
        print(f"\nPostgame-full: {count1} game rows + {count2} pitcher lines for {dt}")


if __name__ == "__main__":
    from datetime import date

    main()
