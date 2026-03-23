"""Compute systematic forecast bias profiles for weather stations.

Bias profiles quantify how MOS forecasts systematically deviate from observed
temperatures, segmented by station, month, season, and year. These biases are
the foundation for mechanical edge detection in Kalshi temperature markets.

Key insight from research: GFS has a documented cold bias of 1.5-1.8C at 00Z
(NCEP Office Note 520). IBM showed bias correction reduces MAE by ~50%.
Station-specific and seasonal biases provide the primary trading signal.

Trading signal: if prob_forecast_too_high > 0.5 consistently for a station-month,
this creates a NO edge on upper temperature brackets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BiasProfile:
    """Statistical summary of forecast bias for a group."""

    group: dict  # Grouping keys (station, month, season, etc.)
    count: int
    mean_bias: float  # Mean(forecast - observed), positive = forecast too warm
    median_bias: float
    std_bias: float
    rmse: float  # Root mean squared error
    mae: float  # Mean absolute error
    prob_too_high: float  # Fraction of times forecast > observed
    p25_error: float  # 25th percentile of error
    p75_error: float  # 75th percentile of error


def compute_bias_profile(
    df: pd.DataFrame,
    groupby_cols: list[str],
    error_col: str = "error_high",
) -> pd.DataFrame:
    """Compute bias statistics for each group.

    Args:
        df: Forecast-obs pairs (from data_loader.build_forecast_obs_pairs).
        groupby_cols: Columns to group by (e.g., ["station", "month"]).
        error_col: Which error column to analyze ("error_high" or "error_low").

    Returns:
        DataFrame with bias statistics per group.
    """
    results = []
    for group_keys, group_df in df.groupby(groupby_cols):
        if isinstance(group_keys, tuple):
            group_dict = dict(zip(groupby_cols, group_keys))
        else:
            group_dict = {groupby_cols[0]: group_keys}

        errors = group_df[error_col].dropna()
        if len(errors) < 10:
            continue

        results.append({
            **group_dict,
            "count": len(errors),
            "mean_bias": errors.mean(),
            "median_bias": errors.median(),
            "std_bias": errors.std(),
            "rmse": np.sqrt((errors**2).mean()),
            "mae": errors.abs().mean(),
            "prob_too_high": (errors > 0).mean(),
            "p25_error": errors.quantile(0.25),
            "p75_error": errors.quantile(0.75),
        })

    return pd.DataFrame(results)


def compute_monthly_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Compute bias profile by station and month.

    This is the primary trading signal. If a station-month consistently
    shows prob_too_high > 0.55, there is a mechanical NO edge on upper brackets.
    """
    return compute_bias_profile(df, ["station", "month"], "error_high")


def compute_seasonal_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Compute bias profile by station and season (DJF, MAM, JJA, SON)."""
    return compute_bias_profile(df, ["station", "season"], "error_high")


def compute_annual_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Compute bias profile by station and year.

    Used to check bias stability over time. A bias present in 18/20 years
    is much more tradeable than one present in 12/20.
    """
    return compute_bias_profile(df, ["station", "year"], "error_high")


def compute_overall_bias(df: pd.DataFrame) -> pd.DataFrame:
    """Compute station-level overall bias."""
    return compute_bias_profile(df, ["station"], "error_high")


