"""Kalshi market data client via public S3 reporting files.

Data source: https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{DATE}.json
No authentication required. One JSON file per day with ALL Kalshi markets.
Files are large (100-700MB) so we stream, filter to weather markets only, and save as parquet.

Weather market ticker format:
    KXHIGHNY-26MAR23-B54.5   (inner bracket, boundary at 54.5F)
    KXHIGHNY-26MAR23-T54     (tail bracket, <= 54F or >= XF)

Bracket structure per day per city: 4 inner (B) + 2 tails (T) = 6 mutually exclusive brackets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from .stations import STATIONS

logger = logging.getLogger(__name__)

S3_BASE = "https://kalshi-public-docs.s3.amazonaws.com/reporting"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "kalshi"

# Map Kalshi report_ticker -> ICAO station code
# Kalshi uses different city abbreviations than our stations.json
KALSHI_TO_ICAO = {
    "KXHIGHNY": "KNYC",
    "KXHIGHCHI": "KMDW",
    "KXHIGHMIA": "KMIA",
}

# Reverse: ICAO -> Kalshi report_ticker
ICAO_TO_KALSHI = {v: k for k, v in KALSHI_TO_ICAO.items()}

# All weather high-temp prefixes on Kalshi (for reference)
ALL_WEATHER_PREFIXES = [
    "KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHLAX", "KXHIGHDEN",
    "KXHIGHPHIL", "KXHIGHAUS", "KXHIGHTATL", "KXHIGHTBOS", "KXHIGHTDAL",
    "KXHIGHTDC", "KXHIGHTHOU", "KXHIGHTLV", "KXHIGHTMIN", "KXHIGHTNOLA",
    "KXHIGHTOKC", "KXHIGHTPHX", "KXHIGHTSATX", "KXHIGHTSEA", "KXHIGHTSFO",
]


@dataclass
class KalshiWeatherMarket:
    """A single Kalshi weather bracket market."""

    ticker: str           # Full ticker: KXHIGHNY-26MAR23-B54.5
    report_ticker: str    # Series: KXHIGHNY
    station_icao: str     # Mapped: KNYC
    market_date: date     # Settlement date (parsed from ticker)
    bracket_type: str     # "inner" or "tail_low" or "tail_high"
    strike: float         # Boundary: 54.5 for B54.5, 54 for T54
    high_price: int       # Day's high YES price (cents 1-99)
    low_price: int        # Day's low YES price (cents 1-99)
    volume: float         # Daily contract volume
    open_interest: float  # Open interest
    status: str           # "active", "finalized", etc.
    data_date: date       # Date of the S3 report file


def parse_ticker_date(date_str: str) -> date:
    """Parse '26MAR23' -> date(2026, 3, 23)."""
    return datetime.strptime(date_str, "%y%b%d").date()


def parse_bracket(bracket_str: str, all_brackets: list[str]) -> tuple[str, float]:
    """Parse bracket identifier.

    B54.5 -> ("inner", 54.5)
    T54   -> ("tail_low" or "tail_high", 54.0)

    For tails, we determine low/high by comparing to inner bracket strikes.
    """
    if bracket_str.startswith("B"):
        return ("inner", float(bracket_str[1:]))
    elif bracket_str.startswith("T"):
        strike = float(bracket_str[1:])
        # Determine if this is low or high tail by comparing to inner brackets
        inner_strikes = [float(b[1:]) for b in all_brackets if b.startswith("B")]
        if inner_strikes:
            min_inner = min(inner_strikes)
            if strike <= min_inner:
                return ("tail_low", strike)
            else:
                return ("tail_high", strike)
        return ("tail_low", strike)
    return ("unknown", 0.0)


def parse_weather_market(
    raw: dict, data_date: date
) -> KalshiWeatherMarket | None:
    """Parse raw S3 market dict into KalshiWeatherMarket."""
    report_ticker = raw.get("report_ticker", "")
    if report_ticker not in KALSHI_TO_ICAO:
        return None

    ticker = raw.get("ticker_name", "")
    parts = ticker.split("-")
    if len(parts) < 3:
        return None

    try:
        market_date = parse_ticker_date(parts[1])
    except (ValueError, IndexError):
        return None

    bracket_str = parts[2]

    return KalshiWeatherMarket(
        ticker=ticker,
        report_ticker=report_ticker,
        station_icao=KALSHI_TO_ICAO[report_ticker],
        market_date=market_date,
        bracket_type="",  # filled later after grouping
        strike=0.0,       # filled later
        high_price=int(raw.get("high", 0)),
        low_price=int(raw.get("low", 0)),
        volume=float(raw.get("daily_volume", "0")),
        open_interest=float(raw.get("open_interest", "0")),
        status=raw.get("status", ""),
        data_date=data_date,
    )


def download_day(
    report_date: date,
    target_prefixes: list[str] | None = None,
) -> list[dict]:
    """Download one day's S3 report, filter to weather markets.

    Returns list of raw market dicts for target weather prefixes.
    """
    if target_prefixes is None:
        target_prefixes = list(KALSHI_TO_ICAO.keys())

    url = f"{S3_BASE}/market_data_{report_date.isoformat()}.json"
    logger.info(f"Downloading {url}")

    resp = httpx.get(url, timeout=120)
    if resp.status_code == 404:
        logger.warning(f"No data for {report_date}")
        return []
    resp.raise_for_status()

    data = resp.json()
    weather = [
        m for m in data
        if m.get("report_ticker", "") in target_prefixes
    ]
    logger.info(f"  {report_date}: {len(data)} total, {len(weather)} weather markets")
    return weather


def build_weather_df(raw_markets: list[dict], report_date: date) -> pd.DataFrame:
    """Convert raw weather market dicts to a clean DataFrame.

    Groups by (station, market_date) and assigns bracket types.
    """
    if not raw_markets:
        return pd.DataFrame()

    rows = []
    for m in raw_markets:
        ticker = m.get("ticker_name", "")
        report_ticker = m.get("report_ticker", "")
        parts = ticker.split("-")
        if len(parts) < 3 or report_ticker not in KALSHI_TO_ICAO:
            continue

        try:
            market_date = parse_ticker_date(parts[1])
        except (ValueError, IndexError):
            continue

        bracket_str = parts[2]

        rows.append({
            "ticker": ticker,
            "report_ticker": report_ticker,
            "station": KALSHI_TO_ICAO[report_ticker],
            "market_date": market_date,
            "bracket_str": bracket_str,
            "high_price": int(m.get("high", 0)),
            "low_price": int(m.get("low", 0)),
            "volume": float(m.get("daily_volume", "0")),
            "open_interest": float(m.get("open_interest", "0")),
            "status": m.get("status", ""),
            "data_date": report_date,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse bracket type and strike
    def classify_bracket(group):
        bracket_strs = group["bracket_str"].tolist()
        types = []
        strikes = []
        for bs in bracket_strs:
            btype, strike = parse_bracket(bs, bracket_strs)
            types.append(btype)
            strikes.append(strike)
        group["bracket_type"] = types
        group["strike"] = strikes
        return group

    df = df.groupby(["station", "market_date"], group_keys=False).apply(classify_bracket)
    return df


def download_date_range(
    start: date,
    end: date,
    target_prefixes: list[str] | None = None,
    skip_existing: bool = True,
) -> pd.DataFrame:
    """Download weather market data for a date range.

    Downloads S3 report files day by day, extracts weather markets,
    returns combined DataFrame.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_dfs = []
    current = start

    while current <= end:
        try:
            raw = download_day(current, target_prefixes)
            if raw:
                df = build_weather_df(raw, current)
                if not df.empty:
                    all_dfs.append(df)
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error for {current}: {e}")
        except Exception as e:
            logger.error(f"Error for {current}: {e}")

        current += timedelta(days=1)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def save_weather_data(df: pd.DataFrame, filename: str = "weather_markets.parquet") -> Path:
    """Save weather market DataFrame to parquet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    df.to_parquet(path, index=False)
    logger.info(f"Saved {len(df)} rows to {path}")
    return path


def load_weather_data(filename: str = "weather_markets.parquet") -> pd.DataFrame:
    """Load saved weather market data."""
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"No data at {path}. Run download_kalshi_data.py first.")
    return pd.read_parquet(path)
