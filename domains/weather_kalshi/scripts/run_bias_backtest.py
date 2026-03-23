"""Historical bias analysis report for weather forecasts.

Produces:
  1. Monthly bias table per station (mean, std, RMSE, directional accuracy)
  2. Seasonal bias evolution (stability over 20 years)
  3. Bracket hit rates (raw vs bias-corrected)
  4. Walk-forward stability test
  5. Actionable trading signals

Usage:
    python scripts/run_bias_backtest.py
    python scripts/run_bias_backtest.py --station KNYC
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bias_analysis import (
    compute_annual_bias,
    compute_monthly_bias,
    generate_bias_report,
)
from src.bracket_builder import build_brackets, evaluate_bracket_accuracy
from src.data_loader import load_pairs
from src.stations import PHASE1_STATIONS, get_station

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_bracket_accuracy_test(
    pairs: pd.DataFrame,
    monthly_bias: pd.DataFrame,
) -> pd.DataFrame:
    """Walk-forward bracket accuracy test.

    For each day, use bias profile trained on PRIOR years only,
    then evaluate bracket prediction accuracy.
    """
    results = []
    years = sorted(pairs["year"].unique())

    for test_year in years[3:]:  # Need at least 3 years of training data
        train = pairs[pairs["year"] < test_year]
        test = pairs[pairs["year"] == test_year]

        for _, row in test.iterrows():
            month = row["month"]

            # Get bias from training data only (walk-forward)
            train_month = train[
                (train["station"] == row["station"]) & (train["month"] == month)
            ]
            if len(train_month) < 30:
                continue

            mean_bias = train_month["error_high"].mean()
            std_error = train_month["error_high"].std()

            if pd.isna(row["forecast_high"]) or pd.isna(row["observed_high"]):
                continue

            result = evaluate_bracket_accuracy(
                forecast_temp=row["forecast_high"],
                observed_temp=row["observed_high"],
                mean_bias=mean_bias,
                std_error=std_error,
            )
            result["station"] = row["station"]
            result["date"] = row["date"]
            result["year"] = row["year"]
            result["month"] = month
            results.append(result)

    return pd.DataFrame(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bias analysis backtest")
    parser.add_argument("--station", type=str, default=None)
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

    # --- Part 1: Bias Report ---
    print(generate_bias_report(df))

    # --- Part 2: Annual Bias Stability ---
    print("\n--- Annual Bias Stability ---")
    annual = compute_annual_bias(df)
    for station in sorted(annual["station"].unique()):
        s_annual = annual[annual["station"] == station].sort_values("year")
        warm_years = (s_annual["mean_bias"] > 0).sum()
        total_years = len(s_annual)
        print(
            f"  {station}: warm bias in {warm_years}/{total_years} years "
            f"({warm_years / total_years:.0%})"
        )

    # --- Part 3: Bracket Accuracy (Walk-Forward) ---
    print("\n--- Bracket Accuracy Test (Walk-Forward) ---")
    monthly_bias = compute_monthly_bias(df)
    bracket_results = run_bracket_accuracy_test(df, monthly_bias)

    if not bracket_results.empty:
        for station in sorted(bracket_results["station"].unique()):
            s_results = bracket_results[bracket_results["station"] == station]
            naive_hit_rate = s_results["naive_hit"].mean()
            corrected_hit_rate = s_results["corrected_hit"].mean()
            improvement = corrected_hit_rate - naive_hit_rate

            print(f"\n  {station} ({len(s_results)} days tested):")
            print(f"    Naive bracket hit rate:     {naive_hit_rate:.1%}")
            print(f"    Corrected bracket hit rate:  {corrected_hit_rate:.1%}")
            print(f"    Improvement:                {improvement:+.1%}")

            # Average NO edge where model disagrees with naive
            disagree = s_results[
                s_results["naive_predicted_bracket"]
                != s_results["corrected_predicted_bracket"]
            ]
            if not disagree.empty:
                print(f"    Days with bracket shift:    {len(disagree)} ({len(disagree) / len(s_results):.1%})")
                print(f"    Avg max NO edge on shift:   {disagree['max_no_edge'].mean():.3f}")

            # Brier score (using probability assigned to actual bracket)
            naive_brier = (1 - s_results["naive_prob_actual"]).pow(2).mean()
            corrected_brier = (1 - s_results["corrected_prob_actual"]).pow(2).mean()
            print(f"    Naive Brier score:          {naive_brier:.4f}")
            print(f"    Corrected Brier score:      {corrected_brier:.4f}")

    # --- Part 4: Trading Signal Summary ---
    print("\n--- TRADING SIGNAL SUMMARY ---")
    print("Station-months with strong directional bias (P(too high) > 58% or < 42%):")
    monthly = compute_monthly_bias(df)
    month_names = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    signals = monthly[
        (monthly["prob_too_high"] > 0.58) | (monthly["prob_too_high"] < 0.42)
    ].sort_values("prob_too_high", ascending=False)

    if signals.empty:
        print("  No strong directional signals found.")
    else:
        for _, row in signals.iterrows():
            direction = "WARM" if row["prob_too_high"] > 0.5 else "COLD"
            action = "NO on high brackets" if direction == "WARM" else "NO on low brackets"
            print(
                f"  {row['station']} {month_names[int(row['month'])]}: "
                f"{direction} bias {row['mean_bias']:+.2f}F, "
                f"P(too high)={row['prob_too_high']:.1%}, "
                f"n={row['count']:.0f} -> {action}"
            )

    print("\nDone.")


if __name__ == "__main__":
    main()
