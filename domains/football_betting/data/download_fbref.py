"""Download FBref data for Brazilian Serie A via soccerdata.

Fetches starting lineups and player match stats (xG, xA, tackles, interceptions).
Brazilian Serie A season = calendar year (April-December).

Requires custom league config — this script creates it automatically.
FBref Opta data available from ~2018 for this league.

Rate limiting: soccerdata handles caching in ~/soccerdata/data/FBref/.
First download is slow (~5-10 min per season); subsequent runs use cache.

Usage:
    python data/download_fbref.py
    python data/download_fbref.py --seasons 2023  # single season
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent / "raw" / "fbref"
TARGET_SEASONS = [2021, 2022, 2023]

# soccerdata custom league config
LEAGUE_DICT_ENTRY = {
    "BRA-Serie A": {
        "FBref": "Campeonato Brasileiro Série A",
        "season_start": "Apr",
        "season_end": "Dec",
    }
}


def ensure_league_config() -> None:
    """Create soccerdata custom league config if not present."""
    config_dir = Path.home() / "soccerdata" / "config"
    config_file = config_dir / "league_dict.json"

    if config_file.exists():
        existing = json.loads(config_file.read_text(encoding="utf-8"))
        if "BRA-Serie A" in existing:
            print("  [OK] BRA-Serie A already in league config")
            return
        # Merge our entry
        existing.update(LEAGUE_DICT_ENTRY)
        config_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        print("  [OK] Added BRA-Serie A to existing league config")
    else:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            json.dumps(LEAGUE_DICT_ENTRY, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  [OK] Created league config at {config_file}")


def download_season(season: int) -> dict[str, pd.DataFrame]:
    """Download all FBref data for a single season.

    Returns dict with keys: 'schedule', 'summary', 'defense'.
    Lineups are extracted from player match stats (is_starter flag).
    """
    import soccerdata as sd

    fbref = sd.FBref(leagues="BRA-Serie A", seasons=season)

    result = {}

    # 1. Match schedule (results + scores)
    print(f"    Fetching schedule for {season}...")
    try:
        schedule = fbref.read_schedule()
        result["schedule"] = schedule
        print(f"    [OK] Schedule: {len(schedule)} matches")
    except Exception as e:
        print(f"    [ERR] Schedule: {e}")
        return result

    # 2. Player match stats — summary (minutes, goals, xG, xA)
    print(f"    Fetching player summary stats for {season}...")
    try:
        summary = fbref.read_player_match_stats(stat_type="summary")
        result["summary"] = summary
        n_players = len(summary)
        n_matches = summary.index.get_level_values("game").nunique() if n_players > 0 else 0
        print(f"    [OK] Summary: {n_players} player-match rows across {n_matches} matches")
    except Exception as e:
        print(f"    [ERR] Summary stats: {e}")

    # 3. Player match stats — defense (tackles, interceptions)
    print(f"    Fetching player defense stats for {season}...")
    try:
        defense = fbref.read_player_match_stats(stat_type="defense")
        result["defense"] = defense
        print(f"    [OK] Defense: {len(defense)} player-match rows")
    except Exception as e:
        print(f"    [ERR] Defense stats: {e}")

    return result


def save_season(season: int, data: dict[str, pd.DataFrame]) -> None:
    """Save season data as parquet files."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for key, df in data.items():
        path = RAW_DIR / f"{key}_{season}.parquet"
        df.to_parquet(path)
        print(f"    [SAVE] {path.name} ({len(df)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download FBref data for BRA Serie A")
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=TARGET_SEASONS,
        help=f"Seasons to download (default: {TARGET_SEASONS})",
    )
    args = parser.parse_args()

    print("Downloading FBref data for Brazilian Serie A")
    print(f"Seasons: {args.seasons}")
    print()

    # Step 1: ensure league config
    print("Step 1: Checking soccerdata league config...")
    ensure_league_config()
    print()

    # Step 2: check soccerdata import
    print("Step 2: Checking soccerdata installation...")
    try:
        import soccerdata as sd

        print(f"  [OK] soccerdata {sd.__version__}")
    except ImportError:
        print("  [ERR] soccerdata not installed. Run: pip install soccerdata")
        sys.exit(1)
    print()

    # Step 3: download each season
    for season in args.seasons:
        print(f"Step 3: Downloading season {season}...")
        try:
            data = download_season(season)
            if data:
                save_season(season, data)
                print(f"  [OK] Season {season} complete\n")
            else:
                print(f"  [WARN] No data for season {season}\n")
        except Exception as e:
            print(f"  [ERR] Season {season} failed: {e}\n")

    print("Done!")


if __name__ == "__main__":
    main()
