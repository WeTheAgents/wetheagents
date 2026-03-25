"""Derive match probabilities from Poisson λ parameters.

Given λ_home (expected home goals) and λ_away (expected away goals),
compute probabilities for all standard football betting markets:
  - 1X2 (home win, draw, away win)
  - Over/Under (2.5, 1.5, 3.5)
  - Asian Handicap (-0.5, -1.0, -1.5, -2.5)
  - Correct score grid

Uses independent Poisson assumption: P(H=i, A=j) = P_pois(i,λ_h) × P_pois(j,λ_a).

Usage:
    from src.markets import match_probabilities

    probs = match_probabilities(1.65, 1.20)
    print(probs["home_win"])  # P(H)
    print(probs["over_2.5"])  # P(total > 2.5)
    print(probs["ah_home_-1.5"])  # P(home wins by 2+)
"""

import numpy as np
from scipy.stats import poisson


MAX_GOALS = 8  # truncate Poisson at 8 goals per team (P(>8) < 0.001 for λ<4)


def score_grid(lambda_home: float, lambda_away: float) -> np.ndarray:
    """Compute probability grid P(home=i, away=j) for i,j in [0, MAX_GOALS].

    Returns (MAX_GOALS+1, MAX_GOALS+1) array.
    """
    home_probs = poisson.pmf(np.arange(MAX_GOALS + 1), lambda_home)
    away_probs = poisson.pmf(np.arange(MAX_GOALS + 1), lambda_away)
    return np.outer(home_probs, away_probs)


def match_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    """Derive all market probabilities from λ_home, λ_away.

    Returns dict with keys:
      home_win, draw, away_win,
      over_1.5, over_2.5, over_3.5,
      ah_home_-0.5, ah_home_-1.0, ah_home_-1.5, ah_home_-2.5,
      expected_home, expected_away, expected_total
    """
    grid = score_grid(lambda_home, lambda_away)
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
) -> dict[str, np.ndarray]:
    """Vectorized: compute market probabilities for arrays of λ values."""
    n = len(lambdas_home)
    results = {key: np.zeros(n) for key in [
        "home_win", "draw", "away_win",
        "over_2.5", "ah_home_-1.5",
    ]}

    for idx in range(n):
        probs = match_probabilities(lambdas_home[idx], lambdas_away[idx])
        for key in results:
            results[key][idx] = probs[key]

    results["expected_home"] = lambdas_home
    results["expected_away"] = lambdas_away
    results["expected_total"] = lambdas_home + lambdas_away

    return results


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
