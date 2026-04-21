"""Paths and bootstrap helpers for local runtime files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent

STATE_EXAMPLE_PATH = RUNTIME_DIR / "state.example.json"
STATE_PATH = RUNTIME_DIR / "state.json"

PITCHER_CACHE_EXAMPLE_PATH = RUNTIME_DIR / "pitcher_cache.example.json"
PITCHER_CACHE_PATH = RUNTIME_DIR / "pitcher_cache.json"


def _ensure_json_runtime_file(
    runtime_path: Path,
    example_path: Path,
    default_payload: dict[str, Any],
) -> Path:
    if runtime_path.exists():
        return runtime_path

    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    payload = default_payload
    if example_path.exists():
        try:
            payload = json.loads(example_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = default_payload

    runtime_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return runtime_path


def state_path() -> Path:
    return _ensure_json_runtime_file(
        STATE_PATH,
        STATE_EXAMPLE_PATH,
        {
            "last_pregame_date": None,
            "last_pregame_rows": 0,
            "last_postgame_date": None,
            "total_games": 0,
            "last_pitchers_date": None,
            "last_boxscore_date": None,
            "total_pitcher_lines": 0,
            "last_lineup_date": None,
            "last_savant_date": None,
            "last_savant_refresh_date": None,
            "last_savant_data_date": None,
        },
    )


def pitcher_cache_path() -> Path:
    return _ensure_json_runtime_file(
        PITCHER_CACHE_PATH,
        PITCHER_CACHE_EXAMPLE_PATH,
        {},
    )
