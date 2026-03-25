"""NBM Discovery: validate herbie-data, inspect GRIB2 inventory, test point extraction.

Run this BEFORE writing production NBM code to discover:
  1. Exact GRIB2 search strings for temperature percentiles
  2. Correct fxx value for MaxT from 12Z cycle
  3. Whether eccodes/cfgrib works on this machine

Usage:
    python scripts/nbm_discovery.py
    python scripts/nbm_discovery.py --date 2026-03-24
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stations import POLYMARKET_STATIONS, get_station


def discover_inventory(run_date: str, fxx: int = 24) -> pd.DataFrame | None:
    """Fetch and display NBM GRIB2 inventory for temperature fields."""
    from herbie import Herbie

    print(f"\n{'=' * 70}")
    print(f"NBM Inventory: {run_date} 12Z, fxx={fxx}")
    print(f"{'=' * 70}")

    try:
        H = Herbie(f"{run_date} 12:00", model="nbm", product="co", fxx=fxx)
    except Exception as e:
        print(f"  ERROR creating Herbie object: {e}")
        return None

    try:
        inv = H.inventory(":TMP:")
        if inv is None or inv.empty:
            print("  No TMP fields found in inventory.")
            return None
        print(f"\n  Found {len(inv)} TMP fields:")
        for _, row in inv.iterrows():
            search = row.get("search_this", row.get("searchString", ""))
            print(f"    {search}")
        return inv
    except Exception as e:
        print(f"  ERROR fetching inventory: {e}")
        return None


def discover_fxx_range(run_date: str) -> dict[int, pd.DataFrame]:
    """Test multiple fxx values to find which contain MaxT percentiles."""
    from herbie import Herbie

    print(f"\n{'=' * 70}")
    print(f"Testing fxx values for MaxT percentiles")
    print(f"{'=' * 70}")

    results = {}
    for fxx in [6, 12, 18, 24, 36, 48, 60]:
        try:
            H = Herbie(f"{run_date} 12:00", model="nbm", product="co", fxx=fxx)
            inv = H.inventory(":TMP:2 m")
            if inv is not None and not inv.empty:
                has_percentiles = any(
                    "%" in str(row.get("search_this", ""))
                    or "prob" in str(row.get("search_this", "")).lower()
                    or "P10" in str(row.get("search_this", ""))
                    or "P90" in str(row.get("search_this", ""))
                    for _, row in inv.iterrows()
                )
                n_fields = len(inv)
                print(f"  fxx={fxx:3d}: {n_fields} TMP 2m fields, percentiles={'YES' if has_percentiles else 'no'}")
                if has_percentiles:
                    results[fxx] = inv
            else:
                print(f"  fxx={fxx:3d}: no TMP 2m fields")
        except Exception as e:
            print(f"  fxx={fxx:3d}: ERROR - {e}")

    return results


def extract_point_data(run_date: str, fxx: int, search_string: str) -> None:
    """Extract point data for all Polymarket stations."""
    from herbie import Herbie

    print(f"\n{'=' * 70}")
    print(f"Point Extraction: {run_date} 12Z fxx={fxx}")
    print(f"Search: {search_string}")
    print(f"{'=' * 70}")

    try:
        H = Herbie(f"{run_date} 12:00", model="nbm", product="co", fxx=fxx)
        ds = H.xarray(search_string)
        print(f"\n  Dataset variables: {list(ds.data_vars)}")
        print(f"  Dimensions: {dict(ds.dims)}")

        # Build points DataFrame
        points = []
        for icao in POLYMARKET_STATIONS:
            st = get_station(icao)
            points.append({
                "latitude": st.lat,
                "longitude": st.lon,
                "station": icao,
            })
        points_df = pd.DataFrame(points)

        # Try pick_points
        try:
            result = ds.herbie.pick_points(points_df, method="nearest")
            print(f"\n  Pick points result type: {type(result)}")
            if isinstance(result, pd.DataFrame):
                print(f"  Columns: {list(result.columns)}")
                print(f"  Shape: {result.shape}")
                print(result.to_string())
            else:
                print(f"  Result: {result}")
        except Exception as e:
            print(f"  pick_points failed: {e}")

            # Fallback: manual nearest-point extraction
            print("\n  Trying manual extraction...")
            for icao in POLYMARKET_STATIONS:
                st = get_station(icao)
                try:
                    point = ds.sel(
                        latitude=st.lat, longitude=(st.lon % 360),
                        method="nearest"
                    )
                    for var in ds.data_vars:
                        val = float(point[var].values)
                        val_f = val * 9.0 / 5.0 - 459.67
                        print(f"    {icao}: {var} = {val:.2f}K = {val_f:.1f}F")
                except Exception as e2:
                    print(f"    {icao}: manual extraction failed - {e2}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def sigma_comparison(run_date: str) -> None:
    """Compare NBM sigma vs GEFS cache vs historical."""
    print(f"\n{'=' * 70}")
    print("Sigma Comparison (if data available)")
    print(f"{'=' * 70}")

    from src.openmeteo_client import load_ensemble_cache

    for icao in POLYMARKET_STATIONS:
        ens_cache = load_ensemble_cache(icao)
        if not ens_cache.empty:
            latest = ens_cache.sort_values("date").tail(5)
            print(f"\n  {icao} — GEFS ensemble cache (last 5 days):")
            for _, row in latest.iterrows():
                print(f"    {row['date']}: spread={row['spread']:.2f}F, "
                      f"sigma_iqr={row.get('sigma_iqr', 'N/A')}")
        else:
            print(f"\n  {icao} — no GEFS ensemble cache")


def main() -> None:
    parser = argparse.ArgumentParser(description="NBM Discovery")
    parser.add_argument(
        "--date", type=str, default=None,
        help="Run date (YYYY-MM-DD). Default: yesterday.",
    )
    args = parser.parse_args()

    if args.date:
        run_date = args.date
    else:
        # Use yesterday to ensure data is available on NOMADS
        run_date = (date.today() - timedelta(days=1)).isoformat()

    print(f"NBM Discovery — run_date={run_date}")

    # Step 1: Inventory for default fxx=24
    inv = discover_inventory(run_date, fxx=24)

    # Step 2: Test multiple fxx values
    fxx_results = discover_fxx_range(run_date)

    # Step 3: Try point extraction if we found any percentile fields
    if inv is not None and not inv.empty:
        # Try the broadest TMP 2m search first
        search = ":TMP:2 m above ground:"
        extract_point_data(run_date, fxx=24, search_string=search)

    # Step 4: Sigma comparison with cached data
    sigma_comparison(run_date)

    print(f"\n{'=' * 70}")
    print("Discovery complete. Use the search strings above in src/nbm_client.py")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
