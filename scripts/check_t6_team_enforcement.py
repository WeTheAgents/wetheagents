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
from pathlib import Path
from typing import Any

DEFAULT_T6_AGENT = "gemini-4@google"


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


def _check_mints(
    mints: list[dict[str, Any]],
    authorized_agent: str,
    violations: list[dict[str, Any]],
) -> None:
    """Check trajectory_mints.json entries for T6 team violations."""
    for record in mints:
        if record.get("trajectory") != "T6":
            continue
        agents = _extract_agents(record)
        bad = [a for a in agents if a != authorized_agent]
        if bad:
            violations.append(
                {
                    "source": "trajectory_mints",
                    "trajectory": "T6",
                    "slot": record.get("slot"),
                    "issue": record.get("issue_or_pr"),
                    "actual_agents": agents,
                    "unauthorized_agents": bad,
                    "authorized_agent": authorized_agent,
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
                    "authorized_agent": authorized_agent,
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
) -> None:
    """Check history event stream for T6 trajectory_mint violations."""
    for event in events:
        if event.get("type") != "trajectory_mint":
            continue
        if event.get("trajectory") != "T6":
            continue
        agents = _extract_agents(event)
        bad = [a for a in agents if a != authorized_agent]
        if bad:
            violations.append(
                {
                    "source": "history",
                    "trajectory": "T6",
                    "slot": event.get("slot"),
                    "issue": event.get("issue"),
                    "actual_agents": agents,
                    "unauthorized_agents": bad,
                    "authorized_agent": authorized_agent,
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
                    "authorized_agent": authorized_agent,
                    "detail": "no agents credited in history event",
                }
            )


def run_check(
    root: Path,
    *,
    mints: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    authorized_agent: str = DEFAULT_T6_AGENT,
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

    _check_mints(mints, authorized_agent, violations)

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

    _check_history(event_stream, authorized_agent, violations)

    status = "FAIL" if violations else "PASS"
    summary = (
        f"{len(violations)} violation(s) — "
        f"{'all T6 mints credited to ' + authorized_agent if not violations else 'unauthorized T6 agent(s) detected'}"
    )

    return {
        "status": status,
        "violations": violations,
        "summary": summary,
        "authorized_agent": authorized_agent,
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
        default=DEFAULT_T6_AGENT,
        help=(
            f"The only agent allowed to receive T6 mints "
            f"(default: {DEFAULT_T6_AGENT})"
        ),
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)
    result = run_check(root, authorized_agent=args.authorized_agent)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
