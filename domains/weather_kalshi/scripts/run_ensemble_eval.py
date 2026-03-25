"""Ensemble forecaster evaluation and live sigma comparison.

Two modes:
  1. Walk-forward eval: compare EnsembleForecaster (fallback mode) to baselines
     on 22 years of IEM data. Verifies it matches CRPSigma when no ensemble
     context is available.

  2. Live comparison: fetch today's GEFS ensemble spread from Open-Meteo and
     compare day-specific sigma to historical monthly sigma. Shows the
     sharpening effect that ensemble spread provides.

Usage:
    python -m scripts.run_ensemble_eval
    python -m scripts.run_ensemble_eval --station KLGA
    python -m scripts.run_ensemble_eval --live-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bracket_builder import build_brackets, forecast_to_bracket_probs
from src.data_loader import load_pairs
from src.forecaster import (
    CRPSigmaForecaster,
    EnsembleForecaster,
    Forecaster,
    NaiveForecaster,
)
from src.openmeteo_client import (
    ensemble_to_dataframe,
    fetch_ensemble_forecast_sync,
    save_ensemble_snapshot,
)
from src.scoring import (
    coverage_probability,
    crps_gaussian,
    crps_mean,
    pit_values,
    sharpness,
)
from src.stations import POLYMARKET_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIN_SAMPLES_YEAR = 300


def evaluate_walk_forward(
    pairs: pd.DataFrame,
    min_train_years: int = 3,
) -> pd.DataFrame:
    """Walk-forward evaluation: Ensemble (fallback) vs CRPSigma vs Naive."""
    years = sorted(pairs["year"].unique())
    all_results = []

    forecasters_cls = [
        NaiveForecaster,
        CRPSigmaForecaster,
        EnsembleForecaster,
    ]

    for test_year in years[min_train_years:]:
        train = pairs[pairs["year"] < test_year]
        test = pairs[pairs["year"] == test_year]

        if len(train) < MIN_SAMPLES_YEAR or len(test) == 0:
            continue

        for cls in forecasters_cls:
            forecaster = cls()
            forecaster.fit(train)
            preds = forecaster.predict_batch(test)

            preds["crps"] = crps_gaussian(
                preds["observed_high"].values,
                preds["pred_mu"].values,
                preds["pred_sigma"].values,
            )
            all_results.append(
                preds[["station", "date", "year", "month",
                       "forecast_high", "observed_high",
                       "pred_mu", "pred_sigma", "pred_method", "crps"]]
            )

        logger.info(f"  year {test_year}: {len(test)} test days")

    return pd.concat(all_results, ignore_index=True)


def print_walk_forward_summary(results: pd.DataFrame) -> None:
    """Print walk-forward comparison table."""
    print("=" * 70)
    print("WALK-FORWARD EVALUATION — Ensemble vs CRPSigma vs Naive")
    print("=" * 70)

    naive_crps = {}
    for _, row in results[results["pred_method"] == "Naive"].groupby("station").agg(
        crps=("crps", "mean")
    ).iterrows():
        naive_crps[_] = row["crps"]

    # Overall summary
    for method in ["Naive", "CRPSigma", "Ensemble"]:
        sub = results[results["pred_method"] == method]
        if sub.empty:
            continue
        obs = sub["observed_high"].values
        mu = sub["pred_mu"].values
        sigma = sub["pred_sigma"].values
        c = crps_mean(obs, mu, sigma)
        naive_c = crps_mean(
            results[results["pred_method"] == "Naive"]["observed_high"].values,
            results[results["pred_method"] == "Naive"]["pred_mu"].values,
            results[results["pred_method"] == "Naive"]["pred_sigma"].values,
        )
        vs = "(baseline)" if method == "Naive" else f"{(c / naive_c - 1) * 100:+.2f}%"
        print(
            f"  {method:<12} CRPS={c:.3f}  "
            f"MAE={np.abs(mu - obs).mean():.2f}  "
            f"Cov90={coverage_probability(obs, mu, sigma, 0.9) * 100:.1f}%  "
            f"Sharp={sharpness(sigma):.2f}  "
            f"{vs}"
        )

    print("\nNote: Ensemble without live data = CRPSigma (same fallback sigma)")


def run_live_comparison(stations: list[str]) -> None:
    """Fetch live ensemble data and compare sigma to historical."""
    print("\n" + "=" * 70)
    print("LIVE ENSEMBLE SPREAD vs HISTORICAL SIGMA")
    print("=" * 70)

    for icao in stations:
        station = get_station(icao)

        # Fetch ensemble
        forecasts = fetch_ensemble_forecast_sync(
            station.lat, station.lon, station=icao,
            forecast_days=7, past_days=3,
        )
        save_ensemble_snapshot(forecasts, icao)

        if not forecasts:
            print(f"\n{icao}: no ensemble data available")
            continue

        # Load historical data to get CRPSigma baseline
        try:
            pairs = load_pairs(station)
        except FileNotFoundError:
            print(f"\n{icao}: no IEM data. Run download_iem_data.py first.")
            continue

        crps_f = CRPSigmaForecaster()
        crps_f.fit(pairs)

        ensemble_f = EnsembleForecaster()
        ensemble_f.fit(pairs)

        print(f"\n--- {icao} ({station.name}) ---")
        print(f"{'Date':>12} {'Ens Mean':>9} {'Spread':>8} {'Ens Sig':>7} {'Hist Sig':>8} {'Ratio':>7}")

        for fc in forecasts:
            month = fc.target_date.month

            # Historical sigma from CRPSigma
            hist_pred = crps_f.predict(fc.mean, icao, month)
            hist_sigma = hist_pred.sigma

            # Ensemble sigma (day-specific)
            ens_pred = ensemble_f.predict_day(
                fc.mean, icao, month,
                forecast_date=fc.target_date,
                context={"ensemble_spread": fc.spread},
            )
            ens_sigma = ens_pred.sigma

            ratio = hist_sigma / ens_sigma if ens_sigma > 0 else 0

            print(
                f"{fc.target_date!s:>12} "
                f"{fc.mean:>8.1f}F "
                f"{fc.spread:>7.2f}F "
                f"{ens_sigma:>6.2f}F "
                f"{hist_sigma:>6.2f}F "
                f"{ratio:>6.1f}x"
            )

        # Show bracket probability comparison for the nearest forecast day
        nearest = forecasts[0]
        for fc in forecasts:
            if fc.target_date >= pd.Timestamp.now().date():
                nearest = fc
                break

        print(f"\n  Bracket probs for {nearest.target_date} (forecast={nearest.mean:.0f}F):")
        brackets = build_brackets(nearest.mean, n_inner=4, inner_width=2)

        hist_sigma = crps_f.predict(nearest.mean, icao, nearest.target_date.month).sigma
        ens_sigma = max(nearest.spread * ensemble_f._cal_factor, 0.5)

        g_probs = forecast_to_bracket_probs(nearest.mean, 0.0, hist_sigma, brackets)
        e_probs = forecast_to_bracket_probs(nearest.mean, 0.0, ens_sigma, brackets)

        print(f"  {'Bracket':>10} {'Historic':>9} {'Ensemble':>9} {'Diff':>7}")
        for b in brackets:
            diff = e_probs[b.index] - g_probs[b.index]
            marker = " <-- sharper" if b.index == max(e_probs, key=e_probs.get) else ""
            print(
                f"  {b.label:>10} "
                f"{g_probs[b.index]:>8.1%} "
                f"{e_probs[b.index]:>8.1%} "
                f"{diff:>+6.1%}{marker}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensemble forecaster evaluation")
    parser.add_argument(
        "--station", type=str, default=None,
        help="Single station ICAO (default: all Polymarket stations)",
    )
    parser.add_argument(
        "--live-only", action="store_true",
        help="Skip walk-forward eval, only run live comparison",
    )
    parser.add_argument(
        "--min-train-years", type=int, default=3,
    )
    args = parser.parse_args()

    stations = [args.station] if args.station else POLYMARKET_STATIONS

    # Walk-forward evaluation
    if not args.live_only:
        all_pairs = []
        for icao in stations:
            try:
                pairs = load_pairs(get_station(icao))
                all_pairs.append(pairs)
                logger.info(f"Loaded {len(pairs)} pairs for {icao}")
            except FileNotFoundError:
                logger.warning(f"No data for {icao}. Run download_iem_data.py first.")

        if all_pairs:
            df = pd.concat(all_pairs, ignore_index=True)
            logger.info(f"Total: {len(df)} pairs, {df['year'].nunique()} years")

            results = evaluate_walk_forward(df, args.min_train_years)
            print_walk_forward_summary(results)

    # Live comparison
    run_live_comparison(stations)
    print("\nDone.")


if __name__ == "__main__":
    main()
