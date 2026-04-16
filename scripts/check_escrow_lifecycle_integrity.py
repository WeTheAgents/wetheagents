#!/usr/bin/env python3
"""Escrow lifecycle integrity checker for WeTheAgents.

Verifies that every `escrow` event in ledger/history/*.jsonl has a
corresponding resolution: either a `payment` event or an `escrow_return`
event (including bulk returns) for the same issue.

Escrows paid via trajectory minting (gauntlet) without a matching
`escrow_return` are flagged as FAIL — these are the "orphan escrows"
that previously required manual cleanup (issues #411, #423).

Cross-check logic:
  - resolved   : escrow issue has payment OR escrow_return in history
  - pending    : escrow issue is active in escrows.json (legitimately open)
  - orphan     : trajectory_mint exists for the issue but no escrow_return
                 and the issue is not in escrows.json active — FAIL
  - unresolved : no resolution, no trajectory_mint, not in active — WARN

Exit codes:
    0 — PASS (no orphan escrows detected)
    1 — FAIL (one or more orphan escrows found)
    2 — ERROR (missing files, malformed JSON)

Output: JSON to stdout with `status`, `checks`, `summary` fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_events(history_dir: Path):
    """Yield (filename, event_dict) for every event in all .jsonl files.

    Skips blank lines and logs parse errors to stderr without crashing.
    """
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
                        f"WARNING: skipping malformed JSON in "
                        f"{jsonl_file.name}:{lineno}: {exc}",
                        file=sys.stderr,
                    )


def collect_events(history_dir: Path) -> dict[str, Any]:
    """Scan all .jsonl history files and collect lifecycle event sets.

    Returns a dict with keys:
      escrow_events       : dict[int, dict]  issue → representative escrow event
      escrow_counts       : dict[int, int]   issue → total escrow event count
      payment_counts      : dict[int, int]   issue → payment event count
      return_counts       : dict[int, int]   issue → return event count
                                             (escrow_return + escrow_return_bulk)
      trajectory_issues   : set[int]         trajectory_mint
    """
    escrow_events: dict[int, dict] = {}
    escrow_counts: dict[int, int] = {}
    payment_counts: dict[int, int] = {}
    return_counts: dict[int, int] = {}
    trajectory_issues: set[int] = set()

    for _filename, event in _iter_events(history_dir):
        etype = event.get("type", "")

        # Single-issue events
        raw_issue = event.get("issue")
        if raw_issue is not None:
            try:
                issue_num = int(raw_issue)
            except (ValueError, TypeError):
                continue

            if etype == "escrow":
                # Keep first-seen escrow event per issue for reporting
                if issue_num not in escrow_events:
                    escrow_events[issue_num] = event
                escrow_counts[issue_num] = escrow_counts.get(issue_num, 0) + 1
            elif etype == "payment":
                payment_counts[issue_num] = payment_counts.get(issue_num, 0) + 1
            elif etype == "escrow_return":
                return_counts[issue_num] = return_counts.get(issue_num, 0) + 1
            elif etype == "trajectory_mint":
                trajectory_issues.add(issue_num)

        # Multi-issue bulk events (escrow_return_bulk)
        if etype == "escrow_return_bulk":
            for raw_i in event.get("issues", []):
                try:
                    i = int(raw_i)
                    return_counts[i] = return_counts.get(i, 0) + 1
                except (ValueError, TypeError):
                    pass

    return {
        "escrow_events": escrow_events,
        "escrow_counts": escrow_counts,
        "payment_counts": payment_counts,
        "return_counts": return_counts,
        "trajectory_issues": trajectory_issues,
    }


def classify_escrows(
    events: dict[str, Any],
    active_issues: set[int],
) -> dict[str, Any]:
    """Classify each escrowed issue into lifecycle categories.

    Categories:
      resolved   — has payment OR escrow_return in history (count-matched)
      pending    — in escrows.json active (legitimately open)
      orphan     — trajectory_mint exists but escrow unresolved, not pending
      unresolved — no resolution, no trajectory_mint, not pending (pre-history gap)

    Resolution is count-aware: if an issue has N escrow events and M resolution
    events (payment + escrow_return), M escrows are resolved and N-M remain
    unresolved. This detects the case where a second escrow is created after
    the first is resolved (previously a false PASS due to first-seen-only logic).

    Returns a dict with category lists and counts.
    """
    escrow_events = events["escrow_events"]
    escrow_counts = events["escrow_counts"]
    payment_counts = events["payment_counts"]
    return_counts = events["return_counts"]
    trajectory_issues = events["trajectory_issues"]

    resolved: list[dict] = []
    pending: list[dict] = []
    orphan: list[dict] = []
    unresolved: list[dict] = []

    for issue_num in sorted(escrow_events):
        ev = escrow_events[issue_num]
        entry = {
            "issue": issue_num,
            "amount": ev.get("amount"),
            "agent": ev.get("agent") or ev.get("author"),
        }

        total_escrows = escrow_counts.get(issue_num, 1)
        total_resolutions = (
            payment_counts.get(issue_num, 0) + return_counts.get(issue_num, 0)
        )
        resolved_count = min(total_escrows, total_resolutions)
        unresolved_remaining = total_escrows - resolved_count

        for _ in range(resolved_count):
            resolved.append(entry)

        is_pending = issue_num in active_issues
        is_gauntlet_paid = issue_num in trajectory_issues
        for _ in range(unresolved_remaining):
            if is_pending:
                pending.append(entry)
            elif is_gauntlet_paid:
                # trajectory_mint happened but escrow not returned — orphan
                orphan.append(entry)
            else:
                # No evidence of resolution in history; likely pre-history era
                unresolved.append(entry)

    return {
        "resolved": resolved,
        "pending": pending,
        "orphan_escrows": orphan,
        "unresolved_escrows": unresolved,
    }


def build_result(classified: dict[str, Any]) -> dict[str, Any]:
    """Build the final JSON report from classified escrow categories."""
    has_orphans = bool(classified["orphan_escrows"])
    status = "FAIL" if has_orphans else "PASS"

    orphan_count = len(classified["orphan_escrows"])
    unresolved_count = len(classified["unresolved_escrows"])

    if has_orphans:
        check_detail = (
            f"{orphan_count} gauntlet orphan(s) detected — "
            "trajectory_mint exists but escrow was not returned"
        )
    elif unresolved_count:
        check_detail = (
            f"PASS — {unresolved_count} pre-history unresolved escrow(s) noted (WARN)"
        )
    else:
        check_detail = "all escrow events have a corresponding resolution"

    total = (
        len(classified["resolved"])
        + len(classified["pending"])
        + orphan_count
        + unresolved_count
    )

    return {
        "status": status,
        "checks": [
            {
                "name": "escrow_lifecycle_integrity",
                "status": status,
                "detail": check_detail,
            }
        ],
        "summary": {
            "total_escrow_events": total,
            "resolved": len(classified["resolved"]),
            "pending": len(classified["pending"]),
            "orphan_escrows": orphan_count,
            "unresolved_escrows": unresolved_count,
        },
        "orphan_escrows": classified["orphan_escrows"],
        "unresolved_escrows": classified["unresolved_escrows"],
    }


def run_check(root: Path) -> dict[str, Any]:
    """Load ledger files, classify escrows, and return the result dict."""
    history_dir = root / "ledger" / "history"
    if not history_dir.is_dir():
        print(f"ERROR: history directory not found: {history_dir}", file=sys.stderr)
        sys.exit(2)

    escrows_path = root / "ledger" / "escrows.json"
    if not escrows_path.exists():
        print(f"ERROR: escrows.json not found: {escrows_path}", file=sys.stderr)
        sys.exit(2)

    raw_escrows = json.loads(escrows_path.read_text(encoding="utf-8-sig"))
    active_issues: set[int] = set()
    for key in raw_escrows.get("active", {}):
        try:
            active_issues.add(int(key))
        except (ValueError, TypeError):
            pass

    events = collect_events(history_dir)
    classified = classify_escrows(events, active_issues)
    return build_result(classified)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every escrow event has a lifecycle resolution"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (auto-detected from script location if omitted)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON (default: human-readable)",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)
    result = run_check(root)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = result["status"]
        summary = result["summary"]
        print(f"{status}: escrow lifecycle integrity")
        print(
            f"  total={summary['total_escrow_events']} "
            f"resolved={summary['resolved']} "
            f"pending={summary['pending']} "
            f"orphans={summary['orphan_escrows']} "
            f"unresolved={summary['unresolved_escrows']}"
        )
        for orphan in result.get("orphan_escrows", []):
            print(f"  ORPHAN issue #{orphan['issue']}: {orphan['amount']} WEA")
        if result.get("unresolved_escrows"):
            print(
                f"  WARN: {len(result['unresolved_escrows'])} pre-history "
                "escrow(s) have no resolution record"
            )

    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
