"""Orchestrator: daily fetch → merge → parquet → xlsx export.

Two phases per day:
  pregame  — capture odds + starters (before first pitch)
  postgame — capture results + linescores, merge with odds, export

Storage:
  data/raw/odds_2026/pregame_YYYYMMDD.json  — raw ESPN odds snapshot
  data/raw/odds_2026/games_2026.parquet     — incremental game store
  data/raw/odds/mlb-odds-2026.xlsx          — 23-column xlsx for data_loader
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .espn_api import (
    OddsRow,
    PitcherRow,
    ResultRow,
    fetch_scoreboard,
    parse_postgame_results,
    parse_pregame_odds,
    parse_probable_pitchers,
)
from .io_safety import (
    append_audit,
    atomic_write_text,
    atomic_write_xlsx,
    safe_write_parquet,
)
from .mlb_api import fetch_pitcher_hand, load_pitcher_cache, save_pitcher_cache
from .pitcher_codes import PitcherCodeRegistry
from .runtime_files import state_path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # data/
RAW_2026_DIR = BASE_DIR / "raw" / "odds_2026"
RAW_ODDS_DIR = BASE_DIR / "raw" / "odds"
PARQUET_PATH = RAW_2026_DIR / "games_2026.parquet"
XLSX_PATH = RAW_ODDS_DIR / "mlb-odds-2026.xlsx"
XLSX_COLUMNS = [
    "date", "rot", "vh", "team", "pitcher",
    "inn_1", "inn_2", "inn_3", "inn_4", "inn_5",
    "inn_6", "inn_7", "inn_8", "inn_9", "final",
    "open_ml", "close_ml",
    "run_line", "run_line_odds",
    "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    path = state_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    atomic_write_text(json.dumps(state, indent=2, default=str), state_path())


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------


def _find_latest_snapshot(dt: date) -> Path | None:
    """Find the latest pregame odds snapshot for a given date.

    Files are named pregame_YYYYMMDD_HHMM.json. Returns the one with the
    latest timestamp, or falls back to pregame_YYYYMMDD.json (legacy format).
    """
    prefix = f"pregame_{dt.strftime('%Y%m%d')}"
    candidates = sorted(RAW_2026_DIR.glob(f"{prefix}*.json"))
    if candidates:
        return candidates[-1]  # sorted alphabetically = latest HHMM wins
    return None


def _load_parquet() -> pd.DataFrame:
    if PARQUET_PATH.exists():
        return pd.read_parquet(PARQUET_PATH)
    return pd.DataFrame(columns=XLSX_COLUMNS + ["event_id"])


def _save_parquet(df: pd.DataFrame) -> None:
    safe_write_parquet(
        df,
        PARQUET_PATH,
        generator="orchestrator.run_postgame",
        date_col="date",
        audit_action="save_games_2026",
    )


def _export_xlsx(df: pd.DataFrame) -> Path:
    """Export the 23-column xlsx for data_loader.py consumption.

    No backup: derived from the parquet which is already backed up.
    """
    out = df[XLSX_COLUMNS].copy()
    atomic_write_xlsx(out, XLSX_PATH, index=False, header=True)
    size_kb = XLSX_PATH.stat().st_size / 1024
    logger.info("Exported %s (%.0f KB, %d rows)", XLSX_PATH.name, size_kb, len(out))
    return XLSX_PATH


# ---------------------------------------------------------------------------
# Pitcher resolution
# ---------------------------------------------------------------------------


def _resolve_pitcher_codes(
    names: list[str],
    cache: dict[str, dict],
    registry: PitcherCodeRegistry,
) -> list[str]:
    """Convert full pitcher names to LASTNAME-Hand codes."""
    codes = []
    for name in names:
        if not name:
            codes.append("")
            continue
        hand = fetch_pitcher_hand(name, cache)
        code = registry.get_code(name, hand)
        codes.append(code)
    return codes


# ---------------------------------------------------------------------------
# Convert dataclass rows to DataFrame rows
# ---------------------------------------------------------------------------


def _date_to_mmdd(dt: date) -> int:
    """Convert date to MMDD integer (e.g., April 1 → 401)."""
    return dt.month * 100 + dt.day


def _odds_rows_to_df(
    odds_rows: list[OddsRow],
    pitcher_cache: dict[str, dict],
    registry: PitcherCodeRegistry,
) -> pd.DataFrame:
    """Convert OddsRow list to a DataFrame with odds columns populated."""
    if not odds_rows:
        return pd.DataFrame()

    records = []
    for row in odds_rows:
        pitcher_code = ""
        if row.pitcher_name:
            hand = fetch_pitcher_hand(row.pitcher_name, pitcher_cache)
            pitcher_code = registry.get_code(row.pitcher_name, hand)

        records.append({
            "event_id": row.event_id,
            "date": _date_to_mmdd(row.game_date),
            "team": row.team_abbr,
            "vh": "H" if row.home_away == "home" else "V",
            "pitcher": pitcher_code,
            "open_ml": row.moneyline,
            "close_ml": row.moneyline,  # single snapshot
            "run_line": row.spread_line,
            "run_line_odds": row.spread_odds,
            "open_ou": row.total_line,
            "open_ou_odds": row.total_odds,
            "close_ou": row.total_line,  # single snapshot
            "close_ou_odds": row.total_odds,
        })

    return pd.DataFrame(records)


def _result_rows_to_df(
    result_rows: list[ResultRow],
    pitcher_cache: dict[str, dict],
    registry: PitcherCodeRegistry,
) -> pd.DataFrame:
    """Convert ResultRow list to a DataFrame with result columns populated."""
    if not result_rows:
        return pd.DataFrame()

    records = []
    for row in result_rows:
        pitcher_code = ""
        if row.pitcher_name:
            hand = fetch_pitcher_hand(row.pitcher_name, pitcher_cache)
            pitcher_code = registry.get_code(row.pitcher_name, hand)

        rec = {
            "event_id": row.event_id,
            "date": _date_to_mmdd(row.game_date),
            "team": row.team_abbr,
            "vh": "H" if row.home_away == "home" else "V",
            "pitcher": pitcher_code,
            "final": row.final,
        }
        for i, runs in enumerate(row.innings, start=1):
            rec[f"inn_{i}"] = runs
        # Pad missing innings
        for i in range(len(row.innings) + 1, 10):
            rec[f"inn_{i}"] = 0

        records.append(rec)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Dedup helper — Bug E fix
# ---------------------------------------------------------------------------


def _dedup_games(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate game rows.

    Doubleheaders share (date, team, vh) but have distinct event_ids — the
    legacy (date, team, vh) dedup silently collapsed one DH game per pair
    (Bug E in plans/§2). The fix dedups by (event_id, team, vh) for any row
    that has an event_id, and falls back to the legacy key only for legacy
    rows pre-dating the event_id column.
    """
    if df.empty:
        return df
    if "event_id" not in df.columns:
        return df.drop_duplicates(subset=["date", "team", "vh"], keep="last")

    has_event = df["event_id"].notna()
    if has_event.all():
        return df.drop_duplicates(subset=["event_id", "team", "vh"], keep="last")
    if not has_event.any():
        return df.drop_duplicates(subset=["date", "team", "vh"], keep="last")

    with_event = df[has_event].drop_duplicates(
        subset=["event_id", "team", "vh"], keep="last"
    )
    without_event = df[~has_event].drop_duplicates(
        subset=["date", "team", "vh"], keep="last"
    )
    return pd.concat([with_event, without_event], ignore_index=True)


