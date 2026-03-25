"""Simulated bracket trading backtest over 22 years of historical data.

Tests whether our calibrated forecasters produce profitable edge signals
against a naive market proxy. Uses Polymarket-style brackets (11 brackets,
2F wide, centered on forecast).

Strategy: when model probability differs from market proxy by more than
a threshold, "trade" the bracket. Resolve against observed temperature.

The "market" is approximated by a naive forecaster (raw GFS forecast +
historical monthly sigma). This is conservative — real markets may be
even tighter (lower sigma), so real edge might be larger.

Usage:
    python -m scripts.run_bracket_backtest
    python -m scripts.run_bracket_backtest --station KLGA --threshold 0.08
    python -m scripts.run_bracket_backtest --years 2020-2025
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bracket_builder import (
    build_brackets,
    forecast_to_bracket_probs,
    resolve_bracket,
)
from src.data_loader import load_pairs
from src.forecaster import (
    CRPSigmaForecaster,
    EMOSForecaster,
    NaiveForecaster,
    NBMForecaster,
)
from src.stations import POLYMARKET_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Polymarket uses 11 brackets (9 inner 2F + 2 tails)
N_INNER = 9
INNER_WIDTH = 2


def run_backtest(
    station_icao: str,
    edge_threshold: float = 0.05,
    min_train_years: int = 5,
    year_start: int | None = None,
    year_end: int | None = None,
    market_sigma_source: str = "naive",
) -> pd.DataFrame:
    """Walk-forward bracket trading backtest for one station.

    For each test day:
      1. Train forecasters on all prior data (walk-forward)
      2. Build 11 brackets centered on forecast
      3. Compute "market" probs (naive sigma) and "model" probs (calibrated sigma)
      4. If |edge| > threshold, record a trade
      5. Resolve bracket against observed temp
      6. Compute P&L: bought at market price, resolved YES/NO

    Returns DataFrame with one row per trade.
    """
    station = get_station(station_icao)
    pairs = load_pairs(station)

    if year_start:
        pairs = pairs[pairs["year"] >= year_start]
    if year_end:
        pairs = pairs[pairs["year"] <= year_end]

    years = sorted(pairs["year"].unique())
    if len(years) < min_train_years + 1:
        logger.error(f"Not enough years for {station_icao}")
        return pd.DataFrame()

    # Walk-forward: train on years[:i], test on year[i]
    trades = []
    for test_year_idx in range(min_train_years, len(years)):
        test_year = years[test_year_idx]
        train_years = years[:test_year_idx]

        train_df = pairs[pairs["year"].isin(train_years)]
        test_df = pairs[pairs["year"] == test_year]

        # Fit forecasters
        naive_f = NaiveForecaster()
        naive_f.fit(train_df)

        crps_f = CRPSigmaForecaster()
        crps_f.fit(train_df)

        emos_f = EMOSForecaster()
        emos_f.fit(train_df)

        for _, row in test_df.iterrows():
            forecast = row["forecast_high"]
            observed = row["observed_high"]
            month = int(row["month"])
            day_date = row["date"]

            if pd.isna(forecast) or pd.isna(observed):
                continue

            # Build Polymarket-style brackets
            brackets = build_brackets(forecast, n_inner=N_INNER, inner_width=INNER_WIDTH)

            # "Market" probabilities (naive — what market maker would use)
            naive_pred = naive_f.predict(forecast, station_icao, month)
            market_probs = forecast_to_bracket_probs(
                forecast, 0.0, naive_pred.sigma, brackets,
            )

            # "Model" probabilities (CRPSigma — our calibrated view)
            crps_pred = crps_f.predict(forecast, station_icao, month)
            model_probs = forecast_to_bracket_probs(
                forecast, 0.0, crps_pred.sigma, brackets,
            )

            # EMOS model probabilities
            emos_pred = emos_f.predict(forecast, station_icao, month)
            emos_probs = forecast_to_bracket_probs(
                emos_pred.mu, 0.0, emos_pred.sigma, brackets,
            )

            # Resolve: which bracket did observed temp fall in?
            resolved_idx = resolve_bracket(observed, brackets)

            for b in brackets:
                market_price = market_probs.get(b.index, 0.0)
                model_prob = model_probs.get(b.index, 0.0)
                emos_prob = emos_probs.get(b.index, 0.0)
                edge_crps = model_prob - market_price
                edge_emos = emos_prob - market_price

                resolved_yes = (b.index == resolved_idx)

                # CRPSigma trades
                if abs(edge_crps) >= edge_threshold:
                    buy_yes = edge_crps > 0
                    if buy_yes:
                        # Buy YES at market_price, payout 1.0 if resolved YES
                        pnl = (1.0 - market_price) if resolved_yes else -market_price
                    else:
                        # Buy NO at (1 - market_price), payout 1.0 if resolved NO
                        pnl = market_price if not resolved_yes else -(1.0 - market_price)

                    trades.append({
                        "station": station_icao,
                        "date": day_date,
                        "year": test_year,
                        "month": month,
                        "forecast": forecast,
                        "observed": observed,
                        "bracket": b.label,
                        "bracket_idx": b.index,
                        "market_price": market_price,
                        "model_prob": model_prob,
                        "edge": edge_crps,
                        "direction": "YES" if buy_yes else "NO",
                        "resolved_yes": resolved_yes,
                        "pnl": pnl,
                        "forecaster": "CRPSigma",
                        "market_sigma": naive_pred.sigma,
                        "model_sigma": crps_pred.sigma,
                    })

                # EMOS trades
                if abs(edge_emos) >= edge_threshold:
                    buy_yes = edge_emos > 0
                    if buy_yes:
                        pnl = (1.0 - market_price) if resolved_yes else -market_price
                    else:
                        pnl = market_price if not resolved_yes else -(1.0 - market_price)

                    trades.append({
                        "station": station_icao,
                        "date": day_date,
                        "year": test_year,
                        "month": month,
                        "forecast": forecast,
                        "observed": observed,
                        "bracket": b.label,
                        "bracket_idx": b.index,
                        "market_price": market_price,
                        "model_prob": emos_prob,
                        "edge": edge_emos,
                        "direction": "YES" if buy_yes else "NO",
                        "resolved_yes": resolved_yes,
                        "pnl": pnl,
                        "forecaster": "EMOS",
                        "market_sigma": naive_pred.sigma,
                        "model_sigma": emos_pred.sigma,
                    })

    return pd.DataFrame(trades)


def print_backtest_report(trades: pd.DataFrame, threshold: float) -> None:
    """Print formatted backtest results."""
    if trades.empty:
        print("No trades generated.")
        return

    print(f"\n{'=' * 70}")
    print(f"BRACKET TRADING BACKTEST — threshold={threshold:.0%}")
    print(f"{'=' * 70}")

    for forecaster, f_trades in trades.groupby("forecaster"):
        print(f"\n--- {forecaster} ---")

        for station, st_trades in f_trades.groupby("station"):
            n_trades = len(st_trades)
            total_pnl = st_trades["pnl"].sum()
            mean_pnl = st_trades["pnl"].mean()
            win_rate = (st_trades["pnl"] > 0).mean()
            mean_edge = st_trades["edge"].abs().mean()
            years = st_trades["year"].nunique()
            days = st_trades["date"].nunique()

            # Direction breakdown
            yes_trades = st_trades[st_trades["direction"] == "YES"]
            no_trades = st_trades[st_trades["direction"] == "NO"]

            print(f"\n  {station}: {n_trades} trades over {years} years ({days} trading days)")
            print(f"    Total P&L: {total_pnl:+.1f} units  |  Mean P&L/trade: {mean_pnl:+.4f}")
            print(f"    Win rate: {win_rate:.1%}  |  Mean |edge|: {mean_edge:.1%}")
            print(f"    BUY YES: {len(yes_trades)} trades, P&L={yes_trades['pnl'].sum():+.1f}")
            print(f"    BUY NO:  {len(no_trades)} trades, P&L={no_trades['pnl'].sum():+.1f}")

            # Annual P&L
            annual = st_trades.groupby("year")["pnl"].agg(["sum", "count", "mean"])
            annual.columns = ["pnl", "n_trades", "mean_pnl"]
            print(f"\n    Year    P&L    Trades  Mean P&L")
            for yr, row in annual.tail(10).iterrows():
                marker = " +" if row["pnl"] > 0 else " -" if row["pnl"] < 0 else "  "
                print(f"    {yr}{marker} {row['pnl']:+7.1f}  {int(row['n_trades']):6d}  {row['mean_pnl']:+.4f}")

    # Overall summary
    print(f"\n{'=' * 70}")
    print("OVERALL SUMMARY")
    print(f"{'=' * 70}")
    for forecaster, f_trades in trades.groupby("forecaster"):
        n = len(f_trades)
        pnl = f_trades["pnl"].sum()
        wr = (f_trades["pnl"] > 0).mean()
        sharpe_daily = f_trades.groupby("date")["pnl"].sum()
        if sharpe_daily.std() > 0:
            sharpe = sharpe_daily.mean() / sharpe_daily.std() * np.sqrt(252)
        else:
            sharpe = 0.0
        print(f"  {forecaster:12s}: {n:6d} trades, P&L={pnl:+8.1f}, "
              f"win={wr:.1%}, Sharpe={sharpe:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bracket trading backtest")
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--years", type=str, default=None, help="Year range, e.g. 2015-2025")
    args = parser.parse_args()

    stations = [args.station] if args.station else POLYMARKET_STATIONS

    year_start, year_end = None, None
    if args.years:
        parts = args.years.split("-")
        year_start = int(parts[0])
        year_end = int(parts[1]) if len(parts) > 1 else None

    all_trades = []
    for icao in stations:
        logger.info(f"Running backtest for {icao}...")
        trades = run_backtest(
            icao,
            edge_threshold=args.threshold,
            year_start=year_start,
            year_end=year_end,
        )
        if not trades.empty:
            all_trades.append(trades)

    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        print_backtest_report(combined, args.threshold)
    else:
        print("No trades generated.")

    print("\nDone.")


if __name__ == "__main__":
    main()
