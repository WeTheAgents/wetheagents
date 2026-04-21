"""MLB Stats API game-feed fetcher for 2026 lineup and inning-1 BABIP features.

Retrosheet will not publish in-season 2026 batter / play-by-play tables until
after the year ends. This module fills that gap from the MLB Stats API
``feed/live`` endpoint and writes a dual-path live dataset under
``data/processed/lineups_2026/``.

Outputs:
  data/processed/lineups_2026/batter_game_logs.parquet
  data/processed/lineups_2026/inning1_play_logs.parquet
  data/processed/lineups_2026/batter_entering_features.parquet
  data/processed/lineups_2026/game_lineup_features.parquet
  data/processed/lineups_2026/first_inning_babip.parquet
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from .io_safety import append_audit, atomic_write_text, safe_write_parquet
from .mlb_boxscore import fetch_schedule
from .runtime_files import state_path
from .team_mapping import normalize_team

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com"
RATE_LIMIT_SECONDS = 0.5
_last_request_time = 0.0

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "processed" / "lineups_2026"
BATTER_LOGS_PATH = OUTPUT_DIR / "batter_game_logs.parquet"
INNING1_PLAYS_PATH = OUTPUT_DIR / "inning1_play_logs.parquet"
BATTER_ENTERING_PATH = OUTPUT_DIR / "batter_entering_features.parquet"
LINEUP_FEATURES_PATH = OUTPUT_DIR / "game_lineup_features.parquet"
BABIP_FEATURES_PATH = OUTPUT_DIR / "first_inning_babip.parquet"

# MLB event types seen in real 2026 inning-1 feeds, plus a few official-score
# variants that occur rarely. Anything not listed here still falls through the
# generic result.type == "atBat" logic.
NON_AB_EVENTS = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "sac_bunt",
    "sac_bunt_double_play",
    "sac_fly",
    "sac_fly_double_play",
    "catcher_interf",
    "fan_interference",
}
K_EVENTS = {"strikeout", "strikeout_double_play"}
SF_EVENTS = {"sac_fly", "sac_fly_double_play"}
HIT_EVENTS = {
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "hr",
}
LIVE_BABIP_MIN_PA = 5
LIVE_BABIP_HISTORY_FLOOR = 20
LIVE_BABIP_PRIOR = 0.300
LIVE_BABIP_PRIOR_DENOM = 20.0

EMPTY_ENTERING_COLUMNS = [
    "batter_id",
    "season",
    "date",
    "gid",
    "team",
    "b_lp",
    "bat_hand",
    "b_obp_short",
    "b_k_rate_short",
    "b_hr_rate_short",
    "b_obp_long",
    "b_k_rate_long",
    "b_obp_vs_rhp",
    "b_k_rate_vs_rhp",
    "b_obp_vs_lhp",
    "b_k_rate_vs_lhp",
    "b_pa_short",
    "b_pa_long",
]
EMPTY_LINEUP_COLUMNS = [
    "gid",
    "team",
    "season",
    "date",
    "top3_obp_short",
    "top3_obp_long",
    "top3_k_rate_short",
    "top3_k_rate_long",
    "top3_hr_rate_short",
    "top3_obp_vs_rhp",
    "top3_k_rate_vs_rhp",
    "top3_obp_vs_lhp",
    "top3_k_rate_vs_lhp",
    "n_batters",
]
EMPTY_BABIP_COLUMNS = [
    "gid",
    "team",
    "date",
    "season",
    "top3_babip_inn1",
    "top3_babip_inn1_pa",
    "sp_babip_inn1",
    "sp_babip_inn1_pa",
]


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def _load_state() -> dict:
    path = state_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    atomic_write_text(json.dumps(state, indent=2, default=str), state_path())


def _to_int(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def _save_output(
    df: pd.DataFrame,
    path: Path,
    *,
    generator: str,
    audit_action: str,
) -> None:
    safe_write_parquet(
        df,
        path,
        generator=generator,
        date_col="date",
        audit_action=audit_action,
    )


def _dedup(df: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def _normalize_schedule_team(game: dict, side: str) -> str:
    abbr = (
        game.get("teams", {})
        .get(side, {})
        .get("team", {})
        .get("abbreviation", "")
    )
    return normalize_team(abbr)


def _to_retrosheet_team(team: str, season: int) -> str:
    from src.data_loader import _map_team_code_to_retrosheet  # noqa: PLC0415

    return _map_team_code_to_retrosheet(team, season)


def fetch_game_feed(game_pk: int) -> dict:
    """Fetch the full MLB Stats API live feed for a completed game."""
    _rate_limit()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(f"{MLB_API_BASE}/api/v1.1/game/{game_pk}/feed/live")
        resp.raise_for_status()
        return resp.json()


def _extract_player(game_data: dict, player_id: int | str | None) -> dict:
    if player_id in (None, ""):
        return {}
    return game_data.get("players", {}).get(f"ID{player_id}", {})


def _extract_pitch_hand(game_data: dict, player_id: int | str | None) -> str:
    player = _extract_player(game_data, player_id)
    hand = player.get("pitchHand", {}).get("code")
    return str(hand or "").strip().upper()


def _extract_bat_hand(game_data: dict, player_id: int | str | None) -> str:
    player = _extract_player(game_data, player_id)
    hand = player.get("batSide", {}).get("code")
    return str(hand or "").strip().upper()


def _starter_context(feed: dict, game_pk: int) -> dict[str, dict[str, object]]:
    """Return actual starter ids + hands for both sides of a completed game."""
    game_data = feed.get("gameData", {})
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    out: dict[str, dict[str, object]] = {}
    for side in ["home", "away"]:
        side_box = boxscore.get(side, {})
        pitcher_ids = side_box.get("pitchers", [])
        starter_id = pitcher_ids[0] if pitcher_ids else None
        starter_hand = _extract_pitch_hand(game_data, starter_id)
        out[side] = {"starter_id": starter_id, "starter_hand": starter_hand}

    # Fallback: infer from inning-1 matchup if the boxscore starter metadata is thin.
    if plays:
        top_first = next(
            (
                p for p in plays
                if p.get("about", {}).get("inning") == 1
                and p.get("about", {}).get("halfInning") == "top"
                and p.get("result", {}).get("type") == "atBat"
            ),
            None,
        )
        bot_first = next(
            (
                p for p in plays
                if p.get("about", {}).get("inning") == 1
                and p.get("about", {}).get("halfInning") == "bottom"
                and p.get("result", {}).get("type") == "atBat"
            ),
            None,
        )
        if top_first is not None:
            if out["home"]["starter_id"] in (None, ""):
                out["home"]["starter_id"] = top_first.get("matchup", {}).get("pitcher", {}).get("id")
            if not out["home"]["starter_hand"]:
                hand = top_first.get("matchup", {}).get("pitchHand", {}).get("code")
                out["home"]["starter_hand"] = str(hand or "").strip().upper()
        if bot_first is not None:
            if out["away"]["starter_id"] in (None, ""):
                out["away"]["starter_id"] = bot_first.get("matchup", {}).get("pitcher", {}).get("id")
            if not out["away"]["starter_hand"]:
                hand = bot_first.get("matchup", {}).get("pitchHand", {}).get("code")
                out["away"]["starter_hand"] = str(hand or "").strip().upper()

    for side in ["home", "away"]:
        out[side]["starter_id"] = (
            str(out[side]["starter_id"]) if out[side]["starter_id"] not in (None, "") else ""
        )
        out[side]["starter_hand"] = str(out[side]["starter_hand"] or "").strip().upper()
        if not out[side]["starter_hand"]:
            logger.debug("Missing starter hand for %s side in MLB%s", side, game_pk)
    return out


def _extract_starting_batters(
    feed: dict,
    *,
    game_pk: int,
    game_date: date,
    home_team: str,
    away_team: str,
) -> tuple[list[dict], dict[str, dict[str, int]]]:
    """Build starter-level batter game logs and a lineup-position lookup."""
    game_data = feed.get("gameData", {})
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    starter_ctx = _starter_context(feed, game_pk)
    season = int(game_date.year)

    raw_rows: list[dict] = []
    lineup_lookup: dict[str, dict[str, int]] = {"home": {}, "away": {}}

    for side, team_code in [("home", home_team), ("away", away_team)]:
        retro_team = _to_retrosheet_team(team_code, season)
        opp_side = "away" if side == "home" else "home"
        opp_hand = str(starter_ctx[opp_side]["starter_hand"] or "").strip().upper()
        side_box = boxscore.get(side, {})
        players = side_box.get("players", {})

        for player_key, player in players.items():
            batting_order = player.get("battingOrder")
            if batting_order in (None, ""):
                continue

            order_int = _to_int(batting_order)
            if order_int <= 0 or order_int % 100 != 0:
                continue

            lineup_pos = order_int // 100
            person = player.get("person", {})
            batter_id = str(person.get("id") or str(player_key).replace("ID", ""))
            if not batter_id:
                continue

            batting = player.get("stats", {}).get("batting", {})
            raw_rows.append(
                {
                    "id": batter_id,
                    "batter_id": batter_id,
                    "season": season,
                    "date": pd.Timestamp(game_date),
                    "gid": f"MLB{game_pk}",
                    "team": retro_team,
                    "b_lp": lineup_pos,
                    "bat_hand": _extract_bat_hand(game_data, batter_id),
                    "opp_starter_id": starter_ctx[opp_side]["starter_id"],
                    "opp_starter_hand": opp_hand,
                    "b_pa": _to_int(batting.get("plateAppearances")),
                    "b_h": _to_int(batting.get("hits")),
                    "b_k": _to_int(batting.get("strikeOuts")),
                    "b_w": _to_int(batting.get("baseOnBalls")),
                    "b_hbp": _to_int(batting.get("hitByPitch")),
                    "b_hr": _to_int(batting.get("homeRuns")),
                }
            )
            lineup_lookup[side][batter_id] = lineup_pos

    return raw_rows, lineup_lookup


def _extract_inning1_plays(
    feed: dict,
    *,
    game_pk: int,
    game_date: date,
    home_team: str,
    away_team: str,
    lineup_lookup: dict[str, dict[str, int]],
) -> list[dict]:
    """Convert inning-1 at-bats into a Retrosheet-like plays schema."""
    season = int(game_date.year)
    home_retro = _to_retrosheet_team(home_team, season)
    away_retro = _to_retrosheet_team(away_team, season)
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    rows: list[dict] = []
    for play in plays:
        about = play.get("about", {})
        if about.get("inning") != 1:
            continue

        result = play.get("result", {})
        if result.get("type") != "atBat":
            continue

        event_type = str(result.get("eventType") or "").strip().lower()
        if not event_type:
            continue

        matchup = play.get("matchup", {})
        batter = matchup.get("batter", {}) or {}
        pitcher = matchup.get("pitcher", {}) or {}
        batter_id = str(batter.get("id") or "")
        pitcher_id = str(pitcher.get("id") or "")
        if not batter_id or not pitcher_id:
            continue

        is_top = about.get("halfInning") == "top"
        batting_side = "away" if is_top else "home"
        batteam = away_retro if is_top else home_retro
        lp = lineup_lookup.get(batting_side, {}).get(batter_id)

        play_events = play.get("playEvents", [])
        in_play = any(
            bool((evt.get("details") or {}).get("isInPlay"))
            for evt in play_events
        )

        row = {
            "gid": f"MLB{game_pk}",
            "at_bat_index": _to_int(about.get("atBatIndex")),
            "inning": 1,
            "batter": batter_id,
            "pitcher": pitcher_id,
            "batteam": batteam,
            "ab": int(event_type not in NON_AB_EVENTS),
            "single": 0,
            "double": 0,
            "triple": 0,
            "hr": 0,
            "k": int(event_type in K_EVENTS or event_type.startswith("strikeout")),
            "sf": int(event_type in SF_EVENTS),
            "bip": int(in_play and event_type != "home_run"),
            "lp": lp,
            "date": pd.Timestamp(game_date),
            "season": season,
        }
        hit_col = HIT_EVENTS.get(event_type)
        if hit_col is not None:
            row[hit_col] = 1

        rows.append(row)

    return rows


def _compute_live_rolling_babip(
    inn1: pd.DataFrame,
    *,
    id_col: str,
    label: str,
) -> pd.DataFrame:
    """Live BABIP estimator for 2026 with a light Bayesian prior.

    Historical training keeps the strict Retrosheet threshold. Live scoring in
    April needs something usable earlier, so we emit a shrunk estimate once a
    player has at least a few 1st-inning opportunities and keep the cumulative
    PA count alongside it for explicit history flags downstream.
    """
    game_stats = inn1.groupby([id_col, "gid", "season", "date"]).agg(
        pa=("ab", "sum"),
        hits=("hit", "sum"),
        hr=("hr", "sum"),
        k=("k", "sum"),
        sf=("sf", "sum"),
    ).reset_index().sort_values([id_col, "date"])

    results: list[dict] = []
    for pid, grp in game_stats.groupby(id_col):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)
        if n < 2:
            continue

        pa_arr = grp["pa"].values.astype(float)
        h_arr = grp["hits"].values.astype(float)
        hr_arr = grp["hr"].values.astype(float)
        k_arr = grp["k"].values.astype(float)
        sf_arr = grp["sf"].values.astype(float)

        for i in range(1, n):
            cum_h = h_arr[:i].sum()
            cum_hr = hr_arr[:i].sum()
            cum_ab = pa_arr[:i].sum()
            cum_k = k_arr[:i].sum()
            cum_sf = sf_arr[:i].sum()
            cum_pa = cum_ab + cum_sf
            denom = cum_ab - cum_k - cum_hr + cum_sf

            if cum_pa < LIVE_BABIP_MIN_PA or denom <= 0:
                continue

            raw_babip = (cum_h - cum_hr) / denom
            shrunk_babip = (
                (cum_h - cum_hr) + (LIVE_BABIP_PRIOR * LIVE_BABIP_PRIOR_DENOM)
            ) / (denom + LIVE_BABIP_PRIOR_DENOM)

            results.append(
                {
                    "id": str(pid),
                    "gid": grp.iloc[i]["gid"],
                    "season": grp.iloc[i]["season"],
                    "date": grp.iloc[i]["date"],
                    "babip_inn1": shrunk_babip,
                    "babip_inn1_raw": raw_babip,
                    "babip_inn1_pa": cum_pa,
                    "babip_inn1_denom": denom,
                }
            )

    df = pd.DataFrame(results)
    if df.empty:
        logger.info("%s live 1st-inning BABIP: 0 rows, 0 unique %ss", label, label)
        return pd.DataFrame(
            columns=[
                "id",
                "gid",
                "season",
                "date",
                "babip_inn1",
                "babip_inn1_raw",
                "babip_inn1_pa",
                "babip_inn1_denom",
            ]
        )

    logger.info(
        "%s live 1st-inning BABIP: %d rows, %d unique %ss",
        label,
        len(df),
        df["id"].nunique(),
        label,
    )
    return df


def fetch_date_lineup_logs(dt: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch completed-game batter logs + inning-1 play logs for a single date."""
    games = fetch_schedule(dt)
    if not games:
        logger.info("No completed games on %s", dt)
        return pd.DataFrame(), pd.DataFrame()

    batter_rows: list[dict] = []
    inning1_rows: list[dict] = []

    for game in games:
        game_pk = game.get("gamePk")
        if not game_pk:
            continue

        home_team = _normalize_schedule_team(game, "home")
        away_team = _normalize_schedule_team(game, "away")

        try:
            feed = fetch_game_feed(int(game_pk))
            batters, lookup = _extract_starting_batters(
                feed,
                game_pk=int(game_pk),
                game_date=dt,
                home_team=home_team,
                away_team=away_team,
            )
            plays = _extract_inning1_plays(
                feed,
                game_pk=int(game_pk),
                game_date=dt,
                home_team=home_team,
                away_team=away_team,
                lineup_lookup=lookup,
            )
            batter_rows.extend(batters)
            inning1_rows.extend(plays)
            logger.info(
                "  %s @ %s (gPk=%s): %d starter batters, %d inning-1 AB rows",
                away_team,
                home_team,
                game_pk,
                len(batters),
                len(plays),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch lineup feed for gamePk=%s: %s", game_pk, exc)

    return pd.DataFrame(batter_rows), pd.DataFrame(inning1_rows)


def build_lineup_feature_tables(
    batter_logs: pd.DataFrame,
    inning1_plays: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Recompute all derived 2026 batter feature tables from raw live logs."""
    from src.retrosheet_batters import (  # noqa: PLC0415
        build_game_lineup_features,
        compute_entering_features,
    )

    if batter_logs.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    logs = batter_logs.copy()
    logs["date"] = pd.to_datetime(logs["date"]).dt.normalize()
    logs["batter_id"] = logs["batter_id"].astype(str)
    logs["id"] = logs["id"].astype(str)
    logs["opp_starter_id"] = logs["opp_starter_id"].astype(str)
    logs = logs.sort_values(["id", "date", "gid", "b_lp"]).reset_index(drop=True)

    entering = compute_entering_features(logs)
    if entering.empty:
        entering = pd.DataFrame(columns=EMPTY_ENTERING_COLUMNS)
        lineup = pd.DataFrame(columns=EMPTY_LINEUP_COLUMNS)
    else:
        lineup = build_game_lineup_features(entering, pd.DataFrame(), pd.DataFrame())
        if lineup.empty:
            lineup = pd.DataFrame(columns=EMPTY_LINEUP_COLUMNS)

    if inning1_plays.empty:
        return entering, lineup, pd.DataFrame(columns=EMPTY_BABIP_COLUMNS)

    inn1 = inning1_plays.copy()
    inn1["date"] = pd.to_datetime(inn1["date"]).dt.normalize()
    for col in ["batter", "pitcher", "gid", "batteam"]:
        inn1[col] = inn1[col].astype(str)
    inn1["hit"] = inn1["single"] + inn1["double"] + inn1["triple"] + inn1["hr"]

    pitcher_babip = _compute_live_rolling_babip(inn1, id_col="pitcher", label="pitcher")
    batter_babip = _compute_live_rolling_babip(inn1, id_col="batter", label="batter")

    starters_by_game = inn1.sort_values("date").groupby(["gid", "batteam"]).agg(
        starter_id=("pitcher", "first"),
    ).reset_index()

    if pitcher_babip.empty:
        pitcher_merge = pd.DataFrame(columns=["starter_id", "gid", "sp_babip_inn1", "sp_babip_inn1_pa"])
    else:
        pitcher_merge = pitcher_babip[["id", "gid", "babip_inn1", "babip_inn1_pa"]].rename(
            columns={
                "id": "starter_id",
                "babip_inn1": "sp_babip_inn1",
                "babip_inn1_pa": "sp_babip_inn1_pa",
            }
        )
    game_sp = starters_by_game.merge(pitcher_merge, on=["starter_id", "gid"], how="left")

    if batter_babip.empty:
        batter_merge = pd.DataFrame(columns=["batter", "gid", "b_babip_inn1", "b_babip_inn1_pa"])
    else:
        batter_merge = batter_babip[["id", "gid", "babip_inn1", "babip_inn1_pa"]].rename(
            columns={
                "id": "batter",
                "babip_inn1": "b_babip_inn1",
                "babip_inn1_pa": "b_babip_inn1_pa",
            }
        )
    inn1_with_babip = (
        inn1[["gid", "batter", "batteam", "lp", "date", "season"]]
        .drop_duplicates(subset=["gid", "batter"])
        .merge(batter_merge, on=["batter", "gid"], how="left")
    )

    top3 = inn1_with_babip[inn1_with_babip["lp"].isin([1, 2, 3])].copy()
    top3_agg = top3.groupby(["gid", "batteam", "date", "season"]).agg(
        top3_babip_inn1=("b_babip_inn1", "mean"),
        top3_babip_inn1_pa=("b_babip_inn1_pa", "mean"),
    ).reset_index()

    babip = top3_agg.merge(
        game_sp[["gid", "batteam", "sp_babip_inn1", "sp_babip_inn1_pa"]],
        on=["gid", "batteam"],
        how="left",
    ).rename(columns={"batteam": "team"})
    if babip.empty:
        babip = pd.DataFrame(columns=EMPTY_BABIP_COLUMNS)

    logger.info(
        "Live 2026 BABIP features: %d rows, sp=%d, top3=%d",
        len(babip),
        int(babip["sp_babip_inn1"].notna().sum()) if not babip.empty else 0,
        int(babip["top3_babip_inn1"].notna().sum()) if not babip.empty else 0,
    )
    return entering, lineup, babip


def run_lineup_fetch(dt: date) -> int:
    """Fetch one date of completed games, update raw stores, and rebuild features."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    new_batter_logs, new_inning1 = fetch_date_lineup_logs(dt)
    if new_batter_logs.empty and new_inning1.empty:
        logger.info("No live lineup rows added for %s", dt)
        return 0

    batter_logs = pd.concat([_load_existing(BATTER_LOGS_PATH), new_batter_logs], ignore_index=True, sort=False)
    batter_logs = _dedup(batter_logs, ["gid", "batter_id"])
    inning1_plays = pd.concat([_load_existing(INNING1_PLAYS_PATH), new_inning1], ignore_index=True, sort=False)
    inning1_plays = _dedup(inning1_plays, ["gid", "at_bat_index"])

    entering, lineup, babip = build_lineup_feature_tables(batter_logs, inning1_plays)

    _save_output(
        batter_logs,
        BATTER_LOGS_PATH,
        generator="mlb_lineups.run_lineup_fetch",
        audit_action="save_batter_game_logs_2026",
    )
    _save_output(
        inning1_plays,
        INNING1_PLAYS_PATH,
        generator="mlb_lineups.run_lineup_fetch",
        audit_action="save_inning1_play_logs_2026",
    )
    _save_output(
        entering,
        BATTER_ENTERING_PATH,
        generator="mlb_lineups.run_lineup_fetch",
        audit_action="save_batter_entering_2026",
    )
    _save_output(
        lineup,
        LINEUP_FEATURES_PATH,
        generator="mlb_lineups.run_lineup_fetch",
        audit_action="save_game_lineup_features_2026",
    )
    _save_output(
        babip,
        BABIP_FEATURES_PATH,
        generator="mlb_lineups.run_lineup_fetch",
        audit_action="save_first_inning_babip_2026",
    )

    state = _load_state()
    state["last_lineup_date"] = dt.isoformat()
    _save_state(state)
    append_audit(
        "run_lineup_fetch",
        target_date=dt,
        rows_added=len(new_batter_logs),
        rows_total=len(batter_logs),
        files_written=[
            BATTER_LOGS_PATH.name,
            INNING1_PLAYS_PATH.name,
            BATTER_ENTERING_PATH.name,
            LINEUP_FEATURES_PATH.name,
            BABIP_FEATURES_PATH.name,
        ],
        extra={
            "new_inning1_rows": int(len(new_inning1)),
            "lineup_feature_rows": int(len(lineup)),
            "babip_feature_rows": int(len(babip)),
        },
    )
    logger.info(
        "Saved live 2026 lineup data through %s: %d batter rows, %d inning-1 rows",
        dt,
        len(batter_logs),
        len(inning1_plays),
    )
    return int(len(new_batter_logs))


def run_lineup_backfill(start: date, end: date) -> int:
    """Backfill lineup / BABIP logs across a date range inclusive."""
    total = 0
    cur = start
    while cur <= end:
        logger.info("Lineup backfill %s", cur)
        total += run_lineup_fetch(cur)
        cur += timedelta(days=1)
    return total
