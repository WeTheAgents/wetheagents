"""Load and combine MLB historical odds data from xlsx files.

Each xlsx row represents one team in one game (2 rows per game: visitor + home).
We pair them into game-level records with all inning scores, odds, and pitchers.

Data sources:
  - sports-statistics.com xlsx: 2010-2019, 2021
  - SportsDatabase.com SDQL API: 2004-2009 (moneyline, total, scores, starters)
  - ArnavSaraogi JSON + SDQL merge: 2022-2025 (multi-book moneyline, run line, starters)

2020 excluded — COVID season (60 games, 7-inning DH, runner on 2nd in extras).
"""

import json as _json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RAW_ODDS_DIR = Path(__file__).parent.parent / "data" / "raw" / "odds"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
RETROSHEET_PROCESSED_DIR = PROCESSED_DIR / "retrosheet"

# SBR-style JSON dumps that may carry run-line odds for 2022-2025.  Either or
# both may be present.  Session 37 found the xlsx files for 2022-2025 ship
# with 100% NaN run_line even though one of these JSON files has the data.
SBR_JSON_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "raw" / "sbr_odds_full.json",
    Path(__file__).parent.parent / "data" / "raw" / "external" / "mlb_odds_dataset.json",
]

# ── Dual-path layout for pitcher/bullpen features ────────────────────────
# Historical (2014-2025) is owned by build_retrosheet_pitchers.py +
# build_bullpen_features.py and lives under pitchers/ and retrosheet/.
# 2026 (live, in-season) is owned by data/fetch_2026/mlb_boxscore.py and
# lives under pitchers_2026/. The two are loaded together via the
# load_combined_* helpers below — neither writer can clobber the other.
HISTORICAL_PITCHERS_DIR = PROCESSED_DIR / "pitchers"
HISTORICAL_BULLPEN_PATH = RETROSHEET_PROCESSED_DIR / "bullpen_features.parquet"
HISTORICAL_LINEUP_PATH = RETROSHEET_PROCESSED_DIR / "game_lineup_features.parquet"
HISTORICAL_BABIP_PATH = RETROSHEET_PROCESSED_DIR / "first_inning_babip.parquet"
LIVE_2026_DIR = PROCESSED_DIR / "pitchers_2026"
LIVE_2026_BULLPEN_PATH = LIVE_2026_DIR / "bullpen_features.parquet"
LIVE_2026_LINEUP_DIR = PROCESSED_DIR / "lineups_2026"
LIVE_2026_LINEUP_PATH = LIVE_2026_LINEUP_DIR / "game_lineup_features.parquet"
LIVE_2026_BABIP_PATH = LIVE_2026_LINEUP_DIR / "first_inning_babip.parquet"

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
    2026,  # ESPN scoreboard API (data/fetch_2026/)
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

    # Run line (both perspectives)
    games["home_run_line"] = homes["run_line"].values
    games["home_run_line_odds"] = homes["run_line_odds"].values
    games["away_run_line"] = visitors["run_line"].values
    games["away_run_line_odds"] = visitors["run_line_odds"].values

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
    *,
    enrich_innings: bool = True,
    enrich_run_line: bool = True,
) -> pd.DataFrame:
    """Load and combine all seasons into a single game-level DataFrame.

    Args:
        data_dir: Path to raw odds xlsx files. Defaults to data/raw/odds/.
        seasons: List of seasons to load. Defaults to all available (excl. 2020).
        enrich_innings: If True (default), backfill 2022-2025 inning-by-inning
            scores from Retrosheet teamstats. Required for any feature that
            depends on per-inning run counts (e.g. ``power_rate_*``). Safe
            no-op if Retrosheet zips are missing.
        enrich_run_line: If True (default), backfill NaN run_line / run_line_odds
            columns for 2022-2025 from SBR JSON. Safe no-op if the JSON file
            is missing.

    Returns:
        DataFrame with one row per game, all innings, odds, and pitchers.

    Notes:
        - ``enrich_innings`` and ``enrich_run_line`` exist because the xlsx
          files for 2022-2025 (built from SDQL + ArnavSaraogi JSON) lack real
          inning data (all zeros) and run_line (all NaN). Without the
          enrichments, features like ``power_rate_home/away`` and strategies
          that filter on ``home_run_line ∈ {-1.5, +1.5}`` silently drop
          2022-2025 entirely. See ``knowledge/session_report_37_data_gaps.md``.
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

    # Backfill xlsx-level data gaps for SDQL/JSON seasons. Both helpers are
    # safe no-ops when their source files are absent, so this is fine to run
    # unconditionally by default.
    if enrich_run_line:
        try:
            games = enrich_run_line_from_sbr(games)
        except Exception as e:  # noqa: BLE001 - never fail the loader on backfill
            logger.warning("run_line enrichment failed (non-fatal): %s", e)

    if enrich_innings:
        try:
            games = enrich_innings_from_retrosheet(games)
        except Exception as e:  # noqa: BLE001 - never fail the loader on backfill
            logger.warning("inning enrichment failed (non-fatal): %s", e)

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
    - Extreme favorites (ML > ±300)
    """
    mask = ~df["involves_col"] & ~df["is_extreme_line"]
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

    # Coinflip detection (odds spread ≤ 4% implied probability)
    df["odds_spread"] = (df["home_implied_prob"] - df["away_implied_prob"]).abs()
    df["is_coinflip"] = df["odds_spread"] <= 0.04

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

    # Season-aware Athletics handling. Retrosheet used "OAK" through 2024, then
    # switched to "ATH" when the franchise relocated to Sacramento in 2025.
    # The xlsx feeds keep the legacy "OAK" code, so without this season-aware
    # remap the inning/starter/bullpen joins silently drop all 162 A's games
    # in 2025+ (see knowledge/session_report_39_road_fav_ml.md).
    if t in {"OAK", "ATH"} and season is not None:
        return "ATH" if int(season) >= 2025 else "OAK"

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
        # Athletics: if season is unknown, fall back to the historical code.
        # With a season passed in, the OAK/ATH branch above handles it.
        "ATH": "OAK",
    }
    return mapping.get(t, t)


