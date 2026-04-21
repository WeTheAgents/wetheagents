#!/usr/bin/env python3
"""Report history-backed idem keys recorded in ledger/idem_keys.json but absent from history."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

RESERVED_TOP_LEVEL_KEYS = frozenset({"keys", "version"})
HISTORY_BACKED_OPERATIONS = frozenset(
    {"accept", "payment", "escrow", "escrow_return", "trajectory_mint", "escrow_create"}
)
HISTORY_BACKED_PREFIXES = (
    "accept|",
    "payment|",
    "escrow|",
    "escrow_return|",
    "trajectory_mint|",
    "escrow_create_",
    "escrow-create-",
    "escrow-return-",
    "escrow_return_",
)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: failed to parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except OSError as exc:
        print(f"ERROR: failed to read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if not isinstance(payload, dict):
        return {}

    return payload


def load_aliases(path: Path) -> dict[str, str]:
    """Load old-agent -> canonical-agent aliases."""
    payload = _load_json_object(path)
    return {str(key): str(value) for key, value in payload.items()}


def load_idem_entries(path: Path) -> dict[str, Any]:
    """Load every recorded idem entry from top-level entries and payload['keys']."""
    payload = _load_json_object(path)

    entries: dict[str, Any] = {}
    nested = payload.get("keys")
    if isinstance(nested, dict):
        entries.update({str(key): value for key, value in nested.items()})

    for raw_key, value in payload.items():
        if raw_key in RESERVED_TOP_LEVEL_KEYS:
            continue
        entries.setdefault(str(raw_key), value)

    return entries


def load_idem_keys(path: Path) -> set[str]:
    """Load every recorded idem key name, regardless of whether it is history-backed."""
    return set(load_idem_entries(path))


def is_history_backed_idem_key(raw_key: str, value: Any) -> bool:
    """Return True when an idem entry is expected to appear in ledger/history."""
    if isinstance(value, dict):
        for field in ("op", "action", "event", "type"):
            operation = value.get(field)
            if isinstance(operation, str) and operation in HISTORY_BACKED_OPERATIONS:
                return True

    return raw_key.startswith(HISTORY_BACKED_PREFIXES)


def select_history_backed_idem_keys(entries: dict[str, Any]) -> set[str]:
    """Keep only idem keys that correspond to history-backed ledger events."""
    return {
        raw_key
        for raw_key, value in entries.items()
        if is_history_backed_idem_key(raw_key, value)
    }


def canonicalize_idem_key(raw_key: str, aliases: dict[str, str]) -> str:
    """Normalize agent segments inside supported idem-key formats."""
    parts = raw_key.split("|")
    if not parts:
        return raw_key

    prefix = parts[0]
    if prefix in {"accept", "payment", "escrow", "escrow_return"} and len(parts) >= 3:
        parts[2] = aliases.get(parts[2], parts[2])
        return "|".join(parts)

    if prefix == "trajectory_mint" and len(parts) >= 4:
        parts[3] = aliases.get(parts[3], parts[3])
        return "|".join(parts)

    return raw_key


def load_history_idem_keys(history_dir: Path) -> set[str]:
    """Collect every literal idem_key value present in ledger/history/*.jsonl."""
    history_keys: set[str] = set()
    if not history_dir.is_dir():
        return history_keys

    for history_file in sorted(history_dir.glob("*.jsonl")):
        try:
            text = history_file.read_text(encoding="utf-8")
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
                history_keys.add(idem_key)

    return history_keys


def build_history_key_evidence(
    history_keys: set[str],
    aliases: dict[str, str] | None = None,
) -> set[str]:
    """Expand raw history idem keys with hashed variants used by legacy storage."""
    aliases = aliases or {}
    canonical_keys = {canonicalize_idem_key(idem_key, aliases) for idem_key in history_keys}
    evidence = set(canonical_keys)
    evidence.update(
        hashlib.sha256(idem_key.encode("utf-8")).hexdigest()
        for idem_key in canonical_keys
    )
    return evidence


def find_orphan_idem_keys(
    recorded_keys: set[str],
    history_key_evidence: set[str],
    aliases: dict[str, str] | None = None,
) -> list[str]:
    """Return sorted idem keys that were recorded but never written to history."""
    aliases = aliases or {}
    return sorted(
        raw_key
        for raw_key in recorded_keys
        if canonicalize_idem_key(raw_key, aliases) not in history_key_evidence
    )


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    aliases = load_aliases(root / "ledger" / "agent_aliases.json")
    entries = load_idem_entries(root / "ledger" / "idem_keys.json")
    all_recorded_keys = set(entries)
    checked_keys = select_history_backed_idem_keys(entries)
    history_keys = load_history_idem_keys(root / "ledger" / "history")
    history_key_evidence = build_history_key_evidence(history_keys, aliases)
    orphan_keys = find_orphan_idem_keys(checked_keys, history_key_evidence, aliases)

    report = {
        "status": "FAIL" if orphan_keys else "PASS",
        "summary": (
            f"{len(orphan_keys)} orphan idem key(s) found"
            if orphan_keys
            else "no orphan idem keys found"
        ),
        "recorded_idem_keys": len(all_recorded_keys),
        "checked_idem_keys": len(checked_keys),
        "history_idem_keys": len(history_keys),
        "orphan_keys": orphan_keys,
    }
    return report, 1 if orphan_keys else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find history-backed idem keys recorded in idem_keys.json but missing from history."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from script location)",
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