def bias_stability_test(
    df: pd.DataFrame,
    station: str,
    month: int,
) -> dict:
    """Walk-forward test: is the bias for this station-month stable over time?

    For each year Y, compute the bias using only data from years < Y,
    then check if the predicted direction matches the actual error in year Y.

    Args:
        df: Forecast-obs pairs.
        station: ICAO code.
        month: Calendar month (1-12).

    Returns:
        Dict with stability metrics: hit_rate, mean_walk_forward_bias, years_tested.
    """
    subset = df[(df["station"] == station) & (df["month"] == month)].copy()
    years = sorted(subset["year"].unique())

    if len(years) < 5:
        return {"hit_rate": np.nan, "years_tested": 0}

    hits = 0
    total = 0
    wf_biases = []

    for test_year in years[3:]:  # Need at least 3 years of training data
        train = subset[subset["year"] < test_year]
        test = subset[subset["year"] == test_year]

        if len(train) < 30 or len(test) < 20:
            continue

        train_bias = train["error_high"].mean()

        # Skip years where training bias is too small to be meaningful
        if abs(train_bias) < 0.5:
            continue

        test_direction = (test["error_high"].mean() > 0)
        predicted_direction = (train_bias > 0)

        if predicted_direction == test_direction:
            hits += 1
        total += 1
        wf_biases.append(train_bias)

    return {
        "hit_rate": hits / total if total > 0 else np.nan,
        "mean_walk_forward_bias": np.mean(wf_biases) if wf_biases else np.nan,
        "years_tested": total,
        "direction_consistency": hits,
    }


def generate_bias_report(df: pd.DataFrame) -> str:
    """Generate a human-readable bias analysis report.

    Returns:
        Formatted string report.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("WEATHER FORECAST BIAS ANALYSIS REPORT")
    lines.append("=" * 70)

    # Overall station bias
    overall = compute_overall_bias(df)
    lines.append("\n--- Overall Station Bias (High Temperature) ---")
    for _, row in overall.iterrows():
        direction = "WARM" if row["mean_bias"] > 0 else "COLD"
        lines.append(
            f"  {row['station']}: {direction} bias {row['mean_bias']:+.2f}F "
            f"(MAE={row['mae']:.2f}F, RMSE={row['rmse']:.2f}F, "
            f"n={row['count']:.0f}, P(too high)={row['prob_too_high']:.1%})"
        )

    # Monthly bias
    monthly = compute_monthly_bias(df)
    lines.append("\n--- Monthly Bias (High Temperature) ---")
    month_names = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    for station in sorted(monthly["station"].unique()):
        lines.append(f"\n  {station}:")
        station_monthly = monthly[monthly["station"] == station].sort_values("month")
        for _, row in station_monthly.iterrows():
            m = int(row["month"])
            direction = "WARM" if row["mean_bias"] > 0 else "COLD"
            # Flag strong directional signals (potential trading signal)
            signal = ""
            if row["prob_too_high"] > 0.58:
                signal = " ** NO-HIGH SIGNAL **"
            elif row["prob_too_high"] < 0.42:
                signal = " ** NO-LOW SIGNAL **"

            lines.append(
                f"    {month_names[m]:>3}: {direction:>4} {row['mean_bias']:+.2f}F "
                f"(MAE={row['mae']:.2f}, std={row['std_bias']:.2f}, "
                f"P(high)={row['prob_too_high']:.1%}, n={row['count']:.0f}){signal}"
            )

    # Seasonal bias
    seasonal = compute_seasonal_bias(df)
    lines.append("\n--- Seasonal Bias ---")
    for station in sorted(seasonal["station"].unique()):
        lines.append(f"\n  {station}:")
        s_rows = seasonal[seasonal["station"] == station]
        for _, row in s_rows.iterrows():
            lines.append(
                f"    {row['season']}: {row['mean_bias']:+.2f}F "
                f"(MAE={row['mae']:.2f}, P(high)={row['prob_too_high']:.1%})"
            )

    # Stability test for promising station-months
    lines.append("\n--- Bias Stability (Walk-Forward Direction Test) ---")
    promising = monthly[
        (monthly["prob_too_high"] > 0.55) | (monthly["prob_too_high"] < 0.45)
    ]
    for _, row in promising.iterrows():
        stability = bias_stability_test(
            df, row["station"], int(row["month"])
        )
        if stability["years_tested"] > 0:
            lines.append(
                f"  {row['station']} {month_names[int(row['month'])]}: "
                f"direction hit rate={stability['hit_rate']:.1%} "
                f"({stability['direction_consistency']}/{stability['years_tested']} years)"
            )

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)
