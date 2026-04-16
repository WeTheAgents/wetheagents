"""Download historical MLB odds data from multiple sources.

Sources:
  - SportsDatabase.com SDQL API: 2004-2009, 2022-2025 (moneyline, total, scores, starters)
  - ArnavSaraogi/mlb-odds-scraper JSON: 2022-2025 (multi-book moneyline, spread, totals)
  - sports-statistics.com xlsx: 2010-2019, 2021 (existing, handled by download.py)

Output: xlsx files in data/raw/odds/ matching the existing column schema.

Usage:
    python data/download_historical.py          # download all new seasons
    python data/download_historical.py --sdql   # SDQL only (2004-2009, 2022-2025)
    python data/download_historical.py --json   # ArnavSaraogi JSON only (2022-2025)
"""

import json
import time
import urllib.parse
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

RAW_DIR = Path(__file__).parent / "raw" / "odds"
EXTERNAL_DIR = Path(__file__).parent / "raw" / "external"

# 2020 excluded (COVID). 2010-2019, 2021 already covered by download.py.
SDQL_SEASONS = [2004, 2005, 2006, 2007, 2008, 2009, 2022, 2023, 2024, 2025]
JSON_SEASONS = [2022, 2023, 2024, 2025]

# SDQL uses full nicknames; map to 3-letter codes used in our xlsx files.
NICKNAME_TO_ABBR = {
    "Angels": "LAA",
    "Astros": "HOU",
    "Athletics": "OAK",
    "Blue Jays": "TOR",
    "Braves": "ATL",
    "Brewers": "MIL",
    "Cardinals": "STL",
    "Cubs": "CHC",
    "Diamondbacks": "ARI",
    "Dodgers": "LAD",
    "Giants": "SFG",
    "Guardians": "CLE",
    "Indians": "CLE",
    "Mariners": "SEA",
    "Marlins": "MIA",
    "Mets": "NYM",
    "Nationals": "WSN",
    "Expos": "MON",
    "Orioles": "BAL",
    "Padres": "SDP",
    "Phillies": "PHI",
    "Pirates": "PIT",
    "Rangers": "TEX",
    "Rays": "TBR",
    "Devil Rays": "TBD",
    "Red Sox": "BOS",
    "Reds": "CIN",
    "Rockies": "COL",
    "Royals": "KCR",
    "Tigers": "DET",
    "Twins": "MIN",
    "White Sox": "CHW",
    "Yankees": "NYY",
}

# ArnavSaraogi JSON uses shortName field; map any non-standard to our codes.
SHORT_NAME_TO_ABBR = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CHW": "CHW", "CIN": "CIN", "CLE": "CLE",
    "COL": "COL", "DET": "DET", "HOU": "HOU", "KC": "KCR",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL",
    "MIN": "MIN", "NYM": "NYM", "NYY": "NYY", "OAK": "OAK",
    "PHI": "PHI", "PIT": "PIT", "SD": "SDP", "SF": "SFG",
    "SEA": "SEA", "STL": "STL", "TB": "TBR", "TEX": "TEX",
    "TOR": "TOR", "WSH": "WSN", "WAS": "WSN",
    # Athletics renamed Sacramento Athletics 2025, same franchise
    "ATH": "OAK",
    # Fallback identity mappings
    "AZ": "ARI", "WSN": "WSN", "KCR": "KCR", "SDP": "SDP",
    "SFG": "SFG", "TBR": "TBR",
}

# Target xlsx column order (must match XLSX_COLUMNS in data_loader.py)
XLSX_COLUMNS = [
    "date", "rot", "vh", "team", "pitcher",
    "inn_1", "inn_2", "inn_3", "inn_4", "inn_5",
    "inn_6", "inn_7", "inn_8", "inn_9", "final",
    "open_ml", "close_ml",
    "run_line", "run_line_odds",
    "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
]


# ---------------------------------------------------------------------------
# SDQL scraper
# ---------------------------------------------------------------------------

def _sdql_query(sdql: str, retries: int = 4) -> dict:
    """Execute an SDQL query against sportsdatabase.com and return parsed JSON."""
    base = "https://sportsdatabase.com/MLB/query"
    params = {"sdql": sdql, "output": "json"}
    url = f"{base}?{urllib.parse.urlencode(params)}"

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "mlb-backtest/1.0"})
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    [RETRY] attempt {attempt+1} failed: {e}, waiting {wait}s")
                time.sleep(wait)
            else:
                raise


