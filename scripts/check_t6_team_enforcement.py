#!/usr/bin/env python3
"""T6 team-enforcement checker for WeTheAgents.

Verifies that every T6 (Red Team Gauntlet) mint recorded in
``ledger/trajectory_mints.json`` and ``ledger/history/*.jsonl`` was
credited exclusively to the authorized T6 agent (default: gemini-4@google).

The authorized agent is configurable via ``--authorized-agent`` so the rule
can adapt without code changes if Agent0 ever rotates the T6 seat.

Computation rules:
  - Scan ``trajectory_mints.json`` "mints" array; collect every entry where
    ``trajectory == "T6"``.
  - Scan every ``ledger/history/*.jsonl`` file in lexicographic order; collect
    every event where ``type == "trajectory_mint"`` and
    ``trajectory == "T6"``.
  - For each collected record, extract the credited agent(s). Handles both
    ``"agents": [...]`` (list) and ``"agent": "..."`` (singular) field forms.
  - If any credited agent is not the authorized agent → VIOLATION.
  - Non-T6 trajectories are never checked.

Exit codes:
    0 — PASS (all T6 mints credited to authorized agent only)
    1 — FAIL (one or more violations detected)

Output: JSON to stdout with fields: status, violations, summary,
        authorized_agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_T6_AGENT = "gemini-4@google"

# T6 holder rotation schedule. Each entry is (start_date, agent_id) and means
# "from start_date onward (inclusive), the only agent allowed to receive T6
# mints is agent_id" — until the next entry's start_date supersedes it.
#
# Documented rotations (see C:\Users\peach\.claude\projects\D--GitHub-wetheagents
# memory and docs/gauntlet.md):
#   - 2026-03-17: Gauntlet implementation day. T6 cycle 1 (slot 1, #301) was
#     filed against Claude-1 during bootstrapping, before the gemini-4 rule
#     was ratified. Slot 1 accepted 2026-03-26.
#   - 2026-03-27: gemini-4@google became the canonical T6 holder; slots 2..35
#     credited to gemini-4@google.
#   - 2026-04-29: After gemini-4 was deprecated 2026-04-23 for API-token cost,
#     the T6 seat was reassigned to Claude-6@claude. Slot 36 (#794) is the
#     first slot under the new holder.
T6_AUTHORIZATION_SCHEDULE: tuple[tuple[date, str], ...] = (
    (date(2026, 3, 27), "gemini-4@google"),
    (date(2026, 4, 29), "Claude-6@claude"),
)


def _authorized_at(when: date | None) -> str | None:
    """Return the T6 agent authorized at `when`, or None if pre-schedule.

    None means "no rule applies yet" — pre-policy bootstrapping period. Callers
    should treat that as grandfathered (skip the entry), since there was no
    documented holder to enforce against.
    """
    if when is None:
        return None
    authorized: str | None = None
    for start, agent in T6_AUTHORIZATION_SCHEDULE:
        if when >= start:
            authorized = agent
        else:
            break
    return authorized


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _extract_agents(record: dict[str, Any]) -> list[str]:
    """Return the list of credited agents from a mint record.

    Handles both the canonical ``"agents": [...]`` list form and the
    legacy ``"agent": "..."`` singular form found in some history events.
    Returns an empty list if neither field is present.
    """
    if "agents" in record and isinstance(record["agents"], list):
        return [str(a) for a in record["agents"]]
    if "agent" in record and isinstance(record["agent"], str):
        return [record["agent"]]
    return []


def _parse_date_prefix(ts: str) -> date | None:
    """Parse the date portion of an ISO-8601 timestamp string (YYYY-MM-DD...)."""
    try:
        return date.fromisoformat(ts[:10])
    except (ValueError, TypeError):
        return None


def _check_mints(
    mints: list[dict[str, Any]],
    authorized_agent: str,
    violations: list[dict[str, Any]],
    since: date | None = None,
    use_schedule: bool = False,
) -> None:
    """Check trajectory_mints.json entries for T6 team violations.

    When ``use_schedule`` is True, the authorized agent at each mint is
    determined by ``T6_AUTHORIZATION_SCHEDULE`` keyed on ``accepted_at``.
    Mints with no parseable ``accepted_at`` or with an ``accepted_at`` before
    the first scheduled entry are grandfathered (skipped).
    """
    for record in mints:
        if record.get("trajectory") != "T6":
            continue
        # Prefer accepted_at; fall back to timestamp before treating as undated.
        # T6 slot 15 (and any future mint written through a code path that only
        # records `timestamp`) would otherwise classify as pre-policy and bypass
        # the rotation schedule. The fallback ensures the rule still applies.
        when = _parse_date_prefix(record.get("accepted_at", ""))
        if when is None:
            when = _parse_date_prefix(record.get("timestamp", ""))
        if since is not None:
            if when is None or when < since:
                continue
        effective_agent = authorized_agent
        if use_schedule:
            scheduled = _authorized_at(when)
            if scheduled is None:
                # Pre-schedule (or undated) — grandfather; the policy did not
                # apply yet at that point.
                continue
            effective_agent = scheduled
        agents = _extract_agents(record)
        bad = [a for a in agents if a != effective_agent]
        if bad:
            violations.append(
                {
                    "source": "trajectory_mints",
                    "trajectory": "T6",
                    "slot": record.get("slot"),
                    "issue": record.get("issue_or_pr"),
                    "actual_agents": agents,
                    "unauthorized_agents": bad,
                    "authorized_agent": effective_agent,
                }
            )
        elif not agents:
            # Empty or absent agent field — treat as violation (unattributed mint).
            violations.append(
                {
                    "source": "trajectory_mints",
                    "trajectory": "T6",
                    "slot": record.get("slot"),
                    "issue": record.get("issue_or_pr"),
                    "actual_agents": [],
                    "unauthorized_agents": [],
                    "authorized_agent": effective_agent,
                    "detail": "no agents credited in mint record",
                }
            )


def _iter_history_events(history_dir: Path):
    """Yield parsed events from all .jsonl files in lexicographic order."""
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"WARNING: skipping malformed JSON in "
                        f"{jsonl_file.name}:{lineno}: {exc}",
                        file=sys.stderr,
                    )


def _check_history(
    events,
    authorized_agent: str,
    violations: list[dict[str, Any]],
    since: date | None = None,
    use_schedule: bool = False,
) -> None:
    """Check history event stream for T6 trajectory_mint violations.

    Schedule resolution mirrors ``_check_mints``: when ``use_schedule`` is
    True, the per-event authorized agent is looked up from
    ``T6_AUTHORIZATION_SCHEDULE`` via the event's ``timestamp``.
    """
    for event in events:
        if event.get("type") != "trajectory_mint":
            continue
        if event.get("trajectory") != "T6":
            continue
        ts = _parse_date_prefix(event.get("timestamp", ""))
        if since is not None:
            if ts is None or ts < since:
                continue
        effective_agent = authorized_agent
        if use_schedule:
            scheduled = _authorized_at(ts)
            if scheduled is None:
                continue
            effective_agent = scheduled
        agents = _extract_agents(event)
        bad = [a for a in agents if a != effective_agent]
        if bad:
            violations.append(
                {
                    "source": "history",
                    "trajectory": "T6",
                    "slot": event.get("slot"),
                    "issue": event.get("issue"),
                    "actual_agents": agents,
                    "unauthorized_agents": bad,
                    "authorized_agent": effective_agent,
                }
            )
        elif not agents:
            violations.append(
                {
                    "source": "history",
                    "trajectory": "T6",
                    "slot": event.get("slot"),
                    "issue": event.get("issue"),
                    "actual_agents": [],
                    "unauthorized_agents": [],
                    "authorized_agent": effective_agent,
                    "detail": "no agents credited in history event",
                }
            )


def run_check(
    root: Path,
    *,
    mints: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    authorized_agent: str = DEFAULT_T6_AGENT,
    since: date | None = None,
    use_schedule: bool = False,
) -> dict[str, Any]:
    """Run the T6 team-enforcement check and return the report.

    Parameters
    ----------
    root:
        Repository root directory.
    mints:
        Override the trajectory_mints.json "mints" array (used by tests to
        inject synthetic data without touching the filesystem).
    events:
        Override the history event stream (used by tests to inject synthetic
        data without touching the filesystem).
    authorized_agent:
        The only agent allowed to receive T6 mints.
    since:
        If provided, only enforce for T6 entries on or after this date.
        Entries with ``accepted_at`` / ``timestamp`` before this date are
        silently skipped (grandfathered).

    Returns
    -------
    dict with keys: status, violations, summary, authorized_agent.
    """
    violations: list[dict[str, Any]] = []

    # --- trajectory_mints.json ---
    if mints is None:
        mints_path = root / "ledger" / "trajectory_mints.json"
        if not mints_path.is_file():
            print(
                f"ERROR: trajectory_mints.json not found: {mints_path}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            with open(mints_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            print(
                f"ERROR: invalid JSON in trajectory_mints.json: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        mints = data.get("mints", [])

    assert mints is not None  # assigned or sys.exit() called above
    _check_mints(mints, authorized_agent, violations, since=since, use_schedule=use_schedule)

    # --- ledger/history/*.jsonl ---
    if events is None:
        history_dir = root / "ledger" / "history"
        if not history_dir.is_dir():
            print(
                f"ERROR: history directory not found: {history_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        event_stream = _iter_history_events(history_dir)
    else:
        event_stream = iter(events)

    _check_history(event_stream, authorized_agent, violations, since=since, use_schedule=use_schedule)

    status = "FAIL" if violations else "PASS"
    if use_schedule:
        clean_desc = "all T6 mints match the authorization schedule"
    else:
        clean_desc = "all T6 mints credited to " + authorized_agent
    summary = (
        f"{len(violations)} violation(s) — "
        f"{clean_desc if not violations else 'unauthorized T6 agent(s) detected'}"
    )

    return {
        "status": status,
        "violations": violations,
        "summary": summary,
        "authorized_agent": "<schedule>" if use_schedule else authorized_agent,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every T6 (Red Team Gauntlet) mint was credited "
            "exclusively to the authorized T6 agent"
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (auto-detected from script location if omitted)",
    )
    parser.add_argument(
        "--authorized-agent",
        default=None,
        help=(
            "Override the per-mint authorized T6 agent (singular). If not "
            "supplied, the rotation schedule in T6_AUTHORIZATION_SCHEDULE is "
            "used: gemini-4@google from 2026-03-27, Claude-6@claude from "
            "2026-04-29. Mints before the first scheduled entry are "
            "grandfathered."
        ),
    )
    parser.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Only enforce T6 team rules for mints on or after this date "
            "(ISO format). Entries before this date are grandfathered and skipped."
        ),
    )
    args = parser.parse_args(argv)

    since: date | None = None
    if args.since is not None:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(
                f"ERROR: --since value '{args.since}' is not a valid YYYY-MM-DD date.",
                file=sys.stderr,
            )
            return 1

    root = _repo_root_from(args.root)
    if args.authorized_agent is None:
        result = run_check(root, since=since, use_schedule=True)
    else:
        result = run_check(
            root, authorized_agent=args.authorized_agent, since=since
        )
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
