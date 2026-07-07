"""Backfill correct day-of NBM MaxT percentiles from the AWS S3 mirror.

The forecast snapshots collected live carry a BROKEN day-of NBM max (day-of
|error| ~16-19F vs realized). Two compounding bugs in the GRIB extraction, both
fixed in src/nbm_client.py on 2026-07-07:
  1. the instantaneous "{fxx} hour fcst" TMP field was read instead of the
     windowed "0-{fxx} hour max fcst" (an overnight value, not the day's high);
  2. the CONUS Lambert grid was indexed as if it were regular lat/lon, landing
     the point lookup hundreds of km offshore.
After the fixes, day-of |error| is ~1.7F (median), matching the ensemble.

This script rebuilds a clean day-of archive for the whole price-history window by
fetching each date's own {cycle}Z fxx=18 run from S3 (the morning-of forecast the
live pipeline sees at ~14:00 UTC). Output feeds the exceedance dataset's z-score
(z = (strike - nbm_median)/nbm_sigma); the snapshot nbm_* columns are NOT usable.

Output: data/raw/nbm_backfill/nbm_dayof.parquet — one row per (slug, target_date,
days_ahead) with median, sigma, fxx and p1..p99. Idempotent: existing rows are
skipped unless --refetch. Requires cfgrib -> run via `uv run`.

Usage
-----
    uv run python -m scripts.backfill_nbm_dayof --data-root D:/.../weather_kalshi/data
    uv run python -m scripts.backfill_nbm_dayof --start 2026-06-01 --refetch
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.nbm_client import POLYMARKET_STATIONS, fetch_nbm_s3  # noqa: E402
from src.stations import STATIONS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ICAO_TO_SLUG = {s.icao: s.polymarket_city_slug for s in STATIONS.values() if s.polymarket_city_slug}
DEFAULT_START = date(2026, 3, 9)   # start of the price-history archive
FLUSH_EVERY = 10                   # write partial progress every N dates


def data_root(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("WEATHER_DATA_ROOT")
    if env:
        return Path(env)
    return ROOT / "data"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def forecast_row(f, slug: str, days_ahead: int, fetched_at: str) -> dict:
    row = {
        "slug": slug,
        "target_date": f.target_date.isoformat(),
        "days_ahead": days_ahead,
        "station": f.station,
        "cycle": f.cycle,
        "fxx": f.fxx,
        "nbm_median": f.median,
        "nbm_sigma": f.sigma,
        "fetched_at": fetched_at,
    }
    for p, v in sorted(f.percentiles.items()):
        row[f"nbm_p{p}"] = v
    return row


def load_existing(out_path: Path) -> tuple[pd.DataFrame, set]:
    if not out_path.exists():
        return pd.DataFrame(), set()
    df = pd.read_parquet(out_path)
    done = set(zip(df["slug"], df["target_date"], df["days_ahead"], strict=False))
    return df, done


def validate(df: pd.DataFrame, data: Path) -> None:
    """Report |nbm_median - realized METAR max| by month (the health check)."""
    dt_path = data / "processed" / "metar_day_table.parquet"
    if not dt_path.exists():
        logger.warning("metar_day_table missing; skipping validation")
        return
    dt = pd.read_parquet(dt_path, columns=["city_slug", "local_date", "day_max_nat"])
    dt["local_date"] = dt["local_date"].astype(str).str[:10]
    real = dt.rename(columns={"city_slug": "slug", "local_date": "target_date", "day_max_nat": "realized"})
    m = df[df["days_ahead"] == 0].merge(real, on=["slug", "target_date"], how="inner").dropna(
        subset=["nbm_median", "realized"]
    )
    if m.empty:
        logger.warning("no overlap with metar_day_table for validation")
        return
    m["abs_err"] = (m["nbm_median"] - m["realized"]).abs()
    m["mo"] = m["target_date"].str[:7]
    by_mo = m.groupby("mo")["abs_err"].agg(["mean", "median", "count"]).round(2)
    logger.info("day-of |nbm_median - realized| by month:\n%s", by_mo.to_string())
    overall = m["abs_err"].median()
    logger.info("OVERALL median |err| = %.2fF (target < 5F; broken archive was ~16.5F)", overall)
    if overall > 5.0:
        logger.error("VALIDATION FAILED: median day-of error %.2fF exceeds 5F", overall)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=None, help="default: yesterday (UTC)")
    ap.add_argument("--cycle", default="12")
    ap.add_argument("--days-ahead", default="0", help="comma list, e.g. 0 or 0,1")
    ap.add_argument("--refetch", action="store_true", help="re-fetch dates already present")
    args = ap.parse_args()

    data = data_root(args.data_root)
    out_path = data / "raw" / "nbm_backfill" / "nbm_dayof.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else (datetime.now(timezone.utc).date() - timedelta(days=1))  # noqa: UP017
    days_ahead_list = [int(x) for x in args.days_ahead.split(",")]

    existing, done = load_existing(out_path)
    fetched_at = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    expected_slugs = {ICAO_TO_SLUG[icao] for icao in POLYMARKET_STATIONS if icao in ICAO_TO_SLUG}

    new_rows: list[dict] = []
    all_frames = [existing] if not existing.empty else []
    n_dates = 0

    for d in daterange(start, end):
        n_dates += 1
        for da in days_ahead_list:
            # Skip the S3 fetch entirely when this date/horizon is already
            # complete: otherwise an incremental extend re-downloads all history.
            if not args.refetch and all((s, d.isoformat(), da) in done for s in expected_slugs):
                continue
            fc = fetch_nbm_s3(POLYMARKET_STATIONS, target_date=d, cycle=args.cycle, days_ahead=da)
            for f in fc:
                slug = ICAO_TO_SLUG.get(f.station)
                if slug is None:
                    continue
                if not args.refetch and (slug, d.isoformat(), da) in done:
                    continue
                new_rows.append(forecast_row(f, slug, da, fetched_at))
        if new_rows and n_dates % FLUSH_EVERY == 0:
            _flush(all_frames, new_rows, out_path)
            new_rows = []
            all_frames = [pd.read_parquet(out_path)]
            logger.info("flushed through %s", d)

    _flush(all_frames, new_rows, out_path)
    final = pd.read_parquet(out_path)
    logger.info("nbm_dayof backfill: %d rows, %d cities, %s..%s -> %s",
                len(final), final["slug"].nunique(),
                final["target_date"].min(), final["target_date"].max(), out_path)
    validate(final, data)


def _flush(frames: list[pd.DataFrame], new_rows: list[dict], out_path: Path) -> None:
    if not new_rows and not frames:
        return
    parts = [f for f in frames if not f.empty]
    if new_rows:
        parts.append(pd.DataFrame(new_rows))
    if not parts:
        return
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(subset=["slug", "target_date", "days_ahead"], keep="last")
    combined = combined.sort_values(["slug", "target_date", "days_ahead"]).reset_index(drop=True)
    combined.to_parquet(out_path, index=False)


if __name__ == "__main__":
    main()
