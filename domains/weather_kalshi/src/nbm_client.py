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

# When today's cycle has not published yet we fall back to an earlier run and
# add 24h to fxx per day back, so the valid target stays the same calendar day.
NBM_MAX_RUN_FALLBACK_DAYS = 2   # NOMADS keeps ~2 days; older dates need S3
# Largest MaxT forecast hour we may request: the deepest base horizon (90, for
# days_ahead=3) plus the full fallback shift (24h * 2 days). QMD carries MaxT
# fields well past this ("96-114"/"120-138 hour max fcst" both exist), so a
# fallback for day+3 still lands on a real windowed-max field.
NBM_MAX_FXX = 90 + 24 * NBM_MAX_RUN_FALLBACK_DAYS  # 138

# Public AWS mirror of NBM GRIB2 (full history; NOMADS is rolling ~2 days).
NBM_S3_BASE = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"

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


def _nearest_grid_cell(
    lats: np.ndarray, lons: np.ndarray, lat: float, lon: float
) -> tuple[int, int]:
    """Nearest (row, col) on a 2D lat/lon grid to a point.

    NBM CONUS is a Lambert-conformal grid: latitude/longitude are 2D and
    curvilinear, so a column is NOT constant longitude. Searching lats[:,0] and
    lons[0,:] independently (the old approach) landed hundreds of km offshore —
    e.g. KLGA resolved to the Atlantic off Maine (71F) instead of LaGuardia
    (102F). Compute the true 2D nearest neighbour instead.
    """
    lon360 = lon % 360
    dlon = (lons - lon360 + 180.0) % 360.0 - 180.0  # shortest signed lon delta
    dist2 = (lats - lat) ** 2 + dlon ** 2
    row, col = np.unravel_index(int(np.argmin(dist2)), lats.shape)
    return int(row), int(col)


def _build_qmd_url(run_date: date, cycle: str, fxx: int, source: str = "nomads") -> tuple[str, str]:
    """Build QMD GRIB2 + index URLs.

    source="nomads" -> live NOMADS server (rolling ~2 days).
    source="s3"     -> public AWS mirror (full history, for backfill).
    """
    date_str = run_date.strftime("%Y%m%d")
    rel = f"blend.{date_str}/{cycle}/qmd/blend.t{cycle}z.qmd.f{fxx:03d}.co.grib2"
    base = NBM_S3_BASE if source == "s3" else NOMADS_BASE
    grib = f"{base}/{rel}"
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
    field_marker: str = "max fcst",
) -> dict[int, tuple[int, int | None]]:
    """Find byte ranges for TMP windowed-MaxT percentile fields in the IDX.

    At a MaxT fxx the QMD file carries TWO TMP records per percentile: an
    instantaneous "{fxx} hour fcst" (the temperature AT the valid time — 06Z /
    overnight for fxx=18) and the windowed "0-{fxx} hour max fcst" (the daytime
    maximum). We must select the MAX field: matching on percentile alone grabbed
    the instantaneous overnight temp and stored it as the day's high (~16-19F too
    low; root cause of the broken archive, fixed 2026-07-07).

    Returns dict mapping percentile number to (start_byte, end_byte).
    end_byte is None for the last record in the file.
    """
    ranges = {}
    for rec in idx_records:
        if rec["var"] != "TMP":
            continue
        if field_marker not in rec.get("forecast", ""):
            continue  # skip the instantaneous "{fxx} hour fcst" field
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
    cell_cache: dict[str, tuple[int, int]] = {}  # station -> (row, col); grid is identical across percentiles

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
                vals = ds[var_name].values

                for station, (lat, lon) in stations.items():
                    if station not in cell_cache:
                        cell_cache[station] = _nearest_grid_cell(lats, lons, lat, lon)
                    lat_idx, lon_idx = cell_cache[station]
                    val_k = float(vals[lat_idx, lon_idx])
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

    base_fxx = FXX_MAXT.get(days_ahead)
    if base_fxx is None:
        logger.warning(f"No fxx mapping for days_ahead={days_ahead}")
        return []

    # Find the freshest published cycle. When today's {cycle}Z run has not
    # published yet (QMD lands ~1.5h after cycle time), fall back to an earlier
    # run AND add 24h to fxx per day so the valid target stays the same calendar
    # date. Reusing base_fxx against a stale run returns an EARLIER day's MaxT —
    # the bug that filled the snapshot archive with overnight-window maxima
    # (day-of |error| ~16-19F vs realized; fixed 2026-07-07).
    idx_text = None
    grib_url = None
    run_date = None
    fxx = None
    for back in range(NBM_MAX_RUN_FALLBACK_DAYS + 1):
        rd = date.today() - timedelta(days=back)
        fx = base_fxx + 24 * back
        if fx > NBM_MAX_FXX:
            break
        g_url, i_url = _build_qmd_url(rd, cycle, fx)
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(i_url)
                resp.raise_for_status()
                idx_text = resp.text
            run_date, fxx, grib_url = rd, fx, g_url
            if back:
                logger.info("NBM %sZ for target not out yet; using %d-day-old run at fxx=%d",
                            cycle, back, fx)
            break
        except httpx.HTTPError:
            continue
    if idx_text is None:
        logger.error("NBM QMD index not available for cycle %sZ within %d-day fallback",
                     cycle, NBM_MAX_RUN_FALLBACK_DAYS)
        return []

    forecasts = _forecasts_from_idx(grib_url, idx_text, stations, target_date, run_date, cycle, fxx)
    logger.info(f"NBM fetch complete: {len(forecasts)} stations")
    return forecasts


