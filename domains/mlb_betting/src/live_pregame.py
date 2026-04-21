"""Pregame overlay — bridge today's pregame JSON into the games frame.

The 2026 data pipeline writes to ``games_2026.parquet`` only via
``run_postgame()``, which fires AFTER games finish. That means on a given
morning the parquet does not yet contain today's matchups, even though
pregame odds + starters have already been scraped and live on disk at
``data/raw/odds_2026/pregame_YYYYMMDD_*.json``.

This module bridges that gap READ-ONLY: it returns a game-level DataFrame
in the exact same schema as ``pair_games()`` output, suitable for
concatenating to the result of ``load_all_seasons()`` before feature
building.

Design rules:
  * Never writes to the data pipeline. Parquet stays canonical (played games
    only).
  * Unplayed innings / final / home_win = 0. Strategies rely on odds +
    pitcher features, not scores.
  * Pitcher codes are resolved through ``PitcherCodeRegistry`` so they match
    the codes the feature builder has been tracking all season. Unknown
    pitchers degrade to empty string — ``apply_data_filters`` would drop
    those rows, which is the correct failure mode (we can't bet a game with
    no pitcher info anyway).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data.fetch_2026.runtime_files import pitcher_cache_path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PREGAME_DIR = BASE_DIR / "data" / "raw" / "odds_2026"


def _find_latest_pregame(target: date) -> Path | None:
    """Most-complete pregame snapshot for the date, or None.

    ESPN morning dumps can be published out of order: the newest file is not
    always the fullest file. For live overlays we prefer the snapshot with the
    largest number of team rows (equivalently, games), then break ties by
    filename so the latest timestamp wins among equally complete files.
    """
    stamp = target.strftime("%Y%m%d")
    files = sorted(PREGAME_DIR.glob(f"pregame_{stamp}_*.json"))
    if not files:
        return None

    best: tuple[int, str, Path] | None = None
    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read pregame snapshot %s: %s", path.name, exc)
            continue
        score = (len(rows), path.name, path)
        if best is None or score > best:
            best = score

    if best is None:
        return None

    chosen = best[2]
    if chosen != files[-1]:
        logger.info(
            "Pregame overlay: selected most-complete snapshot %s over newer %s",
            chosen.name,
            files[-1].name,
        )
    return chosen


def _load_pitcher_hand_cache() -> dict[str, str]:
    """Return {full_name → 'R' | 'L'} from the pitcher cache."""
    cache_path = pitcher_cache_path()
    if not cache_path.exists():
        return {}
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    return {
        name: info.get("hand", "R")
        for name, info in raw.items()
        if isinstance(info, dict)
    }


def _date_to_mmdd(d: date) -> int:
    return d.month * 100 + d.day


def _resolve_pitcher_code(
    full_name: str,
    hand_cache: dict[str, str],
    registry,
    fallback_hand: str = "",
) -> str:
    """Resolve a pitcher's full name to our LASTNAME-Hand code."""
    if not full_name:
        return ""
    hand = hand_cache.get(full_name) or fallback_hand or "R"  # default R if unknown
    return registry.get_code(full_name, hand)


def _load_local_pitcher_snapshot(target: date) -> dict[tuple[str, str, str], dict[str, str]]:
    """Load local probable-pitcher snapshot keyed by (event_id, team, home_away)."""
    path = PREGAME_DIR / f"pitchers_{target.strftime('%Y%m%d')}.json"
    if not path.exists():
        return {}

    rows = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (
            str(row.get("event_id", "")),
            str(row.get("team", "")),
            str(row.get("home_away", "")),
        )
        out[key] = {
            "pitcher_name": str(row.get("pitcher_name", "") or ""),
            "pitcher_code": str(row.get("pitcher_code", "") or ""),
            "hand": str(row.get("hand", "") or ""),
        }
    return out


