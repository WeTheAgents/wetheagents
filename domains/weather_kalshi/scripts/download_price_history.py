"""Download Polymarket CLOB price history for all cached weather brackets.

Fetches 10-minute price candles (interval=max) for each bracket's YES token.
Appends to data/raw/polymarket/price_history.parquet.

Requires VPN (clob.polymarket.com is DNS-blocked otherwise).

Usage:
    python -m scripts.download_price_history
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket_client import fetch_price_history

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "polymarket"
MARKET_PATH = CACHE_DIR / "polymarket_weather.parquet"
HISTORY_PATH = CACHE_DIR / "price_history.parquet"


def main() -> None:
    if not MARKET_PATH.exists():
        logger.error(f"No market data. Run: python -m scripts.download_polymarket_data --all --last 14")
        return

    pm = pd.read_parquet(MARKET_PATH)
    logger.info(f"Loaded {len(pm)} brackets from {MARKET_PATH}")

    # Load existing history to avoid re-fetching
    existing_tokens = set()
    if HISTORY_PATH.exists():
        existing = pd.read_parquet(HISTORY_PATH)
        # Track latest timestamp per token to do incremental fetch
        logger.info(f"Existing history: {len(existing)} rows")
    else:
        existing = pd.DataFrame()

    all_new = []
    for idx, (_, row) in enumerate(pm.iterrows()):
        token = str(row.get("clob_token_id_yes", ""))
        if not token:
            continue

        history = fetch_price_history(token, interval="max")
        time.sleep(0.3)

        for h in history:
            all_new.append({
                "station": row["station"],
                "market_date": row["market_date"],
                "bracket_index": row["bracket_index"],
                "lower": row.get("lower"),
                "upper": row.get("upper"),
                "label": row["label"],
                "timestamp": h["t"],
                "price": h["p"],
            })

        if (idx + 1) % 20 == 0:
            logger.info(f"  {idx+1}/{len(pm)} brackets done, {len(all_new)} new candles")

    if all_new:
        new_df = pd.DataFrame(all_new)
        new_df["datetime"] = pd.to_datetime(new_df["timestamp"], unit="s")

        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["station", "market_date", "bracket_index", "timestamp"],
                keep="last",
            )
        else:
            combined = new_df

        combined.to_parquet(HISTORY_PATH, index=False)
        logger.info(f"Saved {len(combined)} total price points to {HISTORY_PATH}")
    else:
        logger.info("No new price data fetched")

    print("Done.")


if __name__ == "__main__":
    main()
