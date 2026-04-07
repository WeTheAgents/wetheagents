"""ESPN Scoreboard API client for MLB game data.

Fetches from the unofficial ESPN site API:
  - Pre-game: DraftKings odds (moneyline, run line, over/under) + probable starters
  - Post-game: inning-by-inning linescore + final scores

Important: odds disappear from the API once a game starts. Capture pre-game.

Endpoint:
  GET https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard
      ?dates=YYYYMMDD
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from .team_mapping import normalize_team

logger = logging.getLogger(__name__)

SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
)
RATE_LIMIT_SECONDS = 1.0
_last_request_time = 0.0


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class OddsRow:
    """Pre-game odds for one team in one game."""

    event_id: str
    game_date: date
    team_abbr: str  # our 3-letter code
    home_away: str  # "home" or "away"
    pitcher_name: str  # full name from ESPN probables, empty if TBD
    moneyline: float | None = None
    spread_line: float | None = None  # e.g. -1.5 or +1.5
    spread_odds: float | None = None  # American odds on the spread
    total_line: float | None = None  # e.g. 7.5
    total_odds: float | None = None  # over odds for home, under odds for away


@dataclass
class ResultRow:
    """Post-game result for one team in one game."""

    event_id: str
    game_date: date
    team_abbr: str
    home_away: str
    pitcher_name: str
    innings: list[int] = field(default_factory=list)  # runs per inning (1-9+)
    final: int = 0


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


def fetch_scoreboard(dt: date) -> dict:
    """Fetch ESPN MLB scoreboard for a single date. Returns raw JSON."""
    _rate_limit()
    params = {"dates": dt.strftime("%Y%m%d")}
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(SCOREBOARD_URL, params=params)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _get_probables(competition: dict) -> dict[str, str]:
    """Extract probable starters: {"home": full_name, "away": full_name}.

    Pitchers live inside each competitor's probables array, not at competition level.
    """
    mapping: dict[str, str] = {"away": "", "home": ""}
    for competitor in competition.get("competitors", []):
        side = competitor.get("homeAway", "")
        probables = competitor.get("probables", [])
        for prob in probables:
            if prob.get("name") == "probableStartingPitcher":
                athlete = prob.get("athlete", {})
                name = athlete.get("displayName") or athlete.get("fullName", "")
                mapping[side] = name
                break
    return mapping


def _parse_odds_value(val: str | float | int | None) -> float | None:
    """Parse ESPN odds value (may be string like '+109', '-131', 'o7.5')."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Strip o/u prefix for totals
    if s.startswith(("o", "u", "O", "U")):
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(date_str: str) -> date:
    """Parse ESPN date string like '2026-03-27T20:35Z' to date."""
    return date.fromisoformat(date_str[:10])


def parse_pregame_odds(
    data: dict, override_date: date | None = None
) -> list[OddsRow]:
    """Extract odds for all scheduled (pre-game) events.

    Args:
        data: Raw ESPN scoreboard JSON.
        override_date: If set, use this date instead of the UTC event date.
            Fixes late West Coast games that cross midnight UTC.

    Returns two OddsRow per game (one per team) — only for games with odds.
    """
    rows: list[OddsRow] = []

    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status_name = (
            competition.get("status", {}).get("type", {}).get("name", "")
        )

        # Only extract odds for scheduled games
        if status_name != "STATUS_SCHEDULED":
            continue

        odds_list = competition.get("odds", [])
        if not odds_list:
            continue

        odds = odds_list[0]  # DraftKings (sole provider)
        event_id = event.get("id", "")
        game_date = override_date or _parse_date(event.get("date", ""))
        probables = _get_probables(competition)

        # Extract structured odds
        ml = odds.get("moneyline", {})
        spread = odds.get("pointSpread", {})
        total = odds.get("total", {})

        for competitor in competition.get("competitors", []):
            side = competitor.get("homeAway", "")  # "home" or "away"
            espn_abbr = competitor.get("team", {}).get("abbreviation", "")

            try:
                team_code = normalize_team(espn_abbr)
            except KeyError:
                logger.warning("Unknown ESPN team %r, skipping", espn_abbr)
                continue

            # Moneyline
            ml_val = None
            ml_side = ml.get(side, {})
            if ml_side:
                ml_close = ml_side.get("close", {})
                ml_val = _parse_odds_value(ml_close.get("odds"))

            # Spread (run line)
            sp_line = None
            sp_odds = None
            sp_side = spread.get(side, {})
            if sp_side:
                sp_close = sp_side.get("close", {})
                sp_line = _parse_odds_value(sp_close.get("line"))
                sp_odds = _parse_odds_value(sp_close.get("odds"))

            # Total: over for home, under for away (convention for storing)
            tot_line = None
            tot_odds = None
            if side == "home":
                tot_over = total.get("over", {}).get("close", {})
                tot_line = _parse_odds_value(tot_over.get("line"))
                tot_odds = _parse_odds_value(tot_over.get("odds"))
            else:
                tot_under = total.get("under", {}).get("close", {})
                tot_line = _parse_odds_value(tot_under.get("line"))
                tot_odds = _parse_odds_value(tot_under.get("odds"))

            rows.append(
                OddsRow(
                    event_id=event_id,
                    game_date=game_date,
                    team_abbr=team_code,
                    home_away=side,
                    pitcher_name=probables.get(side, ""),
                    moneyline=ml_val,
                    spread_line=sp_line,
                    spread_odds=sp_odds,
                    total_line=tot_line,
                    total_odds=tot_odds,
                )
            )

    logger.info("Parsed %d pre-game odds rows", len(rows))
    return rows


