"""Polymarket CLOB order-book client and fill simulation.

Used by the day-of paper-trading pipeline (scripts/paper_dayof.py) to record
real order books and simulate pessimistic-realistic fills against them.

The /book endpoint returns bid/ask levels sorted worst-to-best; we normalize
to best-first and never trust the API ordering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"


@dataclass
class OrderBook:
    """Normalized order book: levels as (price, size_shares), best-first."""

    token_id: str
    bids: list[tuple[float, float]] = field(default_factory=list)  # highest price first
    asks: list[tuple[float, float]] = field(default_factory=list)  # lowest price first

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    def to_dict(self) -> dict:
        return {"token_id": self.token_id, "bids": self.bids, "asks": self.asks}


@dataclass
class Fill:
    """Result of walking one book side for a target dollar stake."""

    avg_price: float | None  # VWAP of filled shares, None if nothing filled
    shares: float            # shares filled
    stake_filled: float      # dollars actually spent
    stake_target: float      # dollars requested
    levels_used: int

    @property
    def complete(self) -> bool:
        return self.stake_filled >= self.stake_target * 0.999


def fetch_order_book(token_id: str, timeout: float = 15.0) -> OrderBook:
    """Fetch and normalize the order book for a CLOB token."""
    r = httpx.get(f"{CLOB_BASE}/book", params={"token_id": token_id}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    bids = sorted(
        ((float(l["price"]), float(l["size"])) for l in data.get("bids", [])),
        key=lambda x: -x[0],
    )
    asks = sorted(
        ((float(l["price"]), float(l["size"])) for l in data.get("asks", [])),
        key=lambda x: x[0],
    )
    return OrderBook(token_id=token_id, bids=bids, asks=asks)


def walk_fill(levels: list[tuple[float, float]], stake: float) -> Fill:
    """Simulate a market buy of `stake` dollars against best-first levels.

    Levels are (price, size_shares). Fills partially when depth runs out.
    """
    remaining = stake
    shares = 0.0
    cost = 0.0
    used = 0
    for price, size in levels:
        if remaining <= 1e-9:
            break
        if price <= 0:
            continue
        take = min(size, remaining / price)
        shares += take
        cost += take * price
        remaining -= take * price
        used += 1
    avg = cost / shares if shares > 0 else None
    return Fill(avg_price=avg, shares=shares, stake_filled=cost,
                stake_target=stake, levels_used=used)


def no_levels_from_yes_bids(bids: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Buying NO takes liquidity from the YES bid side: NO ask price = 1 - YES bid.

    Input bids are best-first (highest YES price), which maps to the cheapest
    NO price first — already best-first for a NO buy.
    """
    return [(1.0 - p, size) for p, size in bids if 0.0 < p < 1.0]
