"""Open-Meteo Ensemble API client for day-specific temperature uncertainty.

Fetches ensemble member forecasts from GEFS (30 members) to compute
day-specific spread (sigma) for the EnsembleForecaster.

Key insight: the ensemble spread is a proxy for day-specific forecast
uncertainty.  On quiet high-pressure days spread is ~1-2F; on frontal
days it widens to 4-6F.  This replaces the static monthly sigma.

API endpoints:
  Live ensemble: https://ensemble-api.open-meteo.com/v1/ensemble
  (No historical ensemble archive — accumulate daily snapshots locally.)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "openmeteo"

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"

# GEFS has 30 members on Open-Meteo
GEFS_N_MEMBERS = 30

# Multi-model ensemble: ~179 members total from 6 global models
MULTI_MODELS = [
    "ecmwf_ifs025",                 # 51 members, 15d, 25km
    "gfs_seamless",                 # 31 members, 10d, 25km
    "icon_seamless",                # 40 members, 7.5d, 26km
    "gem_global",                   # 21 members, 16d, 25km
    "ukmo_seamless",                # 18 members, 8d, 20km
    "bom_access_global_ensemble",   # 18 members, 10d, 40km
]


@dataclass(frozen=True)
class EnsembleForecast:
    """Ensemble forecast for a single station and target date."""

    target_date: date
    station: str
    member_highs: list[float]  # Max temp (F) per ensemble member
    mean: float
    spread: float  # Std of member_highs
    n_members: int

    @property
    def p10(self) -> float:
        return float(np.percentile(self.member_highs, 10))

    @property
    def p90(self) -> float:
        return float(np.percentile(self.member_highs, 90))

    @property
    def sigma_from_iqr(self) -> float:
        """Sigma estimated from P90-P10 spread (robust to outliers)."""
        return (self.p90 - self.p10) / 2.56


def _parse_ensemble_response(
    data: dict,
    station: str,
    model_suffix: str = "",
) -> list[EnsembleForecast]:
    """Parse Open-Meteo ensemble JSON into EnsembleForecast objects.

    Handles both single-model (no suffix) and multi-model (with suffix)
    response formats.
    """
    daily = data.get("daily", {})
    times = daily.get("time", [])

    # Determine key pattern for member columns
    if model_suffix:
        mean_key = f"temperature_2m_max_{model_suffix}"
        member_pattern = f"temperature_2m_max_member{{:02d}}_{model_suffix}"
    else:
        mean_key = "temperature_2m_max"
        member_pattern = "temperature_2m_max_member{:02d}"

    # Find how many members are present
    n_members = 0
    for i in range(1, 100):
        key = member_pattern.format(i)
        if key in daily:
            n_members = i
        else:
            break

    if n_members == 0:
        logger.warning("No ensemble members found in response")
        return []

    results = []
    for day_idx, date_str in enumerate(times):
        target = date.fromisoformat(date_str)

        members = []
        for m in range(1, n_members + 1):
            key = member_pattern.format(m)
            val = daily[key][day_idx]
            if val is not None:
                members.append(float(val))

        if len(members) < 3:
            continue

        arr = np.array(members)
        results.append(EnsembleForecast(
            target_date=target,
            station=station,
            member_highs=members,
            mean=float(np.mean(arr)),
            spread=float(np.std(arr, ddof=1)),
            n_members=len(members),
        ))

    return results


async def fetch_ensemble_forecast(
    lat: float,
    lon: float,
    station: str = "",
    forecast_days: int = 7,
    past_days: int = 3,
) -> list[EnsembleForecast]:
    """Fetch GEFS ensemble forecast from Open-Meteo.

    Returns EnsembleForecast objects for each available date.
    Typically forecast_days=7 gives ~10 days (past_days + forecast_days).

    Args:
        lat: Station latitude.
        lon: Station longitude.
        station: Station ICAO code (for labeling).
        forecast_days: Days of future forecast (default 7).
        past_days: Days of recent past data (default 3, max ~4 available).

    Returns:
        List of EnsembleForecast, one per date with valid data.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "gfs_seamless",
        "temperature_unit": "fahrenheit",
        "forecast_days": forecast_days,
        "past_days": past_days,
        "timezone": "America/New_York",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ENSEMBLE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    return _parse_ensemble_response(data, station)


