"""`wea report` — Agent0 orchestrator report: system state after Tide."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wea_cli.gh import search_issues_with_comments
from wea_cli.issue_helpers import (
    comment_author,
    comment_body,
    comment_created,
    issue_comments,
    issue_labels,
    parse_iso,
)
from wea_cli.parsers import parse_task_metadata

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT0_ID = "agent0@system"

# Comment patterns
CLAIM_RE_PATTERN = r"^\s*claim\b"
WORK_RE_PATTERN = r"^##\s*work\b"
PR_LINK_RE_PATTERN = r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+"
ACCEPT_KW = {"accept", "accepted", "approved", "merged", "paid", "payout"}
REJECT_KW = {"reject", "rejected", "declined", "changes requested", "needs changes"}

import re

CLAIM_RE = re.compile(CLAIM_RE_PATTERN, re.IGNORECASE)
WORK_RE = re.compile(WORK_RE_PATTERN, re.IGNORECASE | re.MULTILINE)
PR_LINK_RE = re.compile(PR_LINK_RE_PATTERN, re.IGNORECASE)
ACCEPT_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in ACCEPT_KW) + r")\b", re.IGNORECASE)
REJECT_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in REJECT_KW) + r")\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------




def _days_ago(dt: datetime, now: datetime) -> int:
    delta = now - dt
    return max(0, delta.days)


# ---------------------------------------------------------------------------
# Section 1: Tide Summary
# ---------------------------------------------------------------------------


def build_tide_summary(root: Path) -> dict[str, Any]:
    """Read tide.json and today's history for Tide summary."""
    tide_path = root / "ledger" / "tide.json"
    tide = {}
    if tide_path.exists():
        try:
            tide = json.loads(tide_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass

    last_tide = tide.get("last_tide", "unknown")
    halted = tide.get("halted_at") is not None
    halt_reason = tide.get("halt_reason")

    # Count today's history events
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = root / "ledger" / "history" / f"{today_str}.jsonl"
    events_today: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8-sig").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events_today.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    event_counts: dict[str, int] = {}
    for ev in events_today:
        ev_type = ev.get("type", "unknown")
        event_counts[ev_type] = event_counts.get(ev_type, 0) + 1

    return {
        "last_tide": last_tide,
        "halted": halted,
        "halt_reason": halt_reason,
        "events_today": event_counts,
        "total_events_today": len(events_today),
    }


# ---------------------------------------------------------------------------
# Section 2: Inbox — Items Needing Agent0 Action
# ---------------------------------------------------------------------------


AGENT_SECTION_RE = re.compile(r"^##\s*Agent\s*\n+([^\n]+)", re.MULTILINE)
TASK_REF_RE = re.compile(r"\[Task\s*#(\d+)\]", re.IGNORECASE)


def _extract_agent_from_body(body: str) -> str | None:
    """Extract agent ID from ## Agent section in a comment."""
    match = AGENT_SECTION_RE.search(body)
    if match:
        return match.group(1).strip()
    return None


def _is_agent0_authored(body: str) -> bool:
    """Check if a comment was authored by agent0 (even if posted from same GitHub account).

    Agent0 comments typically: accept/reject, escrow confirmations, task validations.
    Agent submissions have ## Work + ## Agent sections with non-agent0 IDs.
    """
    agent = _extract_agent_from_body(body)
    if agent and agent != AGENT0_ID:
        return False
    # Escrow/acceptance confirmations by agent0
    if "escrowed from" in body.lower() or "task validated" in body.lower():
        return True
    # Accept/reject markers
    if ACCEPT_RE.search(body) or REJECT_RE.search(body):
        return True
    return True  # Default: if no ## Agent section, assume agent0


def _list_open_prs(repo: str) -> list[dict[str, Any]]:
    """Fetch open PRs with task reference info."""
    from wea_cli.gh import run_gh_json

    try:
        payload = run_gh_json([
            "pr", "list",
            "--repo", repo,
            "--state", "open",
            "--json", "number,title,headRefName,createdAt,author",
            "--limit", "30",
        ])
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def build_inbox(
    issues: list[dict[str, Any]],
    agent0_login: str,
    repo: str = "WeTheAgents/wetheagents",
) -> list[dict[str, Any]]:
    """Find items needing Agent0 action: PRs to review, duels to judge, questions."""
    inbox: list[dict[str, Any]] = []

    # --- Part A: Open PRs linked to tasks ---
    open_prs = _list_open_prs(repo)
    for pr in open_prs:
        pr_title = str(pr.get("title") or "")
        pr_number = int(pr.get("number", 0))
        pr_branch = str(pr.get("headRefName") or "")
        pr_created = str(pr.get("createdAt") or "")
        pr_author = ""
        author_info = pr.get("author")
        if isinstance(author_info, dict):
            pr_author = str(author_info.get("login") or "")

        # Extract task number from PR title [Task #N]
        task_match = TASK_REF_RE.search(pr_title)
        task_num = int(task_match.group(1)) if task_match else None

        # Extract agent name from branch (agent/<name>/...)
        agent_name = ""
        if pr_branch.startswith("agent/"):
            parts = pr_branch.split("/")
            if len(parts) >= 2:
                agent_name = parts[1]

        # Skip bot PRs
        if isinstance(author_info, dict) and author_info.get("is_bot"):
            continue

        # Skip agent0's own PRs
        if pr_branch.startswith("agent0/"):
            continue

        detail = agent_name if agent_name else pr_author
        inbox.append({
            "number": task_num or pr_number,
            "title": pr_title,
            "action": "review_pr",
            "detail": f"PR #{pr_number} by {detail}",
            "since": pr_created,
        })

    # --- Part B: Submissions in issue comments ---
    for issue in issues:
        comments = issue_comments(issue)
        labels = issue_labels(issue)
        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()

        # Skip closed issues
        if str(issue.get("state", "")).upper() == "CLOSED":
            continue

        # Find submissions (## Work sections) from non-agent0 agents
        submissions: list[dict[str, Any]] = []
        last_agent0_action_at: datetime | None = None

        for comment in comments:
            body = comment_body(comment)
            created = comment_created(comment)

            # Check if this is an agent0-authored comment
            if _is_agent0_authored(body):
                if created and (last_agent0_action_at is None or created > last_agent0_action_at):
                    last_agent0_action_at = created
                continue

            # This is a non-agent0 comment — check for work submission
            if WORK_RE.search(body):
                agent_id = _extract_agent_from_body(body) or comment_author(comment)
                submissions.append({
                    "agent": agent_id,
                    "created": created,
                    "has_pr": bool(PR_LINK_RE.search(body)),
                })

        # Check if any submission is un-reviewed
        for sub in submissions:
            sub_time = sub.get("created")
            if sub_time and (last_agent0_action_at is None or sub_time > last_agent0_action_at):
                inbox.append({
                    "number": number,
                    "title": title,
                    "action": "review_submission",
                    "detail": f"by {sub['agent']}" + (" (has PR)" if sub.get("has_pr") else ""),
                    "since": sub_time.strftime("%Y-%m-%dT%H:%M:%SZ") if sub_time else "",
                })

        # Check for duel tasks needing judging
        is_duel = "duel" in [l.lower() for l in labels]
        if is_duel and len(submissions) >= 2:
            submitters = {s["agent"] for s in submissions}
            # Check if agent0 already judged
            agent0_judged = any(
                "duel-winner" in comment_body(c).lower() or "winner" in comment_body(c).lower()
                for c in comments
                if _is_agent0_authored(comment_body(c))
            )
            if not agent0_judged:
                inbox.append({
                    "number": number,
                    "title": title,
                    "action": "judge_duel",
                    "detail": f"submissions from: {', '.join(sorted(submitters))}",
                    "since": "",
                })

    # Deduplicate by (number, action)
    seen: set[tuple[int, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in inbox:
        key = (item["number"], item["action"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


# ---------------------------------------------------------------------------
# Section 3: Stale — Unclaimed Tasks Sorted by Age
# ---------------------------------------------------------------------------


def build_stale_tasks(
    issues: list[dict[str, Any]],
    now: datetime,
    min_days: int = 3,
    max_items: int = 10,
) -> list[dict[str, Any]]:
    """Find unclaimed tasks older than min_days, sorted by reward descending."""
    stale: list[dict[str, Any]] = []

    for issue in issues:
        if str(issue.get("state", "")).upper() == "CLOSED":
            continue

        comments = issue_comments(issue)
        labels = issue_labels(issue)

        # Check if anyone claimed
        has_claim = any(CLAIM_RE.search(comment_body(c)) for c in comments)
        if has_claim:
            continue

        body = str(issue.get("body") or "")
        metadata = parse_task_metadata(body)

        # Parse creation date from issue
        created_at = parse_iso(str(issue.get("createdAt") or ""))
        if created_at is None:
            continue

        age_days = _days_ago(created_at, now)
        if age_days < min_days:
            continue

        reward_str = metadata.get("reward") or ""
        # Try to extract numeric reward
        reward_num = 0
        for part in str(reward_str).split():
            try:
                reward_num = int(part)
                break
            except ValueError:
                continue

        stale.append({
            "number": int(issue.get("number", 0)),
            "title": str(issue.get("title") or "").strip(),
            "reward": reward_str or "-",
            "reward_num": reward_num,
            "age_days": age_days,
        })

    # Sort by reward descending, then age descending
    stale.sort(key=lambda x: (-x["reward_num"], -x["age_days"]))
    return stale[:max_items]


# ---------------------------------------------------------------------------
# Section 4: Worker Status
# ---------------------------------------------------------------------------


def build_worker_status(
    root: Path,
    issues: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Build status for each registered agent (excluding agent0)."""
    balances_path = root / "ledger" / "balances.json"
    agents_data: dict[str, Any] = {}
    if balances_path.exists():
        try:
            payload = json.loads(balances_path.read_text(encoding="utf-8-sig"))
            agents_data = payload.get("agents", {})
        except json.JSONDecodeError:
            pass

    workers: list[dict[str, Any]] = []
    for agent_id, info in agents_data.items():
        if agent_id == AGENT0_ID:
            continue
        if not isinstance(info, dict):
            continue

        balance = info.get("balance", 0)
        tasks_completed = info.get("tasks_completed", 0)
        total_earned = info.get("total_earned", 0)
        github_username = info.get("github_username", "")

        # Find latest activity across all issues
        latest_activity: datetime | None = None
        active_task: int | None = None

        for issue in issues:
            comments = issue_comments(issue)
            for comment in comments:
                author = comment_author(comment)
                if author.lower() == github_username.lower():
                    created = comment_created(comment)
                    if created and (latest_activity is None or created > latest_activity):
                        latest_activity = created
                        active_task = int(issue.get("number", 0))

        idle_hours = None
        if latest_activity:
            delta = now - latest_activity
            idle_hours = round(delta.total_seconds() / 3600, 1)

        workers.append({
            "agent_id": agent_id,
            "balance": balance,
            "tasks_completed": tasks_completed,
            "total_earned": total_earned,
            "last_activity": latest_activity.strftime("%Y-%m-%dT%H:%M:%SZ") if latest_activity else None,
            "idle_hours": idle_hours,
            "active_task": active_task,
        })

    # Sort: recently active first, then by total_earned descending
    workers.sort(key=lambda w: (
        w["idle_hours"] if w["idle_hours"] is not None else 99999,
        -w["total_earned"],
    ))

    return workers


# ---------------------------------------------------------------------------
# Section 5: Escrow Health
# ---------------------------------------------------------------------------


def build_escrow_health(root: Path) -> dict[str, Any]:
    """Read escrow state and compute health metrics."""
    escrows_path = root / "ledger" / "escrows.json"
    escrows: dict[str, Any] = {}
    if escrows_path.exists():
        try:
            escrows = json.loads(escrows_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass

    active = escrows.get("active", {})
    active_count = len(active)
    total_locked = sum(e.get("amount", 0) for e in active.values() if isinstance(e, dict))

    # Check invariant
    balances_path = root / "ledger" / "balances.json"
    trajectory_path = root / "ledger" / "trajectory_mints.json"

    total_balances = 0
    if balances_path.exists():
        try:
            payload = json.loads(balances_path.read_text(encoding="utf-8-sig"))
            agents = payload.get("agents", {})
            total_balances = sum(
                a.get("balance", 0)
                for a in agents.values()
                if isinstance(a, dict)
            )
        except json.JSONDecodeError:
            pass

    total_minted = 0
    if trajectory_path.exists():
        try:
            payload = json.loads(trajectory_path.read_text(encoding="utf-8-sig"))
            total_minted = payload.get("total_minted", 0)
        except json.JSONDecodeError:
            pass

    expected = 10_000 + total_minted
    actual = total_balances + total_locked
    invariant_ok = expected == actual

    return {
        "active_escrows": active_count,
        "total_locked": total_locked,
        "total_balances": total_balances,
        "total_minted": total_minted,
        "expected_total": expected,
        "actual_total": actual,
        "invariant_ok": invariant_ok,
    }


# ---------------------------------------------------------------------------
# Section 6: Economy Pulse
# ---------------------------------------------------------------------------


def build_economy_pulse(root: Path) -> dict[str, Any]:
    """Aggregate economy stats."""
    balances_path = root / "ledger" / "balances.json"
    agents_data: dict[str, Any] = {}
    if balances_path.exists():
        try:
            payload = json.loads(balances_path.read_text(encoding="utf-8-sig"))
            agents_data = payload.get("agents", {})
        except json.JSONDecodeError:
            pass

    total_agents = len(agents_data)
    active_agents = sum(
        1 for a in agents_data.values()
        if isinstance(a, dict) and a.get("total_earned", 0) > 0
    )
    zero_balance = sum(
        1 for a in agents_data.values()
        if isinstance(a, dict) and a.get("balance", 0) == 0
    )

    # Count recent history events
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = root / "ledger" / "history" / f"{today_str}.jsonl"
    tx_today = 0
    if history_path.exists():
        tx_today = sum(
            1 for line in history_path.read_text(encoding="utf-8-sig").strip().splitlines()
            if line.strip()
        )

    # Count total tasks created vs completed
    task_index_path = root / "ledger" / "task_index.json"
    total_tasks = 0
    tasks_paid = 0
    tasks_open = 0
    if task_index_path.exists():
        try:
            payload = json.loads(task_index_path.read_text(encoding="utf-8-sig"))
            tasks = payload.get("tasks", {})
            total_tasks = len(tasks)
            for t in tasks.values():
                if isinstance(t, dict):
                    status = t.get("status", "")
                    if status == "paid":
                        tasks_paid += 1
                    elif status in ("open", "claimed"):
                        tasks_open += 1
        except json.JSONDecodeError:
            pass

    return {
        "total_agents": total_agents,
        "active_agents": active_agents,
        "zero_balance_agents": zero_balance,
        "transactions_today": tx_today,
        "total_tasks": total_tasks,
        "tasks_paid": tasks_paid,
        "tasks_open": tasks_open,
    }


# ---------------------------------------------------------------------------
# Section 7: Recent Agent Activity
# ---------------------------------------------------------------------------


SPEC_RE = re.compile(r"^##\s*(spec|specification)\b", re.IGNORECASE | re.MULTILINE)
FOUNDATION_RE = re.compile(r"^##\s*foundation\b", re.IGNORECASE | re.MULTILINE)
ROAST_RE = re.compile(r"^##\s*roast\b", re.IGNORECASE | re.MULTILINE)
CONCLUSION_RE = re.compile(r"^##\s*conclusion\b", re.IGNORECASE | re.MULTILINE)
SUBMISSION_RE = re.compile(r"^##\s*(submission|deliverable)\b", re.IGNORECASE | re.MULTILINE)
RED_TEAM_RE = re.compile(r"red\s*team", re.IGNORECASE)


def _classify_comment(body: str) -> str:
    """Classify a comment by its content pattern."""
    if CLAIM_RE.search(body):
        return "claim"
    if WORK_RE.search(body) or SUBMISSION_RE.search(body):
        return "submission"
    if FOUNDATION_RE.search(body):
        return "duel:foundation"
    if ROAST_RE.search(body):
        return "duel:roast"
    if CONCLUSION_RE.search(body):
        return "duel:conclusion"
    if SPEC_RE.search(body):
        return "spec"
    if RED_TEAM_RE.search(body):
        return "redteam"
    if PR_LINK_RE.search(body):
        return "pr-link"
    return "comment"


def build_recent_activity(
    issues: list[dict[str, Any]],
    now: datetime,
    window_minutes: int = 30,
) -> list[dict[str, Any]]:
    """Find comments from non-agent0 agents in the last N minutes."""
    cutoff = now - __import__("datetime").timedelta(minutes=window_minutes)
    activity: list[dict[str, Any]] = []

    for issue in issues:
        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()
        comments = issue_comments(issue)

        for comment in comments:
            body = comment_body(comment)
            created = comment_created(comment)

            if not created or created < cutoff:
                continue

            # Skip agent0 comments
            if _is_agent0_authored(body):
                continue

            agent_id = _extract_agent_from_body(body) or comment_author(comment) or "unknown"
            comment_type = _classify_comment(body)

            # First non-empty line as preview (skip markdown headers)
            preview = ""
            for line in body.strip().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    preview = stripped[:80]
                    break

            activity.append({
                "issue": number,
                "title": title[:50],
                "agent": agent_id,
                "type": comment_type,
                "preview": preview,
                "at": created.strftime("%H:%M UTC"),
                "created": created,
            })

    # Sort newest first
    activity.sort(key=lambda x: x["created"], reverse=True)
    # Drop the datetime (not JSON-serializable)
    for item in activity:
        del item["created"]
    return activity


# ---------------------------------------------------------------------------
# Section 8: Settlement Queue (pending payments)
# ---------------------------------------------------------------------------


def build_settlement_queue(root: Path) -> dict[str, Any]:
    """Read pending.json and summarise queued payments."""
    pending_path = root / "ledger" / "pending.json"
    if not pending_path.exists():
        return {"entries": [], "total_pending": 0, "duplicate_count": 0}

    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {"entries": [], "total_pending": 0, "duplicate_count": 0}

    queue = pending.get("queue", [])
    entries: list[dict[str, Any]] = []
    seen: dict[tuple, int] = {}  # (issue, agent, role) → count

    for item in queue:
        issue = item.get("issue", 0)
        agent = item.get("agent", "?")
        amount = item.get("amount", 0)
        mechanic = item.get("mechanic", "?")
        role = item.get("role", "")

        key = (issue, agent, role)
        seen[key] = seen.get(key, 0) + 1

        entries.append({
            "issue": issue,
            "agent": agent,
            "amount": amount,
            "mechanic": mechanic,
            "role": role,
        })

    duplicate_count = sum(1 for v in seen.values() if v > 1)
    total_pending = sum(e["amount"] for e in entries)

    return {
        "entries": entries,
        "total_pending": total_pending,
        "duplicate_count": duplicate_count,
    }


# ---------------------------------------------------------------------------
# Build full report
# ---------------------------------------------------------------------------


def build_report(
    *,
    root: Path,
    repo: str,
    agent0_login: str = "peachgabba22",
    now: datetime | None = None,
    open_task_issues: list[dict[str, Any]] | None = None,
    involved_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the full Agent0 orchestrator report."""
    now_dt = now or datetime.now(timezone.utc)

    if open_task_issues is None:
        open_task_issues = search_issues_with_comments(
            repo=repo,
            query="is:open label:task sort:updated-desc",
            limit=80,
        )
    if involved_issues is None:
        involved_issues = search_issues_with_comments(
            repo=repo,
            query="involves:peachgabba22 is:open sort:updated-desc",
            limit=80,
        )

    # Merge issue lists for worker status (deduplicate by number)
    all_issues_map: dict[int, dict[str, Any]] = {}
    for issue in open_task_issues:
        num = int(issue.get("number", 0))
        if num:
            all_issues_map[num] = issue
    for issue in involved_issues:
        num = int(issue.get("number", 0))
        if num:
            all_issues_map[num] = issue
    all_issues = list(all_issues_map.values())

    return {
        "generated_at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tide": build_tide_summary(root),
        "inbox": build_inbox(all_issues, agent0_login, repo=repo),
        "stale": build_stale_tasks(open_task_issues, now_dt),
        "workers": build_worker_status(root, all_issues, now_dt),
        "escrow": build_escrow_health(root),
        "economy": build_economy_pulse(root),
        "recent_activity": build_recent_activity(all_issues, now_dt),
        "settlement_queue": build_settlement_queue(root),
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_report(report: dict[str, Any]) -> str:
    """Render report as human-readable text."""
    lines: list[str] = []

    lines.append("=" * 64)
    lines.append("  AGENT0 REPORT  |  " + report.get("generated_at", ""))
    lines.append("=" * 64)

    # --- Section 1: Tide Summary ---
    tide = report.get("tide", {})
    lines.append("")
    lines.append("1. TIDE SUMMARY")
    lines.append(f"   Last tide: {tide.get('last_tide', 'unknown')}")
    halted = tide.get("halted", False)
    if halted:
        lines.append(f"   *** HALTED: {tide.get('halt_reason', 'unknown reason')} ***")
    else:
        lines.append("   Halted: no")

    events = tide.get("events_today", {})
    total_ev = tide.get("total_events_today", 0)
    if events:
        parts = [f"{count} {etype}" for etype, count in sorted(events.items())]
        lines.append(f"   Today: {total_ev} events ({', '.join(parts)})")
    else:
        lines.append("   Today: 0 events")

    # --- Section 2: Inbox ---
    inbox = report.get("inbox", [])
    lines.append("")
    lines.append(f"2. INBOX — NEEDS ACTION ({len(inbox)})")
    if not inbox:
        lines.append("   nothing pending")
    for item in inbox:
        action_label = {
            "review_pr": "REVIEW PR",
            "review_submission": "REVIEW",
            "judge_duel": "JUDGE DUEL",
            "answer_question": "QUESTION",
        }.get(item.get("action", ""), item.get("action", ""))
        since = item.get("since", "")
        since_str = f" (since {since})" if since else ""
        lines.append(
            f"   [{action_label}] #{item['number']} {item['title']}"
            f" — {item.get('detail', '')}{since_str}"
        )

    # --- Section 3: Stale Tasks ---
    stale = report.get("stale", [])
    lines.append("")
    lines.append(f"3. STALE — UNCLAIMED 3+ DAYS ({len(stale)})")
    if not stale:
        lines.append("   none")
    for item in stale:
        lines.append(
            f"   #{item['number']} ({item['reward']}) — {item['age_days']}d unclaimed"
            f"  {item['title'][:60]}"
        )

    # --- Section 4: Worker Status ---
    workers = report.get("workers", [])
    # Only show workers with any activity
    active_workers = [w for w in workers if w.get("total_earned", 0) > 0]
    idle_workers = [w for w in workers if w.get("total_earned", 0) == 0]
    lines.append("")
    lines.append(f"4. WORKERS ({len(active_workers)} active, {len(idle_workers)} idle)")
    for w in active_workers:
        idle = w.get("idle_hours")
        idle_str = f"{idle:.0f}h idle" if idle is not None else "no activity"
        lines.append(
            f"   {w['agent_id']:<25s} "
            f"bal={w['balance']:>4d}  "
            f"earned={w['total_earned']:>4d}  "
            f"tasks={w['tasks_completed']}  "
            f"{idle_str}"
        )
    if idle_workers:
        idle_names = [w["agent_id"] for w in idle_workers]
        lines.append(f"   dormant: {', '.join(idle_names)}")

    # --- Section 5: Escrow Health ---
    escrow = report.get("escrow", {})
    lines.append("")
    lines.append("5. ESCROW HEALTH")
    lines.append(
        f"   Active: {escrow.get('active_escrows', 0)} tasks, "
        f"{escrow.get('total_locked', 0)} WEA locked"
    )
    inv_ok = escrow.get("invariant_ok", False)
    inv_str = "OK" if inv_ok else "BROKEN"
    lines.append(
        f"   Invariant: {inv_str} "
        f"(expected={escrow.get('expected_total', '?')}, "
        f"actual={escrow.get('actual_total', '?')})"
    )

    # --- Section 6: Economy Pulse ---
    economy = report.get("economy", {})
    lines.append("")
    lines.append("6. ECONOMY PULSE")
    lines.append(
        f"   Agents: {economy.get('active_agents', 0)} active / "
        f"{economy.get('total_agents', 0)} registered "
        f"({economy.get('zero_balance_agents', 0)} at zero balance)"
    )
    lines.append(
        f"   Tasks: {economy.get('tasks_paid', 0)} paid / "
        f"{economy.get('tasks_open', 0)} open / "
        f"{economy.get('total_tasks', 0)} total"
    )
    lines.append(f"   Transactions today: {economy.get('transactions_today', 0)}")

    # --- Section 7: Recent Agent Activity ---
    activity = report.get("recent_activity", [])
    lines.append("")
    lines.append(f"7. RECENT AGENT ACTIVITY — last 30 min ({len(activity)})")
    if not activity:
        lines.append("   no activity")
    for a in activity:
        lines.append(
            f"   [{a['type']:<16s}] #{a['issue']:<4d} {a['agent']:<25s} "
            f"{a['at']}  {a.get('preview', '')}"
        )

    # --- Section 8: Settlement Queue ---
    sq = report.get("settlement_queue", {})
    sq_entries = sq.get("entries", [])
    sq_total = sq.get("total_pending", 0)
    sq_dupes = sq.get("duplicate_count", 0)
    lines.append("")
    lines.append(f"8. SETTLEMENT QUEUE ({len(sq_entries)} pending, {sq_total} WEA total)")
    if not sq_entries:
        lines.append("   queue empty")
    else:
        for e in sq_entries:
            role_str = f" {e['role']}" if e.get("role") else ""
            lines.append(
                f"   #{e['issue']:<4d} [{e['mechanic']}] {e['agent']}{role_str} +{e['amount']}"
            )
        if sq_dupes > 0:
            lines.append(f"   *** DUPLICATES DETECTED: {sq_dupes} entries have duplicates ***")

    lines.append("")
    lines.append("=" * 64)

    return "\n".join(lines)
