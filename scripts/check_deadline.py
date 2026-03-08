"""Detect open task issues that have passed their declared deadline."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime


_DEADLINE_PATTERN = re.compile(
    r"###\s+Deadline(?:\s+\(optional\))?\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
    re.DOTALL,
)


def parse_deadline(body: str) -> str | None:
    m = _DEADLINE_PATTERN.search(body)
    if not m:
        return None
    val = m.group(1).strip()
    if not val or val.lower() in ("_no response_", "none"):
        return None
    return val


def load_issues(json_file: str | None) -> list[dict]:
    if json_file:
        with open(json_file) as f:
            return json.load(f)
    result = subprocess.run(
        ["gh", "issue", "list", "--label", "task,open", "--state", "open",
         "--json", "number,title,body", "--limit", "200"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def check_deadlines(issues: list[dict], as_of: date) -> list[dict]:
    overdue = []
    for issue in issues:
        body = issue.get("body") or ""
        deadline_str = parse_deadline(body)
        if not deadline_str:
            continue
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if deadline < as_of:
            days = (as_of - deadline).days
            overdue.append({
                "issue": issue["number"],
                "title": issue["title"],
                "deadline": deadline_str,
                "days_overdue": days,
            })
    return overdue


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect overdue task issues.")
    parser.add_argument("--json-file", help="Path to JSON file with issue data (for testing).")
    parser.add_argument("--as-of", help="Reference date YYYY-MM-DD (default: today).")
    args = parser.parse_args()

    if args.as_of:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    else:
        as_of = date.today()

    issues = load_issues(args.json_file)
    overdue = check_deadlines(issues, as_of)
    print(json.dumps(overdue, indent=2))
    return 1 if overdue else 0


if __name__ == "__main__":
    sys.exit(main())
