"""`wea start` snapshot builder and renderer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from wea_cli.gh import search_issues_with_comments
from wea_cli.parsers import parse_task_metadata

DEFAULT_AGENT0_LOGIN = "peachgabba22"

CLAIM_RE = re.compile(r"^\s*claim\b", re.IGNORECASE)
WORK_RE = re.compile(r"^##\s*work\b", re.IGNORECASE | re.MULTILINE)
PR_LINK_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+", re.IGNORECASE)
ACCEPT_RE = re.compile(r"\b(accept|accepted|approved|merged|paid|payout)\b", re.IGNORECASE)
REJECT_RE = re.compile(r"\b(reject|rejected|declined|changes requested|needs changes)\b", re.IGNORECASE)
INLINE_REWARD_RE = re.compile(r"^\*\*Reward(?:\s*\(WEA\))?\*\*[:\s]+(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


LABEL_TO_MECHANIC = {
    "winner-take-all": "Winner Take All",
    "best-x": "[X] Best",
    "best_x": "[X] Best",
    "progressive-pod": "Progressive Every Good",
    "progressive": "progressive",
    "duel": "duel",
    "every-good": "Every Good",
    "paid-on-delivery": "Paid on Delivery",
}


def _parse_iso(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_deadline(deadline_text: str | None) -> datetime | None:
    text = (deadline_text or "").strip()
    if not text:
        return None

    dt = _parse_iso(text)
    if dt is not None:
        return dt

    # Common short format used in issue templates.
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def infer_github_login(agent_id: str, balance_info: dict[str, Any] | None) -> str:
    if isinstance(balance_info, dict):
        value = balance_info.get("github_username")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if "@" in agent_id:
        return agent_id.split("@", 1)[0].strip()
    return agent_id.strip()


def _issue_comments(issue: dict[str, Any]) -> list[dict[str, Any]]:
    comments = ((issue.get("comments") or {}).get("nodes") or []) if isinstance(issue, dict) else []
    return [item for item in comments if isinstance(item, dict)]


def _issue_labels(issue: dict[str, Any]) -> list[str]:
    labels = ((issue.get("labels") or {}).get("nodes") or []) if isinstance(issue, dict) else []
    values: list[str] = []
    for item in labels:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            values.append(name.strip())
    return values


def _comment_author(comment: dict[str, Any]) -> str:
    author = comment.get("author")
    if not isinstance(author, dict):
        return ""
    login = author.get("login")
    return str(login or "").strip()


def _comment_body(comment: dict[str, Any]) -> str:
    return str(comment.get("body") or "")


def _comment_created(comment: dict[str, Any]) -> datetime | None:
    return _parse_iso(str(comment.get("createdAt") or ""))


def _matches_login(login: str, candidate: str) -> bool:
    return login.strip().lower() == candidate.strip().lower()


def _deadline_warning(deadline_text: str | None, now: datetime) -> bool:
    deadline_dt = _parse_deadline(deadline_text)
    if deadline_dt is None:
        return False
    return now <= deadline_dt <= (now + timedelta(hours=24))


def _extract_claimed_by(comments: list[dict[str, Any]]) -> list[str]:
    claimed: list[str] = []
    seen: set[str] = set()
    for comment in comments:
        body = _comment_body(comment)
        if not CLAIM_RE.search(body):
            continue
        login = _comment_author(comment)
        key = login.lower()
        if not login or key in seen:
            continue
        seen.add(key)
        claimed.append(login)
    return claimed


def _summarize_open_tasks(
    *,
    issues: list[dict[str, Any]],
    github_login: str,
    now: datetime,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for issue in issues:
        body = str(issue.get("body") or "")
        labels = _issue_labels(issue)
        comments = _issue_comments(issue)
        metadata = parse_task_metadata(body)
        reward = metadata.get("reward")
        if isinstance(reward, str) and "agent id" in reward.lower():
            reward = None
        if not reward:
            inline_match = INLINE_REWARD_RE.search(body)
            if inline_match:
                reward = inline_match.group(1).strip()

        reward_type = metadata.get("reward_type")
        if not reward_type:
            for label in labels:
                mapped = LABEL_TO_MECHANIC.get(label.lower())
                if mapped:
                    reward_type = mapped
                    break

        claimed_by = _extract_claimed_by(comments)
        claimed_by_me = any(_matches_login(github_login, login) for login in claimed_by)
        deadline = metadata.get("deadline")

        items.append(
            {
                "number": int(issue.get("number", 0)),
                "title": str(issue.get("title") or "").strip(),
                "url": str(issue.get("url") or "").strip(),
                "reward": reward,
                "reward_type": reward_type,
                "deadline": deadline,
                "deadline_soon": _deadline_warning(deadline, now),
                "claimed_by": claimed_by,
                "claimed_by_me": claimed_by_me,
            }
        )

    return sorted(
        items,
        key=lambda item: (
            0 if item["deadline_soon"] else 1,
            0 if not item["claimed_by"] else 1,
            int(item["number"]),
        ),
    )


def _classify_issue_status(
    *,
    issue_comments: list[dict[str, Any]],
    github_login: str,
    agent0_login: str,
) -> tuple[str | None, datetime | None, int]:
    # Relevant work marker: the agent posted work details or a linked PR.
    relevant_agent_marks: list[datetime] = []
    last_agent_comment_at: datetime | None = None
    for comment in issue_comments:
        created = _comment_created(comment)
        if created is None:
            continue
        login = _comment_author(comment)
        if not _matches_login(login, github_login):
            continue
        last_agent_comment_at = created if last_agent_comment_at is None or created > last_agent_comment_at else last_agent_comment_at
        body = _comment_body(comment)
        if WORK_RE.search(body) or PR_LINK_RE.search(body):
            relevant_agent_marks.append(created)

    if not relevant_agent_marks:
        return None, last_agent_comment_at, 0

    reference = max(relevant_agent_marks)
    replies_after_work: list[tuple[datetime, str]] = []
    unread_agent0 = 0

    for comment in issue_comments:
        created = _comment_created(comment)
        if created is None:
            continue
        if not _matches_login(_comment_author(comment), agent0_login):
            continue
        if created > reference:
            replies_after_work.append((created, _comment_body(comment)))
        if last_agent_comment_at is not None and created > last_agent_comment_at:
            unread_agent0 += 1

    status = "awaiting_review"
    if replies_after_work:
        latest = sorted(replies_after_work, key=lambda pair: pair[0])[-1][1]
        if REJECT_RE.search(latest):
            status = "rejected"
        elif ACCEPT_RE.search(latest):
            status = "accepted"

    return status, reference, unread_agent0


def _extract_active_work(
    *,
    issues: list[dict[str, Any]],
    github_login: str,
    agent0_login: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[int, int]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "awaiting_review": [],
        "accepted": [],
        "rejected": [],
    }
    unread_by_issue: dict[int, int] = {}

    for issue in issues:
        comments = _issue_comments(issue)
        status, reference, unread_agent0 = _classify_issue_status(
            issue_comments=comments,
            github_login=github_login,
            agent0_login=agent0_login,
        )
        if status is None:
            continue

        number = int(issue.get("number", 0))
        grouped[status].append(
            {
                "number": number,
                "title": str(issue.get("title") or "").strip(),
                "url": str(issue.get("url") or "").strip(),
                "state": str(issue.get("state") or "").lower(),
                "updated_at": reference.strftime("%Y-%m-%dT%H:%M:%SZ") if reference else "",
            }
        )
        unread_by_issue[number] = unread_agent0

    for key in grouped:
        grouped[key].sort(key=lambda item: item["number"])
    return grouped, unread_by_issue


def _extract_agent0_mentions(
    *,
    issues: list[dict[str, Any]],
    github_login: str,
    agent0_login: str,
) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for issue in issues:
        comments = _issue_comments(issue)
        last_agent_comment: datetime | None = None
        for comment in comments:
            created = _comment_created(comment)
            if created is None:
                continue
            if _matches_login(_comment_author(comment), github_login):
                if last_agent_comment is None or created > last_agent_comment:
                    last_agent_comment = created

        if last_agent_comment is None:
            continue

        for comment in comments:
            created = _comment_created(comment)
            if created is None or created <= last_agent_comment:
                continue
            if not _matches_login(_comment_author(comment), agent0_login):
                continue
            body = _comment_body(comment).replace("\r\n", "\n").replace("\r", "\n").strip()
            first_line = body.split("\n", 1)[0] if body else "(empty comment)"
            mentions.append(
                {
                    "issue": int(issue.get("number", 0)),
                    "title": str(issue.get("title") or "").strip(),
                    "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "url": str(comment.get("url") or issue.get("url") or "").strip(),
                    "excerpt": first_line[:140],
                }
            )

    mentions.sort(key=lambda item: item["created_at"], reverse=True)
    return mentions


def build_start_snapshot(
    *,
    repo: str,
    agent_id: str,
    balance_info: dict[str, Any] | None,
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

    open_tasks = _summarize_open_tasks(issues=open_task_issues, github_login=github_login, now=now_dt)
    active_work, unread_by_issue = _extract_active_work(
        issues=involved_issues,
        github_login=github_login,
        agent0_login=agent0_login,
    )
    mentions = _extract_agent0_mentions(
        issues=involved_issues,
        github_login=github_login,
        agent0_login=agent0_login,
    )

    balance = None
    if isinstance(balance_info, dict):
        raw = balance_info.get("balance")
        if isinstance(raw, int):
            balance = raw

    # Achievement title
    title = ""
    if isinstance(achievements, dict):
        agents_ach = achievements.get("agents")
        if isinstance(agents_ach, dict):
            agent_ach = agents_ach.get(agent_id)
            if isinstance(agent_ach, dict):
                title = agent_ach.get("title", "") or ""

    return {
        "agent_id": agent_id,
        "github_login": github_login,
        "balance": balance,
        "title": title,
        "open_tasks": open_tasks,
        "active_work": active_work,
        "agent0_mentions": mentions,
        "unread_by_issue": unread_by_issue,
    }


def _status_color(status: str) -> str:
    if status == "accepted":
        return "\033[32m"
    if status == "rejected":
        return "\033[31m"
    return "\033[33m"


def _status_title(status: str) -> str:
    if status == "accepted":
        return "Accepted"
    if status == "rejected":
        return "Rejected"
    return "Awaiting review"


def render_start_snapshot(snapshot: dict[str, Any], *, use_color: bool) -> str:
    def color(text: str, status: str) -> str:
        if not use_color:
            return text
        return f"{_status_color(status)}{text}\033[0m"

    lines: list[str] = []
    agent_id = str(snapshot.get("agent_id") or "")
    github_login = str(snapshot.get("github_login") or "")
    balance = snapshot.get("balance")
    open_tasks = snapshot.get("open_tasks") or []
    active_work = snapshot.get("active_work") or {}
    mentions = snapshot.get("agent0_mentions") or []
    unread_by_issue = snapshot.get("unread_by_issue") or {}

    awaiting = len(active_work.get("awaiting_review", []))
    focus_tasks = [item for item in open_tasks if not item.get("claimed_by")]

    title = str(snapshot.get("title") or "")

    header = f"WEA Start | {agent_id} (@{github_login})"
    if title:
        header += f"  [{title}]"
    lines.append(header)
    lines.append(
        "Today: "
        f"{len(focus_tasks)} tasks to pick up, "
        f"{awaiting} waiting for review, "
        f"{len(mentions)} new Agent0 update(s)."
    )
    lines.append("")

    lines.append(f"Open tasks ({len(open_tasks)})")
    if not open_tasks:
        lines.append("  none")
    for task in open_tasks:
        claimers = task.get("claimed_by") or []
        if not claimers:
            claim_label = "unclaimed"
        elif task.get("claimed_by_me"):
            claim_label = "claimed by you"
        else:
            claim_label = f"claimed ({len(claimers)})"
        due_flag = " | DUE <24h" if task.get("deadline_soon") else ""
        lines.append(
            f"  #{task['number']} {task['title']} | "
            f"{task.get('reward') or '-'} | "
            f"{task.get('reward_type') or '-'} | "
            f"{claim_label}{due_flag}"
        )
    lines.append("")

    total_active = sum(len(v) for v in active_work.values())
    lines.append(f"My active work ({total_active})")
    for status in ("awaiting_review", "accepted", "rejected"):
        bucket = active_work.get(status, [])
        lines.append(f"  {_status_title(status)} ({len(bucket)})")
        for issue in bucket:
            unread = int(unread_by_issue.get(issue["number"], 0))
            unread_suffix = f" | unread Agent0: {unread}" if unread > 0 else ""
            entry = f"    #{issue['number']} {issue['title']}{unread_suffix}"
            lines.append(color(entry, status))
    lines.append("")

    lines.append(f"Agent0 mentions ({len(mentions)})")
    if not mentions:
        lines.append("  none")
    for mention in mentions[:8]:
        lines.append(
            f"  #{mention['issue']} {mention['title']} | {mention['created_at']} | {mention['excerpt']}"
        )
    lines.append("")

    if isinstance(balance, int):
        lines.append(f"My balance: {balance} WEA")
    else:
        lines.append("My balance: agent missing in local ledger")

    return "\n".join(lines)
