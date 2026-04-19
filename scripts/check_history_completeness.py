#!/usr/bin/env python3
"""Detect ledger writes that never produced a matching history entry.

Checks three write surfaces against ``ledger/history/*.jsonl``:

1. accept/payment writes recorded in ``ledger/idem_keys.json`` must have a
   matching ``accept`` or ``payment`` history row for the same issue+agent.
2. ``escrow_create`` writes recorded in ``ledger/idem_keys.json`` must have a
   matching ``escrow_create`` history row for the same issue.
3. Every mint in ``ledger/trajectory_mints.json`` must have a matching
   ``trajectory_mint`` history row for the same ``(trajectory, slot)``.

The history stream is normalized across legacy and current schemas where the
event kind may live in ``event``, ``op``, or ``type``.

Exit code: 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _iter_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects from possibly-concatenated or noisy text."""
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            next_starts = [idx for idx in (text.find("{", pos + 1), text.find("[", pos + 1)) if idx != -1]
            if not next_starts:
                break
            pos = min(next_starts)
            continue
        if isinstance(obj, dict):
            results.append(obj)
        pos = end
    return results


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool):
        return None
    return str(value)


def _load_aliases(path: Path) -> dict[str, str]:
    payload = _load_json(path, default={})
    if not isinstance(payload, dict):
        return {}
    aliases: dict[str, str] = {}
    for source, target in payload.items():
        source_text = _normalize_text(source)
        target_text = _normalize_text(target)
        if source_text and target_text:
            aliases[source_text] = target_text
    return aliases


def _normalize_agent(value: Any, aliases: dict[str, str]) -> str | None:
    agent = _normalize_text(value)
    if not agent:
        return None
    return aliases.get(agent, agent)


