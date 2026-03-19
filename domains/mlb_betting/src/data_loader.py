"""Load and combine MLB historical odds data from xlsx files.

Each xlsx row represents one team in one game (2 rows per game: visitor + home).
We pair them into game-level records with all inning scores, odds, and pitchers.

Data sources:
  - sports-statistics.com xlsx: 2010-2019, 2021
  - SportsDatabase.com SDQL API: 2004-2009 (moneyline, total, scores, starters)
  - ArnavSaraogi JSON + SDQL merge: 2022-2025 (multi-book moneyline, run line, starters)

2020 excluded — COVID season (60 games, 7-inning DH, runner on 2nd in extras).
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RAW_ODDS_DIR = Path(__file__).parent.parent / "data" / "raw" / "odds"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
RETROSHEET_PROCESSED_DIR = PROCESSED_DIR / "retrosheet"

# Column names as they appear in the xlsx files
XLSX_COLUMNS = [
    "date",
    "rot",
    "vh",
    "team",
    "pitcher",
    "inn_1",
    "inn_2",
    "inn_3",
    "inn_4",
    "inn_5",
    "inn_6",
    "inn_7",
    "inn_8",
    "inn_9",
    "final",
    "open_ml",
    "close_ml",
    "run_line",
    "run_line_odds",
    "open_ou",
    "open_ou_odds",
    "close_ou",
    "close_ou_odds",
]

INNING_COLS = [f"inn_{i}" for i in range(1, 10)]

# Seasons to load (2020 excluded — COVID)
SEASONS = [
    2004, 2005, 2006, 2007, 2008, 2009,  # SDQL (sportsdatabase.com)
    2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019,  # sports-statistics.com
    2021,  # sports-statistics.com
    2022, 2023, 2024, 2025,  # ArnavSaraogi JSON + SDQL merge
]


def load_single_season(filepath: Path, season: int) -> pd.DataFrame:
    """Load a single season xlsx file into a DataFrame with standardized columns."""
    df = pd.read_excel(filepath, header=0)

    n_cols = len(df.columns)
    if n_cols == 23:
        # Full schema: all columns including run_line, run_line_odds
        df.columns = XLSX_COLUMNS
    elif n_cols == 21:
        # 2010-2013 xlsx files: no run_line or run_line_odds columns.
        # Columns are: date..close_ml, open_ou, open_ou_odds, close_ou, close_ou_odds
        cols_21 = XLSX_COLUMNS[:17] + XLSX_COLUMNS[19:]  # skip run_line, run_line_odds
        df.columns = cols_21
        df["run_line"] = np.nan
        df["run_line_odds"] = np.nan
    else:
        # Fallback: truncate column names to match
        df.columns = XLSX_COLUMNS[: n_cols]

    # Add season
    df["season"] = season

    # Clean date: format is MMDD (e.g., 401 = April 1st)
    df["date_raw"] = df["date"]
    df["month"] = (df["date_raw"] // 100).astype(int)
    df["day"] = (df["date_raw"] % 100).astype(int)
    df["date"] = pd.to_datetime(
        df.apply(lambda r: f"{season}-{int(r['month']):02d}-{int(r['day']):02d}", axis=1),
        errors="coerce",
    )

    # Clean inning scores: replace None/NaN with 0 for regulation innings
    for col in INNING_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Clean final score
    df["final"] = pd.to_numeric(df["final"], errors="coerce")

    # Clean odds columns
    for col in ["open_ml", "close_ml", "run_line", "run_line_odds", "open_ou", "close_ou"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def pair_games(df: pd.DataFrame) -> pd.DataFrame:
    """Pair visitor/home rows into game-level records.

    Each game has 2 consecutive rows: visitor (V) then home (H).
    We merge them into a single row with away_ and home_ prefixes.
    """
    visitors = df[df["vh"] == "V"].reset_index(drop=True)
    homes = df[df["vh"] == "H"].reset_index(drop=True)

    if len(visitors) != len(homes):
        logger.warning(
            f"Visitor/home count mismatch: {len(visitors)} vs {len(homes)}. "
            "Some games may be incomplete."
        )
        # Truncate to the shorter list
        min_len = min(len(visitors), len(homes))
        visitors = visitors.iloc[:min_len]
        homes = homes.iloc[:min_len]

    # Build game-level DataFrame
    games = pd.DataFrame()

    # Game identifiers
    games["season"] = visitors["season"].values
    games["date"] = visitors["date"].values
    games["month"] = visitors["month"].values

    # Teams
    games["away_team"] = visitors["team"].values
    games["home_team"] = homes["team"].values
    games["matchup_key"] = games.apply(
        lambda r: "_".join(sorted([str(r["away_team"]), str(r["home_team"])])), axis=1
    )

    # Pitchers
    games["away_pitcher"] = visitors["pitcher"].values
    games["home_pitcher"] = homes["pitcher"].values

    # Inning scores — away
    for i in range(1, 10):
        games[f"away_inn_{i}"] = visitors[f"inn_{i}"].values

    # Inning scores — home
    for i in range(1, 10):
        games[f"home_inn_{i}"] = homes[f"inn_{i}"].values

    # Final scores
    games["away_final"] = visitors["final"].values
    games["home_final"] = homes["final"].values
    games["home_win"] = (games["home_final"] > games["away_final"]).astype(int)

    # Odds (from home team perspective)
    games["home_open_ml"] = homes["open_ml"].values
    games["home_close_ml"] = homes["close_ml"].values
    games["away_open_ml"] = visitors["open_ml"].values
    games["away_close_ml"] = visitors["close_ml"].values

    # Run line (home perspective)
    games["home_run_line"] = homes["run_line"].values
    games["home_run_line_odds"] = homes["run_line_odds"].values

    # Over/Under
    games["open_ou"] = homes["open_ou"].values
    games["close_ou"] = homes["close_ou"].values

    # Derived: inning sums
    away_inn_cols = [f"away_inn_{i}" for i in range(1, 10)]
    home_inn_cols = [f"home_inn_{i}" for i in range(1, 10)]
    games["away_innings_sum"] = games[away_inn_cols].sum(axis=1)
    games["home_innings_sum"] = games[home_inn_cols].sum(axis=1)
    games["total_runs"] = games["away_final"] + games["home_final"]

    return games


def load_all_seasons(
    data_dir: Path | None = None,
    seasons: list[int] | None = None,
) -> pd.DataFrame:
    """Load and combine all seasons into a single game-level DataFrame.

    Args:
        data_dir: Path to raw odds xlsx files. Defaults to data/raw/odds/.
        seasons: List of seasons to load. Defaults to all available (excl. 2020).

    Returns:
        DataFrame with one row per game, all innings, odds, and pitchers.
    """
    data_dir = data_dir or RAW_ODDS_DIR
    seasons = seasons or SEASONS

    all_raw = []
    for season in seasons:
        filepath = data_dir / f"mlb-odds-{season}.xlsx"
        if not filepath.exists():
            logger.warning(f"File not found: {filepath}, skipping season {season}")
            continue

        logger.info(f"Loading season {season}...")
        df = load_single_season(filepath, season)
        all_raw.append(df)

    if not all_raw:
        raise FileNotFoundError(f"No data files found in {data_dir}. Run data/download.py first.")

    raw_combined = pd.concat(all_raw, ignore_index=True)
    logger.info(f"Loaded {len(raw_combined)} team-game rows from {len(all_raw)} seasons")

    # Pair into game-level records
    games = pair_games(raw_combined)
    logger.info(f"Paired into {len(games)} games")

    return games


def apply_data_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Clean data quality issues. Colorado stays for form calculations.

    Hard removes: missing odds, missing pitcher, double-headers.
    Soft flags: Colorado, extra innings, extreme lines, season phases, bullpen games.
    """
    n_before = len(df)

    # Hard removes (data quality)
    df = df[df["home_close_ml"].notna() & (df["home_close_ml"] != 0)].copy()
    df = df[df["away_close_ml"].notna() & (df["away_close_ml"] != 0)]
    df = df[df["home_pitcher"].notna() & (df["home_pitcher"] != "")]
    df = df[df["away_pitcher"].notna() & (df["away_pitcher"] != "")]

    # Remove double-headers: >1 game same date + same matchup
    game_counts = df.groupby(["date", "matchup_key"]).size().reset_index(name="n_games")
    dh_keys = game_counts[game_counts["n_games"] > 1][["date", "matchup_key"]]
    if len(dh_keys) > 0:
        dh_merged = df.merge(dh_keys, on=["date", "matchup_key"], how="left", indicator=True)
        df = dh_merged[dh_merged["_merge"] == "left_only"].drop(columns=["_merge"])

    # Safety: remove any remaining "same team plays twice on same date" cases.
    # These can be true doubleheaders (sometimes not detected due to source quirks)
    # and they break downstream feature merges unless we have a stable game_num key.
    team_date = pd.concat(
        [
            df[["date", "home_team"]].rename(columns={"home_team": "team"}),
            df[["date", "away_team"]].rename(columns={"away_team": "team"}),
        ],
        ignore_index=True,
    )
    td_counts = team_date.groupby(["date", "team"]).size().reset_index(name="n_games")
    td_bad = td_counts[td_counts["n_games"] > 1][["date", "team"]]
    if len(td_bad) > 0:
        bad_idx = pd.MultiIndex.from_frame(td_bad)
        home_idx = pd.MultiIndex.from_arrays([df["date"], df["home_team"]])
        away_idx = pd.MultiIndex.from_arrays([df["date"], df["away_team"]])
        mask_bad = home_idx.isin(bad_idx) | away_idx.isin(bad_idx)
        df = df.loc[~mask_bad].copy()

    n_after_hard = len(df)

    # Soft flags (keep rows, filter later as needed)
    df["involves_col"] = (df["home_team"] == "COL") | (df["away_team"] == "COL")

    # Extra innings: inning sum != final score.
    # Guard: if all inning scores are 0 (SDQL/JSON sources lack inning data),
    # the sum==0 comparison would false-positive every game. Only flag when
    # at least one inning column is non-zero (meaning we have real inning data).
    has_inning_data = (df["away_innings_sum"] > 0) | (df["home_innings_sum"] > 0)
    df["is_extra_innings"] = has_inning_data & (
        (df["away_innings_sum"] != df["away_final"])
        | (df["home_innings_sum"] != df["home_final"])
    )

    # Extreme favorite: closing ML > ±300
    df["is_extreme_line"] = (df["home_close_ml"].abs() > 300) | (df["away_close_ml"].abs() > 300)

    # Season phases
    df["is_early_season"] = df["month"] == 4  # April = first month
    df["is_september"] = df["month"] == 9

    # Bullpen game flag (populated later from pitcher stats)
    df["is_bullpen_game"] = False

    logger.info(
        f"Data filters: {n_before} -> {n_after_hard} (hard), "
        f"COL games: {df['involves_col'].sum()}, "
        f"September: {df['is_september'].sum()}, "
        f"Extreme lines: {df['is_extreme_line'].sum()}, "
        f"Extra innings: {df['is_extra_innings'].sum()}, "
        f"Double-headers removed: {n_before - n_after_hard}"
    )

    return df.reset_index(drop=True)


