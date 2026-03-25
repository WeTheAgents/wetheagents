"""Load and join Turkish Super Lig data from football-data.co.uk + transfermarkt-datasets.

Pipeline:
  1. Load odds CSVs (per-season) -> standardize columns, parse dates
  2. Load transfermarkt games/lineups/appearances -> build per-match lineup structures
  3. Join on (date, home_team, away_team) via canonical team mapping
  4. Apply data quality filters
  5. Derive implied probabilities from closing odds

Output schema (one row per match):
  season, date, round, home_team, away_team (canonical codes)
  home_goals, away_goals, result (H/D/A)
  home_win, draw, away_win (bool)
  home_odds, draw_odds, away_odds (Pinnacle closing or avg fallback)
  home_implied, draw_implied, away_implied (vig-removed)
  home_implied_ppg, away_implied_ppg
  has_lineup_data (bool)
  home_lineup, away_lineup (list of player dicts when available)

Usage:
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds

    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
RAW_ODDS_DIR = DATA_DIR / "raw" / "odds"
RAW_TM_DIR = DATA_DIR / "raw" / "transfermarkt" / "filtered"

DEFAULT_SEASONS = list(range(2012, 2024))  # 2012-2023

# Season code mapping for football-data.co.uk per-season CSVs
SEASON_CODES = {
    2012: "1213", 2013: "1314", 2014: "1415", 2015: "1516",
    2016: "1617", 2017: "1718", 2018: "1819", 2019: "1920",
    2020: "2021", 2021: "2122", 2022: "2223", 2023: "2324",
}


# ---------------------------------------------------------------------------
# Team name mapping: football-data.co.uk <-> transfermarkt
# ---------------------------------------------------------------------------

# football-data.co.uk name -> canonical code
_ODDS_TO_CODE = {
    "Ad. Demirspor": "ADS",
    "Alanyaspor": "ALN",
    "Altay": "ALT",
    "Ankaragucu": "ANK",
    "Antalyaspor": "ANT",
    "Besiktas": "BJK",
    "Buyuksehyr": "IBB",
    "Fenerbahce": "FB",
    "Galatasaray": "GS",
    "Gaziantep": "GFK",
    "Giresunspor": "GIR",
    "Goztep": "GOZ",
    "Hatayspor": "HTS",
    "Istanbulspor": "IST",
    "Karagumruk": "FKK",
    "Kasimpasa": "KSM",
    "Kayserispor": "KYS",
    "Konyaspor": "KON",
    "Pendikspor": "PEN",
    "Rizespor": "RIZ",
    "Samsunspor": "SAM",
    "Sivasspor": "SVS",
    "Trabzonspor": "TS",
    "Umraniyespor": "UMR",
    "Yeni Malatyaspor": "YML",
    # 2012-2020 teams (promoted/relegated)
    "Adanaspor": "ADA",
    "Akhisar Belediyespor": "AKH",
    "Balikesirspor": "BAL",
    "Bursaspor": "BUR",
    "Denizlispor": "DEN",
    "Elazigspor": "ELZ",
    "Erciyesspor": "ERC",
    "Erzurum BB": "ERZ",
    "Eskisehirspor": "ESK",
    "Gaziantepspor": "GAZ",
    "Genclerbirligi": "GEN",
    "Karabukspor": "KRB",
    "Mersin Idman Yurdu": "MER",
    "Orduspor": "ORD",
    "Osmanlispor": "OSM",
}

# transfermarkt club_id -> canonical code (verified from actual data)
_TM_CLUBID_TO_CODE = {
    36: "FB",       # Fenerbahçe
    114: "BJK",     # Beşiktaş
    126: "RIZ",     # Çaykur Rizespor
    141: "GS",      # Galatasaray
    152: "SAM",     # Samsunspor
    449: "TS",      # Trabzonspor
    589: "ANT",     # Antalyaspor
    868: "ANK",     # MKE Ankaragücü
    924: "IST",     # İstanbulspor
    1467: "GOZ",    # Göztepe
    2293: "KON",    # Konyaspor
    2375: "ALT",    # Altay SK
    2381: "SVS",    # Sivasspor
    2832: "GFK",    # Gaziantep FK
    3205: "KYS",    # Kayserispor
    3209: "PEN",    # Pendikspor
    3840: "ADS",    # Adana Demirspor
    6646: "FKK",    # Fatih Karagümrük
    6890: "IBB",    # İstanbul Başakşehir
    7775: "HTS",    # Hatayspor
    10484: "KSM",   # Kasımpaşa
    11282: "ALN",   # Alanyaspor
    11688: "GIR",   # Giresunspor
    19789: "YML",   # Yeni Malatyaspor
    24245: "UMR",   # Ümraniyespor
    # 2012-2020 clubs (promoted/relegated)
    6: "ADA",       # Adanaspor
    20: "BUR",      # Bursaspor
    524: "GAZ",     # Gaziantepspor (dissolved 2020)
    820: "GEN",     # Gençlerbirliği
    825: "ESK",     # Eskişehirspor
    833: "DEN",     # Denizlispor
    1506: "KRB",    # Kardemir Karabükspor
    2292: "ELZ",    # Elazığspor
    2323: "ORD",    # Orduspor
    2944: "OSM",    # Ankaspor → Osmanlıspor
    3216: "MER",    # Mersin İdman Yurdu
    6894: "ERC",    # Kayseri Erciyesspor
    19771: "AKH",   # Akhisarspor
    20698: "BAL",   # Balıkesirspor
    39722: "ERZ",   # Erzurumspor FK
}


def _canonicalize_odds(name: str) -> str:
    """Map football-data.co.uk team name to canonical code."""
    if name in _ODDS_TO_CODE:
        return _ODDS_TO_CODE[name]
    raise KeyError(f"Unknown odds team: '{name}'. Add to _ODDS_TO_CODE in data_loader.py")


def _canonicalize_tm(club_id: int) -> str | None:
    """Map transfermarkt club_id to canonical code."""
    return _TM_CLUBID_TO_CODE.get(club_id)


# ---------------------------------------------------------------------------
# 1. Load odds
# ---------------------------------------------------------------------------

def load_odds(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load football-data.co.uk per-season CSVs for Turkish Super Lig."""
    seasons = seasons or DEFAULT_SEASONS
    frames = []

    for season in seasons:
        code = SEASON_CODES.get(season)
        if not code:
            logger.warning(f"No season code for {season}")
            continue

        csv_path = RAW_ODDS_DIR / f"T1_{code}.csv"
        if not csv_path.exists():
            logger.warning(f"Missing odds file: {csv_path}")
            continue

        df = pd.read_csv(csv_path)
        df["season"] = season
        frames.append(df)
        logger.info(f"Loaded odds {season}: {len(df)} matches")

    if not frames:
        raise FileNotFoundError("No odds data found. Run: python data/download_odds.py")

    all_odds = pd.concat(frames, ignore_index=True)

    # Parse date (DD/MM/YYYY format)
    all_odds["date"] = pd.to_datetime(all_odds["Date"], dayfirst=True)

    # Standardize
    result = pd.DataFrame({
        "date": all_odds["date"],
        "season": all_odds["season"],
        "home_team_raw": all_odds["HomeTeam"].str.strip(),
        "away_team_raw": all_odds["AwayTeam"].str.strip(),
        "home_goals": pd.to_numeric(all_odds["FTHG"], errors="coerce"),
        "away_goals": pd.to_numeric(all_odds["FTAG"], errors="coerce"),
        "result": all_odds["FTR"],  # H/D/A
    })

    # Odds: PSH/PSD/PSA = Pinnacle opening, AvgH/AvgD/AvgA = market average
    # PSCH/PSCD/PSCA = Pinnacle closing (when available)
    for outcome, ps_col, avg_col in [
        ("home", "PSH", "AvgH"),
        ("draw", "PSD", "AvgD"),
        ("away", "PSA", "AvgA"),
    ]:
        ps = pd.to_numeric(all_odds.get(ps_col, pd.Series(dtype=float)), errors="coerce")
        avg = pd.to_numeric(all_odds.get(avg_col, pd.Series(dtype=float)), errors="coerce")
        result[f"{outcome}_odds"] = ps.fillna(avg)

    # Pinnacle closing odds (for line movement computation)
    for outcome, psc_col in [
        ("home", "PSCH"),
        ("draw", "PSCD"),
        ("away", "PSCA"),
    ]:
        psc = pd.to_numeric(all_odds.get(psc_col, pd.Series(dtype=float)), errors="coerce")
        result[f"{outcome}_odds_close"] = psc

    # Drop rows with NaN team names (empty rows in some CSVs)
    result = result.dropna(subset=["home_team_raw", "away_team_raw"])

    # Canonicalize team names
    result["home_team"] = result["home_team_raw"].map(_canonicalize_odds)
    result["away_team"] = result["away_team_raw"].map(_canonicalize_odds)

    result = result.sort_values("date").reset_index(drop=True)
    logger.info(f"Odds total: {len(result)} matches, {result['season'].nunique()} seasons")

    return result


