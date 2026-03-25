"""Download Turkish Super Lig lineup and appearance data from transfermarkt-datasets.

Source: https://github.com/dcaribou/transfermarkt-datasets
Data hosted at: https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/

Downloads three tables:
  - games.csv.gz: match results, club IDs, formations
  - game_lineups.csv.gz: starting XI + substitutes per match
  - appearances.csv.gz: per-player per-match minutes, goals, assists

Filters to Turkish Super Lig (competition_id = 'TR1') and saves as parquet.

Usage:
    python data/download_transfermarkt.py
"""

from pathlib import Path

import httpx
import pandas as pd
from io import BytesIO

RAW_DIR = Path(__file__).parent / "raw" / "transfermarkt"
BASE_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"

COMPETITION_ID = "TR1"
TARGET_SEASONS = list(range(2012, 2024))  # 2012-2023

TABLES = {
    "games": "games.csv.gz",
    "game_lineups": "game_lineups.csv.gz",
    "appearances": "appearances.csv.gz",
}


def download_table(name: str, filename: str) -> pd.DataFrame:
    """Download a single table from transfermarkt-datasets."""
    cache_path = RAW_DIR / filename
    url = f"{BASE_URL}/{filename}"

    if cache_path.exists():
        size_mb = cache_path.stat().st_size / 1024 / 1024
        print(f"  [CACHE] {filename} ({size_mb:.1f} MB)")
        return pd.read_csv(cache_path, compression="gzip", low_memory=False)

    print(f"  [DL] Downloading {filename}...")
    headers = {"User-Agent": "football-betting-backtest/1.0"}

    with httpx.Client(timeout=300, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    # Save raw gzip for caching
    cache_path.write_bytes(response.content)
    size_mb = len(response.content) / 1024 / 1024
    print(f"  [OK] {filename} ({size_mb:.1f} MB)")

    return pd.read_csv(BytesIO(response.content), compression="gzip", low_memory=False)


def filter_and_save(
    games: pd.DataFrame,
    lineups: pd.DataFrame,
    appearances: pd.DataFrame,
) -> None:
    """Filter to Turkish Super Lig target seasons and save as parquet."""
    # Filter games
    tr1_games = games[
        (games["competition_id"] == COMPETITION_ID)
        & (games["season"].isin(TARGET_SEASONS))
    ].copy()
    print(f"\n  TR1 games (target seasons): {len(tr1_games)}")

    # Get game IDs for filtering
    tr1_game_ids = set(tr1_games["game_id"])

    # Filter lineups
    tr1_lineups = lineups[lineups["game_id"].isin(tr1_game_ids)].copy()
    starters = tr1_lineups[tr1_lineups["type"] == "starting_lineup"]
    print(f"  TR1 lineups: {len(tr1_lineups)} total, {len(starters)} starters")

    # Filter appearances
    tr1_appearances = appearances[appearances["game_id"].isin(tr1_game_ids)].copy()
    print(f"  TR1 appearances: {len(tr1_appearances)}")
    print(f"    minutes_played: {tr1_appearances['minutes_played'].notna().sum()} non-null")
    print(f"    goals: {tr1_appearances['goals'].sum():.0f} total")
    print(f"    assists: {tr1_appearances['assists'].sum():.0f} total")

    # Save as parquet
    output_dir = RAW_DIR / "filtered"
    output_dir.mkdir(parents=True, exist_ok=True)

    tr1_games.to_parquet(output_dir / "games.parquet", index=False)
    tr1_lineups.to_parquet(output_dir / "game_lineups.parquet", index=False)
    tr1_appearances.to_parquet(output_dir / "appearances.parquet", index=False)

    print(f"\n  Saved to {output_dir}/")

    # Per-season summary
    print("\n  Per-season coverage:")
    for season in TARGET_SEASONS:
        sg = tr1_games[tr1_games["season"] == season]
        sa = tr1_appearances[tr1_appearances["game_id"].isin(set(sg["game_id"]))]
        sl = starters[starters["game_id"].isin(set(sg["game_id"]))]
        print(
            f"    {season}: {len(sg)} games, "
            f"{len(sl)} starters, "
            f"{len(sa)} appearances"
        )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading transfermarkt-datasets for Turkish Super Lig")
    print(f"Seasons: {TARGET_SEASONS}")
    print()

    # Download tables
    all_data = {}
    for name, filename in TABLES.items():
        all_data[name] = download_table(name, filename)

    # Filter and save
    filter_and_save(
        all_data["games"],
        all_data["game_lineups"],
        all_data["appearances"],
    )

    print("\nDone!")


if __name__ == "__main__":
    main()
