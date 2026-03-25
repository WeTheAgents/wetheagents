"""Download Turkish Super Lig odds data from football-data.co.uk.

Downloads per-season CSVs with match results + closing odds.
Turkish Super Lig uses per-season files at mmz4281/{SSSS}/T1.csv.

Column key (football-data.co.uk classic format):
  Div, Date, Time, HomeTeam, AwayTeam,
  FTHG/FTAG (full-time goals), FTR (full-time result H/D/A),
  HTHG/HTAG/HTR (half-time),
  PSH/PSD/PSA (Pinnacle closing home/draw/away),
  B365H/B365D/B365A (Bet365),
  AvgH/AvgD/AvgA (market average)

Turkish Super Lig season runs August-May (European calendar).
Season code "2122" = 2021-2022 season, mapped to year=2021.

Usage:
    python data/download_odds.py
"""

import time
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).parent / "raw" / "odds"

# Season code -> year mapping (use start year as canonical season ID)
SEASONS = {
    "1213": 2012,
    "1314": 2013,
    "1415": 2014,
    "1516": 2015,
    "1617": 2016,
    "1718": 2017,
    "1819": 2018,
    "1920": 2019,
    "2021": 2020,
    "2122": 2021,
    "2223": 2022,
    "2324": 2023,
}

BASE_URL = "https://www.football-data.co.uk/mmz4281"


def download_season(season_code: str, output_dir: Path) -> Path:
    """Download a single season's odds CSV."""
    url = f"{BASE_URL}/{season_code}/T1.csv"
    filename = f"T1_{season_code}.csv"
    output_path = output_dir / filename

    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"  [OK] {filename} already exists ({size_kb:.0f} KB), skipping")
        return output_path

    print(f"  [DL] Downloading {filename}...")
    headers = {"User-Agent": "football-betting-backtest/1.0"}

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    output_path.write_bytes(response.content)
    size_kb = len(response.content) / 1024
    print(f"  [OK] {filename} ({size_kb:.0f} KB)")
    return output_path


def validate_season(csv_path: Path, season_year: int) -> int:
    """Check match count and odds coverage for a season."""
    import pandas as pd

    df = pd.read_csv(csv_path)
    n = len(df)
    pinnacle = df["PSH"].notna().sum() if "PSH" in df.columns else 0
    status = "OK" if pinnacle >= n * 0.9 else "LOW"
    print(f"    {season_year}: {n} matches, {pinnacle} with Pinnacle odds [{status}]")
    return n


def main() -> None:
    """Download and validate all seasons."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading Turkish Super Lig odds from football-data.co.uk")
    print(f"Seasons: {list(SEASONS.values())}")
    print()

    total = 0
    for code, year in SEASONS.items():
        try:
            path = download_season(code, RAW_DIR)
            total += validate_season(path, year)
            time.sleep(1.0)
        except Exception as e:
            print(f"  [ERR] Season {year}: {e}")

    print(f"\nDone! {total} total matches.")


if __name__ == "__main__":
    main()
