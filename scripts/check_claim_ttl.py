#!/usr/bin/env python3
"""Check for expired claims (claim older than TTL without delivery).

TTL semantics: measured from claim moment (idem_keys timestamp), NOT from last
activity. Simpler, harder to game — a claim 25h old with a comment 1h ago is
still expired. Alternative (last-comment-based) would reset TTL on any activity.

Usage:
    python scripts/check_claim_ttl.py [--ttl-hours N] [--root PATH] [--now ISO]
    python scripts/check_claim_ttl.py --json-file claims.json [--ttl-hours N] [--now ISO]

With --json-file: load claims from JSON (for tests). Format:
    [{"issue": 54, "agent": "Cursor-1@cursor", "claimed_at": "2026-03-05T11:02:28Z"}, ...]

Without --json-file: fetch claimed issues via gh, resolve timestamps from idem_keys.

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


def parse_iso_utc(value: str) -> datetime:
    """Parse ISO timestamp and normalize to UTC-aware datetime.

    Copied from scripts/check_provisional.py — do not reinvent.
    """
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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_claims_from_json(path: Path) -> list[tuple[int, str, str]]:
    """Load claims from JSON. Returns [(issue, agent, claimed_at_iso), ...]."""
    data = _load_json(path)
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of {issue, agent, claimed_at} objects")
    result: list[tuple[int, str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        issue = item.get("issue") or item.get("number")
        agent = (str(item.get("agent", "") or "")).strip()
        claimed_at = (str(item.get("claimed_at", "") or "")).strip()
        if issue is not None and agent and claimed_at:
            result.append((int(issue), agent, claimed_at))
    return result


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
    data = _load_json(idem_keys_path)
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
                claims.append((num, agent, ts))

    ttl_delta = timedelta(hours=args.ttl_hours)
    expired: list[tuple[int, str, str]] = []

    for issue, agent, claimed_at_str in claims:
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
