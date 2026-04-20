#!/usr/bin/env python3
"""Detect operation types that mix pipe and underscore idem-key formats."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PIPE_FORMAT = "pipe"
UNDERSCORE_FORMAT = "underscore"
EXAMPLE_LIMIT = 3
_DYNAMIC_SEGMENT_RE = re.compile(r"^\d+$|^[Tt]\d+(?:s\d+)?$")


def load_registered_idem_keys(path: Path) -> list[str]:
    """Load raw idem-key names from ledger/idem_keys.json."""
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(payload, dict):
        return []

    keys: list[str] = []
    nested = payload.get("keys")
    if isinstance(nested, dict):
        keys.extend(str(raw_key) for raw_key in nested)

    for raw_key in payload:
        if raw_key in {"keys", "version"}:
            continue
        keys.append(str(raw_key))

    return keys


def load_history_idem_keys(history_dir: Path) -> list[str]:
    """Load explicit idem_key values from ledger/history/*.jsonl."""
    keys: list[str] = []
    if not history_dir.is_dir():
        return keys

    for path in sorted(history_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            idem_key = payload.get("idem_key")
            if isinstance(idem_key, str) and idem_key:
                keys.append(idem_key)

    return keys


def collect_idem_keys(root: Path) -> list[str]:
    """Collect idem-key strings from history and idem_keys.json."""
    history_keys = load_history_idem_keys(root / "ledger" / "history")
    registered_keys = load_registered_idem_keys(root / "ledger" / "idem_keys.json")
    return history_keys + registered_keys


def _looks_like_dynamic_segment(segment: str) -> bool:
    if not segment:
        return False
    if _DYNAMIC_SEGMENT_RE.fullmatch(segment):
        return True
    return "@" in segment


def classify_idem_key(raw_key: str) -> tuple[str | None, str | None]:
    """Return (type_prefix, format) for pipe/underscore idem keys."""
    if not raw_key:
        return None, None

    if "|" in raw_key:
        return raw_key.split("|", 1)[0], PIPE_FORMAT

    if "_" not in raw_key:
        return None, None

    parts = raw_key.split("_")
    for index in range(1, len(parts)):
        if _looks_like_dynamic_segment(parts[index]):
            prefix = "_".join(parts[:index])
            return (prefix, UNDERSCORE_FORMAT) if prefix else (None, None)

    return None, None


def _is_hex_hash(raw_key: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", raw_key))


def build_format_report(raw_keys: list[str]) -> dict[str, Any]:
    """Build a uniformity report from raw idem-key strings."""
    unique_keys = sorted(set(raw_keys))
    distributions: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    unclassified: list[str] = []

    for raw_key in sorted(raw_keys):
        type_prefix, key_format = classify_idem_key(raw_key)
        if type_prefix is None or key_format is None:
            unclassified.append(raw_key)
            continue

        distributions[type_prefix][key_format] += 1
        if (
            raw_key not in examples[type_prefix][key_format]
            and len(examples[type_prefix][key_format]) < EXAMPLE_LIMIT
        ):
            examples[type_prefix][key_format].append(raw_key)

    type_distributions: list[dict[str, Any]] = []
    mixed_types: list[dict[str, Any]] = []

    for type_prefix in sorted(distributions):
        pipe_count = distributions[type_prefix][PIPE_FORMAT]
        underscore_count = distributions[type_prefix][UNDERSCORE_FORMAT]
        entry = {
            "type": type_prefix,
            PIPE_FORMAT: pipe_count,
            UNDERSCORE_FORMAT: underscore_count,
            "mixed": bool(pipe_count and underscore_count),
            "examples": {
                PIPE_FORMAT: examples[type_prefix].get(PIPE_FORMAT, []),
                UNDERSCORE_FORMAT: examples[type_prefix].get(UNDERSCORE_FORMAT, []),
            },
        }
        type_distributions.append(entry)
        if entry["mixed"]:
            mixed_types.append(entry)

    status = "FAIL" if mixed_types else "PASS"
    unique_unclassified = sorted(
        set(unclassified),
        key=lambda raw_key: (_is_hex_hash(raw_key), raw_key),
    )
    return {
        "status": status,
        "summary": {
            "observations_checked": len(raw_keys),
            "unique_keys_checked": len(unique_keys),
            "classified_observations": sum(
                item[PIPE_FORMAT] + item[UNDERSCORE_FORMAT]
                for item in type_distributions
            ),
            "unclassified_observations": len(unclassified),
            "unclassified_unique_keys": len(unique_unclassified),
            "types_checked": len(type_distributions),
            "mixed_types": len(mixed_types),
        },
        "type_distributions": type_distributions,
        "mixed_types": mixed_types,
        "unclassified_examples": unique_unclassified[:EXAMPLE_LIMIT],
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    report = build_format_report(collect_idem_keys(root))
    return report, 1 if report["status"] == "FAIL" else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect idem-key types that mix pipe and underscore formats."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root.resolve())
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
