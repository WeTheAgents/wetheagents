"""Compare CRPSigma model probabilities to actual Kalshi market prices.

For each day with both Kalshi prices AND forecast-obs pairs:
  1. Get bracket structure + market prices from Kalshi
  2. Compute CRPSigma bracket probabilities (walk-forward)
  3. Compute edge = our_prob - market_price per bracket
  4. Check which bracket actually won (from observation data)

Usage:
    python scripts/run_edge_analysis.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_loader import load_pairs
from src.forecaster import CRPSigmaForecaster, NaiveForecaster
from src.kalshi_client import load_weather_data
from src.stations import PHASE1_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def compute_bracket_probs(
    forecast_temp: float,
    sigma: float,
    bracket_strs: list[str],
    strikes: list[float],
    bracket_types: list[str],
) -> dict[str, float]:
    """Compute Gaussian probabilities for Kalshi bracket structure.

    Kalshi brackets:
      T{X} (tail_low): temp <= X
      B{X}.5 (inner): X < temp <= X+2 (approximately)
      T{X} (tail_high): temp >= X

    Returns dict mapping bracket_str -> probability.
    """
    dist = stats.norm(loc=forecast_temp, scale=max(sigma, 0.5))
    probs = {}

    # Sort brackets by strike to determine boundaries
    items = list(zip(bracket_strs, strikes, bracket_types))
    items.sort(key=lambda x: x[1])

    for bs, strike, bt in items:
        if bt == "tail_low":
            # P(temp <= strike)
            probs[bs] = dist.cdf(strike + 0.5)
        elif bt == "tail_high":
            # P(temp >= strike)
            probs[bs] = 1.0 - dist.cdf(strike - 0.5)
        elif bt == "inner":
            # P(strike-1 < temp <= strike+1) approximately
            # The B{X}.5 means boundary at X.5
            # Inner bracket spans from X.5-1 to X.5+1 = X-0.5 to X+1.5
            # But with integer temps: covers X and X+1
            lo = strike - 1.0  # lower boundary
            hi = strike + 1.0  # upper boundary
            probs[bs] = dist.cdf(hi) - dist.cdf(lo)

    # Normalize to sum to 1
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}

    return probs


def run_edge_analysis(
    kalshi_df: pd.DataFrame,
    forecast_pairs: pd.DataFrame,
) -> pd.DataFrame:
    """Compare model probabilities to Kalshi market prices.

    Returns DataFrame with one row per bracket per day.
    """
    # Train forecasters on all available data BEFORE the Kalshi period
    kalshi_dates = pd.to_datetime(kalshi_df["market_date"]).dt.date
    min_kalshi_date = min(kalshi_dates)

    # Convert date column for comparison
    fp_dates = pd.to_datetime(forecast_pairs["date"]).dt.date
    train = forecast_pairs[fp_dates < min_kalshi_date]
    logger.info(f"Training on {len(train)} forecast-obs pairs before {min_kalshi_date}")

    crps_fc = CRPSigmaForecaster()
    crps_fc.fit(train)
    naive_fc = NaiveForecaster()
    naive_fc.fit(train)

    # For each market date + station, use pre-settlement prices
    # (data_date < market_date or data_date == market_date with care)
    results = []

    for (station, md), group in kalshi_df.groupby(["station", "market_date"]):
        # Find best data_date: prefer day before settlement
        data_dates = sorted(group["data_date"].unique())
        # Use earliest data_date (typically day before settlement)
        best_dd = data_dates[0]
        day_markets = group[group["data_date"] == best_dd]

        if len(day_markets) != 6:
            continue  # skip incomplete bracket sets

        # Get forecast for this day
        day_pairs = forecast_pairs[
            (forecast_pairs["station"] == station)
            & (pd.to_datetime(forecast_pairs["date"]).dt.date == md)
        ]
        if day_pairs.empty:
            continue

        forecast_high = day_pairs.iloc[0]["forecast_high"]
        observed_high = day_pairs.iloc[0]["observed_high"]
        month = int(day_pairs.iloc[0]["month"])

        # Get model predictions
        crps_pred = crps_fc.predict(forecast_high, station, month)
        naive_pred = naive_fc.predict(forecast_high, station, month)

        # Compute bracket probabilities
        bracket_strs = day_markets["bracket_str"].tolist()
        strikes = day_markets["strike"].tolist()
        types = day_markets["bracket_type"].tolist()

        crps_probs = compute_bracket_probs(
            crps_pred.mu, crps_pred.sigma, bracket_strs, strikes, types
        )
        naive_probs = compute_bracket_probs(
            naive_pred.mu, naive_pred.sigma, bracket_strs, strikes, types
        )

        # Determine winner
        winning_bracket = None
        for _, row in day_markets.iterrows():
            if row["high_price"] >= 95:  # settled YES
                winning_bracket = row["bracket_str"]
                break

        for _, row in day_markets.iterrows():
            bs = row["bracket_str"]
            bt = row["bracket_type"]
            market_price = row["high_price"] / 100.0  # convert cents to dollars
            market_mid = (row["high_price"] + row["low_price"]) / 200.0

            crps_prob = crps_probs.get(bs, 0.0)
            naive_prob = naive_probs.get(bs, 0.0)

            won = 1 if bs == winning_bracket else 0

            results.append({
                "station": station,
                "market_date": md,
                "bracket_str": bs,
                "bracket_type": bt,
                "strike": row["strike"],
                "market_high": market_price,
                "market_mid": market_mid,
                "volume": row["volume"],
                "crps_prob": crps_prob,
                "naive_prob": naive_prob,
                "edge_vs_high": crps_prob - market_price,
                "edge_vs_mid": crps_prob - market_mid,
                "naive_edge_vs_mid": naive_prob - market_mid,
                "won": won,
                "forecast_high": forecast_high,
                "observed_high": observed_high,
                "crps_sigma": crps_pred.sigma,
                "naive_sigma": naive_pred.sigma,
            })

    return pd.DataFrame(results)


def print_market_structure(results: pd.DataFrame) -> None:
    """Print overview of Kalshi market pricing patterns."""
    print("=" * 75)
    print("KALSHI MARKET STRUCTURE OVERVIEW")
    print("=" * 75)

    for bt in ["tail_low", "inner", "tail_high"]:
        sub = results[results["bracket_type"] == bt]
        if sub.empty:
            continue
        print(f"\n{bt} brackets (n={len(sub)}):")
        print(f"  Market high:  mean={sub['market_high'].mean()*100:.1f}c  std={sub['market_high'].std()*100:.1f}c")
        print(f"  Market mid:   mean={sub['market_mid'].mean()*100:.1f}c  std={sub['market_mid'].std()*100:.1f}c")
        print(f"  CRPSigma:     mean={sub['crps_prob'].mean()*100:.1f}%")
        print(f"  Naive:        mean={sub['naive_prob'].mean()*100:.1f}%")
        print(f"  Win rate:     {sub['won'].mean()*100:.1f}%")
        print(f"  Avg volume:   {sub['volume'].mean():,.0f}")


def print_edge_analysis(results: pd.DataFrame) -> None:
    """Print edge analysis: model vs market."""
    print("\n" + "=" * 75)
    print("EDGE ANALYSIS: CRPSigma vs Kalshi Market Prices")
    print("=" * 75)

    print(f"\n{'Station':<8} {'Type':<12} {'N':>4} {'Mkt Mid':>8} {'CRPSig':>8} {'Edge':>8} {'Won%':>6}")
    print("-" * 60)

    for station in sorted(results["station"].unique()):
        for bt in ["tail_low", "inner", "tail_high"]:
            sub = results[(results["station"] == station) & (results["bracket_type"] == bt)]
            if sub.empty:
                continue
            print(
                f"{station:<8} {bt:<12} {len(sub):>4} "
                f"{sub['market_mid'].mean()*100:7.1f}c "
                f"{sub['crps_prob'].mean()*100:7.1f}% "
                f"{sub['edge_vs_mid'].mean()*100:+7.1f}pp "
                f"{sub['won'].mean()*100:5.1f}%"
            )

    # Overall summary
    print("\n--- OVERALL ---")
    for bt in ["tail_low", "inner", "tail_high"]:
        sub = results[results["bracket_type"] == bt]
        if sub.empty:
            continue
        edge = sub["edge_vs_mid"].mean() * 100
        direction = "MODEL OVERPRICES (market is cheap)" if edge > 0 else "MARKET OVERPRICES (model is cheap)"
        print(f"{bt:<12}: edge={edge:+.1f}pp -> {direction}")


def print_naive_comparison(results: pd.DataFrame) -> None:
    """Compare how well Naive proxy matches real market prices."""
    print("\n" + "=" * 75)
    print("NAIVE vs REAL MARKET: How good is our Naive proxy?")
    print("=" * 75)

    print(f"\n{'Type':<12} {'Mkt Mid':>8} {'Naive':>8} {'Diff':>8} {'CRPSig':>8} {'Diff':>8}")
    print("-" * 60)

    for bt in ["tail_low", "inner", "tail_high"]:
        sub = results[results["bracket_type"] == bt]
        if sub.empty:
            continue
        mkt = sub["market_mid"].mean() * 100
        naive = sub["naive_prob"].mean() * 100
        crps = sub["crps_prob"].mean() * 100
        print(
            f"{bt:<12} {mkt:7.1f}c {naive:7.1f}% {naive - mkt:+7.1f}pp "
            f"{crps:7.1f}% {crps - mkt:+7.1f}pp"
        )


def print_pnl_simulation(results: pd.DataFrame) -> None:
    """Simulate P&L for trading based on edge."""
    print("\n" + "=" * 75)
    print("P&L SIMULATION: Buy YES where CRPSigma > market mid")
    print("=" * 75)

    # For each bracket where edge > 0: buy YES at market_mid
    positive_edge = results[results["edge_vs_mid"] > 0]
    if positive_edge.empty:
        print("No brackets with positive edge found.")
        return

    trades = len(positive_edge)
    cost = positive_edge["market_mid"].sum()
    payout = positive_edge["won"].sum()  # $1 for each win
    pnl = payout - cost
    roi = pnl / cost * 100 if cost > 0 else 0
    win_rate = positive_edge["won"].mean() * 100

    print(f"\nTrades: {trades}")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Total cost: ${cost:.2f}")
    print(f"Total payout: ${payout:.2f}")
    print(f"P&L: ${pnl:.2f}")
    print(f"ROI: {roi:+.1f}%")

    # By bracket type
    print(f"\n{'Type':<12} {'Trades':>6} {'Win%':>6} {'Cost':>8} {'P&L':>8} {'ROI':>8}")
    print("-" * 55)
    for bt in ["tail_low", "inner", "tail_high"]:
        sub = positive_edge[positive_edge["bracket_type"] == bt]
        if sub.empty:
            continue
        bt_cost = sub["market_mid"].sum()
        bt_pnl = sub["won"].sum() - bt_cost
        bt_roi = bt_pnl / bt_cost * 100 if bt_cost > 0 else 0
        print(
            f"{bt:<12} {len(sub):>6} {sub['won'].mean()*100:5.1f}% "
            f"${bt_cost:7.2f} ${bt_pnl:+7.2f} {bt_roi:+7.1f}%"
        )


def main() -> None:
    # Load Kalshi data
    kalshi_df = load_weather_data()
    logger.info(f"Loaded {len(kalshi_df)} Kalshi market records")

    # Filter to finalized markets with volume
    kalshi_df = kalshi_df[
        (kalshi_df["status"] == "finalized")
        & (kalshi_df["volume"] > 0)
    ]
    logger.info(f"After filtering (finalized, volume>0): {len(kalshi_df)}")

    # Load forecast-obs pairs
    all_pairs = []
    for icao in PHASE1_STATIONS:
        try:
            pairs = load_pairs(get_station(icao))
            all_pairs.append(pairs)
        except FileNotFoundError:
            logger.warning(f"No data for {icao}")
    forecast_pairs = pd.concat(all_pairs, ignore_index=True)
    logger.info(f"Loaded {len(forecast_pairs)} forecast-obs pairs")

    # Run analysis
    results = run_edge_analysis(kalshi_df, forecast_pairs)

    if results.empty:
        logger.error("No matching data between Kalshi markets and forecast-obs pairs.")
        return

    logger.info(f"Edge analysis: {len(results)} bracket-days")

    # Reports
    print(f"\nDate range: {results['market_date'].min()} to {results['market_date'].max()}")
    print(f"Stations: {sorted(results['station'].unique())}")
    print(f"Total bracket-days: {len(results)}")

    print_market_structure(results)
    print_edge_analysis(results)
    print_naive_comparison(results)
    print_pnl_simulation(results)


if __name__ == "__main__":
    main()
