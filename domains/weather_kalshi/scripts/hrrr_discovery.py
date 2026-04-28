"""HRRR plumbing probe — validates herbie + AWS S3 + cfgrib stack end-to-end.

Mirrors scripts/nbm_discovery.py. Run before integrating HRRR into
the daily orchestrator. Exits 0 only if all 13 US ICAOs return finite
temperatures in a plausible range.

Usage:
    PYTHONIOENCODING=utf-8 uv run --no-project python scripts/hrrr_discovery.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hrrr_client import (
    fetch_run,
    latest_available_run,
    points_to_dataframe,
)
from src.stations import POLYMARKET_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PLAUSIBLE_F_LO = -50.0
PLAUSIBLE_F_HI = 140.0


def main() -> int:
    points = {icao: (get_station(icao).lat, get_station(icao).lon)
              for icao in POLYMARKET_STATIONS}

    print(f"Probing HRRR for {len(points)} ICAOs: {sorted(points)}")

    run_time = latest_available_run()
    if run_time is None:
        print("FAIL: no HRRR cycle available within 6h lookback")
        return 1

    print(f"Latest available run: {run_time.isoformat()}")

    rows = fetch_run(run_time, points, fxx_range=[1, 6, 12])
    if not rows:
        print("FAIL: fetch_run returned 0 rows")
        return 2

    df = points_to_dataframe(rows)
    print(f"Fetched {len(df)} rows ({df['icao'].nunique()} ICAOs × {df['lead_hours'].nunique()} fxx)")

    # Sanity: every ICAO produced at least one finite forecast in plausible range
    bad = []
    for icao in points:
        sub = df[df["icao"] == icao]
        if sub.empty:
            bad.append((icao, "no rows"))
            continue
        if sub["temp_2m_f"].isna().all():
            bad.append((icao, "all NaN"))
            continue
        f_min = sub["temp_2m_f"].min()
        f_max = sub["temp_2m_f"].max()
        if f_min < PLAUSIBLE_F_LO or f_max > PLAUSIBLE_F_HI:
            bad.append((icao, f"out-of-range [{f_min:.1f}, {f_max:.1f}]"))

    print()
    print(f"{'ICAO':<8}{'lat':>8}{'lon':>9}  {'F+1':>7}{'F+6':>7}{'F+12':>7}")
    for icao in sorted(points):
        sub = df[df["icao"] == icao].set_index("lead_hours")
        f1 = sub.loc[1, "temp_2m_f"] if 1 in sub.index else float("nan")
        f6 = sub.loc[6, "temp_2m_f"] if 6 in sub.index else float("nan")
        f12 = sub.loc[12, "temp_2m_f"] if 12 in sub.index else float("nan")
        lat, lon = points[icao]
        print(f"{icao:<8}{lat:8.3f}{lon:9.3f}  {f1:7.1f}{f6:7.1f}{f12:7.1f}")

    print()
    if bad:
        print(f"FAIL: {len(bad)} ICAOs with issues:")
        for icao, why in bad:
            print(f"  {icao}: {why}")
        return 3

    print("PASS: all ICAOs returned finite temps in plausible range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
