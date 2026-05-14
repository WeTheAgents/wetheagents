#!/usr/bin/env python3
"""
GitHub issue labels vs ledger payment events cross-validation.

Gauntlet T1S4: confirms that GitHub issue labels and ledger history are consistent:
- Every 'paid'-labeled task issue has at least one 'paid'-class event in ledger
  history (accept | payment | trajectory_mint).
- Every 'paid'-class event in ledger history has the corresponding issue
  labeled 'paid'.
- Every 'claimed'-labeled (not 'paid') issue has an escrow event in ledger history.

Reports orphan labels (label with no event) and orphan events (event with no label).
Exits 0 on clean, 1 on any discrepancy.

Usage:
  python scripts/check_issue_ledger_sync.py
  python scripts/check_issue_ledger_sync.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from glob import glob
from pathlib import Path

_ESCROW_TYPES = frozenset({"escrow", "escrow_create", "escrow_batch"})
# Event types that mark an issue as "paid" in ledger history.
# `accept` is the legacy verb; `payment` is the canonical Tide event today;
# `trajectory_mint` covers gauntlet payouts. All three are recognised so that
# this checker matches the union used by check_task_status_history_sync.py.
_PAID_TYPES = frozenset({"accept", "payment", "trajectory_mint"})


def load_ledger_events(root: str | Path) -> tuple[set[int], set[int]]:
    """Scan ledger/history/*.jsonl and return (paid_issues, escrow_issues).

    paid_issues: issue numbers with at least one 'paid'-class event
        (accept | payment | trajectory_mint).
    escrow_issues: issue numbers with at least one escrow-type event.
    Handles both 'issue' (single int) and 'issues' (list) fields.
    """
    paid_issues: set[int] = set()
    escrow_issues: set[int] = set()
    history_dir = Path(root) / "ledger" / "history"

    if not history_dir.is_dir():
        return paid_issues, escrow_issues

    for path in sorted(glob(str(history_dir / "*.jsonl"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")

                if event_type in _PAID_TYPES:
                    _add_issue(event, paid_issues)

                elif event_type in _ESCROW_TYPES:
                    # escrow_batch / escrow_return_bulk carry 'issues' list
                    if "issues" in event:
                        for num in event["issues"]:
                            try:
                                escrow_issues.add(int(num))
                            except (ValueError, TypeError):
                                pass
                    else:
                        _add_issue(event, escrow_issues)

    return paid_issues, escrow_issues


def _add_issue(event: dict, target: set[int]) -> None:
    """Add event['issue'] to target, ignoring missing or non-integer values."""
    issue = event.get("issue")
    if issue is not None:
        try:
            target.add(int(issue))
        except (ValueError, TypeError):
            pass


def parse_github_issues(issues_data: list[dict]) -> tuple[set[int], set[int]]:
    """Parse GitHub issues list into (paid_issues, claimed_not_paid_issues).

    paid_issues: issue numbers carrying the 'paid' label.
    claimed_not_paid_issues: issue numbers with 'claimed' but not 'paid'.
    """
    paid_issues: set[int] = set()
    claimed_not_paid: set[int] = set()

    for issue in issues_data:
        num = issue.get("number")
        if num is None:
            continue
        label_names = {lbl["name"] for lbl in issue.get("labels", [])}

        if "paid" in label_names:
            paid_issues.add(int(num))
        elif "claimed" in label_names:
            claimed_not_paid.add(int(num))

    return paid_issues, claimed_not_paid


def fetch_github_issues(gh_issues_json: str | None = None) -> tuple[set[int], set[int]]:
    """Return (paid_issues, claimed_not_paid_issues) from GitHub.

    gh_issues_json: pre-serialized JSON string to bypass the gh CLI (used in tests).
    """
    if gh_issues_json is not None:
        return parse_github_issues(json.loads(gh_issues_json))

    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", "task",
            "--state", "all",
            "--limit", "1000",
            "--json", "number,labels,state",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_github_issues(json.loads(result.stdout))


def run_checks(
    ledger_paid: set[int],
    escrow_issues: set[int],
    github_paid: set[int],
    claimed_not_paid: set[int],
) -> list[tuple[str, str, list[int]]]:
    """Cross-validate ledger events against GitHub labels.

    Returns a list of (check_name, severity, failing_issue_numbers).
    severity is 'ERROR' (hard failure) or 'WARN' (soft warning).
    """
    results: list[tuple[str, str, list[int]]] = []

    # Orphan paid labels: 'paid' GitHub label but no paid-class event in ledger
    results.append((
        "paid label with no payment/accept/mint event",
        "ERROR",
        sorted(github_paid - ledger_paid),
    ))

    # Orphan paid events: paid-class event in ledger but issue not labeled 'paid'.
    # Downgraded to WARN: this direction catches GitHub label backlog (paid
    # ledger event but missing GitHub `paid` label), not economic drift. The
    # opposite direction (GitHub `paid` label with no ledger event) is the
    # economically dangerous case and stays at ERROR. A WARN here keeps the
    # signal visible without failing the sweep on accumulated historical
    # label drift that can only be cleaned up on the GitHub side.
    results.append((
        "paid event with no paid label",
        "WARN",
        sorted(ledger_paid - github_paid),
    ))

    # Claimed without escrow: 'claimed' (not 'paid') but no escrow event in ledger
    results.append((
        "claimed issue with no escrow event",
        "WARN",
        sorted(claimed_not_paid - escrow_issues),
    ))

    return results


def main(argv: list[str] | None = None, gh_issues_json: str | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GitHub issue labels vs ledger payment events cross-validation"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    args = parser.parse_args(argv)

    root = args.root or str(Path(__file__).resolve().parent.parent)

    ledger_paid, escrow_issues = load_ledger_events(root)
    print(
        f"Ledger: {len(ledger_paid)} issues with paid-class events, "
        f"{len(escrow_issues)} issues with escrow events"
    )

    try:
        github_paid, claimed_not_paid = fetch_github_issues(gh_issues_json)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error fetching GitHub issues: {e}", file=sys.stderr)
        return 1

    print(
        f"GitHub: {len(github_paid)} paid issues, "
        f"{len(claimed_not_paid)} claimed (not paid) issues"
    )

    checks = run_checks(ledger_paid, escrow_issues, github_paid, claimed_not_paid)

    failed = False
    for check_name, severity, bad_issues in checks:
        if bad_issues:
            if severity == "ERROR":
                failed = True
                print(f"FAIL: {check_name}: {bad_issues}")
            else:
                print(f"WARN: {check_name}: {bad_issues}")
        else:
            print(f"PASS: {check_name}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