def _normalize_issue(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return stripped.lstrip("#")
    return str(value)


def _normalize_slot(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _history_kind(event: dict[str, Any]) -> str:
    for field in ("event", "op", "type"):
        kind = _normalize_text(event.get(field))
        if kind:
            return kind.lower()
    return ""


def _load_history_events(history_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not history_dir.is_dir():
        return events
    for path in sorted(history_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            stripped = raw.strip()
            if not stripped:
                continue
            events.extend(_iter_json_objects(stripped))
    return events


def _load_idem_entries(path: Path) -> dict[str, Any]:
    payload = _load_json(path, default={})
    if not isinstance(payload, dict):
        return {}

    merged: dict[str, Any] = {}
    nested = payload.get("keys")
    if isinstance(nested, dict):
        for raw_key, value in nested.items():
            merged[str(raw_key)] = value

    for raw_key, value in payload.items():
        if raw_key in {"keys", "version"}:
            continue
        merged.setdefault(str(raw_key), value)

    return merged


def _payment_detail_from_key(parts: list[str]) -> tuple[str, str]:
    if len(parts) <= 3:
        return ("base", "")

    head = parts[3]
    if head.startswith("slot"):
        return ("slot", head[4:])
    if head.startswith("rank") and head[4:].isdigit():
        return ("rank", head[4:])
    if head == "ranking" and len(parts) >= 5:
        return ("rank", parts[4])
    if head == "duel" and len(parts) >= 5:
        return ("duel", parts[4])
    return ("base", "")


def _payment_detail_from_record(record: dict[str, Any]) -> tuple[str, str]:
    rank = record.get("rank")
    if rank is not None:
        return ("rank", str(rank))

    duel_role = _normalize_text(record.get("duel_role")) or _normalize_text(record.get("role"))
    if duel_role:
        return ("duel", duel_role)

    slot = _normalize_slot(record.get("slot"))
    if slot is not None:
        return ("slot", str(slot))

    return ("base", "")


def _detail_label(detail: tuple[str, str]) -> str:
    kind, value = detail
    if kind == "base":
        return "base"
    if value:
        return f"{kind}:{value}"
    return kind


def _collect_accept_payment_writes(
    idem_entries: dict[str, Any],
    aliases: dict[str, str],
) -> dict[tuple[str, str, tuple[str, str]], dict[str, Any]]:
    expected: dict[tuple[str, str, tuple[str, str]], dict[str, Any]] = {}
    for raw_key, value in idem_entries.items():
        issue: str | None = None
        agent: str | None = None
        detail = ("base", "")

        if raw_key.startswith(("accept|", "payment|")):
            parts = raw_key.split("|")
            if len(parts) >= 3:
                issue = _normalize_issue(parts[1])
                agent = _normalize_agent(parts[2], aliases)
                detail = _payment_detail_from_key(parts)
        elif isinstance(value, dict):
            action = _normalize_text(value.get("action")) or _normalize_text(value.get("op"))
            if action not in {"accept", "payment"}:
                continue
            issue = _normalize_issue(value.get("issue"))
            agent = _normalize_agent(value.get("agent") or value.get("author"), aliases)
            detail = _payment_detail_from_record(value)

        if not issue or not agent:
            continue

        signature = (issue, agent, detail)
        bucket = expected.setdefault(
            signature,
            {
                "issue": issue,
                "agent": agent,
                "detail": _detail_label(detail),
                "write_ids": [],
            },
        )
        bucket["write_ids"].append(raw_key)
    return expected


def _collect_escrow_create_writes(idem_entries: dict[str, Any]) -> dict[str, list[str]]:
    expected: dict[str, list[str]] = defaultdict(list)
    for raw_key, value in idem_entries.items():
        issue: str | None = None

        if raw_key.startswith("escrow_create_"):
            parts = raw_key.split("_")
            if len(parts) >= 3:
                issue = _normalize_issue(parts[2])
        elif isinstance(value, dict):
            action = _normalize_text(value.get("action")) or _normalize_text(value.get("op"))
            if action == "escrow_create":
                issue = _normalize_issue(value.get("issue"))

        if issue:
            expected[issue].append(raw_key)

    return {issue: sorted(write_ids) for issue, write_ids in expected.items()}


def _load_trajectory_mints(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path, default={"mints": []})
    mints = payload.get("mints", []) if isinstance(payload, dict) else []
    if not isinstance(mints, list):
        return []

    records: list[dict[str, Any]] = []
    for mint in mints:
        if not isinstance(mint, dict):
            continue
        trajectory = _normalize_text(mint.get("trajectory"))
        slot = _normalize_slot(mint.get("slot"))
        if not trajectory or slot is None:
            continue
        records.append(
            {
                "trajectory": trajectory,
                "slot": slot,
                "issue": _normalize_issue(mint.get("issue") or mint.get("issue_or_pr")),
                "idem_key": _normalize_text(mint.get("idem_key")),
            }
        )
    return records


def _build_history_indexes(
    events: list[dict[str, Any]],
    aliases: dict[str, str],
) -> tuple[
    set[tuple[str, str, tuple[str, str]]],
    dict[str, set[str]],
    Counter[str],
    Counter[tuple[str, int]],
]:
    payment_accept_signatures: set[tuple[str, str, tuple[str, str]]] = set()
    escrow_create_keys: dict[str, set[str]] = defaultdict(set)
    escrow_create_counts: Counter[str] = Counter()
    trajectory_counts: Counter[tuple[str, int]] = Counter()

    for event in events:
        kind = _history_kind(event)

        if kind in {"accept", "payment"}:
            issue = _normalize_issue(event.get("issue"))
            agent = _normalize_agent(event.get("agent") or event.get("author"), aliases)
            if issue and agent:
                detail = _payment_detail_from_record(event)
                payment_accept_signatures.add((issue, agent, detail))
                payment_accept_signatures.add((issue, agent, ("base", "")))

        elif kind == "escrow_create":
            issue = _normalize_issue(event.get("issue"))
            if issue:
                escrow_create_counts[issue] += 1
                idem_key = _normalize_text(event.get("idem_key"))
                if idem_key:
                    escrow_create_keys[issue].add(idem_key)

        elif kind == "trajectory_mint":
            trajectory = _normalize_text(event.get("trajectory"))
            slot = _normalize_slot(event.get("slot"))
            if trajectory and slot is not None:
                trajectory_counts[(trajectory, slot)] += 1

    return payment_accept_signatures, escrow_create_keys, escrow_create_counts, trajectory_counts


def _check_accept_payment_history(
    expected: dict[tuple[str, str, tuple[str, str]], dict[str, Any]],
    actual: set[tuple[str, str, tuple[str, str]]],
) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    for signature in sorted(expected):
        if signature in actual:
            continue
        item = expected[signature]
        missing.append(
            {
                "issue": item["issue"],
                "agent": item["agent"],
                "detail": item["detail"],
                "write_ids": sorted(item["write_ids"]),
            }
        )

    return {
        "name": "accept_payment_history",
        "status": "PASS" if not missing else "FAIL",
        "expected_writes": len(expected),
        "history_entries": len(actual),
        "missing": missing,
    }


def _check_escrow_create_history(
    expected: dict[str, list[str]],
    history_keys: dict[str, set[str]],
    history_counts: Counter[str],
) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    for issue in sorted(expected, key=lambda value: (int(value) if value.isdigit() else value)):
        write_ids = expected[issue]
        exact_matches = sum(1 for write_id in write_ids if write_id in history_keys.get(issue, set()))
        actual_total = history_counts.get(issue, 0)
        spare_matches = max(actual_total - exact_matches, 0)
        unmatched_ids = [write_id for write_id in write_ids if write_id not in history_keys.get(issue, set())]

        if len(unmatched_ids) <= spare_matches:
            continue

        for write_id in unmatched_ids[spare_matches:]:
            missing.append(
                {
                    "issue": issue,
                    "write_id": write_id,
                    "history_entries": actual_total,
                }
            )

    return {
        "name": "escrow_create_history",
        "status": "PASS" if not missing else "FAIL",
        "expected_writes": sum(len(write_ids) for write_ids in expected.values()),
        "history_entries": sum(history_counts.values()),
        "missing": missing,
    }


def _check_trajectory_mint_history(
    expected: list[dict[str, Any]],
    actual: Counter[tuple[str, int]],
) -> dict[str, Any]:
    expected_counts: Counter[tuple[str, int]] = Counter(
        (record["trajectory"], record["slot"]) for record in expected
    )
    first_record_for_key: dict[tuple[str, int], dict[str, Any]] = {}
    for record in expected:
        first_record_for_key.setdefault((record["trajectory"], record["slot"]), record)

    missing: list[dict[str, Any]] = []
    for key in sorted(expected_counts):
        expected_count = expected_counts[key]
        actual_count = actual.get(key, 0)
        if actual_count >= expected_count:
            continue
        record = first_record_for_key[key]
        missing.append(
            {
                "trajectory": record["trajectory"],
                "slot": record["slot"],
                "issue": record["issue"],
                "idem_key": record["idem_key"],
                "expected_writes": expected_count,
                "history_entries": actual_count,
                "missing_entries": expected_count - actual_count,
            }
        )

    return {
        "name": "trajectory_mint_history",
        "status": "PASS" if not missing else "FAIL",
        "expected_writes": len(expected),
        "history_entries": sum(actual.values()),
        "missing": missing,
    }


def run(root: Path) -> tuple[dict[str, Any], bool]:
    aliases = _load_aliases(root / "ledger" / "agent_aliases.json")
    history_events = _load_history_events(root / "ledger" / "history")
    idem_entries = _load_idem_entries(root / "ledger" / "idem_keys.json")
    trajectory_mints = _load_trajectory_mints(root / "ledger" / "trajectory_mints.json")

    payment_accept_signatures, escrow_create_keys, escrow_create_counts, trajectory_counts = _build_history_indexes(
        history_events,
        aliases,
    )

    checks = [
        _check_accept_payment_history(
            _collect_accept_payment_writes(idem_entries, aliases),
            payment_accept_signatures,
        ),
        _check_escrow_create_history(
            _collect_escrow_create_writes(idem_entries),
            escrow_create_keys,
            escrow_create_counts,
        ),
        _check_trajectory_mint_history(
            trajectory_mints,
            trajectory_counts,
        ),
    ]

    failed = [check for check in checks if check["status"] == "FAIL"]
    status = "PASS" if not failed else "FAIL"
    missing_total = sum(len(check["missing"]) for check in checks)
    summary = (
        f"{len(checks) - len(failed)} PASS, {len(failed)} FAIL, "
        f"{missing_total} missing history linkage(s)"
    )
    result = {
        "status": status,
        "checks": checks,
        "summary": summary,
    }
    return result, status == "PASS"


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
