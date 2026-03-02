#!/usr/bin/env python3
"""Validate idempotency keys against ledger/idem_keys.json.

Usage:
    python scripts/check_idem_keys.py <key1> [key2 ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def idem_key_hash(key: str) -> str:
    """Hash a raw idempotency key to match the format stored in idem_keys.json."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether provided idempotency keys already exist"
    )
    parser.add_argument(
        "idem_keys",
        nargs="+",
        help="One or more idempotency keys to validate",
    )
    return parser.parse_args()


def load_known_keys(ledger_path: Path) -> set[str]:
    """Load known idempotency keys.

    Missing file means no keys are recorded yet.
    """
    if not ledger_path.exists():
        return set()

    try:
        payload: Any = json.loads(ledger_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return set()

    if not isinstance(payload, dict):
        return set()

    keys = payload.get("keys")
    if not isinstance(keys, dict):
        return set()

    return {str(key) for key in keys.keys()}


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    idem_file = repo_root / "ledger" / "idem_keys.json"

    known_keys = load_known_keys(idem_file)
    duplicates = [key for key in args.idem_keys if idem_key_hash(key) in known_keys]

    if duplicates:
        for key in duplicates:
            print(f"DUPLICATE: idempotency key already exists: {key}")
        return 1

    print(f"OK: {len(args.idem_keys)} key(s) are new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
