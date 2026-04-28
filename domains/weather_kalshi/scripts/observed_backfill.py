"""Daily backfill of observed daily max/min temperatures for all Polymarket cities.

Fills the Y label needed for ML training and edge measurement against snapshots.

Sources
-------
- US cities (polymarket_cities.json `nbm: true`) → IEM daily.json API
  (matches Wunderground resolution that Polymarket uses for settlement)
- International cities (`nbm: false`) → Open-Meteo Archive (ERA5 reanalysis)
  ERA5 has ~5-day publication lag and underestimates daily max by 0.5-1.7C
  vs station obs. Adequate for ML feature engineering, NOT for resolution.

Output
------
data/raw/observed/obs_{slug}.parquet — one file per city, append + dedup on date.
Columns: slug, date, temp_max_native, temp_min_native, temp_max_f, temp_min_f,
         unit, source, fetched_at

Usage
-----
    python -m scripts.observed_backfill                     # last 30 days
    python -m scripts.observed_backfill --days-back 60
    python -m scripts.observed_backfill --start 2026-03-25
    python -m scripts.observed_backfill --cities nyc tokyo  # subset
"""

from __future__ import annotations

import argparse
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

from src.cities import CITIES, City
from src.openmeteo_client import fetch_historical_obs_sync
from src.stations import STATIONS, Station

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = ROOT / "data" / "raw" / "observed"
DEFAULT_DAYS_BACK = 30
IEM_DAILY_URL = "https://mesonet.agron.iastate.edu/api/1/daily.json"
IEM_RATE_LIMIT = 0.6  # seconds between IEM calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug_to_iem_station() -> dict[str, Station]:
    """Map Polymarket slug → Station (only for US cities with IEM coverage)."""
    return {
        s.polymarket_city_slug: s
        for s in STATIONS.values()
        if s.polymarket_city_slug and s.iem_station_id
    }


def c_to_f(c: float | None) -> float | None:
    if c is None:
        return None
    return c * 9.0 / 5.0 + 32.0


def f_to_c(f: float | None) -> float | None:
    if f is None:
        return None
    return (f - 32.0) * 5.0 / 9.0


def load_existing(slug: str) -> pd.DataFrame:
    path = OUTPUT_DIR / f"obs_{slug}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def existing_dates(df: pd.DataFrame) -> set[date]:
    if df.empty or "date" not in df.columns:
        return set()
    out = set()
    for d in df["date"]:
        if isinstance(d, date) and not isinstance(d, pd.Timestamp):
            out.add(d)
        elif hasattr(d, "date"):
            out.add(d.date())
        else:
            out.add(date.fromisoformat(str(d)))
    return out


def save_observed(slug: str, new_rows: list[dict]) -> int:
    """Merge new rows into per-city parquet. Returns count of newly added rows."""
    if not new_rows:
        return 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(new_rows)
    path = OUTPUT_DIR / f"obs_{slug}.parquet"
    if path.exists():
        existing = pd.read_parquet(path)
        before = len(existing)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["slug", "date"], keep="last")
        after = len(combined)
        added = after - before
    else:
        combined = new_df
        added = len(new_df)
    combined = combined.sort_values("date").reset_index(drop=True)
    combined.to_parquet(path, index=False)
    return added


# ---------------------------------------------------------------------------
# IEM fetcher (US cities)
# ---------------------------------------------------------------------------

