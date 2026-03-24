"""Polymarket MLB game market client.

Fetches MLB game events and market prices from Polymarket's
Gamma API (event/market discovery) and CLOB API (prices/orderbook/history).

Polymarket MLB markets (per game):
  - Moneyline: which team wins
  - Spread: margin of victory (e.g., -1.5)
  - Totals: combined score over/under (e.g., O/U 8.5)

API docs: https://docs.polymarket.com/
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "polymarket"
MLB_SERIES_ID = "3"

# Rate limit: 200ms between requests (Gamma allows 300 req/10s)
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
class MLBMarket:
    """A single sub-market within an MLB game event."""

    market_id: str
    market_type: str  # "moneyline" | "spread" | "total"
    question: str
    outcomes: list[str]
    outcome_prices: list[float]
    condition_id: str
    clob_token_ids: list[str]
    line: float | None  # -1.5 for spread, 8.5 for total, None for ML
    group_item_title: str
    best_bid: float | None
    best_ask: float | None
    last_trade_price: float | None
    spread: float | None
    liquidity: float
    accepting_orders: bool
    closed: bool


@dataclass
class MLBGameEvent:
    """A complete MLB game event with all sub-markets."""

    event_id: str
    game_id: int | None
    slug: str
    title: str
    away_team: str
    home_team: str
    game_time: datetime | None
    event_date: date | None
    markets: list[MLBMarket] = field(default_factory=list)
    volume: float = 0.0
    liquidity: float = 0.0


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""

    price: float
    size: float


@dataclass
class OrderBook:
    """Full order book for a single token."""

    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)


# --- Parsing Helpers ---


def _parse_json_field(raw: str | list) -> list[str]:
    """Parse JSON-encoded string array or pass-through list."""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            return [str(x) for x in json.loads(raw)]
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _parse_float_list(raw: str | list) -> list[float]:
    """Parse JSON-encoded float array."""
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, str):
        try:
            return [float(x) for x in json.loads(raw)]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
    return []


def _parse_market_type(sports_market_type: str | None) -> str:
    """Normalize sportsMarketType to internal naming."""
    mapping = {
        "moneyline": "moneyline",
        "spreads": "spread",
        "totals": "total",
    }
    return mapping.get((sports_market_type or "").lower(), "unknown")


def _parse_teams_from_title(title: str) -> tuple[str, str]:
    """Parse 'Away Team vs. Home Team' -> (away, home)."""
    for sep in [" vs. ", " vs ", " v. ", " v "]:
        if sep in title:
            parts = title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return title, ""


def _parse_game_time(raw: str | None) -> datetime | None:
    """Parse game start time string to datetime."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace(" ", "T").rstrip("Z"))
    except (ValueError, TypeError):
        return None


def _parse_date(raw: str | None) -> date | None:
    """Parse date string (YYYY-MM-DD or ISO) to date."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return None


def _safe_float(val, default=None) -> float | None:
    """Safely convert to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# --- API Fetching ---


def fetch_mlb_events(active_only: bool = True, limit: int = 100) -> list[MLBGameEvent]:
    """Fetch all MLB game events from Gamma API.

    Uses series_id=3 for MLB. Handles pagination.
    """
    events = []
    offset = 0

    while True:
        _rate_limit()
        params: dict = {
            "series_id": MLB_SERIES_ID,
            "limit": limit,
            "offset": offset,
        }
        if active_only:
            params["closed"] = "false"

        try:
            r = httpx.get(f"{GAMMA_BASE}/events", params=params, timeout=15)
            r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch MLB events (offset=%d): %s", offset, e)
            break

        data = r.json()
        if not data:
            break

        for event_data in data:
            event = _parse_event(event_data)
            if event is not None:
                events.append(event)

        if len(data) < limit:
            break
        offset += limit

    logger.info("Fetched %d MLB events", len(events))
    return events


