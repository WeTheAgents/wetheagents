import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "collect_all_cities.py"
SPEC = importlib.util.spec_from_file_location("weather_collect_all_cities", SCRIPT_PATH)
collector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(collector)


def test_load_cities_skips_aliases_by_default(monkeypatch, tmp_path):
    cities_path = tmp_path / "cities.json"
    cities_path.write_text(
        """
        {
          "nyc": {"name": "New York"},
          "new-york-city": {"name": "New York alias"},
          "tokyo": {"name": "Tokyo"}
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(collector, "CITIES_PATH", cities_path)

    assert list(collector.load_cities()) == ["nyc", "tokyo"]
    assert list(collector.load_cities(include_aliases=True)) == [
        "nyc",
        "new-york-city",
        "tokyo",
    ]


def test_find_history_gaps_is_limited_to_city_and_window():
    markets = pd.DataFrame(
        [
            {
                "city_slug": "tokyo",
                "market_date": date(2026, 6, 1),
                "bracket_index": 0,
            },
            {
                "city_slug": "tokyo",
                "market_date": date(2026, 6, 2),
                "bracket_index": 0,
            },
            {
                "city_slug": "london",
                "market_date": date(2026, 6, 2),
                "bracket_index": 0,
            },
            {
                "city_slug": "tokyo",
                "market_date": date(2026, 4, 1),
                "bracket_index": 0,
            },
        ]
    )
    history = pd.DataFrame(
        [
            {
                "city_slug": "tokyo",
                "market_date": date(2026, 6, 1),
                "bracket_index": 0,
            }
        ]
    )

    gaps = collector.find_history_gaps(
        markets,
        history,
        cities={"tokyo"},
        start=date(2026, 6, 1),
        end=date(2026, 6, 3),
    )

    assert len(gaps) == 1
    assert gaps.iloc[0]["city_slug"] == "tokyo"
    assert collector.normalize_date(gaps.iloc[0]["market_date"]) == date(2026, 6, 2)


def test_collect_city_markets_saves_only_requested_city(monkeypatch, tmp_path):
    markets_path = tmp_path / "markets.parquet"
    monkeypatch.setattr(collector, "MARKETS_PATH", markets_path)
    monkeypatch.setattr(collector, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collector, "RATE_LIMIT_GAMMA", 0)

    existing = pd.DataFrame(
        [
            {
                "city_slug": "london",
                "city_name": "London",
                "market_date": date(2026, 6, 1),
                "bracket_index": 0,
                "question": "London?",
                "yes_price": 0.2,
                "clob_token_id_yes": "london-token",
                "market_id": "london-market",
                "volume": 1,
            }
        ]
    )

    def fake_fetch(city_slug, target):
        assert city_slug == "tokyo"
        return [
            {
                "city_slug": city_slug,
                "city_name": "",
                "market_date": target,
                "bracket_index": 0,
                "question": "Tokyo?",
                "yes_price": 0.4,
                "clob_token_id_yes": "tokyo-token",
                "market_id": "tokyo-market",
                "volume": 2,
            }
        ]

    monkeypatch.setattr(collector, "fetch_event_brackets", fake_fetch)

    combined, report = collector.collect_city_markets(
        "tokyo",
        {"name": "Tokyo"},
        start=date(2026, 6, 1),
        end=date(2026, 6, 1),
        today=date(2026, 6, 1),
        existing_markets=existing,
        dry_run=False,
        deadline=None,
    )

    assert report["status"] == "OK"
    assert report["market_rows_added"] == 1
    assert set(combined["city_slug"]) == {"london", "tokyo"}

    saved = pd.read_parquet(markets_path)
    assert set(saved["city_slug"]) == {"london", "tokyo"}


def test_collect_city_history_reports_partial_when_limited(monkeypatch, tmp_path):
    history_path = tmp_path / "history.parquet"
    monkeypatch.setattr(collector, "HISTORY_PATH", history_path)
    monkeypatch.setattr(collector, "DATA_DIR", tmp_path)
    monkeypatch.setattr(collector, "RATE_LIMIT_CLOB", 0)

    markets = pd.DataFrame(
        [
            {
                "city_slug": "tokyo",
                "city_name": "Tokyo",
                "market_date": date(2026, 6, 1),
                "bracket_index": 0,
                "question": "Tokyo low?",
                "clob_token_id_yes": "tokyo-token-000",
            },
            {
                "city_slug": "tokyo",
                "city_name": "Tokyo",
                "market_date": date(2026, 6, 1),
                "bracket_index": 1,
                "question": "Tokyo high?",
                "clob_token_id_yes": "tokyo-token-111",
            },
        ]
    )

    def fake_fetch_price_history(token, interval):
        assert token == "tokyo-token-000"
        assert interval == "max"
        return [{"t": 1_781_000_000, "p": 0.44}]

    monkeypatch.setattr(collector, "fetch_price_history", fake_fetch_price_history)

    combined, report = collector.collect_city_history(
        "tokyo",
        start=date(2026, 6, 1),
        end=date(2026, 6, 1),
        markets=markets,
        existing_history=pd.DataFrame(),
        dry_run=False,
        backfill_all_history=False,
        deadline=None,
        max_brackets=1,
    )

    assert report["status"] == "PARTIAL"
    assert report["history_brackets"] == 2
    assert report["history_brackets_attempted"] == 1
    assert report["history_candles_added"] == 1
    assert len(combined) == 1

    saved = pd.read_parquet(history_path)
    assert len(saved) == 1