def _concat_dual_source(
    historical_path: Path,
    live_path: Path,
    *,
    label: str,
    dedup_keys: list[str] | None = None,
) -> pd.DataFrame:
    """Read historical + live parquets, concatenate, optionally dedup.

    Either side may be missing. If both are missing, returns an empty frame.
    On overlap (e.g. a date present in both files), the LIVE side wins via
    ``keep="last"`` so a fresh 2026 fetch is always preferred over a stale
    snapshot in the historical file.
    """
    frames = []
    for path, source in [(historical_path, "historical"), (live_path, "live_2026")]:
        if path.exists():
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    df["_source"] = source
                    frames.append(df)
            except (OSError, ValueError) as e:
                logger.warning("Failed to read %s (%s): %s", label, path, e)
    if not frames:
        logger.warning("Both %s sources missing: %s, %s", label, historical_path, live_path)
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if dedup_keys:
        # Sort historical first so live_2026 wins via keep="last".
        combined = combined.sort_values(
            "_source", kind="stable"
        ).drop_duplicates(subset=dedup_keys, keep="last")
    return combined.drop(columns=["_source"], errors="ignore").reset_index(drop=True)


def load_combined_bullpen_features() -> pd.DataFrame:
    """Load historical + 2026 bullpen features as a single frame."""
    return _concat_dual_source(
        HISTORICAL_BULLPEN_PATH,
        LIVE_2026_BULLPEN_PATH,
        label="bullpen_features",
        dedup_keys=["team", "date"],
    )


def load_combined_lineup_features() -> pd.DataFrame:
    """Load historical + 2026 team-level lineup features as a single frame."""
    return _concat_dual_source(
        HISTORICAL_LINEUP_PATH,
        LIVE_2026_LINEUP_PATH,
        label="game_lineup_features",
        dedup_keys=["team", "date"],
    )


def load_combined_first_inning_babip() -> pd.DataFrame:
    """Load historical + 2026 first-inning BABIP features as a single frame."""
    return _concat_dual_source(
        HISTORICAL_BABIP_PATH,
        LIVE_2026_BABIP_PATH,
        label="first_inning_babip",
        dedup_keys=["team", "date"],
    )


def load_combined_starter_entering_features() -> pd.DataFrame:
    """Load historical + 2026 starter entering-game features as a single frame."""
    return _concat_dual_source(
        HISTORICAL_PITCHERS_DIR / "starter_entering_features.parquet",
        LIVE_2026_DIR / "starter_entering_features.parquet",
        label="starter_entering_features",
        dedup_keys=["date", "pitcher_id", "is_home"],
    )