def _parse_event(event_data: dict) -> MLBGameEvent | None:
    """Parse a single event from Gamma API response."""
    title = event_data.get("title", "")
    away, home = _parse_teams_from_title(title)

    markets = []
    for m in event_data.get("markets", []):
        market_type = _parse_market_type(m.get("sportsMarketType"))
        if market_type == "unknown":
            logger.debug("Skipping unknown market type: %s", m.get("sportsMarketType"))
            continue

        outcomes = _parse_json_field(m.get("outcomes", []))
        outcome_prices = _parse_float_list(m.get("outcomePrices", []))
        clob_token_ids = _parse_json_field(m.get("clobTokenIds", []))

        markets.append(MLBMarket(
            market_id=str(m.get("id", "")),
            market_type=market_type,
            question=m.get("question", ""),
            outcomes=outcomes,
            outcome_prices=outcome_prices,
            condition_id=m.get("conditionId", ""),
            clob_token_ids=clob_token_ids,
            line=_safe_float(m.get("line")),
            group_item_title=m.get("groupItemTitle", ""),
            best_bid=_safe_float(m.get("bestBid")),
            best_ask=_safe_float(m.get("bestAsk")),
            last_trade_price=_safe_float(m.get("lastTradePrice")),
            spread=_safe_float(m.get("spread")),
            liquidity=float(m.get("liquidity", 0)),
            accepting_orders=bool(m.get("acceptingOrders", True)),
            closed=bool(m.get("closed", False)),
        ))

    game_id_raw = event_data.get("gameId")
    game_id = int(game_id_raw) if game_id_raw is not None else None

    return MLBGameEvent(
        event_id=str(event_data.get("id", "")),
        game_id=game_id,
        slug=event_data.get("slug", ""),
        title=title,
        away_team=away,
        home_team=home,
        game_time=_parse_game_time(
            event_data.get("gameStartTime") or event_data.get("startTime")
        ),
        event_date=_parse_date(event_data.get("eventDate")),
        markets=markets,
        volume=float(event_data.get("volume", 0)),
        liquidity=float(event_data.get("liquidity", 0)),
    )


def fetch_todays_games() -> list[MLBGameEvent]:
    """Fetch only today's MLB games."""
    today = date.today()
    events = fetch_mlb_events(active_only=True)
    return [e for e in events if e.event_date == today]


def fetch_upcoming_games(days: int = 3) -> list[MLBGameEvent]:
    """Fetch MLB games within the next N days."""
    today = date.today()
    cutoff = today + timedelta(days=days)
    events = fetch_mlb_events(active_only=True)
    return [e for e in events if e.event_date and today <= e.event_date <= cutoff]


# --- Order Book ---


def fetch_order_book(token_id: str) -> OrderBook:
    """Fetch the full order book for a CLOB token."""
    _rate_limit()
    try:
        r = httpx.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch order book for %s: %s", token_id[:20], e)
        return OrderBook(token_id=token_id)

    bids = [
        OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
        for b in data.get("bids", [])
    ]
    asks = [
        OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
        for a in data.get("asks", [])
    ]

    return OrderBook(token_id=token_id, bids=bids, asks=asks)


def fetch_order_books_for_game(event: MLBGameEvent) -> dict[str, OrderBook]:
    """Fetch order books for all markets in a game event.

    Returns dict mapping market_id -> OrderBook (for the first token).
    """
    result = {}
    for market in event.markets:
        if market.clob_token_ids:
            token_id = market.clob_token_ids[0]
            result[market.market_id] = fetch_order_book(token_id)
    return result


# --- Price Data ---


def fetch_midpoint(token_id: str) -> float | None:
    """Fetch midpoint price for a single token."""
    _rate_limit()
    try:
        r = httpx.get(
            f"{CLOB_BASE}/midpoint",
            params={"token_id": token_id},
            timeout=15,
        )
        r.raise_for_status()
        return _safe_float(r.json().get("mid"))
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch midpoint for %s: %s", token_id[:20], e)
        return None


