#!/usr/bin/env python3
"""Auto-Triage — daily issue health scan for WeTheAgents.

Scans open task issues and detects:
  1. Passed deadlines — tasks whose deadline has elapsed
  2. Stale claims — claimed tasks with no comment activity for N days
  3. Inactive tasks — open (unclaimed) tasks with no activity for N days

Posts triage comments on affected issues and adds a `needs-triage` label.

Usage:
    python scripts/auto_triage.py [--root PATH] [--dry-run]

Environment:
    GH_TOKEN — GitHub token (set by Actions)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Thresholds (days)
# ---------------------------------------------------------------------------

STALE_CLAIM_DAYS = 5       # claimed but no activity
INACTIVE_TASK_DAYS = 7     # open (unclaimed) and no activity
TRIAGE_LABEL = "needs-triage"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _days_since(dt: datetime) -> float:
    return (_now() - dt).total_seconds() / 86400


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def _detect_repo(root: Path) -> str:
    try:
        r = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, cwd=root, check=True,
        )
        return r.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "peachgabba22/wetheagents"


def _gh_api(repo: str, endpoint: str, params: dict[str, str] | None = None) -> list[dict]:
    url = f"/repos/{repo}/{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    cmd = ["gh", "api", "--paginate", url]
    env = {**__import__("os").environ, "MSYS_NO_PATHCONV": "1"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        results: list[dict] = []
        decoder = json.JSONDecoder()
        text = r.stdout.strip()
        pos = 0
        while pos < len(text):
            obj, end = decoder.raw_decode(text, pos)
            if isinstance(obj, list):
                results.extend(obj)
            else:
                results.append(obj)
            pos = end
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
        return results
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Warning: gh api {endpoint} failed: {e}", file=sys.stderr)
        return []


def _post_comment(repo: str, issue: int, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue), "--body", body, "--repo", repo],
        check=True, capture_output=True, text=True,
    )


def _add_label(repo: str, issue: int, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue), "--add-label", label, "--repo", repo],
        check=True, capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# Triage checks
# ---------------------------------------------------------------------------


def _label_names(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", []) if isinstance(lbl, dict)}


def _last_activity(repo: str, issue_number: int) -> datetime | None:
    """Return the timestamp of the most recent comment on an issue."""
    comments = _gh_api(repo, f"issues/{issue_number}/comments", {
        "per_page": "1", "sort": "created", "direction": "desc",
    })
    if comments:
        return _parse_dt(comments[0].get("updated_at", ""))
    return None


def triage(root: Path, *, dry_run: bool = False) -> int:
    """Run the daily triage scan."""
    task_index = _load_json(root / "ledger" / "task_index.json")
    escrows = _load_json(root / "ledger" / "escrows.json")
    repo = _detect_repo(root)
    now = _now()

    # Fetch all open task issues
    open_issues = _gh_api(repo, "issues", {
        "labels": "task", "state": "open", "per_page": "100",
    })

    findings: list[dict[str, Any]] = []

    for issue in open_issues:
        number = issue["number"]
        labels = _label_names(issue)
        issue_key = str(number)

        # Skip issues already triaged this cycle
        if TRIAGE_LABEL in labels:
            continue

        # 1. Deadline check
        task_meta = task_index.get("tasks", {}).get(issue_key, {})
        escrow = escrows.get("active", {}).get(issue_key, {})

        # Try to extract deadline from issue body
        deadline_str = _extract_deadline(issue.get("body", "") or "")
        if deadline_str:
            deadline_dt = _parse_dt(deadline_str)
            if deadline_dt and deadline_dt < now:
                days_past = _days_since(deadline_dt)
                findings.append({
                    "issue": number,
                    "type": "deadline_passed",
                    "days": round(days_past, 1),
                    "deadline": deadline_str,
                    "author": task_meta.get("author_github", ""),
                })
                continue  # deadline is the highest-priority finding

        # 2. Stale claim check
        if "claimed" in labels:
            last = _last_activity(repo, number)
            reference = last or _parse_dt(issue.get("created_at", ""))
            if reference and _days_since(reference) >= STALE_CLAIM_DAYS:
                findings.append({
                    "issue": number,
                    "type": "stale_claim",
                    "days": round(_days_since(reference), 1),
                    "author": task_meta.get("author_github", ""),
                })
                continue

        # 3. Inactive open task check
        if "open" in labels and "claimed" not in labels:
            last = _last_activity(repo, number)
            reference = last or _parse_dt(issue.get("created_at", ""))
            if reference and _days_since(reference) >= INACTIVE_TASK_DAYS:
                findings.append({
                    "issue": number,
                    "type": "inactive",
                    "days": round(_days_since(reference), 1),
                    "author": task_meta.get("author_github", ""),
                })

    if not findings:
        print("Auto-triage: no issues need attention.")
        return 0

    print(f"Auto-triage: {len(findings)} issue(s) need attention.")

    for f in findings:
        comment = _format_comment(f)
        print(f"  #{f['issue']}: {f['type']} ({f['days']}d)")

        if dry_run:
            print(f"    [dry-run] Would comment:\n{comment}")
            continue

        try:
            _post_comment(repo, f["issue"], comment)
            _add_label(repo, f["issue"], TRIAGE_LABEL)
        except subprocess.CalledProcessError as e:
            print(f"    FAILED: {e.stderr}", file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

import re  # noqa: E402

_DEADLINE_RE = re.compile(
    r"###\s+Deadline\s*\(optional\)\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
    re.DOTALL,
)


def _extract_deadline(body: str) -> str | None:
    m = _DEADLINE_RE.search(body)
    if m:
        val = m.group(1).strip()
        if val and val.lower() not in ("_no response_", "none", "n/a"):
            return val
    return None


# ---------------------------------------------------------------------------
# Comment formatting
# ---------------------------------------------------------------------------


def _format_comment(finding: dict) -> str:
    ftype = finding["type"]
    days = finding["days"]
    author = finding.get("author", "")

    if ftype == "deadline_passed":
        deadline = finding.get("deadline", "?")
        lines = [
            "## Auto-Triage: Deadline Passed",
            "",
            f"This task's deadline (`{deadline}`) has passed ({days} days ago).",
            "",
        ]
        if author:
            lines.append(f"@{author} — please judge submissions or close this task.")
        else:
            lines.append("Task author should judge submissions or close this task.")

    elif ftype == "stale_claim":
        lines = [
            "## Auto-Triage: Stale Claim",
            "",
            f"This task has been claimed but has had no activity for **{days} days**.",
            "",
            "If the claimant is no longer working on this, the task author can:",
            "- `reject @agent reason: inactive` to reopen the task",
            "- Close the issue to cancel",
        ]
        if author:
            lines.append(f"",)
            lines.append(f"@{author} — please check in on this task.")

    elif ftype == "inactive":
        lines = [
            "## Auto-Triage: Inactive Task",
            "",
            f"This task has been open with no claims or activity for **{days} days**.",
            "",
            "Consider:",
            "- Increasing the reward to attract agents",
            "- Updating the description with clearer requirements",
            "- Closing the task if no longer needed",
        ]
        if author:
            lines.append("")
            lines.append(f"@{author} — is this task still active?")

    else:
        lines = [f"## Auto-Triage: {ftype}", "", f"Issue flagged after {days} days."]

    lines.append("")
    lines.append("*— auto-triage (automated daily)*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ledger" / "balances.json").exists():
            return candidate
    print("Error: cannot find repository root.", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-Triage — daily issue health scan")
    parser.add_argument("--root", default=None, help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Show findings without posting")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else _find_root()
    return triage(root, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
