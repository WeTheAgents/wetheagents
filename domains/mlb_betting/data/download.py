"""Download historical MLB odds data from sports-statistics.com.

Downloads xlsx files for seasons 2010-2019 and 2021 (2020 excluded — COVID).
Files are saved to data/raw/odds/.

For additional seasons (2004-2009, 2022-2025), use:
    python data/download_historical.py

Usage:
    python data/download.py
"""

import time
from pathlib import Path

import httpx

BASE_URL = "https://sports-statistics.com/database/mlb-data"
RAW_DIR = Path(__file__).parent / "raw" / "odds"

# 2020 excluded — COVID season (60 games, 7-inning DH, runner on 2nd in extras)
SEASONS = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021]


def download_season(season: int, output_dir: Path) -> Path:
    """Download a single season's odds xlsx file."""
    filename = f"mlb-odds-{season}.xlsx"
    url = f"{BASE_URL}/{filename}"
    output_path = output_dir / filename

    if output_path.exists():
        print(f"  [OK] {filename} already exists, skipping")
        return output_path

    print(f"  [DL] Downloading {filename}...")
    headers = {"User-Agent": "mlb-betting-backtest/1.0"}

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

        output_path.write_bytes(response.content)
        size_kb = len(response.content) / 1024
        print(f"  [OK] {filename} ({size_kb:.0f} KB)")
        return output_path

    except httpx.HTTPError as e:
        print(f"  [ERR] Failed to download {filename}: {e}")
        raise


def main() -> None:
    """Download all seasons."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading MLB odds data to {RAW_DIR}")
    print(f"Seasons: {SEASONS} ({len(SEASONS)} seasons, 2020 excluded)")
    print()

    downloaded = 0
    for season in SEASONS:
        try:
            download_season(season, RAW_DIR)
            downloaded += 1
            # Be polite to the server
            time.sleep(1.0)
        except Exception:
            print(f"  Skipping {season} due to error")

    print(f"\nDone! Downloaded {downloaded}/{len(SEASONS)} seasons.")


if __name__ == "__main__":
    main()
