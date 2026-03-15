"""Travel and fatigue features from game schedule.

Computes per team per game:
- rest_days: days since team's last game
- travel_miles_3d: cumulative haversine distance in last 3 days
- road_trip_len: consecutive away games entering this game
- tz_changes_3d: timezone crossings in last 3 days

Output: data/processed/schedule/travel_fatigue.parquet
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VENUES_PATH = Path(__file__).parent.parent / "data" / "static" / "venues.json"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed" / "schedule"


def _load_venues(path: Path | None = None) -> dict[str, dict]:
    """Load venue lat/lon/timezone data."""
    path = path or VENUES_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _tz_offset_hours(tz_name: str) -> float:
    """Map timezone name to approximate UTC offset for tz-change counting.

    Only needs relative ordering, not exact offset (which varies with DST).
    """
    tz_map = {
        "America/New_York": -5,
        "America/Detroit": -5,
        "America/Toronto": -5,
        "America/Chicago": -6,
        "America/Denver": -7,
        "America/Phoenix": -7,  # No DST, but same offset as Mountain
        "America/Los_Angeles": -8,
    }
    return tz_map.get(tz_name, -5)  # default Eastern


def build_team_schedule(games: pd.DataFrame) -> pd.DataFrame:
    """Build team-level schedule from game-level data.

    Each row = one team in one game, with venue info.
    """
    home = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "team": games["home_team"].values,
            "is_home": True,
            "venue_team": games["home_team"].values,  # game played at home team's venue
        }
    )
    away = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "team": games["away_team"].values,
            "is_home": False,
            "venue_team": games["home_team"].values,  # away team travels to home team's venue
        }
    )
    schedule = pd.concat([home, away], ignore_index=True)
    schedule = schedule.sort_values(["team", "date"]).reset_index(drop=True)
    return schedule


def compute_travel_features(
    games: pd.DataFrame,
    *,
    venues_path: Path | None = None,
) -> pd.DataFrame:
    """Compute travel and fatigue features for each team-game.

    Returns DataFrame with: team, season, date, rest_days, travel_miles_3d,
    road_trip_len, tz_changes_3d
    """
    venues = _load_venues(venues_path)
    schedule = build_team_schedule(games)

    results = []

    for team, grp in schedule.groupby("team", sort=False):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        dates = grp["date"].values
        venue_teams = grp["venue_team"].values
        is_home = grp["is_home"].values

        for i in range(n):
            game_date = dates[i]
            venue = venue_teams[i]

            # Rest days
            if i == 0:
                rest_days = np.nan
            else:
                delta = pd.Timestamp(game_date) - pd.Timestamp(dates[i - 1])
                rest_days = max(0, delta.days - 1)  # 0 = back-to-back

            # Travel miles in last 3 days
            travel_miles = 0.0
            tz_changes = 0
            if i > 0:
                prev_venue = venue_teams[i - 1]
                d3_start = pd.Timestamp(game_date) - pd.Timedelta(days=3)

                # Walk backward through recent games
                prev_tz = None
                for j in range(i - 1, -1, -1):
                    if pd.Timestamp(dates[j]) < d3_start:
                        break
                    v_from = venue_teams[j]
                    v_to = venue_teams[min(j + 1, i)] if j < i else venue

                    if v_from in venues and v_to in venues and v_from != v_to:
                        travel_miles += _haversine_miles(
                            venues[v_from]["lat"],
                            venues[v_from]["lon"],
                            venues[v_to]["lat"],
                            venues[v_to]["lon"],
                        )

                    # Timezone changes
                    cur_tz = venues.get(venue_teams[j], {}).get("timezone")
                    if cur_tz and prev_tz and cur_tz != prev_tz:
                        tz_changes += 1
                    prev_tz = cur_tz

                # Also count transition from last 3d game to current game venue
                if venue in venues and prev_venue in venues:
                    cur_tz = venues.get(venue, {}).get("timezone")
                    prev_game_tz = venues.get(prev_venue, {}).get("timezone")
                    if cur_tz and prev_game_tz and cur_tz != prev_game_tz:
                        tz_changes += 1

            # Road trip length (consecutive away games entering this game)
            road_trip_len = 0
            if i > 0:
                for j in range(i - 1, -1, -1):
                    if is_home[j]:
                        break
                    road_trip_len += 1

            results.append(
                {
                    "team": team,
                    "season": grp.iloc[i]["season"],
                    "date": game_date,
                    "rest_days": rest_days,
                    "travel_miles_3d": round(travel_miles, 1),
                    "road_trip_len": road_trip_len,
                    "tz_changes_3d": tz_changes,
                }
            )

    df = pd.DataFrame(results)
    logger.info(f"Travel features: {len(df)} rows, {df['team'].nunique()} teams")
    return df


def save_travel_features(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "travel_fatigue.parquet"
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved travel features to {out_path}")
    return out_path
