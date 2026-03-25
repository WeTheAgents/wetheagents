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

# GEFS has 30 members on Open-Meteo
GEFS_N_MEMBERS = 30


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
