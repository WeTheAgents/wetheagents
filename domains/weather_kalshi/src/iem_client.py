"""IEM (Iowa Environmental Mesonet) API client for MOS forecasts and daily observations.

Two data sources:
  1. MOS Archive: GFS model output statistics (forecast high/low temps)
     Endpoint: /api/1/mos.json
     Available: Dec 2003 - present

  2. Daily Climate Summary: observed max/min temperatures
     Endpoint: /api/1/daily.json
     Available: varies by station (NYC since 1943)

Rate limiting: 1 second between requests to be polite to IEM servers.
Idempotent: skips download if output file already exists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from .stations import Station, get_station

logger = logging.getLogger(__name__)

BASE_URL = "https://mesonet.agron.iastate.edu"
MOS_ENDPOINT = f"{BASE_URL}/api/1/mos.json"
DAILY_ENDPOINT = f"{BASE_URL}/api/1/daily.json"

# Rate limit: minimum seconds between requests
RATE_LIMIT_SECONDS = 1.0
_last_request_time = 0.0


def _rate_limit() -> None:
    """Enforce minimum delay between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def download_mos_year(
    station: Station,
    year: int,
    model: str = "GFS",
    output_dir: Path | None = None,
) -> Path:
    """Download MOS forecasts for one station-year.

    Iterates day-by-day through each model run (00Z and 12Z) for the year,
    collecting all forecast data. Saves as parquet.

    Args:
        station: Station metadata.
        year: Calendar year to download.
        model: NWP model name (GFS, NAM, NBS).
        output_dir: Directory for output files.

    Returns:
        Path to saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "mos"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{station.icao}_{model}_{year}.parquet"
    if out_path.exists():
        logger.info(f"Skipping {out_path.name} (already exists)")
        return out_path

    logger.info(f"Downloading MOS {station.icao} {model} {year}...")

    all_records = []
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    # For each day, request 00Z and 12Z model runs
    current = start
    while current <= end:
        for hour in [0, 12]:
            runtime_str = f"{current:%Y-%m-%d} {hour:02d}:00Z"
            _rate_limit()

            try:
                resp = httpx.get(
                    MOS_ENDPOINT,
                    params={
                        "station": station.icao,
                        "model": model,
                        "runtime": runtime_str,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()

                if "data" in data:
                    for row in data["data"]:
                        row["runtime_str"] = runtime_str
                    all_records.extend(data["data"])

            except (httpx.HTTPError, json.JSONDecodeError) as e:
                logger.warning(f"Failed {station.icao} {runtime_str}: {e}")

        current += timedelta(days=1)

    if not all_records:
        logger.warning(f"No MOS data for {station.icao} {model} {year}")
        # Save empty parquet so we don't re-download
        pd.DataFrame().to_parquet(out_path)
        return out_path

    df = pd.DataFrame(all_records)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} rows to {out_path.name}")
    return out_path


def download_mos_bulk(
    station: Station,
    model: str = "GFS",
    output_dir: Path | None = None,
) -> Path:
    """Download MOS forecasts using the bulk CSV endpoint (much faster).

    Uses the cgi-bin request endpoint which supports date ranges.
    Downloads one file per station covering all available years.

    Args:
        station: Station metadata.
        model: NWP model name (GFS, NAM, NBS).
        output_dir: Directory for output files.

    Returns:
        Path to saved CSV file.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "mos"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{station.icao}_{model}_all.csv"
    if out_path.exists():
        logger.info(f"Skipping {out_path.name} (already exists)")
        return out_path

    logger.info(f"Downloading bulk MOS {station.icao} {model}...")
    _rate_limit()

    today = date.today()
    try:
        resp = httpx.get(
            f"{BASE_URL}/cgi-bin/request/mos.py",
            params={
                "station": station.icao,
                "model": model,
                "year1": "2003",
                "month1": "12",
                "day1": "1",
                "hour1": "0",
                "year2": str(today.year),
                "month2": str(today.month),
                "day2": str(today.day),
                "hour2": "0",
                "format": "csv",
            },
            timeout=300.0,  # Large download, may take minutes
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(
            f"Bulk MOS download failed for {station.icao}: {e}. "
            f"Try download_mos_year() for per-year fallback."
        )
        raise

    out_path.write_text(resp.text, encoding="utf-8")
    line_count = resp.text.count("\n")
    logger.info(f"Saved {line_count} lines to {out_path.name}")
    return out_path


def download_obs_year(
    station: Station,
    year: int,
    output_dir: Path | None = None,
) -> Path:
    """Download daily observed temperatures for one station-year.

    Args:
        station: Station metadata.
        year: Calendar year.
        output_dir: Directory for output files.

    Returns:
        Path to saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "obs"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{station.iem_station_id}_{year}.parquet"
    if out_path.exists():
        logger.info(f"Skipping {out_path.name} (already exists)")
        return out_path

    logger.info(f"Downloading obs {station.iem_station_id} {year}...")

    all_records = []
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    current = start

    while current <= end:
        _rate_limit()
        try:
            resp = httpx.get(
                DAILY_ENDPOINT,
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
                all_records.extend(data["data"])

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning(f"Failed obs {station.iem_station_id} {current}: {e}")

        current += timedelta(days=1)

    if not all_records:
        logger.warning(f"No obs data for {station.iem_station_id} {year}")
        pd.DataFrame().to_parquet(out_path)
        return out_path

    df = pd.DataFrame(all_records)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} rows to {out_path.name}")
    return out_path


def download_obs_bulk(
    station: Station,
    start_year: int = 2004,
    end_year: int | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Download daily observations using per-day JSON API.

    The bulk CSV endpoint (daily.py) does not return temperature columns for
    some stations (e.g., NYC/Central Park). The JSON API (/api/1/daily.json)
    works reliably. Downloads year by year with progress reporting.

    Args:
        station: Station metadata.
        start_year: First year to download.
        end_year: Last year (defaults to current year).
        output_dir: Directory for output files.

    Returns:
        Path to saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "obs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if end_year is None:
        end_year = date.today().year

    # Check if merged file already exists
    merged_path = output_dir / f"{station.iem_station_id}_obs_all.parquet"
    if merged_path.exists():
        logger.info(f"Skipping {merged_path.name} (already exists)")
        return merged_path

    # Download year by year (each year is idempotent)
    for year in range(start_year, end_year + 1):
        download_obs_year(station, year, output_dir)

    # Merge all years into one file
    year_files = sorted(output_dir.glob(f"{station.iem_station_id}_*.parquet"))
    year_files = [f for f in year_files if "obs_all" not in f.name]

    if not year_files:
        logger.warning(f"No obs data downloaded for {station.iem_station_id}")
        pd.DataFrame().to_parquet(merged_path)
        return merged_path

    dfs = []
    for f in year_files:
        try:
            part = pd.read_parquet(f)
            if not part.empty:
                dfs.append(part)
        except Exception as e:
            logger.warning(f"Failed to load {f.name}: {e}")

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        merged.to_parquet(merged_path, index=False)
        logger.info(f"Merged {len(merged)} obs days to {merged_path.name}")
    else:
        pd.DataFrame().to_parquet(merged_path)

    return merged_path


# --- Async obs download (5x faster) ---

ASYNC_CONCURRENCY = 5  # Max concurrent requests to IEM
ASYNC_DELAY = 0.25  # Seconds between dispatching requests


async def _fetch_obs_day(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    station: Station,
    day: date,
) -> list[dict]:
    """Fetch a single day's observations asynchronously."""
    async with semaphore:
        await asyncio.sleep(ASYNC_DELAY)
        try:
            resp = await client.get(
                DAILY_ENDPOINT,
                params={
                    "station": station.iem_station_id,
                    "network": station.iem_network,
                    "date": day.isoformat(),
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "data" in data and data["data"]:
                return data["data"]
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning(f"Failed obs {station.iem_station_id} {day}: {e}")
    return []


async def download_obs_year_async(
    station: Station,
    year: int,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    output_dir: Path | None = None,
) -> Path:
    """Download daily obs for one station-year using async concurrency."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "obs"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{station.iem_station_id}_{year}.parquet"
    if out_path.exists():
        logger.info(f"Skipping {out_path.name} (already exists)")
        return out_path

    logger.info(f"Downloading obs {station.iem_station_id} {year} (async)...")

    start = date(year, 1, 1)
    end = date(year, 12, 31)
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)

    tasks = [_fetch_obs_day(client, semaphore, station, d) for d in days]
    results = await asyncio.gather(*tasks)

    all_records = []
    for records in results:
        all_records.extend(records)

    if not all_records:
        logger.warning(f"No obs data for {station.iem_station_id} {year}")
        pd.DataFrame().to_parquet(out_path)
        return out_path

    df = pd.DataFrame(all_records)
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(df)} rows to {out_path.name}")
    return out_path


async def download_obs_bulk_async(
    station: Station,
    start_year: int = 2004,
    end_year: int | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Download observations using async concurrent requests (~5x faster).

    Uses httpx.AsyncClient with a semaphore to limit concurrency.
    Same output format as download_obs_bulk (per-year parquet + merged file).
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "obs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if end_year is None:
        end_year = date.today().year

    merged_path = output_dir / f"{station.iem_station_id}_obs_all.parquet"
    if merged_path.exists():
        logger.info(f"Skipping {merged_path.name} (already exists)")
        return merged_path

    semaphore = asyncio.Semaphore(ASYNC_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        for year in range(start_year, end_year + 1):
            await download_obs_year_async(station, year, client, semaphore, output_dir)

    # Merge all years into one file
    year_files = sorted(output_dir.glob(f"{station.iem_station_id}_*.parquet"))
    year_files = [f for f in year_files if "obs_all" not in f.name]

    if not year_files:
        logger.warning(f"No obs data downloaded for {station.iem_station_id}")
        pd.DataFrame().to_parquet(merged_path)
        return merged_path

    dfs = []
    for f in year_files:
        try:
            part = pd.read_parquet(f)
            if not part.empty:
                dfs.append(part)
        except Exception as e:
            logger.warning(f"Failed to load {f.name}: {e}")

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        merged.to_parquet(merged_path, index=False)
        logger.info(f"Merged {len(merged)} obs days to {merged_path.name}")
    else:
        pd.DataFrame().to_parquet(merged_path)

    return merged_path
