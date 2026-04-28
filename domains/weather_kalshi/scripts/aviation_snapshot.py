"""Aviation weather snapshot orchestrator: METAR + TAF + HRRR.

Bulk-fetches the latest aviation data for all Polymarket cities and persists
to per-ICAO parquets:
  - data/raw/metar/metar_{ICAO}.parquet  (45 ICAOs, hourly observations)
  - data/raw/taf/taf_{ICAO}.parquet      (45 ICAOs, latest forecast)
  - data/raw/hrrr/hrrr_{ICAO}.parquet    (13 US ICAOs, latest run × fxx 1..18)

Each source runs in its own try/except. Partial success acceptable; failures
are surfaced in the printed summary so the caller (routine) can flag.

Usage
-----
    python -m scripts.aviation_snapshot
    python -m scripts.aviation_snapshot --sources metar taf
    python -m scripts.aviation_snapshot --icaos KLGA EHAM
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cities import CITIES
from src.hrrr_client import (
    cleanup_cache as hrrr_cleanup_cache,
    fetch_and_save as hrrr_fetch_and_save,
    latest_available_run as hrrr_latest_run,
)
from src.metar_client import fetch_and_save as metar_fetch_and_save
from src.stations import POLYMARKET_STATIONS, get_station
from src.taf_client import fetch_and_save as taf_fetch_and_save

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ICAO_MAP_PATH = ROOT / "data" / "static" / "icao_map.json"
DEFAULT_METAR_HOURS = 48


def load_icao_map() -> dict[str, dict]:
    with open(ICAO_MAP_PATH) as f:
        return json.load(f)


def resolve_icaos(
    slugs: list[str] | None = None,
    icao_filter: list[str] | None = None,
) -> list[str]:
    """Pick primary ICAOs from icao_map for given slugs (or all)."""
    icao_map = load_icao_map()
    if slugs is None:
        slugs = [s for s in icao_map if s in CITIES]
    icaos = []
    for slug in slugs:
        if slug not in icao_map:
            continue
        primary = icao_map[slug]["primary"]
        if icao_filter and primary not in icao_filter:
            continue
        icaos.append(primary)
    return sorted(set(icaos))


def run_metar(icaos: list[str], hours: int) -> dict:
    if not icaos:
        return {"status": "SKIP", "icaos": 0, "rows_added": 0, "error": None}
    try:
        counts = metar_fetch_and_save(icaos, hours=hours)
        added = sum(counts.values())
        with_data = sum(1 for v in counts.values() if v > 0)
        return {
            "status": "OK" if with_data > 0 else "FAIL",
            "icaos": with_data,
            "rows_added": added,
            "error": None if with_data > 0 else "no rows added",
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("METAR fetch crashed")
        return {"status": "FAIL", "icaos": 0, "rows_added": 0, "error": str(e)}


def run_taf(icaos: list[str]) -> dict:
    if not icaos:
        return {"status": "SKIP", "icaos": 0, "rows_added": 0, "error": None}
    try:
        counts = taf_fetch_and_save(icaos)
        added = sum(counts.values())
        with_data = sum(1 for v in counts.values() if v > 0)
        return {
            "status": "OK" if with_data > 0 else "WARN",
            "icaos": with_data,
            "rows_added": added,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("TAF fetch crashed")
        return {"status": "FAIL", "icaos": 0, "rows_added": 0, "error": str(e)}


def run_hrrr(icao_filter: list[str] | None) -> dict:
    us_icaos = list(POLYMARKET_STATIONS)
    if icao_filter:
        us_icaos = [i for i in us_icaos if i in icao_filter]
    if not us_icaos:
        return {"status": "SKIP", "icaos": 0, "rows_added": 0, "error": None,
                "run_time": None}
    try:
        run_time = hrrr_latest_run()
        if run_time is None:
            return {"status": "FAIL", "icaos": 0, "rows_added": 0,
                    "error": "no run available", "run_time": None}
        points = {icao: (get_station(icao).lat, get_station(icao).lon)
                  for icao in us_icaos}
        counts = hrrr_fetch_and_save(points, run_time_utc=run_time)
        added = sum(counts.values())
        with_data = sum(1 for v in counts.values() if v > 0)
        return {
            "status": "OK" if with_data > 0 else "FAIL",
            "icaos": with_data,
            "rows_added": added,
            "error": None if with_data > 0 else "no rows added",
            "run_time": run_time.isoformat(),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("HRRR fetch crashed")
        return {"status": "FAIL", "icaos": 0, "rows_added": 0,
                "error": str(e), "run_time": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Aviation weather snapshot")
    parser.add_argument("--sources", nargs="+",
                        choices=["metar", "taf", "hrrr"],
                        default=["metar", "taf", "hrrr"])
    parser.add_argument("--icaos", nargs="+",
                        help="Restrict to specific ICAO codes")
    parser.add_argument("--metar-hours", type=int, default=DEFAULT_METAR_HOURS)
    parser.add_argument("--skip-cache-cleanup", action="store_true")
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    metar_taf_icaos = resolve_icaos(icao_filter=args.icaos)

    print(f"\n{'=' * 60}")
    print(f"Aviation snapshot starting @ {started_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  ICAOs (METAR/TAF set): {len(metar_taf_icaos)}")
    print(f"  Sources: {args.sources}")
    print(f"{'=' * 60}\n")

    summaries = {}
    if "metar" in args.sources:
        summaries["metar"] = run_metar(metar_taf_icaos, args.metar_hours)
    if "taf" in args.sources:
        summaries["taf"] = run_taf(metar_taf_icaos)
    if "hrrr" in args.sources:
        summaries["hrrr"] = run_hrrr(args.icaos)

    if not args.skip_cache_cleanup:
        n_files, total_mb = hrrr_cleanup_cache(older_than_days=7)
        if n_files:
            logger.info("HRRR cache cleanup: removed %d files (%d MB)", n_files, total_mb)

    print(f"\n{'=' * 60}")
    print("Aviation snapshot summary")
    print(f"{'=' * 60}")
    for src, s in summaries.items():
        run_extra = f" run={s['run_time']}" if s.get("run_time") else ""
        err = f" ERR={s['error']}" if s.get("error") else ""
        print(f"  {src:6s} [{s['status']:4s}]  icaos={s['icaos']:>3d}  rows_added={s['rows_added']:>5d}{run_extra}{err}")
    print(f"{'=' * 60}")

    # Non-zero exit if any source failed (excluding TAF WARN — that's expected
    # as most TAFs lack temp groups, but the bulletins were still written).
    fail_count = sum(1 for s in summaries.values() if s["status"] == "FAIL")
    return fail_count


if __name__ == "__main__":
    sys.exit(main())