def _sdql_to_dataframe(result: dict) -> pd.DataFrame:
    """Convert SDQL JSON result to DataFrame."""
    headers = result.get("headers", [])
    groups = result.get("groups", [])
    if not headers or not groups:
        return pd.DataFrame()

    columns = groups[0].get("columns", [])
    if not columns:
        return pd.DataFrame()

    data = {h: columns[i] for i, h in enumerate(headers)}
    return pd.DataFrame(data)


def download_sdql_season(season: int) -> pd.DataFrame:
    """Download a full season from SDQL and return as DataFrame with 2-row-per-game format."""
    print(f"  [SDQL] Downloading season {season}...")

    sdql = f"date, team, o:team, line, o:line, total, site, runs, o:runs, starter @ season={season}"
    result = _sdql_query(sdql)
    df = _sdql_to_dataframe(result)

    if df.empty:
        print(f"  [WARN] No SDQL data for {season}")
        return pd.DataFrame(columns=XLSX_COLUMNS)

    print(f"  [OK] {len(df)} team-game rows from SDQL")

    # Map team names to abbreviations
    df["team_abbr"] = df["team"].map(NICKNAME_TO_ABBR)
    df["opp_abbr"] = df["o:team"].map(NICKNAME_TO_ABBR)
    unmapped = df[df["team_abbr"].isna()]["team"].unique()
    if len(unmapped) > 0:
        print(f"  [WARN] Unmapped teams: {unmapped}")

    # Parse SDQL date (YYYYMMDD int) to MMDD
    df["date_mmdd"] = df["date"] % 10000  # e.g., 20050404 -> 504 (but we want MMDD)
    df["month"] = (df["date"] % 10000) // 100
    df["day"] = df["date"] % 100
    df["date_mmdd"] = df["month"] * 100 + df["day"]  # e.g., 404

    # Site to vh
    df["vh"] = df["site"].map({"home": "H", "away": "V"})

    # Build output matching xlsx schema
    out = pd.DataFrame()
    out["date"] = df["date_mmdd"]
    # Rotation number: SDQL doesn't provide it, use sequential pairs
    out["rot"] = 0
    out["vh"] = df["vh"]
    out["team"] = df["team_abbr"]
    out["pitcher"] = df["starter"]  # May be None for older years
    for i in range(1, 10):
        out[f"inn_{i}"] = 0  # SDQL doesn't provide inning-by-inning
    out["final"] = df["runs"]
    out["open_ml"] = np.nan  # SDQL line is closing line
    out["close_ml"] = df["line"]
    out["run_line"] = np.nan
    out["run_line_odds"] = np.nan
    out["open_ou"] = np.nan
    out["open_ou_odds"] = np.nan
    out["close_ou"] = df["total"]
    out["close_ou_odds"] = np.nan

    # Assign rotation numbers (sequential pairs: 901/902, 903/904, etc.)
    # Group by date, then assign pairs
    out = out.reset_index(drop=True)
    rot_counter = {}
    rots = []
    for _, row in out.iterrows():
        d = row["date"]
        if d not in rot_counter:
            rot_counter[d] = 901
        rots.append(rot_counter[d])
        rot_counter[d] += 1
    out["rot"] = rots

    # Sort: visitors first, then home within each date
    # SDQL gives one row per team per game. We need V then H pairs.
    # Sort by date, then by rotation to keep pairs together
    out = out.sort_values(["date", "rot"]).reset_index(drop=True)

    return out


# ---------------------------------------------------------------------------
# ArnavSaraogi JSON converter
# ---------------------------------------------------------------------------