def load_combined_game_id_bridge() -> pd.DataFrame:
    """Load historical + 2026 game-id bridge as a single frame."""
    return _concat_dual_source(
        HISTORICAL_PITCHERS_DIR / "game_id_bridge.parquet",
        LIVE_2026_DIR / "game_id_bridge.parquet",
        label="game_id_bridge",
        # Bridge dedup is by (date, home_team, away_team[, game_num if present]).
        # We omit game_num because the historical file doesn't always carry it
        # for non-DH games — that mirrors the existing dedup in
        # merge_retrosheet_pitchers.
        dedup_keys=["date", "home_team", "away_team"],
    )


def merge_retrosheet_pitchers(
    games: pd.DataFrame,
    *,
    bridge_path: Path | None = None,
    bridge_df: pd.DataFrame | None = None,
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
    if bridge_df is not None:
        bridge = bridge_df.copy()
    elif bridge_path is not None:
        if not Path(bridge_path).exists():
            raise FileNotFoundError(
                f"Retrosheet bridge not found: {bridge_path}. "
                "Run scripts/build_retrosheet_pitchers.py first."
            )
        bridge = pd.read_parquet(bridge_path)
    else:
        bridge = load_combined_game_id_bridge()
        if bridge.empty:
            raise FileNotFoundError(
                "No game-id bridge found in either pitchers/ or pitchers_2026/. "
                "Run scripts/build_retrosheet_pitchers.py and/or backfill 2026 boxscores."
            )
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


def enrich_innings_from_retrosheet(games: pd.DataFrame) -> pd.DataFrame:
    """Backfill zero-inning seasons with real inning scores from Retrosheet teamstats.

    Seasons fetched via SDQL/JSON (2022-2025) have all-zero inning columns.
    Retrosheet ``{year}csvs.zip`` contain ``teamstats.csv`` with real per-inning runs.

    This function detects seasons where inning data is fake (all zeros) and merges
    real inning scores from Retrosheet, overwriting the zero columns.

    Must be called AFTER ``load_all_seasons()`` and BEFORE ``apply_data_filters()``.
    """
    from src.retrosheet_games import load_inning_scores_from_teamstats

    inn_cols = [f"away_inn_{i}" for i in range(1, 10)] + [
        f"home_inn_{i}" for i in range(1, 10)
    ]
    # Check which columns actually exist
    present_inn_cols = [c for c in inn_cols if c in games.columns]
    if not present_inn_cols:
        logger.warning("No inning columns found in games DataFrame, skipping enrichment.")
        return games

    # Detect seasons with fake inning data (all zeros)
    seasons_to_enrich = []
    for season, grp in games.groupby("season"):
        inn_sum = grp[present_inn_cols].sum().sum()
        if inn_sum == 0:
            seasons_to_enrich.append(int(season))

    if not seasons_to_enrich:
        logger.info("All seasons have real inning data, no enrichment needed.")
        return games

    logger.info(f"Enriching inning data for seasons: {seasons_to_enrich}")

    ts = load_inning_scores_from_teamstats(seasons_to_enrich)
    if ts.empty:
        logger.warning("No teamstats data loaded, skipping enrichment.")
        return games

    out = games.copy()

    # Map our team codes to Retrosheet codes for join
    out["_home_rs"] = out.apply(
        lambda r: _map_team_code_to_retrosheet(r["home_team"], r["season"]), axis=1
    )
    out["_away_rs"] = out.apply(
        lambda r: _map_team_code_to_retrosheet(r["away_team"], r["season"]), axis=1
    )

    ts_join = ts[
        ["date", "home_team", "away_team"]
        + [f"away_inn_{i}" for i in range(1, 10)]
        + [f"home_inn_{i}" for i in range(1, 10)]
        + ["away_innings_sum", "home_innings_sum"]
    ].rename(columns={"home_team": "_home_rs", "away_team": "_away_rs"})

    # Handle doubleheaders: keep first occurrence per (date, home, away) to avoid
    # row duplication (our dataset removes DH later in apply_data_filters).
    ts_join = ts_join.drop_duplicates(
        subset=["date", "_home_rs", "_away_rs"], keep="first"
    )

    # Rename inning cols to avoid collision during merge
    inn_rename = {}
    for i in range(1, 10):
        inn_rename[f"away_inn_{i}"] = f"_rs_away_inn_{i}"
        inn_rename[f"home_inn_{i}"] = f"_rs_home_inn_{i}"
    inn_rename["away_innings_sum"] = "_rs_away_innings_sum"
    inn_rename["home_innings_sum"] = "_rs_home_innings_sum"
    ts_join = ts_join.rename(columns=inn_rename)

    n_before = len(out)
    out = out.merge(
        ts_join,
        on=["date", "_home_rs", "_away_rs"],
        how="left",
    )
    assert len(out) == n_before, (
        f"Row count changed after merge: {n_before} -> {len(out)}. "
        "Likely a doubleheader causing duplication."
    )

    # Overwrite zero inning columns only for enriched seasons
    enrich_mask = out["season"].isin(seasons_to_enrich) & out["_rs_away_inn_1"].notna()
    n_enriched = enrich_mask.sum()

    for i in range(1, 10):
        out.loc[enrich_mask, f"away_inn_{i}"] = out.loc[enrich_mask, f"_rs_away_inn_{i}"].astype(int)
        out.loc[enrich_mask, f"home_inn_{i}"] = out.loc[enrich_mask, f"_rs_home_inn_{i}"].astype(int)
    out.loc[enrich_mask, "away_innings_sum"] = out.loc[enrich_mask, "_rs_away_innings_sum"].astype(int)
    out.loc[enrich_mask, "home_innings_sum"] = out.loc[enrich_mask, "_rs_home_innings_sum"].astype(int)

    # Cleanup temp columns
    drop_cols = ["_home_rs", "_away_rs"] + list(inn_rename.values())
    out = out.drop(columns=[c for c in drop_cols if c in out.columns])

    n_target = out["season"].isin(seasons_to_enrich).sum()
    logger.info(
        f"Inning enrichment: {n_enriched}/{n_target} games enriched "
        f"({n_enriched / n_target * 100:.1f}%) for seasons {seasons_to_enrich}"
    )
    return out


# ── Session 37: run_line backfill from SBR JSON ──────────────────────────
#
# The 2022-2025 xlsx files ship with 100% NaN run_line/run_line_odds because
# the SDQL-only fallback path in ``data/download_historical.py`` doesn't carry
# point spreads, and the JSON path that does carry them was not always wired
# up when the historical xlsx files were built.  Rather than re-running the
# historical xlsx build (which would also re-touch 2004-2009 SDQL files), we
# backfill run_line values at load time by reading the raw SBR JSON dump(s).
#
# This is purely additive: we only fill rows where the current run_line is
# NaN; any row that already has a run_line value is left untouched.


# Team-code variants observed across the different xlsx generators and SBR
# dumps.  Used when joining SBR JSON (keyed on shortName) into the xlsx-derived
# games frame (keyed on whatever abbreviation the generator produced).
_TEAM_VARIANTS: dict[str, set[str]] = {
    "KC":   {"KC", "KCR", "KAN", "KCA"},
    "KCR":  {"KC", "KCR", "KAN", "KCA"},
    "KAN":  {"KC", "KCR", "KAN", "KCA"},
    "SD":   {"SD", "SDP", "SDG", "SDN"},
    "SDP":  {"SD", "SDP", "SDG", "SDN"},
    "SDG":  {"SD", "SDP", "SDG", "SDN"},
    "SF":   {"SF", "SFG", "SFO", "SFN"},
    "SFG":  {"SF", "SFG", "SFO", "SFN"},
    "SFO":  {"SF", "SFG", "SFO", "SFN"},
    "TB":   {"TB", "TBR", "TAM", "TBA"},
    "TBR":  {"TB", "TBR", "TAM", "TBA"},
    "TAM":  {"TB", "TBR", "TAM", "TBA"},
    "WSH":  {"WSH", "WSN", "WAS"},
    "WSN":  {"WSH", "WSN", "WAS"},
    "WAS":  {"WSH", "WSN", "WAS"},
    "LAA":  {"LAA", "ANA"},
    "ANA":  {"LAA", "ANA"},
    "LAD":  {"LAD", "LAN", "LOS"},
    "LAN":  {"LAD", "LAN", "LOS"},
    "CHW":  {"CHW", "CWS", "CHA"},
    "CWS":  {"CHW", "CWS", "CHA"},
    "CHA":  {"CHW", "CWS", "CHA"},
    "CHC":  {"CHC", "CUB", "CHN"},
    "CUB":  {"CHC", "CUB", "CHN"},
    "CHN":  {"CHC", "CUB", "CHN"},
    "NYY":  {"NYY", "NYA"},
    "NYA":  {"NYY", "NYA"},
    "NYM":  {"NYM", "NYN"},
    "NYN":  {"NYM", "NYN"},
    "STL":  {"STL", "SLN"},
    "SLN":  {"STL", "SLN"},
    "MIA":  {"MIA", "FLA", "FLO"},
    "FLA":  {"MIA", "FLA", "FLO"},
    "FLO":  {"MIA", "FLA", "FLO"},
    "OAK":  {"OAK", "ATH"},
    "ATH":  {"OAK", "ATH"},
    "ARI":  {"ARI", "AZ"},
    "AZ":   {"ARI", "AZ"},
}

_SBR_BOOK_PRIORITY = [
    "draftkings", "fanduel", "bet365", "caesars", "betmgm",
    "bet_rivers_ny", "betrivers",
]


def _variants_of(code: str) -> set[str]:
    """Return the set of abbreviations that may represent the same franchise."""
    c = (code or "").strip().upper()
    return _TEAM_VARIANTS.get(c, {c})


def _load_sbr_run_line_lookup(json_paths: list[Path]) -> pd.DataFrame:
    """Read SBR-style JSON dumps and return a (date, teams) → run_line frame.

    Columns: date, away_team_short, home_team_short, home_run_line,
    home_run_line_odds, away_run_line, away_run_line_odds.

    Team codes are the raw SBR ``shortName`` values; the caller is expected to
    normalize against xlsx team codes via ``_variants_of`` before joining.
    """
    frames: list[pd.DataFrame] = []
    for path in json_paths:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                data = _json.load(f)
        except (OSError, ValueError) as e:
            logger.warning("Failed to read SBR JSON %s: %s", path, e)
            continue
        if not isinstance(data, dict):
            logger.warning("Unexpected SBR JSON shape in %s (not a dict)", path)
            continue

        rows: list[dict] = []
        for date_str, games in data.items():
            if not isinstance(games, list):
                continue
            try:
                dt = pd.Timestamp(date_str).normalize()
            except (ValueError, TypeError):
                continue
            for game in games:
                if not isinstance(game, dict):
                    continue
                gv = game.get("gameView") or {}
                if gv.get("gameType") and gv.get("gameType") != "R":
                    continue
                away_short = (gv.get("awayTeam") or {}).get("shortName", "")
                home_short = (gv.get("homeTeam") or {}).get("shortName", "")
                if not away_short or not home_short:
                    continue
                spread_books = (game.get("odds") or {}).get("pointspread") or []
                if not spread_books:
                    continue
                home_rl = home_rl_odds = away_rl = away_rl_odds = np.nan
                # Try a preferred book, then fall back to any book with a spread.
                search_order = list(_SBR_BOOK_PRIORITY)
                seen = set(search_order)
                for entry in spread_books:
                    name = entry.get("sportsbook", "")
                    if name and name not in seen:
                        search_order.append(name)
                        seen.add(name)
                for book_name in search_order:
                    for entry in spread_books:
                        if entry.get("sportsbook") != book_name:
                            continue
                        cl = entry.get("currentLine") or entry.get("openingLine") or {}
                        hs = cl.get("homeSpread")
                        if hs is None:
                            continue
                        home_rl = hs
                        home_rl_odds = cl.get("homeOdds", np.nan)
                        raw_as = cl.get("awaySpread")
                        away_rl = raw_as if raw_as is not None else -hs
                        away_rl_odds = cl.get("awayOdds", np.nan)
                        break
                    if pd.notna(home_rl):
                        break
                if pd.isna(home_rl):
                    continue
                rows.append({
                    "date": dt,
                    "away_team_short": str(away_short).upper(),
                    "home_team_short": str(home_short).upper(),
                    "home_run_line": float(home_rl),
                    "home_run_line_odds": (
                        float(home_rl_odds) if pd.notna(home_rl_odds) else np.nan
                    ),
                    "away_run_line": float(away_rl),
                    "away_run_line_odds": (
                        float(away_rl_odds) if pd.notna(away_rl_odds) else np.nan
                    ),
                })

        if rows:
            frames.append(pd.DataFrame(rows))
            logger.info(
                "Loaded %d run-line rows from SBR JSON: %s",
                len(rows), path.name,
            )

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["date", "away_team_short", "home_team_short"], keep="first"
    )
    return combined


