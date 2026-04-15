#!/usr/bin/env python3
"""Detect idem keys that have no matching ledger history event."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_TYPES = frozenset({"payment", "escrow", "escrow_return", "trajectory_mint"})


@dataclass(frozen=True)
class ParsedKey:
    kind: str
    issue: str | None = None
    actor: str | None = None
    trajectory: str | None = None
    slot: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(registered_at: str | None, now: datetime) -> float | None:
    parsed = _parse_timestamp(registered_at)
    if parsed is None:
        return None
    return round((now - parsed).total_seconds() / 86400, 1)


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): str(v) for k, v in payload.items()}


def _normalize_actor(actor: str | None, aliases: dict[str, str]) -> str | None:
    if actor is None:
        return None
    actor = str(actor)
    return aliases.get(actor, actor)


def _registered_at_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for field in ("registered_at", "created_at", "timestamp"):
            field_value = value.get(field)
            if isinstance(field_value, str):
                return field_value
    return None


def _should_check_key(raw_key: str, value: Any) -> bool:
    if raw_key.startswith("escrow_create_"):
        return True
    prefix = raw_key.split("|", 1)[0]
    if prefix in TARGET_TYPES:
        return True
    if isinstance(value, dict) and str(value.get("op", "")) in TARGET_TYPES:
        return True
    return False


def load_idem_entries(path: Path) -> list[tuple[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return []

    merged: dict[str, Any] = {}
    nested = payload.get("keys")
    if isinstance(nested, dict):
        merged.update(nested)
    for raw_key, value in payload.items():
        if raw_key in {"keys", "version"}:
            continue
        merged.setdefault(str(raw_key), value)

    return [
        (raw_key, value)
        for raw_key, value in merged.items()
        if _should_check_key(raw_key, value)
    ]


def parse_idem_key(raw_key: str, aliases: dict[str, str]) -> ParsedKey | None:
    if raw_key.startswith("escrow_create_"):
        return None

    parts = raw_key.split("|")
    if not parts:
        return None

    kind = parts[0]
    if kind in {"payment", "escrow", "escrow_return"}:
        if len(parts) < 2:
            return None
        issue = parts[1]
        actor = _normalize_actor(parts[2], aliases) if len(parts) >= 3 and parts[2] else None
        return ParsedKey(kind=kind, issue=issue, actor=actor)

    if kind == "trajectory_mint":
        if len(parts) < 3:
            return None
        trajectory = parts[1]
        slot = parts[2]
        actor = _normalize_actor(parts[3], aliases) if len(parts) >= 4 and parts[3] else None
        return ParsedKey(kind=kind, trajectory=trajectory, slot=slot, actor=actor)

    return None


def load_history_events(history_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events

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
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _history_actor(event: dict[str, Any], aliases: dict[str, str]) -> str | None:
    actor = event.get("agent") or event.get("author") or event.get("recipient")
    if actor:
        return _normalize_actor(str(actor), aliases)
    agents = event.get("agents")
    if isinstance(agents, list) and len(agents) == 1:
        return _normalize_actor(str(agents[0]), aliases)
    return None


def build_history_index(
    events: list[dict[str, Any]],
    aliases: dict[str, str],
) -> dict[str, set[tuple[str, ...]]]:
    index: dict[str, set[tuple[str, ...]]] = {
        "payment": set(),
        "payment_any": set(),
        "escrow": set(),
        "escrow_any": set(),
        "escrow_return": set(),
        "escrow_return_any": set(),
        "trajectory_mint": set(),
        "trajectory_mint_any": set(),
    }

    for event in events:
        event_type = str(event.get("type", ""))
        actor = _history_actor(event, aliases)

        if event_type in {"payment", "escrow", "escrow_return"}:
            issue = str(event.get("issue", ""))
            if issue:
                index[f"{event_type}_any"].add((issue,))
                if actor:
                    index[event_type].add((issue, actor))
        elif event_type == "trajectory_mint":
            trajectory = str(event.get("trajectory", ""))
            slot = str(event.get("slot", ""))
            if trajectory and slot:
                index["trajectory_mint_any"].add((trajectory, slot))
                if actor:
                    index["trajectory_mint"].add((trajectory, slot, actor))

    return index


def key_has_history_match(parsed_key: ParsedKey | None, history_index: dict[str, set[tuple[str, ...]]]) -> bool:
    if parsed_key is None:
        return False

    if parsed_key.kind in {"payment", "escrow", "escrow_return"}:
        if parsed_key.issue is None:
            return False
        if parsed_key.actor is not None:
            return (parsed_key.issue, parsed_key.actor) in history_index[parsed_key.kind]
        return (parsed_key.issue,) in history_index[f"{parsed_key.kind}_any"]

    if parsed_key.kind == "trajectory_mint":
        if parsed_key.trajectory is None or parsed_key.slot is None:
            return False
        if parsed_key.actor is not None:
            return (
                parsed_key.trajectory,
                parsed_key.slot,
                parsed_key.actor,
            ) in history_index["trajectory_mint"]
        return (parsed_key.trajectory, parsed_key.slot) in history_index["trajectory_mint_any"]

    return False


def find_orphans(
    idem_entries: list[tuple[str, Any]],
    history_events: list[dict[str, Any]],
    aliases: dict[str, str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    aliases = aliases or {}
    now = now or _utc_now()
    history_index = build_history_index(history_events, aliases)

    orphans: list[dict[str, Any]] = []
    for raw_key, value in idem_entries:
        parsed_key = parse_idem_key(raw_key, aliases)
        if key_has_history_match(parsed_key, history_index):
            continue

        registered_at = _registered_at_from_value(value)
        orphan: dict[str, Any] = {
            "key": raw_key,
            "registered_at": registered_at,
            "age_days": _age_days(registered_at, now),
        }
        orphans.append(orphan)

    orphans.sort(key=lambda item: item["key"])
    return orphans


def run_check(
    root: Path,
    *,
    strict: bool = False,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    aliases = load_aliases(root / "ledger" / "agent_aliases.json")
    idem_entries = load_idem_entries(root / "ledger" / "idem_keys.json")
    history_events = load_history_events(root / "ledger" / "history")
    orphans = find_orphans(idem_entries, history_events, aliases, now)

    if strict and orphans:
        status = "FAIL"
    elif orphans:
        status = "WARN"
    else:
        status = "PASS"

    summary = f"{len(orphans)} orphan keys found ({status})"
    report = {
        "status": status,
        "orphans": orphans,
        "summary": summary,
    }
    return report, 1 if status == "FAIL" else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find idem keys with no corresponding history event."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any orphan key is found",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root or Path(__file__).resolve().parent.parent
    report, exit_code = run_check(root.resolve(), strict=args.strict)
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