def apply_betting_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for bettable games only. Applied BEFORE selecting bets.

    Removes:
    - Games involving Colorado Rockies (Coors Field altitude effect)
    - September games (tanking, roster expansion)
    - Extreme favorites (ML > ±300)
    """
    mask = ~df["involves_col"] & ~df["is_september"] & ~df["is_extreme_line"]
    result = df[mask].copy()
    logger.info(f"Betting filters: {len(df)} -> {len(result)} bettable games")
    return result.reset_index(drop=True)


def american_to_decimal(ml: float) -> float:
    """Convert American moneyline odds to decimal odds."""
    if ml > 0:
        return (ml / 100) + 1
    elif ml < 0:
        return (100 / abs(ml)) + 1
    return 1.0


def american_to_implied_prob(ml: float) -> float:
    """Convert American moneyline odds to implied probability (no-vig)."""
    if ml > 0:
        return 100 / (ml + 100)
    elif ml < 0:
        return abs(ml) / (abs(ml) + 100)
    return 0.5


def add_derived_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Add decimal odds, implied probabilities, and convenience columns."""
    df = df.copy()

    # Decimal odds
    df["home_decimal_odds"] = df["home_close_ml"].apply(american_to_decimal)
    df["away_decimal_odds"] = df["away_close_ml"].apply(american_to_decimal)

    # Implied probabilities (from closing line)
    df["home_implied_prob"] = df["home_close_ml"].apply(american_to_implied_prob)
    df["away_implied_prob"] = df["away_close_ml"].apply(american_to_implied_prob)

    # Home favorite flag
    df["home_is_favorite"] = df["home_implied_prob"] > 0.5

    return df