def _forecasts_from_idx(
    grib_url: str,
    idx_text: str,
    stations: list[str],
    target_date: date,
    run_date: date,
    cycle: str,
    fxx: int,
) -> list[NBMForecast]:
    """Parse an idx, download the percentile byte ranges, and build forecasts.

    Shared by the live NOMADS fetch and the S3 backfill (they differ only in how
    they pick the run/URL). All percentiles are for the same (run_date, fxx),
    labelled with the caller's target_date.
    """
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

    station_coords = {}
    for icao in stations:
        st = get_station(icao)
        station_coords[icao] = (st.lat, st.lon)

    raw = _download_and_extract(grib_url, byte_ranges, station_coords)

    forecasts = []
    for icao, pctls in raw.items():
        if 10 not in pctls or 90 not in pctls or 50 not in pctls:
            logger.warning(f"Incomplete percentiles for {icao}: {sorted(pctls.keys())}")
            continue
        forecasts.append(NBMForecast(
            target_date=target_date,
            station=icao,
            cycle=cycle,
            fxx=fxx,
            percentiles=pctls,
            sigma=(pctls[90] - pctls[10]) / 2.56,
            median=pctls[50],
        ))
    return forecasts


def fetch_nbm_s3(
    stations: list[str] | None = None,
    target_date: date | None = None,
    cycle: str = "12",
    days_ahead: int = 0,
) -> list[NBMForecast]:
    """Fetch NBM MaxT percentiles for a specific PAST date from the AWS mirror.

    Deterministic (no fallback): run_date = target_date - days_ahead, fxx from
    FXX_MAXT. days_ahead=0 -> that date's {cycle}Z fxx=18 = the morning-of
    forecast for the day's high (what the live pipeline sees at ~14:00 UTC).
    Used by scripts/backfill_nbm_dayof.py to repair the broken snapshot archive.
    """
    if stations is None:
        stations = POLYMARKET_STATIONS
    if target_date is None:
        raise ValueError("fetch_nbm_s3 requires an explicit target_date")

    fxx = FXX_MAXT.get(days_ahead)
    if fxx is None:
        logger.warning(f"No fxx mapping for days_ahead={days_ahead}")
        return []

    run_date = target_date - timedelta(days=days_ahead)
    grib_url, idx_url = _build_qmd_url(run_date, cycle, fxx, source="s3")
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(idx_url)
            resp.raise_for_status()
            idx_text = resp.text
    except httpx.HTTPError as e:
        logger.warning("NBM S3 idx missing for %s %sZ f%03d: %s", run_date, cycle, fxx, e)
        return []

    return _forecasts_from_idx(grib_url, idx_text, stations, target_date, run_date, cycle, fxx)


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
