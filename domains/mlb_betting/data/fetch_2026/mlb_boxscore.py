"""MLB Stats API boxscore fetcher — pitcher-level game logs for 2026.

Retrosheet won't publish 2026 data until after the season. This module
fills the gap by fetching real-time boxscores from the MLB Stats API and
producing parquet files in the same schema the feature pipeline expects.

Endpoints:
  Schedule:  GET https://statsapi.mlb.com/api/v1/schedule?date=YYYY-MM-DD&sportId=1
  Boxscore:  GET https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore

Output:
  data/processed/pitchers_2026/pitcher_game_logs.parquet  — all pitchers, all games
  data/processed/pitchers_2026/starter_game_logs.parquet  — starters only (p_seq=1)
  data/processed/pitchers_2026/starter_entering_features.parquet
  data/processed/pitchers_2026/game_id_bridge.parquet
  data/processed/retrosheet/bullpen_features.parquet  — drop-in for feature pipeline
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from .team_mapping import normalize_team

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com"
RATE_LIMIT_SECONDS = 0.5
_last_request_time = 0.0

BASE_DIR = Path(__file__).resolve().parent.parent  # data/
OUTPUT_DIR = BASE_DIR / "processed" / "pitchers_2026"
RETROSHEET_OUTPUT_DIR = BASE_DIR / "processed" / "retrosheet"
# Also write to the pitchers/ dir so the feature pipeline finds them
PITCHERS_OUTPUT_DIR = BASE_DIR / "processed" / "pitchers"
STATE_PATH = Path(__file__).parent / "state.json"


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# MLB Stats API calls
# ---------------------------------------------------------------------------


def fetch_schedule(dt: date) -> list[dict]:
    """Fetch MLB schedule for a date. Returns list of game entries."""
    _rate_limit()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(
            f"{MLB_API_BASE}/api/v1/schedule",
            params={
                "date": dt.strftime("%Y-%m-%d"),
                "sportId": 1,
                "hydrate": "team",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("abstractGameState") == "Final":
                games.append(g)
    return games


def fetch_boxscore(game_pk: int) -> dict:
    """Fetch full boxscore for a game."""
    _rate_limit()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(f"{MLB_API_BASE}/api/v1/game/{game_pk}/boxscore")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Parse boxscore into pitcher game logs
# ---------------------------------------------------------------------------


def _parse_pitcher_lines(
    boxscore: dict,
    game_pk: int,
    game_date: date,
    home_team: str,
    away_team: str,
) -> list[dict]:
    """Extract pitcher lines from a boxscore. One row per pitcher appearance."""
    rows = []
    teams = boxscore.get("teams", {})

    for side_key, team_abbr in [("home", home_team), ("away", away_team)]:
        side_data = teams.get(side_key, {})
        pitchers_ids = side_data.get("pitchers", [])
        players = side_data.get("players", {})

        p_seq = 0
        for pid in pitchers_ids:
            player_key = f"ID{pid}"
            player = players.get(player_key, {})
            if not player:
                continue

            stats = player.get("stats", {}).get("pitching", {})
            if not stats:
                continue

            p_seq += 1
            person = player.get("person", {})

            # Parse IP string like "6.1" → outs
            ip_str = stats.get("inningsPitched", "0")
            try:
                ip_parts = str(ip_str).split(".")
                full_innings = int(ip_parts[0])
                partial = int(ip_parts[1]) if len(ip_parts) > 1 else 0
                outs = full_innings * 3 + partial
            except (ValueError, IndexError):
                outs = 0

            rows.append({
                "gid": f"MLB{game_pk}",
                "season": game_date.year,
                "date": pd.Timestamp(game_date),
                "game_num": 0,
                "home_team": home_team,
                "away_team": away_team,
                "team": team_abbr,
                "pitcher_id": str(pid),
                "pitcher_name": person.get("fullName", ""),
                "p_seq": p_seq,
                "p_ipouts": outs,
                "p_h": int(stats.get("hits", 0)),
                "p_w": int(stats.get("baseOnBalls", 0)),
                "p_k": int(stats.get("strikeOuts", 0)),
                "p_er": int(stats.get("earnedRuns", 0)),
                "p_hr": int(stats.get("homeRuns", 0)),
                "p_r": int(stats.get("runs", 0)),
                "p_bfp": int(stats.get("battersFaced", 0)),
            })

    return rows


def _normalize_mlb_team(game_data: dict, side: str) -> str:
    """Extract and normalize team abbreviation from schedule game data."""
    team_data = game_data.get("teams", {}).get(side, {}).get("team", {})
    abbr = team_data.get("abbreviation", "")
    try:
        return normalize_team(abbr)
    except KeyError:
        return abbr


# ---------------------------------------------------------------------------
# Fetch all boxscores for a date
# ---------------------------------------------------------------------------


def fetch_date_pitcher_logs(dt: date) -> pd.DataFrame:
    """Fetch all pitcher game logs for completed games on a date."""
    games = fetch_schedule(dt)
    if not games:
        logger.info("No completed games on %s", dt)
        return pd.DataFrame()

    all_rows = []
    for game in games:
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        home_team = _normalize_mlb_team(game, "home")
        away_team = _normalize_mlb_team(game, "away")

        try:
            boxscore = fetch_boxscore(game_pk)
            rows = _parse_pitcher_lines(boxscore, game_pk, dt, home_team, away_team)
            all_rows.extend(rows)
            logger.info(
                "  %s @ %s (gPk=%s): %d pitcher lines",
                away_team, home_team, game_pk, len(rows),
            )
        except Exception as e:
            logger.warning("Failed to fetch boxscore for gamePk=%s: %s", game_pk, e)

    if not all_rows:
        return pd.DataFrame()

    return pd.DataFrame(all_rows)


# ---------------------------------------------------------------------------
# Incremental store
# ---------------------------------------------------------------------------


def _load_pitcher_logs() -> pd.DataFrame:
    """Load existing pitcher game logs parquet."""
    path = OUTPUT_DIR / "pitcher_game_logs.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def _save_pitcher_logs(df: pd.DataFrame) -> None:
    """Save pitcher game logs parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_DIR / "pitcher_game_logs.parquet", index=False)


