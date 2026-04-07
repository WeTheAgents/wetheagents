"""Daily collection of Polymarket weather data for all 26 cities with gap-filling.

Collects market brackets and CLOB price history. Detects missing (city, date)
pairs and backfills them automatically — so a failed run yesterday is covered today.

Data files:
  - data/raw/polymarket/all_cities_markets.parquet       (bracket snapshots)
  - data/raw/polymarket/all_cities_price_history.parquet  (CLOB candles)

Usage:
    python scripts/collect_all_cities.py                 # default: 14 days back, 5 ahead
    python scripts/collect_all_cities.py --days-back 7   # scan fewer days
    python scripts/collect_all_cities.py --dry-run        # show gaps only
    python scripts/collect_all_cities.py --skip-history   # markets only (fast)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.polymarket_client import build_event_slug, fetch_price_history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = ROOT / "data" / "raw" / "polymarket"
CITIES_PATH = ROOT / "data" / "static" / "polymarket_cities.json"
MARKETS_PATH = DATA_DIR / "all_cities_markets.parquet"
HISTORY_PATH = DATA_DIR / "all_cities_price_history.parquet"

DAYS_AHEAD_DEFAULT = 5
DAYS_BACK_DEFAULT = 14
RATE_LIMIT_GAMMA = 0.15   # seconds between Gamma API calls
RATE_LIMIT_CLOB = 0.25    # seconds between CLOB API calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_cities() -> dict:
    with open(CITIES_PATH) as f:
        return json.load(f)


def load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def normalize_date(val) -> date:
    """Coerce various date-like objects to datetime.date."""
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        return val
    if hasattr(val, "date"):
        return val.date()
    return date.fromisoformat(str(val))


def find_market_gaps(
    existing: pd.DataFrame,
    cities: dict,
    start: date,
    end: date,
) -> list[tuple[str, date]]:
    """Return (city_slug, target_date) pairs absent from existing markets."""
    if existing.empty:
        covered: set[tuple[str, date]] = set()
    else:
        covered = set()
        for _, row in existing.iterrows():
            covered.add((row["city_slug"], normalize_date(row["market_date"])))

    gaps: list[tuple[str, date]] = []
    d = start
    while d <= end:
        for slug in cities:
            if (slug, d) not in covered:
                gaps.append((slug, d))
        d += timedelta(days=1)
    return gaps


def find_history_gaps(
    markets: pd.DataFrame,
    history: pd.DataFrame,
) -> pd.DataFrame:
    """Return market rows whose price history hasn't been fetched yet."""
    if markets.empty:
        return pd.DataFrame()

    if history.empty:
        return markets

    hist_keys = set()
    for _, row in history.iterrows():
        hist_keys.add((
            row["city_slug"],
            str(normalize_date(row["market_date"])),
            int(row["bracket_index"]),
        ))

    mask = []
    for _, row in markets.iterrows():
        key = (
            row["city_slug"],
            str(normalize_date(row["market_date"])),
            int(row["bracket_index"]),
        )
        mask.append(key not in hist_keys)

    return markets[mask]


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_event_brackets(city_slug: str, target: date) -> list[dict]:
    """Fetch bracket data for one (city, date) via Gamma API."""
    slug = build_event_slug(city_slug, target)
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/events",
            params={"slug": slug},
            timeout=15,
        )
        r.raise_for_status()
        events = r.json()
        if not events:
            return []

        e = events[0]
        rows = []
        for i, m in enumerate(e.get("markets", [])):
            prices_raw = m.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            clob_raw = m.get("clobTokenIds", "[]")
            if isinstance(clob_raw, str):
                clob_ids = json.loads(clob_raw)
            else:
                clob_ids = clob_raw

            rows.append({
                "city_slug": city_slug,
                "city_name": "",
                "market_date": target,
                "bracket_index": i,
                "question": m.get("question", ""),
                "yes_price": float(prices[0]) if prices else 0,
                "clob_token_id_yes": clob_ids[0] if clob_ids else "",
                "market_id": m.get("id", ""),
                "volume": e.get("volume", 0),
            })
        return rows
    except Exception as ex:
        logger.warning("Gamma fetch failed %s %s: %s", city_slug, target, ex)
        return []


