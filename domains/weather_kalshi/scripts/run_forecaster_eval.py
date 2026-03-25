"""Walk-forward evaluation of Naive, Bias, and EMOS forecasters.

For each test year (with sufficient prior training data):
  1. Split: train = prior years, test = this year
  2. Fit each forecaster on train
  3. Predict on test -> (mu, sigma) for each day
  4. Score: CRPS, MAE, bias, coverage, sharpness

Usage:
    python scripts/run_forecaster_eval.py
    python scripts/run_forecaster_eval.py --station KNYC
    python scripts/run_forecaster_eval.py --rolling-window 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_loader import load_pairs
from src.forecaster import (
    BiasForecaster,
    CRPSigmaForecaster,
    EMOSForecaster,
    Forecaster,
    NaiveForecaster,
)
from src.scoring import (
    coverage_probability,
    crps_gaussian,
    crps_mean,
    pit_values,
    reliability_bins,
    sharpness,
)
from src.stations import PHASE1_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def make_forecasters() -> list[Forecaster]:
    """Create fresh forecaster instances for one walk-forward fold."""
    return [
        NaiveForecaster(),
        BiasForecaster(),
        EMOSForecaster(),
        CRPSigmaForecaster(),
    ]


def evaluate_walk_forward(
    pairs: pd.DataFrame,
    min_train_years: int = 3,
    rolling_window: int | None = None,
) -> pd.DataFrame:
    """Walk-forward evaluation: train on prior years, test on current year.

    Returns DataFrame with one row per (forecaster, test day), columns:
      station, date, year, month, forecast_high, observed_high,
      pred_mu, pred_sigma, pred_method, crps.
    """
    years = sorted(pairs["year"].unique())
    all_results = []

    for test_year in years[min_train_years:]:
        if rolling_window is not None:
            train = pairs[
                (pairs["year"] < test_year)
                & (pairs["year"] >= test_year - rolling_window)
            ]
        else:
            train = pairs[pairs["year"] < test_year]

        test = pairs[pairs["year"] == test_year]

        if len(train) < MIN_SAMPLES_YEAR or len(test) == 0:
            continue

        for forecaster in make_forecasters():
            forecaster.fit(train)
            preds = forecaster.predict_batch(test)

            preds["crps"] = crps_gaussian(
                preds["observed_high"].values,
                preds["pred_mu"].values,
                preds["pred_sigma"].values,
            )
            preds["abs_error_mu"] = np.abs(
                preds["pred_mu"] - preds["observed_high"]
            )
            preds["bias_mu"] = preds["pred_mu"] - preds["observed_high"]

            all_results.append(
                preds[
                    [
                        "station", "date", "year", "month",
                        "forecast_high", "observed_high",
                        "pred_mu", "pred_sigma", "pred_method",
                        "crps", "abs_error_mu", "bias_mu",
                    ]
                ]
            )

        logger.info(f"  year {test_year}: {len(test)} test days")

    return pd.concat(all_results, ignore_index=True)


# Minimum training rows before we start testing
MIN_SAMPLES_YEAR = 300


def aggregate_results(results: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-day results into summary by (method, station)."""
    rows = []
    for (method, station), grp in results.groupby(["pred_method", "station"]):
        obs = grp["observed_high"].values
        mu = grp["pred_mu"].values
        sigma = grp["pred_sigma"].values

        rows.append({
            "method": method,
            "station": station,
            "crps": crps_mean(obs, mu, sigma),
            "mae": float(grp["abs_error_mu"].mean()),
            "bias": float(grp["bias_mu"].mean()),
            "cov90": coverage_probability(obs, mu, sigma, 0.9),
            "sharp": sharpness(sigma),
            "n_days": len(grp),
        })

    # Also compute all-station aggregate
    for method, grp in results.groupby("pred_method"):
        obs = grp["observed_high"].values
        mu = grp["pred_mu"].values
        sigma = grp["pred_sigma"].values

        rows.append({
            "method": method,
            "station": "ALL",
            "crps": crps_mean(obs, mu, sigma),
            "mae": float(grp["abs_error_mu"].mean()),
            "bias": float(grp["bias_mu"].mean()),
            "cov90": coverage_probability(obs, mu, sigma, 0.9),
            "sharp": sharpness(sigma),
            "n_days": len(grp),
        })

    return pd.DataFrame(rows)


def print_comparison_table(summary: pd.DataFrame) -> None:
    """Print formatted comparison table."""
    # Get Naive CRPS per station for relative comparison
    naive_crps = {}
    for _, row in summary[summary["method"] == "Naive"].iterrows():
        naive_crps[row["station"]] = row["crps"]

    print("=" * 75)
    print("FORECASTER EVALUATION — WALK-FORWARD COMPARISON")
    print("=" * 75)

    stations = [s for s in summary["station"].unique() if s != "ALL"]
    stations.append("ALL")

    for station in stations:
        sub = summary[summary["station"] == station].sort_values("method")
        if sub.empty:
            continue

        n_days = int(sub.iloc[0]["n_days"])
        label = f"ALL STATIONS" if station == "ALL" else station
        print(f"\n--- {label} ({n_days:,} test days) ---")
        print(f"{'Forecaster':<12} {'CRPS':>6} {'MAE':>6} {'Bias':>7} {'Cov90%':>7} {'Sharp':>6} {'vs Naive':>10}")

        base_crps = naive_crps.get(station, 1.0)
        for _, row in sub.iterrows():
            vs = "(baseline)" if row["method"] == "Naive" else f"{(row['crps'] / base_crps - 1) * 100:+.1f}%"
            print(
                f"{row['method']:<12} {row['crps']:6.3f} {row['mae']:6.2f} "
                f"{row['bias']:+7.3f} {row['cov90'] * 100:6.1f}% {row['sharp']:6.2f} {vs:>10}"
            )