def fetch_price_history(
    token_id: str,
    interval: str = "1h",
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:
    """Fetch price history for a token from CLOB API.

    Args:
        token_id: The CLOB token ID.
        interval: "1h", "6h", "1d", "1w", "max".
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


# --- DataFrame Builders ---


def build_games_df(events: list[MLBGameEvent]) -> pd.DataFrame:
    """Convert events to a flat DataFrame with one row per market."""
    rows = []
    for e in events:
        for m in e.markets:
            rows.append({
                "event_id": e.event_id,
                "game_id": e.game_id,
                "slug": e.slug,
                "title": e.title,
                "away_team": e.away_team,
                "home_team": e.home_team,
                "game_time": e.game_time,
                "event_date": e.event_date,
                "market_type": m.market_type,
                "question": m.question,
                "outcome_1": m.outcomes[0] if m.outcomes else "",
                "outcome_2": m.outcomes[1] if len(m.outcomes) > 1 else "",
                "price_1": m.outcome_prices[0] if m.outcome_prices else None,
                "price_2": m.outcome_prices[1] if len(m.outcome_prices) > 1 else None,
                "line": m.line,
                "condition_id": m.condition_id,
                "clob_token_id_1": m.clob_token_ids[0] if m.clob_token_ids else "",
                "clob_token_id_2": m.clob_token_ids[1] if len(m.clob_token_ids) > 1 else "",
                "best_bid": m.best_bid,
                "best_ask": m.best_ask,
                "last_trade_price": m.last_trade_price,
                "spread": m.spread,
                "liquidity": m.liquidity,
                "volume": e.volume,
                "accepting_orders": m.accepting_orders,
                "closed": m.closed,
            })
    return pd.DataFrame(rows)


def build_moneyline_df(events: list[MLBGameEvent]) -> pd.DataFrame:
    """Extract only moneyline markets into a focused DataFrame."""
    rows = []
    for e in events:
        for m in e.markets:
            if m.market_type != "moneyline":
                continue
            prices = m.outcome_prices
            outcomes = m.outcomes
            rows.append({
                "event_date": e.event_date,
                "away_team": outcomes[0] if outcomes else e.away_team,
                "home_team": outcomes[1] if len(outcomes) > 1 else e.home_team,
                "game_time": e.game_time,
                "away_price": prices[0] if prices else None,
                "home_price": prices[1] if len(prices) > 1 else None,
                "away_implied_prob": prices[0] if prices else None,
                "home_implied_prob": prices[1] if len(prices) > 1 else None,
                "volume": e.volume,
                "liquidity": m.liquidity,
                "slug": e.slug,
            })
    return pd.DataFrame(rows)


def build_totals_df(events: list[MLBGameEvent]) -> pd.DataFrame:
    """Extract only totals (O/U) markets."""
    rows = []
    for e in events:
        for m in e.markets:
            if m.market_type != "total":
                continue
            prices = m.outcome_prices
            rows.append({
                "event_date": e.event_date,
                "away_team": e.away_team,
                "home_team": e.home_team,
                "line": m.line,
                "over_price": prices[0] if prices else None,
                "under_price": prices[1] if len(prices) > 1 else None,
                "volume": e.volume,
                "liquidity": m.liquidity,
                "slug": e.slug,
            })
    return pd.DataFrame(rows)


def build_spreads_df(events: list[MLBGameEvent]) -> pd.DataFrame:
    """Extract only spread markets."""
    rows = []
    for e in events:
        for m in e.markets:
            if m.market_type != "spread":
                continue
            prices = m.outcome_prices
            outcomes = m.outcomes
            rows.append({
                "event_date": e.event_date,
                "away_team": e.away_team,
                "home_team": e.home_team,
                "line": m.line,
                "outcome_1": outcomes[0] if outcomes else "",
                "outcome_2": outcomes[1] if len(outcomes) > 1 else "",
                "price_1": prices[0] if prices else None,
                "price_2": prices[1] if len(prices) > 1 else None,
                "volume": e.volume,
                "liquidity": m.liquidity,
                "slug": e.slug,
            })
    return pd.DataFrame(rows)


# --- Persistence ---


def save_market_data(
    df: pd.DataFrame, filename: str = "polymarket_mlb.parquet"
) -> Path:
    """Save MLB market data to parquet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    df.to_parquet(path, index=False)
    logger.info("Saved %d rows to %s", len(df), path)
    return path


def load_market_data(
    filename: str = "polymarket_mlb.parquet",
) -> pd.DataFrame:
    """Load saved MLB market data."""
    path = DATA_DIR / filename
    return pd.read_parquet(path)
