"""Bullpen features from Retrosheet pitching data.

Computes three categories of bullpen metrics per team per game:
1. Bullpen WHIP + K/BB (rolling quality, same approach as starters)
2. Close-game win contribution (management quality — margin ≤ 2)
3. Bullpen workload / fatigue (IP in last 1 and 3 days)

All metrics are strictly ENTERING-game (anti-leakage).

Output: data/processed/retrosheet/bullpen_features.parquet
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.retrosheet_pitchers import (
    FIP_CONSTANT,
    RETROSHEETS_DIR,
    _ensure_int,
    _find_member,
    _parse_yyyymmdd_int,
)

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed" / "retrosheet"
SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]


def load_reliever_lines(
    season: int,
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
) -> pd.DataFrame:
    """Load reliever pitching lines (p_seq > 1) for a season from Retrosheet zips."""
    from zipfile import ZipFile

    zip_path = retrosheets_dir / f"{season}csvs.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing Retrosheet archive: {zip_path}")

    with ZipFile(zip_path) as z:
        gameinfo_name = _find_member(z, f"{season}gameinfo.csv")
        pitching_name = _find_member(z, f"{season}pitching.csv")

    # Load gameinfo for date + teams
    from src.retrosheet_pitchers import _read_csv_from_zip

    games = _read_csv_from_zip(zip_path, gameinfo_name)
    games = _ensure_int(games, ["date", "number", "season"])
    games = games.rename(columns={"visteam": "away_team", "hometeam": "home_team"})
    games["season"] = season
    games["date"] = _parse_yyyymmdd_int(games["date"])

    # Load pitching
    pitching = _read_csv_from_zip(zip_path, pitching_name)
    pitching = _ensure_int(pitching, ["p_seq", "p_ipouts", "p_h", "p_w", "p_k", "p_er", "p_hr"])

    if "stattype" in pitching.columns:
        pitching = pitching[pitching["stattype"] == "value"]

    # Keep relievers only (p_seq > 1)
    relievers = pitching[pitching["p_seq"] > 1].copy()

    # Drop columns that would collide with game metadata on merge
    for col in ["date", "number", "season", "home_team", "away_team"]:
        if col in relievers.columns:
            relievers = relievers.drop(columns=[col])

    # Join game metadata
    keep_cols = ["gid", "season", "date", "home_team", "away_team"]
    keep_cols = [c for c in keep_cols if c in games.columns]
    relievers = relievers.merge(
        games[keep_cols].drop_duplicates(subset=["gid"]),
        on="gid",
        how="left",
    )

    return relievers


def _aggregate_team_game_relievers(relievers: pd.DataFrame) -> pd.DataFrame:
    """Aggregate reliever stats to team-game level."""
    df = relievers.copy()
    df = _ensure_int(df, ["p_ipouts", "p_h", "p_w", "p_k", "p_hr", "p_er"])

    # Group by gid + team
    grp = df.groupby(["gid", "team", "season", "date"], sort=False)
    agg = grp.agg(
        bp_outs=("p_ipouts", "sum"),
        bp_h=("p_h", "sum"),
        bp_bb=("p_w", "sum"),
        bp_so=("p_k", "sum"),
        bp_hr=("p_hr", "sum"),
        bp_er=("p_er", "sum"),
        bp_n_pitchers=("p_seq", "count"),
    ).reset_index()

    agg["bp_ip"] = agg["bp_outs"] / 3.0

    return agg


def _compute_rolling_bullpen_quality(
    team_game_bp: pd.DataFrame,
    *,
    short_window: int = 5,
    mid_window: int = 7,
    long_window: int = 15,
) -> pd.DataFrame:
    """Compute rolling bullpen WHIP, K/BB, K9 entering each game."""
    df = team_game_bp.sort_values(["team", "season", "date"]).reset_index(drop=True)

    results = []
    for (team, season), grp in df.groupby(["team", "season"], sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        # Arrays
        h = grp["bp_h"].values.astype(float)
        bb = grp["bp_bb"].values.astype(float)
        so = grp["bp_so"].values.astype(float)
        outs = grp["bp_outs"].values.astype(float)

        for i in range(n):
            row = {
                "team": team,
                "season": grp.iloc[i]["season"],
                "date": grp.iloc[i]["date"],
            }

            for label, window in [("short", short_window), ("7g", mid_window), ("long", long_window)]:
                start = max(0, i - window)
                if i == 0:
                    row[f"bp_whip_{label}"] = np.nan
                    row[f"bp_kbb_{label}"] = np.nan
                    row[f"bp_k9_{label}"] = np.nan
                else:
                    h_sum = h[start:i].sum()
                    bb_sum = bb[start:i].sum()
                    so_sum = so[start:i].sum()
                    outs_sum = outs[start:i].sum()
                    ip = outs_sum / 3.0

                    row[f"bp_whip_{label}"] = (h_sum + bb_sum) / ip if ip > 0 else np.nan
                    row[f"bp_kbb_{label}"] = (so_sum + 1.0) / (bb_sum + 1.0)
                    row[f"bp_k9_{label}"] = (9.0 * so_sum / ip) if ip > 0 else np.nan
                    hr_sum = grp.iloc[start:i]["bp_hr"].values.astype(float).sum()
                    row[f"bp_fip_{label}"] = (
                        (13.0 * hr_sum + 3.0 * bb_sum - 2.0 * so_sum) / ip + FIP_CONSTANT
                        if ip > 0 else np.nan
                    )

            results.append(row)

    return pd.DataFrame(results)


def _compute_close_game_win_pct(
    team_game_bp: pd.DataFrame,
    games_info: pd.DataFrame,
    *,
    window: int = 20,
    margin_threshold: int = 2,
) -> pd.DataFrame:
    """Compute rolling win% in close games (margin ≤ threshold) where bullpen appeared.

    games_info must have: gid, home_team, away_team, home_final, away_final (or equivalent).
    """
    df = team_game_bp.copy()

    # Build game outcome mapping
    gi = games_info.copy()
    if "home_final" in gi.columns and "away_final" in gi.columns:
        gi["margin"] = (gi["home_final"] - gi["away_final"]).abs()
        gi["home_won"] = gi["home_final"] > gi["away_final"]
    else:
        raise ValueError("games_info must have home_final and away_final")

    # For each team-game: determine if it was a close game and if team won
    df = df.merge(
        gi[["gid", "home_team", "away_team", "margin", "home_won"]].drop_duplicates(subset=["gid"]),
        on="gid",
        how="left",
    )
    df["is_close"] = df["margin"] <= margin_threshold
    df["home_won"] = df["home_won"].astype("boolean")
    df["team_won"] = np.where(
        df["team"] == df["home_team"],
        df["home_won"].fillna(False),
        (~df["home_won"]).fillna(False),
    )

    results = []
    for (team, season), grp in df.groupby(["team", "season"], sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        is_close = grp["is_close"].values
        won = grp["team_won"].values

        for i in range(n):
            start = max(0, i - window)
            if i == 0:
                bp_close_win_pct = np.nan
            else:
                close_mask = is_close[start:i]
                close_wins = won[start:i][close_mask]
                if len(close_wins) >= 3:
                    bp_close_win_pct = close_wins.mean()
                else:
                    bp_close_win_pct = np.nan

            results.append(
                {
                    "team": team,
                    "season": grp.iloc[i]["season"],
                    "date": grp.iloc[i]["date"],
                    "bp_close_win_pct": bp_close_win_pct,
                }
            )

    return pd.DataFrame(results)


def _compute_workload(
    relievers: pd.DataFrame,
    team_game_bp: pd.DataFrame,
) -> pd.DataFrame:
    """Compute bullpen workload: IP in last 1 and 3 days, pitcher count in 3 days."""
    df = team_game_bp[["team", "season", "date"]].copy()
    df = df.sort_values(["team", "season", "date"]).reset_index(drop=True)

    # Build daily reliever IP by team and season
    rel = relievers.copy()
    rel = _ensure_int(rel, ["p_ipouts"])
    daily = rel.groupby(["team", "season", "date"]).agg(
        daily_bp_outs=("p_ipouts", "sum"),
        daily_bp_pitchers=("p_seq", "count"),
    ).reset_index()
    daily["daily_bp_ip"] = daily["daily_bp_outs"] / 3.0

    results = []
    for (team, season), grp in df.groupby(["team", "season"], sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        season_daily = daily[(daily["team"] == team) & (daily["season"] == season)]
        team_daily = season_daily.set_index("date").sort_index()

        for i in range(len(grp)):
            game_date = grp.iloc[i]["date"]

            # 1-day lookback (yesterday only)
            d1_start = game_date - pd.Timedelta(days=1)
            mask_1d = (team_daily.index >= d1_start) & (team_daily.index < game_date)
            bp_ip_1d = team_daily.loc[mask_1d, "daily_bp_ip"].sum() if mask_1d.any() else 0.0

            # 3-day lookback
            d3_start = game_date - pd.Timedelta(days=3)
            mask_3d = (team_daily.index >= d3_start) & (team_daily.index < game_date)
            bp_ip_3d = team_daily.loc[mask_3d, "daily_bp_ip"].sum() if mask_3d.any() else 0.0
            bp_pitchers_3d = int(
                team_daily.loc[mask_3d, "daily_bp_pitchers"].sum() if mask_3d.any() else 0
            )

            results.append(
                {
                    "team": team,
                    "season": grp.iloc[i]["season"],
                    "date": game_date,
                    "bp_ip_1d": bp_ip_1d,
                    "bp_ip_3d": bp_ip_3d,
                    "bp_pitchers_3d": bp_pitchers_3d,
                }
            )

    return pd.DataFrame(results)


def build_bullpen_features(
    seasons: list[int] | None = None,
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
    short_window: int = 5,
    mid_window: int = 7,
    long_window: int = 15,
    close_game_window: int = 20,
) -> pd.DataFrame:
    """Build all bullpen features for all seasons.

    Returns DataFrame with columns:
    - team, season, date (keys)
    - bp_whip_short, bp_whip_7g, bp_whip_long, etc.
    - bp_fip_short, bp_fip_7g, bp_fip_long
    - bp_close_win_pct
    - bp_ip_1d, bp_ip_3d, bp_pitchers_3d
    """
    seasons = seasons or SEASONS

    all_relievers = []
    all_gameinfo = []

    for season in seasons:
        logger.info(f"Loading relievers for {season}...")
        rel = load_reliever_lines(season, retrosheets_dir=retrosheets_dir)
        all_relievers.append(rel)

        # Also load gameinfo for close-game computation
        from src.retrosheet_pitchers import load_year_gameinfo_and_pitching

        games, _ = load_year_gameinfo_and_pitching(season, retrosheets_dir=retrosheets_dir)
        # Need home_final/away_final — get from gamescores if available, else compute from pitching
        # Actually gameinfo has score columns. Let's check what we have.
        if "home_final" not in games.columns:
            # Try to get from the games table itself or pitching aggregation
            # In Retrosheet gameinfo, scores are typically in specific columns
            # Let's skip games without final scores
            logger.warning(f"No home_final in gameinfo for {season}, checking alternatives...")
        all_gameinfo.append(games)

    relievers = pd.concat(all_relievers, ignore_index=True)
    gameinfo = pd.concat(all_gameinfo, ignore_index=True)

    logger.info(f"Total reliever lines: {len(relievers)}")

    # Aggregate to team-game level
    team_game_bp = _aggregate_team_game_relievers(relievers)
    logger.info(f"Team-game bullpen aggregates: {len(team_game_bp)}")

    # Deduplicate doubleheader dates: keep game-1 entering state per (team, date).
    # Retrosheet has both DH games; rolling features must produce exactly 1 row
    # per (team, season, date) to avoid fan-out when merged to games.
    before_dedup = len(team_game_bp)
    team_game_bp = team_game_bp.sort_values(["team", "date", "gid"])
    team_game_bp = team_game_bp.drop_duplicates(
        subset=["team", "season", "date"], keep="first"
    )
    n_dropped = before_dedup - len(team_game_bp)
    if n_dropped > 0:
        logger.info(f"Deduped {n_dropped} doubleheader bullpen rows (kept game-1 per team-date)")

    # 1. Rolling quality (WHIP, K/BB, K9)
    logger.info("Computing rolling bullpen quality...")
    quality = _compute_rolling_bullpen_quality(
        team_game_bp, short_window=short_window, mid_window=mid_window, long_window=long_window
    )

    # 2. Close-game win contribution
    # We need game results. Try to get from our odds data pipeline instead (more reliable).
    # For now, try gameinfo if it has scores, otherwise skip.
    if "home_final" in gameinfo.columns and "away_final" in gameinfo.columns:
        logger.info("Computing close-game win contribution...")
        close_game = _compute_close_game_win_pct(
            team_game_bp, gameinfo, window=close_game_window
        )
    else:
        logger.warning(
            "Cannot compute close-game win%. "
            "gameinfo missing home_final/away_final. "
            "Use build_with_odds_data() instead."
        )
        close_game = pd.DataFrame(columns=["team", "season", "date", "bp_close_win_pct"])

    # 3. Workload
    logger.info("Computing bullpen workload...")
    workload = _compute_workload(relievers, team_game_bp)

    # Merge all
    result = quality.merge(
        close_game, on=["team", "season", "date"], how="left"
    ).merge(
        workload, on=["team", "season", "date"], how="left"
    )

    logger.info(f"Bullpen features: {len(result)} rows, {result['team'].nunique()} teams")
    return result


def build_with_odds_data(
    seasons: list[int] | None = None,
    *,
    retrosheets_dir: Path = RETROSHEETS_DIR,
    short_window: int = 5,
    mid_window: int = 7,
    long_window: int = 15,
    close_game_window: int = 20,
) -> pd.DataFrame:
    """Build bullpen features using Retrosheet master games for close-game win%.

    Uses retrosheet_master_games.parquet which has gid + final scores,
    avoiding the need for team code mapping between odds and Retrosheet.
    """
    from src.data_loader import PROCESSED_DIR

    seasons_list = seasons or SEASONS

    # Load relievers from Retrosheet
    all_relievers = []
    for season in seasons_list:
        logger.info(f"Loading relievers for {season}...")
        rel = load_reliever_lines(season, retrosheets_dir=retrosheets_dir)
        all_relievers.append(rel)

    relievers = pd.concat(all_relievers, ignore_index=True)
    logger.info(f"Total reliever lines: {len(relievers)}")

    # Aggregate to team-game level
    team_game_bp = _aggregate_team_game_relievers(relievers)

    # Load Retrosheet master games (has gid + scores, same team codes)
    master_path = PROCESSED_DIR / "retrosheet" / "retrosheet_master_games.parquet"
    if not master_path.exists():
        raise FileNotFoundError(
            f"Retrosheet master not found: {master_path}. "
            "Run scripts/build_retrosheet_master_with_odds.py first."
        )
    logger.info("Loading Retrosheet master games for scores...")
    master = pd.read_parquet(master_path)

    # 1. Quality
    logger.info("Computing rolling bullpen quality...")
    quality = _compute_rolling_bullpen_quality(
        team_game_bp, short_window=short_window, mid_window=mid_window, long_window=long_window
    )

    # 2. Close-game win contribution (using Retrosheet master with gid-based join)
    logger.info("Computing close-game win contribution...")
    close_game = _compute_close_game_win_pct(
        team_game_bp, master, window=close_game_window
    )

    # 3. Workload
    logger.info("Computing bullpen workload...")
    workload = _compute_workload(relievers, team_game_bp)

    # Merge all
    result = quality.merge(
        close_game, on=["team", "season", "date"], how="left"
    ).merge(
        workload, on=["team", "season", "date"], how="left"
    )

    logger.info(f"Bullpen features: {len(result)} rows, {result['team'].nunique()} teams")
    return result


def save_bullpen_features(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    out_path = output_dir / "bullpen_features.parquet"
    # Use the 2026 fetcher's io_safety helpers so historical rebuilds also
    # get atomic writes, backups, and a sidecar.
    from data.fetch_2026.io_safety import safe_write_parquet

    safe_write_parquet(
        df,
        out_path,
        generator="src.bullpen_features.save_bullpen_features",
        date_col="date",
        audit_action="historical_bullpen_rebuild",
    )
    logger.info(f"Saved bullpen features to {out_path}")
    return out_path
