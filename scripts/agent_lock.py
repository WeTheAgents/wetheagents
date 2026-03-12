#!/usr/bin/env python3
"""Agent lock via GitHub issue comments (JSONL protocol).

Each comment on the lock issue is a single JSON line:
  {"action":"acquire","agent":"claude-1","session":"a0-cloud-123","expires":"...","ts":"..."}
  {"action":"release","agent":"claude-1","session":"a0-cloud-123","ts":"..."}

Latest action per agent wins. Expired acquires are treated as released.

Usage:
    python3 scripts/agent_lock.py acquire <slug> --session <id> [--ttl 7200]
    python3 scripts/agent_lock.py release <slug> --session <id>
    python3 scripts/agent_lock.py release-all --session <id>
    python3 scripts/agent_lock.py status

Exit codes: 0 = success, 1 = locked by another session, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = "WeTheAgents/wetheagents"
LOCK_LABEL = "agent-locks"
DEFAULT_TTL = 7200  # 2 hours


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── GitHub helpers ───────────────────────────────────────────


def _find_lock_issue() -> int | None:
    """Find the issue number labeled 'agent-locks'."""
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", LOCK_LABEL,
         "--state", "open", "--limit", "1", "--json", "number"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    issues = json.loads(result.stdout or "[]")
    return issues[0]["number"] if issues else None


def _fetch_comments(issue: int) -> list[dict]:
    """Fetch all comments on the lock issue."""
    result = subprocess.run(
        ["gh", "issue", "view", str(issue), "--repo", REPO,
         "--comments", "--json", "comments"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout or "{}")
    return data.get("comments", [])


def _post_comment(issue: int, payload: dict) -> None:
    """Post a JSON line comment. Retries once on failure."""
    body = json.dumps(payload, separators=(",", ":"))
    for attempt in range(2):
        result = subprocess.run(
            ["gh", "issue", "comment", str(issue), "--repo", REPO, "--body", body],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return
        if attempt == 0:
            import time
            time.sleep(2)
    raise RuntimeError(f"failed to post comment: {result.stderr.strip()}")


# ── Lock state ───────────────────────────────────────────────


def _parse_lock_state(comments: list[dict]) -> dict[str, dict]:
    """Parse comments into current lock state per agent.

    Returns: {agent_slug: {"session": ..., "expires": ..., "ts": ..., "action": ...}}
    """
    state: dict[str, dict] = {}
    for comment in comments:
        body = comment.get("body", "").strip()
        try:
            entry = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict) or "action" not in entry:
            continue
        agent = entry.get("agent")
        if not agent:
            continue
        state[agent] = entry
    return state


def _is_locked(entry: dict, now: datetime) -> bool:
    """Check if a lock entry is currently active (not expired, not released)."""
    if entry.get("action") != "acquire":
        return False
    expires = entry.get("expires")
    if not expires:
        return False
    return _parse_iso(expires) > now


def get_lock_status(issue: int) -> dict[str, dict]:
    """Get current lock state for all agents."""
    comments = _fetch_comments(issue)
    return _parse_lock_state(comments)


# ── Commands ─────────────────────────────────────────────────


def cmd_acquire(issue: int, slug: str, session: str, ttl: int) -> int:
    now = _now()
    state = get_lock_status(issue)
    entry = state.get(slug)

    if entry and _is_locked(entry, now):
        holder = entry.get("session", "?")
        expires = entry.get("expires", "?")
        if holder == session:
            print(f"already locked by this session ({session})", file=sys.stderr)
            return 0
        print(f"LOCKED by {holder} (expires {expires})", file=sys.stderr)
        return 1

    expires = _iso(now + timedelta(seconds=ttl))
    _post_comment(issue, {
        "action": "acquire",
        "agent": slug,
        "session": session,
        "expires": expires,
        "ts": _iso(now),
    })

    # Read-after-write: verify we won the race
    state2 = get_lock_status(issue)
    entry2 = state2.get(slug)
    if entry2 and entry2.get("session") != session and _is_locked(entry2, _now()):
        # Another session's acquire is the latest — we lost the race.
        # Do NOT post a release: that would overwrite the winner's lock
        # (since _parse_lock_state uses "last comment wins" semantics).
        # Our stale acquire will expire harmlessly via TTL.
        holder = entry2.get("session", "?")
        print(f"RACE LOST: {slug} locked by {holder}", file=sys.stderr)
        return 1

    print(f"acquired {slug} (session={session}, expires={expires})")
    return 0


def cmd_release(issue: int, slug: str, session: str) -> int:
    now = _now()
    state = get_lock_status(issue)
    entry = state.get(slug)

    if not entry or not _is_locked(entry, now):
        print(f"{slug} is not locked, nothing to release")
        return 0

    holder = entry.get("session", "?")
    if holder != session:
        print(f"DENIED: {slug} is locked by {holder}, not {session}", file=sys.stderr)
        return 1

    _post_comment(issue, {
        "action": "release",
        "agent": slug,
        "session": session,
        "ts": _iso(_now()),
    })
    print(f"released {slug}")
    return 0


def cmd_release_all(issue: int, session: str) -> int:
    now = _now()
    state = get_lock_status(issue)
    released = []
    for agent, entry in state.items():
        if entry.get("session") == session and _is_locked(entry, now):
            _post_comment(issue, {
                "action": "release",
                "agent": agent,
                "session": session,
                "ts": _iso(now),
            })
            released.append(agent)
    if released:
        print(f"released: {', '.join(released)}")
    else:
        print("no locks held by this session")
    return 0


def cmd_status(issue: int) -> int:
    now = _now()
    state = get_lock_status(issue)
    if not state:
        print("no locks")
        return 0
    for agent, entry in sorted(state.items()):
        if _is_locked(entry, now):
            session = entry.get("session", "?")
            expires = entry.get("expires", "?")
            print(f"  {agent}: LOCKED by {session} (expires {expires})")
        else:
            print(f"  {agent}: free")
    return 0


# ── Main ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Agent lock manager")
    sub = parser.add_subparsers(dest="command")

    p_acq = sub.add_parser("acquire")
    p_acq.add_argument("slug")
    p_acq.add_argument("--session", required=True)
    p_acq.add_argument("--ttl", type=int, default=DEFAULT_TTL)

    p_rel = sub.add_parser("release")
    p_rel.add_argument("slug")
    p_rel.add_argument("--session", required=True)

    p_all = sub.add_parser("release-all")
    p_all.add_argument("--session", required=True)

    sub.add_parser("status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 2

    issue = _find_lock_issue()
    if issue is None:
        print("ERROR: no open issue with label 'agent-locks' found", file=sys.stderr)
        return 2

    if args.command == "acquire":
        return cmd_acquire(issue, args.slug, args.session, args.ttl)
    elif args.command == "release":
        return cmd_release(issue, args.slug, args.session)
    elif args.command == "release-all":
        return cmd_release_all(issue, args.session)
    elif args.command == "status":
        return cmd_status(issue)
    return 2


if __name__ == "__main__":
    sys.exit(main())