def _map_team_code_to_retrosheet(team: str, season: int | None = None) -> str:
    """Map common MLB abbreviations to Retrosheet team codes.

    This is best-effort and only affects joins to Retrosheet-derived tables.
    If the input already looks like a Retrosheet code, it's returned unchanged.
    """
    if not isinstance(team, str):
        return team

    t = team.strip().upper()

    # Season-aware Marlins handling (Retrosheet: FLO -> MIA in 2012).
    if t in {"FLA", "FLO", "MIA"} and season is not None:
        return "FLO" if int(season) <= 2011 else "MIA"

    mapping = {
        # New York
        "NYY": "NYA",
        "NYM": "NYN",
        # Alternate codes (sports-statistics style)
        "NYA": "NYA",
        "NYN": "NYN",
        # Chicago
        "CHW": "CHA",
        "CWS": "CHA",
        "CHA": "CHA",
        "CHC": "CHN",
        "CUB": "CHN",
        "CHN": "CHN",
        # California / LA
        "LAA": "ANA",
        "LAD": "LAN",
        "LOS": "LAN",
        "ANA": "ANA",
        "LAN": "LAN",
        # Bay / KC / DC
        "TBR": "TBA",
        "TB": "TBA",
        "KCR": "KCA",
        "KAN": "KCA",
        "KC": "KCA",
        "WSN": "WAS",
        "WSH": "WAS",
        # Others frequently seen
        "SFG": "SFN",
        "SFO": "SFN",
        "SDP": "SDN",
        "SDG": "SDN",
        "STL": "SLN",
        "TAM": "TBA",
        # Athletics renamed Sacramento Athletics 2025, same Retrosheet franchise
        "ATH": "OAK",
    }
    return mapping.get(t, t)


