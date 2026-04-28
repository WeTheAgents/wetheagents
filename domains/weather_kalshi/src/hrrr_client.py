"""HRRR (High-Resolution Rapid Refresh) client.

Fetches NOAA HRRR hourly-updated 3km CONUS forecasts via herbie-data
(uses AWS Open Data S3 bucket noaa-hrrr-bdp-pds — no auth required).

CONUS-only: works for 13 US ICAOs in stations.json. International cities
will not have HRRR features (column NaN in ml_panel by design).

Schema for data/raw/hrrr/hrrr_{ICAO}.parquet (append + dedup on
(run_time_utc, valid_time_utc)):
    icao, run_time_utc, valid_time_utc, lead_hours, temp_2m_c, temp_2m_f, fetched_at

Cycle resolution: caller specifies a target run_time (or `latest_available()`
walks backwards from now until herbie resolves). HRRR runs hourly.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Force UTF-8 stdout BEFORE importing herbie (it prints emoji on instantiation
# which crashes Windows cp1251 console).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from herbie import Herbie  # noqa: E402

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "hrrr"
HERBIE_CACHE_DIR = CACHE_DIR / "_cache"

DEFAULT_FXX_RANGE = list(range(1, 19))  # 1..18 hourly forecasts
SEARCH_STRING_TMP_2M = ":TMP:2 m above ground:"


@dataclass(frozen=True)
class HrrrPoint:
    icao: str
    run_time_utc: datetime
    valid_time_utc: datetime
    lead_hours: int
    temp_2m_k: float


def _k_to_f(k: float) -> float:
    return k * 9.0 / 5.0 - 459.67


def _k_to_c(k: float) -> float:
    return k - 273.15


def latest_available_run(
    max_lookback_hours: int = 8,
    probe_fxx: int = 18,
) -> datetime | None:
    """Walk backwards hourly; return first run whose ENTIRE forecast (up to
    `probe_fxx`) is published.

    HRRR cycle publishes incrementally — fxx=1 lands ~30 min after run time,
    fxx=18 lands ~2-3 hours after. For full-coverage features we want a run
    where the late-lead files exist, hence we probe with `probe_fxx=18`.
    """
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for back in range(0, max_lookback_hours + 1):
        candidate = now - timedelta(hours=back)
        try:
            H = Herbie(
                candidate.strftime("%Y-%m-%d %H:%M"),
                model="hrrr", product="sfc", fxx=probe_fxx,
                save_dir=str(HERBIE_CACHE_DIR),
                verbose=False,
            )
            if H.idx is not None:
                return candidate
        except Exception:  # noqa: BLE001
            continue
    return None


def _nearest_grid_index(
    lats_2d: np.ndarray,
    lons_2d_0_360: np.ndarray,
    lat: float,
    lon: float,
) -> tuple[int, int]:
    """Find (y, x) index of grid cell nearest to (lat, lon).

    Uses Euclidean distance on lat/lon — adequate for CONUS scale at 3km grid.
    `lons_2d_0_360` must be in 0-360 longitude format.
    """
    lon_q = lon % 360.0
    dist_sq = (lats_2d - lat) ** 2 + (lons_2d_0_360 - lon_q) ** 2
    idx = int(np.argmin(dist_sq))
    return np.unravel_index(idx, lats_2d.shape)


def _extract_field_at_points(
    H: Herbie,
    points: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Load TMP-2m field, point-extract at each (icao -> (lat, lon))."""
    ds = H.xarray(SEARCH_STRING_TMP_2M)
    var = "t2m" if "t2m" in ds.data_vars else list(ds.data_vars)[0]
    lats = ds.latitude.values
    lons = ds.longitude.values  # already 0-360 from GRIB
    field = ds[var].values
    out = {}
    for icao, (lat, lon) in points.items():
        try:
            yi, xi = _nearest_grid_index(lats, lons, lat, lon)
            out[icao] = float(field[yi, xi])
        except (IndexError, ValueError) as e:
            logger.warning("HRRR point extract failed for %s: %s", icao, e)
            out[icao] = float("nan")
    ds.close()
    return out


