import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_GEN_SPEC = importlib.util.spec_from_file_location(
    "weather_gen_station_configs",
    ROOT / "scripts" / "gen_station_configs.py",
)
gen_station_configs = importlib.util.module_from_spec(_GEN_SPEC)
assert _GEN_SPEC.loader is not None
_GEN_SPEC.loader.exec_module(gen_station_configs)

_STATIONS_SPEC = importlib.util.spec_from_file_location(
    "weather_stations",
    ROOT / "src" / "stations.py",
)
stations_module = importlib.util.module_from_spec(_STATIONS_SPEC)
assert _STATIONS_SPEC.loader is not None
sys.modules["weather_stations"] = stations_module
_STATIONS_SPEC.loader.exec_module(stations_module)


def test_generator_reproduces_committed_legacy_files():
    generated = gen_station_configs.generate_texts()
    for relative_path, text in generated.items():
        assert (ROOT / relative_path).read_text(encoding="utf-8") == text


def test_traded_cities_have_required_resolution_metadata():
    canonical = gen_station_configs.load_canonical()
    for slug, city in canonical.items():
        if not city["traded_on_polymarket"]:
            assert city["resolution"] is None, slug
            continue
        assert city["resolution"]["source"], slug
        assert city["resolution"]["station_id"], slug
        assert city["resolution"]["url"], slug
        assert city["lat"] is not None, slug
        assert city["lon"] is not None, slug
        assert city["timezone"], slug
        assert city["unit"] in {"F", "C"}, slug


def test_us_primary_icaos_and_polymarket_icaos_exist_in_stations_json():
    canonical = gen_station_configs.load_canonical()
    generated_icao_map = gen_station_configs.build_icao_map(canonical)
    generated_stations = gen_station_configs.build_stations(canonical)

    for slug, entry in generated_icao_map.items():
        if canonical[slug]["has_nbm"]:
            assert entry["primary"] in generated_stations, slug

    for icao in stations_module.POLYMARKET_STATIONS:
        assert icao in generated_stations
    for icao in stations_module.POLYMARKET_SLUG_TO_ICAO.values():
        assert icao in generated_stations


def test_polymarket_us_stations_derive_from_canonical_resolution_icaos():
    canonical = gen_station_configs.load_canonical()
    expected = {
        slug: city["resolution"]["station_id"]
        for slug, city in canonical.items()
        if city["traded_on_polymarket"] and city["has_nbm"]
    }

    assert expected == stations_module.POLYMARKET_SLUG_TO_ICAO
    assert list(expected.values()) == stations_module.POLYMARKET_STATIONS
    assert expected["houston"] == "KHOU"
    assert expected["dallas"] == "KDAL"
    assert expected["denver"] == "KBKF"
    assert "dc" not in expected
    assert "phoenix" not in expected


def test_resolution_source_corrections_and_taipei_cwa_are_canonical():
    canonical = gen_station_configs.load_canonical()

    assert canonical["moscow"]["resolution"]["source"] == "noaa_weather_gov"
    assert canonical["moscow"]["resolution"]["station_id"] == "UUWW"
    assert canonical["istanbul"]["resolution"]["source"] == "noaa_weather_gov"
    assert canonical["tel-aviv"]["resolution"]["source"] == "wunderground"

    taipei = canonical["taipei"]
    assert taipei["resolution"]["source"] == "cwa_taiwan"
    assert taipei["resolution"]["station_id"] == "46692"
    assert taipei["obs"]["primary_icao"] == "RCTP"
    assert "wunderground.com" not in taipei["resolution"]["url"]


def test_polymarket_city_alias_is_generated_from_nyc():
    canonical = gen_station_configs.load_canonical()
    cities = gen_station_configs.build_polymarket_cities(canonical)
    assert cities["new-york-city"] == cities["nyc"]
