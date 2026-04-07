"""Extract settlement data from Polymarket price history.

Finds resolved markets (where a winning bracket's final price ≈ 1.0),
extracts the settled temperature range from the bracket question text,
and saves to data/processed/settlements.parquet.

Usage:
    python -m scripts.extract_settlements
    python -m scripts.extract_settlements --threshold 0.90
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRICE_HISTORY_PATH = DATA_DIR / "raw" / "polymarket" / "all_cities_price_history.parquet"
OUTPUT_PATH = DATA_DIR / "processed" / "settlements.parquet"

# Bracket question patterns — Fahrenheit (US cities)
_RE_INNER_F = re.compile(
    r"be between (-?\d+)-(-?\d+)\s*°?F", re.IGNORECASE,
)
_RE_TAIL_LOW_F = re.compile(
    r"be (-?\d+)\s*°?F or below", re.IGNORECASE,
)
_RE_TAIL_HIGH_F = re.compile(
    r"be (-?\d+)\s*°?F or higher", re.IGNORECASE,
)

# Bracket question patterns — Celsius (international cities)
_RE_INNER_C = re.compile(
    r"be between (-?\d+)-(-?\d+)\s*°?C", re.IGNORECASE,
)
_RE_TAIL_LOW_C = re.compile(
    r"be (-?\d+)\s*°?C or below", re.IGNORECASE,
)
_RE_TAIL_HIGH_C = re.compile(
    r"be (-?\d+)\s*°?C or higher", re.IGNORECASE,
)
# Single-value Celsius: "be 13°C on" (exact integer, no range)
_RE_EXACT_C = re.compile(
    r"be (-?\d+)\s*°?C on", re.IGNORECASE,
)


def parse_settlement_question(question: str) -> dict:
    """Parse bracket question into settlement bounds and unit.

    Returns dict with keys: lower, upper, unit, bracket_type.
    - inner:     lower=38, upper=39, unit='F'
    - tail_low:  lower=None, upper=37, unit='F'
    - tail_high: lower=56, upper=None, unit='F'
    - exact:     lower=13, upper=13, unit='C'  (single-degree Celsius)
    """
    # Fahrenheit inner: "between 38-39°F"
    m = _RE_INNER_F.search(question)
    if m:
        return {
            "lower": float(m.group(1)),
            "upper": float(m.group(2)),
            "unit": "F",
            "bracket_type": "inner",
        }

    # Fahrenheit tail low: "37°F or below"
    m = _RE_TAIL_LOW_F.search(question)
    if m:
        return {
            "lower": None,
            "upper": float(m.group(1)),
            "unit": "F",
            "bracket_type": "tail_low",
        }

    # Fahrenheit tail high: "56°F or higher"
    m = _RE_TAIL_HIGH_F.search(question)
    if m:
        return {
            "lower": float(m.group(1)),
            "upper": None,
            "unit": "F",
            "bracket_type": "tail_high",
        }

    # Celsius inner: "between 10-11°C"
    m = _RE_INNER_C.search(question)
    if m:
        return {
            "lower": float(m.group(1)),
            "upper": float(m.group(2)),
            "unit": "C",
            "bracket_type": "inner",
        }

    # Celsius tail low: "5°C or below"
    m = _RE_TAIL_LOW_C.search(question)
    if m:
        return {
            "lower": None,
            "upper": float(m.group(1)),
            "unit": "C",
            "bracket_type": "tail_low",
        }

    # Celsius tail high: "15°C or higher"
    m = _RE_TAIL_HIGH_C.search(question)
    if m:
        return {
            "lower": float(m.group(1)),
            "upper": None,
            "unit": "C",
            "bracket_type": "tail_high",
        }

    # Celsius exact: "be 13°C on March 11"
    m = _RE_EXACT_C.search(question)
    if m:
        return {
            "lower": float(m.group(1)),
            "upper": float(m.group(1)),
            "unit": "C",
            "bracket_type": "exact",
        }

    logger.warning("Could not parse question: %s", question)
    return {"lower": None, "upper": None, "unit": None, "bracket_type": "unknown"}


def extract_settlements(threshold: float = 0.95) -> pd.DataFrame:
    """Extract settlement data from price history.

    For each (city, date), finds the bracket whose last candle price
    is >= threshold (indicating it resolved to YES), parses the
    temperature range from the question text, and returns a DataFrame.

    Args:
        threshold: minimum final price to consider a bracket resolved.
    """
    logger.info("Reading price history from %s", PRICE_HISTORY_PATH)
    ph = pd.read_parquet(PRICE_HISTORY_PATH)
    logger.info("Loaded %d candles across %d cities", len(ph), ph.city_slug.nunique())

    # Get the last candle per (city, date, bracket)
    last_prices = (
        ph.sort_values("timestamp")
        .groupby(["city_slug", "city_name", "market_date", "bracket_index"])
        .last()
        .reset_index()
    )

    # Filter to winning brackets
    winners = last_prices[last_prices.price >= threshold].copy()
    logger.info(
        "Found %d winning brackets (price >= %.2f) across %d cities",
        len(winners), threshold, winners.city_slug.nunique(),
    )

    # Handle ties: if multiple brackets resolve >= threshold for the same
    # (city, date), keep the one with the highest price
    winners = (
        winners.sort_values("price", ascending=False)
        .drop_duplicates(subset=["city_slug", "market_date"], keep="first")
    )
    logger.info("After dedup: %d settlements", len(winners))

    # Parse bracket questions
    parsed = winners["question"].apply(parse_settlement_question).apply(pd.Series)
    settlements = pd.DataFrame({
        "city_slug": winners["city_slug"].values,
        "city_name": winners["city_name"].values,
        "market_date": winners["market_date"].values,
        "winning_bracket_index": winners["bracket_index"].values,
        "winning_price": winners["price"].values,
        "question": winners["question"].values,
        "settled_lower": parsed["lower"].values,
        "settled_upper": parsed["upper"].values,
        "unit": parsed["unit"].values,
        "bracket_type": parsed["bracket_type"].values,
    })

    # Compute midpoint for inner/exact brackets
    settlements["settled_midpoint"] = None
    mask_inner = settlements.bracket_type.isin(["inner", "exact"])
    settlements.loc[mask_inner, "settled_midpoint"] = (
        (settlements.loc[mask_inner, "settled_lower"]
         + settlements.loc[mask_inner, "settled_upper"]) / 2
    )

    settlements = settlements.sort_values(
        ["city_slug", "market_date"],
    ).reset_index(drop=True)

    # Summary stats
    n_unknown = (settlements.bracket_type == "unknown").sum()
    if n_unknown:
        logger.warning("%d settlements could not be parsed", n_unknown)

    type_counts = settlements.bracket_type.value_counts()
    logger.info("Bracket types: %s", dict(type_counts))

    return settlements


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract settlements from price history")
    parser.add_argument(
        "--threshold", type=float, default=0.95,
        help="Minimum final price to consider resolved (default: 0.95)",
    )
    args = parser.parse_args()

    settlements = extract_settlements(args.threshold)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    settlements.to_parquet(OUTPUT_PATH, index=False)
    logger.info("Saved %d settlements to %s", len(settlements), OUTPUT_PATH)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Settlement Extraction Summary")
    print(f"{'=' * 60}")
    print(f"  Total settlements: {len(settlements)}")
    print(f"  Cities: {settlements.city_slug.nunique()}")
    print(f"  Date range: {settlements.market_date.min()} to {settlements.market_date.max()}")
    print(f"  Bracket types: {dict(settlements.bracket_type.value_counts())}")
    print(f"  Units: {dict(settlements.unit.value_counts())}")
    n_mid = settlements.settled_midpoint.notna().sum()
    print(f"  With midpoint (inner/exact): {n_mid}/{len(settlements)}")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
