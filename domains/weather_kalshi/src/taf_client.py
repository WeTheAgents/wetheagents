"""Aviation Weather Center TAF client.

Fetches latest TAF (Terminal Aerodrome Forecast) bulletins from AWC.
TAFs include wind, visibility, sky cover, and OPTIONALLY temperature groups
(TX/TN). In practice TX/TN are rare — most stations omit them entirely.
We persist the full parsed period JSON for flexibility and emit NaN for
temperature aggregates when temp groups are absent.

Schema for data/raw/taf/taf_{ICAO}.parquet (append + dedup on issue_time_utc):
    icao, issue_time_utc, valid_from_utc, valid_to_utc,
    n_periods, temp_groups_present, periods_json, raw_taf, fetched_at
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "taf"
AWC_TAF_URL = "https://aviationweather.gov/api/data/taf"


@dataclass(frozen=True)
class TafBulletin:
    icao: str
    issue_time_utc: datetime
    valid_from_utc: datetime
    valid_to_utc: datetime
    periods: list[dict]
    temp_groups_present: bool
    raw_taf: str


def _parse_record(rec: dict) -> TafBulletin | None:
    icao = rec.get("icaoId")
    issue_unix = rec.get("issueTime")
    valid_from_unix = rec.get("validTimeFrom")
    valid_to_unix = rec.get("validTimeTo")
    if not icao or issue_unix is None:
        return None

    fcsts = rec.get("fcsts") or []
    temp_groups_present = any(
        p.get("temp") for p in fcsts if isinstance(p, dict)
    )

    def _ts(val) -> datetime | None:
        if val is None or val == "":
            return None
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(int(val), tz=timezone.utc)
        # ISO 8601 string, e.g. "2026-04-28T05:20:00.000Z"
        s = str(val).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    issue = _ts(issue_unix) or datetime.fromtimestamp(0, tz=timezone.utc)
    valid_from = _ts(valid_from_unix) or issue
    valid_to = _ts(valid_to_unix) or issue

    return TafBulletin(
        icao=icao,
        issue_time_utc=issue,
        valid_from_utc=valid_from,
        valid_to_utc=valid_to,
        periods=fcsts,
        temp_groups_present=temp_groups_present,
        raw_taf=rec.get("rawTAF") or rec.get("rawOb") or "",
    )


CHUNK_SIZE = 12


def _fetch_chunk(
    client: httpx.Client, ids_csv: str, most_recent_only: bool,
) -> list[dict]:
    params: dict = {"ids": ids_csv, "format": "json"}
    if most_recent_only:
        params["mostRecent"] = "true"
    try:
        resp = client.get(
            AWC_TAF_URL, params=params,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("AWC TAF fetch failed for batch %s: %s", ids_csv, e)
        return []
    ctype = resp.headers.get("content-type", "")
    if "application/json" not in ctype:
        logger.warning("AWC TAF returned non-JSON (%s) for batch %s", ctype, ids_csv)
        return []
    try:
        return resp.json() or []
    except ValueError as e:
        logger.warning("AWC TAF JSON decode failed for batch %s: %s", ids_csv, e)
        return []


def fetch_taf_bulk(
    icaos: list[str],
    most_recent_only: bool = True,
    timeout: float = 60.0,
    chunk_size: int = CHUNK_SIZE,
) -> list[TafBulletin]:
    """Fetch TAFs for ICAOs in chunks (AWC bulk responses can truncate)."""
    if not icaos:
        return []

    unique = sorted(set(icaos))
    rows: list[TafBulletin] = []
    with httpx.Client(timeout=timeout) as client:
        for i in range(0, len(unique), chunk_size):
            batch = unique[i:i + chunk_size]
            ids_csv = ",".join(batch)
            data = _fetch_chunk(client, ids_csv, most_recent_only)
            for rec in data:
                parsed = _parse_record(rec)
                if parsed is not None:
                    rows.append(parsed)
    return rows


def bulletins_to_dataframe(bulletins: list[TafBulletin]) -> pd.DataFrame:
    """Convert parsed bulletins to DataFrame; periods serialized to JSON string."""
    if not bulletins:
        return pd.DataFrame()

    fetched_at = datetime.now(timezone.utc)
    rows = []
    for b in bulletins:
        rows.append({
            "icao": b.icao,
            "issue_time_utc": b.issue_time_utc,
            "valid_from_utc": b.valid_from_utc,
            "valid_to_utc": b.valid_to_utc,
            "n_periods": len(b.periods),
            "temp_groups_present": b.temp_groups_present,
            "periods_json": json.dumps(b.periods),
            "raw_taf": b.raw_taf,
            "fetched_at": fetched_at,
        })
    return pd.DataFrame(rows)


def save_taf_snapshot(df: pd.DataFrame, icao: str) -> tuple[Path, int]:
    """Append TAF bulletins for one ICAO to its parquet, dedup on issue_time_utc."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"taf_{icao}.parquet"

    if df.empty:
        return path, 0

    new_df = df[df["icao"] == icao].copy()
    if new_df.empty:
        return path, 0

    if path.exists():
        existing = pd.read_parquet(path)
        before = len(existing)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["icao", "issue_time_utc"], keep="last")
        added = len(combined) - before
    else:
        combined = new_df
        added = len(new_df)

    combined = combined.sort_values("issue_time_utc").reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return path, added


def fetch_and_save(icaos: list[str]) -> dict[str, int]:
    """Bulk-fetch latest TAFs and save per-ICAO. Returns rows-added per ICAO."""
    bulletins = fetch_taf_bulk(icaos)
    if not bulletins:
        return {icao: 0 for icao in icaos}

    df = bulletins_to_dataframe(bulletins)
    counts: dict[str, int] = {}
    for icao in sorted(set(icaos)):
        _, added = save_taf_snapshot(df, icao)
        counts[icao] = added
    return counts


def load_taf(icao: str) -> pd.DataFrame:
    """Load cached TAFs for one ICAO."""
    path = CACHE_DIR / f"taf_{icao}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()
