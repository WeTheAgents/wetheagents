from __future__ import annotations

import json

from data.fetch_2026 import runtime_files


def test_state_path_bootstraps_from_example(tmp_path, monkeypatch) -> None:
    runtime_path = tmp_path / "state.json"
    example_path = tmp_path / "state.example.json"
    example_path.write_text(
        json.dumps({"last_postgame_date": "2026-04-19", "total_games": 123}, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_files, "STATE_PATH", runtime_path)
    monkeypatch.setattr(runtime_files, "STATE_EXAMPLE_PATH", example_path)

    resolved = runtime_files.state_path()

    assert resolved == runtime_path
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {
        "last_postgame_date": "2026-04-19",
        "total_games": 123,
    }


def test_pitcher_cache_path_bootstraps_empty_seed(tmp_path, monkeypatch) -> None:
    runtime_path = tmp_path / "pitcher_cache.json"
    example_path = tmp_path / "pitcher_cache.example.json"
    example_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(runtime_files, "PITCHER_CACHE_PATH", runtime_path)
    monkeypatch.setattr(runtime_files, "PITCHER_CACHE_EXAMPLE_PATH", example_path)

    resolved = runtime_files.pitcher_cache_path()

    assert resolved == runtime_path
    assert json.loads(runtime_path.read_text(encoding="utf-8")) == {}