def fetch_run(
    run_time_utc: datetime,
    points: dict[str, tuple[float, float]],
    fxx_range: list[int] | None = None,
) -> list[HrrrPoint]:
    """Fetch one HRRR run for given lead hours and stations.

    `points` maps ICAO to (lat, lon). Returns flat list of HrrrPoint records.
    Failures on individual fxx are logged and skipped (partial success OK).
    """
    if fxx_range is None:
        fxx_range = DEFAULT_FXX_RANGE
    HERBIE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[HrrrPoint] = []
    for fxx in fxx_range:
        try:
            H = Herbie(
                run_time_utc.strftime("%Y-%m-%d %H:%M"),
                model="hrrr", product="sfc", fxx=fxx,
                save_dir=str(HERBIE_CACHE_DIR),
                verbose=False,
            )
            if H.idx is None:
                logger.info("HRRR fxx=%d not yet available for %s", fxx, run_time_utc)
                continue
            point_vals = _extract_field_at_points(H, points)
        except Exception as e:  # noqa: BLE001
            logger.warning("HRRR fetch failed run=%s fxx=%d: %s", run_time_utc, fxx, e)
            continue

        valid_time = run_time_utc + timedelta(hours=fxx)
        for icao, val_k in point_vals.items():
            if np.isnan(val_k):
                continue
            rows.append(HrrrPoint(
                icao=icao,
                run_time_utc=run_time_utc,
                valid_time_utc=valid_time,
                lead_hours=fxx,
                temp_2m_k=val_k,
            ))
    return rows


def points_to_dataframe(points: list[HrrrPoint]) -> pd.DataFrame:
    if not points:
        return pd.DataFrame()
    fetched_at = datetime.now(timezone.utc)
    return pd.DataFrame([
        {
            "icao": p.icao,
            "run_time_utc": p.run_time_utc,
            "valid_time_utc": p.valid_time_utc,
            "lead_hours": p.lead_hours,
            "temp_2m_c": _k_to_c(p.temp_2m_k),
            "temp_2m_f": _k_to_f(p.temp_2m_k),
            "fetched_at": fetched_at,
        }
        for p in points
    ])


def save_hrrr_snapshot(df: pd.DataFrame, icao: str) -> tuple[Path, int]:
    """Append HRRR rows for one ICAO; dedup on (run_time_utc, valid_time_utc)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"hrrr_{icao}.parquet"

    if df.empty:
        return path, 0

    new_df = df[df["icao"] == icao].copy()
    if new_df.empty:
        return path, 0

    if path.exists():
        existing = pd.read_parquet(path)
        before = len(existing)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["icao", "run_time_utc", "valid_time_utc"], keep="last",
        )
        added = len(combined) - before
    else:
        combined = new_df
        added = len(new_df)

    combined = combined.sort_values(["run_time_utc", "valid_time_utc"]).reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return path, added


def fetch_and_save(
    points: dict[str, tuple[float, float]],
    run_time_utc: datetime | None = None,
    fxx_range: list[int] | None = None,
) -> dict[str, int]:
    """Fetch latest available run (or specified) and save per-ICAO parquets."""
    if run_time_utc is None:
        run_time_utc = latest_available_run()
        if run_time_utc is None:
            logger.warning("No HRRR run available within lookback window")
            return {icao: 0 for icao in points}

    rows = fetch_run(run_time_utc, points, fxx_range)
    if not rows:
        return {icao: 0 for icao in points}

    df = points_to_dataframe(rows)
    counts: dict[str, int] = {}
    for icao in sorted(points):
        _, added = save_hrrr_snapshot(df, icao)
        counts[icao] = added
    return counts


def cleanup_cache(older_than_days: int = 7) -> tuple[int, int]:
    """Delete cached GRIB2 files older than N days. Returns (n_files, total_mb)."""
    if not HERBIE_CACHE_DIR.exists():
        return 0, 0
    cutoff = datetime.now() - timedelta(days=older_than_days)
    n = 0
    total = 0
    for path in HERBIE_CACHE_DIR.rglob("*.grib2*"):
        try:
            stat = path.stat()
            if datetime.fromtimestamp(stat.st_mtime) < cutoff:
                total += stat.st_size
                path.unlink()
                n += 1
        except OSError:
            pass
    return n, total // (1024 * 1024)


def load_hrrr(icao: str) -> pd.DataFrame:
    path = CACHE_DIR / f"hrrr_{icao}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()
