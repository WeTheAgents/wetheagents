"""Derive match probabilities from Poisson λ parameters.

Given λ_home (expected home goals) and λ_away (expected away goals),
compute probabilities for all standard football betting markets:
  - 1X2 (home win, draw, away win)
  - Over/Under (2.5, 1.5, 3.5)
  - Asian Handicap (-0.5, -1.0, -1.5, -2.5)
  - Correct score grid

Supports both independent and bivariate Poisson (Karlis & Ntzoufras, 2003).
Bivariate Poisson models positive goal correlation via a shared component ρ,
improving draw estimation.

Usage:
    from src.markets import match_probabilities

    probs = match_probabilities(1.65, 1.20)           # independent
    probs = match_probabilities(1.65, 1.20, rho=0.12) # bivariate
"""

import logging
from math import factorial

import numpy as np
from scipy.stats import poisson

logger = logging.getLogger(__name__)

MAX_GOALS = 8  # truncate Poisson at 8 goals per team (P(>8) < 0.001 for λ<4)

# Precompute factorials for bivariate PMF (0! through 8!)
_FACTORIALS = np.array([factorial(k) for k in range(MAX_GOALS + 1)], dtype=np.float64)


def score_grid(lambda_home: float, lambda_away: float) -> np.ndarray:
    """Compute probability grid P(home=i, away=j) for i,j in [0, MAX_GOALS].

    Independent Poisson: P(H=i, A=j) = P_pois(i, λ_h) × P_pois(j, λ_a).

    Returns (MAX_GOALS+1, MAX_GOALS+1) array.
    """
    home_probs = poisson.pmf(np.arange(MAX_GOALS + 1), lambda_home)
    away_probs = poisson.pmf(np.arange(MAX_GOALS + 1), lambda_away)
    return np.outer(home_probs, away_probs)


def bivariate_score_grid(
    lambda_home: float,
    lambda_away: float,
    rho: float = 0.0,
) -> np.ndarray:
    """Compute bivariate Poisson probability grid (Karlis & Ntzoufras, 2003).

    Models goal correlation via a shared Poisson component:
        X₁ ~ Poi(λ₁), X₂ ~ Poi(λ₂), X₃ ~ Poi(ρ)  — independent
        Home = X₁ + X₃,  Away = X₂ + X₃
        λ₁ = λ_home - ρ,  λ₂ = λ_away - ρ

    P(X=x, Y=y) = exp(-(λ₁+λ₂+ρ)) × Σ_{k=0}^{min(x,y)} [
        λ₁^(x-k) × λ₂^(y-k) × ρ^k / ((x-k)! × (y-k)! × k!)
    ]

    When rho=0, delegates to score_grid() for exact backward compatibility.

    Args:
        lambda_home: expected home goals (λ_home = λ₁ + ρ)
        lambda_away: expected away goals (λ_away = λ₂ + ρ)
        rho: correlation parameter (covariance of home/away goals). Must be ≥ 0.

    Returns:
        (MAX_GOALS+1, MAX_GOALS+1) array of joint probabilities.
    """
    if rho == 0.0:
        return score_grid(lambda_home, lambda_away)

    # Enforce constraints
    if rho < 0.0:
        logger.warning(f"rho={rho:.4f} < 0, clamping to 0")
        return score_grid(lambda_home, lambda_away)

    max_rho = min(lambda_home, lambda_away) - 0.001
    if rho >= max_rho:
        logger.warning(
            f"rho={rho:.4f} >= min(λ_h, λ_a)={min(lambda_home, lambda_away):.4f}, "
            f"clamping to {max_rho:.4f}"
        )
        rho = max(max_rho, 0.0)
        if rho == 0.0:
            return score_grid(lambda_home, lambda_away)

    lam1 = lambda_home - rho  # independent home component
    lam2 = lambda_away - rho  # independent away component
    n = MAX_GOALS + 1

    grid = np.zeros((n, n))
    for x in range(n):
        for y in range(n):
            s = 0.0
            for k in range(min(x, y) + 1):
                s += (
                    lam1 ** (x - k)
                    * lam2 ** (y - k)
                    * rho**k
                    / (_FACTORIALS[x - k] * _FACTORIALS[y - k] * _FACTORIALS[k])
                )
            grid[x, y] = s

    grid *= np.exp(-(lam1 + lam2 + rho))

    return grid