# ---------------------------------------------------------------------------
# Assign rotation numbers
# ---------------------------------------------------------------------------


def _assign_rot_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Assign sequential rotation numbers per date, paired V-H."""
    if df.empty:
        return df

    df = df.copy()
    df["rot"] = 0

    for dt in df["date"].unique():
        mask = df["date"] == dt
        n_rows = mask.sum()
        # Sequential from 901, each game gets a pair
        rots = []
        for i in range(n_rows):
            rots.append(901 + i)
        df.loc[mask, "rot"] = rots

    return df


# ---------------------------------------------------------------------------
# Pitcher backfill from snapshots
# ---------------------------------------------------------------------------


def _fill_pitchers_from_snapshots(
    df: pd.DataFrame, dt: date, odds_df: pd.DataFrame
) -> None:
    """Fill empty pitcher codes from pitcher snapshot or odds snapshot (in-place)."""
    if "pitcher" not in df.columns:
        return

    # Build pitcher lookup: event_id+team+vh → pitcher code
    pitcher_map: dict[tuple, str] = {}

    # Source 1: dedicated pitcher snapshot (highest priority)
    pitcher_path = RAW_2026_DIR / f"pitchers_{dt.strftime('%Y%m%d')}.json"
    if pitcher_path.exists():
        rows = json.loads(pitcher_path.read_text(encoding="utf-8"))
        for r in rows:
            vh = "H" if r["home_away"] == "home" else "V"
            key = (r["event_id"], r["team"], vh)
            code = r.get("pitcher_code", "")
            if code:
                pitcher_map[key] = code

    # Source 2: odds snapshot (fallback)
    if not odds_df.empty and "pitcher" in odds_df.columns:
        for _, row in odds_df.iterrows():
            key = (row["event_id"], row["team"], row["vh"])
            if key not in pitcher_map and row.get("pitcher"):
                pitcher_map[key] = row["pitcher"]

    # Apply
    for idx, row in df.iterrows():
        if not row.get("pitcher"):
            key = (row.get("event_id"), row["team"], row["vh"])
            if key in pitcher_map:
                df.at[idx, "pitcher"] = pitcher_map[key]


# ---------------------------------------------------------------------------
# Sort: V then H per game
# ---------------------------------------------------------------------------


def _sort_vh_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Sort so visitor row comes before home row for each game.

    Our xlsx convention: V row first, then H row. 'V' > 'H' alphabetically,
    so we sort vh descending to get V before H.
    """
    if df.empty:
        return df
    sort_cols = ["date", "event_id"] if "event_id" in df.columns else ["date"]
    df = df.copy()
    # Map V→0, H→1 for sorting (V first)
    df["_vh_sort"] = df["vh"].map({"V": 0, "H": 1}).fillna(2)
    df = df.sort_values(sort_cols + ["_vh_sort"]).reset_index(drop=True)
    df = df.drop(columns=["_vh_sort"])
    return df


