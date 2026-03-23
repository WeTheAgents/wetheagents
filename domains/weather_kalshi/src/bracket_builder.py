"""Convert continuous temperature forecasts to Kalshi bracket probabilities.

Kalshi temperature markets use 6 mutually exclusive brackets per city:
  - 4 inner brackets of 2F width centered on the forecast
  - 2 open-ended tail brackets

Example for forecast_high=80F:
  Bracket 0: T <= 75  (tail low)
  Bracket 1: 76-77
  Bracket 2: 78-79
  Bracket 3: 80-81
  Bracket 4: 82-83
  Bracket 5: T >= 84  (tail high)

The edge comes from bias correction: if GFS systematically forecasts too warm
in July for KNYC, the Gaussian CDF shifts probability mass from upper brackets
to lower brackets, creating NO opportunities on the upper brackets.

Key formula:
  F_corrected = F_raw - mean_bias
  P(bracket [a,b]) = Phi(b; F_corrected, sigma) - Phi(a; F_corrected, sigma)
  where sigma = historical std of forecast error for this station-month
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class Bracket:
    """A single Kalshi temperature bracket."""

    index: int  # 0-5
    lower: float | None  # None for tail low
    upper: float | None  # None for tail high
    label: str  # Human-readable label

    @property
    def is_tail_low(self) -> bool:
        return self.lower is None

    @property
    def is_tail_high(self) -> bool:
        return self.upper is None


def build_brackets(
    center_temp: float,
    n_inner: int = 4,
    inner_width: int = 2,
) -> list[Bracket]:
    """Build Kalshi-style bracket structure around a center temperature.

    Args:
        center_temp: Forecast temperature to center brackets on.
        n_inner: Number of inner brackets (default 4).
        inner_width: Width of each inner bracket in degrees F (default 2).

    Returns:
        List of Bracket objects (tail_low + inner + tail_high).
    """
    # Round center to nearest even number for symmetric bracket placement
    center = round(center_temp / 2) * 2
    total_inner_width = n_inner * inner_width
    start = center - total_inner_width // 2

    brackets = []

    # Tail low
    brackets.append(Bracket(
        index=0,
        lower=None,
        upper=start,
        label=f"<= {start}",
    ))

    # Inner brackets
    for i in range(n_inner):
        lo = start + i * inner_width
        hi = lo + inner_width
        brackets.append(Bracket(
            index=i + 1,
            lower=lo,
            upper=hi,
            label=f"{lo + 1}-{hi}",
        ))

    # Tail high
    tail_start = start + total_inner_width
    brackets.append(Bracket(
        index=n_inner + 1,
        lower=tail_start,
        upper=None,
        label=f">= {tail_start + 1}",
    ))

    return brackets


def forecast_to_bracket_probs(
    forecast_temp: float,
    mean_bias: float,
    std_error: float,
    brackets: list[Bracket],
) -> dict[int, float]:
    """Convert a point forecast + error stats into bracket probabilities.

    Uses Gaussian predictive distribution:
      F_corrected = forecast_temp - mean_bias
      P(bracket) = CDF(upper) - CDF(lower)

    Args:
        forecast_temp: Raw MOS forecast temperature (F).
        mean_bias: Historical mean(forecast - observed) for this station-month.
        std_error: Historical std of forecast error for this station-month.
        brackets: List of Bracket objects defining the bracket structure.

    Returns:
        Dict mapping bracket index to probability.
    """
    corrected = forecast_temp - mean_bias
    dist = stats.norm(loc=corrected, scale=max(std_error, 0.1))

    probs = {}
    for b in brackets:
        if b.is_tail_low:
            # P(T <= upper)
            probs[b.index] = dist.cdf(b.upper + 0.5)
        elif b.is_tail_high:
            # P(T > lower)
            probs[b.index] = 1.0 - dist.cdf(b.lower + 0.5)
        else:
            # P(lower < T <= upper)
            probs[b.index] = dist.cdf(b.upper + 0.5) - dist.cdf(b.lower + 0.5)

    # Normalize to sum to 1.0 (should be very close already)
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}

    return probs


def compute_naive_probs(
    forecast_temp: float,
    std_error: float,
    brackets: list[Bracket],
) -> dict[int, float]:
    """Compute bracket probabilities WITHOUT bias correction.

    This represents what a naive forecaster (using raw MOS) would estimate.
    The difference between naive and bias-corrected probs = our edge.
    """
    return forecast_to_bracket_probs(forecast_temp, 0.0, std_error, brackets)


def compute_no_edge(
    model_probs: dict[int, float],
    naive_probs: dict[int, float],
) -> dict[int, float]:
    """Compute NO edge for each bracket.

    NO edge = naive_prob - model_prob

    Positive NO edge means the naive market is OVERPRICING this bracket
    (assigning too much probability). Buying NO is profitable.

    Negative NO edge means the naive market is UNDERPRICING this bracket.
    Buying YES might be profitable.

    In practice, we use naive_probs as a proxy for market prices, because
    Kalshi market makers likely use similar raw-forecast-based pricing.

    Args:
        model_probs: Our bias-corrected bracket probabilities.
        naive_probs: Naive (raw forecast) bracket probabilities.

    Returns:
        Dict mapping bracket index to NO edge (positive = buy NO).
    """
    edges = {}
    for idx in model_probs:
        edges[idx] = naive_probs.get(idx, 0.0) - model_probs[idx]
    return edges


def resolve_bracket(observed_temp: float, brackets: list[Bracket]) -> int | None:
    """Determine which bracket an observed temperature falls into.

    Uses the same +0.5 continuity correction boundaries as the CDF integration
    to ensure consistency between pricing and resolution.

    For integer temperatures this is equivalent to the intuitive assignment:
      - Tail low: T <= upper_bound
      - Inner [lo, hi]: lo+1 <= T <= hi  (label says "lo+1 - hi")
      - Tail high: T >= lower_bound+1

    For fractional temperatures, uses midpoint boundaries (e.g., 72.5)
    matching the CDF integration in forecast_to_bracket_probs.
    """
    for b in brackets:
        if b.is_tail_low:
            if observed_temp < b.upper + 0.5:
                return b.index
        elif b.is_tail_high:
            if observed_temp >= b.lower + 0.5:
                return b.index
        else:
            if b.lower + 0.5 <= observed_temp < b.upper + 0.5:
                return b.index
    return None


def evaluate_bracket_accuracy(
    forecast_temp: float,
    observed_temp: float,
    mean_bias: float,
    std_error: float,
    center_temp: float | None = None,
) -> dict:
    """Evaluate bracket prediction accuracy for a single day.

    Determines which bracket the observed temp falls in, and whether
    bias correction would have improved the prediction.

    Args:
        forecast_temp: Raw MOS forecast.
        observed_temp: Actual observed temperature.
        mean_bias: Bias correction for this station-month.
        std_error: Error std for this station-month.
        center_temp: Center for bracket construction (default: forecast_temp).

    Returns:
        Dict with evaluation metrics.
    """
    if center_temp is None:
        center_temp = forecast_temp

    brackets = build_brackets(center_temp)

    # Find which bracket the observed temp actually fell in
    # Uses same +0.5 boundaries as CDF integration for consistency
    actual_bracket = resolve_bracket(observed_temp, brackets)

    # Compute probabilities
    naive_probs = compute_naive_probs(forecast_temp, std_error, brackets)
    corrected_probs = forecast_to_bracket_probs(
        forecast_temp, mean_bias, std_error, brackets
    )

    # Find predicted bracket (highest probability)
    naive_predicted = max(naive_probs, key=naive_probs.get)
    corrected_predicted = max(corrected_probs, key=corrected_probs.get)

    # Compute NO edges
    edges = compute_no_edge(corrected_probs, naive_probs)

    return {
        "forecast_temp": forecast_temp,
        "observed_temp": observed_temp,
        "actual_bracket": actual_bracket,
        "naive_predicted_bracket": naive_predicted,
        "corrected_predicted_bracket": corrected_predicted,
        "naive_hit": naive_predicted == actual_bracket,
        "corrected_hit": corrected_predicted == actual_bracket,
        "naive_prob_actual": naive_probs.get(actual_bracket, 0.0),
        "corrected_prob_actual": corrected_probs.get(actual_bracket, 0.0),
        "max_no_edge": max(edges.values()),
        "max_no_edge_bracket": max(edges, key=edges.get),
        "actual_bracket_no_edge": edges.get(actual_bracket, 0.0),
    }
