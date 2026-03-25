#!/usr/bin/env python3
"""Check max active claims per agent (abuse protection).

Usage:
    python scripts/check_concurrent_claims.py [--max N] [--root PATH]
    python scripts/check_concurrent_claims.py --json-file claims.json [--max N]

With --json-file: load claims from JSON (for tests, no gh needed).
JSON format: [{"issue": 54, "agent": "Cursor-1@cursor"}, ...]

Without --json-file: fetch claimed issues via gh, resolve agents from idem_keys.

Exit codes:
    0 — no agent exceeds max concurrent claims
    1 — one or more agents exceed the limit
    2 — error (missing files, gh failure, invalid JSON)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root(script_path: Path) -> Path:
    """scripts/ -> repo root."""
    return script_path.resolve().parent.parent


def get_claims_from_json(path: Path) -> list[tuple[int, str]]:
    """Load claims from JSON file. Returns [(issue, agent), ...]."""
    data = load_json(path, encoding="utf-8-sig")
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of {issue, agent} objects")
    result: list[tuple[int, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        issue = item.get("issue") or item.get("number")
        agent = (str(item.get("agent", "") or "")).strip()
        if issue is not None and agent:
            result.append((int(issue), agent))
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


def get_claim_agent_from_idem_keys(issue: int, idem_keys_path: Path) -> str | None:
    """Get the current claimant for an issue from idem_keys (latest timestamp)."""
    if not idem_keys_path.exists():
        return None
    data = load_json(idem_keys_path, encoding="utf-8-sig")
    keys = data.get("keys") or {}
    if not isinstance(keys, dict):
        return None
    prefix = f"claim|{issue}|"
    candidates: list[tuple[str, str]] = []
    for key, ts in keys.items():
        if isinstance(key, str) and key.startswith(prefix):
            agent = key[len(prefix) :]
            if agent and isinstance(ts, str):
                candidates.append((ts, agent))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def count_claims_per_agent(claims: list[tuple[int, str]]) -> dict[str, list[int]]:
    """Group claims by agent. Returns {agent: [issue, ...]}."""
    by_agent: dict[str, list[int]] = {}
    for issue, agent in claims:
        by_agent.setdefault(agent, []).append(issue)
    return by_agent


def main() -> int:
    repo_root = _repo_root(Path(__file__))

    parser = argparse.ArgumentParser(
        description="Check max active claims per agent"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=2,
        help="Max concurrent claims per agent (default: 2)",
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
    args = parser.parse_args()

    root = args.root.resolve()
    idem_keys_path = root / "ledger" / "idem_keys.json"

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
            agent = get_claim_agent_from_idem_keys(num, idem_keys_path)
            if agent:
                claims.append((num, agent))

    by_agent = count_claims_per_agent(claims)
    violators = {
        agent: issues
        for agent, issues in by_agent.items()
        if len(issues) > args.max
    }

    if violators:
        print("FAIL: Agent(s) exceed max concurrent claims")
        for agent, issues in sorted(violators.items()):
            print(f"  {agent}: {len(issues)} claims (max {args.max}) — issues {issues}")
        print("  Why it matters: claim squatting blocks other agents.")
        print("  Remediation:")
        print("    1. Complete or release one of the claimed tasks.")
        print("    2. Post 'reject @agent reason: ...' to free the slot.")
        return 1

    print(f"OK: No agent exceeds {args.max} concurrent claim(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
