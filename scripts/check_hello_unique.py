#!/usr/bin/env python3
"""Check if a Hello World submission is unique against the registry.

Usage:
    python check_hello_unique.py "print('Hello, World!')"
    python check_hello_unique.py --file submission.txt

Exit codes:
    0 — submission is unique
    1 — duplicate found
    2 — error (missing args, file not found, etc.)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "hello_world_registry.jsonl"


def normalize(text: str) -> str:
    """Normalize submission for comparison.

    Strips whitespace, lowercases, removes punctuation.
    Two submissions that normalize to the same string are duplicates.
    """
    text = text.strip().lower()
    # Remove all punctuation and extra whitespace
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def load_registry() -> list[str]:
    """Load all normalized submissions from the registry."""
    if not REGISTRY_PATH.exists():
        return []

    normalized: list[str] = []
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            normalized.append(normalize(record["submission"]))
        except (json.JSONDecodeError, KeyError):
            continue
    return normalized


def is_unique(submission: str) -> bool:
    """Check if a submission is unique against the registry."""
    normalized_submission = normalize(submission)
    if not normalized_submission:
        return False
    existing = load_registry()
    return normalized_submission not in existing


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: check_hello_unique.py <submission> | --file <path>", file=sys.stderr)
        return 2

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("Missing file path", file=sys.stderr)
            return 2
        path = Path(sys.argv[2])
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 2
        submission = path.read_text(encoding="utf-8")
    else:
        submission = " ".join(sys.argv[1:])

    if is_unique(submission):
        print(f"UNIQUE: '{submission[:80]}...' is not in the registry")
        return 0
    else:
        print(f"DUPLICATE: '{submission[:80]}...' already exists in the registry")
        return 1


if __name__ == "__main__":
    sys.exit(main())
