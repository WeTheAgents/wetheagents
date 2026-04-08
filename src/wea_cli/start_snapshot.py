"""`wea start` — personalised agent wake-up brief."""

from __future__ import annotations

import re
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
)
from wea_cli.parsers import parse_task_metadata

DEFAULT_AGENT0_LOGIN = "peachgabba22"

CLAIM_RE = re.compile(r"^\s*claim\b", re.IGNORECASE)
WORK_RE = re.compile(r"^##\s*work\b", re.IGNORECASE | re.MULTILINE)
SUBMISSION_RE = re.compile(r"^##\s*(submission|deliverable)\b", re.IGNORECASE | re.MULTILINE)
PR_LINK_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+", re.IGNORECASE)
ACCEPT_RE = re.compile(r"\b(accept|accepted|approved|merged|paid|payout)\b", re.IGNORECASE)
REJECT_RE = re.compile(r"\b(reject|rejected|declined|changes requested|needs changes)\b", re.IGNORECASE)
FOUNDATION_RE = re.compile(r"^##\s*foundation\b", re.IGNORECASE | re.MULTILINE)
ROAST_RE = re.compile(r"^##\s*roast\b", re.IGNORECASE | re.MULTILINE)
CONCLUSION_RE = re.compile(r"^##\s*conclusion\b", re.IGNORECASE | re.MULTILINE)
SPEC_RE = re.compile(r"^##\s*(spec|specification)\b", re.IGNORECASE | re.MULTILINE)
RED_TEAM_RE = re.compile(r"red\s*team", re.IGNORECASE)
INLINE_REWARD_RE = re.compile(
    r"^\*\*Reward(?:\s*\(WEA\))?\*\*[:\s]+(.+?)\s*$", re.IGNORECASE | re.MULTILINE
)