# ---------------------------------------------------------------------------
# Build features from pitcher logs (mirrors retrosheet_pitchers.py)
# ---------------------------------------------------------------------------


def build_starter_logs(pitcher_logs: pd.DataFrame) -> pd.DataFrame:
    """Extract starter rows (p_seq=1) and compute derived fields."""
    if pitcher_logs.empty:
        return pd.DataFrame()

    starters = pitcher_logs[pitcher_logs["p_seq"] == 1].copy()
    starters["is_home"] = starters["team"] == starters["home_team"]
    starters["opponent"] = np.where(
        starters["is_home"], starters["away_team"], starters["home_team"]
    )
    starters["outs"] = starters["p_ipouts"].astype(int)
    starters["ip"] = starters["outs"] / 3.0
    starters["h"] = starters["p_h"].astype(int)
    starters["bb"] = starters["p_w"].astype(int)
    starters["so"] = starters["p_k"].astype(int)
    starters["er"] = starters["p_er"].astype(int)
    starters["hr"] = starters["p_hr"].astype(int)

    # Bullpen flags per (gid, team)
    starters = _add_bullpen_flags(starters, pitcher_logs)

    return starters


def _add_bullpen_flags(
    starters: pd.DataFrame, all_pitchers: pd.DataFrame
) -> pd.DataFrame:
    """Add bullpen-day detection flags (same logic as retrosheet_pitchers.py)."""
    NO_STARTER_MAX_OUTS = 12  # 4.0 IP
    OPENER_MAX_OUTS = 6  # 2.0 IP

    grp = all_pitchers.groupby(["gid", "team"], sort=False)
    max_outs = grp["p_ipouts"].max().rename("max_outs")
    n_pitchers = grp.size().rename("n_pitchers")

    # Starter outs
    starter_info = all_pitchers[all_pitchers["p_seq"] == 1][
        ["gid", "team", "pitcher_id", "p_ipouts"]
    ].rename(columns={"pitcher_id": "starter_id", "p_ipouts": "starter_outs"})
    starter_info = starter_info.drop_duplicates(subset=["gid", "team"], keep="first")

    # Bulk pitcher (most outs)
    idx = grp["p_ipouts"].idxmax()
    bulk = all_pitchers.loc[idx, ["gid", "team", "pitcher_id", "p_ipouts"]].rename(
        columns={"pitcher_id": "bulk_pitcher_id", "p_ipouts": "bulk_outs"}
    )

    flags = (
        pd.concat([max_outs, n_pitchers], axis=1)
        .reset_index()
        .merge(starter_info, on=["gid", "team"], how="left")
        .merge(bulk, on=["gid", "team"], how="left")
    )

    flags["is_bullpen_no_starter"] = flags["max_outs"] < NO_STARTER_MAX_OUTS
    flags["is_opener_game"] = (
        (flags["starter_outs"].fillna(0) <= OPENER_MAX_OUTS)
        & (flags["bulk_pitcher_id"] != flags["starter_id"])
        & (flags["max_outs"] >= NO_STARTER_MAX_OUTS)
    )
    flags["starter_is_bulk"] = flags["starter_id"] == flags["bulk_pitcher_id"]
    flags["max_ip"] = flags["max_outs"] / 3.0
    flags["starter_ip"] = flags["starter_outs"].fillna(0).astype(int) / 3.0
    flags["bulk_ip"] = flags["bulk_outs"].fillna(0).astype(int) / 3.0

    starters = starters.merge(flags, on=["gid", "team"], how="left", validate="m:1")
    return starters


