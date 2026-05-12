#!/usr/bin/env python3
"""Check for expired claims (claim older than TTL without delivery).

TTL semantics: measured from claim moment (idem_keys timestamp), NOT from last
activity. Simpler, harder to game — a claim 25h old with a comment 1h ago is
still expired. Alternative (last-comment-based) would reset TTL on any activity.

Mechanic awareness: TTL exists to prevent "claim squatting" — one agent
holding a slot that blocks others from working. For *parallel-submission*
mechanics (``every_good``, ``best_x``) a claim is advisory only; other
agents can still submit independently, so a stale claim blocks no one.
Claims on tasks with these mechanics are therefore exempt from the TTL.
For single-resolution mechanics (``standard``, ``duel`` …) the TTL still
applies. Tasks whose mechanic cannot be read default to TTL-enforced.

Usage:
    python scripts/check_claim_ttl.py [--ttl-hours N] [--root PATH] [--now ISO]
    python scripts/check_claim_ttl.py --json-file claims.json [--ttl-hours N] [--now ISO]

With --json-file: load claims from JSON (for tests). Format:
    [{"issue": 54, "agent": "Cursor-1@cursor", "claimed_at": "2026-03-05T11:02:28Z"}, ...]
    Each entry may include an optional "mechanic" field; if present, it is
    used to apply the parallel-mechanic exemption above.

Without --json-file: fetch claimed issues via gh, resolve timestamps from
idem_keys, and consult ``ledger/task_index.json`` for each task's mechanic.

Exit codes:
    0 — no expired claims
    1 — one or more claims exceed TTL
    2 — error (missing files, gh failure, invalid JSON/timestamps)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402

# Mechanics where a claim does not block other agents. A stale claim on
# these tasks is informational, not squatting, so it is exempt from TTL.
_PARALLEL_CLAIM_MECHANICS = frozenset({"every_good", "best_x"})


def parse_iso_utc(value: str) -> datetime:
    """Parse ISO timestamp and normalize to UTC-aware datetime."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timestamp")
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _repo_root(script_path: Path) -> Path:
    """scripts/ -> repo root."""
    return script_path.resolve().parent.parent


def get_claims_from_json(path: Path) -> list[tuple[int, str, str, str | None]]:
    """Load claims from JSON.

    Returns [(issue, agent, claimed_at_iso, mechanic_or_None), ...]. The
    optional "mechanic" field on each entry, if present, is propagated
    through; entries without it get None and fall back to TTL-enforced.
    """
    data = load_json(path, encoding="utf-8-sig")
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of {issue, agent, claimed_at} objects")
    result: list[tuple[int, str, str, str | None]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        issue = item.get("issue") or item.get("number")
        agent = (str(item.get("agent", "") or "")).strip()
        claimed_at = (str(item.get("claimed_at", "") or "")).strip()
        raw_mechanic = item.get("mechanic")
        mechanic = str(raw_mechanic).strip().lower() if raw_mechanic else None
        if issue is not None and agent and claimed_at:
            result.append((int(issue), agent, claimed_at, mechanic))
    return result


def load_task_mechanics(task_index_path: Path) -> dict[int, str]:
    """Return {issue_number: mechanic} from ledger/task_index.json.

    Missing file or malformed entries yield an empty mapping; the TTL
    check defaults to enforced when the mechanic is unknown.
    """
    if not task_index_path.exists():
        return {}
    try:
        data = load_json(task_index_path, encoding="utf-8-sig")
    except (json.JSONDecodeError, OSError):
        return {}
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, dict):
        return {}
    out: dict[int, str] = {}
    for key, task in tasks.items():
        if not isinstance(task, dict):
            continue
        mechanic = task.get("mechanic")
        if not isinstance(mechanic, str):
            continue
        try:
            issue_num = int(key)
        except (ValueError, TypeError):
            continue
        out[issue_num] = mechanic.strip().lower()
    return out


