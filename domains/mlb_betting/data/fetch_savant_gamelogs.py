"""Fetch Statcast pitch-by-pitch data from Baseball Savant via pybaseball.

Downloads monthly chunks, aggregates to pitcher-game level, and caches
to parquet.  Also builds a Retrosheet ↔ MLBAM ID bridge from the
Chadwick register.

Usage:
    python data/fetch_savant_gamelogs.py          # all seasons 2015-2025
    python data/fetch_savant_gamelogs.py --year 2024  # single season
    python data/fetch_savant_gamelogs.py --bridge-only  # just rebuild ID bridge
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pybaseball

pybaseball.cache.enable()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

OUTPUT_DIR = Path(__file__).parent / "processed" / "savant"
SEASONS = [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]

# Month ranges for MLB regular season (April through October).
MONTH_RANGES = [
    ("03-20", "04-30"),
    ("05-01", "05-31"),
    ("06-01", "06-30"),
    ("07-01", "07-31"),
    ("08-01", "08-31"),
    ("09-01", "09-30"),
    ("10-01", "10-15"),
]

# Pitch outcomes that count as swings.
SWING_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "foul",
    "foul_tip",
    "foul_bunt",
    "missed_bunt",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
}
WHIFF_DESCRIPTIONS = {"swinging_strike", "swinging_strike_blocked"}


# ---------------------------------------------------------------------------
# ID Bridge
# ---------------------------------------------------------------------------

def build_id_bridge() -> pd.DataFrame:
    """Build Retrosheet ↔ MLBAM ID mapping from Chadwick register."""
    logger.info("Building ID bridge from Chadwick register ...")
    reg = pybaseball.chadwick_register()
    bridge = reg.dropna(subset=["key_retro", "key_mlbam"])[
        ["name_first", "name_last", "key_retro", "key_mlbam", "mlb_played_first", "mlb_played_last"]
    ].copy()
    bridge["key_mlbam"] = bridge["key_mlbam"].astype(int)
    # Keep only players who played in or after 2010 (overlap with our Retrosheet data).
    bridge = bridge[bridge["mlb_played_last"] >= 2010].reset_index(drop=True)
    logger.info("ID bridge: %d players with both Retrosheet + MLBAM IDs", len(bridge))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "id_bridge.parquet"
    bridge.to_parquet(out_path, index=False)
    logger.info("Saved %s", out_path)
    return bridge


# ---------------------------------------------------------------------------
# Pitch-level fetch + pitcher-game aggregation
# ---------------------------------------------------------------------------

def _aggregate_pitcher_game(pitches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pitch-level Statcast data to one row per pitcher per game.

    Computes: total_pitches, swings, whiffs, whiff_pct,
              batted_balls, avg_exit_velo, hard_hit_pct, barrel_pct, xwoba.
    Also determines pitcher_team from inning_topbot.
    """
    df = pitches.copy()

    # Determine pitcher's team: pitching in Top = home team, Bot = away team.
    df["pitcher_team"] = np.where(
        df["inning_topbot"] == "Top", df["home_team"], df["away_team"]
    )

    # Swing / whiff flags at pitch level.
    df["is_swing"] = df["description"].isin(SWING_DESCRIPTIONS)
    df["is_whiff"] = df["description"].isin(WHIFF_DESCRIPTIONS)

    # Batted ball metrics (only rows with launch_speed).
    df["is_batted"] = df["launch_speed"].notna()
    df["is_hard_hit"] = df["launch_speed"] >= 95.0
    # Savant barrel: launch_speed_angle == 6
    df["is_barrel"] = df["launch_speed_angle"] == 6

    # Group by pitcher + game.
    grp = df.groupby(["pitcher", "game_pk", "game_date", "pitcher_team"], sort=False)

    agg = grp.agg(
        total_pitches=("pitch_type", "count"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        batted_balls=("is_batted", "sum"),
        hard_hits=("is_hard_hit", "sum"),
        barrels=("is_barrel", "sum"),
        xwoba_sum=("estimated_woba_using_speedangle", "sum"),
        xwoba_count=("estimated_woba_using_speedangle", "count"),
        exit_velo_sum=("launch_speed", "sum"),
        exit_velo_count=("launch_speed", "count"),
        min_inning=("inning", "min"),
        max_inning=("inning", "max"),
        home_team=("home_team", "first"),
        away_team=("away_team", "first"),
        player_name=("player_name", "first"),
    ).reset_index()

    # Flag starter vs reliever: pitcher who entered in inning 1 = starter.
    agg["is_starter"] = agg["min_inning"] == 1

    # Compute rates.
    agg["whiff_pct"] = agg["whiffs"] / agg["swings"].replace(0, np.nan)
    agg["hard_hit_pct"] = agg["hard_hits"] / agg["batted_balls"].replace(0, np.nan)
    agg["barrel_pct"] = agg["barrels"] / agg["batted_balls"].replace(0, np.nan)
    agg["xwoba"] = agg["xwoba_sum"] / agg["xwoba_count"].replace(0, np.nan)
    agg["avg_exit_velo"] = agg["exit_velo_sum"] / agg["exit_velo_count"].replace(0, np.nan)

    # Drop intermediate columns.
    agg = agg.drop(columns=["xwoba_sum", "xwoba_count", "exit_velo_sum", "exit_velo_count"])

    return agg


def fetch_season(year: int) -> pd.DataFrame:
    """Fetch all Statcast pitches for a season and aggregate to pitcher-game."""
    logger.info("=== Fetching season %d ===", year)
    chunks = []
    for start_suffix, end_suffix in MONTH_RANGES:
        start_dt = f"{year}-{start_suffix}"
        end_dt = f"{year}-{end_suffix}"
        logger.info("  %s → %s", start_dt, end_dt)
        try:
            chunk = pybaseball.statcast(start_dt, end_dt)
            if chunk is not None and len(chunk) > 0:
                chunks.append(chunk)
                logger.info("    %d pitches", len(chunk))
            else:
                logger.info("    no data")
        except Exception as e:
            logger.warning("    FAILED: %s", e)

    if not chunks:
        logger.warning("No data for season %d", year)
        return pd.DataFrame()

    raw = pd.concat(chunks, ignore_index=True)
    logger.info("  Total raw pitches: %d", len(raw))

    # Aggregate to pitcher-game level.
    pitcher_games = _aggregate_pitcher_game(raw)
    pitcher_games["season"] = year
    logger.info("  Pitcher-game rows: %d", len(pitcher_games))

    # Save.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"pitcher_games_{year}.parquet"
    pitcher_games.to_parquet(out_path, index=False)
    logger.info("  Saved %s", out_path)

    return pitcher_games


def fetch_all(years: list[int] | None = None) -> None:
    """Fetch and aggregate Statcast data for all specified seasons."""
    years = years or SEASONS
    for year in years:
        out_path = OUTPUT_DIR / f"pitcher_games_{year}.parquet"
        if out_path.exists():
            logger.info("Skipping %d — already cached at %s", year, out_path)
            continue
        fetch_season(year)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Savant pitcher game logs")
    parser.add_argument("--year", type=int, help="Single season to fetch")
    parser.add_argument("--bridge-only", action="store_true", help="Only rebuild ID bridge")
    parser.add_argument("--force", action="store_true", help="Refetch even if cached")
    args = parser.parse_args()

    if args.bridge_only:
        build_id_bridge()
        return

    # Always ensure bridge exists.
    bridge_path = OUTPUT_DIR / "id_bridge.parquet"
    if not bridge_path.exists():
        build_id_bridge()

    if args.year:
        if args.force:
            fetch_season(args.year)
        else:
            fetch_all([args.year])
    else:
        fetch_all()


if __name__ == "__main__":
    main()
