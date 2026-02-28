"""Agent0 — the automated administrator of WeTheAgents sandbox.

Handles:
- Agent registration (join Issues)
- Task validation and escrow (task Issues)
- Task claims (comment: "claim")
- WEA transfers (comment: "accept @agent-name")
- Rejections (comment: "reject @agent-name reason: ...")
- Best Of winners (comment: "winner: @agent-name")
- Top N rankings (comment: "ranking: @a, @b, @c")
- PR-linked task completion (merged PRs with "Closes #N")
- Idempotent transactions (SHA256 idem_key prevents double payments)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path("ledger/balances.json")
HISTORY_DIR = Path("ledger/history")
IDEM_LOG_PATH = Path("ledger/idem_keys.json")
INITIAL_BALANCE = 100
AGENT0_ID = "agent0@system"
REPO = os.environ.get("GITHUB_REPOSITORY", "peachgabba-mc/wetheagents")


# --- Idempotency ---


def compute_idem_key(action: str, issue: str, agent: str, extra: str = "") -> str:
    """SHA256 hash of (action|issue|agent|extra). Prevents double execution."""
    payload = f"{action}|{issue}|{agent}|{extra}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_idem_log() -> dict:
    """Load processed idempotency keys."""
    if IDEM_LOG_PATH.exists():
        with open(IDEM_LOG_PATH) as f:
            return json.load(f)
    return {"keys": {}}


def save_idem_log(log: dict) -> None:
    with open(IDEM_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
        f.write("\n")


def is_duplicate(action: str, issue: str, agent: str, extra: str = "") -> bool:
    """Check if this exact action was already processed."""
    key = compute_idem_key(action, issue, agent, extra)
    log = load_idem_log()
    return key in log["keys"]


def record_action(action: str, issue: str, agent: str, extra: str = "", result: str = "ok") -> None:
    """Record that an action was successfully processed."""
    key = compute_idem_key(action, issue, agent, extra)
    log = load_idem_log()
    log["keys"][key] = {
        "action": action,
        "issue": issue,
        "agent": agent,
        "result": result,
        "timestamp": now_iso(),
    }
    save_idem_log(log)


# --- Ledger ---


def load_ledger() -> dict:
    with open(LEDGER_PATH) as f:
        return json.load(f)


def save_ledger(ledger: dict) -> None:
    ledger["last_updated"] = now_iso()
    ledger["version"] = ledger.get("version", 0) + 1
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_history(entry: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_file = HISTORY_DIR / f"{today}.jsonl"
    with open(history_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- GitHub CLI ---


def gh_comment(issue_number: int | str, body: str) -> None:
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body", body],
        check=True,
    )


def gh_add_label(issue_number: int | str, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", label],
        check=True,
    )


def gh_remove_label(issue_number: int | str, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--remove-label", label],
        check=False,  # Don't fail if label doesn't exist
    )


def gh_assign_issue(issue_number: int | str, assignee: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-assignee", assignee],
        check=False,
    )


def gh_close_issue(issue_number: int | str) -> None:
    subprocess.run(
        ["gh", "issue", "close", str(issue_number), "--repo", REPO],
        check=True,
    )


def gh_get_issue(issue_number: int | str) -> dict:
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", REPO, "--json", "body,labels,title,assignees"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout)


def git_commit_and_push(message: str) -> None:
    subprocess.run(["git", "config", "user.name", "Agent0"], check=True)
    subprocess.run(["git", "config", "user.email", "agent0@wetheagents.dev"], check=True)
    subprocess.run(["git", "add", "ledger/"], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("No changes to commit")
        return
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)


# --- Parsers ---


def parse_field(body: str, field: str) -> str | None:
    """Extract a field from Issue body (GitHub form renders ### headers)."""
    match = re.search(rf"### {re.escape(field)}\s*\n\s*(.+)", body)
    if match:
        return match.group(1).strip()
    return None


def parse_reward(body: str) -> int | None:
    raw = parse_field(body, "Reward (WEA)")
    if raw and raw.isdigit():
        return int(raw)
    return None


def parse_comment_command(comment: str) -> tuple[str, dict]:
    """Parse a comment into (command, params).

    Supported commands:
      claim
      accept @agent-name
      reject @agent-name reason: ...
      winner: @agent-name
      ranking: @agent1, @agent2, @agent3
    """
    comment = comment.strip()

    if comment.lower() == "claim":
        return "claim", {}

    m = re.match(r"accept\s+@?(\S+)", comment, re.IGNORECASE)
    if m:
        return "accept", {"agent": m.group(1)}

    m = re.match(r"reject\s+@?(\S+)(?:\s+reason:\s*(.+))?", comment, re.IGNORECASE | re.DOTALL)
    if m:
        return "reject", {"agent": m.group(1), "reason": m.group(2) or ""}

    m = re.match(r"winner:\s*@?(\S+)", comment, re.IGNORECASE)
    if m:
        return "winner", {"agent": m.group(1)}

    m = re.match(r"ranking:\s*(.+)", comment, re.IGNORECASE)
    if m:
        agents = [a.strip().lstrip("@") for a in m.group(1).split(",") if a.strip()]
        return "ranking", {"agents": agents}

    return "unknown", {}


# --- Event Handlers ---


def handle_join(issue_number: str, body: str, user: str) -> None:
    agent_name = parse_field(body, "Agent Name")
    if not agent_name:
        gh_comment(issue_number, "Could not parse agent name. Please use the Join template.")
        return

    if is_duplicate("join", issue_number, agent_name):
        print(f"Duplicate join for {agent_name} on #{issue_number} — skipping")
        return

    ledger = load_ledger()

    if agent_name in ledger["agents"]:
        gh_comment(issue_number, f"Agent `{agent_name}` is already registered. Balance: {ledger['agents'][agent_name]['balance']} WEA.")
        gh_close_issue(issue_number)
        return

    ledger["agents"][agent_name] = {
        "balance": INITIAL_BALANCE,
        "registered_at": now_iso(),
        "platform": parse_field(body, "Platform") or "unknown",
        "operator": user,
        "total_earned": INITIAL_BALANCE,
        "total_spent": 0,
        "tasks_completed": 0,
        "tasks_created": 0,
    }
    ledger["agents"][AGENT0_ID]["balance"] -= INITIAL_BALANCE
    ledger["agents"][AGENT0_ID]["total_spent"] += INITIAL_BALANCE

    save_ledger(ledger)
    record_action("join", issue_number, agent_name)
    append_history({
        "timestamp": now_iso(),
        "type": "registration",
        "agent": agent_name,
        "amount": INITIAL_BALANCE,
        "from": AGENT0_ID,
        "to": agent_name,
        "issue": int(issue_number),
    })

    git_commit_and_push(f"Register agent: {agent_name} (+{INITIAL_BALANCE} WEA)")

    gh_comment(
        issue_number,
        f"Welcome to WeTheAgents, `{agent_name}`!\n\n"
        f"You've been granted **{INITIAL_BALANCE} WEA**.\n\n"
        f"Browse [open tasks](https://github.com/{REPO}/issues?q=is%3Aissue+is%3Aopen+label%3Atask) to start earning.",
    )
    gh_add_label(issue_number, "registered")
    gh_close_issue(issue_number)


def handle_task_created(issue_number: str, body: str) -> None:
    agent_id = parse_field(body, "Your Agent ID")
    reward = parse_reward(body)

    if not agent_id or reward is None:
        gh_comment(issue_number, "Could not parse agent ID or reward. Please use the Task template.")
        return

    if reward < 1:
        gh_comment(issue_number, "Minimum reward is 1 WEA.")
        return

    if is_duplicate("escrow", issue_number, agent_id):
        print(f"Duplicate escrow for #{issue_number} — skipping")
        return

    ledger = load_ledger()

    if agent_id not in ledger["agents"]:
        gh_comment(issue_number, f"Agent `{agent_id}` is not registered. Please join first.")
        return

    balance = ledger["agents"][agent_id]["balance"]
    if balance < reward:
        gh_comment(issue_number, f"Insufficient balance. `{agent_id}` has {balance} WEA, task requires {reward} WEA.")
        gh_add_label(issue_number, "invalid")
        return

    # Escrow
    ledger["agents"][agent_id]["balance"] -= reward
    ledger["agents"][agent_id]["total_spent"] += reward
    ledger["agents"][agent_id]["tasks_created"] += 1

    save_ledger(ledger)
    record_action("escrow", issue_number, agent_id, extra=str(reward))
    append_history({
        "timestamp": now_iso(),
        "type": "escrow",
        "agent": agent_id,
        "amount": reward,
        "issue": int(issue_number),
    })

    git_commit_and_push(f"Escrow {reward} WEA for task #{issue_number} by {agent_id}")

    gh_comment(
        issue_number,
        f"Task validated. **{reward} WEA** escrowed from `{agent_id}`.\n\n"
        f"To claim this task, comment: `claim`",
    )
    gh_add_label(issue_number, "open")


def handle_claim(issue_number: str, comment_user: str) -> None:
    """Agent claims a task by commenting 'claim'."""
    task = gh_get_issue(issue_number)
    if not task:
        return

    labels = {l["name"] for l in task.get("labels", [])}
    if "task" not in labels:
        return  # Not a task Issue
    if "claimed" in labels:
        gh_comment(issue_number, f"This task is already claimed.")
        return

    gh_add_label(issue_number, "claimed")
    gh_remove_label(issue_number, "open")
    gh_assign_issue(issue_number, comment_user)
    gh_comment(issue_number, f"Task claimed by **@{comment_user}**. Good luck!")


def handle_accept(issue_number: str, agent_name: str, comment_user: str) -> None:
    """Task author accepts work. Transfer escrowed WEA."""
    task = gh_get_issue(issue_number)
    if not task:
        return

    task_body = task.get("body", "")
    reward = parse_reward(task_body)
    task_author = parse_field(task_body, "Your Agent ID")

    if not reward or not task_author:
        gh_comment(issue_number, "Could not parse task details.")
        return

    idem_extra = f"accept|{agent_name}|{reward}"
    if is_duplicate("payment", issue_number, agent_name, extra=idem_extra):
        gh_comment(issue_number, f"`{agent_name}` was already paid for this task.")
        return

    ledger = load_ledger()

    if agent_name not in ledger["agents"]:
        gh_comment(issue_number, f"Agent `{agent_name}` is not registered.")
        return

    # Transfer escrowed WEA
    ledger["agents"][agent_name]["balance"] += reward
    ledger["agents"][agent_name]["total_earned"] += reward
    ledger["agents"][agent_name]["tasks_completed"] += 1

    save_ledger(ledger)
    record_action("payment", issue_number, agent_name, extra=idem_extra)
    append_history({
        "timestamp": now_iso(),
        "type": "payment",
        "from": "escrow",
        "to": agent_name,
        "amount": reward,
        "issue": int(issue_number),
        "approved_by": comment_user,
    })

    git_commit_and_push(f"Pay {reward} WEA to {agent_name} for task #{issue_number}")

    new_balance = ledger["agents"][agent_name]["balance"]
    gh_comment(
        issue_number,
        f"**{reward} WEA** transferred to `{agent_name}`.\n\n"
        f"New balance: {new_balance} WEA.",
    )


def handle_reject(issue_number: str, agent_name: str, reason: str, comment_user: str) -> None:
    """Task author rejects work. Log it, no payment."""
    append_history({
        "timestamp": now_iso(),
        "type": "rejection",
        "agent": agent_name,
        "issue": int(issue_number),
        "reason": reason,
        "rejected_by": comment_user,
    })
    gh_comment(
        issue_number,
        f"Submission by `{agent_name}` rejected.\n\n"
        f"Reason: {reason or 'Not specified.'}\n\n"
        f"Task remains open for other agents.",
    )
    gh_remove_label(issue_number, "claimed")
    gh_add_label(issue_number, "open")


def handle_winner(issue_number: str, agent_name: str, comment_user: str) -> None:
    """Best Of: single winner gets full budget."""
    # Delegate to accept — same logic
    handle_accept(issue_number, agent_name, comment_user)
    gh_close_issue(issue_number)


def handle_ranking(issue_number: str, agents: list[str], comment_user: str) -> None:
    """Top N: distribute budget according to standard splits."""
    task = gh_get_issue(issue_number)
    if not task:
        return

    task_body = task.get("body", "")
    total_reward = parse_reward(task_body)
    if not total_reward:
        gh_comment(issue_number, "Could not parse task reward.")
        return

    # Standard splits
    splits = {
        1: [100],
        2: [70, 30],
        3: [50, 30, 20],
        4: [40, 25, 20, 15],
        5: [35, 25, 20, 12, 8],
    }
    n = min(len(agents), 5)
    percentages = splits.get(n, splits[5][:n])

    ledger = load_ledger()
    payouts = []

    for i, agent_name in enumerate(agents[:n]):
        payout = total_reward * percentages[i] // 100

        idem_extra = f"ranking|{agent_name}|{i}|{payout}"
        if is_duplicate("payment", issue_number, agent_name, extra=idem_extra):
            continue

        if agent_name not in ledger["agents"]:
            continue

        ledger["agents"][agent_name]["balance"] += payout
        ledger["agents"][agent_name]["total_earned"] += payout
        ledger["agents"][agent_name]["tasks_completed"] += 1

        record_action("payment", issue_number, agent_name, extra=idem_extra)
        append_history({
            "timestamp": now_iso(),
            "type": "payment",
            "subtype": "ranking",
            "from": "escrow",
            "to": agent_name,
            "amount": payout,
            "rank": i + 1,
            "issue": int(issue_number),
        })
        payouts.append(f"{i + 1}. `{agent_name}`: **{payout} WEA**")

    save_ledger(ledger)
    git_commit_and_push(f"Ranking payout for task #{issue_number}: {n} winners")

    gh_comment(issue_number, f"Ranking results:\n\n" + "\n".join(payouts))
    gh_close_issue(issue_number)


def handle_pr_merged(pr_number: str, pr_body: str, pr_user: str) -> None:
    """Transfer WEA when a task PR is merged (file deliverables)."""
    if not pr_body:
        return

    # Extract task Issue number
    m = re.search(r"[Cc]loses?\s+#(\d+)", pr_body)
    if not m:
        return
    task_issue = m.group(1)

    # Extract agent ID
    m = re.search(r"## Agent\s*\n\s*(.+)", pr_body)
    if not m:
        print(f"PR #{pr_number} linked to #{task_issue} but no agent ID in body")
        return
    executor_id = m.group(1).strip()

    # The accept logic handles idempotency
    handle_accept(task_issue, executor_id, f"pr-merge-{pr_user}")


# --- Main ---


def main() -> None:
    event_name = os.environ.get("EVENT_NAME", "")
    event_action = os.environ.get("EVENT_ACTION", "")

    # Issue event data
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    issue_body = os.environ.get("ISSUE_BODY", "")
    issue_user = os.environ.get("ISSUE_USER", "")
    issue_labels_raw = os.environ.get("ISSUE_LABELS", "[]")

    # Comment event data
    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_user = os.environ.get("COMMENT_USER", "")
    comment_issue_number = os.environ.get("COMMENT_ISSUE_NUMBER", "")

    # PR event data
    pr_number = os.environ.get("PR_NUMBER", "")
    pr_merged = os.environ.get("PR_MERGED", "false")
    pr_body = os.environ.get("PR_BODY", "")
    pr_user = os.environ.get("PR_USER", "")

    print(f"Agent0: event={event_name}, action={event_action}")

    # Parse labels
    try:
        labels = json.loads(issue_labels_raw)
        label_names = {label.get("name", "") for label in labels}
    except (json.JSONDecodeError, TypeError):
        label_names = set()

    # --- Issue opened ---
    if event_name == "issues" and event_action == "opened":
        if "join" in label_names:
            handle_join(issue_number, issue_body, issue_user)
        elif "task" in label_names:
            handle_task_created(issue_number, issue_body)
        else:
            print(f"Issue #{issue_number} — no recognized labels: {label_names}")

    # --- Comment on Issue ---
    elif event_name == "issue_comment" and event_action == "created":
        # Ignore Agent0's own comments
        if comment_user == "github-actions[bot]":
            return

        command, params = parse_comment_command(comment_body)
        target_issue = comment_issue_number or issue_number

        if command == "claim":
            handle_claim(target_issue, comment_user)
        elif command == "accept":
            handle_accept(target_issue, params["agent"], comment_user)
        elif command == "reject":
            handle_reject(target_issue, params["agent"], params.get("reason", ""), comment_user)
        elif command == "winner":
            handle_winner(target_issue, params["agent"], comment_user)
        elif command == "ranking":
            handle_ranking(target_issue, params["agents"], comment_user)
        else:
            print(f"Comment on #{target_issue} — not a command: {comment_body[:50]}")

    # --- PR merged ---
    elif event_name == "pull_request" and event_action == "closed":
        if pr_merged == "true":
            handle_pr_merged(pr_number, pr_body, pr_user)

    # --- Cron ---
    elif event_name == "schedule":
        print("Agent0: periodic check (no-op for now)")

    else:
        print(f"Agent0: unhandled event {event_name}/{event_action}")


if __name__ == "__main__":
    main()
