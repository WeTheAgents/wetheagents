"""Load and standardize MOS forecast-observation pairs.

The core challenge is parsing the MOS n_x field, which encodes daily max/min
temperatures at 12-hour intervals:

  - ftime at 00:00 UTC: MAX temperature for the preceding daytime
    (12Z-00Z window covers afternoon in US time zones)
  - ftime at 12:00 UTC: MIN temperature for the preceding nighttime
    (00Z-12Z window covers overnight in US time zones)

Calendar day mapping (for US stations):
  - MAX: calendar_day = ftime.date() - 1 day
    (00Z of July 16 captures the afternoon high of July 15)
  - MIN: calendar_day = ftime.date()
    (12Z of July 16 captures the overnight low into July 16 morning)

Walk-forward discipline: all bias computations use only data from BEFORE
the forecast date. Never look ahead.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .stations import Station, get_station

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Seasons by month
MONTH_TO_SEASON = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


def load_mos_forecasts(
    station: Station,
    model: str = "GFS",
) -> pd.DataFrame:
    """Load MOS forecasts and extract daily max/min temperature predictions.

    Parses n_x field from raw MOS data into structured forecast records.

    Args:
        station: Station metadata.
        model: NWP model name.

    Returns:
        DataFrame with columns: station, date, model, runtime, forecast_lead_hours,
        forecast_high, forecast_low.
    """
    # Try bulk CSV first, then individual year parquet files
    bulk_path = RAW_DIR / "mos" / f"{station.icao}_{model}_all.csv"
    if bulk_path.exists():
        df = _load_mos_from_csv(bulk_path, station, model)
    else:
        df = _load_mos_from_parquet(station, model)

    if df.empty:
        logger.warning(f"No MOS data found for {station.icao} {model}")
        return pd.DataFrame()

    return _extract_max_min_forecasts(df, station, model)


def _load_mos_from_csv(path: Path, station: Station, model: str) -> pd.DataFrame:
    """Load from bulk CSV download."""
    logger.info(f"Loading MOS from {path.name}")
    df = pd.read_csv(path, low_memory=False)
    return df


def _load_mos_from_parquet(station: Station, model: str) -> pd.DataFrame:
    """Load from individual year files (parquet or CSV)."""
    mos_dir = RAW_DIR / "mos"

    # Try parquet first, then CSV
    dfs = []
    for ext in ["parquet", "csv"]:
        pattern = f"{station.icao}_{model}_*.{ext}"
        files = sorted(mos_dir.glob(pattern))
        # Exclude "_all" files (handled by bulk loader)
        files = [f for f in files if "_all" not in f.stem]

        for f in files:
            try:
                if ext == "parquet":
                    part = pd.read_parquet(f)
                else:
                    part = pd.read_csv(f, low_memory=False)
                if not part.empty:
                    dfs.append(part)
                    logger.info(f"Loaded {len(part)} MOS rows from {f.name}")
            except Exception as e:
                logger.warning(f"Failed to load {f.name}: {e}")

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def _extract_max_min_forecasts(
    df: pd.DataFrame,
    station: Station,
    model: str,
) -> pd.DataFrame:
    """Extract daily MAX and MIN temperature forecasts from MOS n_x field.

    Logic:
      - Filter to rows where n_x is not null
      - ftime hour == 0 (00Z) -> this is a MAX temperature forecast
      - ftime hour == 12 (12Z) -> this is a MIN temperature forecast
      - Calendar day of MAX = ftime.date() - 1 day
      - Calendar day of MIN = ftime.date()
      - Group by (runtime, calendar_date) to pair MAX and MIN for same day
    """
    # Parse datetime columns
    df = df.copy()
    df["runtime"] = pd.to_datetime(df["runtime"])
    df["ftime"] = pd.to_datetime(df["ftime"])

    # Filter to rows with n_x (temperature extremes only)
    mask = df["n_x"].notna()
    temps = df.loc[mask, ["runtime", "ftime", "n_x"]].copy()

    if temps.empty:
        return pd.DataFrame()

    temps["n_x"] = pd.to_numeric(temps["n_x"], errors="coerce")
    temps = temps.dropna(subset=["n_x"])

    # Determine if MAX or MIN based on ftime hour
    temps["ftime_hour"] = temps["ftime"].dt.hour
    temps["is_max"] = temps["ftime_hour"] == 0
    temps["is_min"] = temps["ftime_hour"] == 12

    # Calendar day assignment
    # MAX at 00Z: calendar day = ftime.date() - 1
    # MIN at 12Z: calendar day = ftime.date()
    temps["calendar_date"] = pd.NaT
    max_mask = temps["is_max"]
    min_mask = temps["is_min"]
    temps.loc[max_mask, "calendar_date"] = temps.loc[max_mask, "ftime"] - timedelta(days=1)
    temps.loc[min_mask, "calendar_date"] = temps.loc[min_mask, "ftime"]
    temps["calendar_date"] = temps["calendar_date"].dt.date

    # Drop rows that are neither MAX nor MIN (shouldn't happen, but defensive)
    temps = temps[max_mask | min_mask].copy()

    # Pivot: for each (runtime, calendar_date), get MAX and MIN
    maxes = temps.loc[max_mask, ["runtime", "calendar_date", "n_x"]].rename(
        columns={"n_x": "forecast_high"}
    )
    mins = temps.loc[min_mask, ["runtime", "calendar_date", "n_x"]].rename(
        columns={"n_x": "forecast_low"}
    )

    # Use the FIRST model run that covers each calendar date (shortest lead time)
    # For daily high: prefer the same-day 00Z run or previous-day 12Z run
    maxes = maxes.sort_values("runtime").drop_duplicates(
        subset=["calendar_date"], keep="first"
    )
    mins = mins.sort_values("runtime").drop_duplicates(
        subset=["calendar_date"], keep="first"
    )

    # Merge MAX and MIN for same calendar date
    forecasts = pd.merge(
        maxes, mins,
        on="calendar_date",
        how="outer",
        suffixes=("_max", "_min"),
    )

    # Use the MAX runtime as the reference runtime
    forecasts["runtime"] = forecasts["runtime_max"].fillna(forecasts["runtime_min"])
    forecasts = forecasts.drop(columns=["runtime_max", "runtime_min"])

    # Compute lead time (hours from runtime to calendar date noon local)
    forecasts["date"] = pd.to_datetime(forecasts["calendar_date"])
    forecasts["forecast_lead_hours"] = (
        (forecasts["date"] - forecasts["runtime"]).dt.total_seconds() / 3600
    ).round().astype("Int64")

    # Add metadata
    forecasts["station"] = station.icao
    forecasts["model"] = model

    # Select and order columns
    result = forecasts[[
        "station", "date", "model", "runtime",
        "forecast_lead_hours", "forecast_high", "forecast_low",
    ]].copy()

    result["date"] = pd.to_datetime(result["date"]).dt.date
    result = result.sort_values("date").reset_index(drop=True)

    logger.info(
        f"Extracted {len(result)} forecast days for {station.icao} "
        f"({result['date'].min()} to {result['date'].max()})"
    )
    return result


def load_observations(station: Station) -> pd.DataFrame:
    """Load daily observed temperatures.

    Tries merged parquet first, then individual year parquet files.
    The JSON API returns records with max_tmpf, min_tmpf, date fields.

    Returns:
        DataFrame with columns: station, date, observed_high, observed_low.
    """
    # Try merged parquet (from download_obs_bulk)
    bulk_parquet = RAW_DIR / "obs" / f"{station.iem_station_id}_obs_all.parquet"
    if bulk_parquet.exists():
        df = pd.read_parquet(bulk_parquet)
        if not df.empty and "max_tmpf" in df.columns:
            return _parse_obs_df(df, station)

    # Try individual year parquet files
    obs_dir = RAW_DIR / "obs"
    pattern = f"{station.iem_station_id}_*.parquet"
    files = sorted(obs_dir.glob(pattern))
    # Exclude the merged file
    files = [f for f in files if "obs_all" not in f.name]

    if not files:
        logger.warning(f"No obs data found for {station.icao}")
        return pd.DataFrame()

    dfs = []
    for f in files:
        try:
            part = pd.read_parquet(f)
            if not part.empty:
                dfs.append(part)
        except Exception as e:
            logger.warning(f"Failed to load {f.name}: {e}")

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)
    return _parse_obs_df(df, station)


def _parse_obs_df(df: pd.DataFrame, station: Station) -> pd.DataFrame:
    """Parse observation DataFrame into standardized format.

    Handles both JSON API format (max_tmpf, date) and CSV format (max_tmpf, day).
    """
    # Determine date column name
    date_col = "date" if "date" in df.columns else "day"

    obs = pd.DataFrame({
        "station": station.icao,
        "date": pd.to_datetime(df[date_col]).dt.date,
        "observed_high": pd.to_numeric(df["max_tmpf"], errors="coerce"),
        "observed_low": pd.to_numeric(df["min_tmpf"], errors="coerce"),
    })
    obs = obs.dropna(subset=["observed_high", "observed_low"])
    obs = obs.drop_duplicates(subset=["station", "date"])
    logger.info(f"Loaded {len(obs)} obs days for {station.icao}")
    return obs


def build_forecast_obs_pairs(
    station: Station,
    model: str = "GFS",
    min_obs_coverage: float = 0.95,
) -> pd.DataFrame:
    """Build paired forecast-observation dataset for analysis.

    Joins MOS forecasts with observed temperatures, computes errors,
    and adds derived fields (month, season, absolute error).

    Rejects station-years with < min_obs_coverage fraction of days observed.

    Args:
        station: Station metadata.
        model: NWP model name.
        min_obs_coverage: Minimum fraction of days with obs per year (default 95%).

    Returns:
        DataFrame with all forecast, observation, and error columns.
    """
    forecasts = load_mos_forecasts(station, model)
    observations = load_observations(station)

    if forecasts.empty or observations.empty:
        logger.warning(f"Cannot build pairs: missing data for {station.icao}")
        return pd.DataFrame()

    # Join on (station, date)
    pairs = pd.merge(
        forecasts, observations,
        on=["station", "date"],
        how="inner",
    )

    if pairs.empty:
        logger.warning(f"No matching forecast-obs pairs for {station.icao}")
        return pd.DataFrame()

    # Compute errors
    pairs["error_high"] = pairs["forecast_high"] - pairs["observed_high"]
    pairs["error_low"] = pairs["forecast_low"] - pairs["observed_low"]
    pairs["abs_error_high"] = pairs["error_high"].abs()
    pairs["abs_error_low"] = pairs["error_low"].abs()

    # Add derived fields
    pairs["date_dt"] = pd.to_datetime(pairs["date"])
    pairs["month"] = pairs["date_dt"].dt.month
    pairs["year"] = pairs["date_dt"].dt.year
    pairs["day_of_year"] = pairs["date_dt"].dt.dayofyear
    pairs["season"] = pairs["month"].map(MONTH_TO_SEASON)

    # Quality filter: reject station-years with poor forecast-obs pair coverage
    # Use correct denominator (366 for leap years, 365 otherwise)
    year_counts = pairs.groupby("year")["date"].count()
    import calendar
    good_years = []
    for yr, count in year_counts.items():
        days_in_year = 366 if calendar.isleap(yr) else 365
        if count >= days_in_year * min_obs_coverage:
            good_years.append(yr)
    rejected = set(pairs["year"].unique()) - set(good_years)
    if rejected:
        logger.info(
            f"Rejecting years with <{min_obs_coverage:.0%} "
            f"forecast-obs pair coverage: {rejected}"
        )
        pairs = pairs[pairs["year"].isin(good_years)]

    # Drop temp column
    pairs = pairs.drop(columns=["date_dt"])

    pairs = pairs.sort_values("date").reset_index(drop=True)
    logger.info(
        f"Built {len(pairs)} forecast-obs pairs for {station.icao} "
        f"({pairs['year'].min()}-{pairs['year'].max()}, "
        f"{pairs['year'].nunique()} years)"
    )
    return pairs


def save_pairs(pairs: pd.DataFrame, station: Station) -> Path:
    """Save forecast-obs pairs to processed parquet."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / f"forecast_obs_{station.icao}.parquet"
    pairs.to_parquet(out_path, index=False)
    logger.info(f"Saved {len(pairs)} pairs to {out_path.name}")
    return out_path


def load_pairs(station: Station) -> pd.DataFrame:
    """Load pre-built forecast-obs pairs from processed parquet."""
    path = PROCESSED_DIR / f"forecast_obs_{station.icao}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No processed data for {station.icao}. Run download first.")
    return pd.read_parquet(path)
