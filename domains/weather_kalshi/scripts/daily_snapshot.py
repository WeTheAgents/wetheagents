"""Daily data snapshot: capture NBM forecasts + Polymarket prices + ensemble spreads.

Run once daily (ideally around 12-14 UTC, after NBM 12Z cycle publishes).
Captures a consistent snapshot of all data sources for backtesting.

Stores snapshots in data/raw/snapshots/ as daily parquet files.
Each snapshot records: NBM percentiles, ensemble spread, and Polymarket bracket
prices at the time of capture — aligned by station and target date.

Usage:
    python -m scripts.daily_snapshot
    python -m scripts.daily_snapshot --days-ahead 1 2 3
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.nbm_client import fetch_nbm_batch, save_nbm_snapshot
from src.openmeteo_client import fetch_ensemble_forecast_sync, save_ensemble_snapshot
from src.stations import POLYMARKET_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "snapshots"


def capture_polymarket_prices(
    stations: list[str],
    target_dates: list[date],
) -> pd.DataFrame:
    """Fetch current Polymarket bracket prices via CLOB price history."""
    from src.polymarket_client import fetch_weather_events

    events = []
    for icao in stations:
        st = get_station(icao)
        city_slug = st.polymarket_city_slug
        if not city_slug:
            continue
        try:
            city_events = fetch_weather_events(
                city_slug,
                min(target_dates),
                max(target_dates) + timedelta(days=1),
            )
            events.extend(city_events)
        except Exception as e:
            logger.warning(f"Failed to fetch Polymarket events for {city_slug}: {e}")

    if not events:
        return pd.DataFrame()

    from src.polymarket_client import build_weather_df
    return build_weather_df(events)


def capture_snapshot(days_ahead: list[int] | None = None) -> Path:
    """Capture a full daily snapshot of all data sources.

    Returns path to the saved snapshot file.
    """
    if days_ahead is None:
        days_ahead = [0, 1, 2, 3]

    today = date.today()
    now = datetime.utcnow()
    target_dates = [today + timedelta(days=d) for d in days_ahead]

    rows = []

    # ---- 1. NBM percentiles ----
    for d_ahead in days_ahead:
        target = today + timedelta(days=d_ahead)
        try:
            nbm_forecasts = fetch_nbm_batch(
                POLYMARKET_STATIONS, days_ahead=d_ahead,
            )
            for nbf in nbm_forecasts:
                save_nbm_snapshot([nbf], nbf.station)
                row = {
                    "snapshot_time": now,
                    "station": nbf.station,
                    "target_date": target,
                    "days_ahead": d_ahead,
                    "nbm_median": nbf.median,
                    "nbm_sigma": nbf.sigma,
                }
                for p, v in nbf.percentiles.items():
                    row[f"nbm_p{p}"] = v
                rows.append(row)
        except Exception as e:
            logger.warning(f"NBM fetch failed for days_ahead={d_ahead}: {e}")

    # ---- 2. Ensemble spread ----
    for icao in POLYMARKET_STATIONS:
        st = get_station(icao)
        try:
            forecasts = fetch_ensemble_forecast_sync(
                st.lat, st.lon, station=icao,
                forecast_days=7, past_days=0,
            )
            save_ensemble_snapshot(forecasts, icao)
            for ef in forecasts:
                # Find matching row or create new
                matched = False
                for row in rows:
                    if row["station"] == icao and row["target_date"] == ef.target_date:
                        row["ens_mean"] = ef.mean
                        row["ens_spread"] = ef.spread
                        row["ens_n_members"] = ef.n_members
                        matched = True
                        break
                if not matched:
                    d_ahead = (ef.target_date - today).days
                    rows.append({
                        "snapshot_time": now,
                        "station": icao,
                        "target_date": ef.target_date,
                        "days_ahead": d_ahead,
                        "ens_mean": ef.mean,
                        "ens_spread": ef.spread,
                        "ens_n_members": ef.n_members,
                    })
        except Exception as e:
            logger.warning(f"Ensemble fetch failed for {icao}: {e}")

    # ---- 3. Polymarket prices ----
    try:
        pm_df = capture_polymarket_prices(POLYMARKET_STATIONS, target_dates)
        if not pm_df.empty:
            for _, pm_row in pm_df.iterrows():
                station = pm_row.get("station", "")
                mdate = pm_row.get("market_date")
                if hasattr(mdate, "date"):
                    mdate = mdate.date()
                elif isinstance(mdate, str):
                    mdate = date.fromisoformat(mdate)

                # Find matching row
                for row in rows:
                    if row["station"] == station and row["target_date"] == mdate:
                        bi = pm_row.get("bracket_index", 0)
                        row[f"pm_bracket_{bi}_price"] = pm_row.get("yes_price", 0)
                        row[f"pm_bracket_{bi}_lower"] = pm_row.get("lower")
                        row[f"pm_bracket_{bi}_upper"] = pm_row.get("upper")
                        row[f"pm_bracket_{bi}_label"] = pm_row.get("label", "")
                        break
            logger.info(f"Captured {len(pm_df)} Polymarket bracket prices")
    except Exception as e:
        logger.warning(f"Polymarket fetch failed: {e}")

    if not rows:
        logger.error("No data captured!")
        return SNAPSHOT_DIR

    # ---- Save ----
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_df = pd.DataFrame(rows)
    out_path = SNAPSHOT_DIR / f"snapshot_{today.isoformat()}.parquet"

    if out_path.exists():
        existing = pd.read_parquet(out_path)
        snapshot_df = pd.concat([existing, snapshot_df], ignore_index=True)
        snapshot_df = snapshot_df.drop_duplicates(
            subset=["station", "target_date", "days_ahead"], keep="last",
        )

    snapshot_df.to_parquet(out_path, index=False)
    logger.info(f"Saved snapshot to {out_path} ({len(snapshot_df)} rows)")

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Daily Snapshot — {today} ({now.strftime('%H:%M')} UTC)")
    print(f"{'=' * 60}")
    for _, row in snapshot_df.iterrows():
        nbm_s = f"NBM={row.get('nbm_sigma', 'N/A'):.2f}F" if pd.notna(row.get("nbm_sigma")) else "NBM=N/A"
        ens_s = f"Ens={row.get('ens_spread', 'N/A'):.2f}F" if pd.notna(row.get("ens_spread")) else "Ens=N/A"
        nbm_m = f"med={row.get('nbm_median', 'N/A'):.1f}F" if pd.notna(row.get("nbm_median")) else ""
        print(f"  {row['station']} {row['target_date']} (D+{row['days_ahead']}): {nbm_s} {ens_s} {nbm_m}")

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily data snapshot")
    parser.add_argument(
        "--days-ahead", type=int, nargs="+", default=[0, 1, 2, 3],
        help="Days ahead to capture (default: 0 1 2 3)",
    )
    args = parser.parse_args()
    capture_snapshot(args.days_ahead)


if __name__ == "__main__":
    main()