# ---------------------------------------------------------------------------
# Public API: phase runners
# ---------------------------------------------------------------------------


def run_pregame(dt: date | None = None) -> int:
    """Fetch and store pre-game odds for today's scheduled games.

    Returns number of odds rows captured.
    """
    if dt is None:
        dt = date.today()

    logger.info("=== PREGAME fetch for %s ===", dt)

    data = fetch_scoreboard(dt)
    odds_rows = parse_pregame_odds(data, override_date=dt)

    if not odds_rows:
        logger.warning("No pre-game odds found for %s", dt)
        return 0

    # Save raw snapshot — timestamped so multiple captures per day are preserved
    from datetime import datetime as _dt

    now_str = _dt.now().strftime("%H%M")
    snapshot_path = RAW_2026_DIR / f"pregame_{dt.strftime('%Y%m%d')}_{now_str}.json"
    snapshot_payload = json.dumps(
        [
            {
                "event_id": r.event_id,
                "team": r.team_abbr,
                "home_away": r.home_away,
                "pitcher": r.pitcher_name,
                "moneyline": r.moneyline,
                "spread_line": r.spread_line,
                "spread_odds": r.spread_odds,
                "total_line": r.total_line,
                "total_odds": r.total_odds,
            }
            for r in odds_rows
        ],
        indent=2,
    )
    atomic_write_text(snapshot_payload, snapshot_path)
    logger.info("Saved odds snapshot: %s (%d rows)", snapshot_path.name, len(odds_rows))

    # Update state
    state = _load_state()
    state["last_pregame_date"] = str(dt)
    state["last_pregame_rows"] = len(odds_rows)
    _save_state(state)

    append_audit(
        "pregame_capture",
        target_date=dt,
        rows_total=len(odds_rows),
        files_written=[snapshot_path.name],
    )

    return len(odds_rows)


