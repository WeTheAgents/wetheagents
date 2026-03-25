"""Polymarket weather temperature market client.

Fetches weather temperature events and bracket prices from Polymarket's
Gamma API (market discovery) and CLOB API (prices/history).

Polymarket weather markets:
  - 11 brackets per city: 9 inner (2F wide) + 2 tails
  - Resolution via Weather Underground (wunderground.com)
  - Stations: KLGA (NYC), KORD (Chicago), KMIA (Miami)

API docs: https://docs.polymarket.com/
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from src.stations import POLYMARKET_SLUG_TO_ICAO

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "polymarket"

# Rate limit: be polite (Gamma allows 300 req/10s but no reason to hammer)
RATE_LIMIT_SECONDS = 0.2

_last_request_time = 0.0


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


# --- Dataclasses ---


@dataclass
class PolymarketBracket:
    """A single bracket from a Polymarket weather temperature event."""

    market_id: str
    condition_id: str
    clob_token_id_yes: str
    clob_token_id_no: str
    lower: float | None  # None for tail_low (e.g., "49F or below")
    upper: float | None  # None for tail_high (e.g., "68F or higher")
    label: str
    yes_price: float  # 0.0-1.0
    no_price: float


@dataclass
class PolymarketWeatherEvent:
    """A complete weather temperature event with all bracket markets."""

    event_id: str
    slug: str
    title: str
    city_slug: str
    station_icao: str
    market_date: date
    brackets: list[PolymarketBracket] = field(default_factory=list)
    volume: float = 0.0
    liquidity: float = 0.0
    resolution_source: str = ""


# --- Bracket Parsing ---

# Question patterns (degree sign may be ° or \u00b0):
# Tail low:  "Will the highest temperature in X be 37°F or below on March 24?"
# Inner:     "Will the highest temperature in X be between 38-39°F on March 24?"
# Tail high: "Will the highest temperature in X be 56°F or higher on March 24?"

_RE_TAIL_LOW = re.compile(r"be (\d+).?F or below", re.IGNORECASE)
_RE_INNER = re.compile(r"be between (\d+)-(\d+).?F", re.IGNORECASE)
_RE_TAIL_HIGH = re.compile(r"be (\d+).?F or higher", re.IGNORECASE)


def parse_bracket_question(question: str) -> tuple[float | None, float | None]:
    """Parse bracket boundaries from Polymarket market question.

    Returns:
        (lower, upper) where None indicates open-ended tail.
        - Tail low: (None, 37.0) meaning "37F or below"
        - Inner: (38.0, 39.0) meaning "between 38-39F"
        - Tail high: (56.0, None) meaning "56F or higher"
    """
    m = _RE_INNER.search(question)
    if m:
        return float(m.group(1)), float(m.group(2))

    m = _RE_TAIL_LOW.search(question)
    if m:
        return None, float(m.group(1))

    m = _RE_TAIL_HIGH.search(question)
    if m:
        return float(m.group(1)), None

    logger.warning("Could not parse bracket from question: %s", question)
    return None, None


# --- Slug Generation ---

_MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}


def build_event_slug(city_slug: str, d: date) -> str:
    """Build Polymarket event slug for a given city and date.

    Example: build_event_slug("chicago", date(2026, 3, 24))
    → "highest-temperature-in-chicago-on-march-24-2026"
    """
    month = _MONTH_NAMES[d.month]
    return f"highest-temperature-in-{city_slug}-on-{month}-{d.day}-{d.year}"


def discover_weather_slugs(
    city_slug: str, start: date, end: date
) -> list[str]:
    """Generate event slugs for a date range."""
    slugs = []
    d = start
    while d <= end:
        slugs.append(build_event_slug(city_slug, d))
        d += timedelta(days=1)
    return slugs


# --- API Fetching ---


def fetch_weather_event(slug: str) -> PolymarketWeatherEvent | None:
    """Fetch a single weather temperature event from Gamma API.

    Returns None if the event doesn't exist (404 or empty response).
    """
    _rate_limit()
    try:
        r = httpx.get(
            f"{GAMMA_BASE}/events",
            params={"slug": slug},
            timeout=15,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch event %s: %s", slug, e)
        return None

    data = r.json()
    if not data:
        return None

    event = data[0] if isinstance(data, list) else data

    # Parse city slug from the event slug
    city_slug = _parse_city_from_slug(slug)
    station_icao = POLYMARKET_SLUG_TO_ICAO.get(city_slug, "")
    market_date = _parse_date_from_slug(slug)

    brackets = []
    for m in event.get("markets", []):
        question = m.get("question", "")
        lower, upper = parse_bracket_question(question)
        if lower is None and upper is None:
            continue

        # Parse outcome prices
        prices_raw = m.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            prices = [float(p) for p in re.findall(r"[\d.]+", prices_raw)]
        else:
            prices = [float(p) for p in prices_raw]

        yes_price = prices[0] if len(prices) > 0 else 0.0
        no_price = prices[1] if len(prices) > 1 else 0.0

        clob_ids_raw = m.get("clobTokenIds", [])
        if isinstance(clob_ids_raw, str):
            import json as _json
            clob_ids = _json.loads(clob_ids_raw)
        else:
            clob_ids = clob_ids_raw

        brackets.append(PolymarketBracket(
            market_id=str(m.get("id", "")),
            condition_id=m.get("conditionId", ""),
            clob_token_id_yes=clob_ids[0] if len(clob_ids) > 0 else "",
            clob_token_id_no=clob_ids[1] if len(clob_ids) > 1 else "",
            lower=lower,
            upper=upper,
            label=question,
            yes_price=yes_price,
            no_price=no_price,
        ))

    # Sort brackets by lower bound (tails at edges)
    brackets.sort(key=lambda b: (b.lower if b.lower is not None else -999))

    return PolymarketWeatherEvent(
        event_id=str(event.get("id", "")),
        slug=slug,
        title=event.get("title", ""),
        city_slug=city_slug,
        station_icao=station_icao,
        market_date=market_date,
        brackets=brackets,
        volume=float(event.get("volume", 0)),
        liquidity=float(event.get("liquidity", 0)),
        resolution_source=event.get("resolutionSource", ""),
    )


def fetch_weather_events(
    city_slug: str, start: date, end: date
) -> list[PolymarketWeatherEvent]:
    """Fetch all weather events for a city over a date range."""
    slugs = discover_weather_slugs(city_slug, start, end)
    events = []
    for slug in slugs:
        event = fetch_weather_event(slug)
        if event is not None:
            events.append(event)
            logger.info("Fetched %s: %d brackets, $%.0f vol", slug, len(event.brackets), event.volume)
        else:
            logger.debug("No event found: %s", slug)
    return events


# --- Price History ---


def fetch_price_history(
    token_id: str,
    interval: str = "1d",
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:
    """Fetch price history for a bracket token from CLOB API.

    Args:
        token_id: The CLOB token ID (YES token).
        interval: Aggregation period: "1h", "6h", "1d", "1w", "max".
        start_ts: Unix timestamp start filter.
        end_ts: Unix timestamp end filter.

    Returns:
        List of {t: unix_timestamp, p: price_float} dicts.
    """
    _rate_limit()
    params: dict = {"market": token_id, "interval": interval}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts

    try:
        r = httpx.get(f"{CLOB_BASE}/prices-history", params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("history", [])
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch price history for %s: %s", token_id[:20], e)
        return []


# --- DataFrame Building ---


def build_weather_df(events: list[PolymarketWeatherEvent]) -> pd.DataFrame:
    """Convert events to a flat DataFrame for analysis.

    Columns: station, market_date, bracket_index, lower, upper, label,
             yes_price, no_price, volume, market_id, clob_token_id_yes,
             event_slug, city_slug
    """
    rows = []
    for event in events:
        for i, b in enumerate(event.brackets):
            rows.append({
                "station": event.station_icao,
                "market_date": event.market_date,
                "bracket_index": i,
                "lower": b.lower,
                "upper": b.upper,
                "label": b.label,
                "yes_price": b.yes_price,
                "no_price": b.no_price,
                "volume": event.volume,
                "market_id": b.market_id,
                "clob_token_id_yes": b.clob_token_id_yes,
                "event_slug": event.slug,
                "city_slug": event.city_slug,
            })

    return pd.DataFrame(rows)


# --- Persistence ---


def save_weather_data(
    df: pd.DataFrame, filename: str = "polymarket_weather.parquet"
) -> Path:
    """Save weather market data to parquet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    df.to_parquet(path, index=False)
    logger.info("Saved %d rows to %s", len(df), path)
    return path


def load_weather_data(
    filename: str = "polymarket_weather.parquet",
) -> pd.DataFrame:
    """Load saved weather market data."""
    path = DATA_DIR / filename
    return pd.read_parquet(path)


# --- Internal Helpers ---


def _parse_city_from_slug(slug: str) -> str:
    """Extract city slug from event slug.

    'highest-temperature-in-chicago-on-march-24-2026' → 'chicago'
    'highest-temperature-in-nyc-on-march-24-2026' → 'nyc'
    """
    m = re.search(r"highest-temperature-in-(.+?)-on-", slug)
    return m.group(1) if m else ""


def _parse_date_from_slug(slug: str) -> date:
    """Extract date from event slug.

    'highest-temperature-in-chicago-on-march-24-2026' → date(2026, 3, 24)
    """
    m = re.search(r"-on-(\w+)-(\d+)-(\d+)$", slug)
    if not m:
        return date.today()

    month_name = m.group(1).lower()
    day = int(m.group(2))
    year = int(m.group(3))

    month_map = {v: k for k, v in _MONTH_NAMES.items()}
    month = month_map.get(month_name, 1)
    return date(year, month, day)
