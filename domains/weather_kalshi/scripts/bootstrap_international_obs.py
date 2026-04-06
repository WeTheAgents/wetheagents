"""Bootstrap historical observations for international cities.

One-time script to download 5 years of daily max/min temperatures
from Open-Meteo Historical Archive (ERA5-based) for all international
Polymarket cities.  This data is used by MultiModelForecaster to
learn per-(city, month) fallback sigma values.

Usage:
    python -m scripts.bootstrap_international_obs
    python -m scripts.bootstrap_international_obs --years 3
    python -m scripts.bootstrap_international_obs --city tokyo --city london
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cities import INTERNATIONAL_CITIES, get_city
from src.openmeteo_client import (
    fetch_historical_obs_sync,
    save_historical_obs,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def bootstrap(
    cities: list | None = None,
    years: int = 5,
) -> None:
    """Download historical observations for international cities.

    Args:
        cities: List of city slugs (default: all international).
        years: Years of history to fetch (default: 5).
    """
    if cities is None:
        target_cities = INTERNATIONAL_CITIES
    else:
        target_cities = [get_city(slug) for slug in cities]

    end = date.today() - timedelta(days=5)  # ERA5 has ~5 day lag
    start = date(end.year - years, end.month, end.day)

    print(f"Bootstrapping {len(target_cities)} cities, {start} to {end}")
    print(f"{'=' * 60}")

    for i, city in enumerate(target_cities, 1):
        print(f"\n[{i}/{len(target_cities)}] {city.slug}")
        try:
            temp_unit = "celsius" if city.unit == "C" else "fahrenheit"
            df = fetch_historical_obs_sync(
                city.lat, city.lon,
                start_date=start,
                end_date=end,
                temperature_unit=temp_unit,
                timezone=city.timezone,
            )
            if df.empty:
                logger.warning(f"  No data returned for {city.slug}")
                continue

            path = save_historical_obs(df, city.slug)
            temp_max_mean = df["temp_max"].mean()
            temp_max_std = df["temp_max"].std()
            unit = city.unit
            print(
                f"  {len(df)} days saved to {path.name}"
                f"  (mean={temp_max_mean:.1f}{unit}, std={temp_max_std:.1f}{unit})"
            )
        except Exception as e:
            logger.error(f"  Failed for {city.slug}: {e}")

        # Respect rate limits (free tier: 600/min)
        if i < len(target_cities):
            time.sleep(0.2)

    print(f"\n{'=' * 60}")
    print("Bootstrap complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap historical obs for international cities",
    )
    parser.add_argument(
        "--years", type=int, default=5,
        help="Years of history to fetch (default: 5)",
    )
    parser.add_argument(
        "--city", type=str, action="append", default=None,
        help="Specific city slug(s) to fetch (default: all international)",
    )
    args = parser.parse_args()
    bootstrap(cities=args.city, years=args.years)


if __name__ == "__main__":
    main()