def fetch_ensemble_forecast_sync(
    lat: float,
    lon: float,
    station: str = "",
    forecast_days: int = 7,
    past_days: int = 3,
) -> list[EnsembleForecast]:
    """Synchronous wrapper for fetch_ensemble_forecast."""
    return asyncio.run(
        fetch_ensemble_forecast(lat, lon, station, forecast_days, past_days)
    )


def ensemble_to_dataframe(forecasts: list[EnsembleForecast]) -> pd.DataFrame:
    """Convert ensemble forecasts to a DataFrame for analysis.

    Returns DataFrame with columns:
        date, station, mean, spread, sigma_iqr, n_members, p10, p90
    """
    rows = []
    for f in forecasts:
        rows.append({
            "date": f.target_date,
            "station": f.station,
            "mean": f.mean,
            "spread": f.spread,
            "sigma_iqr": f.sigma_from_iqr,
            "n_members": f.n_members,
            "p10": f.p10,
            "p90": f.p90,
        })
    return pd.DataFrame(rows)


def save_ensemble_snapshot(
    forecasts: list[EnsembleForecast],
    station: str,
) -> Path:
    """Save ensemble data to daily cache for accumulation.

    Appends to station-level parquet file.  Deduplicates on
    (date, station) so repeated runs don't create duplicates.

    Returns path to the cache file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"ensemble_{station}.parquet"

    new_df = ensemble_to_dataframe(forecasts)
    new_df["station"] = station

    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date", "station"], keep="last")
    else:
        combined = new_df

    combined.to_parquet(cache_path, index=False)
    logger.info(f"Saved {len(new_df)} ensemble forecasts to {cache_path} (total: {len(combined)})")
    return cache_path


def load_ensemble_cache(station: str) -> pd.DataFrame:
    """Load accumulated ensemble data from cache.

    Returns empty DataFrame if no cache exists.
    """
    cache_path = CACHE_DIR / f"ensemble_{station}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Multi-model ensemble (international cities)
# ---------------------------------------------------------------------------

def _discover_model_suffixes(daily: dict) -> list[str]:
    """Auto-discover model suffixes from multi-model response keys.

    Open-Meteo transforms model names in responses (e.g. gfs_seamless ->
    ncep_gefs_seamless, ecmwf_ifs025 -> ecmwf_ifs025_ensemble).  Instead
    of hardcoding these, we extract unique suffixes from the member keys.

    Returns list of unique suffixes found.
    """
    import re
    suffixes: set[str] = set()
    for key in daily:
        m = re.match(r"temperature_2m_max_member\d+_(.+)", key)
        if m:
            suffixes.add(m.group(1))
    return sorted(suffixes)


def _pool_multimodel_forecasts(
    per_model: dict[str, list[EnsembleForecast]],
    station: str,
) -> list[EnsembleForecast]:
    """Pool members from multiple models into single EnsembleForecast per date.

    Combines all members across models for each target date, producing a
    single EnsembleForecast with ~156 members (when all models respond).
    """
    all_dates: dict[date, list[float]] = {}
    for forecasts in per_model.values():
        for ef in forecasts:
            all_dates.setdefault(ef.target_date, []).extend(ef.member_highs)

    results = []
    for target, members in sorted(all_dates.items()):
        if len(members) < 3:
            continue
        arr = np.array(members)
        results.append(EnsembleForecast(
            target_date=target,
            station=station,
            member_highs=members,
            mean=float(np.mean(arr)),
            spread=float(np.std(arr, ddof=1)),
            n_members=len(members),
        ))

    return results


async def fetch_multimodel_ensemble(
    lat: float,
    lon: float,
    station: str = "",
    models: list[str] | None = None,
    temperature_unit: str = "celsius",
    timezone: str = "UTC",
    forecast_days: int = 7,
) -> list[EnsembleForecast]:
    """Fetch multi-model ensemble forecast from Open-Meteo.

    Queries up to 6 global models in a single API call and pools all
    ensemble members into one EnsembleForecast per date (~156 members).

    Args:
        lat: Latitude.
        lon: Longitude.
        station: City slug or ICAO code (for labeling).
        models: List of Open-Meteo model names (default: MULTI_MODELS).
        temperature_unit: "celsius" or "fahrenheit".
        timezone: IANA timezone for daily aggregation window.
        forecast_days: Days of future forecast (default 7).

    Returns:
        List of EnsembleForecast, one per date with pooled members.
    """
    if models is None:
        models = MULTI_MODELS

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": ",".join(models),
        "temperature_unit": temperature_unit,
        "forecast_days": forecast_days,
        "past_days": 0,
        "timezone": timezone,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(ENSEMBLE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    daily = data.get("daily", {})

    # Auto-discover model suffixes from response keys
    suffixes = _discover_model_suffixes(daily)
    if not suffixes:
        logger.warning(f"No model suffixes found in response for {station}")
        return []

    # Parse each model's members separately, then pool
    per_model: dict[str, list[EnsembleForecast]] = {}
    for suffix in suffixes:
        parsed = _parse_ensemble_response(data, station, model_suffix=suffix)
        if parsed:
            per_model[suffix] = parsed
            logger.debug(
                f"{suffix}: {parsed[0].n_members} members, "
                f"{len(parsed)} dates"
            )

    if not per_model:
        logger.warning(f"No ensemble data from any model for {station}")
        return []

    pooled = _pool_multimodel_forecasts(per_model, station)
    total_models = len(per_model)
    if pooled:
        logger.info(
            f"Multi-model {station}: {pooled[0].n_members} members from "
            f"{total_models} models, {len(pooled)} dates"
        )
    return pooled


def fetch_multimodel_ensemble_sync(
    lat: float,
    lon: float,
    station: str = "",
    models: list[str] | None = None,
    temperature_unit: str = "celsius",
    timezone: str = "UTC",
    forecast_days: int = 7,
) -> list[EnsembleForecast]:
    """Synchronous wrapper for fetch_multimodel_ensemble."""
    return asyncio.run(
        fetch_multimodel_ensemble(
            lat, lon, station, models, temperature_unit, timezone,
            forecast_days,
        )
    )


# ---------------------------------------------------------------------------
# Historical observations (Open-Meteo Archive API, ERA5-based)
# ---------------------------------------------------------------------------

HISTORICAL_CACHE_DIR = CACHE_DIR / "historical"


async def fetch_historical_obs(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    temperature_unit: str = "celsius",
    timezone: str = "UTC",
) -> pd.DataFrame:
    """Fetch daily max/min temperatures from Open-Meteo Historical Archive.

    Uses ERA5 reanalysis data (available from 1940 to ~5 days ago).
    Adequate for sigma calibration; not for contract resolution (ERA5
    underestimates daily max by 0.5-1.7C vs station obs).

    Args:
        lat: Latitude.
        lon: Longitude.
        start_date: Start of period (inclusive).
        end_date: End of period (inclusive).
        temperature_unit: "celsius" or "fahrenheit".
        timezone: IANA timezone for daily aggregation.

    Returns:
        DataFrame with columns: date, temp_max, temp_min.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": temperature_unit,
        "timezone": timezone,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(HISTORICAL_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])

    rows = []
    for i, date_str in enumerate(times):
        tmax = temp_max[i] if i < len(temp_max) else None
        tmin = temp_min[i] if i < len(temp_min) else None
        if tmax is not None:
            rows.append({
                "date": date.fromisoformat(date_str),
                "temp_max": float(tmax),
                "temp_min": float(tmin) if tmin is not None else None,
            })

    df = pd.DataFrame(rows)
    logger.info(f"Historical obs: {len(df)} days ({start_date} to {end_date})")
    return df


def fetch_historical_obs_sync(
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
    temperature_unit: str = "celsius",
    timezone: str = "UTC",
) -> pd.DataFrame:
    """Synchronous wrapper for fetch_historical_obs."""
    return asyncio.run(
        fetch_historical_obs(
            lat, lon, start_date, end_date, temperature_unit, timezone,
        )
    )


def save_historical_obs(
    df: pd.DataFrame,
    slug: str,
) -> Path:
    """Save historical observations to cache.

    Appends to city-level parquet file. Deduplicates on date.

    Returns path to the cache file.
    """
    HISTORICAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = HISTORICAL_CACHE_DIR / f"historical_{slug}.parquet"

    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"], keep="last")
    else:
        combined = df

    combined.to_parquet(cache_path, index=False)
    logger.info(f"Saved {len(df)} obs to {cache_path} (total: {len(combined)})")
    return cache_path


def load_historical_obs(slug: str) -> pd.DataFrame:
    """Load cached historical observations for a city.

    Returns empty DataFrame if no cache exists.
    """
    cache_path = HISTORICAL_CACHE_DIR / f"historical_{slug}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    return pd.DataFrame()
