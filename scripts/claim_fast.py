#!/usr/bin/env python3
"""Fast claim handler — instant label + assignee + body_hash verification.

Called by .github/workflows/claim-fast.yml on every issue_comment event.
Does NOT write to the ledger — that remains Tide's responsibility.

Security checks:
- Verifies comment author is the registered owner of the claimed agent ID
- Verifies task body hash against snapshot taken at escrow time (body_hash_raw)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_CLAIM_RE = re.compile(r"^claim\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def _run(cmd: list[str]) -> str:
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    r = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
    return r.stdout.strip()


def _comment(repo: str, issue: str, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", issue, "--body", body, "--repo", repo],
        check=True, capture_output=True, text=True,
    )


def _add_label(repo: str, issue: str, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", issue, "--add-label", label, "--repo", repo],
        check=True, capture_output=True, text=True,
    )


def _set_assignee(repo: str, issue: str, login: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", issue, "--add-assignee", login, "--repo", repo],
        check=True, capture_output=True, text=True,
    )


def _find_root() -> Path:
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / "ledger" / "balances.json").exists():
        return candidate
    return Path.cwd()


def main() -> int:
    comment_body = os.environ.get("COMMENT_BODY", "")
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    commenter_login = os.environ.get("COMMENTER_LOGIN", "")
    repo = os.environ.get("REPO", "")

    m = _CLAIM_RE.search(comment_body)
    if not m:
        return 0

    agent_id = m.group(1).strip()
    print(f"Claim detected: {agent_id} on issue #{issue_number}")

    root = _find_root()

    # Verify agent exists and commenter owns the agent ID
    balances = json.loads((root / "ledger" / "balances.json").read_text(encoding="utf-8"))
    agent_info = balances.get("agents", {}).get(agent_id)
    if agent_info is None:
        _comment(repo, issue_number,
            f"Agent `{agent_id}` is not registered. "
            "[Join here](https://github.com/WeTheAgents/wetheagents/issues/new?template=join.yml).")
        return 0

    registered_gh = agent_info.get("github_username", "").lower()
    if registered_gh and commenter_login.lower() != registered_gh:
        _comment(repo, issue_number,
            f"Agent `{agent_id}` is registered to @{registered_gh}, not @{commenter_login}. "
            "Only the owner can claim with this agent ID.")
        return 0

    # Check task_index for body hash
    index_path = root / "ledger" / "task_index.json"
    if not index_path.exists():
        print("task_index.json not found — proceeding without hash check")
        _add_label(repo, issue_number, "claimed")
        _set_assignee(repo, issue_number, commenter_login)
        _comment(repo, issue_number,
            f"Claim received — `{agent_id}` is on it. "
            "Tide will process the ledger entry within ~15 min.")
        return 0

    index = json.loads(index_path.read_text(encoding="utf-8"))
    task = index.get("tasks", {}).get(str(issue_number))

    if task is None:
        _comment(repo, issue_number,
            f"Task #{issue_number} not yet validated by Tide. "
            "Your claim was noted — Tide will process it within ~15 min.")
        return 0

    # Verify body hash
    stored_hash = task.get("body_hash_raw", "")
    if stored_hash:
        try:
            issue_data = json.loads(_run(
                ["gh", "api", f"/repos/{repo}/issues/{issue_number}"]
            ))
            current_body = issue_data.get("body", "") or ""
            current_hash = "sha256:" + hashlib.sha256(current_body.encode()).hexdigest()
        except subprocess.CalledProcessError as e:
            print(f"Warning: could not fetch issue body: {e}", file=sys.stderr)
            current_hash = ""

        if current_hash and current_hash != stored_hash:
            _comment(repo, issue_number,
                f"⚠️ Task body has been modified since escrow. "
                f"Claim by `{agent_id}` paused — @peachgabba22 review needed.\n"
                f"(body hash mismatch on issue #{issue_number})")
            print(f"Hash mismatch on #{issue_number}: stored={stored_hash} current={current_hash}")
            return 1

    # All checks passed
    _add_label(repo, issue_number, "claimed")
    _set_assignee(repo, issue_number, commenter_login)
    _comment(repo, issue_number,
        f"Claim received — `{agent_id}` is on it. "
        "Tide will process the ledger entry within ~15 min.")
    print(f"Claim fast-processed: {agent_id} on #{issue_number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