def match_probabilities(
    lambda_home: float,
    lambda_away: float,
    rho: float = 0.0,
) -> dict[str, float]:
    """Derive all market probabilities from λ_home, λ_away.

    Args:
        lambda_home: expected home goals
        lambda_away: expected away goals
        rho: bivariate Poisson correlation parameter (0 = independent)

    Returns dict with keys:
      home_win, draw, away_win,
      over_1.5, over_2.5, over_3.5,
      ah_home_-0.5, ah_home_-1.0, ah_home_-1.5, ah_home_-2.5,
      expected_home, expected_away, expected_total
    """
    grid = bivariate_score_grid(lambda_home, lambda_away, rho)
    n = MAX_GOALS + 1

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0

    totals = {1.5: 0.0, 2.5: 0.0, 3.5: 0.0}  # P(over X)
    ah = {-0.5: 0.0, -1.5: 0.0, -2.5: 0.0}    # P(home wins by more than |line|)
    ah_10_win = 0.0  # AH -1.0: win if margin > 1, push if margin == 1
    ah_10_push = 0.0

    for i in range(n):
        for j in range(n):
            p = grid[i, j]
            margin = i - j
            total = i + j

            if margin > 0:
                p_home += p
            elif margin == 0:
                p_draw += p
            else:
                p_away += p

            for line, _ in totals.items():
                if total > line:
                    totals[line] += p

            if margin > 0.5:
                ah[-0.5] += p
            if margin > 1.5:
                ah[-1.5] += p
            if margin > 2.5:
                ah[-2.5] += p

            if margin > 1:
                ah_10_win += p
            elif margin == 1:
                ah_10_push += p

    return {
        "home_win": p_home,
        "draw": p_draw,
        "away_win": p_away,
        "over_1.5": totals[1.5],
        "over_2.5": totals[2.5],
        "over_3.5": totals[3.5],
        "ah_home_-0.5": ah[-0.5],
        "ah_home_-1.0_eff": ah_10_win + 0.5 * ah_10_push,
        "ah_home_-1.5": ah[-1.5],
        "ah_home_-2.5": ah[-2.5],
        "expected_home": lambda_home,
        "expected_away": lambda_away,
        "expected_total": lambda_home + lambda_away,
    }


def batch_match_probabilities(
    lambdas_home: np.ndarray,
    lambdas_away: np.ndarray,
    rho: float = 0.0,
) -> dict[str, np.ndarray]:
    """Vectorized: compute market probabilities for arrays of λ values."""
    n = len(lambdas_home)
    results = {key: np.zeros(n) for key in [
        "home_win", "draw", "away_win",
        "over_2.5", "ah_home_-1.5",
    ]}

    for idx in range(n):
        probs = match_probabilities(lambdas_home[idx], lambdas_away[idx], rho)
        for key in results:
            results[key][idx] = probs[key]

    results["expected_home"] = lambdas_home
    results["expected_away"] = lambdas_away
    results["expected_total"] = lambdas_home + lambdas_away

    return results


def estimate_rho(
    games_df: "pd.DataFrame",
    lambdas_home: np.ndarray,
    lambdas_away: np.ndarray,
    rho_range: np.ndarray | None = None,
) -> tuple[float, dict]:
    """Estimate optimal ρ via grid search minimizing RPS.

    Tests each candidate ρ, computes mean RPS over all matches,
    and selects the value that minimizes it.

    Args:
        games_df: match-level DataFrame with result, home_implied, draw_implied, away_implied
        lambdas_home: predicted λ for home teams
        lambdas_away: predicted λ for away teams
        rho_range: candidate ρ values (default: 0.00 to 0.24 in steps of 0.01)

    Returns:
        (rho_star, info_dict) where info_dict has rho_values, rps_values, best_rps
    """
    if rho_range is None:
        rho_range = np.arange(0.0, 0.41, 0.01)

    n = len(games_df)
    rps_values = []

    for rho_candidate in rho_range:
        total_rps = 0.0
        for i in range(n):
            row = games_df.iloc[i]
            probs = match_probabilities(lambdas_home[i], lambdas_away[i], rho_candidate)

            actual = [
                1.0 if row["result"] == "H" else 0.0,
                1.0 if row["result"] == "D" else 0.0,
                1.0 if row["result"] == "A" else 0.0,
            ]
            model_p = [probs["home_win"], probs["draw"], probs["away_win"]]

            cum_pred = np.cumsum(model_p)
            cum_actual = np.cumsum(actual)
            total_rps += np.mean((cum_pred - cum_actual) ** 2)

        mean_rps = total_rps / n
        rps_values.append(mean_rps)

    rps_arr = np.array(rps_values)
    best_idx = int(np.argmin(rps_arr))
    rho_star = float(rho_range[best_idx])

    logger.info(
        f"Rho estimation: best rho={rho_star:.3f} (RPS={rps_arr[best_idx]:.5f}), "
        f"independent RPS={rps_arr[0]:.5f}, "
        f"improvement={1 - rps_arr[best_idx] / rps_arr[0]:.2%}"
    )

    return rho_star, {
        "rho_values": rho_range.tolist(),
        "rps_values": rps_arr.tolist(),
        "best_rho": rho_star,
        "best_rps": float(rps_arr[best_idx]),
        "independent_rps": float(rps_arr[0]),
    }


def implied_lambdas_from_odds(
    home_odds: float, draw_odds: float, away_odds: float,
    max_iter: int = 50,
) -> tuple[float, float]:
    """Back-calculate λ_home, λ_away from 1X2 odds via Poisson inversion.

    Uses grid search to find (λ_h, λ_a) that best match implied 1X2 probabilities.
    """
    # Fair probabilities
    raw = np.array([1/home_odds, 1/draw_odds, 1/away_odds])
    fair = raw / raw.sum()
    p_h_target, p_d_target, p_a_target = fair

    best_loss = float("inf")
    best_lh, best_la = 1.3, 1.1

    # Grid search
    for lh in np.arange(0.3, 3.5, 0.05):
        for la in np.arange(0.3, 3.5, 0.05):
            probs = match_probabilities(lh, la)
            loss = (
                (probs["home_win"] - p_h_target) ** 2
                + (probs["draw"] - p_d_target) ** 2
                + (probs["away_win"] - p_a_target) ** 2
            )
            if loss < best_loss:
                best_loss = loss
                best_lh, best_la = lh, la

    return best_lh, best_la