# ---------------------------------------------------------------------------
# 2. Load transfermarkt data
# ---------------------------------------------------------------------------

def load_transfermarkt(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load transfermarkt games + lineups + appearances, build per-match lineups.

    Returns match-level DataFrame with columns:
      tm_game_id, date, home_team, away_team, home_lineup, away_lineup
    Each lineup is a list of dicts:
      [{player_id, player_name, is_starter, minutes, goals, assists}, ...]
    """
    seasons = seasons or DEFAULT_SEASONS

    games_path = RAW_TM_DIR / "games.parquet"
    lineups_path = RAW_TM_DIR / "game_lineups.parquet"
    appearances_path = RAW_TM_DIR / "appearances.parquet"

    for path in [games_path, lineups_path, appearances_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"Missing: {path}. Run: python data/download_transfermarkt.py"
            )

    games = pd.read_parquet(games_path)
    lineups = pd.read_parquet(lineups_path)
    appearances = pd.read_parquet(appearances_path)

    games = games[games["season"].isin(seasons)].copy()

    # Canonicalize team codes via club_id
    games["home_team"] = games["home_club_id"].map(_canonicalize_tm)
    games["away_team"] = games["away_club_id"].map(_canonicalize_tm)

    # Log unmapped clubs
    unmapped_home = games[games["home_team"].isna()][["home_club_id", "home_club_name"]].drop_duplicates()
    unmapped_away = games[games["away_team"].isna()][["away_club_id", "away_club_name"]].drop_duplicates()
    if len(unmapped_home) > 0:
        for _, row in unmapped_home.iterrows():
            logger.warning(f"Unmapped home club: {row['home_club_id']} = {row['home_club_name']}")
    if len(unmapped_away) > 0:
        for _, row in unmapped_away.iterrows():
            logger.warning(f"Unmapped away club: {row['away_club_id']} = {row['away_club_name']}")

    # Keep only starters from lineups
    starters = lineups[lineups["type"] == "starting_lineup"].copy()

    # Join starters with appearances to get minutes/goals/assists
    starters = starters.merge(
        appearances[["game_id", "player_id", "minutes_played", "goals", "assists"]],
        on=["game_id", "player_id"],
        how="left",
    )

    # Build per-match lineup structure
    game_ids = set(games["game_id"])
    match_lineups = {}

    for game_id, grp in starters[starters["game_id"].isin(game_ids)].groupby("game_id"):
        home_club_id = games.loc[games["game_id"] == game_id, "home_club_id"].iloc[0]

        home_players = []
        away_players = []

        for _, p in grp.iterrows():
            player_dict = {
                "player_id": int(p["player_id"]),
                "player_name": p["player_name"],
                "is_starter": True,
                "minutes": float(p["minutes_played"]) if pd.notna(p["minutes_played"]) else 0.0,
                "goals": int(p["goals"]) if pd.notna(p["goals"]) else 0,
                "assists": int(p["assists"]) if pd.notna(p["assists"]) else 0,
            }

            if p["club_id"] == home_club_id:
                home_players.append(player_dict)
            else:
                away_players.append(player_dict)

        match_lineups[game_id] = {
            "home_lineup": home_players,
            "away_lineup": away_players,
        }

    # Build result DataFrame
    games["date"] = pd.to_datetime(games["date"])
    result = games[["game_id", "date", "season", "home_team", "away_team"]].copy()
    result = result.rename(columns={"game_id": "tm_game_id"})
    result["home_lineup"] = result["tm_game_id"].map(lambda gid: match_lineups.get(gid, {}).get("home_lineup"))
    result["away_lineup"] = result["tm_game_id"].map(lambda gid: match_lineups.get(gid, {}).get("away_lineup"))

    n_with = result["home_lineup"].notna().sum()
    logger.info(f"Transfermarkt: {len(result)} matches, {n_with} with lineups")

    return result


# ---------------------------------------------------------------------------
# 3. Join odds + transfermarkt
# ---------------------------------------------------------------------------

def join_sources(odds: pd.DataFrame, tm: pd.DataFrame) -> pd.DataFrame:
    """Join odds and transfermarkt on (date, home_team, away_team).

    Uses exact date match first, then ±1 day fuzzy fallback.
    """
    # Exact join
    merged = odds.merge(
        tm[["date", "home_team", "away_team", "tm_game_id", "home_lineup", "away_lineup"]],
        on=["date", "home_team", "away_team"],
        how="left",
    )

    n_matched = merged["tm_game_id"].notna().sum()
    n_total = len(merged)
    logger.info(f"Exact join: {n_matched}/{n_total} matched ({100*n_matched/n_total:.0f}%)")

    # Fuzzy date fallback for unmatched: try ±1 day
    unmatched = merged[merged["tm_game_id"].isna()].copy()
    if len(unmatched) > 0:
        n_fuzzy = 0
        for idx, row in unmatched.iterrows():
            for delta in [-1, 1]:
                fuzzy_date = row["date"] + pd.Timedelta(days=delta)
                candidates = tm[
                    (tm["date"] == fuzzy_date)
                    & (tm["home_team"] == row["home_team"])
                    & (tm["away_team"] == row["away_team"])
                ]
                if len(candidates) == 1:
                    c = candidates.iloc[0]
                    merged.at[idx, "tm_game_id"] = c["tm_game_id"]
                    merged.at[idx, "home_lineup"] = c["home_lineup"]
                    merged.at[idx, "away_lineup"] = c["away_lineup"]
                    n_fuzzy += 1
                    break

        if n_fuzzy > 0:
            logger.info(f"Fuzzy date join: +{n_fuzzy} matches")

    merged["has_lineup_data"] = merged["home_lineup"].apply(
        lambda x: x is not None and isinstance(x, list) and len(x) > 0
    )

    n_final = merged["has_lineup_data"].sum()
    logger.info(
        f"Final join: {n_final}/{n_total} with lineup data ({100*n_final/n_total:.0f}%)"
    )

    return merged


# ---------------------------------------------------------------------------
# 4. Public API
# ---------------------------------------------------------------------------

def load_all_seasons(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load all data, join, return unified match DataFrame."""
    seasons = seasons or DEFAULT_SEASONS

    logger.info(f"Loading seasons: {seasons}")

    odds = load_odds(seasons)

    try:
        tm = load_transfermarkt(seasons)
    except FileNotFoundError as e:
        logger.warning(f"Transfermarkt data not found: {e}")
        tm = pd.DataFrame()

    if tm.empty:
        odds["has_lineup_data"] = False
        games = odds
    else:
        games = join_sources(odds, tm)

    # Convenience columns
    games["home_win"] = games["result"] == "H"
    games["draw"] = games["result"] == "D"
    games["away_win"] = games["result"] == "A"
    games["total_goals"] = games["home_goals"] + games["away_goals"]

    return games


def apply_data_filters(games: pd.DataFrame) -> pd.DataFrame:
    """Remove matches with data quality issues."""
    n_before = len(games)

    games = games.dropna(subset=["result", "home_goals", "away_goals"])
    games = games.dropna(subset=["home_odds", "draw_odds", "away_odds"])

    for col in ["home_odds", "draw_odds", "away_odds"]:
        games = games[games[col] > 1.0]

    games = games.reset_index(drop=True)
    logger.info(f"Filters: {n_before} -> {len(games)} ({n_before - len(games)} removed)")

    return games


def add_derived_odds(games: pd.DataFrame) -> pd.DataFrame:
    """Compute vig-removed implied probabilities from decimal odds."""
    raw_h = 1.0 / games["home_odds"]
    raw_d = 1.0 / games["draw_odds"]
    raw_a = 1.0 / games["away_odds"]

    overround = raw_h + raw_d + raw_a
    games["overround"] = overround

    games["home_implied"] = raw_h / overround
    games["draw_implied"] = raw_d / overround
    games["away_implied"] = raw_a / overround

    # Implied PPG (W=3, D=1)
    games["home_implied_ppg"] = 3 * games["home_implied"] + games["draw_implied"]
    games["away_implied_ppg"] = 3 * games["away_implied"] + games["draw_implied"]

    logger.info(f"Derived odds: mean overround = {overround.mean():.3f}")

    return games


def add_line_movement(games: pd.DataFrame) -> pd.DataFrame:
    """Compute line movement from opening (PSH) vs closing (PSCH) Pinnacle odds.

    Adds columns: line_move_home, line_move_draw, line_move_away.
    line_move = 1/close - 1/open (change in implied probability).
    Positive = odds shortened (more money on that outcome).
    NaN when closing odds are missing.
    """
    for outcome in ["home", "draw", "away"]:
        open_col = f"{outcome}_odds"
        close_col = f"{outcome}_odds_close"
        if close_col in games.columns:
            open_imp = 1.0 / games[open_col]
            close_imp = 1.0 / games[close_col]
            games[f"line_move_{outcome}"] = close_imp - open_imp
        else:
            games[f"line_move_{outcome}"] = np.nan

    n_with = games["line_move_home"].notna().sum()
    logger.info(f"Line movement: {n_with}/{len(games)} matches with data")

    return games
