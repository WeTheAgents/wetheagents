"""Pitcher-level feature engineering from available game data.

Computes rolling proxy features for each starting pitcher:
- Win rate (short/long windows + oscillator)
- Runs allowed per start (short/long + oscillator)
- First inning runs allowed per start (1st inn ERA proxy)
- Pitcher hand (R/L from code suffix)

All features use only data available BEFORE the game (no look-ahead).
Window sizes: short=5 starts, long=15 starts (configurable).
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default oscillator windows (in number of starts)
SHORT_WINDOW = 5
LONG_WINDOW = 15


def build_pitcher_start_log(games: pd.DataFrame) -> pd.DataFrame:
    """Build a pitcher-level start log from game-level data.

    Each row = one pitcher's start in one game.
    Includes: pitcher code, date, season, team, opponent,
    whether team won, runs allowed by team, first inning runs allowed.
    """
    # Home pitcher perspective
    home = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "pitcher": games["home_pitcher"].values,
            "team": games["home_team"].values,
            "opponent": games["away_team"].values,
            "is_home": True,
            "team_won": games["home_win"].astype(bool).values,
            "runs_allowed": games["away_final"].values,  # opponent's final score
            "runs_scored": games["home_final"].values,
            "first_inn_runs_allowed": games["away_inn_1"].values,  # opponent scored in 1st
            "first_inn_runs_scored": games["home_inn_1"].values,
            "close_ml": games["home_close_ml"].values,
        }
    )

    # Away pitcher perspective
    away = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "pitcher": games["away_pitcher"].values,
            "team": games["away_team"].values,
            "opponent": games["home_team"].values,
            "is_home": False,
            "team_won": (~games["home_win"].astype(bool)).values,
            "runs_allowed": games["home_final"].values,  # opponent's final score
            "runs_scored": games["away_final"].values,
            "first_inn_runs_allowed": games["home_inn_1"].values,  # opponent scored in 1st
            "first_inn_runs_scored": games["away_inn_1"].values,
            "close_ml": games["away_close_ml"].values,
        }
    )

    log = pd.concat([home, away], ignore_index=True)
    log = log.dropna(subset=["pitcher", "runs_allowed"])
    log = log.sort_values(["pitcher", "date"]).reset_index(drop=True)

    logger.info(
        f"Pitcher start log: {len(log)} starts, {log['pitcher'].nunique()} unique pitchers"
    )
    return log


def extract_pitcher_hand(pitcher_code: str) -> str | None:
    """Extract pitcher hand (R/L) from code suffix like JBECKETT-R."""
    if isinstance(pitcher_code, str):
        if pitcher_code.endswith("-R"):
            return "R"
        elif pitcher_code.endswith("-L"):
            return "L"
    return None


def _rolling_mean_entering(values: np.ndarray, window: int) -> np.ndarray:
    """Compute rolling mean of `values` over last `window` entries, ENTERING each row.

    For row i, uses values[max(0, i-window):i] (excludes current row).
    Returns NaN if fewer than 3 prior entries (minimum sample).
    """
    n = len(values)
    result = np.full(n, np.nan)
    min_sample = 3

    for i in range(min_sample, n):
        start = max(0, i - window)
        result[i] = values[start:i].mean()

    return result


def _rolling_winrate_entering(wins: np.ndarray, window: int) -> np.ndarray:
    """Compute rolling win rate over last `window` starts, ENTERING each row."""
    return _rolling_mean_entering(wins.astype(float), window)


def calc_pitcher_rolling_features(
    start_log: pd.DataFrame,
    short_window: int = SHORT_WINDOW,
    long_window: int = LONG_WINDOW,
) -> pd.DataFrame:
    """Compute rolling pitcher features for each start.

    For each pitcher, computes rolling stats over their starts (not calendar days).

    Returns DataFrame with columns:
    - pitcher, season, date, team (join keys)
    - p_wr_short: win rate over last `short_window` starts
    - p_wr_long: win rate over last `long_window` starts
    - p_wr_momentum: p_wr_short - p_wr_long (oscillator)
    - p_ra_short: runs allowed per start, short window
    - p_ra_long: runs allowed per start, long window
    - p_ra_momentum: p_ra_short - p_ra_long (positive = getting worse)
    - p_first_inn_ra_short: 1st inning runs allowed, short window
    - p_first_inn_ra_long: 1st inning runs allowed, long window
    - p_first_inn_momentum: oscillator for 1st inning
    - p_hand: R/L/None
    - p_starts_total: total starts entering this game (experience proxy)
    """
    results = []

    # Group by (pitcher, team, season) — season isolation ensures no cross-year
    # leakage. Each season starts fresh with NaN until min_sample starts.
    # Also separates same-code pitchers on different teams (trade mid-season).
    for (pitcher, team, season), grp in start_log.groupby(["pitcher", "team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        hand = extract_pitcher_hand(pitcher)

        if n < 3:
            # Not enough data for any rolling metric
            for i in range(n):
                results.append(
                    {
                        "pitcher": pitcher,
                        "season": grp.iloc[i]["season"],
                        "date": grp.iloc[i]["date"],
                        "team": team,
                        "p_wr_short": np.nan,
                        "p_wr_long": np.nan,
                        "p_wr_momentum": np.nan,
                        "p_ra_short": np.nan,
                        "p_ra_long": np.nan,
                        "p_ra_momentum": np.nan,
                        "p_first_inn_ra_short": np.nan,
                        "p_first_inn_ra_long": np.nan,
                        "p_first_inn_momentum": np.nan,
                        "p_hand": hand,
                        "p_starts_total": i,
                    }
                )
            continue

        won = grp["team_won"].values.astype(float)
        ra = grp["runs_allowed"].values.astype(float)
        first_inn_ra = grp["first_inn_runs_allowed"].values.astype(float)

        # Rolling features (cross-season within same team)
        wr_short = _rolling_winrate_entering(won, short_window)
        wr_long = _rolling_winrate_entering(won, long_window)

        ra_short = _rolling_mean_entering(ra, short_window)
        ra_long = _rolling_mean_entering(ra, long_window)

        fi_short = _rolling_mean_entering(first_inn_ra, short_window)
        fi_long = _rolling_mean_entering(first_inn_ra, long_window)

        for i in range(n):
            results.append(
                {
                    "pitcher": pitcher,
                    "season": grp.iloc[i]["season"],
                    "date": grp.iloc[i]["date"],
                    "team": team,
                    "p_wr_short": wr_short[i],
                    "p_wr_long": wr_long[i],
                    "p_wr_momentum": (
                        wr_short[i] - wr_long[i]
                        if not (np.isnan(wr_short[i]) or np.isnan(wr_long[i]))
                        else np.nan
                    ),
                    "p_ra_short": ra_short[i],
                    "p_ra_long": ra_long[i],
                    "p_ra_momentum": (
                        ra_short[i] - ra_long[i]
                        if not (np.isnan(ra_short[i]) or np.isnan(ra_long[i]))
                        else np.nan
                    ),
                    "p_first_inn_ra_short": fi_short[i],
                    "p_first_inn_ra_long": fi_long[i],
                    "p_first_inn_momentum": (
                        fi_short[i] - fi_long[i]
                        if not (np.isnan(fi_short[i]) or np.isnan(fi_long[i]))
                        else np.nan
                    ),
                    "p_hand": hand,
                    "p_starts_total": i,
                }
            )

    df = pd.DataFrame(results)
    n_with_data = df["p_wr_short"].notna().sum()
    logger.info(
        f"Pitcher features: {len(df)} rows, "
        f"{n_with_data} with rolling data ({100 * n_with_data / len(df):.1f}%)"
    )
    return df


def merge_pitcher_features_to_games(
    games: pd.DataFrame,
    pitcher_features: pd.DataFrame,
) -> pd.DataFrame:
    """Merge pitcher rolling features onto game-level data.

    Adds home_sp_* and away_sp_* columns, plus composite features.
    """
    # Rename for home pitcher merge (keep team for disambiguation)
    home_pf = pitcher_features.rename(
        columns={
            "pitcher": "home_pitcher",
            "team": "home_team",
            "p_wr_short": "home_sp_wr_short",
            "p_wr_long": "home_sp_wr_long",
            "p_wr_momentum": "home_sp_wr_momentum",
            "p_ra_short": "home_sp_ra_short",
            "p_ra_long": "home_sp_ra_long",
            "p_ra_momentum": "home_sp_ra_momentum",
            "p_first_inn_ra_short": "home_sp_fi_ra_short",
            "p_first_inn_ra_long": "home_sp_fi_ra_long",
            "p_first_inn_momentum": "home_sp_fi_momentum",
            "p_hand": "home_sp_hand",
            "p_starts_total": "home_sp_starts",
        }
    )
    home_pf = home_pf.drop(columns=["season"], errors="ignore")

    # Rename for away pitcher merge (keep team for disambiguation)
    away_pf = pitcher_features.rename(
        columns={
            "pitcher": "away_pitcher",
            "team": "away_team",
            "p_wr_short": "away_sp_wr_short",
            "p_wr_long": "away_sp_wr_long",
            "p_wr_momentum": "away_sp_wr_momentum",
            "p_ra_short": "away_sp_ra_short",
            "p_ra_long": "away_sp_ra_long",
            "p_ra_momentum": "away_sp_ra_momentum",
            "p_first_inn_ra_short": "away_sp_fi_ra_short",
            "p_first_inn_ra_long": "away_sp_fi_ra_long",
            "p_first_inn_momentum": "away_sp_fi_momentum",
            "p_hand": "away_sp_hand",
            "p_starts_total": "away_sp_starts",
        }
    )
    away_pf = away_pf.drop(columns=["season"], errors="ignore")

    # Merge on pitcher code + team + date (team disambiguates same-code pitchers)
    enriched = games.merge(
        home_pf, on=["home_pitcher", "home_team", "date"], how="left"
    ).merge(
        away_pf, on=["away_pitcher", "away_team", "date"], how="left"
    )

    # Composite / diff features
    # Win rate diff (home advantage in pitcher form)
    enriched["sp_wr_short_diff"] = (
        enriched["home_sp_wr_short"] - enriched["away_sp_wr_short"]
    )
    enriched["sp_wr_long_diff"] = (
        enriched["home_sp_wr_long"] - enriched["away_sp_wr_long"]
    )
    enriched["sp_wr_momentum_diff"] = (
        enriched["home_sp_wr_momentum"] - enriched["away_sp_wr_momentum"]
    )

    # Runs allowed diff (lower = better, so home - away: negative = home pitcher better)
    enriched["sp_ra_short_diff"] = (
        enriched["home_sp_ra_short"] - enriched["away_sp_ra_short"]
    )
    enriched["sp_ra_long_diff"] = (
        enriched["home_sp_ra_long"] - enriched["away_sp_ra_long"]
    )
    enriched["sp_ra_momentum_diff"] = (
        enriched["home_sp_ra_momentum"] - enriched["away_sp_ra_momentum"]
    )

    # First inning composite (for YRFI)
    enriched["sp_fi_ra_combined"] = (
        enriched["home_sp_fi_ra_long"] + enriched["away_sp_fi_ra_long"]
    ) / 2
    enriched["sp_fi_momentum_diff"] = (
        enriched["home_sp_fi_momentum"] - enriched["away_sp_fi_momentum"]
    )

    # Experience diff
    enriched["sp_starts_diff"] = (
        enriched["home_sp_starts"] - enriched["away_sp_starts"]
    )

    # Matchup quality: both pitchers experienced + low RA
    enriched["sp_quality_floor"] = enriched[
        ["home_sp_ra_long", "away_sp_ra_long"]
    ].max(axis=1)  # worst of the two (lower is better for quality matchup)

    n_pitcher_cols = len([
        c for c in enriched.columns
        if c.startswith("home_sp_") or c.startswith("away_sp_") or c.startswith("sp_")
    ])
    n_matched = enriched["home_sp_wr_short"].notna().sum()
    logger.info(
        f"Merged {n_pitcher_cols} pitcher features. "
        f"Coverage: {n_matched}/{len(enriched)} games ({100 * n_matched / len(enriched):.1f}%)"
    )

    return enriched
