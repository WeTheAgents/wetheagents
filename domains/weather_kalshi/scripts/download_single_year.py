"""Download a single year of KNYC data for testing.

Uses bulk CSV for MOS (fast) and per-day JSON for obs (slow but reliable).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stations import get_station

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_URL = "https://mesonet.agron.iastate.edu"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
station = get_station("KNYC")
YEAR = 2024


def download_mos():
    """Download MOS forecasts for one year via bulk CSV."""
    out_dir = DATA_DIR / "raw" / "mos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{station.icao}_GFS_{YEAR}.csv"

    if out_path.exists():
        logger.info(f"MOS already exists: {out_path.name}")
        return out_path

    logger.info(f"Downloading MOS {station.icao} GFS {YEAR}...")
    resp = httpx.get(
        f"{BASE_URL}/cgi-bin/request/mos.py",
        params={
            "station": station.icao,
            "model": "GFS",
            "year1": str(YEAR),
            "month1": "1",
            "day1": "1",
            "hour1": "0",
            "year2": str(YEAR),
            "month2": "12",
            "day2": "31",
            "hour2": "23",
            "format": "csv",
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    out_path.write_text(resp.text, encoding="utf-8")
    lines = resp.text.count("\n")
    logger.info(f"Saved {lines} lines to {out_path.name}")
    return out_path


def download_obs():
    """Download daily observations for one year via JSON API."""
    out_dir = DATA_DIR / "raw" / "obs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{station.iem_station_id}_{YEAR}.parquet"

    if out_path.exists():
        logger.info(f"Obs already exists: {out_path.name}")
        return out_path

    logger.info(f"Downloading obs {station.iem_station_id} {YEAR}...")
    records = []
    current = date(YEAR, 1, 1)
    end = date(YEAR, 12, 31)
    total_days = (end - current).days + 1

    while current <= end:
        day_num = (current - date(YEAR, 1, 1)).days + 1
        if day_num % 30 == 0:
            logger.info(f"  Progress: {day_num}/{total_days} days...")

        try:
            resp = httpx.get(
                f"{BASE_URL}/api/1/daily.json",
                params={
                    "station": station.iem_station_id,
                    "network": station.iem_network,
                    "date": current.isoformat(),
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "data" in data and data["data"]:
                records.extend(data["data"])
        except Exception as e:
            logger.warning(f"  Failed {current}: {e}")

        time.sleep(0.5)  # Rate limit
        current += timedelta(days=1)

    df = pd.DataFrame(records)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} obs days to {out_path.name}")
    return out_path


def build_and_test():
    """Build forecast-obs pairs and run quick bias check."""
    from src.data_loader import build_forecast_obs_pairs, save_pairs

    logger.info("Building forecast-obs pairs...")
    pairs = build_forecast_obs_pairs(station, model="GFS")

    if pairs.empty:
        logger.error("No pairs built!")
        return

    save_pairs(pairs, station)
    logger.info(f"\nPairs: {len(pairs)} days")
    logger.info(f"Date range: {pairs['date'].min()} to {pairs['date'].max()}")
    logger.info(f"Mean error (high): {pairs['error_high'].mean():+.2f}F")
    logger.info(f"Std error (high): {pairs['error_high'].std():.2f}F")
    logger.info(f"MAE (high): {pairs['abs_error_high'].mean():.2f}F")
    logger.info(f"P(forecast too high): {(pairs['error_high'] > 0).mean():.1%}")

    # Quick monthly breakdown
    logger.info("\nMonthly bias (high temp):")
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for month in range(1, 13):
        m = pairs[pairs["month"] == month]
        if len(m) > 0:
            logger.info(
                f"  {month_names[month]:>3}: bias={m['error_high'].mean():+.2f}F, "
                f"MAE={m['abs_error_high'].mean():.2f}F, "
                f"P(high)={( m['error_high'] > 0).mean():.1%}, "
                f"n={len(m)}"
            )


def main():
    logger.info(f"=== KNYC Single Year Download ({YEAR}) ===")
    download_mos()
    download_obs()
    build_and_test()
    logger.info("\nDone!")


if __name__ == "__main__":
    main()
