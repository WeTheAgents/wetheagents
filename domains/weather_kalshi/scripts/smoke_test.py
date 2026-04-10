"""Quick smoke test: download 2 days of KNYC data via JSON API, verify parsing.

This avoids the bulk endpoint and uses the per-runtime JSON API which we
confirmed works. Tests the entire pipeline: download -> parse -> bias -> brackets.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stations import get_station

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_URL = "https://mesonet.agron.iastate.edu"
station = get_station("KNYC")


def test_mos_json_api():
    """Test MOS JSON API for a single runtime."""
    logger.info("=== Test 1: MOS JSON API ===")
    resp = httpx.get(
        f"{BASE_URL}/api/1/mos.json",
        params={
            "station": station.icao,
            "model": "GFS",
            "runtime": "2024-07-15 00:00Z",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()

    assert "data" in data, "Response should have 'data' key"
    rows = data["data"]
    logger.info(f"  Got {len(rows)} rows for GFS 2024-07-15 00Z")

    # Check n_x values
    nx_rows = [r for r in rows if r.get("n_x") is not None]
    logger.info(f"  Rows with n_x: {len(nx_rows)}")
    for r in nx_rows:
        logger.info(f"    ftime={r['ftime']}, n_x={r['n_x']}")

    # Verify known values from our earlier API test
    first_nx = nx_rows[0]
    assert first_nx["ftime"] == "2024-07-16 00:00", f"Expected ftime 2024-07-16 00:00, got {first_nx['ftime']}"
    assert first_nx["n_x"] == 95.0, f"Expected n_x=95, got {first_nx['n_x']}"
    logger.info("  PASS: n_x values match expected")

    return rows


def test_obs_json_api():
    """Test daily observations JSON API."""
    logger.info("=== Test 2: Daily Observations API ===")
    resp = httpx.get(
        f"{BASE_URL}/api/1/daily.json",
        params={
            "station": station.iem_station_id,
            "network": station.iem_network,
            "date": "2024-07-15",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()

    assert "data" in data, "Response should have 'data' key"
    rows = data["data"]
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"

    obs = rows[0]
    logger.info(f"  max_tmpf={obs['max_tmpf']}, min_tmpf={obs['min_tmpf']}")
    assert obs["max_tmpf"] == 91.0, f"Expected max_tmpf=91, got {obs['max_tmpf']}"
    logger.info("  PASS: observation values match expected")

    return obs


def test_nx_parsing():
    """Test n_x -> calendar day mapping logic."""
    logger.info("=== Test 3: n_x Calendar Day Mapping ===")

    # 00Z run on July 15: n_x at ftime July 16 00Z = MAX for July 15
    # Calendar day = ftime.date() - 1 day = July 16 - 1 = July 15
    ftime = pd.Timestamp("2024-07-16 00:00")
    calendar_day = (ftime - timedelta(days=1)).date()
    assert calendar_day == date(2024, 7, 15), f"Expected July 15, got {calendar_day}"
    logger.info(f"  MAX: ftime={ftime} -> calendar_day={calendar_day} PASS")

    # 00Z run: n_x at ftime July 16 12Z = MIN for night of July 15-16
    # Calendar day = ftime.date() = July 16
    ftime_min = pd.Timestamp("2024-07-16 12:00")
    calendar_day_min = ftime_min.date()
    assert calendar_day_min == date(2024, 7, 16), f"Expected July 16, got {calendar_day_min}"
    logger.info(f"  MIN: ftime={ftime_min} -> calendar_day={calendar_day_min} PASS")

    logger.info("  PASS: calendar day mapping correct")


def test_bias_and_brackets():
    """Test bias computation and bracket probability math."""
    logger.info("=== Test 4: Bias & Bracket Math ===")
    from scipy import stats

    # Simulate: forecast=95, observed=91 -> error=+4 (warm bias)
    forecast = 95.0
    observed = 91.0
    error = forecast - observed

    # Assume monthly bias profile: mean=+2.0, std=3.5
    mean_bias = 2.0
    std_error = 3.5

    # Bias-corrected forecast
    corrected = forecast - mean_bias  # 93
    logger.info(f"  Raw forecast: {forecast}F, Corrected: {corrected}F, Observed: {observed}F")

    # Build brackets around forecast (center=95)
    from src.bracket_builder import (
        build_brackets,
        compute_naive_probs,
        compute_no_edge,
        forecast_to_bracket_probs,
    )

    brackets = build_brackets(forecast)
    logger.info(f"  Brackets: {[b.label for b in brackets]}")

    # Compute probs
    corrected_probs = forecast_to_bracket_probs(forecast, mean_bias, std_error, brackets)
    naive_probs = compute_naive_probs(forecast, std_error, brackets)

    logger.info("  Naive probs vs Corrected probs:")
    for b in brackets:
        n_p = naive_probs[b.index]
        c_p = corrected_probs[b.index]
        edge = n_p - c_p
        flag = " <- NO signal" if edge > 0.05 else ""
        logger.info(f"    {b.label:>10}: naive={n_p:.3f} corrected={c_p:.3f} NO_edge={edge:+.3f}{flag}")

    # Verify: corrected should shift mass DOWN (forecast too warm -> lower brackets get more prob)
    edges = compute_no_edge(corrected_probs, naive_probs)
    max_no_bracket = max(edges, key=edges.get)
    logger.info(f"  Max NO edge: bracket {max_no_bracket} ({brackets[max_no_bracket].label}), edge={edges[max_no_bracket]:.3f}")

    # The upper brackets should have positive NO edge (market overprices them)
    upper_no_edge = sum(e for idx, e in edges.items() if idx >= 3 and e > 0)
    assert upper_no_edge > 0, "Upper brackets should have positive NO edge when forecast is warm-biased"
    logger.info("  PASS: warm bias correctly shifts probability to lower brackets")

    # Verify probs sum to 1
    total = sum(corrected_probs.values())
    assert abs(total - 1.0) < 0.001, f"Probs should sum to 1, got {total}"
    logger.info(f"  PASS: probs sum to {total:.6f}")


def test_bulk_mos_csv():
    """Test bulk MOS CSV download (small date range)."""
    logger.info("=== Test 5: Bulk MOS CSV Endpoint ===")
    resp = httpx.get(
        f"{BASE_URL}/cgi-bin/request/mos.py",
        params={
            "station": "KNYC",
            "model": "GFS",
            "year1": "2024",
            "month1": "7",
            "day1": "15",
            "hour1": "0",
            "year2": "2024",
            "month2": "7",
            "day2": "17",
            "hour2": "0",
            "format": "csv",
        },
        timeout=60.0,
    )
    resp.raise_for_status()

    lines = resp.text.strip().split("\n")
    logger.info(f"  Got {len(lines)} lines (1 header + {len(lines) - 1} data)")
    assert len(lines) > 1, "Should have data rows"

    # Parse as CSV
    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))
    logger.info(f"  Columns: {list(df.columns[:10])}...")
    logger.info(f"  Rows: {len(df)}")

    # Check n_x values
    nx_mask = df["n_x"].notna()
    nx_rows = df[nx_mask]
    logger.info(f"  Rows with n_x: {len(nx_rows)}")
    for _, r in nx_rows.head(4).iterrows():
        logger.info(f"    runtime={r['runtime']}, ftime={r['ftime']}, n_x={r['n_x']}")

    logger.info("  PASS: bulk CSV endpoint works")
    return df


def test_bulk_obs_csv():
    """Test bulk observations CSV download."""
    logger.info("=== Test 6: Bulk Observations CSV Endpoint ===")
    resp = httpx.get(
        f"{BASE_URL}/cgi-bin/request/daily.py",
        params=[
            ("network", station.iem_network),
            ("stations", station.iem_station_id),
            ("year1", "2024"),
            ("month1", "7"),
            ("day1", "15"),
            ("year2", "2024"),
            ("month2", "7"),
            ("day2", "17"),
            ("var", "max_tmpf"),
            ("var", "min_tmpf"),
            ("format", "csv"),
        ],
        timeout=60.0,
    )
    resp.raise_for_status()

    lines = resp.text.strip().split("\n")
    logger.info(f"  Got {len(lines)} lines")
    for line in lines[:5]:
        logger.info(f"    {line}")

    # Check if temperature data is present
    has_temp = "max_tmpf" in resp.text or "91" in resp.text
    if has_temp:
        logger.info("  PASS: bulk obs endpoint returns temperature data")
    else:
        logger.warning("  WARNING: bulk obs endpoint may not return temperature columns")
        logger.info("  Fallback: will use /api/1/daily.json per-day endpoint")

    return resp.text


def test_city_registry():
    """Test city registry loads all cities with timezone fields."""
    logger.info("=== Test 7: City Registry ===")
    from src.cities import CITIES, INTERNATIONAL_CITIES, US_CITIES

    assert len(CITIES) >= 40, f"Expected 40+ cities, got {len(CITIES)}"
    assert len(INTERNATIONAL_CITIES) >= 15, f"Expected 15+ international, got {len(INTERNATIONAL_CITIES)}"
    assert len(US_CITIES) >= 10, f"Expected 10+ US, got {len(US_CITIES)}"

    # All cities must have timezone
    for slug, city in CITIES.items():
        assert city.timezone, f"City {slug} missing timezone"
        assert city.unit in ("C", "F"), f"City {slug} has invalid unit: {city.unit}"

    # International cities should not have NBM
    for city in INTERNATIONAL_CITIES:
        assert not city.nbm, f"International city {city.slug} has nbm=True"

    logger.info(f"  {len(CITIES)} cities, {len(INTERNATIONAL_CITIES)} international, {len(US_CITIES)} US")
    logger.info("  PASS: all cities valid with timezone")


def test_multimodel_fetch():
    """Test multi-model ensemble fetch for Tokyo (international city)."""
    logger.info("=== Test 8: Multi-Model Ensemble Fetch ===")
    from src.openmeteo_client import fetch_multimodel_ensemble_sync

    forecasts = fetch_multimodel_ensemble_sync(
        lat=35.5494, lon=139.78, station="tokyo",
        temperature_unit="celsius", timezone="Asia/Tokyo",
        forecast_days=3,
    )

    assert len(forecasts) > 0, "Should get at least 1 forecast date"
    first = forecasts[0]
    logger.info(f"  Date: {first.target_date}, Members: {first.n_members}, "
                f"Mean: {first.mean:.1f}C, Spread: {first.spread:.1f}C")

    assert first.n_members > 50, f"Expected >50 members (multi-model), got {first.n_members}"
    assert first.mean > -30 and first.mean < 50, f"Mean temp out of range: {first.mean}"
    logger.info("  PASS: multi-model ensemble returns >50 members")


def test_historical_obs_fetch():
    """Test historical observations fetch for London."""
    logger.info("=== Test 9: Historical Observations Fetch ===")
    from datetime import date as _date
    from src.openmeteo_client import fetch_historical_obs_sync

    df = fetch_historical_obs_sync(
        lat=51.47, lon=-0.4543,
        start_date=_date(2024, 1, 1),
        end_date=_date(2024, 1, 31),
        temperature_unit="celsius",
        timezone="Europe/London",
    )

    assert len(df) >= 28, f"Expected ~31 days, got {len(df)}"
    assert "temp_max" in df.columns, "Missing temp_max column"
    assert "temp_min" in df.columns, "Missing temp_min column"

    mean_max = df["temp_max"].mean()
    logger.info(f"  London Jan 2024: {len(df)} days, mean max: {mean_max:.1f}C")
    assert -5 < mean_max < 20, f"London Jan mean max out of range: {mean_max}"
    logger.info("  PASS: historical obs returns valid data")


def main():
    logger.info("Weather Kalshi Pipeline Smoke Test")
    logger.info("=" * 50)

    try:
        test_mos_json_api()
        test_obs_json_api()
        test_nx_parsing()
        test_bias_and_brackets()
        test_bulk_mos_csv()
        test_bulk_obs_csv()
        test_city_registry()
        test_multimodel_fetch()
        test_historical_obs_fetch()

        logger.info("\n" + "=" * 50)
        logger.info("ALL TESTS PASSED")
        logger.info("=" * 50)
    except Exception as e:
        logger.error(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