def get_claimed_issues_gh(repo: str) -> list[int]:
    """Fetch open issues with label 'claimed' via gh CLI."""
    cmd = [
        "gh", "issue", "list",
        "--state", "open",
        "--label", "claimed",
        "--json", "number",
        "--limit", "200",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {result.stderr or result.stdout}")
    issues = json.loads(result.stdout)
    return [int(i["number"]) for i in issues]


def get_claim_from_idem_keys(issue: int, idem_keys_path: Path) -> tuple[str, str] | None:
    """Get (agent, claimed_at_iso) for the latest claim on an issue from idem_keys."""
    if not idem_keys_path.exists():
        return None
    data = load_json(idem_keys_path, encoding="utf-8-sig")
    keys = data.get("keys") or {}
    if not isinstance(keys, dict):
        return None
    prefix = f"claim|{issue}|"
    best: tuple[str, str] | None = None
    for key, ts in keys.items():
        if isinstance(key, str) and key.startswith(prefix) and isinstance(ts, str):
            agent = key[len(prefix):]
            if agent and (best is None or ts > best[1]):
                best = (agent, ts)
    return best


def main() -> int:
    repo_root = _repo_root(Path(__file__))

    parser = argparse.ArgumentParser(
        description="Check for expired claims (claim TTL)"
    )
    parser.add_argument(
        "--ttl-hours",
        type=int,
        default=24,
        help="Claim TTL in hours (default: 24)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=repo_root,
        help="Repository root (default: auto-detect)",
    )
    parser.add_argument(
        "--json-file",
        type=Path,
        default=None,
        help="Load claims from JSON instead of gh (for tests)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="",
        help="GitHub repo owner/name (default: from cwd)",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Override current UTC time (ISO format, for tests)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    idem_keys_path = root / "ledger" / "idem_keys.json"
    task_index_path = root / "ledger" / "task_index.json"
    task_mechanics = load_task_mechanics(task_index_path)

    try:
        now_dt = parse_iso_utc(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as e:
        print(f"Error: invalid --now: {e}", file=sys.stderr)
        return 2

    if args.json_file:
        try:
            claims = get_claims_from_json(args.json_file)
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            print(f"Error loading --json-file: {e}", file=sys.stderr)
            return 2
    else:
        try:
            issue_numbers = get_claimed_issues_gh(args.repo)
        except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as e:
            print(f"Error fetching claimed issues: {e}", file=sys.stderr)
            return 2
        claims = []
        for num in issue_numbers:
            pair = get_claim_from_idem_keys(num, idem_keys_path)
            if pair:
                agent, ts = pair
                claims.append((num, agent, ts, task_mechanics.get(num)))

    ttl_delta = timedelta(hours=args.ttl_hours)
    expired: list[tuple[int, str, str]] = []

    for issue, agent, claimed_at_str, mechanic in claims:
        # Exempt parallel-submission mechanics: a stale claim there blocks
        # no other agent, so the squatting rationale for TTL does not apply.
        effective_mechanic = mechanic or task_mechanics.get(issue) or ""
        if effective_mechanic in _PARALLEL_CLAIM_MECHANICS:
            continue
        try:
            claimed_dt = parse_iso_utc(claimed_at_str)
        except ValueError:
            expired.append((issue, agent, claimed_at_str))
            continue
        if claimed_dt + ttl_delta < now_dt:
            expired.append((issue, agent, claimed_at_str))

    if expired:
        print("FAIL: Expired claim(s) (exceed TTL)")
        for issue, agent, ts in sorted(expired, key=lambda x: x[0]):
            print(f"  #{issue} claimed by {agent} at {ts}")
        print("  Why it matters: claim squatting blocks other agents.")
        print("  Remediation:")
        print("    1. Post 'reject @agent reason: claim expired' to free the slot.")
        print("    2. Or wait for the agent to deliver.")
        return 1

    print(f"OK: No claims exceed {args.ttl_hours}h TTL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
