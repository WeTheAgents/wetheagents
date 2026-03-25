"""Construct derived betting markets from inning-by-inning game data.

Builds: YRFI, F5 result/total, Race to X runs, Run Line cover.
Uses game-level DataFrame from data_loader.pair_games().
"""

import numpy as np
import pandas as pd

# Fixed odds for exotic markets (for backtest, since we don't have historical lines)
YRFI_FIXED_ODDS = 1.80  # Standard YRFI line

# ── NRFI odds calibration ────────────────────────────────────────────────
# Derived from YRFI calibration: NRFI rate = 1 - YRFI rate per OU bucket
# Low OU → high NRFI rate → cheap odds (market knows pitchers dominate)
# High OU → low NRFI rate → expensive odds (value if dominant pitching)
_NRFI_CALIB_OU = np.array([6.5, 7.25, 7.75, 8.25, 8.75, 9.50, 10.25, 11.0])
_NRFI_CALIB_ODDS = np.array([1.61, 1.79, 1.86, 1.91, 1.96, 2.01, 2.14, 2.36])


def estimate_nrfi_odds(close_ou: pd.Series) -> pd.Series:
    """Piecewise-linear interpolation: close_ou -> estimated NRFI decimal odds."""
    return pd.Series(
        np.interp(close_ou.values, _NRFI_CALIB_OU, _NRFI_CALIB_ODDS),
        index=close_ou.index,
    )


def add_yrfi_market(df: pd.DataFrame) -> pd.DataFrame:
    """Add Yes Run First Inning (YRFI) columns.

    YRFI = at least 1 run scored in the 1st inning by either team.
    """
    df = df.copy()
    df["first_inning_runs"] = df["away_inn_1"] + df["home_inn_1"]
    df["yrfi"] = (df["first_inning_runs"] > 0).astype(int)
    df["yrfi_odds"] = YRFI_FIXED_ODDS  # Fixed for backtest
    return df


def add_f5_markets(df: pd.DataFrame) -> pd.DataFrame:
    """Add First 5 Innings (F5) markets.

    - F5 total runs
    - F5 winner (home/away/push)
    - F5 home lead
    """
    df = df.copy()

    away_f5_cols = [f"away_inn_{i}" for i in range(1, 6)]
    home_f5_cols = [f"home_inn_{i}" for i in range(1, 6)]

    df["away_f5_runs"] = df[away_f5_cols].sum(axis=1)
    df["home_f5_runs"] = df[home_f5_cols].sum(axis=1)
    df["f5_total"] = df["away_f5_runs"] + df["home_f5_runs"]

    # F5 winner
    df["f5_winner"] = np.where(
        df["home_f5_runs"] > df["away_f5_runs"],
        "home",
        np.where(df["home_f5_runs"] < df["away_f5_runs"], "away", "push"),
    )
    df["f5_home_win"] = (df["f5_winner"] == "home").astype(int)

    # F5 over/under using half of the game O/U line as proxy
    df["f5_ou_line"] = df["close_ou"] / 2  # Rough proxy
    df["f5_over"] = (df["f5_total"] > df["f5_ou_line"]).astype(int)

    return df


def add_run_line_market(df: pd.DataFrame) -> pd.DataFrame:
    """Add run line cover column (home team perspective).

    Standard MLB run line = -1.5 for favorite.
    home_rl_cover = home team wins by 2+ runs.
    """
    df = df.copy()
    df["home_margin"] = df["home_final"] - df["away_final"]
    df["home_rl_cover"] = (df["home_margin"] >= 2).astype(int)  # Covers -1.5
    df["away_rl_cover"] = (df["home_margin"] <= -2).astype(int)  # Away covers +1.5
    return df


def add_race_to_x_market(df: pd.DataFrame, x: int = 3) -> pd.DataFrame:
    """Add Race to X runs market.

    Determines which team first reaches X cumulative runs, tracked inning by inning.
    """
    df = df.copy()

    away_inn_cols = [f"away_inn_{i}" for i in range(1, 10)]
    home_inn_cols = [f"home_inn_{i}" for i in range(1, 10)]

    def race_to_x(row, x_runs):
        away_cum = 0
        home_cum = 0
        for i in range(9):
            # Away team bats first (top of inning)
            away_cum += row[away_inn_cols[i]]
            if away_cum >= x_runs and home_cum < x_runs:
                return "away"

            # Home team bats second (bottom of inning)
            home_cum += row[home_inn_cols[i]]
            if home_cum >= x_runs and away_cum < x_runs:
                return "home"

            # If both reached X in same inning, first to reach wins
            if away_cum >= x_runs and home_cum >= x_runs:
                # Away batted first, so away reached it first (unless home already had X)
                return "away"

        # Neither reached X (very low-scoring game)
        return "none"

    df[f"race_to_{x}"] = df.apply(lambda r: race_to_x(r, x), axis=1)
    df[f"home_race_to_{x}"] = (df[f"race_to_{x}"] == "home").astype(int)

    return df


def add_all_markets(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived markets to the game DataFrame."""
    df = add_yrfi_market(df)
    df = add_f5_markets(df)
    df = add_run_line_market(df)
    df = add_race_to_x_market(df, x=3)
    return df


def market_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Print summary statistics for all markets."""
    stats = {}

    if "yrfi" in df.columns:
        stats["YRFI Rate"] = df["yrfi"].mean()
        stats["YRFI Games"] = len(df)

    if "f5_total" in df.columns:
        stats["F5 Avg Total"] = df["f5_total"].mean()
        stats["F5 Home Win %"] = df["f5_home_win"].mean()
        stats["F5 Push %"] = (df["f5_winner"] == "push").mean()
        stats["F5 Over %"] = df["f5_over"].mean()

    if "home_rl_cover" in df.columns:
        stats["Home RL Cover %"] = df["home_rl_cover"].mean()

    if "home_win" in df.columns:
        stats["Home Win %"] = df["home_win"].mean()

    if "race_to_3" in df.columns:
        stats["Race to 3: Home %"] = df["home_race_to_3"].mean()
        stats["Race to 3: None %"] = (df["race_to_3"] == "none").mean()

    return pd.Series(stats)