def fetch_history_batch(
    brackets: pd.DataFrame,
) -> pd.DataFrame:
    """Fetch CLOB price history for a batch of brackets."""
    new_rows = []
    n_ok = 0
    n_err = 0

    total = len(brackets)
    for idx, (_, row) in enumerate(brackets.iterrows()):
        token = str(row.get("clob_token_id_yes", ""))
        if not token or len(token) < 10:
            continue

        candles = fetch_price_history(token, interval="max")
        time.sleep(RATE_LIMIT_CLOB)

        if candles:
            n_ok += 1
            for c in candles:
                new_rows.append({
                    "city_slug": row["city_slug"],
                    "city_name": row.get("city_name", ""),
                    "market_date": row["market_date"],
                    "bracket_index": row["bracket_index"],
                    "question": row["question"],
                    "timestamp": c["t"],
                    "price": c["p"],
                })
        else:
            n_err += 1

        if (idx + 1) % 100 == 0:
            logger.info(
                "  CLOB progress: %d/%d (%d ok, %d err, %d candles)",
                idx + 1, total, n_ok, n_err, len(new_rows),
            )

    logger.info("CLOB done: %d ok, %d errors, %d candles", n_ok, n_err, len(new_rows))

    if new_rows:
        df = pd.DataFrame(new_rows)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        return df
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect all-cities Polymarket weather data")
    parser.add_argument("--days-back", type=int, default=DAYS_BACK_DEFAULT)
    parser.add_argument("--days-ahead", type=int, default=DAYS_AHEAD_DEFAULT)
    parser.add_argument("--dry-run", action="store_true", help="Show gaps only")
    parser.add_argument("--skip-history", action="store_true", help="Markets only")
    args = parser.parse_args()

    cities = load_cities()
    today = date.today()
    start = today - timedelta(days=args.days_back)
    end = today + timedelta(days=args.days_ahead)

    n_slots = (end - start).days * len(cities) + len(cities)
    logger.info("%d cities, %s to %s (%d date-city slots)", len(cities), start, end, n_slots)

    # ---- Phase 1: Markets ----
    existing_markets = load_existing(MARKETS_PATH)
    gaps = find_market_gaps(existing_markets, cities, start, end)
    logger.info("Existing markets: %d rows. Gaps: %d", len(existing_markets), len(gaps))

    if args.dry_run:
        print(f"\n{len(gaps)} gaps:")
        for city, d in sorted(gaps)[:50]:
            print(f"  {city:20s} {d}")
        if len(gaps) > 50:
            print(f"  ... and {len(gaps) - 50} more")
        return

    if gaps:
        new_rows = []
        for i, (city, d) in enumerate(gaps):
            rows = fetch_event_brackets(city, d)
            if rows:
                # Fill city_name
                name = cities.get(city, {}).get("name", "")
                for r in rows:
                    r["city_name"] = name
                new_rows.extend(rows)
            time.sleep(RATE_LIMIT_GAMMA)

            if (i + 1) % 100 == 0:
                logger.info("  Gamma progress: %d/%d gaps, %d rows", i + 1, len(gaps), len(new_rows))

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            if not existing_markets.empty:
                combined = pd.concat([existing_markets, new_df], ignore_index=True)
                combined = combined.drop_duplicates(
                    subset=["city_slug", "market_date", "bracket_index"],
                    keep="last",
                )
            else:
                combined = new_df

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            combined.to_parquet(MARKETS_PATH, index=False)
            logger.info("Markets saved: %d rows → %s", len(combined), MARKETS_PATH)
        else:
            logger.info("No new market data (events may not exist yet)")
            combined = existing_markets
    else:
        logger.info("Markets: no gaps to fill")
        combined = existing_markets

    # ---- Phase 2: Price History ----
    if args.skip_history or combined.empty:
        logger.info("Skipping price history")
        _print_summary()
        return

    existing_history = load_existing(HISTORY_PATH)
    to_fetch = find_history_gaps(combined, existing_history)
    logger.info("History: %d existing rows. To fetch: %d brackets", len(existing_history), len(to_fetch))

    if to_fetch.empty:
        logger.info("Price history: no gaps")
        _print_summary()
        return

    new_history = fetch_history_batch(to_fetch)

    if not new_history.empty:
        if not existing_history.empty:
            all_hist = pd.concat([existing_history, new_history], ignore_index=True)
            all_hist = all_hist.drop_duplicates(
                subset=["city_slug", "market_date", "bracket_index", "timestamp"],
                keep="last",
            )
        else:
            all_hist = new_history

        all_hist.to_parquet(HISTORY_PATH, index=False)
        logger.info("History saved: %d rows -> %s", len(all_hist), HISTORY_PATH)

    _print_summary()


def _print_summary() -> None:
    print(f"\n{'='*60}")
    print("Collection complete")
    if MARKETS_PATH.exists():
        m = pd.read_parquet(MARKETS_PATH)
        print(f"  Markets: {len(m)} rows, {m['city_slug'].nunique()} cities")
        print(f"  Dates: {m['market_date'].min()} to {m['market_date'].max()}")
    if HISTORY_PATH.exists():
        h = pd.read_parquet(HISTORY_PATH)
        print(f"  Price history: {len(h)} candles")
        print(f"  Range: {h['datetime'].min()} to {h['datetime'].max()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
