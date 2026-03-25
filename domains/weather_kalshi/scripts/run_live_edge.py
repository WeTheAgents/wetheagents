"""Live edge detection: ensemble model vs Polymarket bracket prices.

Compares our EnsembleForecaster's bracket probabilities to Polymarket's
market prices to identify mispriced brackets in real-time.

Pipeline:
  1. Fetch Polymarket bracket prices for upcoming dates
  2. Fetch GEFS ensemble forecast from Open-Meteo
  3. Compute model bracket probabilities (ensemble sigma)
  4. Compare model vs market, flag edges > threshold

Requires VPN for Polymarket API access (DNS blocks gamma-api.polymarket.com).

Usage:
    python -m scripts.run_live_edge
    python -m scripts.run_live_edge --station KLGA --threshold 0.05
    python -m scripts.run_live_edge --cached   # use previously downloaded market data
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bracket_builder import Bracket, brackets_from_polymarket, forecast_to_bracket_probs
from src.data_loader import load_pairs
from src.forecaster import CRPSigmaForecaster, EnsembleForecaster
from src.nbm_client import fetch_nbm_batch, save_nbm_snapshot
from src.openmeteo_client import fetch_ensemble_forecast_sync, save_ensemble_snapshot
from src.stations import POLYMARKET_STATIONS, get_station

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def run_edge_analysis(
    station_icao: str,
    market_events: list,
    edge_threshold: float = 0.05,
) -> pd.DataFrame:
    """Compare model bracket probs to market prices for one station.

    Returns DataFrame with edge analysis per bracket.
    """
    station = get_station(station_icao)

    # Load IEM pairs for historical sigma calibration
    try:
        pairs = load_pairs(station)
    except FileNotFoundError:
        logger.error(f"No IEM data for {station_icao}. Run download_iem_data.py first.")
        return pd.DataFrame()

    # Fit forecasters
    ensemble_f = EnsembleForecaster()
    ensemble_f.fit(pairs)

    crps_f = CRPSigmaForecaster()
    crps_f.fit(pairs)

    # Fetch live ensemble
    forecasts = fetch_ensemble_forecast_sync(
        station.lat, station.lon, station=station_icao,
        forecast_days=7, past_days=2,
    )
    save_ensemble_snapshot(forecasts, station_icao)

    # Build lookup: date -> ensemble forecast
    ens_by_date = {f.target_date: f for f in forecasts}

    # Fetch NBM percentiles (priority source)
    nbm_by_date = {}
    try:
        for days_ahead in range(0, 4):
            nbm_forecasts = fetch_nbm_batch(
                [station_icao], days_ahead=days_ahead,
            )
            for nbf in nbm_forecasts:
                nbm_by_date[nbf.target_date] = nbf
                save_nbm_snapshot([nbf], station_icao)
    except Exception as e:
        logger.warning(f"NBM fetch failed for {station_icao}: {e}")

    rows = []
    for event in market_events:
        if event.station_icao != station_icao:
            continue

        target_date = event.market_date
        nbm = nbm_by_date.get(target_date)
        ens = ens_by_date.get(target_date)

        market_brackets = brackets_from_polymarket(event)

        if nbm is not None:
            # Priority 1: NBM empirical distribution (pre-calibrated, 200+ members)
            sigma = nbm.sigma
            mu = nbm.median
            model_probs = forecast_to_bracket_probs(
                mu, 0.0, sigma, market_brackets,
                distribution="empirical",
                percentiles=nbm.percentiles,
            )
            sigma_source = "nbm"
        elif ens is not None:
            # Priority 2: Ensemble Gaussian (single model, 30 members)
            sigma = max(ens.spread * ensemble_f._cal_factor, 0.5)
            mu = ens.mean
            model_probs = forecast_to_bracket_probs(mu, 0.0, sigma, market_brackets)
            sigma_source = "ensemble"
        else:
            # Priority 3: Historical sigma
            month = target_date.month
            pred = crps_f.predict(0, station_icao, month)
            sigma = pred.sigma
            mu = _estimate_mu_from_brackets(market_brackets)
            model_probs = forecast_to_bracket_probs(mu, 0.0, sigma, market_brackets)
            sigma_source = "historical"

        for b in market_brackets:
            market_yes = next(
                (pb.yes_price for pb in event.brackets
                 if (pb.lower == b.lower and pb.upper == b.upper)),
                0.0,
            )
            model_prob = model_probs.get(b.index, 0.0)
            edge = model_prob - market_yes

            rows.append({
                "station": station_icao,
                "date": target_date,
                "bracket": b.label,
                "lower": b.lower,
                "upper": b.upper,
                "market_yes": market_yes,
                "model_prob": model_prob,
                "edge": edge,
                "abs_edge": abs(edge),
                "direction": "BUY YES" if edge > 0 else "BUY NO",
                "sigma": sigma,
                "sigma_source": sigma_source,
                "mu": mu,
                "ens_spread": ens.spread if ens else None,
                "ens_n_members": ens.n_members if ens else None,
                "nbm_sigma": nbm.sigma if nbm else None,
                "nbm_median": nbm.median if nbm else None,
            })

    return pd.DataFrame(rows)


def _estimate_mu_from_brackets(brackets: list[Bracket]) -> float:
    """Estimate forecast mu from bracket midpoints (when no ensemble available)."""
    inner = [b for b in brackets if b.lower is not None and b.upper is not None]
    if inner:
        midpoints = [(b.lower + b.upper) / 2 for b in inner]
        return float(np.median(midpoints))
    return 60.0


def print_edge_report(edges: pd.DataFrame, threshold: float) -> None:
    """Print formatted edge analysis."""
    if edges.empty:
        print("No edge data available.")
        return

    for (station, target_date), group in edges.groupby(["station", "date"]):
        sigma_source = group.iloc[0]["sigma_source"]
        sigma = group.iloc[0]["sigma"]
        mu = group.iloc[0]["mu"]
        ens_spread = group.iloc[0]["ens_spread"]

        nbm_sigma = group.iloc[0].get("nbm_sigma")
        nbm_median = group.iloc[0].get("nbm_median")

        print(f"\n{'=' * 70}")
        print(f"{station} — {target_date}  |  mu={mu:.1f}F  sigma={sigma:.2f}F ({sigma_source})")
        if sigma_source == "nbm" and nbm_sigma is not None:
            print(f"  NBM: sigma={nbm_sigma:.2f}F, median={nbm_median:.1f}F")
        if ens_spread is not None:
            print(f"  Ensemble: spread={ens_spread:.2f}F, {group.iloc[0]['ens_n_members']} members")
        print(f"{'=' * 70}")

        print(f"{'Bracket':>12} {'Market':>8} {'Model':>8} {'Edge':>8} {'Signal':>10}")
        print("-" * 50)

        for _, row in group.sort_values("lower", na_position="first").iterrows():
            signal = ""
            if abs(row["edge"]) >= threshold:
                signal = row["direction"]
            print(
                f"{row['bracket']:>12} "
                f"{row['market_yes']:>7.1%} "
                f"{row['model_prob']:>7.1%} "
                f"{row['edge']:>+7.1%} "
                f"{signal:>10}"
            )

    # Summary
    signals = edges[edges["abs_edge"] >= threshold]
    if not signals.empty:
        print(f"\n--- SIGNALS (|edge| >= {threshold:.0%}) ---")
        for _, s in signals.sort_values("abs_edge", ascending=False).iterrows():
            print(
                f"  {s['station']} {s['date']} {s['bracket']:>12}: "
                f"edge={s['edge']:+.1%} → {s['direction']}  "
                f"(market={s['market_yes']:.1%}, model={s['model_prob']:.1%})"
            )
    else:
        print(f"\nNo signals above {threshold:.0%} threshold.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live edge detection vs Polymarket")
    parser.add_argument("--station", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--cached", action="store_true", help="Use cached market data")
    parser.add_argument("--days", type=int, default=3, help="Days ahead to analyze")
    args = parser.parse_args()

    stations = [args.station] if args.station else POLYMARKET_STATIONS

    # Load market data
    if args.cached:
        from src.polymarket_client import load_weather_data
        try:
            market_df = load_weather_data()
            logger.info(f"Loaded cached market data: {len(market_df)} rows")
        except FileNotFoundError:
            logger.error("No cached data. Run: python -m scripts.download_polymarket_data --all --last 7")
            return

        # Reconstruct events from DataFrame for bracket structure
        from src.polymarket_client import PolymarketBracket, PolymarketWeatherEvent
        events = []
        for (slug, station_icao, market_date), group in market_df.groupby(
            ["event_slug", "station", "market_date"]
        ):
            brackets = []
            for _, row in group.sort_values("bracket_index").iterrows():
                brackets.append(PolymarketBracket(
                    market_id=row.get("market_id", ""),
                    condition_id="",
                    clob_token_id_yes=row.get("clob_token_id_yes", ""),
                    clob_token_id_no="",
                    lower=row["lower"] if pd.notna(row["lower"]) else None,
                    upper=row["upper"] if pd.notna(row["upper"]) else None,
                    label=row["label"],
                    yes_price=row["yes_price"],
                    no_price=row.get("no_price", 1.0 - row["yes_price"]),
                ))
            events.append(PolymarketWeatherEvent(
                event_id="",
                slug=slug,
                title="",
                city_slug=row.get("city_slug", ""),
                station_icao=station_icao,
                market_date=market_date if isinstance(market_date, date) else pd.Timestamp(market_date).date(),
                brackets=brackets,
                volume=row.get("volume", 0),
            ))
    else:
        # Fetch live from Polymarket (requires VPN)
        from src.polymarket_client import fetch_weather_events

        today = date.today()
        events = []
        for icao in stations:
            station = get_station(icao)
            city_slug = station.polymarket_city_slug
            if not city_slug:
                continue
            logger.info(f"Fetching Polymarket events for {city_slug}...")
            city_events = fetch_weather_events(
                city_slug, today, today + timedelta(days=args.days)
            )
            events.extend(city_events)

    if not events:
        logger.error("No market events. Use --cached or ensure VPN is on for live data.")
        return

    logger.info(f"Analyzing {len(events)} market events...")

    # Run edge analysis
    all_edges = []
    for icao in stations:
        edges = run_edge_analysis(icao, events, args.threshold)
        if not edges.empty:
            all_edges.append(edges)

    if all_edges:
        combined = pd.concat(all_edges, ignore_index=True)
        print_edge_report(combined, args.threshold)
    else:
        print("No edge data produced. Check data availability.")

    print("\nDone.")


if __name__ == "__main__":
    main()
