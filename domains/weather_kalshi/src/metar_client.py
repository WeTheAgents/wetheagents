"""Aviation Weather Center METAR client.

Fetches hourly METAR observations from AWC (https://aviationweather.gov/api/data/metar).
No auth required. Supports global ICAOs in a single bulk request.

Schema for data/raw/metar/metar_{ICAO}.parquet (append + dedup on obs_time_unix):
    icao, valid_time_utc, obs_time_unix, temp_c, temp_f, dewpoint_c, dewpoint_f,
    wind_kt, wind_dir_deg, visibility_sm, pressure_mb,
    max_t_6h_c, min_t_6h_c, flight_category, metar_type, raw_metar, fetched_at
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "metar"
AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
DEFAULT_HOURS_BACK = 48


@dataclass(frozen=True)
class MetarRow:
    icao: str
    valid_time_utc: datetime
    obs_time_unix: int
    temp_c: float | None
    dewpoint_c: float | None
    wind_kt: float | None
    wind_dir_deg: float | None
    visibility_sm: str | None
    pressure_mb: float | None
    max_t_6h_c: float | None
    min_t_6h_c: float | None
    flight_category: str | None
    metar_type: str | None
    raw_metar: str


def _c_to_f(c: float | None) -> float | None:
    if c is None:
        return None
    return c * 9.0 / 5.0 + 32.0


def _parse_record(rec: dict) -> MetarRow | None:
    icao = rec.get("icaoId")
    obs_unix = rec.get("obsTime")
    if not icao or obs_unix is None:
        return None
    return MetarRow(
        icao=icao,
        valid_time_utc=datetime.fromtimestamp(int(obs_unix), tz=timezone.utc),
        obs_time_unix=int(obs_unix),
        temp_c=_to_float(rec.get("temp")),
        dewpoint_c=_to_float(rec.get("dewp")),
        wind_kt=_to_float(rec.get("wspd")),
        wind_dir_deg=_to_float(rec.get("wdir")),
        visibility_sm=str(rec.get("visib")) if rec.get("visib") is not None else None,
        pressure_mb=_to_float(rec.get("altim")),
        max_t_6h_c=_to_float(rec.get("maxT")),
        min_t_6h_c=_to_float(rec.get("minT")),
        flight_category=rec.get("fltCat"),
        metar_type=rec.get("metarType"),
        raw_metar=rec.get("rawOb") or "",
    )


def _to_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


CHUNK_SIZE = 8  # AWC truncates bulk responses; chunk to keep responses complete


def _fetch_chunk(client: httpx.Client, ids_csv: str, hours: int) -> list[dict]:
    params = {"ids": ids_csv, "format": "json", "hours": str(hours)}
    try:
        resp = client.get(
            AWC_METAR_URL,
            params=params,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("AWC METAR fetch failed for batch %s: %s", ids_csv, e)
        return []
    ctype = resp.headers.get("content-type", "")
    if "application/json" not in ctype:
        logger.warning("AWC METAR returned non-JSON (%s) for batch %s", ctype, ids_csv)
        return []
    try:
        return resp.json() or []
    except ValueError as e:
        logger.warning("AWC METAR JSON decode failed for batch %s: %s", ids_csv, e)
        return []


def fetch_metar_bulk(
    icaos: list[str],
    hours: int = DEFAULT_HOURS_BACK,
    timeout: float = 60.0,
    chunk_size: int = CHUNK_SIZE,
) -> list[MetarRow]:
    """Fetch METAR for a batch of ICAOs from AWC, in chunks.

    AWC seems to cap bulk responses around ~500 records, so we chunk requests
    into smaller batches. Each chunk failure is logged independently — partial
    success is acceptable.
    """
    if not icaos:
        return []

    unique = sorted(set(icaos))
    rows: list[MetarRow] = []
    with httpx.Client(timeout=timeout) as client:
        for i in range(0, len(unique), chunk_size):
            batch = unique[i:i + chunk_size]
            ids_csv = ",".join(batch)
            data = _fetch_chunk(client, ids_csv, hours)
            for rec in data:
                parsed = _parse_record(rec)
                if parsed is not None:
                    rows.append(parsed)
    return rows


def rows_to_dataframe(rows: list[MetarRow]) -> pd.DataFrame:
    """Convert MetarRow list to wide DataFrame with both °C and °F columns."""
    if not rows:
        return pd.DataFrame()

    fetched_at = datetime.now(timezone.utc)
    out = []
    for r in rows:
        out.append({
            "icao": r.icao,
            "valid_time_utc": r.valid_time_utc,
            "obs_time_unix": r.obs_time_unix,
            "temp_c": r.temp_c,
            "temp_f": _c_to_f(r.temp_c),
            "dewpoint_c": r.dewpoint_c,
            "dewpoint_f": _c_to_f(r.dewpoint_c),
            "wind_kt": r.wind_kt,
            "wind_dir_deg": r.wind_dir_deg,
            "visibility_sm": r.visibility_sm,
            "pressure_mb": r.pressure_mb,
            "max_t_6h_c": r.max_t_6h_c,
            "max_t_6h_f": _c_to_f(r.max_t_6h_c),
            "min_t_6h_c": r.min_t_6h_c,
            "min_t_6h_f": _c_to_f(r.min_t_6h_c),
            "flight_category": r.flight_category,
            "metar_type": r.metar_type,
            "raw_metar": r.raw_metar,
            "fetched_at": fetched_at,
        })
    return pd.DataFrame(out)


def save_metar_snapshot(df: pd.DataFrame, icao: str) -> tuple[Path, int]:
    """Append METAR rows for one ICAO to its parquet, dedup on obs_time_unix.

    Returns (path, n_new_rows).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"metar_{icao}.parquet"

    if df.empty:
        return path, 0

    new_df = df[df["icao"] == icao].copy()
    if new_df.empty:
        return path, 0

    if path.exists():
        existing = pd.read_parquet(path)
        before = len(existing)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["icao", "obs_time_unix"], keep="last")
        added = len(combined) - before
    else:
        combined = new_df
        added = len(new_df)

    combined = combined.sort_values("obs_time_unix").reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return path, added


def fetch_and_save(
    icaos: list[str],
    hours: int = DEFAULT_HOURS_BACK,
) -> dict[str, int]:
    """Bulk-fetch METAR for ICAOs, save per-ICAO parquets. Returns rows-added per ICAO."""
    rows = fetch_metar_bulk(icaos, hours)
    if not rows:
        return {icao: 0 for icao in icaos}

    df = rows_to_dataframe(rows)
    counts: dict[str, int] = {}
    for icao in sorted(set(icaos)):
        _, added = save_metar_snapshot(df, icao)
        counts[icao] = added
    return counts


def load_metar(icao: str) -> pd.DataFrame:
    """Load cached METAR for one ICAO. Returns empty DataFrame if no cache."""
    path = CACHE_DIR / f"metar_{icao}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()
