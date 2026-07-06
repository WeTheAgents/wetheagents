"""Generate legacy station config files from stations_canonical.json."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "data" / "static"
CANONICAL_PATH = STATIC_DIR / "stations_canonical.json"

ICAO_MAP_ORDER = [
    "nyc",
    "chicago",
    "miami",
    "los-angeles",
    "houston",
    "dallas",
    "denver",
    "seattle",
    "atlanta",
    "san-francisco",
    "austin",
    "dc",
    "phoenix",
    "hong-kong",
    "taipei",
    "tel-aviv",
    "london",
    "tokyo",
    "seoul",
    "singapore",
    "paris",
    "toronto",
    "sao-paulo",
    "buenos-aires",
    "shanghai",
    "beijing",
    "madrid",
    "warsaw",
    "mexico-city",
    "istanbul",
    "dubai",
    "moscow",
    "milan",
    "munich",
    "ankara",
    "wellington",
    "shenzhen",
    "chengdu",
    "chongqing",
    "wuhan",
    "lucknow",
    "jakarta",
    "kuala-lumpur",
    "amsterdam",
    "helsinki",
]

POLYMARKET_CITIES_ORDER = [
    "nyc",
    "chicago",
    "miami",
    "los-angeles",
    "houston",
    "dallas",
    "denver",
    "seattle",
    "atlanta",
    "san-francisco",
    "austin",
    "hong-kong",
    "taipei",
    "tel-aviv",
    "london",
    "tokyo",
    "seoul",
    "singapore",
    "paris",
    "toronto",
    "sao-paulo",
    "buenos-aires",
    "shanghai",
    "beijing",
    "madrid",
    "warsaw",
    "new-york-city",
    "dc",
    "phoenix",
    "mexico-city",
    "istanbul",
    "dubai",
    "moscow",
    "milan",
    "munich",
    "ankara",
    "wellington",
    "shenzhen",
    "chengdu",
    "chongqing",
    "wuhan",
    "lucknow",
    "jakarta",
    "kuala-lumpur",
    "amsterdam",
    "helsinki",
]

STATION_OUTPUT_SLOTS = [
    ("kalshi", "nyc"),
    ("resolution", "nyc"),
    ("kalshi", "chicago"),
    ("resolution", "chicago"),
    ("resolution", "miami"),
    ("resolution", "los-angeles"),
    ("resolution", "houston"),
    ("resolution", "dallas"),
    ("resolution", "denver"),
    ("resolution", "seattle"),
    ("resolution", "atlanta"),
    ("resolution", "san-francisco"),
    ("resolution", "austin"),
    ("resolution", "dc"),
    ("resolution", "phoenix"),
]

GENERATED_FILES = {
    "data/static/icao_map.json": "icao_map",
    "data/static/polymarket_cities.json": "polymarket_cities",
    "data/static/stations.json": "stations",
}


def load_canonical(path: Path = CANONICAL_PATH) -> dict[str, Any]:
    """Load canonical station config, preserving numeric spelling."""
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def build_icao_map(canonical: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the legacy slug -> primary/fallback ICAO mapping."""
    return {
        slug: {
            "primary": canonical[slug]["obs"]["primary_icao"],
            "fallback": list(canonical[slug]["obs"].get("fallback_icao", [])),
        }
        for slug in ICAO_MAP_ORDER
    }


