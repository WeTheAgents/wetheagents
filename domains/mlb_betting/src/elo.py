"""Elo rating engine for MLB teams.

Computes entering-game Elo for each team strictly from past game outcomes.
No external dependencies — self-contained from our game-level dataset.

Standard Elo with MLB-tuned parameters:
- K=4 (low K → stable ratings, appropriate for 162-game season)
- Home advantage = 24 Elo points (~54% expected home win rate)
- Initial rating = 1500, with season-to-season regression toward mean
"""

from __future__ import annotations

import numpy as np
import pandas as pd


DEFAULT_K = 4
DEFAULT_HOME_ADV = 24
DEFAULT_INITIAL = 1500
SEASON_REGRESSION = 0.33  # Regress 1/3 toward mean between seasons


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def compute_elo(
    games: pd.DataFrame,
    *,
    k: float = DEFAULT_K,
    home_adv: float = DEFAULT_HOME_ADV,
    initial: float = DEFAULT_INITIAL,
    regress: float = SEASON_REGRESSION,
) -> pd.DataFrame:
    """Compute entering-game Elo ratings for all teams across all seasons.

    Args:
        games: Game-level DataFrame with columns:
            season, date, home_team, away_team, home_win (0/1)
        k: Elo K-factor
        home_adv: Home team Elo bonus (points)
        initial: Starting Elo for new teams
        regress: Fraction to regress toward mean between seasons

    Returns:
        DataFrame with columns: season, date, home_team, away_team,
        home_elo, away_elo, elo_diff (home_elo - away_elo, incl. home_adv)
    """
    df = games[["season", "date", "home_team", "away_team", "home_win"]].copy()
    df = df.sort_values(["season", "date"]).reset_index(drop=True)

    ratings: dict[str, float] = {}
    results = []
    prev_season = None

    for _, row in df.iterrows():
        season = row["season"]
        home = row["home_team"]
        away = row["away_team"]
        home_won = bool(row["home_win"])

        # Season transition: regress all ratings toward mean
        if prev_season is not None and season != prev_season:
            mean_elo = np.mean(list(ratings.values())) if ratings else initial
            for team in list(ratings.keys()):
                ratings[team] = ratings[team] + regress * (mean_elo - ratings[team])
        prev_season = season

        # Initialize new teams
        if home not in ratings:
            ratings[home] = initial
        if away not in ratings:
            ratings[away] = initial

        home_elo = ratings[home]
        away_elo = ratings[away]

        # Record ENTERING-game Elo (before update)
        results.append({
            "season": season,
            "date": row["date"],
            "home_team": home,
            "away_team": away,
            "home_elo": home_elo,
            "away_elo": away_elo,
            "elo_diff": (home_elo + home_adv) - away_elo,
        })

        # Update ratings
        expected_home = _expected_score(home_elo + home_adv, away_elo)
        actual_home = 1.0 if home_won else 0.0
        delta = k * (actual_home - expected_home)
        ratings[home] += delta
        ratings[away] -= delta

    return pd.DataFrame(results)
