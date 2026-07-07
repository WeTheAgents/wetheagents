"""Proper scoring rules for Gaussian probabilistic temperature forecasts.

Implements CRPS (the primary optimization target for EMOS), PIT diagnostics
for calibration assessment, coverage checks, and sharpness measurement.

All functions are vectorized over numpy arrays for batch evaluation.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

# Floor to prevent degenerate zero-variance distributions
_SIGMA_FLOOR = 0.01


def _safe_sigma(sigma: np.ndarray) -> np.ndarray:
    """Clamp sigma to a positive floor."""
    return np.maximum(np.asarray(sigma, dtype=float), _SIGMA_FLOOR)


def crps_gaussian(
    observed: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
) -> np.ndarray:
    """Closed-form CRPS for a Gaussian predictive distribution.

    CRPS = sigma * [z*(2*Phi(z) - 1) + 2*phi(z) - 1/sqrt(pi)]
    where z = (observed - mu) / sigma.

    Reference: Gneiting & Raftery (2007), eq. 21.

    Returns array of CRPS values (lower is better), same shape as inputs.
    """
    observed = np.asarray(observed, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sigma = _safe_sigma(sigma)

    z = (observed - mu) / sigma
    crps = sigma * (
        z * (2.0 * stats.norm.cdf(z) - 1.0)
        + 2.0 * stats.norm.pdf(z)
        - 1.0 / np.sqrt(np.pi)
    )
    return crps


def crps_mean(
    observed: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
) -> float:
    """Mean CRPS over a dataset. Primary metric for forecaster comparison."""
    return float(np.mean(crps_gaussian(observed, mu, sigma)))


def pit_values(
    observed: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
) -> np.ndarray:
    """Probability Integral Transform values for calibration assessment.

    PIT = Phi((observed - mu) / sigma).
    For a perfectly calibrated Gaussian, PIT ~ Uniform[0, 1].
    """
    observed = np.asarray(observed, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sigma = _safe_sigma(sigma)

    z = (observed - mu) / sigma
    return stats.norm.cdf(z)


def reliability_bins(
    pit: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """Bin PIT values for calibration histogram.

    For a calibrated forecast, each bin should contain ~len(pit)/n_bins obs.

    Returns dict with: bin_edges, counts, expected, chi2_stat, chi2_pval.
    """
    pit = np.asarray(pit, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    counts, _ = np.histogram(pit, bins=edges)
    expected = len(pit) / n_bins

    # Chi-squared test for uniformity
    chi2_stat = float(np.sum((counts - expected) ** 2 / expected))
    chi2_pval = float(1.0 - stats.chi2.cdf(chi2_stat, df=n_bins - 1))

    return {
        "bin_edges": edges,
        "counts": counts,
        "expected": expected,
        "chi2_stat": chi2_stat,
        "chi2_pval": chi2_pval,
    }


def coverage_probability(
    observed: np.ndarray,
    mu: np.ndarray,
    sigma: np.ndarray,
    level: float = 0.9,
) -> float:
    """Fraction of observations within the prediction interval.

    For a calibrated Gaussian at level=0.9, coverage should be ~0.9.
    """
    observed = np.asarray(observed, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sigma = _safe_sigma(sigma)

    z_crit = stats.norm.ppf((1.0 + level) / 2.0)
    lower = mu - z_crit * sigma
    upper = mu + z_crit * sigma
    inside = (observed >= lower) & (observed <= upper)
    return float(np.mean(inside))


def sharpness(sigma: np.ndarray) -> float:
    """Mean predictive standard deviation. Lower = sharper = better (given calibration)."""
    return float(np.mean(np.asarray(sigma, dtype=float)))


def crps_empirical(
    observed: np.ndarray,
    ensemble: np.ndarray,
) -> np.ndarray:
    """CRPS for empirical (ensemble) forecasts.

    Uses the standard representation:
        CRPS = E|X - y| - 0.5 * E|X - X'|
    where X, X' are independent draws from the ensemble.

    Args:
        observed: shape (n,) — observed values.
        ensemble: shape (n, m) — m ensemble members for each of n days.

    Returns:
        CRPS per observation, shape (n,).
    """
    observed = np.asarray(observed, dtype=float)
    ensemble = np.asarray(ensemble, dtype=float)

    if ensemble.ndim == 1:
        raise ValueError("ensemble must be 2D: (n_days, n_members)")

    n, m = ensemble.shape

    # Term 1: E|X - y|
    abs_diff = np.abs(ensemble - observed[:, np.newaxis])  # (n, m)
    term1 = abs_diff.mean(axis=1)  # (n,)

    # Term 2: E|X - X'| — computed efficiently via sorted ensemble
    sorted_ens = np.sort(ensemble, axis=1)  # (n, m)
    # For sorted values: E|X-X'| = 2/(m^2) * sum_i (2i - m - 1) * x_{(i)}
    weights = 2.0 * np.arange(1, m + 1) - m - 1.0  # (m,)
    term2 = (sorted_ens * weights[np.newaxis, :]).sum(axis=1) / (m * m)

    return term1 - term2


# --- Binary probability scores (wing-ladder / market-comparison metrics) ---

_P_EPS = 1e-6


def log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Per-row binary log-loss (natural log). Probabilities are clipped to
    [1e-6, 1-1e-6] so a confidently-wrong 0/1 stays finite."""
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), _P_EPS, 1.0 - _P_EPS)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def brier(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Per-row Brier score (squared probability error)."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return (p - y) ** 2


def reliability_table(
    y: np.ndarray,
    p: np.ndarray,
    bins: np.ndarray | list[float],
) -> list[dict]:
    """Reliability curve on predicted-probability bins.

    Returns one dict per non-empty bin: predicted mean, realized rate, count.
    Pass tail-focused bins (e.g. [0, .02, .05, .08, .12, .15]) to inspect the
    wing zone specifically.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.asarray(bins, dtype=float)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        m = (p >= lo) & (p < hi)
        if m.sum() == 0:
            continue
        out.append({
            "bin": f"[{lo:.3f},{hi:.3f})",
            "n": int(m.sum()),
            "pred_mean": float(p[m].mean()),
            "realized": float(y[m].mean()),
        })
    return out
