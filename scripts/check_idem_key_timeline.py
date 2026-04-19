#!/usr/bin/env python3
"""Check temporal consistency for idem keys with history-backed operations.

This validator focuses on the operations that currently rely on idem keys for
ledger safety:

* ``accept``
* ``escrow_create``
* ``trajectory_mint``

It enforces three invariants:

1. Every known idem key has a matching history event.
2. Every history event for those operations has a timestamp on or after the
   earliest ``ledger/history/YYYY-MM-DD.jsonl`` file date.
3. The number of unique known idem keys is at least the number of
   idempotency-requiring history events.

Exit codes:
  0  PASS
  1  one or more invariants failed
  2  required ledger files are missing
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TARGET_KINDS = frozenset({"accept", "escrow_create", "trajectory_mint"})
TIMESTAMP_FIELDS = ("timestamp", "created_at", "ts", "started_at", "event_at", "at")


@dataclass(frozen=True)
class ParsedIdemKey:
    kind: str
    issue: str | None = None
    actor: str | None = None
    trajectory: str | None = None
    slot: str | None = None
    variant: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnownIdemEntry:
    raw_key: str
    parsed: ParsedIdemKey
    registered_at: str | None


@dataclass(frozen=True)
class HistoryRecord:
    file_name: str
    line_number: int
    event: dict[str, Any]
    operation_kind: str | None
    explicit_idem_key: ParsedIdemKey | None
    timestamp: datetime | None


def _normalize_actor(actor: str | None, aliases: dict[str, str]) -> str | None:
    if actor is None:
        return None
    normalized = str(actor)
    return aliases.get(normalized, normalized)


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def load_idem_keys(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        return {}

    merged: dict[str, Any] = {}
    nested = payload.get("keys")
    if isinstance(nested, dict):
        merged.update(nested)

    for raw_key, value in payload.items():
        if raw_key in {"keys", "version"}:
            continue
        merged.setdefault(str(raw_key), value)

    return merged


def _registered_at(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for field in ("registered_at", "created_at", "timestamp", "ts"):
            field_value = value.get(field)
            if isinstance(field_value, str):
                return field_value
    return None


def parse_known_idem_key(raw_key: str, aliases: dict[str, str]) -> ParsedIdemKey | None:
    if raw_key.startswith("accept|"):
        parts = raw_key.split("|")
        if len(parts) < 3:
            return None
        return ParsedIdemKey(
            kind="accept",
            issue=parts[1],
            actor=_normalize_actor(parts[2], aliases),
            variant=tuple(parts[3:]),
        )

    if raw_key.startswith("escrow_create_"):
        prefix, issue, *rest = raw_key.split("_")
        if prefix != "escrow" or issue != "create":
            return None
        if not rest:
            return None
        issue_number = rest[0]
        if not issue_number.isdigit():
            return None
        suffix = "_".join(rest[1:])
        variant = (suffix,) if suffix else ()
        return ParsedIdemKey(
            kind="escrow_create",
            issue=issue_number,
            variant=variant,
        )

    if raw_key.startswith("trajectory_mint|"):
        parts = raw_key.split("|")
        if len(parts) < 3:
            return None
        actor = _normalize_actor(parts[3], aliases) if len(parts) >= 4 and parts[3] else None
        return ParsedIdemKey(
            kind="trajectory_mint",
            trajectory=parts[1],
            slot=str(parts[2]),
            actor=actor,
            variant=tuple(parts[4:]),
        )

    return None


def collect_known_idem_keys(
    raw_keys: dict[str, Any],
    aliases: dict[str, str],
) -> list[KnownIdemEntry]:
    entries: list[KnownIdemEntry] = []
    for raw_key, value in raw_keys.items():
        parsed = parse_known_idem_key(raw_key, aliases)
        if parsed is None:
            continue
        entries.append(
            KnownIdemEntry(
                raw_key=raw_key,
                parsed=parsed,
                registered_at=_registered_at(value),
            )
        )
    entries.sort(key=lambda item: item.raw_key)
    return entries


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_timestamp(event: dict[str, Any]) -> datetime | None:
    for field in TIMESTAMP_FIELDS:
        parsed = _parse_iso_datetime(event.get(field))
        if parsed is not None:
            return parsed
    return None


def _iter_json_objects(raw_line: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    text = raw_line.strip()
    results: list[dict[str, Any]] = []
    position = 0

    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            next_starts = [
                index
                for index in (text.find("{", position + 1), text.find("[", position + 1))
                if index != -1
            ]
            if not next_starts:
                break
            position = min(next_starts)
            continue
        if isinstance(obj, dict):
            results.append(obj)
        position = end

    return results


def _event_kind_from(event: dict[str, Any], explicit_key: ParsedIdemKey | None) -> str | None:
    raw_kind = event.get("event") or event.get("op") or event.get("type")
    if isinstance(raw_kind, str) and raw_kind in TARGET_KINDS:
        return raw_kind
    if explicit_key is not None:
        return explicit_key.kind
    return None


def load_history_records(
    history_dir: Path,
    aliases: dict[str, str],
) -> list[HistoryRecord]:
    records: list[HistoryRecord] = []
    if not history_dir.is_dir():
        return records

    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                for event in _iter_json_objects(raw_line):
                    idem_value = event.get("idem_key")
                    explicit_key = (
                        parse_known_idem_key(idem_value, aliases)
                        if isinstance(idem_value, str)
                        else None
                    )
                    records.append(
                        HistoryRecord(
                            file_name=path.name,
                            line_number=line_number,
                            event=event,
                            operation_kind=_event_kind_from(event, explicit_key),
                            explicit_idem_key=explicit_key,
                            timestamp=extract_timestamp(event),
                        )
                    )

    return records


def earliest_history_file_date(history_dir: Path) -> date | None:
    dates: list[date] = []
    for path in history_dir.glob("*.jsonl"):
        try:
            dates.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return min(dates) if dates else None


def _event_actor_set(event: dict[str, Any], aliases: dict[str, str]) -> set[str]:
    actors: set[str] = set()

    for field in ("agent", "author", "recipient", "to", "from"):
        normalized = _normalize_actor(event.get(field), aliases)
        if normalized:
            actors.add(normalized)

    agents = event.get("agents")
    if isinstance(agents, list):
        for item in agents:
            normalized = _normalize_actor(item, aliases)
            if normalized:
                actors.add(normalized)

    return actors


def _first_event_actor(event: dict[str, Any], aliases: dict[str, str]) -> str | None:
    for field in ("agent", "author", "recipient", "to", "from"):
        normalized = _normalize_actor(event.get(field), aliases)
        if normalized:
            return normalized

    agents = event.get("agents")
    if isinstance(agents, list) and len(agents) == 1:
        return _normalize_actor(agents[0], aliases)

    return None


def build_history_index(
    records: list[HistoryRecord],
    aliases: dict[str, str],
) -> dict[str, Any]:
    explicit_keys: set[ParsedIdemKey] = set()
    accept_events: set[tuple[str, str]] = set()
    escrow_create_events: set[str] = set()
    trajectory_mint_any: set[tuple[str, str]] = set()
    trajectory_mint_actor: set[tuple[str, str, str]] = set()
    counts: Counter[str] = Counter()

    for record in records:
        if record.explicit_idem_key is not None:
            explicit_keys.add(record.explicit_idem_key)

        kind = record.operation_kind
        if kind is None:
            continue

        counts[kind] += 1

        if kind == "accept":
            if record.explicit_idem_key is not None and record.explicit_idem_key.kind == "accept":
                issue = record.explicit_idem_key.issue
                actor = record.explicit_idem_key.actor
            else:
                issue = str(record.event.get("issue", ""))
                actor = _first_event_actor(record.event, aliases)

            if issue and actor:
                accept_events.add((issue, actor))

        elif kind == "escrow_create":
            issue = (
                record.explicit_idem_key.issue
                if record.explicit_idem_key is not None and record.explicit_idem_key.kind == "escrow_create"
                else str(record.event.get("issue", ""))
            )
            if issue:
                escrow_create_events.add(issue)

        elif kind == "trajectory_mint":
            if record.explicit_idem_key is not None and record.explicit_idem_key.kind == "trajectory_mint":
                trajectory = record.explicit_idem_key.trajectory or ""
                slot = record.explicit_idem_key.slot or ""
            else:
                trajectory = str(record.event.get("trajectory", ""))
                slot = str(record.event.get("slot", ""))

            if not trajectory or not slot:
                continue

            trajectory_mint_any.add((trajectory, slot))
            for actor in _event_actor_set(record.event, aliases):
                trajectory_mint_actor.add((trajectory, slot, actor))

    return {
        "explicit_keys": explicit_keys,
        "accept_events": accept_events,
        "escrow_create_events": escrow_create_events,
        "trajectory_mint_any": trajectory_mint_any,
        "trajectory_mint_actor": trajectory_mint_actor,
        "counts": dict(counts),
    }


def key_has_history_match(
    parsed: ParsedIdemKey,
    history_index: dict[str, Any],
) -> bool:
    if parsed in history_index["explicit_keys"]:
        return True

    if parsed.kind == "accept":
        if parsed.issue is None or parsed.actor is None:
            return False
        return (parsed.issue, parsed.actor) in history_index["accept_events"]

    if parsed.kind == "escrow_create":
        if parsed.issue is None:
            return False
        return parsed.issue in history_index["escrow_create_events"]

    if parsed.kind == "trajectory_mint":
        if parsed.trajectory is None or parsed.slot is None:
            return False
        if parsed.actor is not None:
            return (
                parsed.trajectory,
                parsed.slot,
                parsed.actor,
            ) in history_index["trajectory_mint_actor"]
        return (parsed.trajectory, parsed.slot) in history_index["trajectory_mint_any"]

    return False


def find_phantom_keys(
    idem_entries: list[KnownIdemEntry],
    history_index: dict[str, Any],
) -> list[dict[str, Any]]:
    phantom_keys: list[dict[str, Any]] = []

    for entry in idem_entries:
        if key_has_history_match(entry.parsed, history_index):
            continue

        phantom_keys.append(
            {
                "idem_key": entry.raw_key,
                "operation": entry.parsed.kind,
                "registered_at": entry.registered_at,
            }
        )

    return phantom_keys


def find_backdated_events(
    records: list[HistoryRecord],
    earliest_file_date: date,
) -> list[dict[str, Any]]:
    backdated: list[dict[str, Any]] = []

    for record in records:
        if record.operation_kind is None or record.timestamp is None:
            continue
        if record.timestamp.date() >= earliest_file_date:
            continue

        raw_type = record.event.get("type") or record.event.get("op")
        backdated.append(
            {
                "operation": record.operation_kind,
                "event_type": raw_type,
                "file": record.file_name,
                "line": record.line_number,
                "timestamp": record.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "earliest_history_file_date": earliest_file_date.isoformat(),
            }
        )

    return backdated


def run_check(root: Path) -> dict[str, Any]:
    history_dir = root / "ledger" / "history"
    idem_path = root / "ledger" / "idem_keys.json"
    aliases_path = root / "ledger" / "agent_aliases.json"

    aliases = load_aliases(aliases_path)
    raw_idem_keys = load_idem_keys(idem_path)
    idem_entries = collect_known_idem_keys(raw_idem_keys, aliases)
    history_records = load_history_records(history_dir, aliases)

    earliest_file = earliest_history_file_date(history_dir)
    history_index = build_history_index(history_records, aliases)
    phantom_keys = find_phantom_keys(idem_entries, history_index)
    backdated_events = (
        find_backdated_events(history_records, earliest_file)
        if earliest_file is not None
        else []
    )

    key_counts = Counter(entry.parsed.kind for entry in idem_entries)
    event_counts = Counter(history_index["counts"])
    total_keys = len(idem_entries)
    total_events = sum(event_counts.values())
    count_pass = total_keys >= total_events

    status = "PASS"
    if phantom_keys or backdated_events or not count_pass:
        status = "FAIL"

    if status == "PASS":
        summary = (
            f"PASS: {total_keys} known idem key(s) cover {total_events} "
            "idempotency-requiring history event(s)."
        )
    else:
        summary = (
            f"FAIL: phantom_keys={len(phantom_keys)}, "
            f"backdated_events={len(backdated_events)}, "
            f"known_idem_keys={total_keys}, required_history_events={total_events}."
        )

    return {
        "status": status,
        "summary": summary,
        "earliest_history_file_date": earliest_file.isoformat() if earliest_file else None,
        "counts": {
            "known_idem_keys": total_keys,
            "required_history_events": total_events,
            "keys_by_operation": {kind: key_counts.get(kind, 0) for kind in sorted(TARGET_KINDS)},
            "events_by_operation": {kind: event_counts.get(kind, 0) for kind in sorted(TARGET_KINDS)},
        },
        "phantom_keys": phantom_keys,
        "backdated_events": backdated_events,
        "count_check": {
            "status": "PASS" if count_pass else "FAIL",
            "unique_idem_keys": total_keys,
            "required_history_events": total_events,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that known idem keys line up with ledger history."
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

    history_dir = root / "ledger" / "history"
    idem_path = root / "ledger" / "idem_keys.json"
    earliest_file = earliest_history_file_date(history_dir)

    if not idem_path.exists():
        print(f"SKIP: idem_keys.json not found at {idem_path}", file=sys.stderr)
        return 2
    if not history_dir.is_dir():
        print(f"SKIP: history directory not found at {history_dir}", file=sys.stderr)
        return 2
    if earliest_file is None:
        print(
            f"SKIP: no YYYY-MM-DD history files found under {history_dir}",
            file=sys.stderr,
        )
        return 2

    report = run_check(root.resolve())
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