def convert_arnav_json_season(json_path: Path, season: int) -> pd.DataFrame:
    """Convert ArnavSaraogi JSON dataset for a single season to xlsx format."""
    print(f"  [JSON] Converting season {season}...")

    with open(json_path) as f:
        data = json.load(f)

    rows = []
    for date_str, games in data.items():
        # Filter by season year
        year = int(date_str[:4])
        if year != season:
            continue

        month = int(date_str[5:7])
        day = int(date_str[8:10])
        date_mmdd = month * 100 + day

        for game in games:
            gv = game.get("gameView", {})
            odds = game.get("odds", {})

            # Skip non-regular-season games
            if gv.get("gameType") != "R":
                continue
            # Skip games that haven't finished
            status = gv.get("gameStatusText", "")
            if "Final" not in status:
                continue

            away_team = gv.get("awayTeam", {})
            home_team = gv.get("homeTeam", {})

            away_abbr = SHORT_NAME_TO_ABBR.get(
                away_team.get("shortName", ""), away_team.get("shortName", "")
            )
            home_abbr = SHORT_NAME_TO_ABBR.get(
                home_team.get("shortName", ""), home_team.get("shortName", "")
            )

            away_score = gv.get("awayTeamScore")
            home_score = gv.get("homeTeamScore")

            # Extract moneyline odds (prefer DraftKings, then consensus)
            ml_data = odds.get("moneyline", [])
            home_open_ml = np.nan
            home_close_ml = np.nan
            away_open_ml = np.nan
            away_close_ml = np.nan

            # Priority order for bookmakers
            book_priority = ["draftkings", "fanduel", "bet365", "caesars", "betmgm", "betrivers"]
            for book_name in book_priority:
                for entry in ml_data:
                    if entry.get("sportsbook") == book_name:
                        opening = entry.get("openingLine", {})
                        closing = entry.get("currentLine", {})
                        if pd.isna(home_close_ml) and closing.get("homeOdds") is not None:
                            home_close_ml = closing["homeOdds"]
                            away_close_ml = closing["awayOdds"]
                        if pd.isna(home_open_ml) and opening.get("homeOdds") is not None:
                            home_open_ml = opening["homeOdds"]
                            away_open_ml = opening["awayOdds"]
                        break
                if not pd.isna(home_close_ml):
                    break

            # Extract totals
            totals_data = odds.get("totals", [])
            close_ou = np.nan
            for book_name in book_priority:
                for entry in totals_data:
                    if entry.get("sportsbook") == book_name:
                        closing = entry.get("currentLine", {})
                        if closing.get("total") is not None:
                            close_ou = closing["total"]
                            break
                if not pd.isna(close_ou):
                    break

            # Extract point spread (run line)
            spread_data = odds.get("pointspread", [])
            home_run_line = np.nan
            home_run_line_odds = np.nan
            away_run_line_odds = np.nan
            for book_name in book_priority:
                for entry in spread_data:
                    if entry.get("sportsbook") == book_name:
                        closing = entry.get("currentLine", {})
                        if closing.get("homeSpread") is not None:
                            home_run_line = closing["homeSpread"]
                            home_run_line_odds = closing.get("homeOdds", np.nan)
                            away_run_line_odds = closing.get("awayOdds", np.nan)
                            break
                if not pd.isna(home_run_line):
                    break

            # Create visitor row
            rows.append({
                "date": date_mmdd, "rot": 0, "vh": "V",
                "team": away_abbr, "pitcher": "",
                **{f"inn_{i}": 0 for i in range(1, 10)},
                "final": away_score,
                "open_ml": away_open_ml, "close_ml": away_close_ml,
                "run_line": -home_run_line if not pd.isna(home_run_line) else np.nan,
                "run_line_odds": away_run_line_odds,
                "open_ou": np.nan, "open_ou_odds": np.nan,
                "close_ou": close_ou, "close_ou_odds": np.nan,
            })

            # Create home row
            rows.append({
                "date": date_mmdd, "rot": 0, "vh": "H",
                "team": home_abbr, "pitcher": "",
                **{f"inn_{i}": 0 for i in range(1, 10)},
                "final": home_score,
                "open_ml": home_open_ml, "close_ml": home_close_ml,
                "run_line": home_run_line,
                "run_line_odds": home_run_line_odds,
                "open_ou": np.nan, "open_ou_odds": np.nan,
                "close_ou": close_ou, "close_ou_odds": np.nan,
            })

    if not rows:
        print(f"  [WARN] No JSON data for season {season}")
        return pd.DataFrame(columns=XLSX_COLUMNS)

    df = pd.DataFrame(rows)

    # Assign rotation numbers
    rot_counter = {}
    rots = []
    for _, row in df.iterrows():
        d = row["date"]
        if d not in rot_counter:
            rot_counter[d] = 901
        rots.append(rot_counter[d])
        rot_counter[d] += 1
    df["rot"] = rots

    df = df.sort_values(["date", "rot"]).reset_index(drop=True)
    df = df[XLSX_COLUMNS]
    print(f"  [OK] {len(df)} team-game rows from JSON ({len(df)//2} games)")
    return df


# ---------------------------------------------------------------------------
# Merge SDQL + JSON for best quality (2022-2025)
# ---------------------------------------------------------------------------

