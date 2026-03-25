"""Download Polymarket weather temperature market data.

Usage:
    python scripts/download_polymarket_data.py --city chicago --last 7
    python scripts/download_polymarket_data.py --city nyc --start 2026-03-01 --end 2026-03-24
    python scripts/download_polymarket_data.py --all --last 30
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from src.polymarket_client import (
    build_weather_df,
    fetch_weather_events,
    load_weather_data,
    save_weather_data,
)
from src.stations import POLYMARKET_SLUG_TO_ICAO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CITIES = list(POLYMARKET_SLUG_TO_ICAO.keys())  # ["nyc", "chicago", "miami"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Polymarket weather data")
    parser.add_argument("--city", choices=CITIES, help="City slug (nyc, chicago, miami)")
    parser.add_argument("--all", action="store_true", help="All three cities")
    parser.add_argument("--start", type=date.fromisoformat, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="End date (YYYY-MM-DD)")
    parser.add_argument("--last", type=int, help="Last N days (shorthand)")
    parser.add_argument("--append", action="store_true", help="Append to existing data")
    args = parser.parse_args()

    # Determine cities
    if args.all:
        cities = CITIES
    elif args.city:
        cities = [args.city]
    else:
        parser.error("Specify --city or --all")

    # Determine date range
    if args.last:
        end = date.today()
        start = end - timedelta(days=args.last - 1)
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        parser.error("Specify --last N or --start/--end dates")

    logger.info("Fetching %s from %s to %s", cities, start, end)

    # Fetch events
    all_events = []
    for city in cities:
        logger.info("--- %s (%s) ---", city.upper(), POLYMARKET_SLUG_TO_ICAO[city])
        events = fetch_weather_events(city, start, end)
        all_events.extend(events)
        logger.info("  %d events fetched", len(events))

    if not all_events:
        logger.warning("No events found!")
        return

    # Build DataFrame
    df = build_weather_df(all_events)

    # Optionally append to existing
    if args.append:
        try:
            existing = load_weather_data()
            df = existing[~existing["event_slug"].isin(df["event_slug"])].copy()
            df = existing._append(df, ignore_index=True)
            logger.info("Appended to existing data: %d total rows", len(df))
        except FileNotFoundError:
            pass

    # Save
    path = save_weather_data(df)

    # Summary
    print(f"\n{'='*60}")
    print(f"Downloaded {len(all_events)} events, {len(df)} bracket rows")
    print(f"Stations: {df['station'].unique().tolist()}")
    print(f"Date range: {df['market_date'].min()} to {df['market_date'].max()}")
    print(f"Total volume: ${df.groupby('event_slug')['volume'].first().sum():,.0f}")
    print(f"Saved to: {path}")

    # Bracket structure summary
    for station in df["station"].unique():
        sdf = df[df["station"] == station]
        dates = sdf["market_date"].nunique()
        brackets_per_day = len(sdf) / dates if dates > 0 else 0
        print(f"  {station}: {dates} days, {brackets_per_day:.0f} brackets/day")


if __name__ == "__main__":
    main()
