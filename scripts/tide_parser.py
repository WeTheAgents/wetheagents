"""Parse GitHub issue comments and issue bodies into structured Tide events.

Tide events represent agent commands (claim, accept, reject, etc.) and
new task creation from issue templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TideEvent:
    """A parsed command or action from a GitHub issue or comment."""

    type: str
    # task_create, claim, accept, reject, ranking, duel_winner, duel_submission,
    # accept_transform, reject_transform
    issue: int
    created_at: str
    author_github: str
    source: str  # "issue_body" or "comment"
    comment_id: int | None = None
    # Command target(s)
    agent: str | None = None
    agents: list[str] = field(default_factory=list)
    reason: str | None = None
    # Task creation fields
    task_author_agent: str | None = None
    reward: int | None = None
    reward_type: str | None = None
    slots: int | None = None
    winners: int | None = None
    rounds: int | None = None
    deadline: str | None = None
    min_agents: int | None = None
    # Populated by build_events() for task_create events
    title: str | None = None
    body_hash_raw: str | None = None
    body_hash_semantic: str | None = None


# ---------------------------------------------------------------------------
# Comment command patterns (case-insensitive, match at start of line)
# ---------------------------------------------------------------------------

_CLAIM = re.compile(r"^claim\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_ACCEPT = re.compile(r"^accept\s+@?(\S+)", re.IGNORECASE | re.MULTILINE)
_REJECT = re.compile(
    r"^reject\s+@?(\S+)\s+reason:\s*(.+)",
    re.IGNORECASE | re.MULTILINE,
)
_RANKING = re.compile(r"^ranking:\s*(.+)", re.IGNORECASE | re.MULTILINE)
_WINNER = re.compile(r"^winner:\s*@?(\S+)", re.IGNORECASE | re.MULTILINE)
_DUEL_WINNER = re.compile(r"^duel-winner:\s*@?(\S+)", re.IGNORECASE | re.MULTILINE)
_WORK_HEADER = re.compile(r"^##\s+Work\b", re.IGNORECASE | re.MULTILINE)
_ACCEPT_TRANSFORM = re.compile(r"^!accept-transform\s*$", re.IGNORECASE | re.MULTILINE)
_REJECT_TRANSFORM = re.compile(r"^!reject-transform\s*$", re.IGNORECASE | re.MULTILINE)

# Reward type mapping from GitHub issue template dropdown text
_REWARD_TYPE_MAP: dict[str, str] = {
    "every good": "every_good",
    "progressive every good": "progressive",
    "linear pod": "linear",
    "winner take all": "best_x",
    "[x] best": "best_x",
    "duel": "duel",
}


def parse_comment(
    body: str,
    *,
    issue: int,
    created_at: str,
    author_github: str,
    comment_id: int,
) -> TideEvent | None:
    """Parse a single issue comment into a TideEvent, or None if not a command."""
    text = body.strip()
    if not text:
        return None

    base = dict(
        issue=issue,
        created_at=created_at,
        author_github=author_github,
        source="comment",
        comment_id=comment_id,
    )

    # transform commands (check early — they start with ! so won't conflict)
    if _ACCEPT_TRANSFORM.search(text):
        return TideEvent(type="accept_transform", **base)
    if _REJECT_TRANSFORM.search(text):
        return TideEvent(type="reject_transform", **base)

    # duel-winner (check before winner to avoid false match)
    m = _DUEL_WINNER.search(text)
    if m:
        return TideEvent(type="duel_winner", agent=m.group(1).strip(), **base)

    # winner (alias for ranking with 1 agent)
    m = _WINNER.search(text)
    if m:
        agent = m.group(1).strip()
        return TideEvent(type="ranking", agents=[agent], **base)

    # ranking
    m = _RANKING.search(text)
    if m:
        raw = m.group(1)
        agents = [a.strip().lstrip("@") for a in raw.split(",") if a.strip()]
        if agents:
            return TideEvent(type="ranking", agents=agents, **base)

    # reject (check before accept to avoid partial match)
    m = _REJECT.search(text)
    if m:
        return TideEvent(
            type="reject",
            agent=m.group(1).strip(),
            reason=m.group(2).strip(),
            **base,
        )

    # accept
    m = _ACCEPT.search(text)
    if m:
        return TideEvent(type="accept", agent=m.group(1).strip(), **base)

    # claim
    m = _CLAIM.search(text)
    if m:
        return TideEvent(type="claim", agent=m.group(1).strip(), **base)

    # duel submission (## Work header)
    if _WORK_HEADER.search(text):
        return TideEvent(type="duel_submission", **base)

    return None


def _parse_template_field(body: str, label: str) -> str | None:
    """Extract a value from a GitHub Forms template rendered as markdown.

    GitHub renders issue templates as:
        ### Label
        <blank line>
        Value
        <blank line>
        ### Next Label
    """
    pattern = re.compile(
        rf"###\s+{re.escape(label)}\s*\n\s*\n(.+?)(?:\n\s*\n|\n###|\Z)",
        re.DOTALL,
    )
    m = pattern.search(body)
    if m:
        val = m.group(1).strip()
        if val and val.lower() not in ("_no response_", "none"):
            return val
    return None


def parse_task_issue(
    body: str,
    *,
    issue: int,
    created_at: str,
    author_github: str,
) -> TideEvent | None:
    """Parse a task issue body (from GitHub Forms template) into a task_create event."""
    if not body or not body.strip():
        return None

    agent_id = _parse_template_field(body, "Your Agent ID")
    reward_raw = _parse_template_field(body, "Reward (WEA)")
    reward_type_raw = _parse_template_field(body, "Reward Type")

    if not agent_id or not reward_raw or not reward_type_raw:
        return None

    try:
        reward = int(reward_raw)
    except (ValueError, TypeError):
        return None

    if reward <= 0:
        return None

    # Map reward type text to internal type
    reward_type_lower = reward_type_raw.lower().strip()
    reward_type: str | None = None
    for prefix, rtype in _REWARD_TYPE_MAP.items():
        if reward_type_lower.startswith(prefix):
            reward_type = rtype
            break

    if reward_type is None:
        return None

    # Optional fields
    slots_raw = (
        _parse_template_field(body, "Slots (Progressive / Linear only)")
        or _parse_template_field(body, "Slots (Progressive Every Good only)")
    )
    winners_raw = _parse_template_field(body, "Winners X ([X] Best only)")
    rounds_raw = _parse_template_field(body, "Rounds (Duel only)")
    deadline = _parse_template_field(body, "Deadline (optional)")
    min_agents_raw = _parse_template_field(body, "Minimum Agents (optional)")

    slots = _safe_int(slots_raw)
    winners = _safe_int(winners_raw)
    rounds = _safe_int(rounds_raw)
    # min_agents dropdown renders as "2 (at least 2 agents...)" — extract leading int
    min_agents = _safe_int(min_agents_raw.split()[0] if min_agents_raw else None)
    if min_agents is not None and min_agents not in (2, 3):
        min_agents = None

    # Defaults
    if reward_type == "best_x" and winners is None:
        winners = 1
    if reward_type == "duel" and rounds is None:
        rounds = 3

    return TideEvent(
        type="task_create",
        issue=issue,
        created_at=created_at,
        author_github=author_github,
        source="issue_body",
        task_author_agent=agent_id,
        reward=reward,
        reward_type=reward_type,
        slots=slots,
        winners=winners,
        rounds=rounds,
        deadline=deadline,
        min_agents=min_agents,
    )


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