def fetch_iem_day(station: Station, day: date, client: httpx.Client) -> dict | None:
    """Fetch one day of observations from IEM. Returns canonical row or None."""
    try:
        resp = client.get(
            IEM_DAILY_URL,
            params={
                "station": station.iem_station_id,
                "network": station.iem_network,
                "date": day.isoformat(),
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("IEM fetch failed %s %s: %s", station.iem_station_id, day, e)
        return None

    data = payload.get("data") or []
    if not data:
        return None

    # IEM returns one record per (date, station)
    rec = data[0]
    tmax_f = rec.get("max_tmpf")
    tmin_f = rec.get("min_tmpf")
    if tmax_f is None and tmin_f is None:
        return None

    return {
        "tmax_f": float(tmax_f) if tmax_f is not None else None,
        "tmin_f": float(tmin_f) if tmin_f is not None else None,
    }


def backfill_us_city(slug: str, station: Station, days: list[date]) -> int:
    """Backfill IEM observations for a single US city. Returns rows added."""
    new_rows = []
    fetched_at = datetime.now(timezone.utc)
    with httpx.Client() as client:
        for day in days:
            obs = fetch_iem_day(station, day, client)
            time.sleep(IEM_RATE_LIMIT)
            if obs is None:
                continue
            new_rows.append({
                "slug": slug,
                "date": day,
                "temp_max_native": obs["tmax_f"],
                "temp_min_native": obs["tmin_f"],
                "temp_max_f": obs["tmax_f"],
                "temp_min_f": obs["tmin_f"],
                "unit": "F",
                "source": "iem",
                "iem_station": station.iem_station_id,
                "fetched_at": fetched_at,
            })

    added = save_observed(slug, new_rows)
    logger.info(
        "IEM %s (%s): fetched %d / %d days, added %d rows",
        slug, station.iem_station_id, len(new_rows), len(days), added,
    )
    return added


# ---------------------------------------------------------------------------
# Open-Meteo Archive fetcher (international + US fallback)
# ---------------------------------------------------------------------------

def backfill_openmeteo_city(city: City, days: list[date]) -> int:
    """Backfill Open-Meteo Archive observations for a city. Returns rows added."""
    if not days:
        return 0

    start = min(days)
    end = max(days)
    unit_arg = "celsius" if city.unit == "C" else "fahrenheit"
    fetched_at = datetime.now(timezone.utc)

    try:
        df = fetch_historical_obs_sync(
            lat=city.lat,
            lon=city.lon,
            start_date=start,
            end_date=end,
            temperature_unit=unit_arg,
            timezone=city.timezone,
        )
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Open-Meteo Archive failed for %s: %s", city.slug, e)
        return 0

    if df.empty:
        logger.info("Open-Meteo Archive empty for %s (%s..%s)", city.slug, start, end)
        return 0

    wanted = set(days)
    new_rows = []
    for _, row in df.iterrows():
        d = row["date"]
        if not isinstance(d, date) or isinstance(d, pd.Timestamp):
            d = d.date() if hasattr(d, "date") else date.fromisoformat(str(d))
        if d not in wanted:
            continue

        tmax = row.get("temp_max")
        tmin = row.get("temp_min")
        if pd.isna(tmax) and pd.isna(tmin):
            continue

        tmax_native = float(tmax) if pd.notna(tmax) else None
        tmin_native = float(tmin) if pd.notna(tmin) else None
        if city.unit == "C":
            tmax_f = c_to_f(tmax_native)
            tmin_f = c_to_f(tmin_native)
        else:
            tmax_f = tmax_native
            tmin_f = tmin_native

        new_rows.append({
            "slug": city.slug,
            "date": d,
            "temp_max_native": tmax_native,
            "temp_min_native": tmin_native,
            "temp_max_f": tmax_f,
            "temp_min_f": tmin_f,
            "unit": city.unit,
            "source": "openmeteo_archive",
            "iem_station": "",
            "fetched_at": fetched_at,
        })

    added = save_observed(city.slug, new_rows)
    logger.info(
        "Open-Meteo %s (%s): fetched %d / %d days, added %d rows",
        city.slug, city.unit, len(new_rows), len(days), added,
    )
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def determine_target_days(
    slug: str, start: date, end: date, *, force: bool = False,
) -> list[date]:
    """Return dates to fetch for a city, skipping ones already on disk."""
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if force:
        return all_days
    have = existing_dates(load_existing(slug))
    return [d for d in all_days if d not in have]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill observed temperatures")
    parser.add_argument("--days-back", type=int, default=DEFAULT_DAYS_BACK)
    parser.add_argument("--start", type=date.fromisoformat,
                        help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat,
                        help="Override end date (default: yesterday)")
    parser.add_argument("--cities", nargs="+", help="Restrict to specific slugs")
    parser.add_argument("--force", action="store_true",
                        help="Refetch dates even if already cached")
    parser.add_argument("--openmeteo-only", action="store_true",
                        help="Use Open-Meteo Archive even for US cities (testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report gaps only; no fetches")
    args = parser.parse_args()

    today = date.today()
    end = args.end if args.end else today - timedelta(days=1)
    start = args.start if args.start else end - timedelta(days=args.days_back - 1)

    if start > end:
        logger.error("start (%s) is after end (%s)", start, end)
        sys.exit(1)

    if args.cities:
        target_cities = [CITIES[c] for c in args.cities if c in CITIES]
        missing = [c for c in args.cities if c not in CITIES]
        if missing:
            logger.warning("Unknown city slugs: %s", missing)
    else:
        target_cities = list(CITIES.values())

    iem_lookup = slug_to_iem_station()

    logger.info(
        "Backfill window: %s → %s (%d days), %d cities",
        start, end, (end - start).days + 1, len(target_cities),
    )

    # Skip the duplicate slug "new-york-city" — same coords as "nyc"
    target_cities = [c for c in target_cities if c.slug != "new-york-city"]

    summary = {"iem_added": 0, "openmeteo_added": 0, "skipped": 0, "errors": 0}

    for city in target_cities:
        days = determine_target_days(city.slug, start, end, force=args.force)
        if not days:
            summary["skipped"] += 1
            continue

        if args.dry_run:
            logger.info("%s: %d days to fetch (%s..%s)",
                        city.slug, len(days), days[0], days[-1])
            continue

        try:
            if not args.openmeteo_only and city.slug in iem_lookup:
                added = backfill_us_city(city.slug, iem_lookup[city.slug], days)
                summary["iem_added"] += added
            else:
                added = backfill_openmeteo_city(city, days)
                summary["openmeteo_added"] += added
        except Exception as e:
            logger.exception("Backfill failed for %s: %s", city.slug, e)
            summary["errors"] += 1

    print(f"\n{'=' * 60}")
    print(f"Observed backfill complete — {start} to {end}")
    print(f"  IEM rows added:        {summary['iem_added']}")
    print(f"  Open-Meteo rows added: {summary['openmeteo_added']}")
    print(f"  Cities already up-to-date: {summary['skipped']}")
    print(f"  Errors:                {summary['errors']}")
    print(f"{'=' * 60}")

    if summary["errors"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
