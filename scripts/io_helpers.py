"""Shared I/O helpers for WeTheAgents scripts.

Provides consistent JSON loading/saving and timestamp formatting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path, *, default: Any = None, encoding: str = "utf-8") -> Any:
    """Load JSON from *path*.

    If *default* is not None and the file does not exist, return *default*.
    If *default* is None and the file does not exist, raise FileNotFoundError.
    """
    if default is not None and not path.exists():
        return default
    return json.loads(path.read_text(encoding=encoding))


def save_json(path: Path, data: Any, *, encoding: str = "utf-8") -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding=encoding
    )


def now_iso() -> str:
    """Return current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
