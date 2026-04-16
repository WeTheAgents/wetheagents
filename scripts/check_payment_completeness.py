#!/usr/bin/env python3
"""Payment completeness checker for the WeTheAgents ledger.

Scans ledger/history/*.jsonl for verification events (type==verification) and
confirms that each has a corresponding payment event (type==payment, same
issue, same agent) anywhere in the history.

Rules:
  - every_good mechanic: multiple payments per issue are valid (one per agent).
  - Verifications for rejected work (issue was never escrowed) are skipped.
  - Exits non-zero if any gaps are found; reports each gap to stdout.

Usage:
    python scripts/check_payment_completeness.py [--root PATH]

Exit codes:
    0 — all verifications have matching payments (or are for rejected work)
    1 — one or more gaps found
    2 — error (missing files, malformed JSON)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _iter_events(history_dir: Path):
    """Yield (filename, event_dict) for every event in all .jsonl files."""
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield jsonl_file.name, json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"WARNING: skipping malformed JSON in {jsonl_file.name}:{lineno}: {exc}",
                        file=sys.stderr,
                    )


def check_payment_completeness(root: Path) -> list[dict]:
    """Scan history and return a list of gap dicts.

    Each gap dict has keys: issue, agent, verification_file.
    An empty list means all verifications are complete.
    """
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        print(f"ERROR: history directory not found: {history_dir}", file=sys.stderr)
        sys.exit(2)

    # Pass 1: collect all events by type.
    verifications: list[dict] = []   # {issue, agent, file}
    payments: set[tuple] = set()     # (issue, agent)
    escrowed_issues: set[int] = set()

    escrow_types = {"escrow", "escrow_create", "escrow_batch"}

    for filename, event in _iter_events(history_dir):
        etype = event.get("type")

        if etype == "verification":
            issue = event.get("issue")
            agent = event.get("agent")
            if issue is not None and agent is not None:
                try:
                    verifications.append({
                        "issue": int(issue),
                        "agent": str(agent),
                        "file": filename,
                    })
                except (ValueError, TypeError):
                    pass  # skip events with non-numeric issue IDs

        elif etype == "payment":
            issue = event.get("issue")
            agent = event.get("agent")
            if issue is not None and agent is not None:
                try:
                    payments.add((int(issue), str(agent)))
                except (ValueError, TypeError):
                    pass

        elif etype in escrow_types:
            # escrow_batch lists multiple issues
            if etype == "escrow_batch":
                for iss in event.get("issues", []):
                    try:
                        escrowed_issues.add(int(iss))
                    except (ValueError, TypeError):
                        pass
            else:
                issue = event.get("issue")
                if issue is not None:
                    try:
                        escrowed_issues.add(int(issue))
                    except (ValueError, TypeError):
                        pass

    # Pass 2: find gaps.
    gaps: list[dict] = []
    for v in verifications:
        issue, agent = v["issue"], v["agent"]

        # Rejected work: issue was never escrowed — skip.
        if issue not in escrowed_issues:
            continue

        # Gap: escrowed issue has verification but no payment.
        if (issue, agent) not in payments:
            gaps.append(v)

    return gaps


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Check that every verified submission has a corresponding payment"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root,
        help="Repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    gaps = check_payment_completeness(root)

    if not gaps:
        print("OK: all verifications have corresponding payments.")
        return 0

    print(f"FAIL: {len(gaps)} verification(s) missing payment:")
    for g in gaps:
        print(f"  issue #{g['issue']}, agent {g['agent']}  (found in {g['file']})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