def run_pitchers(dt: date | None = None) -> int:
    """Fetch and cache probable starting pitchers for today's games.

    Saves to pitchers_YYYYMMDD.json. Resolves handedness via MLB Stats API
    and updates the pitcher cache so postgame doesn't need extra API calls.

    Returns number of pitcher rows captured.
    """
    if dt is None:
        dt = date.today()

    logger.info("=== PITCHERS fetch for %s ===", dt)

    data = fetch_scoreboard(dt)
    pitcher_rows = parse_probable_pitchers(data, override_date=dt)

    if not pitcher_rows:
        logger.warning("No probable pitchers found for %s", dt)
        return 0

    # Resolve handedness and build codes
    pitcher_cache = load_pitcher_cache()
    registry = PitcherCodeRegistry()
    resolved = []

    for row in pitcher_rows:
        hand = ""
        code = ""
        if row.pitcher_name:
            hand = fetch_pitcher_hand(row.pitcher_name, pitcher_cache)
            code = registry.get_code(row.pitcher_name, hand)
        resolved.append({
            "event_id": row.event_id,
            "team": row.team_abbr,
            "home_away": row.home_away,
            "pitcher_name": row.pitcher_name,
            "pitcher_code": code,
            "hand": hand,
        })

    save_pitcher_cache(pitcher_cache)

    # Save snapshot
    snapshot_path = RAW_2026_DIR / f"pitchers_{dt.strftime('%Y%m%d')}.json"
    atomic_write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), snapshot_path
    )
    logger.info("Saved pitchers: %s (%d rows)", snapshot_path.name, len(resolved))
    append_audit(
        "pitchers_capture",
        target_date=dt,
        rows_total=len(resolved),
        files_written=[snapshot_path.name],
    )

    state = _load_state()
    state["last_pitchers_date"] = str(dt)
    _save_state(state)

    return len(resolved)


def run_postgame(dt: date | None = None) -> int:
    """Fetch results for completed games, merge with pre-game odds, export xlsx.

    Returns number of game rows added.
    """
    if dt is None:
        dt = date.today()

    logger.info("=== POSTGAME fetch for %s ===", dt)

    pitcher_cache = load_pitcher_cache()
    registry = PitcherCodeRegistry()

    # 1. Fetch completed game results
    data = fetch_scoreboard(dt)
    result_rows = parse_postgame_results(data, override_date=dt)

    if not result_rows:
        logger.warning("No completed games found for %s", dt)
        return 0

    results_df = _result_rows_to_df(result_rows, pitcher_cache, registry)

    # 2. Load latest pre-game odds snapshot for this date
    snapshot_path = _find_latest_snapshot(dt)
    odds_df = pd.DataFrame()

    if snapshot_path is not None:
        logger.info("Using odds snapshot: %s", snapshot_path.name)
        raw_odds = json.loads(snapshot_path.read_text(encoding="utf-8"))
        # Reconstruct OddsRow objects from saved JSON
        odds_rows_reconstructed = [
            OddsRow(
                event_id=r["event_id"],
                game_date=dt,
                team_abbr=r["team"],
                home_away=r["home_away"],
                pitcher_name=r.get("pitcher", ""),
                moneyline=r.get("moneyline"),
                spread_line=r.get("spread_line"),
                spread_odds=r.get("spread_odds"),
                total_line=r.get("total_line"),
                total_odds=r.get("total_odds"),
            )
            for r in raw_odds
        ]
        odds_df = _odds_rows_to_df(odds_rows_reconstructed, pitcher_cache, registry)

    # 3. Merge results with odds
    if not odds_df.empty:
        merge_keys = ["event_id", "team", "vh"]
        odds_cols = [
            "open_ml", "close_ml", "run_line", "run_line_odds",
            "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
        ]
        # Keep only odds columns + merge keys from odds_df
        odds_subset = odds_df[merge_keys + odds_cols].copy()
        merged = results_df.merge(odds_subset, on=merge_keys, how="left")
    else:
        merged = results_df.copy()
        for col in ["open_ml", "close_ml", "run_line", "run_line_odds",
                     "open_ou", "open_ou_odds", "close_ou", "close_ou_odds"]:
            if col not in merged.columns:
                merged[col] = np.nan

    # 4. Fill missing pitchers from pitcher snapshot or odds snapshot
    _fill_pitchers_from_snapshots(merged, dt, odds_df)

    # 5. Sort V-then-H and assign rot numbers
    merged = _sort_vh_pairs(merged)
    merged = _assign_rot_numbers(merged)

    # 6. Ensure all columns exist
    for col in XLSX_COLUMNS:
        if col not in merged.columns:
            merged[col] = 0 if col.startswith("inn_") else np.nan

    # 7. Append to parquet store
    existing = _load_parquet()
    combined = pd.concat([existing, merged], ignore_index=True)
    combined = _dedup_games(combined)
    combined = _sort_vh_pairs(combined)
    combined = _assign_rot_numbers(combined)

    _save_parquet(combined)

    # 8. Export xlsx
    _export_xlsx(combined)

    # 9. Save pitcher cache
    save_pitcher_cache(pitcher_cache)

    # 10. Update state
    state = _load_state()
    state["last_postgame_date"] = str(dt)
    state["total_games"] = len(combined)
    _save_state(state)

    append_audit(
        "postgame_merge",
        target_date=dt,
        rows_added=len(merged),
        rows_total=len(combined),
        files_written=["games_2026.parquet", "mlb-odds-2026.xlsx"],
    )

    logger.info("Added %d rows for %s (total: %d)", len(merged), dt, len(combined))
    return len(merged)