def print_pit_summary(results: pd.DataFrame) -> None:
    """Print PIT calibration summary per forecaster."""
    print("\n" + "=" * 75)
    print("PIT CALIBRATION DIAGNOSTICS")
    print("=" * 75)

    for method in sorted(results["pred_method"].unique()):
        sub = results[results["pred_method"] == method]
        pit = pit_values(
            sub["observed_high"].values,
            sub["pred_mu"].values,
            sub["pred_sigma"].values,
        )
        rb = reliability_bins(pit, n_bins=10)

        print(f"\n--- {method} (all stations) ---")
        for i in range(len(rb["counts"])):
            lo = rb["bin_edges"][i]
            hi = rb["bin_edges"][i + 1]
            count = rb["counts"][i]
            exp = rb["expected"]
            bar = "#" * max(1, int(count / exp * 20))
            print(f"  [{lo:.1f}-{hi:.1f}]: {count:5.0f} (exp: {exp:.0f})  {bar}")

        chi2 = rb["chi2_stat"]
        pval = rb["chi2_pval"]
        if pval > 0.05:
            verdict = "CALIBRATED"
        elif pit.mean() > 0.55:
            verdict = "OVERDISPERSED (sigma too wide)"
        elif pit.mean() < 0.45:
            verdict = "UNDERDISPERSED (sigma too tight)"
        else:
            verdict = "MISCALIBRATED"
        print(f"  Chi-squared: {chi2:.2f}, p-value: {pval:.4f} -> {verdict}")


def print_yearly_trend(results: pd.DataFrame) -> None:
    """Print year-by-year CRPS comparison for all forecasters vs Naive."""
    print("\n" + "=" * 75)
    print("YEAR-BY-YEAR CRPS TREND (all forecasters vs Naive)")
    print("=" * 75)

    methods = sorted(results["pred_method"].unique())
    yearly = {}
    for method in methods:
        yearly[method] = (
            results[results["pred_method"] == method]
            .groupby("year")["crps"]
            .mean()
        )

    non_naive = [m for m in methods if m != "Naive"]
    header = f"{'Year':>6} {'Naive':>7}"
    for m in non_naive:
        header += f" {m:>9}"
    print(f"\n{header}")

    for year in sorted(yearly["Naive"].index):
        n_crps = yearly["Naive"][year]
        line = f"{year:>6} {n_crps:7.3f}"
        for m in non_naive:
            if year in yearly[m].index:
                m_crps = yearly[m][year]
                improve = (m_crps / n_crps - 1) * 100
                line += f" {improve:+8.1f}%"
            else:
                line += f" {'n/a':>9}"
        print(line)

    # Recent 5 years summary
    recent = sorted(yearly["Naive"].index)[-5:]
    if len(recent) >= 3:
        print()
        n_recent = yearly["Naive"][recent].mean()
        line = f"{'Recent 5yr':>14} {n_recent:7.3f}"
        for m in non_naive:
            m_recent = yearly[m][recent].mean()
            improve = (m_recent / n_recent - 1) * 100
            line += f" {improve:+8.1f}%"
        print(line)


def print_station_monthly(results: pd.DataFrame) -> None:
    """Print per-station monthly EMOS CRPS improvement over Naive."""
    print("\n" + "=" * 75)
    print("MONTHLY CRPS IMPROVEMENT (EMOS vs Naive, by station)")
    print("=" * 75)

    for station in sorted(results["station"].unique()):
        sub = results[results["station"] == station]
        naive_monthly = (
            sub[sub["pred_method"] == "Naive"]
            .groupby("month")["crps"]
            .mean()
        )
        emos_monthly = (
            sub[sub["pred_method"] == "EMOS"]
            .groupby("month")["crps"]
            .mean()
        )

        print(f"\n--- {station} ---")
        print(f"{'Month':>6} {'Naive':>7} {'EMOS':>7} {'Improve':>9}")
        for month in range(1, 13):
            if month not in naive_monthly.index or month not in emos_monthly.index:
                continue
            n = naive_monthly[month]
            e = emos_monthly[month]
            improve = (e / n - 1) * 100
            print(f"{month:>6} {n:7.3f} {e:7.3f} {improve:+8.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Forecaster walk-forward evaluation")
    parser.add_argument(
        "--station", type=str, default=None,
        help="Single station ICAO (default: all Phase 1 stations)",
    )
    parser.add_argument(
        "--min-train-years", type=int, default=3,
        help="Minimum training years before testing (default: 3)",
    )
    parser.add_argument(
        "--rolling-window", type=int, default=None,
        help="Rolling training window in years (default: all prior years)",
    )
    args = parser.parse_args()

    stations = [args.station] if args.station else PHASE1_STATIONS

    # Load data
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
        logger.error("No data available. Run: python scripts/download_iem_data.py --fast")
        return

    df = pd.concat(all_pairs, ignore_index=True)
    logger.info(f"Total: {len(df)} pairs, {df['year'].nunique()} years, {df['station'].nunique()} stations")

    # Walk-forward evaluation
    logger.info("Running walk-forward evaluation...")
    results = evaluate_walk_forward(
        df,
        min_train_years=args.min_train_years,
        rolling_window=args.rolling_window,
    )

    window_desc = f"rolling {args.rolling_window}yr" if args.rolling_window else "all prior years"
    print(f"\nTraining: {window_desc} | Min training: {args.min_train_years} years")

    # Reports
    summary = aggregate_results(results)
    print_comparison_table(summary)
    print_pit_summary(results)
    print_yearly_trend(results)
    print_station_monthly(results)

    print("\nDone.")


if __name__ == "__main__":
    main()
