"""FanGraphs team batting data via pybaseball.

Pulls per-player batting stats, aggregates to team level (PA-weighted wRC+, OBP).
Anti-leakage: each game in season Y uses team batting from season Y-1.

Output: data/processed/fangraphs/team_batting_season.parquet
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed" / "fangraphs"
RAW_CACHE_DIR = DEFAULT_OUTPUT_DIR

# Seasons to pull: 2009 (prior for 2010) through 2021
PULL_SEASONS = list(range(2009, 2022))

# FanGraphs team abbreviation → Retrosheet/our team codes
_FANGRAPHS_TEAM_MAP = {
    "NYY": "NYA",
    "NYM": "NYN",
    "CHW": "CHA",
    "CWS": "CHA",
    "CHC": "CHN",
    "LAA": "ANA",
    "LAD": "LAN",
    "TBR": "TBA",
    "TB": "TBA",
    "KCR": "KCA",
    "KC": "KCA",
    "WSN": "WAS",
    "WSH": "WAS",
    "SFG": "SFN",
    "SF": "SFN",
    "SDP": "SDN",
    "SD": "SDN",
    "STL": "SLN",
    "MIA": "MIA",
    "FLA": "FLO",
}


def _map_fg_team(team: str, season: int) -> str:
    """Map FanGraphs team abbreviation to our team codes."""
    t = team.strip().upper()

    # Marlins: FLO before 2012, MIA from 2012
    if t in {"FLA", "FLO", "MIA"}:
        return "FLO" if season <= 2011 else "MIA"

    return _FANGRAPHS_TEAM_MAP.get(t, t)


def pull_season_batting(season: int, *, cache_dir: Path | None = None) -> pd.DataFrame:
    """Pull per-player batting stats for a season from FanGraphs.

    Caches raw data as parquet to avoid re-pulling.
    """
    cache_dir = cache_dir or RAW_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"raw_batting_{season}.parquet"

    if cache_path.exists():
        logger.info(f"  Loading cached {season} batting data")
        return pd.read_parquet(cache_path)

    from pybaseball import batting_stats

    logger.info(f"  Pulling FanGraphs batting stats for {season}...")
    df = batting_stats(season, season, qual=0)

    df.to_parquet(cache_path, index=False)
    logger.info(f"  Cached {len(df)} player rows for {season}")
    return df


def aggregate_team_batting(player_df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Aggregate per-player batting to team level (PA-weighted)."""
    df = player_df.copy()

    # Normalize column names (pybaseball sometimes uses different casing)
    col_map = {c: c.upper() for c in df.columns}
    # Common variants
    for target, alts in [
        ("TEAM", ["Team", "team", "Tm"]),
        ("PA", ["PA", "pa"]),
        ("WRC+", ["wRC+", "WRC+", "wrc+"]),
        ("OBP", ["OBP", "obp"]),
    ]:
        for alt in alts:
            if alt in df.columns:
                col_map[alt] = target
    df = df.rename(columns=col_map)

    # Filter to players with at-bats
    if "PA" not in df.columns:
        raise ValueError(f"PA column not found in FanGraphs data. Columns: {list(df.columns)}")
    df = df[df["PA"] > 0].copy()

    # wRC+ and OBP columns
    for col in ["WRC+", "OBP"]:
        if col not in df.columns:
            raise ValueError(f"{col} column not found. Columns: {list(df.columns)}")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["PA"] = pd.to_numeric(df["PA"], errors="coerce")

    # Group by team, PA-weighted average
    team_groups = df.groupby("TEAM")
    results = []
    for team, grp in team_groups:
        pa_total = grp["PA"].sum()
        if pa_total == 0:
            continue
        wrc_plus = (grp["WRC+"] * grp["PA"]).sum() / pa_total
        obp = (grp["OBP"] * grp["PA"]).sum() / pa_total

        results.append(
            {
                "team_fg": team,
                "team": _map_fg_team(str(team), season),
                "season": season,
                "wrc_plus": round(wrc_plus, 1),
                "obp": round(obp, 4),
                "pa_total": int(pa_total),
            }
        )

    return pd.DataFrame(results)


def build_team_batting_all_seasons(
    seasons: list[int] | None = None,
    *,
    cache_dir: Path | None = None,
    delay_seconds: float = 2.0,
) -> pd.DataFrame:
    """Pull and aggregate FanGraphs team batting for all seasons.

    Returns DataFrame with columns: team, season, wrc_plus, obp, pa_total
    """
    seasons = seasons or PULL_SEASONS
    all_seasons = []

    for i, season in enumerate(seasons):
        player_df = pull_season_batting(season, cache_dir=cache_dir)
        team_df = aggregate_team_batting(player_df, season)
        all_seasons.append(team_df)

        # Rate limit (skip delay for cached)
        cache_path = (cache_dir or RAW_CACHE_DIR) / f"raw_batting_{season}.parquet"
        if i < len(seasons) - 1 and not cache_path.exists():
            time.sleep(delay_seconds)

    result = pd.concat(all_seasons, ignore_index=True)
    logger.info(
        f"FanGraphs team batting: {len(result)} rows, "
        f"seasons {result['season'].min()}-{result['season'].max()}, "
        f"teams per season: {result.groupby('season')['team'].nunique().median():.0f}"
    )
    return result


def validate_team_batting(df: pd.DataFrame) -> dict[str, object]:
    """Run sanity checks on aggregated team batting data."""
    issues = {}
    issues["total_rows"] = len(df)
    issues["seasons"] = sorted(df["season"].unique().tolist())
    issues["teams_per_season"] = df.groupby("season")["team"].nunique().to_dict()

    # wRC+ should center around 100
    wrc_mean = df["wrc_plus"].mean()
    issues["wrc_plus_mean"] = round(wrc_mean, 1)
    issues["wrc_plus_range"] = [round(df["wrc_plus"].min(), 1), round(df["wrc_plus"].max(), 1)]

    # OBP should be in reasonable range
    issues["obp_range"] = [round(df["obp"].min(), 4), round(df["obp"].max(), 4)]

    return issues


def save_team_batting(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Save aggregated team batting to parquet."""
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "team_batting_season.parquet"
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved team batting to {out_path}")
    return out_path
