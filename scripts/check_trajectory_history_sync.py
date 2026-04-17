#!/usr/bin/env python3
"""Cross-validate trajectory_mints.json against trajectory_mint history events.

Checks both directions:
- JSON → history: every mint in trajectory_mints.json[mints] must have a
  matching trajectory_mint event in ledger/history/*.jsonl.
- history → JSON: every trajectory_mint event in history must have a
  matching entry in trajectory_mints.json[mints].

Matching key: (trajectory, slot) — uniquely identifies each mint.

Output: JSON to stdout with keys:
  status          — "PASS" or "FAIL"
  missing_from_history — list of {trajectory, slot} present in JSON but absent from history
  missing_from_json    — list of {trajectory, slot} present in history but absent from JSON

Exit code: 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract all JSON objects from a string, handling concatenated objects.

    Some history lines were written as two concatenated JSON objects with no
    separator (e.g. ``{"a":1}{"b":2}``).  The stdlib json module rejects these;
    raw_decode processes them one at a time.
    """
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        # Skip whitespace between objects
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
            results.append(obj)
            pos = end
        except json.JSONDecodeError:
            break
    return results


def load_history_mints(history_dir: Path) -> set[tuple[str, int]]:
    """Return a set of (trajectory, slot) tuples from all trajectory_mint events."""
    keys: set[tuple[str, int]] = set()
    if not history_dir.is_dir():
        return keys
    for path in sorted(history_dir.glob("*.jsonl")):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            for event in _iter_json_objects(raw_line):
                if event.get("type") == "trajectory_mint":
                    traj = event.get("trajectory")
                    slot = event.get("slot")
                    if isinstance(traj, str) and isinstance(slot, int):
                        keys.add((traj, slot))
    return keys


def load_json_mints(mints_path: Path) -> list[dict[str, Any]]:
    """Return the mints list from trajectory_mints.json."""
    data = load_json(mints_path, default={"mints": []}, encoding="utf-8-sig")
    return data.get("mints", [])


def extract_json_keys(mints: list[dict[str, Any]]) -> set[tuple[str, int]]:
    """Extract (trajectory, slot) keys from the mints list."""
    keys: set[tuple[str, int]] = set()
    for mint in mints:
        traj = mint.get("trajectory")
        slot = mint.get("slot")
        if isinstance(traj, str) and isinstance(slot, int):
            keys.add((traj, slot))
    return keys


def run_check(root: Path) -> dict[str, Any]:
    """Cross-validate trajectory_mints.json against history events.

    Returns a result dict with keys: status, missing_from_history, missing_from_json.
    """
    mints_path = root / "ledger" / "trajectory_mints.json"
    history_dir = root / "ledger" / "history"

    json_mints = load_json_mints(mints_path)
    json_keys = extract_json_keys(json_mints)
    history_keys = load_history_mints(history_dir)

    missing_from_history = sorted(
        json_keys - history_keys, key=lambda t: (t[0], t[1])
    )
    missing_from_json = sorted(
        history_keys - json_keys, key=lambda t: (t[0], t[1])
    )

    status = "PASS" if not missing_from_history and not missing_from_json else "FAIL"
    return {
        "status": status,
        "missing_from_history": [
            {"trajectory": t, "slot": s} for t, s in missing_from_history
        ],
        "missing_from_json": [
            {"trajectory": t, "slot": s} for t, s in missing_from_json
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-validate trajectory_mints.json against history events"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    root = _repo_root_from(args.root)
    result = run_check(root)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