def run_backfill(start: date, end: date) -> int:
    """Backfill results for a date range. Odds will be NaN for past days.

    Returns total rows added.
    """
    logger.info("=== BACKFILL %s → %s ===", start, end)

    pitcher_cache = load_pitcher_cache()
    registry = PitcherCodeRegistry()
    total_added = 0

    current = start
    while current <= end:
        logger.info("Backfilling %s...", current)

        data = fetch_scoreboard(current)
        result_rows = parse_postgame_results(data, override_date=current)

        if result_rows:
            results_df = _result_rows_to_df(result_rows, pitcher_cache, registry)

            # Check for pre-game snapshot (use latest for that date)
            snapshot_path = _find_latest_snapshot(current)
            if snapshot_path is not None:
                raw_odds = json.loads(snapshot_path.read_text(encoding="utf-8"))
                odds_rows = [
                    OddsRow(
                        event_id=r["event_id"],
                        game_date=current,
                        team_abbr=r["team"],
                        home_away=r["home_away"],
                        pitcher_name=r.get("pitcher", ""),
                        moneyline=r.get("moneyline"),
                        spread_line=r.get("spread_line"),
                        spread_odds=r.get("spread_odds"),
                        total_line=r.get("total_line"),
                        total_odds=r.get("total_odds"),
                    )
                    for r in raw_odds
                ]
                odds_df = _odds_rows_to_df(odds_rows, pitcher_cache, registry)
                merge_keys = ["event_id", "team", "vh"]
                odds_cols = [
                    "open_ml", "close_ml", "run_line", "run_line_odds",
                    "open_ou", "open_ou_odds", "close_ou", "close_ou_odds",
                ]
                odds_subset = odds_df[merge_keys + odds_cols].copy()
                results_df = results_df.merge(odds_subset, on=merge_keys, how="left")

            # Fill missing columns
            for col in XLSX_COLUMNS:
                if col not in results_df.columns:
                    results_df[col] = 0 if col.startswith("inn_") else np.nan

            existing = _load_parquet()
            combined = pd.concat([existing, results_df], ignore_index=True)
            combined = _dedup_games(combined)
            combined = _sort_vh_pairs(combined)
            combined = _assign_rot_numbers(combined)
            _save_parquet(combined)

            total_added += len(results_df)
            logger.info("  %s: %d rows", current, len(results_df))
        else:
            logger.info("  %s: no completed games", current)

        current += timedelta(days=1)

    # Final export + cache save
    if total_added > 0:
        final_df = _load_parquet()
        _export_xlsx(final_df)
        save_pitcher_cache(pitcher_cache)

    state = _load_state()
    state["last_backfill_end"] = str(end)
    state["total_games"] = len(_load_parquet())
    _save_state(state)

    logger.info("Backfill complete: %d rows added", total_added)
    return total_added
