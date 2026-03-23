"""NO-biased trading strategy backtest.

Simulates buying NO on brackets where bias correction indicates the naive
forecast is overpricing. Uses walk-forward methodology: bias profiles are
computed from prior years only.

Key parameters:
  - Minimum edge: 8% (|model_prob - naive_prob| > 0.08)
  - Fractional Kelly: 15% of full Kelly
  - Position cap: $100 per trade
  - Maker fee: ~$0.007 per contract (~0.7%)

Research basis: Chris Dodds' analysis shows YES trades on Kalshi weather
lose 75-88% of the time. NO-only strategy yielded ~86% win rate in backtesting.
The favorite-longshot bias creates systematic YES losses.

Usage:
    python scripts/run_no_strategy_backtest.py
    python scripts/run_no_strategy_backtest.py --station KNYC
    python scripts/run_no_strategy_backtest.py --min-edge 0.05
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bracket_builder import (
    build_brackets,
    compute_naive_probs,
    compute_no_edge,
    forecast_to_bracket_probs,
    resolve_bracket,
)
from src.data_loader import load_pairs
from src.stations import PHASE1_STATIONS, get_station

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Trading parameters
DEFAULT_MIN_EDGE = 0.08  # Minimum NO edge to trigger a trade
MAKER_FEE_RATE = 0.007  # ~0.7% maker fee
FRACTIONAL_KELLY = 0.15  # 15% of full Kelly
MAX_POSITION = 100.0  # $100 max per trade
INITIAL_BANKROLL = 1000.0  # Starting capital


def compute_kelly_fraction(
    true_prob_no: float,
    market_price_no: float,
) -> float:
    """Compute fractional Kelly bet size for a NO trade.

    Full Kelly: f* = (p - q) / (1 - q) where p = true prob of NO winning,
    q = market-implied prob of NO (= 1 - bracket_price).

    Returns fractional Kelly (15% of full Kelly).
    """
    if true_prob_no <= market_price_no:
        return 0.0
    full_kelly = (true_prob_no - market_price_no) / (1.0 - market_price_no)
    return min(full_kelly * FRACTIONAL_KELLY, 0.05)  # Cap at 5% of bankroll


def simulate_no_strategy(
    pairs: pd.DataFrame,
    min_edge: float = DEFAULT_MIN_EDGE,
    min_train_years: int = 3,
) -> pd.DataFrame:
    """Run walk-forward NO-biased trading simulation.

    For each test day:
    1. Train bias profile on prior years only
    2. Compute bias-corrected bracket probs
    3. Compute naive bracket probs (proxy for market prices)
    4. Find brackets with NO edge > min_edge
    5. Simulate buying NO at the naive price (maker fee applies)
    6. Resolve: observed temp determines which bracket wins

    Returns:
        DataFrame with one row per trade.
    """
    trades = []
    years = sorted(pairs["year"].unique())

    for test_year in years[min_train_years:]:
        train = pairs[pairs["year"] < test_year]
        test = pairs[pairs["year"] == test_year]

        for _, row in test.iterrows():
            month = row["month"]
            station = row["station"]

            # Walk-forward: use only prior years for this station-month
            train_sm = train[(train["station"] == station) & (train["month"] == month)]
            if len(train_sm) < 30:
                continue

            mean_bias = train_sm["error_high"].mean()
            std_error = train_sm["error_high"].std()

            forecast = row["forecast_high"]
            observed = row["observed_high"]
            if pd.isna(forecast) or pd.isna(observed):
                continue

            # Build brackets centered on forecast
            brackets = build_brackets(forecast)

            # Compute probabilities
            corrected_probs = forecast_to_bracket_probs(
                forecast, mean_bias, std_error, brackets
            )
            naive_probs = compute_naive_probs(forecast, std_error, brackets)

            # Find NO edges
            edges = compute_no_edge(corrected_probs, naive_probs)

            # Determine which bracket the observed temp actually fell in
            # Uses same +0.5 boundaries as CDF integration for consistency
            actual_bracket = resolve_bracket(observed, brackets)

            # Trade: buy NO on brackets with sufficient edge
            for bracket_idx, no_edge in edges.items():
                if no_edge < min_edge:
                    continue

                # Price we buy NO at = 1 - naive_prob (market price of NO)
                bracket_yes_price = naive_probs[bracket_idx]
                no_price = 1.0 - bracket_yes_price

                # Kelly sizing
                true_no_prob = 1.0 - corrected_probs[bracket_idx]
                kelly_frac = compute_kelly_fraction(true_no_prob, no_price)
                if kelly_frac <= 0:
                    continue

                position_size = min(kelly_frac * INITIAL_BANKROLL, MAX_POSITION)

                # Number of contracts (each pays $1 if NO wins)
                n_contracts = position_size / no_price
                cost = n_contracts * no_price
                fee = n_contracts * MAKER_FEE_RATE

                # Resolution: NO wins if observed temp is NOT in this bracket
                no_wins = (actual_bracket != bracket_idx)
                payout = n_contracts * 1.0 if no_wins else 0.0
                pnl = payout - cost - fee

                bracket_label = brackets[bracket_idx].label

                trades.append({
                    "date": row["date"],
                    "station": station,
                    "year": test_year,
                    "month": month,
                    "forecast_high": forecast,
                    "observed_high": observed,
                    "error": forecast - observed,
                    "bracket_idx": bracket_idx,
                    "bracket_label": bracket_label,
                    "no_edge": no_edge,
                    "no_price": no_price,
                    "true_no_prob": true_no_prob,
                    "n_contracts": n_contracts,
                    "cost": cost,
                    "fee": fee,
                    "payout": payout,
                    "pnl": pnl,
                    "no_wins": no_wins,
                })

    return pd.DataFrame(trades)


def print_report(trades: pd.DataFrame, min_edge: float) -> None:
    """Print comprehensive backtest report."""
    print("=" * 70)
    print("NO-BIASED TRADING STRATEGY BACKTEST")
    print(f"Min edge: {min_edge:.0%} | Kelly: {FRACTIONAL_KELLY:.0%} | "
          f"Max position: ${MAX_POSITION:.0f} | Maker fee: {MAKER_FEE_RATE:.1%}")
    print("=" * 70)

    if trades.empty:
        print("\nNo trades generated. Check min_edge threshold.")
        return

    # Overall summary
    total_trades = len(trades)
    wins = trades["no_wins"].sum()
    win_rate = wins / total_trades
    total_pnl = trades["pnl"].sum()
    total_cost = trades["cost"].sum()
    roi = total_pnl / total_cost if total_cost > 0 else 0

    print(f"\n--- Overall Performance ---")
    print(f"  Total trades:   {total_trades}")
    print(f"  Win rate:       {win_rate:.1%} ({wins:.0f}W / {total_trades - wins:.0f}L)")
    print(f"  Total P&L:      ${total_pnl:.2f}")
    print(f"  Total cost:     ${total_cost:.2f}")
    print(f"  ROI:            {roi:.1%}")
    print(f"  Avg P&L/trade:  ${total_pnl / total_trades:.2f}")

    # Sharpe ratio (annualized from daily P&L)
    daily_pnl = trades.groupby("date")["pnl"].sum()
    if len(daily_pnl) > 10:
        sharpe = daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)
        print(f"  Sharpe ratio:   {sharpe:.3f}")

    # Max drawdown
    cumulative = daily_pnl.cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()
    print(f"  Max drawdown:   ${max_dd:.2f}")

    # Longest losing streak
    losses = ~trades["no_wins"].values
    max_streak = 0
    current_streak = 0
    for loss in losses:
        if loss:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    print(f"  Max loss streak: {max_streak}")

    # Per-station breakdown
    print(f"\n--- By Station ---")
    for station in sorted(trades["station"].unique()):
        s = trades[trades["station"] == station]
        s_wins = s["no_wins"].sum()
        s_pnl = s["pnl"].sum()
        s_roi = s_pnl / s["cost"].sum() if s["cost"].sum() > 0 else 0
        print(
            f"  {station}: {len(s)} trades, "
            f"{s_wins / len(s):.1%} win rate, "
            f"${s_pnl:.2f} P&L, "
            f"{s_roi:.1%} ROI"
        )

    # Per-year breakdown
    print(f"\n--- By Year ---")
    for year in sorted(trades["year"].unique()):
        y = trades[trades["year"] == year]
        y_wins = y["no_wins"].sum()
        y_pnl = y["pnl"].sum()
        y_roi = y_pnl / y["cost"].sum() if y["cost"].sum() > 0 else 0
        print(
            f"  {year}: {len(y)} trades, "
            f"{y_wins / len(y):.1%} win rate, "
            f"${y_pnl:.2f} P&L, "
            f"{y_roi:.1%} ROI"
        )

    # Per-month breakdown
    print(f"\n--- By Month ---")
    month_names = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    for month in sorted(trades["month"].unique()):
        m = trades[trades["month"] == month]
        m_wins = m["no_wins"].sum()
        m_pnl = m["pnl"].sum()
        m_roi = m_pnl / m["cost"].sum() if m["cost"].sum() > 0 else 0
        print(
            f"  {month_names[month]:>3}: {len(m)} trades, "
            f"{m_wins / len(m):.1%} win rate, "
            f"${m_pnl:.2f} P&L, "
            f"{m_roi:.1%} ROI"
        )

    # Edge distribution
    print(f"\n--- Edge Distribution ---")
    for label, lo, hi in [
        ("8-12%", 0.08, 0.12),
        ("12-16%", 0.12, 0.16),
        ("16-20%", 0.16, 0.20),
        ("20%+", 0.20, 1.0),
    ]:
        bucket = trades[(trades["no_edge"] >= lo) & (trades["no_edge"] < hi)]
        if not bucket.empty:
            b_wins = bucket["no_wins"].sum()
            b_roi = bucket["pnl"].sum() / bucket["cost"].sum() if bucket["cost"].sum() > 0 else 0
            print(
                f"  {label}: {len(bucket)} trades, "
                f"{b_wins / len(bucket):.1%} win rate, "
                f"{b_roi:.1%} ROI"
            )

    print("\n" + "=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="NO-strategy backtest")
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument(
        "--min-edge",
        type=float,
        default=DEFAULT_MIN_EDGE,
        help=f"Minimum NO edge to trigger trade (default: {DEFAULT_MIN_EDGE})",
    )
    args = parser.parse_args()

    stations = [args.station] if args.station else PHASE1_STATIONS

    all_pairs = []
    for icao in stations:
        try:
            station = get_station(icao)
            pairs = load_pairs(station)
            all_pairs.append(pairs)
            logger.info(f"Loaded {len(pairs)} pairs for {icao}")
        except FileNotFoundError:
            logger.warning(f"No data for {icao}. Run download_iem_data.py first.")

    if not all_pairs:
        logger.error("No data available. Run download_iem_data.py first.")
        return

    df = pd.concat(all_pairs, ignore_index=True)

    logger.info("Running NO-strategy simulation...")
    trades = simulate_no_strategy(df, min_edge=args.min_edge)

    print_report(trades, args.min_edge)


if __name__ == "__main__":
    main()
