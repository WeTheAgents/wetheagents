#!/usr/bin/env python3
"""Detect recorded idem keys whose namespace is not recognized."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RESERVED_TOP_LEVEL_KEYS = frozenset({"keys", "version"})
SHA256_NAMESPACE = "sha256_hash"
EXAMPLE_LIMIT = 3

RECOGNIZED_NAMESPACES = frozenset(
    {
        "accept",
        "claim",
        "cleanup",
        "create_task",
        "escrow",
        "escrow-cancel",
        "escrow-create",
        "escrow-return-cycle",
        "escrow_create",
        "escrow_return",
        "hello_world",
        "join",
        "payment",
        "register",
        "reject",
        "settle",
        SHA256_NAMESPACE,
        "trajectory_mint",
        "verify",
    }
)
SUPPORTED_BARE_NAMESPACES = frozenset({"cleanup", "create_task", "hello_world", "join"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DYNAMIC_SEGMENT_RE = re.compile(r"^\d+$|^[Tt]\d+(?:s\d+)?$|^slot\d+$|^cycle\d+$")
_DASHED_NAMESPACE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("escrow-create", re.compile(r"^escrow-create-\d+$")),
    ("escrow-cancel", re.compile(r"^escrow-cancel-\d+$")),
    ("escrow-return-cycle", re.compile(r"^escrow-return-cycle\d+-\d+$")),
)


def load_recorded_idem_keys(path: Path) -> list[str]:
    """Load raw idem key names from nested and top-level idem stores."""
    if not path.exists():
        raise FileNotFoundError(f"idem_keys.json not found at {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("idem_keys.json must contain a top-level JSON object")

    keys: list[str] = []
    nested = payload.get("keys")
    if nested is not None and not isinstance(nested, dict):
        raise ValueError("idem_keys.json field 'keys' must be an object when present")

    if isinstance(nested, dict):
        keys.extend(str(raw_key) for raw_key in nested)

    for raw_key in payload:
        if raw_key in RESERVED_TOP_LEVEL_KEYS:
            continue
        keys.append(str(raw_key))

    return keys


def _looks_like_dynamic_segment(segment: str) -> bool:
    return bool(segment) and (
        bool(_DYNAMIC_SEGMENT_RE.fullmatch(segment)) or "@" in segment
    )


def extract_namespace(raw_key: str) -> str | None:
    """Extract the namespace/prefix portion of a raw idem key."""
    if not raw_key:
        return None

    if _SHA256_RE.fullmatch(raw_key):
        return SHA256_NAMESPACE

    if "|" in raw_key:
        prefix = raw_key.split("|", 1)[0]
        return prefix or None

    for namespace, pattern in _DASHED_NAMESPACE_PATTERNS:
        if pattern.fullmatch(raw_key):
            return namespace

    if raw_key in SUPPORTED_BARE_NAMESPACES:
        return raw_key

    if "_" not in raw_key:
        return None

    parts = raw_key.split("_")
    for index in range(1, len(parts)):
        if _looks_like_dynamic_segment(parts[index]):
            prefix = "_".join(parts[:index])
            return prefix or None

    return None


def build_namespace_report(
    raw_keys: list[str],
    recognized_namespaces: frozenset[str] = RECOGNIZED_NAMESPACES,
) -> dict[str, Any]:
    """Build a report describing used and unrecognized idem namespaces."""
    unique_keys = sorted(set(raw_keys))
    namespace_counts: Counter[str | None] = Counter()
    examples: dict[str | None, list[str]] = defaultdict(list)

    for raw_key in sorted(raw_keys):
        namespace = extract_namespace(raw_key)
        namespace_counts[namespace] += 1
        if raw_key not in examples[namespace] and len(examples[namespace]) < EXAMPLE_LIMIT:
            examples[namespace].append(raw_key)

    used_namespaces = sorted(
        namespace
        for namespace in namespace_counts
        if namespace is not None and namespace in recognized_namespaces
    )
    unused_known_namespaces = sorted(recognized_namespaces - set(used_namespaces))

    namespace_buckets = [
        {
            "namespace": namespace,
            "count": namespace_counts[namespace],
            "recognized": namespace in recognized_namespaces if namespace is not None else False,
        }
        for namespace in sorted(
            namespace_counts,
            key=lambda item: (item is None, item or ""),
        )
    ]

    unrecognized_namespaces = [
        {
            "namespace": namespace,
            "count": namespace_counts[namespace],
            "examples": examples[namespace],
        }
        for namespace in sorted(
            namespace_counts,
            key=lambda item: (item is None, item or ""),
        )
        if namespace is None or namespace not in recognized_namespaces
    ]

    status = "FAIL" if unrecognized_namespaces else "PASS"
    return {
        "status": status,
        "summary": {
            "observations_checked": len(raw_keys),
            "unique_keys_checked": len(unique_keys),
            "namespace_buckets_seen": len(namespace_buckets),
            "recognized_namespaces_seen": len(used_namespaces),
            "unused_known_namespaces_count": len(unused_known_namespaces),
            "keys_with_unrecognized_namespaces": sum(
                item["count"] for item in unrecognized_namespaces
            ),
            "unrecognized_namespace_buckets": len(unrecognized_namespaces),
        },
        "used_namespaces": used_namespaces,
        "unused_known_namespaces": unused_known_namespaces,
        "namespace_counts": namespace_buckets,
        "unrecognized_namespaces": unrecognized_namespaces,
    }


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    raw_keys = load_recorded_idem_keys(root / "ledger" / "idem_keys.json")
    report = build_namespace_report(raw_keys)
    return report, 1 if report["status"] == "FAIL" else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect idem keys whose namespace prefix is not recognized."
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
    try:
        report, exit_code = run_check(root.resolve())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: failed to parse idem_keys.json: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: failed to read idem_keys.json: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
