"""MLB Stats API client — used solely for pitcher handedness lookup.

ESPN's scoreboard API does not include throwing hand. We call MLB Stats API
to resolve it and cache results locally.

Endpoint:
  GET https://statsapi.mlb.com/api/v1/people/search?names={name}&sportId=1
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com"
CACHE_PATH = Path(__file__).parent / "pitcher_cache.json"
RATE_LIMIT_SECONDS = 1.0
_last_request_time = 0.0


def _rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def load_pitcher_cache() -> dict[str, dict]:
    """Load pitcher cache from disk. Returns {full_name: {hand, mlb_id}}."""
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_pitcher_cache(cache: dict[str, dict]) -> None:
    """Persist pitcher cache to disk (atomic write)."""
    from .io_safety import atomic_write_text

    atomic_write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), CACHE_PATH
    )


def fetch_pitcher_hand(name: str, cache: dict[str, dict]) -> str:
    """Look up a pitcher's throwing hand ('R' or 'L').

    Checks local cache first, then queries MLB Stats API.
    Updates cache in-place on successful lookup.

    Returns "R" or "L", or "R" as fallback if lookup fails.
    """
    if not name:
        return "R"

    if name in cache:
        return cache[name].get("hand", "R")

    _rate_limit()
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            # Try people search endpoint
            resp = client.get(
                f"{MLB_API_BASE}/api/v1/people/search",
                params={"names": name, "sportId": 1},
            )
            resp.raise_for_status()
            data = resp.json()

            people = data.get("people", [])
            if not people:
                # Fallback: search with last name only
                last_name = name.split()[-1] if name else name
                resp = client.get(
                    f"{MLB_API_BASE}/api/v1/people/search",
                    params={"names": last_name, "sportId": 1, "active": True},
                )
                resp.raise_for_status()
                data = resp.json()
                people = data.get("people", [])

            if people:
                person = people[0]
                hand = person.get("pitchHand", {}).get("code", "R")
                mlb_id = person.get("id")
                cache[name] = {"hand": hand, "mlb_id": mlb_id}
                logger.info("Pitcher %s → %s (ID %s)", name, hand, mlb_id)
                return hand

    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("MLB API lookup failed for %r: %s", name, e)

    # Fallback
    cache[name] = {"hand": "R", "mlb_id": None}
    return "R"
