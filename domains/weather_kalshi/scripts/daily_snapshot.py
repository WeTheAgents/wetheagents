"""Daily forecast snapshot for all Polymarket cities.

Captures NBM percentiles (US cities) + multi-model ensemble (international)
in one parquet file per day. Polymarket bracket prices are NOT fetched here —
that's `collect_all_cities.py`'s job (full bracket history with candles).

Output
------
data/raw/snapshots/snapshot_{YYYY-MM-DD}.parquet
  Columns: snapshot_time, slug, icao (US only), target_date, days_ahead,
           nbm_p1..p99, nbm_median, nbm_sigma,
           ens_mean, ens_spread, ens_n_members, multimodel_members_json
  Primary key: (slug, target_date, days_ahead)

Per-city accumulating caches (append + dedup):
  data/raw/nbm/nbm_{ICAO}.parquet           — for US cities
  data/raw/openmeteo/ensemble_{slug}.parquet — for all cities

Run after the NBM 12Z cycle publishes (~14 UTC).

Usage
-----
    python -m scripts.daily_snapshot
    python -m scripts.daily_snapshot --days-ahead 0 1 2 3
    python -m scripts.daily_snapshot --cities nyc tokyo
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cities import CITIES, City
from src.nbm_client import fetch_nbm_batch, save_nbm_snapshot
from src.openmeteo_client import (
    fetch_ensemble_forecast_sync,
    fetch_multimodel_ensemble_sync,
    save_ensemble_snapshot,
)
from src.stations import STATIONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SNAPSHOT_DIR = ROOT / "data" / "raw" / "snapshots"
DEFAULT_DAYS_AHEAD = [0, 1, 2, 3]


def slug_to_icao() -> dict[str, str]:
    """Polymarket slug → ICAO (US cities with NBM-eligible stations only)."""
    return {
        s.polymarket_city_slug: s.icao
        for s in STATIONS.values()
        if s.polymarket_city_slug
    }


def make_row(snapshot_time: datetime, slug: str, target: date, d_ahead: int) -> dict:
    """Empty row with primary-key fields populated."""
    return {
        "snapshot_time": snapshot_time,
        "slug": slug,
        "target_date": target,
        "days_ahead": d_ahead,
    }


def fetch_nbm_for_us_cities(
    us_cities: list[City],
    days_ahead: list[int],
    snapshot_time: datetime,
    today: date,
) -> tuple[list[dict], dict[str, int]]:
    """Fetch NBM percentiles for all NBM-eligible US cities. One GRIB2 per horizon."""
    slug_icao = slug_to_icao()
    icao_to_slug = {v: k for k, v in slug_icao.items()}

    # Skip duplicate slugs (e.g. "new-york-city" → same coords as "nyc")
    seen_icaos: set[str] = set()
    icaos: list[str] = []
    for city in us_cities:
        if city.slug == "new-york-city":
            continue
        icao = slug_icao.get(city.slug)
        if not icao or icao in seen_icaos:
            continue
        icaos.append(icao)
        seen_icaos.add(icao)

    rows = []
    counts = {"ok": 0, "fail": 0}

    for d_ahead in days_ahead:
        target = today + timedelta(days=d_ahead)
        try:
            forecasts = fetch_nbm_batch(stations=icaos, days_ahead=d_ahead)
        except Exception as e:
            logger.warning("NBM fetch failed for d+%d: %s", d_ahead, e)
            counts["fail"] += len(icaos)
            continue

        got = {nbf.station for nbf in forecasts}
        counts["ok"] += len(got)
        counts["fail"] += len(set(icaos) - got)

        for nbf in forecasts:
            save_nbm_snapshot([nbf], nbf.station)
            slug = icao_to_slug.get(nbf.station)
            if not slug:
                continue
            row = make_row(snapshot_time, slug, target, d_ahead)
            row["icao"] = nbf.station
            row["nbm_median"] = nbf.median
            row["nbm_sigma"] = nbf.sigma
            for p, v in nbf.percentiles.items():
                row[f"nbm_p{p}"] = v
            rows.append(row)

    return rows, counts


def fetch_us_ensemble(
    us_cities: list[City],
    snapshot_time: datetime,
    today: date,
) -> tuple[list[dict], dict[str, int]]:
    """GEFS single-model ensemble for US cities (matches historical KLGA/etc. cache)."""
    slug_icao = slug_to_icao()
    rows = []
    counts = {"ok": 0, "fail": 0}

    for city in us_cities:
        if city.slug == "new-york-city":
            continue
        icao = slug_icao.get(city.slug)
        if not icao:
            continue
        try:
            forecasts = fetch_ensemble_forecast_sync(
                lat=city.lat, lon=city.lon, station=icao,
                forecast_days=7, past_days=0,
            )
        except Exception as e:
            logger.warning("GEFS ensemble failed for %s: %s", city.slug, e)
            counts["fail"] += 1
            continue
        if not forecasts:
            counts["fail"] += 1
            continue

        save_ensemble_snapshot(forecasts, icao)
        counts["ok"] += 1
        for ef in forecasts:
            d_ahead = (ef.target_date - today).days
            row = make_row(snapshot_time, city.slug, ef.target_date, d_ahead)
            row["icao"] = icao
            row["ens_mean"] = ef.mean
            row["ens_spread"] = ef.spread
            row["ens_n_members"] = ef.n_members
            rows.append(row)

    return rows, counts


def fetch_intl_ensemble(
    intl_cities: list[City],
    snapshot_time: datetime,
    today: date,
) -> tuple[list[dict], dict[str, int]]:
    """Multi-model ensemble (~150 members) for international cities."""
    rows = []
    counts = {"ok": 0, "fail": 0}

    for city in intl_cities:
        try:
            forecasts = fetch_multimodel_ensemble_sync(
                lat=city.lat, lon=city.lon, station=city.slug,
                temperature_unit="celsius" if city.unit == "C" else "fahrenheit",
                timezone=city.timezone,
                forecast_days=7,
            )
        except Exception as e:
            logger.warning("Multi-model ensemble failed for %s: %s", city.slug, e)
            counts["fail"] += 1
            continue
        if not forecasts:
            counts["fail"] += 1
            continue

        save_ensemble_snapshot(forecasts, city.slug)
        counts["ok"] += 1
        for ef in forecasts:
            d_ahead = (ef.target_date - today).days
            row = make_row(snapshot_time, city.slug, ef.target_date, d_ahead)
            row["ens_mean"] = ef.mean
            row["ens_spread"] = ef.spread
            row["ens_n_members"] = ef.n_members
            row["multimodel_members_json"] = json.dumps(ef.member_highs)
            rows.append(row)

    return rows, counts


def merge_rows(*chunks: list[dict]) -> pd.DataFrame:
    """Merge multiple row sets, joining on (slug, target_date, days_ahead)."""
    flat = []
    for chunk in chunks:
        flat.extend(chunk)
    if not flat:
        return pd.DataFrame()

    df = pd.DataFrame(flat)
    pk = ["slug", "target_date", "days_ahead"]
    if df.empty:
        return df

    # Group by PK and merge fields (last non-null wins)
    grouped = df.groupby(pk, as_index=False, dropna=False).agg("last")
    return grouped


def capture_snapshot(
    days_ahead: list[int] | None = None,
    cities_filter: list[str] | None = None,
) -> Path:
    """Capture full daily forecast snapshot. Returns path to saved parquet."""
    if days_ahead is None:
        days_ahead = DEFAULT_DAYS_AHEAD

    today = date.today()
    snapshot_time = datetime.now(timezone.utc)

    # Resolve city set
    if cities_filter:
        cities = [CITIES[c] for c in cities_filter if c in CITIES]
        unknown = [c for c in cities_filter if c not in CITIES]
        if unknown:
            logger.warning("Unknown city slugs ignored: %s", unknown)
    else:
        cities = list(CITIES.values())

    # Skip duplicate slug
    cities = [c for c in cities if c.slug != "new-york-city"]
    us_cities = [c for c in cities if c.nbm]
    intl_cities = [c for c in cities if not c.nbm]

    logger.info(
        "Capturing snapshot %s @ %s — %d US (NBM+GEFS), %d intl (multi-model), horizons=%s",
        today, snapshot_time.strftime("%H:%M UTC"),
        len(us_cities), len(intl_cities), days_ahead,
    )

    nbm_rows, nbm_stats = fetch_nbm_for_us_cities(us_cities, days_ahead, snapshot_time, today)
    us_ens_rows, us_ens_stats = fetch_us_ensemble(us_cities, snapshot_time, today)
    intl_rows, intl_stats = fetch_intl_ensemble(intl_cities, snapshot_time, today)

    df = merge_rows(nbm_rows, us_ens_rows, intl_rows)
    if df.empty:
        logger.error("No data captured!")
        raise RuntimeError("Snapshot fetched zero rows")

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOT_DIR / f"snapshot_{today.isoformat()}.parquet"

    if out_path.exists():
        existing = pd.read_parquet(out_path)
        if "slug" in existing.columns:
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(
                subset=["slug", "target_date", "days_ahead"], keep="last",
            )
        else:
            logger.warning(
                "Existing %s uses legacy schema (no 'slug' column); overwriting",
                out_path.name,
            )

    df.to_parquet(out_path, index=False)

    print(f"\n{'=' * 60}")
    print(f"Daily Snapshot — {today} ({snapshot_time.strftime('%H:%M UTC')})")
    print(f"{'=' * 60}")
    print(f"  Rows in file:       {len(df)}")
    print(f"  Cities covered:     {df['slug'].nunique()}")
    print(f"  NBM:        ok={nbm_stats['ok']:3d}  fail={nbm_stats['fail']:3d}")
    print(f"  GEFS (US):  ok={us_ens_stats['ok']:3d}  fail={us_ens_stats['fail']:3d}")
    print(f"  Multi-model (intl): ok={intl_stats['ok']:3d}  fail={intl_stats['fail']:3d}")
    print(f"  Saved:      {out_path}")
    print(f"{'=' * 60}")

    # Compact per-row preview (today's horizon only)
    today_rows = df[df["days_ahead"] == 0].head(20)
    for _, r in today_rows.iterrows():
        slug = str(r["slug"])
        nbm_sig = r.get("nbm_sigma")
        nbm_med = r.get("nbm_median")
        if pd.notna(nbm_sig) and pd.notna(nbm_med):
            nbm = f"NBM sigma={float(nbm_sig):.2f}F med={float(nbm_med):.1f}F"
        else:
            nbm = "NBM=N/A"
        ens_sp = r.get("ens_spread")
        ens = f"ens={float(ens_sp):.2f}" if pd.notna(ens_sp) else "ens=N/A"
        print(f"  {slug:18s} D+0  {nbm:35s}  {ens}")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily forecast snapshot")
    parser.add_argument("--days-ahead", type=int, nargs="+", default=DEFAULT_DAYS_AHEAD)
    parser.add_argument("--cities", nargs="+", help="Restrict to specific slugs")
    args = parser.parse_args()
    capture_snapshot(args.days_ahead, args.cities)


if __name__ == "__main__":
    main()