def merge_sdql_and_json(sdql_df: pd.DataFrame, json_df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Merge SDQL and JSON data for 2022-2025 seasons.

    Strategy: use JSON as primary (has multi-book odds, run lines, open/close lines)
    and fill missing pitchers from SDQL starter data.
    """
    if json_df.empty:
        return sdql_df
    if sdql_df.empty:
        return json_df

    # JSON has better odds data (open + close, run line, multi-book)
    # SDQL has pitcher names
    # Use JSON as base, merge pitcher names from SDQL

    # Build a lookup: (date_mmdd, team_abbr) -> pitcher from SDQL
    pitcher_lookup = {}
    for _, row in sdql_df.iterrows():
        key = (int(row["date"]), str(row["team"]))
        if pd.notna(row["pitcher"]) and row["pitcher"]:
            pitcher_lookup[key] = row["pitcher"]

    result = json_df.copy()
    filled = 0
    for idx, row in result.iterrows():
        if pd.isna(row["pitcher"]) or row["pitcher"] == "":
            key = (int(row["date"]), str(row["team"]))
            if key in pitcher_lookup:
                result.at[idx, "pitcher"] = pitcher_lookup[key]
                filled += 1

    if filled > 0:
        print(f"  [MERGE] Filled {filled} pitcher names from SDQL into JSON data")

    return result


# ---------------------------------------------------------------------------
# Save to xlsx
# ---------------------------------------------------------------------------

def save_season_xlsx(df: pd.DataFrame, season: int, output_dir: Path) -> Path:
    """Save a season DataFrame to xlsx matching the existing format."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"mlb-odds-{season}.xlsx"
    df = df[XLSX_COLUMNS].copy()
    df.to_excel(filepath, index=False, header=True)
    size_kb = filepath.stat().st_size / 1024
    print(f"  [SAVE] {filepath.name} ({size_kb:.0f} KB, {len(df)} rows)")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Download historical MLB odds")
    parser.add_argument("--sdql", action="store_true", help="SDQL only")
    parser.add_argument("--json", action="store_true", help="ArnavSaraogi JSON only")
    parser.add_argument("--seasons", type=int, nargs="+", help="Specific seasons")
    args = parser.parse_args()

    do_sdql = args.sdql or (not args.sdql and not args.json)
    do_json = args.json or (not args.sdql and not args.json)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    json_path = EXTERNAL_DIR / "mlb_odds_dataset.json"
    has_json = json_path.exists()

    # Determine which seasons to process
    if args.seasons:
        seasons = args.seasons
    else:
        seasons = sorted(set(SDQL_SEASONS + JSON_SEASONS))

    print(f"Processing seasons: {seasons}")
    print(f"Sources: SDQL={'yes' if do_sdql else 'no'}, JSON={'yes' if do_json and has_json else 'no'}")
    print()

    downloaded = 0
    for season in seasons:
        existing = RAW_DIR / f"mlb-odds-{season}.xlsx"
        if existing.exists():
            print(f"  [SKIP] {existing.name} already exists")
            downloaded += 1
            continue

        print(f"\n--- Season {season} ---")

        sdql_df = pd.DataFrame(columns=XLSX_COLUMNS)
        json_df = pd.DataFrame(columns=XLSX_COLUMNS)

        # SDQL
        if do_sdql and season in SDQL_SEASONS:
            try:
                sdql_df = download_sdql_season(season)
                time.sleep(1.5)  # Be polite
            except Exception as e:
                print(f"  [ERR] SDQL failed for {season}: {e}")

        # JSON (only for 2022-2025)
        if do_json and has_json and season in JSON_SEASONS:
            try:
                json_df = convert_arnav_json_season(json_path, season)
            except Exception as e:
                print(f"  [ERR] JSON conversion failed for {season}: {e}")

        # Merge or pick best source
        if season in JSON_SEASONS and not json_df.empty:
            final_df = merge_sdql_and_json(sdql_df, json_df, season)
        elif not sdql_df.empty:
            final_df = sdql_df
        else:
            print(f"  [SKIP] No data available for {season}")
            continue

        if len(final_df) < 100:
            print(f"  [WARN] Only {len(final_df)} rows for {season}, skipping (likely incomplete)")
            continue

        save_season_xlsx(final_df, season, RAW_DIR)
        downloaded += 1

    print(f"\nDone! Processed {downloaded}/{len(seasons)} seasons.")


if __name__ == "__main__":
    main()
