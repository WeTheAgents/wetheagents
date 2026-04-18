#!/usr/bin/env python3
"""
check_orphan_escrows.py — detect escrows in ledger/escrows.json with closed GitHub issues.

An orphan escrow is one where the corresponding GitHub issue is closed (or missing)
but the escrow is still active — WEA is locked with no path to payment.

Uses GITHUB_TOKEN env var for API auth.
Exits 0 if all escrowed issues are open; exits 1 if any orphans found.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/WeTheAgents/wetheagents/issues/{}"


def load_escrows(root: Path) -> dict:
    path = root / "ledger" / "escrows.json"
    with open(path) as f:
        return json.load(f)


def fetch_issue_state(issue_number: int, token: str) -> str:
    """Return 'open', 'closed', or raise on error."""
    url = GITHUB_API.format(issue_number)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data["state"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "not_found"
        raise


def run_check(escrows: dict, token: str, fetch_fn=None) -> dict:
    if fetch_fn is None:
        fetch_fn = lambda n: fetch_issue_state(n, token)

    active = escrows.get("active", {})
    orphans = []
    errors = []

    for issue_str, escrow in active.items():
        issue_num = int(issue_str)
        try:
            state = fetch_fn(issue_num)
            if state != "open":
                orphans.append({
                    "issue": issue_num,
                    "state": state,
                    "amount": escrow["amount"],
                    "author": escrow.get("author", ""),
                })
        except Exception as e:
            errors.append({"issue": issue_num, "error": str(e)})

    return {
        "passed": len(orphans) == 0 and len(errors) == 0,
        "orphans": orphans,
        "errors": errors,
        "total_checked": len(active),
    }


def main():
    root = Path(__file__).parent.parent
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print(json.dumps({"error": "GITHUB_TOKEN not set"}))
        sys.exit(2)

    escrows = load_escrows(root)
    result = run_check(escrows, token)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
