"""City registry for Polymarket weather prediction markets.

Lightweight wrapper over polymarket_cities.json.  International cities
(nbm=False) use multi-model ensembles instead of NOAA NBM.

Separate from stations.py which is US-only with ICAO/IEM/NWS metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "data" / "static"


@dataclass(frozen=True)
class City:
    """Polymarket weather market city."""

    slug: str       # "tokyo", "london", "nyc"
    name: str       # "Tokyo", "London", "New York City"
    lat: float
    lon: float
    unit: str       # "C" or "F"
    nbm: bool       # True for US cities with NOAA NBM coverage
    timezone: str   # IANA timezone e.g. "Asia/Tokyo"


def load_cities() -> dict[str, City]:
    """Load all cities from polymarket_cities.json.

    Returns:
        Dict mapping slug to City dataclass.
    """
    path = STATIC_DIR / "polymarket_cities.json"
    with open(path) as f:
        raw = json.load(f)

    return {
        slug: City(slug=slug, **data)
        for slug, data in raw.items()
    }


# Pre-loaded registries
CITIES: dict[str, City] = load_cities()

INTERNATIONAL_CITIES: list[City] = [
    c for c in CITIES.values() if not c.nbm
]

US_CITIES: list[City] = [
    c for c in CITIES.values() if c.nbm
]


def get_city(slug: str) -> City:
    """Get city by Polymarket slug. Raises KeyError if not found."""
    return CITIES[slug]
