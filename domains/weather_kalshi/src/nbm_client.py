"""NBM (National Blend of Models) QMD client for temperature percentiles.

Fetches MaxT/MinT percentile distributions from NOAA's NBM QMD GRIB2 files
via byte-range HTTP requests. No herbie dependency needed — uses direct
NOMADS access with cfgrib for GRIB2 parsing.

NBM QMD provides P1-P99 percentiles for temperature, pre-calibrated by NOAA
from ~10 models (200+ ensemble members). This is a strict upgrade over
single-model GEFS ensemble spread.

Key details:
  - QMD files on NOMADS: blend.t{cycle}z.qmd.f{fxx:03d}.co.grib2
  - MaxT percentiles: TMP:2 m above ground:{N}% level
  - fxx mapping from 12Z cycle:
      fxx=18 → today's high (0-18h max)
      fxx=42 → tomorrow's high (24-42h max)
      fxx=66 → day-after-tomorrow's high (48-66h max)
  - Units in GRIB2: Kelvin → convert to Fahrenheit
  - One CONUS file covers all stations → download once, extract all
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import cfgrib
import httpx
import numpy as np
import pandas as pd

from .stations import POLYMARKET_STATIONS, get_station

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "nbm"

# NOMADS base URL for NBM QMD files
NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod"

# fxx offsets for MaxT from 12Z cycle
# Each covers a 18-hour window ending at the fxx hour
FXX_MAXT = {
    0: 18,   # today's high (0-18h)
    1: 42,   # tomorrow's high (24-42h)
    2: 66,   # day-after's high (48-66h)
    3: 90,   # day+3's high (72-90h)
}

# Percentiles to fetch (covers full distribution shape)
TARGET_PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]


@dataclass(frozen=True)
class NBMForecast:
    """NBM percentile forecast for a single station and target date."""

    target_date: date
    station: str
    cycle: str                       # "00", "06", "12", "18"
    fxx: int                         # forecast hour offset
    percentiles: dict[int, float]    # {10: 52.3, 25: 54.1, 50: 56.0, ...} in F
    sigma: float                     # (P90-P10)/2.56
    median: float                    # P50 in F

    @property
    def p10(self) -> float:
        return self.percentiles[10]

    @property
    def p90(self) -> float:
        return self.percentiles[90]


def _kelvin_to_fahrenheit(k: float) -> float:
    """Convert Kelvin to Fahrenheit."""
    return k * 9.0 / 5.0 - 459.67


def _build_qmd_url(run_date: date, cycle: str, fxx: int) -> tuple[str, str]:
    """Build NOMADS URLs for QMD GRIB2 and its index file."""
    date_str = run_date.strftime("%Y%m%d")
    grib = (
        f"{NOMADS_BASE}/blend.{date_str}/{cycle}/qmd/"
        f"blend.t{cycle}z.qmd.f{fxx:03d}.co.grib2"
    )
    return grib, f"{grib}.idx"


def _parse_idx(idx_text: str) -> list[dict]:
    """Parse GRIB2 index file into structured records."""
    records = []
    lines = idx_text.strip().split("\n")
    for i, line in enumerate(lines):
        parts = line.split(":")
        if len(parts) < 6:
            continue
        rec = {
            "line_num": int(parts[0]),
            "start_byte": int(parts[1]),
            "date": parts[2],
            "var": parts[3],
            "level": parts[4],
            "forecast": parts[5],
        }
        # Remaining fields (percentile level, prob, etc.)
        if len(parts) > 6:
            rec["extra"] = ":".join(parts[6:])
        # Compute end byte from next record
        if i + 1 < len(lines):
            next_parts = lines[i + 1].split(":")
            if len(next_parts) >= 2:
                rec["end_byte"] = int(next_parts[1]) - 1
        records.append(rec)
    return records


def _find_percentile_ranges(
    idx_records: list[dict],
    percentiles: list[int],
) -> dict[int, tuple[int, int | None]]:
    """Find byte ranges for TMP MaxT percentile fields in the IDX.

    Returns dict mapping percentile number to (start_byte, end_byte).
    end_byte is None for the last record in the file.
    """
    ranges = {}
    for rec in idx_records:
        if rec["var"] != "TMP":
            continue
        extra = rec.get("extra", "")
        for p in percentiles:
            if f"{p}% level" == extra.strip():
                ranges[p] = (rec["start_byte"], rec.get("end_byte"))
                break
    return ranges


def _download_and_extract(
    grib_url: str,
    byte_ranges: dict[int, tuple[int, int | None]],
    stations: dict[str, tuple[float, float]],
) -> dict[str, dict[int, float]]:
    """Download GRIB2 byte ranges and extract point values for each station.

    Args:
        grib_url: URL of the GRIB2 file.
        byte_ranges: Dict mapping percentile to (start, end) byte range.
        stations: Dict mapping station ICAO to (lat, lon).

    Returns:
        Dict mapping station ICAO to dict of percentile → temperature (F).
    """
    results: dict[str, dict[int, float]] = {st: {} for st in stations}

    with httpx.Client(timeout=60) as client:
        for pctl, (start, end) in sorted(byte_ranges.items()):
            range_val = f"bytes={start}-{end}" if end else f"bytes={start}-"
            try:
                resp = client.get(grib_url, headers={"Range": range_val})
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning(f"Failed to download P{pctl}: {e}")
                continue

            tmp_path = tempfile.mktemp(suffix=".grib2")
            try:
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)

                datasets = cfgrib.open_datasets(tmp_path)
                if not datasets:
                    logger.warning(f"No datasets parsed for P{pctl}")
                    continue

                ds = datasets[0]
                var_name = list(ds.data_vars)[0]
                lats = ds.latitude.values
                lons = ds.longitude.values  # 0-360 format

                for station, (lat, lon) in stations.items():
                    lon360 = lon % 360
                    lat_idx = int(np.argmin(np.abs(lats[:, 0] - lat)))
                    lon_idx = int(np.argmin(np.abs(lons[0, :] - lon360)))
                    val_k = float(ds[var_name].values[lat_idx, lon_idx])
                    results[station][pctl] = _kelvin_to_fahrenheit(val_k)

                ds.close()
            except Exception as e:
                logger.warning(f"Failed to parse P{pctl}: {e}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    return results


def fetch_nbm_batch(
    stations: list[str] | None = None,
    target_date: date | None = None,
    cycle: str = "12",
    days_ahead: int = 1,
) -> list[NBMForecast]:
    """Fetch NBM MaxT percentiles for multiple stations from QMD GRIB2.

    Downloads one GRIB2 file per target date, extracts all stations.
    Uses byte-range requests to download only the needed percentile fields.

    Args:
        stations: Station ICAO codes (default: POLYMARKET_STATIONS).
        target_date: The date whose MaxT we want. Default: tomorrow.
        cycle: NBM cycle hour (default "12").
        days_ahead: How many days ahead the target is from today
            (used to select fxx). Default 1 (tomorrow).

    Returns:
        List of NBMForecast, one per station with data.
    """
    if stations is None:
        stations = POLYMARKET_STATIONS

    if target_date is None:
        target_date = date.today() + timedelta(days=days_ahead)

    fxx = FXX_MAXT.get(days_ahead)
    if fxx is None:
        logger.warning(f"No fxx mapping for days_ahead={days_ahead}")
        return []

    # Run date is today (or yesterday if cycle hasn't run yet)
    run_date = date.today()

    grib_url, idx_url = _build_qmd_url(run_date, cycle, fxx)

    # Step 1: Download and parse IDX
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(idx_url)
            resp.raise_for_status()
            idx_text = resp.text
    except httpx.HTTPError:
        # Try yesterday's run if today's isn't available yet
        run_date = date.today() - timedelta(days=1)
        grib_url, idx_url = _build_qmd_url(run_date, cycle, fxx)
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(idx_url)
                resp.raise_for_status()
                idx_text = resp.text
        except httpx.HTTPError as e:
            logger.error(f"NBM QMD index not available: {e}")
            return []

    idx_records = _parse_idx(idx_text)
    byte_ranges = _find_percentile_ranges(idx_records, TARGET_PERCENTILES)

    if not byte_ranges:
        logger.error("No TMP percentile fields found in QMD index")
        return []

    if 10 not in byte_ranges or 90 not in byte_ranges or 50 not in byte_ranges:
        logger.error(f"Missing critical percentiles. Found: {sorted(byte_ranges.keys())}")
        return []

    logger.info(
        f"Fetching NBM QMD: {run_date} {cycle}Z fxx={fxx}, "
        f"{len(byte_ranges)} percentiles for {len(stations)} stations"
    )

    # Step 2: Build station coordinate lookup
    station_coords = {}
    for icao in stations:
        st = get_station(icao)
        station_coords[icao] = (st.lat, st.lon)

    # Step 3: Download and extract
    raw = _download_and_extract(grib_url, byte_ranges, station_coords)

    # Step 4: Build NBMForecast objects
    forecasts = []
    for icao, pctls in raw.items():
        if 10 not in pctls or 90 not in pctls or 50 not in pctls:
            logger.warning(f"Incomplete percentiles for {icao}: {sorted(pctls.keys())}")
            continue

        sigma = (pctls[90] - pctls[10]) / 2.56
        forecasts.append(NBMForecast(
            target_date=target_date,
            station=icao,
            cycle=cycle,
            fxx=fxx,
            percentiles=pctls,
            sigma=sigma,
            median=pctls[50],
        ))

    logger.info(f"NBM fetch complete: {len(forecasts)} stations")
    return forecasts


def fetch_nbm_percentiles(
    station_icao: str,
    target_date: date | None = None,
    cycle: str = "12",
    days_ahead: int = 1,
) -> NBMForecast | None:
    """Fetch NBM percentiles for a single station. Convenience wrapper."""
    forecasts = fetch_nbm_batch([station_icao], target_date, cycle, days_ahead)
    return forecasts[0] if forecasts else None


def nbm_to_dataframe(forecasts: list[NBMForecast]) -> pd.DataFrame:
    """Convert NBM forecasts to DataFrame for caching and analysis."""
    rows = []
    for f in forecasts:
        row = {
            "date": f.target_date,
            "station": f.station,
            "cycle": f.cycle,
            "fxx": f.fxx,
            "sigma": f.sigma,
            "median": f.median,
        }
        for p, val in sorted(f.percentiles.items()):
            row[f"p{p}"] = val
        rows.append(row)
    return pd.DataFrame(rows)


def save_nbm_snapshot(forecasts: list[NBMForecast], station: str) -> Path:
    """Save NBM data to daily cache (append + dedup on date,station).

    Mirrors openmeteo_client.save_ensemble_snapshot() pattern.
    Cache file: data/raw/nbm/nbm_{station}.parquet
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"nbm_{station}.parquet"

    new_df = nbm_to_dataframe([f for f in forecasts if f.station == station])
    if new_df.empty:
        return cache_path

    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date", "station"], keep="last")
    else:
        combined = new_df

    combined.to_parquet(cache_path, index=False)
    logger.info(
        f"Saved {len(new_df)} NBM forecasts to {cache_path} (total: {len(combined)})"
    )
    return cache_path


def load_nbm_cache(station: str) -> pd.DataFrame:
    """Load accumulated NBM data from cache. Returns empty DataFrame if none."""
    cache_path = CACHE_DIR / f"nbm_{station}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    return pd.DataFrame()
