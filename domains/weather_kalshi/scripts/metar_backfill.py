"""Historical METAR backfill from IEM ASOS archive.

Complements scripts/aviation_snapshot.py (which uses AWC for the rolling
~48h window) by tapping IEM's full historical archive going back decades.

Endpoint: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
Returns CSV. Works for both US (3-char) and international (4-char) ICAOs.
No network= param needed — IEM auto-resolves the station globally.

Output is appended to the same parquet files as the live AWC client:
data/raw/metar/metar_{ICAO}.parquet, dedup on obs_time_unix. Rows from
this script have flight_category/metar_type NULL since IEM CSV doesn't
include them (the live AWC fetch fills those for recent rows).

Usage
-----
    python -m scripts.metar_backfill --days-back 30
    python -m scripts.metar_backfill --start 2026-03-09 --end 2026-04-26
    python -m scripts.metar_backfill --cities nyc tokyo --days-back 60
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.metar_client import save_metar_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ICAO_MAP_PATH = ROOT / "data" / "static" / "icao_map.json"
IEM_ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
DEFAULT_DAYS_BACK = 30
RATE_LIMIT_SECONDS = 1.5  # IEM rate-limits aggressive bulk consumers
IEM_DATA_COLS = "tmpc,dwpc,sknt,drct,vsby,alti,metar"


def _c_to_f(c: float | None) -> float | None:
    if c is None or pd.isna(c):
        return None
    return float(c) * 9.0 / 5.0 + 32.0


def _to_float(val) -> float | None:
    if val is None or val == "" or val == "M":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _altimeter_in_hg_to_mb(in_hg: float | None) -> float | None:
    """Convert altimeter inches Hg to millibars (hPa)."""
    if in_hg is None:
        return None
    return float(in_hg) * 33.8639


def fetch_iem_csv(
    icao: str,
    start: date,
    end: date,
    client: httpx.Client,
    timeout: float = 120.0,
) -> pd.DataFrame:
    """Fetch IEM ASOS CSV for one ICAO over a date window. Returns DataFrame."""
    params = {
        "station": icao,
        "data": IEM_DATA_COLS,
        "year1": str(start.year), "month1": str(start.month), "day1": str(start.day),
        "year2": str(end.year), "month2": str(end.month), "day2": str(end.day),
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3,4",  # 3=METAR, 4=SPECI
    }

    try:
        resp = client.get(IEM_ASOS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("IEM fetch failed for %s %s..%s: %s", icao, start, end, e)
        return pd.DataFrame()

    text = resp.text
    if not text or text.startswith("ERROR"):
        logger.warning("IEM returned empty/error for %s: %s", icao, text[:120])
        return pd.DataFrame()

    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        return df

    # Normalize column names (IEM lowercase; our convention varies)
    return df


def iem_to_metar_parquet_rows(df: pd.DataFrame, icao: str) -> pd.DataFrame:
    """Convert IEM CSV DataFrame to the metar_{ICAO}.parquet schema."""
    if df.empty:
        return df

    rows = []
    fetched_at = datetime.now(timezone.utc)
    for _, r in df.iterrows():
        valid_str = r.get("valid")
        if pd.isna(valid_str):
            continue
        try:
            valid_dt = datetime.strptime(str(valid_str), "%Y-%m-%d %H:%M")
            valid_dt = valid_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        temp_c = _to_float(r.get("tmpc"))
        if temp_c is None:
            # Skip rows where the primary signal is missing
            continue

        dewp_c = _to_float(r.get("dwpc"))
        wind_kt = _to_float(r.get("sknt"))
        wind_dir = _to_float(r.get("drct"))
        vsby = _to_float(r.get("vsby"))
        alti_in = _to_float(r.get("alti"))
        raw_metar = r.get("metar")
        if pd.isna(raw_metar):
            raw_metar = ""

        rows.append({
            "icao": icao,
            "valid_time_utc": valid_dt,
            "obs_time_unix": int(valid_dt.timestamp()),
            "temp_c": temp_c,
            "temp_f": _c_to_f(temp_c),
            "dewpoint_c": dewp_c,
            "dewpoint_f": _c_to_f(dewp_c),
            "wind_kt": wind_kt,
            "wind_dir_deg": wind_dir,
            "visibility_sm": str(vsby) if vsby is not None else None,
            "pressure_mb": _altimeter_in_hg_to_mb(alti_in),
            "max_t_6h_c": None,
            "max_t_6h_f": None,
            "min_t_6h_c": None,
            "min_t_6h_f": None,
            "flight_category": None,
            "metar_type": None,
            "raw_metar": str(raw_metar),
            "fetched_at": fetched_at,
        })

    return pd.DataFrame(rows)


def backfill_icao(
    icao: str, start: date, end: date, client: httpx.Client,
) -> int:
    """Fetch IEM CSV for one ICAO over [start, end], append to parquet. Returns rows added."""
    raw = fetch_iem_csv(icao, start, end, client)
    if raw.empty:
        logger.info("IEM %s: no data for %s..%s", icao, start, end)
        return 0
    df = iem_to_metar_parquet_rows(raw, icao)
    if df.empty:
        logger.info("IEM %s: %d raw rows but none with tmpc", icao, len(raw))
        return 0
    _, added = save_metar_snapshot(df, icao)
    logger.info("IEM %s: %d raw, %d valid, %d new", icao, len(raw), len(df), added)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical METAR from IEM ASOS")
    parser.add_argument("--days-back", type=int, default=DEFAULT_DAYS_BACK)
    parser.add_argument("--start", type=date.fromisoformat,
                        help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat,
                        help="Override end date (default: yesterday)")
    parser.add_argument("--cities", nargs="+",
                        help="Restrict to specific Polymarket slugs")
    parser.add_argument("--icaos", nargs="+",
                        help="Restrict to specific ICAO codes (overrides --cities)")
    args = parser.parse_args()

    today = date.today()
    end = args.end if args.end else today - timedelta(days=1)
    start = args.start if args.start else end - timedelta(days=args.days_back - 1)
    if start > end:
        logger.error("start (%s) > end (%s)", start, end)
        return 1

    with open(ICAO_MAP_PATH) as f:
        icao_map = json.load(f)

    if args.icaos:
        target_icaos = sorted(set(args.icaos))
    elif args.cities:
        target_icaos = sorted(
            {icao_map[s]["primary"] for s in args.cities if s in icao_map}
        )
    else:
        target_icaos = sorted({info["primary"] for info in icao_map.values()})

    logger.info(
        "Backfilling METAR %s..%s for %d ICAOs",
        start, end, len(target_icaos),
    )

    summary = {"added": 0, "skipped": 0, "errors": 0}
    with httpx.Client() as client:
        for i, icao in enumerate(target_icaos):
            try:
                added = backfill_icao(icao, start, end, client)
                summary["added"] += added
                if added == 0:
                    summary["skipped"] += 1
            except Exception as e:  # noqa: BLE001
                logger.exception("Backfill failed for %s: %s", icao, e)
                summary["errors"] += 1
            time.sleep(RATE_LIMIT_SECONDS)

    print(f"\n{'=' * 60}")
    print(f"METAR backfill complete: {start}..{end}")
    print(f"  ICAOs queried:     {len(target_icaos)}")
    print(f"  Total rows added:  {summary['added']}")
    print(f"  ICAOs with 0 rows: {summary['skipped']}")
    print(f"  Errors:            {summary['errors']}")
    print(f"{'=' * 60}")
    return 2 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