@dataclass
class PitcherRow:
    """Probable starting pitcher for one team in one game."""

    event_id: str
    game_date: date
    team_abbr: str
    home_away: str
    pitcher_name: str


def parse_probable_pitchers(
    data: dict, override_date: date | None = None
) -> list[PitcherRow]:
    """Extract probable starters for all scheduled games.

    Returns two PitcherRow per game (one per team).
    """
    rows: list[PitcherRow] = []

    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status_name = (
            competition.get("status", {}).get("type", {}).get("name", "")
        )

        if status_name != "STATUS_SCHEDULED":
            continue

        event_id = event.get("id", "")
        game_date = override_date or _parse_date(event.get("date", ""))
        probables = _get_probables(competition)

        for competitor in competition.get("competitors", []):
            side = competitor.get("homeAway", "")
            espn_abbr = competitor.get("team", {}).get("abbreviation", "")

            try:
                team_code = normalize_team(espn_abbr)
            except KeyError:
                logger.warning("Unknown ESPN team %r, skipping", espn_abbr)
                continue

            name = probables.get(side, "")
            rows.append(
                PitcherRow(
                    event_id=event_id,
                    game_date=game_date,
                    team_abbr=team_code,
                    home_away=side,
                    pitcher_name=name,
                )
            )

    logger.info("Parsed %d probable pitcher rows", len(rows))
    return rows


def parse_postgame_results(
    data: dict, override_date: date | None = None
) -> list[ResultRow]:
    """Extract results for all completed games.

    Args:
        data: Raw ESPN scoreboard JSON.
        override_date: If set, use this instead of the UTC event date.

    Returns two ResultRow per game (one per team).
    """
    rows: list[ResultRow] = []

    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status_name = (
            competition.get("status", {}).get("type", {}).get("name", "")
        )

        if status_name != "STATUS_FINAL":
            continue

        event_id = event.get("id", "")
        game_date = override_date or _parse_date(event.get("date", ""))
        probables = _get_probables(competition)

        for competitor in competition.get("competitors", []):
            side = competitor.get("homeAway", "")
            espn_abbr = competitor.get("team", {}).get("abbreviation", "")

            try:
                team_code = normalize_team(espn_abbr)
            except KeyError:
                logger.warning("Unknown ESPN team %r, skipping", espn_abbr)
                continue

            # Linescore: list of {period, value, displayValue}
            linescores = competitor.get("linescores", [])
            innings = []
            for ls in linescores:
                val = ls.get("value", 0)
                innings.append(int(val) if val is not None else 0)

            # Pad to 9 innings or truncate
            while len(innings) < 9:
                innings.append(0)

            final_score = int(competitor.get("score", 0))

            rows.append(
                ResultRow(
                    event_id=event_id,
                    game_date=game_date,
                    team_abbr=team_code,
                    home_away=side,
                    pitcher_name=probables.get(side, ""),
                    innings=innings[:9],  # only first 9 for xlsx
                    final=final_score,
                )
            )

    logger.info("Parsed %d post-game result rows", len(rows))
    return rows
