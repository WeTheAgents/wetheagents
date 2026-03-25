"""Station metadata registry for weather prediction markets.

Maps resolution stations to IEM archive identifiers for both Kalshi and Polymarket.
Key subtlety: IEM MOS uses 4-char ICAO (KNYC), observations use 3-char (NYC).

Polymarket resolves on different stations than Kalshi:
  - NYC: Polymarket → KLGA (LaGuardia), Kalshi → KNYC (Central Park)
  - Chicago: Polymarket → KORD (O'Hare), Kalshi → KMDW (Midway)
  - Miami: Both → KMIA
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


# Pre-loaded registry for quick access
STATIONS = load_stations()

# Convenience: map 3-char IEM station ID back to ICAO
IEM_TO_ICAO = {s.iem_station_id: s.icao for s in STATIONS.values()}

# Kalshi Phase 1 stations
PHASE1_STATIONS = ["KNYC", "KMDW", "KMIA"]

# Polymarket resolution stations
POLYMARKET_STATIONS = ["KLGA", "KORD", "KMIA"]

# Polymarket slug → ICAO lookup
POLYMARKET_SLUG_TO_ICAO = {
    s.polymarket_city_slug: s.icao
    for s in STATIONS.values()
    if s.polymarket_city_slug
}


def get_station(icao: str) -> Station:
    """Get station by ICAO code. Raises KeyError if not found."""
    return STATIONS[icao]
