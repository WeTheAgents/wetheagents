"""Station metadata registry for weather prediction markets.

Maps resolution stations to IEM archive identifiers for both Kalshi and Polymarket.
Key subtlety: IEM MOS uses 4-char ICAO (KNYC), observations use 3-char (NYC).

Polymarket resolves on different stations than Kalshi:
  - NYC: Polymarket → KLGA (LaGuardia), Kalshi → KNYC (Central Park)
  - Chicago: Polymarket → KORD (O'Hare), Kalshi → KMDW (Midway)
  - Miami: Both → KMIA

The Polymarket US station list is derived from stations_canonical.json so
resolution-station corrections flow through without another hardcoded list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "data" / "static"


@dataclass(frozen=True)
class Station:
    """Weather station used for temperature contract resolution."""

    icao: str  # 4-char ICAO code used by MOS (KNYC, KMDW, KMIA, KLGA, KORD)
    name: str  # Human-readable name
    city: str  # City name
    state: str  # 2-char state abbreviation
    lat: float  # Latitude (decimal degrees, north positive)
    lon: float  # Longitude (decimal degrees, west negative)
    nws_office: str  # NWS forecast office code (OKX, LOT, MFL)
    cli_time_utc: str  # When NWS CLI report is issued (UTC)
    iem_network: str  # IEM ASOS network for observations (NY_ASOS, IL_ASOS, FL_ASOS)
    iem_station_id: str  # 3-char IEM station ID for observations (NYC, MDW, MIA, LGA, ORD)
    timezone: str  # IANA timezone (America/New_York, America/Chicago)
    kalshi_ticker_prefix: str  # Kalshi contract ticker prefix (KXHIGHNY), empty if N/A
    polymarket_city_slug: str  # Polymarket event slug city component (nyc, chicago, miami)
    wunderground_id: str  # Weather Underground station ID for resolution (KLGA, KORD, KMIA)


def load_stations() -> dict[str, Station]:
    """Load station registry from static JSON.

    Returns:
        Dict mapping ICAO code to Station dataclass.
    """
    path = STATIC_DIR / "stations.json"
    with open(path) as f:
        raw = json.load(f)

    return {
        icao: Station(icao=icao, **data)
        for icao, data in raw.items()
    }


def load_station_canonical() -> dict:
    """Load canonical city/station metadata."""
    path = STATIC_DIR / "stations_canonical.json"
    with open(path) as f:
        return json.load(f)


def _load_polymarket_us_resolution_map() -> dict[str, str]:
    """Return slug -> resolution ICAO for traded US Polymarket cities."""
    canonical = load_station_canonical()
    mapping = {}
    missing = []
    for slug, city in canonical.items():
        if not city.get("traded_on_polymarket") or not city.get("has_nbm"):
            continue
        resolution = city.get("resolution") or {}
        station_id = resolution.get("station_id")
        if not station_id:
            missing.append(f"{slug}:<missing>")
            continue
        if station_id not in STATIONS:
            missing.append(f"{slug}:{station_id}")
            continue
        mapping[slug] = station_id
    if missing:
        raise KeyError(
            "Canonical Polymarket US station(s) missing from stations.json: "
            + ", ".join(missing)
        )
    return mapping


# Pre-loaded registry for quick access
STATIONS = load_stations()

# Convenience: map 3-char IEM station ID back to ICAO
IEM_TO_ICAO = {s.iem_station_id: s.icao for s in STATIONS.values()}

# Kalshi Phase 1 stations
PHASE1_STATIONS = ["KNYC", "KMDW", "KMIA"]

# Polymarket resolution stations
POLYMARKET_SLUG_TO_ICAO = _load_polymarket_us_resolution_map()
POLYMARKET_STATIONS = list(POLYMARKET_SLUG_TO_ICAO.values())

# Polymarket slug → ICAO lookup is canonical-driven and excludes non-traded
# config carryovers such as dc and phoenix.


def get_station(icao: str) -> Station:
    """Get station by ICAO code. Raises KeyError if not found."""
    return STATIONS[icao]