def merge_retrosheet_pitchers(
    games: pd.DataFrame,
    *,
    bridge_path: Path | None = None,
) -> pd.DataFrame:
    """Merge Retrosheet starter ids + bullpen flags onto our game-level dataset.

    Adds:
    - `home_starter_id`, `away_starter_id`
    - `home_is_bullpen_no_starter`, `away_is_bullpen_no_starter`
    - `home_is_opener_game`, `away_is_opener_game`
    - Updates `is_bullpen_game` (True if either side has no designated starter)

    Join keys:
    - date + (mapped) home_team + (mapped) away_team

    Important:
    - Our dataset hard-removes doubleheaders in `apply_data_filters()`, so joining
      without `game_num` is safe for the default pipeline.
    """
    bridge_path = bridge_path or (PROCESSED_DIR / "pitchers" / "game_id_bridge.parquet")
    if not Path(bridge_path).exists():
        raise FileNotFoundError(
            f"Retrosheet bridge not found: {bridge_path}. "
            "Run scripts/build_retrosheet_pitchers.py first."
        )

    bridge = pd.read_parquet(bridge_path)
    needed = {
        "date",
        "home_team",
        "away_team",
        "home_starter_id",
        "away_starter_id",
        "home_is_bullpen_no_starter",
        "away_is_bullpen_no_starter",
        "home_is_opener_game",
        "away_is_opener_game",
    }
    missing = needed - set(bridge.columns)
    if missing:
        raise ValueError(f"Bridge parquet is missing columns: {sorted(missing)}")

    out = games.copy()
    if "date" not in out.columns:
        raise ValueError("games must contain a `date` column (datetime)")

    # Map team codes to Retrosheet codes for join.
    out["_home_team_rs"] = out.apply(
        lambda r: _map_team_code_to_retrosheet(r["home_team"], r["season"]), axis=1
    )
    out["_away_team_rs"] = out.apply(
        lambda r: _map_team_code_to_retrosheet(r["away_team"], r["season"]), axis=1
    )

    bridge2 = bridge.rename(columns={"home_team": "_home_team_rs", "away_team": "_away_team_rs"})

    # Retrosheet has true double-headers (game_num=1/2) where (date, home, away) repeats.
    # Our odds dataset may contain only one of the games (or has no game_num), so we must
    # avoid row multiplication. For ambiguous keys, we keep a single placeholder row and
    # set starter ids/flags to NA (fail-safe rather than wrong join).
    join_keys = ["date", "_home_team_rs", "_away_team_rs"]
    dup = bridge2.duplicated(subset=join_keys, keep=False)
    if bool(dup.any()):
        amb_keys = bridge2.loc[dup, join_keys].drop_duplicates().copy()
        amb = amb_keys.assign(
            home_starter_id=pd.NA,
            away_starter_id=pd.NA,
            home_is_bullpen_no_starter=pd.NA,
            away_is_bullpen_no_starter=pd.NA,
            home_is_opener_game=pd.NA,
            away_is_opener_game=pd.NA,
            retrosheet_bridge_ambiguous=True,
        )
        uniq = bridge2.loc[~dup, join_keys + [
            "home_starter_id",
            "away_starter_id",
            "home_is_bullpen_no_starter",
            "away_is_bullpen_no_starter",
            "home_is_opener_game",
            "away_is_opener_game",
        ]].copy()
        uniq["retrosheet_bridge_ambiguous"] = False
        bridge2 = pd.concat([uniq, amb], ignore_index=True)
    else:
        bridge2 = bridge2.copy()
        bridge2["retrosheet_bridge_ambiguous"] = False

    merged = out.merge(
        bridge2[
            [
                "date",
                "_home_team_rs",
                "_away_team_rs",
                "home_starter_id",
                "away_starter_id",
                "home_is_bullpen_no_starter",
                "away_is_bullpen_no_starter",
                "home_is_opener_game",
                "away_is_opener_game",
                "retrosheet_bridge_ambiguous",
            ]
        ],
        on=["date", "_home_team_rs", "_away_team_rs"],
        how="left",
    )

    # Normalize flags to strict bool (avoid object dtype caused by NA placeholders).
    for c in [
        "home_is_bullpen_no_starter",
        "away_is_bullpen_no_starter",
        "home_is_opener_game",
        "away_is_opener_game",
        "retrosheet_bridge_ambiguous",
    ]:
        if c in merged.columns:
            merged[c] = merged[c].astype("boolean").fillna(False).astype(bool)

    # Update game-level bullpen flag (keep existing default False if no match).
    if "is_bullpen_game" not in merged.columns:
        merged["is_bullpen_game"] = False
    merged["is_bullpen_game"] = merged["is_bullpen_game"].astype(bool) | (
        merged["home_is_bullpen_no_starter"] | merged["away_is_bullpen_no_starter"]
    )

    merged = merged.drop(columns=["_home_team_rs", "_away_team_rs"])
    return merged