def _fetch_runtime_pitcher_snapshot(
    target: date,
    hand_cache: dict[str, str],
    registry,
) -> dict[tuple[str, str, str], dict[str, str]]:
    """Best-effort ESPN fallback for missing local probable pitchers.

    Read-only: this does not persist any refreshed hand cache to disk.
    """
    try:
        from data.fetch_2026.espn_api import fetch_scoreboard, parse_probable_pitchers
        from data.fetch_2026.mlb_api import fetch_pitcher_hand, load_pitcher_cache
    except ImportError as exc:
        logger.warning("Runtime pitcher fallback unavailable: %s", exc)
        return {}

    try:
        scoreboard = fetch_scoreboard(target)
        pitcher_rows = parse_probable_pitchers(scoreboard, override_date=target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Runtime probable-pitcher fallback failed: %s", exc)
        return {}

    cache = load_pitcher_cache()
    cache.update({name: {"hand": hand} for name, hand in hand_cache.items()})

    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in pitcher_rows:
        name = str(row.pitcher_name or "")
        hand = fetch_pitcher_hand(name, cache) if name else ""
        code = registry.get_code(name, hand) if name else ""
        key = (str(row.event_id), str(row.team_abbr), str(row.home_away))
        out[key] = {
            "pitcher_name": name,
            "pitcher_code": code,
            "hand": hand,
        }
    return out


def load_pregame_overlay(
    target: date,
    *,
    season: int = 2026,
    allow_network_pitcher_fallback: bool = True,
) -> pd.DataFrame:
    """Return a game-level DataFrame for ``target`` from pregame JSON.

    Output schema matches ``pair_games()`` exactly — the caller can safely
    ``pd.concat`` this onto ``load_all_seasons()`` output.

    If no pregame file exists for the date, returns an empty DataFrame.
    """
    # Import lazily to avoid a circular dep with data_loader during module init.
    from data.fetch_2026.pitcher_codes import PitcherCodeRegistry  # noqa: PLC0415
    from src.data_loader import pair_games  # noqa: PLC0415

    path = _find_latest_pregame(target)
    if path is None:
        logger.info("No pregame JSON found for %s", target)
        return pd.DataFrame()

    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        return pd.DataFrame()

    logger.info("Pregame overlay source: %s (%d team-rows)", path.name, len(rows))

    hand_cache = _load_pitcher_hand_cache()
    registry = PitcherCodeRegistry()
    local_pitchers = _load_local_pitcher_snapshot(target)

    unresolved_keys = [
        (
            str(r.get("event_id", "")),
            str(r.get("team", "")),
            str(r.get("home_away", "")),
        )
        for r in rows
        if not str(r.get("pitcher") or "").strip()
        and not local_pitchers.get(
            (
                str(r.get("event_id", "")),
                str(r.get("team", "")),
                str(r.get("home_away", "")),
            ),
            {},
        ).get("pitcher_code")
    ]
    runtime_pitchers: dict[tuple[str, str, str], dict[str, str]] = {}
    if unresolved_keys and allow_network_pitcher_fallback:
        runtime_pitchers = _fetch_runtime_pitcher_snapshot(target, hand_cache, registry)

    mmdd = _date_to_mmdd(target)
    team_records = []
    unknown_pitchers: list[str] = []

    for r in rows:
        key = (
            str(r.get("event_id", "")),
            str(r.get("team", "")),
            str(r.get("home_away", "")),
        )
        local_fallback = local_pitchers.get(key, {})
        runtime_fallback = runtime_pitchers.get(key, {})

        pitcher_name = str(r.get("pitcher") or "").strip()
        if not pitcher_name:
            pitcher_name = (
                str(local_fallback.get("pitcher_name") or "").strip()
                or str(runtime_fallback.get("pitcher_name") or "").strip()
            )
        if pitcher_name and pitcher_name not in hand_cache:
            unknown_pitchers.append(pitcher_name)
        fallback_hand = (
            str(local_fallback.get("hand") or "").strip()
            or str(runtime_fallback.get("hand") or "").strip()
        )
        pitcher_code = _resolve_pitcher_code(
            pitcher_name,
            hand_cache,
            registry,
            fallback_hand=fallback_hand,
        )
        if not pitcher_code:
            pitcher_code = (
                str(local_fallback.get("pitcher_code") or "").strip()
                or str(runtime_fallback.get("pitcher_code") or "").strip()
            )

        ml = r.get("moneyline")
        rec = {
            "event_id": r.get("event_id"),
            "date_raw": mmdd,
            "month": target.month,
            "day": target.day,
            "date": pd.Timestamp(target),
            "season": season,
            "team": r.get("team"),
            "vh": "H" if r.get("home_away") == "home" else "V",
            "pitcher": pitcher_code,
            "open_ml": ml,
            "close_ml": ml,  # single pregame snapshot
            "run_line": r.get("spread_line"),
            "run_line_odds": r.get("spread_odds"),
            "open_ou": r.get("total_line"),
            "open_ou_odds": r.get("total_odds"),
            "close_ou": r.get("total_line"),
            "close_ou_odds": r.get("total_odds"),
            # Zero innings + zero final — game hasn't been played. 0 (not NaN)
            # is required so build_pitcher_start_log's dropna(runs_allowed)
            # keeps these rows, which is what lets rolling pitcher features
            # merge back onto the overlay. rolling windows use shift(1) so
            # the current 0-0 row doesn't pollute its own features; team-
            # rolling features look at games BEFORE the date so they are
            # unaffected on the overlay day itself.
            **{f"inn_{i}": 0 for i in range(1, 10)},
            "final": 0,
        }
        team_records.append(rec)

    if unknown_pitchers:
        logger.warning(
            "Unknown pitchers (pitcher code will be blank → row likely dropped by "
            "apply_data_filters): %s",
            sorted(set(unknown_pitchers)),
        )

    raw_df = pd.DataFrame(team_records)

    # pair_games expects visitor/home in alternating order per event.
    # Sort by (event_id, vh) so 'V' comes before 'H' for each pair.
    raw_df["_vh_sort"] = raw_df["vh"].map({"V": 0, "H": 1})
    raw_df = raw_df.sort_values(["event_id", "_vh_sort"]).drop(columns=["_vh_sort"])

    games = pair_games(raw_df)
    logger.info("Pregame overlay: %d games for %s", len(games), target)
    return games