def build_polymarket_cities(
    canonical: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the legacy Polymarket city registry, including the NYC alias."""
    cities = {}
    for slug in POLYMARKET_CITIES_ORDER:
        source_slug = "nyc" if slug == "new-york-city" else slug
        city = canonical[source_slug]
        cities[slug] = {
            "name": city["name"],
            "lat": city["lat"],
            "lon": city["lon"],
            "unit": city["unit"],
            "nbm": city["has_nbm"],
            "timezone": city["timezone"],
        }
    return cities


def build_stations(canonical: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the legacy US ICAO station registry."""
    stations: dict[str, dict[str, Any]] = {}
    for kind, slug in STATION_OUTPUT_SLOTS:
        city = canonical[slug]
        if kind == "kalshi":
            icao, station = _kalshi_station_entry(city)
        else:
            icao, station = _resolution_station_entry(slug, city)
        stations[icao] = station
    return stations


def generate_texts(canonical: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, str]:
    """Generate the three legacy config files as text without writing them."""
    if canonical is None:
        canonical = load_canonical()
    return {
        "data/static/icao_map.json": render_icao_map(build_icao_map(canonical)),
        "data/static/polymarket_cities.json": dumps_pretty(build_polymarket_cities(canonical)),
        "data/static/stations.json": dumps_pretty(build_stations(canonical)),
    }


def write_configs() -> None:
    """Rewrite legacy station config files from the canonical source."""
    for relative_path, text in generate_texts().items():
        (ROOT / relative_path).write_text(text, encoding="utf-8")


def render_icao_map(icao_map: Mapping[str, Mapping[str, Any]]) -> str:
    """Render icao_map.json in its compact aligned legacy style."""
    lines = ["{"]
    for index, slug in enumerate(ICAO_MAP_ORDER):
        entry = icao_map[slug]
        comma = "," if index < len(ICAO_MAP_ORDER) - 1 else ""
        padding = " " * (14 - len(slug))
        fallback = json.dumps(entry["fallback"], ensure_ascii=True)
        lines.append(
            f'  "{slug}":{padding}'
            f'{{"primary": "{entry["primary"]}", "fallback": {fallback}}}{comma}'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def dumps_pretty(value: Any) -> str:
    """Render JSON with 2-space indentation and preserved Decimal spellings."""
    return _format_json(value, level=0) + "\n"


def _resolution_station_entry(slug: str, city: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    us = city["us"]
    resolution = city.get("resolution")
    icao = resolution["station_id"] if resolution else city["obs"]["primary_icao"]
    kalshi_prefix = (
        us["kalshi_ticker_prefix"]
        if us.get("kalshi_resolution_icao") == icao
        else ""
    )
    wunderground_id = us.get("wunderground_id")
    if wunderground_id is None:
        wunderground_id = icao if resolution and resolution["source"] == "wunderground" else ""

    return icao, {
        "name": us["station_name"],
        "city": us["station_city"],
        "state": us["state"],
        "lat": us["station_lat"],
        "lon": us["station_lon"],
        "nws_office": us["nws_office"],
        "cli_time_utc": us["cli_time_utc"],
        "iem_network": us["iem_network"],
        "iem_station_id": us["iem_station_id"],
        "timezone": city["timezone"],
        "kalshi_ticker_prefix": kalshi_prefix,
        "polymarket_city_slug": us.get("polymarket_city_slug", slug),
        "wunderground_id": wunderground_id,
    }


def _kalshi_station_entry(city: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    us = city["us"]
    station = us["kalshi_station"]
    icao = us["kalshi_resolution_icao"]
    return icao, {
        "name": station["name"],
        "city": station["city"],
        "state": station["state"],
        "lat": station["lat"],
        "lon": station["lon"],
        "nws_office": station["nws_office"],
        "cli_time_utc": station["cli_time_utc"],
        "iem_network": station["iem_network"],
        "iem_station_id": station["iem_station_id"],
        "timezone": city["timezone"],
        "kalshi_ticker_prefix": us["kalshi_ticker_prefix"],
        "polymarket_city_slug": "",
        "wunderground_id": "",
    }


def _format_json(value: Any, *, level: int) -> str:
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        child_indent = " " * ((level + 1) * 2)
        close_indent = " " * (level * 2)
        lines = ["{"]
        items = list(value.items())
        for index, (key, item) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            rendered = _format_json(item, level=level + 1)
            lines.append(
                f"{child_indent}{json.dumps(str(key), ensure_ascii=True)}: {rendered}{comma}"
            )
        lines.append(f"{close_indent}}}")
        return "\n".join(lines)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return "[]"
        return "[" + ", ".join(_format_json(item, level=level) for item in value) + "]"

    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value, ensure_ascii=True)

    raise TypeError(f"Unsupported JSON value: {value!r}")


def main() -> None:
    write_configs()


if __name__ == "__main__":
    main()