def enrich_run_line_from_sbr(
    games: pd.DataFrame,
    *,
    json_paths: list[Path] | None = None,
    seasons: list[int] | None = None,
) -> pd.DataFrame:
    """Backfill NaN ``home_run_line`` / ``away_run_line`` (+ odds) from SBR JSON.

    Non-destructive: rows that already have a run_line value are preserved.
    Safe no-op if no JSON source file is present.

    By default only 2022-2025 are considered because those are the seasons
    where the xlsx-level gap was identified.  Pass ``seasons=None`` to limit;
    an explicit list can widen (or narrow) the scope.
    """
    paths = json_paths or SBR_JSON_CANDIDATES
    existing = [p for p in paths if Path(p).exists()]
    if not existing:
        logger.info(
            "SBR JSON not found at %s; skipping run_line enrichment.",
            [str(p) for p in paths],
        )
        return games

    rl_cols = [
        "home_run_line", "home_run_line_odds",
        "away_run_line", "away_run_line_odds",
    ]
    missing_cols = [c for c in rl_cols if c not in games.columns]
    if missing_cols:
        logger.warning(
            "games missing %s; skipping run_line enrichment", missing_cols
        )
        return games

    target_seasons = seasons if seasons is not None else [2022, 2023, 2024, 2025]
    scope = games[games["season"].isin(target_seasons)]
    n_nan = int(scope["home_run_line"].isna().sum())
    if n_nan == 0:
        logger.info(
            "run_line already populated for seasons %s; nothing to enrich.",
            target_seasons,
        )
        return games

    logger.info(
        "Enriching run_line from SBR JSON for seasons %s "
        "(%d/%d rows currently NaN)",
        target_seasons, n_nan, len(scope),
    )

    lookup = _load_sbr_run_line_lookup(existing)
    if lookup.empty:
        logger.warning(
            "SBR JSON had no usable run_line rows; nothing enriched."
        )
        return games

    idx: dict[tuple, dict] = {}
    for _, r in lookup.iterrows():
        dt = r["date"]
        home_vars = _variants_of(r["home_team_short"])
        away_vars = _variants_of(r["away_team_short"])
        payload = {
            "home_run_line": r["home_run_line"],
            "home_run_line_odds": r["home_run_line_odds"],
            "away_run_line": r["away_run_line"],
            "away_run_line_odds": r["away_run_line_odds"],
        }
        for h in home_vars:
            for a in away_vars:
                # First writer wins so that preferred books (checked first in
                # _load_sbr_run_line_lookup) are not clobbered by later entries.
                idx.setdefault((dt, h, a), payload)

    out = games.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()

    mask = (
        out["season"].isin(target_seasons)
        & out["home_run_line"].isna()
    )

    filled = 0
    fill_cols = list(rl_cols)
    for i in out.index[mask]:
        key = (
            out.at[i, "date"],
            str(out.at[i, "home_team"]).strip().upper(),
            str(out.at[i, "away_team"]).strip().upper(),
        )
        match = idx.get(key)
        if match is None:
            continue
        for col in fill_cols:
            out.at[i, col] = match[col]
        filled += 1

    denom = max(int(mask.sum()), 1)
    logger.info(
        "Run-line enrichment: %d/%d NaN rows filled in seasons %s (%.1f%%)",
        filled, int(mask.sum()), target_seasons, 100.0 * filled / denom,
    )
    return out


def merge_retrosheet_starter_entering_features(
    games: pd.DataFrame,
    *,
    entering_path: Path | None = None,
    entering_df: pd.DataFrame | None = None,
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
    if entering_df is not None:
        entering = entering_df.copy()
    elif entering_path is not None:
        if not Path(entering_path).exists():
            raise FileNotFoundError(
                f"Entering-game features not found: {entering_path}. "
                "Run scripts/build_retrosheet_pitchers.py first."
            )
        entering = pd.read_parquet(entering_path)
    else:
        entering = load_combined_starter_entering_features()
        if entering.empty:
            raise FileNotFoundError(
                "No starter entering features found in either pitchers/ or "
                "pitchers_2026/. Run scripts/build_retrosheet_pitchers.py "
                "and/or backfill 2026 boxscores."
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
