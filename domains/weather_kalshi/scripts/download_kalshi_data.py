"""Download Kalshi weather market data from public S3 reports.

Each daily report is 100-700MB (ALL Kalshi markets). We filter to weather-only
and save as compact parquet.

Usage:
    python scripts/download_kalshi_data.py
    python scripts/download_kalshi_data.py --start 2025-10-01 --end 2026-03-22
    python scripts/download_kalshi_data.py --last 30
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kalshi_client import download_date_range, save_weather_data

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Kalshi weather market data")
    parser.add_argument(
        "--start", type=str, default=None,
        help="Start date YYYY-MM-DD (default: 90 days ago)",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="End date YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--last", type=int, default=None,
        help="Download last N days (overrides --start)",
    )
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)

    if args.last:
        start = end - timedelta(days=args.last - 1)
    elif args.start:
        start = date.fromisoformat(args.start)
    else:
        start = end - timedelta(days=89)

    logger.info(f"Downloading Kalshi weather data: {start} to {end} ({(end - start).days + 1} days)")

    df = download_date_range(start, end)

    if df.empty:
        logger.error("No weather data found.")
        return

    # Summary
    stations = df["station"].unique()
    dates = df["market_date"].nunique()
    finalized = len(df[df["status"] == "finalized"])
    with_volume = len(df[df["volume"] > 0])

    logger.info(f"\nSummary:")
    logger.info(f"  Stations: {sorted(stations)}")
    logger.info(f"  Market dates: {dates}")
    logger.info(f"  Total rows: {len(df)}")
    logger.info(f"  Finalized: {finalized}")
    logger.info(f"  With volume > 0: {with_volume}")
    logger.info(f"  Date range: {df['market_date'].min()} to {df['market_date'].max()}")

    path = save_weather_data(df)
    logger.info(f"Saved to {path}")


if __name__ == "__main__":
    main()