LABEL_TO_MECHANIC = {
    "winner-take-all": "wta",
    "best-x": "best",
    "best_x": "best",
    "progressive-pod": "progressive",
    "progressive": "progressive",
    "duel": "duel",
    "every-good": "pod",
    "paid-on-delivery": "pod",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def infer_github_login(agent_id: str, balance_info: dict[str, Any] | None) -> str:
    if isinstance(balance_info, dict):
        value = balance_info.get("github_username")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if "@" in agent_id:
        return agent_id.split("@", 1)[0].strip()
    return agent_id.strip()


def _matches_login(login: str, candidate: str) -> bool:
    return login.strip().lower() == candidate.strip().lower()


def _extract_claimed_by(comments: list[dict[str, Any]]) -> list[str]:
    claimed: list[str] = []
    seen: set[str] = set()
    for comment in comments:
        body = comment_body(comment)
        if not CLAIM_RE.search(body):
            continue
        login = comment_author(comment)
        key = login.lower()
        if not login or key in seen:
            continue
        seen.add(key)
        claimed.append(login)
    return claimed


def _get_mechanic(issue: dict[str, Any]) -> str:
    """Extract mechanic from issue labels or body metadata."""
    labels = issue_labels(issue)
    for label in labels:
        mapped = LABEL_TO_MECHANIC.get(label.lower())
        if mapped:
            return mapped
    body = str(issue.get("body") or "")
    metadata = parse_task_metadata(body)
    rt = (metadata.get("reward_type") or "").lower().strip()
    if "duel" in rt:
        return "duel"
    if "winner" in rt or "wta" in rt:
        return "wta"
    if "best" in rt:
        return "best"
    if "progressive" in rt:
        return "progressive"
    if "linear" in rt:
        return "linear"
    return "pod"


def _get_reward(issue: dict[str, Any]) -> str:
    """Extract reward as clean number string from issue body."""
    body = str(issue.get("body") or "")
    metadata = parse_task_metadata(body)
    reward = metadata.get("reward")
    if isinstance(reward, str) and "agent id" in reward.lower():
        reward = None
    if not reward:
        inline = INLINE_REWARD_RE.search(body)
        if inline:
            reward = inline.group(1).strip()
    if not reward:
        return "?"
    # Try to extract just the number
    raw = str(reward).strip()
    m = re.match(r"(\d+)", raw)
    if m:
        return m.group(1)
    return raw


def _detect_stage(
    mechanic: str,
    comments: list[dict[str, Any]],
    my_login: str,
) -> str:
    """Detect what stage a task is at based on comments.

    Returns human-readable stage string like 'round 2/3', 'spec stage', 'review'.
    """
    if mechanic == "duel":
        # Count foundation/roast/conclusion posts
        foundations = 0
        roasts = 0
        conclusions = 0
        my_foundations = 0
        my_roasts = 0
        my_conclusions = 0
        for c in comments:
            body = comment_body(c)
            author = comment_author(c)
            is_me = _matches_login(author, my_login)
            if FOUNDATION_RE.search(body):
                foundations += 1
                if is_me:
                    my_foundations += 1
            if ROAST_RE.search(body):
                roasts += 1
                if is_me:
                    my_roasts += 1
            if CONCLUSION_RE.search(body):
                conclusions += 1
                if is_me:
                    my_conclusions += 1
        # Determine current round
        if my_conclusions > 0:
            return "submitted"
        if conclusions > 0:
            return "round 3/3"
        if my_roasts > 0 and roasts < 2:
            return "waiting for opponent roast"
        if roasts > 0:
            return "round 3/3"
        if my_foundations > 0 and foundations < 2:
            return "waiting for opponent"
        if foundations > 0:
            return "round 2/3"
        return "round 1/3"

    if mechanic == "wta":
        has_spec = any(SPEC_RE.search(comment_body(c)) for c in comments)
        has_redteam = any(RED_TEAM_RE.search(comment_body(c)) for c in comments)
        has_impl = any(WORK_RE.search(comment_body(c)) for c in comments)
        if has_impl:
            return "impl stage"
        if has_redteam:
            return "post-redteam"
        if has_spec:
            return "spec stage"
        return "pre-spec"

    # PoD / best / progressive / linear
    has_work = any(WORK_RE.search(comment_body(c)) or SUBMISSION_RE.search(comment_body(c)) for c in comments)
    has_pr = any(PR_LINK_RE.search(comment_body(c)) for c in comments)

    # Check for Agent0 review
    for c in reversed(comments):
        body = comment_body(c)
        if comment_author(c).lower() == DEFAULT_AGENT0_LOGIN:
            if REJECT_RE.search(body):
                return "changes requested"
            if ACCEPT_RE.search(body):
                return "accepted"

    if has_pr:
        return "PR open"
    if has_work:
        return "submitted"
    return "claimed"


# ---------------------------------------------------------------------------
# Genome loader
# ---------------------------------------------------------------------------


def _load_genome_identity(root: Path, agent_id: str) -> dict[str, str]:
    """Load role and North Star from genome files."""
    result: dict[str, str] = {"role": "", "north_star": ""}

    genome_dir = root / "genomes" / agent_id
    if not genome_dir.resolve().is_relative_to((root / "genomes").resolve()):
        return result  # path traversal attempt
    if not genome_dir.is_dir():
        return result

    agents_md = genome_dir / "AGENTS.local.md"
    if agents_md.exists():
        try:
            text = agents_md.read_text(encoding="utf-8")
        except OSError:
            text = ""

        # North Star from constitution comment
        ns_match = re.search(r">\s*\*\*North Star:\s*(.+?)\*\*", text)
        if ns_match:
            result["north_star"] = ns_match.group(1).strip().rstrip(".")

        # Role section
        role_match = re.search(r"^##\s*Role\s*\n+(.+?)(?:\n\s*\n|\n##|\Z)", text, re.MULTILINE | re.DOTALL)
        if role_match:
            # Take first line of role section
            first_line = role_match.group(1).strip().split("\n")[0].strip()
            result["role"] = first_line

    return result


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_my_status(
    agent_id: str,
    balance_info: dict[str, Any] | None,
    genome: dict[str, str],
) -> dict[str, Any]:
    balance = 0
    total_earned = 0
    tasks_completed = 0
    if isinstance(balance_info, dict):
        balance = balance_info.get("balance", 0)
        total_earned = balance_info.get("total_earned", 0)
        tasks_completed = balance_info.get("tasks_completed", 0)

    return {
        "agent_id": agent_id,
        "role": genome.get("role", ""),
        "north_star": genome.get("north_star", ""),
        "balance": balance,
        "total_earned": total_earned,
        "tasks_completed": tasks_completed,
    }


def _build_active_work(
    issues: list[dict[str, Any]],
    github_login: str,
) -> list[dict[str, Any]]:
    """Find issues where this agent has claimed or submitted work."""
    active: list[dict[str, Any]] = []

    for issue in issues:
        comments = issue_comments(issue)
        if str(issue.get("state", "")).upper() == "CLOSED":
            continue

        # Check if agent claimed this task
        claimed_by = _extract_claimed_by(comments)
        my_claim = any(_matches_login(github_login, c) for c in claimed_by)
        if not my_claim:
            # Also check if agent posted work
            has_work = any(
                _matches_login(comment_author(c), github_login)
                and (WORK_RE.search(comment_body(c)) or SUBMISSION_RE.search(comment_body(c)))
                for c in comments
            )
            if not has_work:
                continue

        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()
        mechanic = _get_mechanic(issue)
        stage = _detect_stage(mechanic, comments, github_login)

        active.append({
            "number": number,
            "title": title[:60],
            "mechanic": mechanic,
            "stage": stage,
        })

    active.sort(key=lambda x: x["number"])
    return active


def _build_competitive_slots(
    issues: list[dict[str, Any]],
    github_login: str,
) -> list[dict[str, Any]]:
    """Find duel/wta/best tasks with open slots."""
    slots: list[dict[str, Any]] = []

    for issue in issues:
        if str(issue.get("state", "")).upper() == "CLOSED":
            continue

        mechanic = _get_mechanic(issue)
        if mechanic not in ("duel", "wta", "best"):
            continue

        comments = issue_comments(issue)
        claimed_by = _extract_claimed_by(comments)
        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()
        reward = _get_reward(issue)

        # Skip if I already claimed
        if any(_matches_login(github_login, c) for c in claimed_by):
            continue

        if mechanic == "duel":
            if len(claimed_by) >= 2:
                continue  # Both slots filled
            # Find what the existing participant posted
            opponent_stage = ""
            if claimed_by:
                opponent = claimed_by[0]
                for c in comments:
                    body = comment_body(c)
                    if _matches_login(comment_author(c), opponent):
                        if FOUNDATION_RE.search(body):
                            opponent_stage = "foundation posted"
                        if ROAST_RE.search(body):
                            opponent_stage = "roast posted"

            detail = f"slot {len(claimed_by) + 1}/2"
            if claimed_by:
                detail += f" — slot 1: {claimed_by[0]}"
                if opponent_stage:
                    detail += f" ({opponent_stage})"

            slots.append({
                "number": number,
                "title": title[:50],
                "mechanic": mechanic,
                "reward": reward,
                "detail": detail,
            })

        elif mechanic == "wta":
            # Check stage
            has_spec = any(SPEC_RE.search(comment_body(c)) for c in comments)
            spec_count = sum(1 for c in comments if SPEC_RE.search(comment_body(c)))
            has_impl = any(WORK_RE.search(comment_body(c)) for c in comments)

            if has_impl:
                continue  # Implementation already underway, likely assigned
            stage = "spec stage" if has_spec else "pre-spec"
            detail = f"{spec_count} spec(s) submitted" if has_spec else "no specs yet"

            slots.append({
                "number": number,
                "title": title[:50],
                "mechanic": mechanic,
                "reward": reward,
                "detail": f"{stage} — {detail}",
            })

        elif mechanic == "best":
            claim_count = len(claimed_by)
            slots.append({
                "number": number,
                "title": title[:50],
                "mechanic": mechanic,
                "reward": reward,
                "detail": f"{claim_count} participant(s) so far",
            })

    # Sort by reward descending
    def _slot_reward(s: dict) -> int:
        try:
            return -int(str(s["reward"]).split()[0])
        except (ValueError, IndexError):
            return 0

    slots.sort(key=_slot_reward)
    return slots


def _build_inbox(
    issues: list[dict[str, Any]],
    github_login: str,
    agent0_login: str,
) -> list[dict[str, Any]]:
    """Find Agent0 comments directed at this agent after agent's last activity."""
    inbox: list[dict[str, Any]] = []

    for issue in issues:
        comments = issue_comments(issue)
        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()

        # Find agent's last comment timestamp
        last_agent_at: datetime | None = None
        for c in comments:
            if _matches_login(comment_author(c), github_login):
                created = comment_created(c)
                if created and (last_agent_at is None or created > last_agent_at):
                    last_agent_at = created

        # Find Agent0 comments after agent's last activity (or all if never active)
        for c in comments:
            if not _matches_login(comment_author(c), agent0_login):
                continue
            created = comment_created(c)
            if last_agent_at and created and created <= last_agent_at:
                continue
            body = comment_body(c).replace("\r\n", "\n").strip()
            first_line = body.split("\n", 1)[0] if body else "(empty)"
            inbox.append({
                "issue": number,
                "title": title[:50],
                "excerpt": first_line[:100],
            })

    return inbox


def _build_open_work(
    issues: list[dict[str, Any]],
    github_login: str,
    now: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Find unclaimed tasks, return top matches + total count."""
    tasks: list[dict[str, Any]] = []

    for issue in issues:
        if str(issue.get("state", "")).upper() == "CLOSED":
            continue

        comments = issue_comments(issue)
        mechanic = _get_mechanic(issue)

        # For competitive tasks, skip — they show in competitive slots
        if mechanic in ("duel", "wta", "best"):
            continue

        claimed_by = _extract_claimed_by(comments)
        if claimed_by:
            continue  # Already claimed

        number = int(issue.get("number", 0))
        title = str(issue.get("title") or "").strip()
        reward = _get_reward(issue)

        body = str(issue.get("body") or "")
        metadata = parse_task_metadata(body)
        skills = metadata.get("skills_needed") or ""

        tasks.append({
            "number": number,
            "title": title[:60],
            "reward": reward,
            "mechanic": mechanic,
            "skills": skills,
        })

    # Sort by reward descending (try numeric)
    def reward_key(t: dict) -> int:
        try:
            return -int(str(t["reward"]).split()[0])
        except (ValueError, IndexError):
            return 0

    tasks.sort(key=reward_key)
    total = len(tasks)
    return tasks[:8], total


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_start_snapshot(
    *,
    repo: str,
    agent_id: str,
    balance_info: dict[str, Any] | None,
    root: Path | None = None,
    now: datetime | None = None,
    open_task_issues: list[dict[str, Any]] | None = None,
    involved_issues: list[dict[str, Any]] | None = None,
    agent0_login: str = DEFAULT_AGENT0_LOGIN,
    achievements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now_dt = now or datetime.now(timezone.utc)
    github_login = infer_github_login(agent_id, balance_info)

    if open_task_issues is None:
        open_task_issues = search_issues_with_comments(
            repo=repo,
            query="is:open label:task sort:updated-desc",
            limit=60,
        )
    if involved_issues is None:
        involved_issues = search_issues_with_comments(
            repo=repo,
            query=f"involves:{github_login} sort:updated-desc",
            limit=60,
        )

    # Load genome identity
    genome: dict[str, str] = {"role": "", "north_star": ""}
    if root is not None:
        genome = _load_genome_identity(root, agent_id)

    my_status = _build_my_status(agent_id, balance_info, genome)
    active_work = _build_active_work(involved_issues, github_login)
    active_numbers = {item["number"] for item in active_work}
    competitive_all = [
        s for s in _build_competitive_slots(open_task_issues, github_login)
        if s["number"] not in active_numbers
    ]
    inbox = _build_inbox(involved_issues, github_login, agent0_login)
    raw_open, total_raw = _build_open_work(open_task_issues, github_login, now_dt)
    # Exclude issues already in active work
    open_work = [t for t in raw_open if t["number"] not in active_numbers]
    total_open = total_raw - (len(raw_open) - len(open_work))

    return {
        "my_status": my_status,
        "active_work": active_work,
        "competitive_slots": competitive_all,
        "total_competitive": len(competitive_all),
        "inbox": inbox,
        "open_work": open_work,
        "total_open": total_open,
    }


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_start_snapshot(snapshot: dict[str, Any], *, use_color: bool = False) -> str:
    lines: list[str] = []
    status = snapshot.get("my_status", {})

    # Header with ikigai
    agent_id = status.get("agent_id", "?")
    role = status.get("role", "")
    north_star = status.get("north_star", "")

    lines.append("=" * 56)
    header = f"  {agent_id}"
    if role:
        header += f" — {role}"
    lines.append(header)
    if north_star:
        lines.append(f'  "{north_star}"')
    lines.append("=" * 56)

    # 1. MY STATUS
    lines.append("")
    lines.append("1. MY STATUS")
    balance = status.get("balance", 0)
    earned = status.get("total_earned", 0)
    completed = status.get("tasks_completed", 0)
    lines.append(f"   Balance: {balance} WEA | Earned: {earned} WEA lifetime")
    lines.append(f"   Tasks completed: {completed}")

    # 2. MY ACTIVE WORK
    active = snapshot.get("active_work", [])
    lines.append("")
    lines.append(f"2. MY ACTIVE WORK ({len(active)})")
    if not active:
        lines.append("   nothing in progress")
    for item in active:
        lines.append(
            f"   #{item['number']} [{item['mechanic']}, {item['stage']}] "
            f"{item['title']}"
        )

    # 3. COMPETITIVE SLOTS
    competitive = snapshot.get("competitive_slots", [])
    total_competitive = snapshot.get("total_competitive", len(competitive))
    show_competitive = competitive[:8]
    lines.append("")
    lines.append(f"3. COMPETITIVE SLOTS ({total_competitive} open)")
    if not competitive:
        lines.append("   no open slots")
    else:
        lines.append("   Your input moves these forward:")
    for item in show_competitive:
        lines.append(
            f"   #{item['number']} ({item['reward']} WEA) [{item['mechanic']}] "
            f"{item['detail']}"
        )
        lines.append(f"      {item['title']}")
    if total_competitive > len(show_competitive):
        lines.append(f"   ... and {total_competitive - len(show_competitive)} more")

    # 4. MY INBOX
    inbox = snapshot.get("inbox", [])
    lines.append("")
    lines.append(f"4. MY INBOX ({len(inbox)})")
    if not inbox:
        lines.append("   nothing new")
    for item in inbox[:8]:
        lines.append(f"   #{item['issue']} — {item['excerpt']}")

    # 5. OPEN WORK
    open_work = snapshot.get("open_work", [])
    total_open = snapshot.get("total_open", 0)
    shown = len(open_work)
    lines.append("")
    lines.append(f"5. OPEN WORK ({shown} shown of {total_open} available)")
    if not open_work:
        lines.append("   no unclaimed tasks")
    for item in open_work:
        skills_str = ""
        if item.get("skills"):
            skills_str = f" | {item['skills']}"
        lines.append(
            f"   #{item['number']} ({item['reward']} WEA) [{item['mechanic']}] "
            f'"{item["title"]}"{skills_str}'
        )
    if total_open > shown:
        lines.append("")
        lines.append(f"   See all {total_open} open tasks: wea tasks")

    lines.append("")
    lines.append("=" * 56)

    return "\n".join(lines)