def merge_retrosheet_starter_entering_features(
    games: pd.DataFrame,
    *,
    entering_path: Path | None = None,
    home_prefix: str = "home_sp_",
    away_prefix: str = "away_sp_",
) -> pd.DataFrame:
    """Merge Retrosheet entering-game starter features onto our game-level dataset.

    Expects that `games` already contains `home_starter_id` and `away_starter_id`
    (see `merge_retrosheet_pitchers()`).

    Join keys:
    - `date` + `home_starter_id` (home side, `is_home=True`)
    - `date` + `away_starter_id` (away side, `is_home=False`)

    Notes:
    - We normalize `date` to timezone-naive midnight for both tables.
    - We require uniqueness of (date, pitcher_id, is_home) in the entering-features table,
      otherwise the merge could silently duplicate rows.
    """
    entering_path = entering_path or (
        PROCESSED_DIR / "pitchers" / "starter_entering_features.parquet"
    )
    if not Path(entering_path).exists():
        raise FileNotFoundError(
            f"Entering-game features not found: {entering_path}. "
            "Run scripts/build_retrosheet_pitchers.py first."
        )

    out = games.copy()
    required = {"date", "home_starter_id", "away_starter_id"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(
            "games is missing required columns for entering-features merge: "
            f"{sorted(missing)}. Call merge_retrosheet_pitchers() first."
        )

    # Normalize dates to naive midnight for reliable joins.
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    if pd.api.types.is_datetime64tz_dtype(out["date"]):
        out["date"] = out["date"].dt.tz_convert(None)

    entering = pd.read_parquet(entering_path)
    needed = {"date", "pitcher_id", "is_home"}
    missing_e = needed - set(entering.columns)
    if missing_e:
        raise ValueError(
            f"starter_entering_features parquet is missing columns: {sorted(missing_e)}"
        )

    entering = entering.copy()
    entering["date"] = pd.to_datetime(entering["date"], errors="coerce").dt.normalize()
    if pd.api.types.is_datetime64tz_dtype(entering["date"]):
        entering["date"] = entering["date"].dt.tz_convert(None)

    key_cols = ["date", "pitcher_id", "is_home"]
    dup = entering.duplicated(subset=key_cols, keep=False)
    if bool(dup.any()):
        sample = entering.loc[dup, key_cols].head(10)
        raise ValueError(
            "starter_entering_features has duplicate keys (date, pitcher_id, is_home). "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    # Keep all computed entering-game metrics, but avoid merging Retrosheet game metadata.
    drop_meta = {
        "gid",
        "season",
        "game_num",
        "home_team",
        "away_team",
        "team",
        "opponent",
    }
    feat_cols = [c for c in entering.columns if c not in (set(key_cols) | drop_meta)]

    home = entering[entering["is_home"] == True][["date", "pitcher_id", *feat_cols]].copy()  # noqa: E712
    home = home.rename(
        columns={
            "pitcher_id": "home_starter_id",
            **{c: f"{home_prefix}{c}" for c in feat_cols},
        }
    )
    out = out.merge(home, on=["date", "home_starter_id"], how="left", validate="m:1")

    away = entering[entering["is_home"] == False][["date", "pitcher_id", *feat_cols]].copy()  # noqa: E712
    away = away.rename(
        columns={
            "pitcher_id": "away_starter_id",
            **{c: f"{away_prefix}{c}" for c in feat_cols},
        }
    )
    out = out.merge(away, on=["date", "away_starter_id"], how="left", validate="m:1")

    return out


def load_retrosheet_master_games(
    *,
    with_odds: bool = True,
    path: Path | None = None,
    seasons: list[int] | None = None,
) -> pd.DataFrame:
    """Load Retrosheet master game table (optionally with merged odds).

    This is produced by `scripts/build_retrosheet_master_with_odds.py`.

    Notes:
    - Retrosheet gamelogs used here cover regular season; postseason games are not expected.
    - The table already contains `away_inn_1..9`, `home_inn_1..9`, finals, and `gid`.
    """
    if path is None:
        filename = "retrosheet_master_games_with_odds.parquet" if with_odds else "retrosheet_master_games.parquet"
        path = RETROSHEET_PROCESSED_DIR / filename

    if not Path(path).exists():
        raise FileNotFoundError(
            f"Retrosheet master parquet not found: {path}. "
            "Run scripts/build_retrosheet_master_with_odds.py first."
        )

    df = pd.read_parquet(path)
    if seasons is not None:
        df = df[df["season"].isin(list(seasons))].copy()
    return df.reset_index(drop=True)
