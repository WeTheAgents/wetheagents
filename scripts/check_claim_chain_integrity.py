#!/usr/bin/env python3
"""Validate that claim history forms coherent per-issue resolution chains.

Each ``claim`` event must eventually become one of:
  - resolved by a same-agent ``accept`` / ``payment`` / ``reject``
  - superseded by a later claim on the same issue
  - pending as the current tail claim on an in-progress issue

Single-claim mechanics (default / ``standard``) allow reassignment via a later
claim. Multi-claim mechanics (``every_good``, ``progressive``, ``linear``,
``best_x``, ``duel``) do not treat different-agent claims as reassignment;
those claims must resolve per agent.

Exit codes:
    0 - PASS (no broken claim chains; pending claims are allowed)
    1 - FAIL (broken chains or malformed relevant history entries)

Output: JSON to stdout with ``status``, ``checks``, ``summary``,
``pending_claims``, and ``broken_claims``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")
_RELEVANT_TYPES = frozenset({"claim", "accept", "payment", "reject"})
_TERMINAL_TYPES = frozenset({"accept", "payment", "reject"})
_MULTI_CLAIM_MECHANICS = frozenset({"every_good", "progressive", "linear", "best_x", "duel"})
_CLOSED_STATUSES = frozenset({"paid", "cancelled"})


@dataclass(frozen=True)
class TimelineEvent:
    """Relevant history event used for claim-chain analysis."""

    type: str
    issue: int
    agent: str
    timestamp: datetime
    timestamp_raw: str
    path: str
    line: int


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _load_jsonl_line(raw: str) -> dict[str, Any]:
    """Parse one JSONL line, repairing legacy invalid escapes when possible."""
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _INVALID_ESCAPE_RE.sub(r"\\\\", raw)
        loaded = json.loads(repaired)

    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object, got {type(loaded).__name__}")
    return loaded


def _event_timestamp_fields(event: dict[str, Any]) -> tuple[datetime, str]:
    """Return the best available timestamp for a relevant history event."""
    for key in ("timestamp", "created_at", "event_at", "started_at", "at"):
        value = str(event.get(key, "") or "").strip()
        if value:
            return parse_iso_utc(value), value
    raise ValueError("missing timestamp")


def _event_agent(event: dict[str, Any]) -> str:
    for key in ("agent", "author"):
        value = str(event.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _event_issue(event: dict[str, Any]) -> int | None:
    raw_issue = event.get("issue")
    if raw_issue is None:
        return None
    try:
        return int(raw_issue)
    except (TypeError, ValueError):
        return None


def _normalize_mechanic(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    aliases = {
        "pod": "every_good",
        "paid_on_delivery": "every_good",
        "progressive_every_good": "progressive",
        "ranking": "best_x",
        "winner_take_all": "best_x",
        "x_best": "best_x",
    }
    return aliases.get(normalized, normalized)


def _load_optional_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(loaded, dict):
        return loaded
    raise ValueError(f"{path.name} must contain a JSON object")


def load_relevant_events(root: Path) -> list[TimelineEvent]:
    """Load and sort claim-chain-relevant history events."""
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        return []

    events: list[TimelineEvent] = []
    for path in sorted(history_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, raw in enumerate(handle, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                payload = _load_jsonl_line(stripped)
                event_type = str(payload.get("type", "") or "").strip()
                if event_type not in _RELEVANT_TYPES:
                    continue

                issue = _event_issue(payload)
                if issue is None:
                    raise ValueError(f"{path.name}:{line_no} {event_type} event missing valid issue")

                agent = _event_agent(payload)
                if not agent:
                    raise ValueError(f"{path.name}:{line_no} {event_type} event missing agent/author")

                try:
                    timestamp, timestamp_raw = _event_timestamp_fields(payload)
                except ValueError as exc:
                    raise ValueError(f"{path.name}:{line_no} {event_type} event {exc}") from exc

                events.append(
                    TimelineEvent(
                        type=event_type,
                        issue=issue,
                        agent=agent,
                        timestamp=timestamp,
                        timestamp_raw=timestamp_raw,
                        path=path.name,
                        line=line_no,
                    )
                )

    events.sort(key=lambda item: (item.timestamp, item.path, item.line))
    return events


def _issue_metadata(
    task_index: dict[str, Any],
    escrows: dict[str, Any],
) -> tuple[dict[int, str], dict[int, str]]:
    """Return per-issue mechanics and task statuses from optional ledger files."""
    mechanics: dict[int, str] = {}
    statuses: dict[int, str] = {}

    tasks = task_index.get("tasks", {})
    if isinstance(tasks, dict):
        for issue_str, task in tasks.items():
            if not isinstance(task, dict):
                continue
            try:
                issue = int(issue_str)
            except (TypeError, ValueError):
                continue

            mechanic = (
                _normalize_mechanic(task.get("mechanic"))
                or _normalize_mechanic(task.get("reward_type"))
            )
            accepted_agents = task.get("accepted_agents")
            if (
                mechanic is None
                and isinstance(accepted_agents, list)
                and len([agent for agent in accepted_agents if str(agent).strip()]) > 1
            ):
                mechanic = "every_good"
            if mechanic:
                mechanics[issue] = mechanic

            status = str(task.get("status", "") or "").strip().lower()
            if status:
                statuses[issue] = status

    active = escrows.get("active", {})
    if isinstance(active, dict):
        for issue_str, escrow in active.items():
            if not isinstance(escrow, dict):
                continue
            try:
                issue = int(issue_str)
            except (TypeError, ValueError):
                continue
            mechanic = (
                _normalize_mechanic(escrow.get("type"))
                or _normalize_mechanic(escrow.get("reward_type"))
                or _normalize_mechanic(escrow.get("mechanic"))
            )
            if mechanic and issue not in mechanics:
                mechanics[issue] = mechanic

    return mechanics, statuses


def _is_multi_claim_issue(mechanic: str | None) -> bool:
    return mechanic in _MULTI_CLAIM_MECHANICS


def _infer_issue_mechanic(
    issue_events: list[TimelineEvent],
    *,
    existing: str | None,
) -> str | None:
    """Infer a multi-claim mechanic from history when metadata is missing."""
    if existing is not None:
        return existing

    terminal_agents = {
        event.agent
        for event in issue_events
        if event.type in _TERMINAL_TYPES
    }
    if len(terminal_agents) > 1:
        return "every_good"
    return None


def _claim_is_closed_issue(issue_status: str | None) -> bool:
    return bool(issue_status and issue_status in _CLOSED_STATUSES)


def _claim_entry(
    claim: TimelineEvent,
    *,
    mechanic: str | None,
    issue_status: str | None,
) -> dict[str, Any]:
    entry = {
        "issue": claim.issue,
        "agent": claim.agent,
        "claim_ts": claim.timestamp_raw,
        "file": claim.path,
        "line": claim.line,
    }
    if mechanic:
        entry["mechanic"] = mechanic
    if issue_status:
        entry["issue_status"] = issue_status
    return entry


def _resolve_single_claim(
    claim: TimelineEvent,
    later_events: list[TimelineEvent],
    *,
    mechanic: str | None,
    issue_status: str | None,
) -> dict[str, Any]:
    base = _claim_entry(claim, mechanic=mechanic, issue_status=issue_status)

    for later in later_events:
        if later.type == "claim":
            return {
                "kind": "superseded",
                **base,
                "resolved_by": "claim",
                "resolved_ts": later.timestamp_raw,
                "resolved_agent": later.agent,
            }

        if later.type in _TERMINAL_TYPES:
            if later.agent == claim.agent:
                return {
                    "kind": "resolved",
                    **base,
                    "resolved_by": later.type,
                    "resolved_ts": later.timestamp_raw,
                    "resolved_agent": later.agent,
                }
            return {
                "kind": "broken",
                **base,
                "reason": "mismatched_terminal",
                "next_event_type": later.type,
                "next_event_agent": later.agent,
                "next_event_ts": later.timestamp_raw,
            }

    if _claim_is_closed_issue(issue_status):
        return {
            "kind": "broken",
            **base,
            "reason": "closed_without_resolution",
        }

    return {
        "kind": "pending",
        **base,
    }


def _resolve_multi_claim(
    claim: TimelineEvent,
    later_events: list[TimelineEvent],
    *,
    mechanic: str | None,
    issue_status: str | None,
) -> dict[str, Any]:
    base = _claim_entry(claim, mechanic=mechanic, issue_status=issue_status)

    for later in later_events:
        if later.agent != claim.agent:
            continue

        if later.type == "claim":
            return {
                "kind": "superseded",
                **base,
                "resolved_by": "claim",
                "resolved_ts": later.timestamp_raw,
                "resolved_agent": later.agent,
            }

        if later.type in _TERMINAL_TYPES:
            return {
                "kind": "resolved",
                **base,
                "resolved_by": later.type,
                "resolved_ts": later.timestamp_raw,
                "resolved_agent": later.agent,
            }

    if _claim_is_closed_issue(issue_status):
        conflicting_terminal = next(
            (event for event in later_events if event.type in _TERMINAL_TYPES),
            None,
        )
        broken = {
            "kind": "broken",
            **base,
            "reason": "closed_without_same_agent_resolution",
        }
        if conflicting_terminal is not None:
            broken.update(
                {
                    "next_event_type": conflicting_terminal.type,
                    "next_event_agent": conflicting_terminal.agent,
                    "next_event_ts": conflicting_terminal.timestamp_raw,
                }
            )
        return broken

    return {
        "kind": "pending",
        **base,
    }


def build_result(
    events: list[TimelineEvent],
    *,
    mechanics: dict[int, str],
    statuses: dict[int, str],
) -> dict[str, Any]:
    """Return the claim-chain integrity report."""
    events_by_issue: dict[int, list[TimelineEvent]] = defaultdict(list)
    for event in events:
        events_by_issue[event.issue].append(event)

    pending_claims: list[dict[str, Any]] = []
    broken_claims: list[dict[str, Any]] = []
    resolved_counts = {
        "accept": 0,
        "payment": 0,
        "reject": 0,
        "superseded": 0,
    }
    total_claims = 0

    for issue, issue_events in sorted(events_by_issue.items()):
        issue_mechanic = _infer_issue_mechanic(
            issue_events,
            existing=mechanics.get(issue),
        )
        issue_status = statuses.get(issue)
        multi_claim = _is_multi_claim_issue(issue_mechanic)

        for index, event in enumerate(issue_events):
            if event.type != "claim":
                continue

            total_claims += 1
            later_events = issue_events[index + 1 :]
            if multi_claim:
                outcome = _resolve_multi_claim(
                    event,
                    later_events,
                    mechanic=issue_mechanic,
                    issue_status=issue_status,
                )
            else:
                outcome = _resolve_single_claim(
                    event,
                    later_events,
                    mechanic=issue_mechanic,
                    issue_status=issue_status,
                )

            kind = outcome["kind"]
            if kind == "pending":
                pending_claims.append(outcome)
            elif kind == "broken":
                broken_claims.append(outcome)
            else:
                resolved_by = outcome["resolved_by"]
                key = "superseded" if resolved_by == "claim" else resolved_by
                resolved_counts[key] += 1

    status = "FAIL" if broken_claims else "PASS"

    if total_claims == 0:
        detail = "no claim events found in ledger/history"
    elif broken_claims:
        detail = (
            f"{len(broken_claims)} claim(s) have broken resolution chains; "
            f"{len(pending_claims)} claim(s) remain pending"
        )
    elif pending_claims:
        detail = (
            f"all closed claim chains resolve cleanly; "
            f"{len(pending_claims)} current claim(s) remain pending"
        )
    else:
        detail = "all claim events resolve cleanly"

    return {
        "status": status,
        "checks": [
            {
                "name": "claim_chain_integrity",
                "status": status,
                "detail": detail,
            }
        ],
        "summary": {
            "total_claim_events": total_claims,
            "resolved": sum(resolved_counts.values()),
            "resolved_by_accept": resolved_counts["accept"],
            "resolved_by_payment": resolved_counts["payment"],
            "resolved_by_reject": resolved_counts["reject"],
            "superseded": resolved_counts["superseded"],
            "pending": len(pending_claims),
            "broken": len(broken_claims),
        },
        "pending_claims": pending_claims,
        "broken_claims": broken_claims,
    }


def run_check(root: Path) -> dict[str, Any]:
    """Load repo data and return the claim-chain integrity report."""
    task_index = _load_optional_json(root / "ledger" / "task_index.json", default={"tasks": {}})
    escrows = _load_optional_json(root / "ledger" / "escrows.json", default={"active": {}})
    mechanics, statuses = _issue_metadata(task_index, escrows)
    events = load_relevant_events(root)
    return build_result(events, mechanics=mechanics, statuses=statuses)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that claim history resolves cleanly"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    try:
        result = run_check(_repo_root_from(args.root))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "status": "FAIL",
            "checks": [
                {
                    "name": "claim_chain_integrity",
                    "status": "FAIL",
                    "error": str(exc),
                }
            ],
            "summary": {
                "total_claim_events": 0,
                "resolved": 0,
                "resolved_by_accept": 0,
                "resolved_by_payment": 0,
                "resolved_by_reject": 0,
                "superseded": 0,
                "pending": 0,
                "broken": 0,
            },
            "pending_claims": [],
            "broken_claims": [],
        }
        print(json.dumps(result, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