def _safe_div(n: pd.Series, d: pd.Series, *, eps: float = 1e-9) -> pd.Series:
    return n / (d.replace(0, np.nan) + eps)


def build_entering_features(
    starter_logs: pd.DataFrame,
    *,
    short_window: int = 5,
    long_window: int = 15,
) -> pd.DataFrame:
    """Compute strict entering-game rolling metrics (mirrors retrosheet_pitchers.py)."""
    if starter_logs.empty:
        return pd.DataFrame()

    df = starter_logs.copy()
    df = df.sort_values(["pitcher_id", "date", "game_num"]).reset_index(drop=True)
    grp = df.groupby("pitcher_id", sort=False)

    FIP_CONSTANT = 3.10
    sum_cols = ["h", "bb", "so", "hr", "er", "outs"]

    for c in sum_cols:
        shifted = grp[c].shift(1)
        df[f"{c}_short_sum"] = (
            shifted.groupby(df["pitcher_id"])
            .rolling(short_window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )
        df[f"{c}_long_sum"] = (
            shifted.groupby(df["pitcher_id"])
            .rolling(long_window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )

    # Start counts
    shifted_outs = grp["outs"].shift(1)
    df["starts_prior"] = grp.cumcount()
    df["starts_short"] = (
        shifted_outs.groupby(df["pitcher_id"])
        .rolling(short_window, min_periods=1)
        .count()
        .reset_index(level=0, drop=True)
        .astype(int)
    )
    df["starts_long"] = (
        shifted_outs.groupby(df["pitcher_id"])
        .rolling(long_window, min_periods=1)
        .count()
        .reset_index(level=0, drop=True)
        .astype(int)
    )

    for prefix in ["short", "long"]:
        outs_sum = df[f"outs_{prefix}_sum"]
        ip = outs_sum / 3.0
        h_sum = df[f"h_{prefix}_sum"]
        bb_sum = df[f"bb_{prefix}_sum"]
        so_sum = df[f"so_{prefix}_sum"]
        hr_sum = df[f"hr_{prefix}_sum"]

        df[f"ip_{prefix}"] = ip
        df[f"whip_{prefix}"] = _safe_div(h_sum + bb_sum, ip)
        df[f"kbb_{prefix}"] = (so_sum + 1.0) / (bb_sum + 1.0)
        df[f"k9_{prefix}"] = _safe_div(9.0 * so_sum, ip)
        df[f"bb9_{prefix}"] = _safe_div(9.0 * bb_sum, ip)
        df[f"hr9_{prefix}"] = _safe_div(9.0 * hr_sum, ip)
        df[f"fip_{prefix}"] = _safe_div(
            13.0 * hr_sum + 3.0 * bb_sum - 2.0 * so_sum, ip
        ) + FIP_CONSTANT
        df[f"ip_per_start_{prefix}"] = _safe_div(
            ip, df[f"starts_{prefix}"].clip(lower=1).astype(float)
        )

    keep = [
        "gid", "season", "date", "game_num", "home_team", "away_team",
        "team", "is_home", "opponent", "pitcher_id",
        "starts_prior", "starts_short", "starts_long",
        "ip_short", "ip_long",
        "whip_short", "whip_long", "kbb_short", "kbb_long",
        "k9_short", "k9_long", "bb9_short", "bb9_long",
        "hr9_short", "hr9_long", "fip_short", "fip_long",
        "ip_per_start_short", "ip_per_start_long",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].copy()


def build_game_id_bridge(starter_logs: pd.DataFrame) -> pd.DataFrame:
    """Build 1-row-per-game bridge with home/away starter IDs and bullpen flags."""
    if starter_logs.empty:
        return pd.DataFrame()

    df = starter_logs.copy()
    home = df[df["team"] == df["home_team"]][
        ["gid", "pitcher_id", "is_bullpen_no_starter", "is_opener_game"]
    ].rename(columns={
        "pitcher_id": "home_starter_id",
        "is_bullpen_no_starter": "home_is_bullpen_no_starter",
        "is_opener_game": "home_is_opener_game",
    })
    away = df[df["team"] == df["away_team"]][
        ["gid", "pitcher_id", "is_bullpen_no_starter", "is_opener_game"]
    ].rename(columns={
        "pitcher_id": "away_starter_id",
        "is_bullpen_no_starter": "away_is_bullpen_no_starter",
        "is_opener_game": "away_is_opener_game",
    })

    base_cols = ["gid", "season", "date", "home_team", "away_team", "game_num"]
    base = df[base_cols].drop_duplicates(subset=["gid"], keep="first")
    bridge = base.merge(home, on="gid", how="left").merge(away, on="gid", how="left")
    return bridge


# ---------------------------------------------------------------------------
# Bullpen features (mirrors bullpen_features.py for 2026)
# ---------------------------------------------------------------------------


def build_bullpen_features(pitcher_logs: pd.DataFrame) -> pd.DataFrame:
    """Compute entering-game bullpen features per (team, date).

    Features:
      bp_fip_short  — 5-game rolling bullpen FIP
      bp_fip_7g     — 7-game rolling bullpen FIP
      bp_fip_long   — 15-game rolling bullpen FIP
      bp_ip_3d      — total bullpen IP in last 3 calendar days (fatigue)
    """
    if pitcher_logs.empty:
        return pd.DataFrame()

    FIP_CONSTANT = 3.10

    # Relievers only (p_seq > 1)
    bp = pitcher_logs[pitcher_logs["p_seq"] > 1].copy()
    if bp.empty:
        return pd.DataFrame()

    bp["date"] = pd.to_datetime(bp["date"])

    # Aggregate reliever stats per (team, date/game)
    agg = bp.groupby(["team", "gid", "date"], sort=False).agg(
        bp_ip_outs=("p_ipouts", "sum"),
        bp_h=("p_h", "sum"),
        bp_bb=("p_w", "sum"),
        bp_so=("p_k", "sum"),
        bp_hr=("p_hr", "sum"),
        bp_er=("p_er", "sum"),
    ).reset_index()

    agg = agg.sort_values(["team", "date"]).reset_index(drop=True)
    agg["bp_ip"] = agg["bp_ip_outs"] / 3.0

    # Per-game FIP
    agg["bp_fip_game"] = _safe_div(
        13.0 * agg["bp_hr"] + 3.0 * agg["bp_bb"] - 2.0 * agg["bp_so"],
        agg["bp_ip"],
    ) + FIP_CONSTANT

    # Rolling FIP (entering-game: shift then roll)
    for team, tdf in agg.groupby("team", sort=False):
        idx = tdf.index
        shifted = tdf["bp_fip_game"].shift(1)
        for window, col in [(5, "bp_fip_short"), (7, "bp_fip_7g"), (15, "bp_fip_long")]:
            agg.loc[idx, col] = shifted.rolling(window, min_periods=1).mean().values

    # 3-day bullpen IP (fatigue) — sum of BP IP in the 3 calendar days before game
    fatigue_rows = []
    for team, tdf in agg.groupby("team", sort=False):
        tdf = tdf.sort_values("date")
        dates = tdf["date"].values
        ips = tdf["bp_ip"].values
        for i in range(len(tdf)):
            game_date = dates[i]
            window_start = game_date - np.timedelta64(3, "D")
            mask = (dates < game_date) & (dates >= window_start)
            fatigue_rows.append({
                "team": team,
                "date": game_date,
                "gid": tdf.iloc[i]["gid"],
                "bp_ip_3d": float(ips[mask].sum()),
            })

    fatigue_df = pd.DataFrame(fatigue_rows)

    # Merge rolling FIP + fatigue
    result = agg[["team", "date", "gid", "bp_fip_short", "bp_fip_7g", "bp_fip_long"]].merge(
        fatigue_df[["team", "date", "gid", "bp_ip_3d"]],
        on=["team", "date", "gid"],
        how="left",
    )

    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_boxscore_fetch(dt: date | None = None) -> int:
    """Fetch pitcher boxscores for a date, append to store, rebuild features.

    Returns number of pitcher lines fetched.
    """
    if dt is None:
        dt = date.today()

    logger.info("=== BOXSCORE fetch for %s ===", dt)

    new_logs = fetch_date_pitcher_logs(dt)
    if new_logs.empty:
        logger.warning("No pitcher data for %s", dt)
        return 0

    # Append to incremental store
    existing = _load_pitcher_logs()
    combined = pd.concat([existing, new_logs], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["gid", "team", "pitcher_id", "p_seq"], keep="last"
    )
    combined = combined.sort_values(["date", "gid", "team", "p_seq"]).reset_index(drop=True)
    _save_pitcher_logs(combined)

    logger.info("Pitcher logs: %d total rows (%d new)", len(combined), len(new_logs))

    # Rebuild all derived features from the full store
    _rebuild_features(combined)

    # Update state
    state = _load_state()
    state["last_boxscore_date"] = str(dt)
    state["total_pitcher_lines"] = len(combined)
    _save_state(state)

    return len(new_logs)


def run_boxscore_backfill(start: date, end: date) -> int:
    """Backfill pitcher boxscores for a date range."""
    logger.info("=== BOXSCORE BACKFILL %s → %s ===", start, end)
    total = 0
    current = start
    while current <= end:
        n = run_boxscore_fetch(current)
        total += n
        current += timedelta(days=1)
    logger.info("Backfill complete: %d pitcher lines total", total)
    return total


def _rebuild_features(pitcher_logs: pd.DataFrame) -> None:
    """Rebuild all derived parquets from the full pitcher log store."""
    # 1. Starter game logs
    starter_logs = build_starter_logs(pitcher_logs)
    if starter_logs.empty:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    starter_logs.to_parquet(OUTPUT_DIR / "starter_game_logs.parquet", index=False)

    # 2. Entering features
    entering = build_entering_features(starter_logs)
    entering.to_parquet(OUTPUT_DIR / "starter_entering_features.parquet", index=False)

    # 3. Game ID bridge
    bridge = build_game_id_bridge(starter_logs)
    bridge.to_parquet(OUTPUT_DIR / "game_id_bridge.parquet", index=False)

    # Also write to pitchers/ dir (where features.py looks by default)
    PITCHERS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entering.to_parquet(PITCHERS_OUTPUT_DIR / "starter_entering_features.parquet", index=False)
    bridge.to_parquet(PITCHERS_OUTPUT_DIR / "game_id_bridge.parquet", index=False)

    # 4. Bullpen features
    bp_features = build_bullpen_features(pitcher_logs)
    if not bp_features.empty:
        RETROSHEET_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        bp_features.to_parquet(
            RETROSHEET_OUTPUT_DIR / "bullpen_features.parquet", index=False
        )

    n_games = len(bridge)
    n_bp = len(bp_features) if not bp_features.empty else 0
    logger.info(
        "Rebuilt features: %d games, %d starter entering rows, %d bullpen rows",
        n_games, len(entering), n_bp,
    )
