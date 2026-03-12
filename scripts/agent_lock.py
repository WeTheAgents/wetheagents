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

Limitations (advisory lock, not hard mutual exclusion):
- GitHub comments API is eventually consistent. Double-verify with a settle
  delay reduces the race window but cannot eliminate it entirely.
- Session ownership is based on the --session string passed by the caller.
  Any process that knows (or can read) the session ID can forge a release.
  This is acceptable for a single-operator (Agent0) setup; for multi-tenant
  use, a signed token protocol would be needed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

REPO = "WeTheAgents/wetheagents"
LOCK_LABEL = "agent-locks"
DEFAULT_TTL = 7200  # 2 hours
ACQUIRE_SETTLE_SECS = 2  # delay between post and verify to let GitHub propagate


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


class FetchError(Exception):
    """Raised when comment fetch fails (network, auth, etc.)."""


def _fetch_comments(issue: int) -> list[dict]:
    """Fetch all comments on the lock issue. Raises FetchError on failure."""
    result = subprocess.run(
        ["gh", "issue", "view", str(issue), "--repo", REPO,
         "--comments", "--json", "comments"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise FetchError(f"gh failed (exit {result.returncode}): {result.stderr.strip()}")
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


_NOT_VISIBLE = object()  # sentinel: our comment hasn't propagated yet


def _verify_acquire(issue: int, slug: str, session: str) -> str | object | None:
    """Re-read lock state and check we still hold it.

    Returns:
        None          — we hold the lock
        _NOT_VISIBLE  — our comment hasn't propagated (transient)
        str           — competing session that holds the lock
    Raises FetchError if the API call fails.
    """
    state = get_lock_status(issue)
    entry = state.get(slug)
    if not entry:
        return _NOT_VISIBLE
    if entry.get("session") != session and _is_locked(entry, _now()):
        return entry.get("session", "?")
    return None


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

    # Double-verify with settle delay.
    # GitHub's comment API is eventually consistent — an immediate re-read
    # may miss a concurrent acquire. We wait ACQUIRE_SETTLE_SECS to let
    # both posts propagate, then verify twice.
    #
    # Verify 1: immediate (catches fast races where a *different* session
    # already wrote an acquire).  _NOT_VISIBLE means GitHub hasn't
    # propagated our own comment yet — that's expected, not a failure.
    result = _verify_acquire(issue, slug, session)
    if result is not None and result is not _NOT_VISIBLE:
        print(f"RACE LOST: {slug} locked by {result}", file=sys.stderr)
        return 1

    # Verify 2: after settle delay (catches slow propagation).
    # By now our comment should be visible; treat _NOT_VISIBLE as failure.
    time.sleep(ACQUIRE_SETTLE_SECS)
    result = _verify_acquire(issue, slug, session)
    if result is not None and result is not _NOT_VISIBLE:
        print(f"RACE LOST: {slug} locked by {result}", file=sys.stderr)
        return 1
    if result is _NOT_VISIBLE:
        print(f"WARN: acquire comment still not visible after settle delay", file=sys.stderr)
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

    try:
        if args.command == "acquire":
            return cmd_acquire(issue, args.slug, args.session, args.ttl)
        elif args.command == "release":
            return cmd_release(issue, args.slug, args.session)
        elif args.command == "release-all":
            return cmd_release_all(issue, args.session)
        elif args.command == "status":
            return cmd_status(issue)
    except (FetchError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
