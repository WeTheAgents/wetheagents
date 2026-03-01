"""Config helpers for the `wea` CLI."""

from __future__ import annotations

import os
from pathlib import Path


def get_agent_from_env() -> str | None:
    value = os.environ.get("WEA_AGENT", "").strip()
    return value or None


def get_agent_from_file(path: Path | None = None) -> str | None:
    config_path = path or (Path.home() / ".wea_config")
    if not config_path.exists():
        return None
    raw = config_path.read_text(encoding="utf-8").strip()
    return raw or None


def resolve_agent(explicit: str | None = None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    return get_agent_from_env() or get_agent_from_file()
