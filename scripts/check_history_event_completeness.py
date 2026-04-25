#!/usr/bin/env python3
"""Validate required fields across all known ledger history event types.

This checker is intentionally completeness-focused rather than type-strict:
it verifies that each known event type has the fields needed to understand and
replay the event, while tolerating legacy field aliases that exist in the live
ledger.

Output: JSON with top-level ``status``, ``checks``, and ``summary``.
Exit code: 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")
_TIMESTAMP_ALIASES = ("timestamp", "created_at", "event_at", "started_at", "at", "ts")

# Fields that are allowed to be absent in legacy entries written with the "op" discriminator
# (an early format that predated the canonical schema enforcement).
_LEGACY_OP_OPTIONAL: dict[str, frozenset[str]] = {
    "escrow_return": frozenset({"amount"}),
}


def _req(name: str, *aliases: str) -> tuple[str, tuple[str, ...]]:
    return name, aliases or (name,)


REQUIRED_FIELDS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "accept": (
        _req("issue"),
        _req("agent"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "agent_registration": (
        _req("agent"),
        _req("balance"),
        _req("platform"),
        _req("operator"),
        _req("description"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "agent_removal": (
        _req("agent"),
        _req("balance_returned"),
        _req("mint_burned"),
        _req("description"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "domain_assign": (
        _req("agent"),
        _req("domain"),
        _req("previous"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "economy_reset": (
        _req("description"),
        _req("agents_zeroed"),
        _req("wea_returned_to_agent0"),
        _req("mint_burned"),
        _req("new_supply"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "escrow": (
        _req("issue"),
        _req("agent", "agent", "author"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "escrow_batch": (
        _req("author", "author", "agent"),
        _req("issues"),
        _req("total"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "escrow_create": (
        _req("issue"),
        _req("author", "author", "agent", "from"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "escrow_return": (
        _req("issue"),
        _req("agent", "agent", "author", "recipient", "to"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "escrow_return_bulk": (
        _req("agent", "agent", "author"),
        _req("amount"),
        _req("issues"),
        _req("description"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "hello_world_mint": (
        _req("agent"),
        _req("amount"),
        _req("issue"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "mint": (
        _req("agent"),
        _req("amount"),
        _req("issue"),
        _req("reason"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "payment": (
        _req("issue"),
        _req("agent"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "provisional_join": (
        _req("agent"),
        _req("github_username"),
        _req("expires"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "register": (
        _req("agent"),
        _req("platform"),
        _req("operator"),
        _req("github_username"),
        _req("slot"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "registration": (
        _req("agent"),
        _req("github_username"),
        _req("platform"),
        _req("operator"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "registration_confirmed": (
        _req("agent"),
        _req("previous_id"),
        _req("github_username"),
        _req("issue"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "reversal": (
        _req("issue"),
        _req("agent"),
        _req("amount"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "settle": (
        _req("issue"),
        _req("author", "author", "agent"),
        _req("escrow_amount"),
        _req("distributed"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "trajectory_mint": (
        _req("trajectory"),
        _req("slot"),
        _req("amount"),
        _req("issue"),
        _req("agent", "agent", "agents", "to"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
    "verification": (
        _req("issue"),
        _req("agent"),
        _req("verified_by"),
        _req("evidence"),
        _req("timestamp", *_TIMESTAMP_ALIASES),
    ),
}


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _has_value(entry: dict[str, Any], key: str) -> bool:
    value = entry.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _satisfies(entry: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    return any(_has_value(entry, alias) for alias in aliases)


def _load_jsonl_line(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        loaded = json.loads(repaired)

    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object, got {type(loaded).__name__}")
    return loaded


def _extra_missing_fields(event_type: str, entry: dict[str, Any]) -> list[str]:
    missing: list[str] = []

    if event_type == "trajectory_mint":
        has_agents = _has_value(entry, "agents")
        has_agent = _has_value(entry, "agent")
        has_per_agent = _has_value(entry, "per_agent")

        if has_agents and not has_per_agent:
            missing.append("per_agent")
        if has_per_agent and not has_agents and not has_agent:
            missing.append("agents")

    return missing


def _check_entry(filename: str, lineno: int, entry: dict[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    event_type = entry.get("event") or entry.get("type") or entry.get("op")

    if not isinstance(event_type, str) or not event_type.strip():
        violations.append(
            {
                "check": "missing_type",
                "status": "FAIL",
                "file": filename,
                "line": lineno,
                "event_type": None,
                "detail": "entry has no non-empty string 'type' field",
            }
        )
        return violations

    event_type = event_type.strip()
    schema = REQUIRED_FIELDS.get(event_type)
    if schema is None:
        violations.append(
            {
                "check": "unknown_type",
                "status": "WARN",
                "file": filename,
                "line": lineno,
                "event_type": event_type,
                "detail": f"unknown event type '{event_type}' — completeness rules not defined",
            }
        )
        return violations

    missing = [
        name
        for name, aliases in schema
        if not _satisfies(entry, aliases)
    ]
    missing.extend(_extra_missing_fields(event_type, entry))
    missing = sorted(set(missing))

    if missing and "op" in entry:
        legacy_optional = _LEGACY_OP_OPTIONAL.get(event_type, frozenset())
        missing = [f for f in missing if f not in legacy_optional]

    if missing:
        violations.append(
            {
                "check": "required_fields",
                "status": "FAIL",
                "file": filename,
                "line": lineno,
                "event_type": event_type,
                "missing_fields": missing,
                "detail": f"missing or empty required fields: {missing}",
            }
        )

    return violations


def _scan_file(path: Path) -> tuple[list[dict[str, Any]], int]:
    violations: list[dict[str, Any]] = []
    entry_count = 0

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        violations.append(
            {
                "check": "file_read_error",
                "status": "FAIL",
                "file": path.name,
                "line": 0,
                "detail": str(exc),
            }
        )
        return violations, 0

    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue

        entry_count += 1
        try:
            entry = _load_jsonl_line(stripped)
        except json.JSONDecodeError as exc:
            violations.append(
                {
                    "check": "parse_error",
                    "status": "WARN",
                    "file": path.name,
                    "line": lineno,
                    "detail": f"JSONL parse error: {exc}",
                }
            )
            continue
        except ValueError as exc:
            violations.append(
                {
                    "check": "not_a_dict",
                    "status": "FAIL",
                    "file": path.name,
                    "line": lineno,
                    "detail": str(exc),
                }
            )
            continue

        violations.extend(_check_entry(path.name, lineno, entry))

    return violations, entry_count


def run(root: Path) -> tuple[dict[str, Any], bool]:
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        result = {
            "status": "FAIL",
            "checks": [],
            "summary": f"history directory not found: {history_dir}",
        }
        return result, False

    jsonl_files = sorted(history_dir.glob("*.jsonl"))
    if not jsonl_files:
        result = {
            "status": "PASS",
            "checks": [],
            "summary": "no history files found — nothing to validate",
        }
        return result, True

    all_checks: list[dict[str, Any]] = []
    total_entries = 0
    for path in jsonl_files:
        file_checks, entry_count = _scan_file(path)
        all_checks.extend(file_checks)
        total_entries += entry_count

    fail_count = sum(1 for check in all_checks if check["status"] == "FAIL")
    warn_count = sum(1 for check in all_checks if check["status"] == "WARN")
    passed = fail_count == 0

    summary_parts = [
        f"{len(jsonl_files)} file(s)",
        f"{total_entries} entr{'y' if total_entries == 1 else 'ies'}",
    ]
    if fail_count:
        summary_parts.append(f"{fail_count} violation(s)")
    if warn_count:
        summary_parts.append(f"{warn_count} warning(s)")

    result = {
        "status": "PASS" if passed else "FAIL",
        "checks": all_checks,
        "summary": ", ".join(summary_parts),
    }
    return result, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)

    result, passed = run(_repo_root_from(args.root))
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
