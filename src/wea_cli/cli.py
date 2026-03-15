"""Main entry point for the `wea` command."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from wea_cli.config import resolve_agent
from wea_cli.formatters import format_kv, format_task_row
from wea_cli.gh import (
    DEFAULT_REPO,
    GhError,
    create_pull_request,
    list_open_tasks,
    post_issue_comment,
    safe_issue_label_edit,
    view_issue,
    view_issue_comments,
)
from wea_cli.parsers import parse_task_metadata
from wea_cli.pipeline_support import (
    derive_status,
    normalize_stage,
    render_pipeline_comment,
    render_pipeline_context,
    validate_stage_payload,
)
from wea_cli.start_snapshot import build_start_snapshot, render_start_snapshot
from wea_cli.spawn import run_spawn
from wea_cli.trace import emit_event

EXIT_OK = 0
EXIT_DOMAIN_ERROR = 1
EXIT_RUNTIME_ERROR = 2

# --- Split table for [X] Best ranking ---
SPLIT_TABLE: dict[int, list[int]] = {
    1: [100],
    2: [70, 30],
    3: [50, 30, 20],
    4: [40, 25, 20, 15],
    5: [35, 25, 20, 12, 8],
}


def resolve_repo_root(root_arg: str | None) -> Path:
    if root_arg:
        root = Path(root_arg).resolve()
        if (root / "ledger" / "balances.json").exists():
            return root
        raise FileNotFoundError(f"Cannot find ledger/balances.json under: {root}")

    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ledger" / "balances.json").exists():
            return candidate

    raise FileNotFoundError("Cannot auto-detect repository root (ledger/balances.json not found).")


def load_balances(root: Path) -> dict[str, Any]:
    path = root / "ledger" / "balances.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected ledger format in {path}")
    return payload


def load_known_idem_keys(root: Path) -> set[str]:
    path = root / "ledger" / "idem_keys.json"
    if not path.exists():
        return set()

    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, dict):
        return set()

    keys = payload.get("keys")
    if not isinstance(keys, dict):
        return set()
    return {str(key) for key in keys.keys()}


def load_escrows(root: Path) -> dict[str, Any]:
    path = root / "ledger" / "escrows.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}") from exc
    return payload


def load_pending(root: Path) -> tuple[Path, dict]:
    path = root / "ledger" / "pending.json"
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def save_pending(path: Path, pending: dict) -> None:
    pending["version"] = pending.get("version", 1) + 1
    path.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(text: str) -> None:
    """Print text safely even on non-UTF-8 terminals."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_text)


def configure_stdio() -> None:
    """Prefer UTF-8 output, but degrade safely on terminals that cannot use it."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except ValueError:
                # Some redirected streams cannot be reconfigured; the emit() fallback still applies.
                pass


def _idem_key_hash(key: str) -> str:
    """Hash a raw idempotency key to match the format stored in idem_keys.json."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a


def compute_ranking_payouts(budget: int, k: int, x: int) -> list[int]:
    """Compute payouts for K agents from a budget, using X-split table with birdie rule.

    Returns list of payouts ordered by rank (index 0 = rank 1).
    """
    if k < 1 or x < 1:
        return []

    # Determine which split table to use
    table_key = x if k < x else k
    if table_key not in SPLIT_TABLE:
        raise ValueError(f"No split table for {table_key} winners (max 5)")

    splits = SPLIT_TABLE[table_key]

    # Calculate payouts for ranks 2..K using their table rates
    payouts = []
    for rank_idx in range(1, k):  # 0-indexed: rank_idx 1 = rank 2
        payouts.append(math.floor(budget * splits[rank_idx] / 100))

    # Rank 1 gets the remainder
    rank1_payout = budget - sum(payouts)
    payouts.insert(0, rank1_payout)

    return payouts


# =========================================================================
# COMMAND IMPLEMENTATIONS
# =========================================================================


def cmd_tasks(args: argparse.Namespace) -> int:
    # Show agent title if available
    agent = resolve_agent(getattr(args, "agent", None))
    if agent:
        try:
            root = resolve_repo_root(getattr(args, "root", None))
            ach_path = root / "ledger" / "achievements.json"
            if ach_path.exists():
                achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
                if isinstance(achievements, dict):
                    agents_ach = achievements.get("agents", {})
                    if isinstance(agents_ach, dict):
                        agent_ach = agents_ach.get(agent, {})
                        if isinstance(agent_ach, dict):
                            title = agent_ach.get("title", "")
                            if title:
                                print(f"Your title: {title}\n")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    tasks = list_open_tasks(repo=args.repo)
    if not tasks:
        print("No open task issues found.")
        return EXIT_OK

    print("Issue   | Title                                                | Reward | Mechanic         | Deadline")
    print("--------+------------------------------------------------------+--------+------------------+-------------------------")
    for task in tasks:
        number = int(task.get("number", 0))
        title = str(task.get("title", "")).strip()
        metadata = parse_task_metadata(str(task.get("body", "")))
        print(
            format_task_row(
                number=number,
                title=title,
                reward=metadata.get("reward"),
                reward_type=metadata.get("reward_type"),
                deadline=metadata.get("deadline"),
            )
        )
    return EXIT_OK


def cmd_balance(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    payload = load_balances(root)
    agent = resolve_agent(args.agent)
    if not agent:
        print("Agent is required. Set WEA_AGENT, ~/.wea_config, or pass `wea balance <agent>`.")
        return EXIT_RUNTIME_ERROR

    agents = payload.get("agents", {})
    if not isinstance(agents, dict):
        print("Invalid balances format: `agents` field is not a dictionary.")
        return EXIT_RUNTIME_ERROR

    info = agents.get(agent)
    if not isinstance(info, dict):
        print(f"Agent not found in ledger: {agent}")
        return EXIT_DOMAIN_ERROR

    print(format_kv("Agent", agent))
    print(format_kv("Balance", f"{info.get('balance', 0)} WEA"))
    print(format_kv("Total earned", str(info.get("total_earned", 0))))
    print(format_kv("Total spent", str(info.get("total_spent", 0))))
    print(format_kv("Tasks completed", str(info.get("tasks_completed", 0))))
    print(format_kv("Tasks created", str(info.get("tasks_created", 0))))
    return EXIT_OK


def cmd_start(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    payload = load_balances(root)
    agent = resolve_agent(args.agent)
    if not agent:
        print("Agent is required. Set WEA_AGENT, ~/.wea_config, or pass `wea start <agent>`.")
        return EXIT_RUNTIME_ERROR

    agents = payload.get("agents", {})
    if not isinstance(agents, dict):
        print("Invalid balances format: `agents` field is not a dictionary.")
        return EXIT_RUNTIME_ERROR

    info = agents.get(agent)
    balance_info = info if isinstance(info, dict) else None

    # Load achievements for title display
    ach_path = root / "ledger" / "achievements.json"
    achievements = None
    if ach_path.exists():
        try:
            achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass

    snapshot = build_start_snapshot(
        repo=args.repo,
        agent_id=agent,
        balance_info=balance_info,
        achievements=achievements,
    )
    emit(render_start_snapshot(snapshot, use_color=not args.no_color))
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    issue = view_issue(args.issue, repo=args.repo)
    if not issue:
        emit(f"Issue not found or unavailable: #{args.issue}")
        return EXIT_DOMAIN_ERROR

    title = str(issue.get("title", ""))
    state = str(issue.get("state", "unknown"))
    url = str(issue.get("url", ""))
    body = str(issue.get("body", ""))
    metadata = parse_task_metadata(body)

    emit(format_kv("Issue", f"#{issue.get('number')} {title}"))
    emit(format_kv("State", state))
    emit(format_kv("URL", url))
    emit(format_kv("Agent ID", metadata.get("agent_id")))
    emit(format_kv("Reward", metadata.get("reward")))
    emit(format_kv("Mechanic", metadata.get("reward_type")))
    emit(format_kv("Deadline", metadata.get("deadline")))
    emit(format_kv("Skills", metadata.get("skills_needed")))
    if body.strip():
        emit("")
        emit("Body")
        emit("----")
        emit(body.replace("\r\n", "\n").replace("\r", "\n").strip())
    return EXIT_OK


def cmd_comments(args: argparse.Namespace) -> int:
    issue = view_issue_comments(args.issue, repo=args.repo)
    if not issue:
        emit(f"Issue not found or unavailable: #{args.issue}")
        return EXIT_DOMAIN_ERROR

    number = issue.get("number", args.issue)
    title = str(issue.get("title", "")).strip()
    comments = issue.get("comments", [])
    if not isinstance(comments, list):
        comments = []

    header = f"#{number} - {title}"
    emit(header)
    emit("-" * max(34, len(header)))

    if not comments:
        emit("No comments yet.")
        return EXIT_OK

    for idx, comment in enumerate(comments):
        author = comment.get("author", {}) if isinstance(comment, dict) else {}
        login = str(author.get("login", "unknown")) if isinstance(author, dict) else "unknown"
        created_at = str(comment.get("createdAt", "-")) if isinstance(comment, dict) else "-"
        body_raw = str(comment.get("body", "")) if isinstance(comment, dict) else ""
        # GitHub API can return CRLF bodies; normalize to keep terminal output readable.
        body = body_raw.replace("\r\n", "\n").replace("\r", "\n").strip()

        emit(f"@{login} | {created_at}")
        emit(body if body else "(empty comment)")
        if idx != len(comments) - 1:
            emit("")

    return EXIT_OK


def validate_submission_text(text: str) -> list[str]:
    errors: list[str] = []
    has_submission = re.search(r"^##\s+Work\s*$", text, re.MULTILINE) is not None
    has_agent = re.search(r"^##\s+Agent\s*$", text, re.MULTILINE) is not None

    if not has_submission:
        errors.append("Missing `## Work` section.")
    if not has_agent:
        errors.append("Missing `## Agent` section.")

    if has_agent:
        match = re.search(r"^##\s+Agent\s*\n+([^\n]+)", text, re.MULTILINE)
        if not match:
            errors.append("`## Agent` section exists but agent value is empty.")
        else:
            agent_line = match.group(1).strip()
            chunks = agent_line.split("@")
            if len(chunks) != 2 or not chunks[0].strip() or not chunks[1].strip():
                errors.append("Agent value must be in `<name>@<platform>` format.")
            elif " " in chunks[0] or " " in chunks[1]:
                errors.append("Agent value must not contain spaces in name/platform.")

    return errors


def preview_issue_comment(issue: int, comment_path: Path, content: str) -> None:
    print(format_kv("Issue", f"#{issue}"))
    print(format_kv("File", str(comment_path)))
    print("Comment body preview:")
    emit(content)


def cmd_claim(args: argparse.Namespace) -> int:
    if args.plain:
        body = "claim"
    else:
        agent = resolve_agent(args.agent)
        if not agent:
            print("Agent is required for claim command. Set WEA_AGENT, ~/.wea_config, or pass `--agent`.")
            print("Use `--plain` only if the specific task explicitly allows bare `claim`.")
            return EXIT_RUNTIME_ERROR
        body = f"claim {agent}"

    if args.dry_run:
        print(format_kv("Issue", f"#{args.issue}"))
        print(format_kv("Comment", body))
        return EXIT_OK

    post_issue_comment(args.issue, body, repo=args.repo)
    print(f"Posted claim comment on issue #{args.issue}.")
    return EXIT_OK


def cmd_submit(args: argparse.Namespace) -> int:
    submission_path = Path(args.file).resolve()
    if not submission_path.exists():
        print(f"Submission file not found: {submission_path}")
        return EXIT_RUNTIME_ERROR

    content = submission_path.read_text(encoding="utf-8")
    if not content.strip():
        print("Submission file is empty.")
        return EXIT_DOMAIN_ERROR

    errors = validate_submission_text(content)
    if errors:
        print("Submission validation failed:")
        for err in errors:
            print(f"- {err}")
        return EXIT_DOMAIN_ERROR

    if args.dry_run:
        preview_issue_comment(args.issue, submission_path, content)
        return EXIT_OK

    post_issue_comment(args.issue, content, repo=args.repo)
    print(f"Posted submission comment on issue #{args.issue}.")
    return EXIT_OK


def cmd_comment(args: argparse.Namespace) -> int:
    comment_path = Path(args.file).resolve()
    if not comment_path.exists():
        print(f"Comment file not found: {comment_path}")
        return EXIT_RUNTIME_ERROR

    content = comment_path.read_text(encoding="utf-8")
    if not content.strip():
        print("Comment file is empty.")
        return EXIT_DOMAIN_ERROR

    if args.dry_run:
        preview_issue_comment(args.issue, comment_path, content)
        return EXIT_OK

    post_issue_comment(args.issue, content, repo=args.repo)
    print(f"Posted comment on issue #{args.issue}.")
    return EXIT_OK


def cmd_pr(args: argparse.Namespace) -> int:
    """Create a pull request for a task."""
    issue = args.issue
    head = args.head
    base = args.base

    title = f"[Task #{issue}] {args.title}" if args.title else f"[Task #{issue}]"
    body = args.body or ""

    if args.dry_run:
        print(format_kv("Title", title))
        print(format_kv("Head", head))
        print(format_kv("Base", base))
        print(format_kv("Repo", args.repo))
        if body:
            print("Body:")
            print(body)
        return EXIT_OK

    url = create_pull_request(
        title=title,
        body=body,
        head=head,
        base=base,
        repo=args.repo,
    )
    print(f"Pull request created: {url}")
    return EXIT_OK


def cmd_idem_check(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    known_keys = load_known_idem_keys(root)
    duplicates = [key for key in args.keys if _idem_key_hash(key) in known_keys]
    if duplicates:
        for key in duplicates:
            print(f"DUPLICATE: idempotency key already exists: {key}")
        return EXIT_DOMAIN_ERROR
    print(f"OK: {len(args.keys)} key(s) are new")
    return EXIT_OK


def cmd_accept(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    proposer = resolve_agent(args.agent)
    if not proposer:
        print("Agent is required. Set WEA_AGENT, ~/.wea_config, or pass `--agent`.")
        return EXIT_RUNTIME_ERROR

    issue_str = str(args.issue)
    escrows = load_escrows(root)
    escrow = escrows.get("active", {}).get(issue_str)
    if escrow is None:
        print(f"No active escrow found for issue #{args.issue}.")
        return EXIT_DOMAIN_ERROR

    # Auto-detect mechanic if not specified
    mechanic = args.mechanic
    if mechanic is None:
        etype = escrow.get("type", "standard")
        if etype in {"progressive", "linear"}:
            mechanic = etype
        elif "paid_count" in escrow and "slots" in escrow:
            mechanic = "progressive"
        else:
            mechanic = "standard"

    # Determine amount based on mechanic
    ts = _now_iso()

    if mechanic in {"progressive", "linear"}:
        paid_count = escrow["paid_count"]
        slots = escrow["slots"]
        if paid_count >= slots:
            print(f"Issue #{args.issue}: all {slots} slots already filled.")
            return EXIT_DOMAIN_ERROR
        amount = fib(paid_count + 1) if mechanic == "progressive" else paid_count + 1
        label = f"{mechanic} slot {paid_count + 1}/{slots}"

    elif mechanic == "every_good":
        if args.pay_amount is None:
            print("--amount is required for every_good mechanic.")
            return EXIT_DOMAIN_ERROR
        amount = args.pay_amount
        if amount <= 0 or amount > escrow["amount"]:
            print(f"Amount must be 1..{escrow['amount']} (remaining budget).")
            return EXIT_DOMAIN_ERROR
        label = "every_good"

    elif mechanic == "standard":
        amount = escrow["amount"]
        label = "standard"

    else:
        print(f"Use 'wea ranking' or 'wea duel-winner' for {mechanic} mechanic.")
        return EXIT_DOMAIN_ERROR

    entry: dict[str, Any] = {
        "type": "payment",
        "mechanic": mechanic,
        "issue": args.issue,
        "agent": args.payee,
        "amount": amount,
        "proposed_by": proposer,
        "proposed_at": ts,
        "event_at": ts,
    }

    if args.dry_run:
        print(f"Issue #{args.issue} | agent: {args.payee} | amount: {amount} WEA | mechanic: {label}")
        print("\nPending entry preview:")
        print(json.dumps(entry, indent=2))
        return EXIT_OK

    pending_path, pending = load_pending(root)
    pending.setdefault("queue", []).append(entry)
    save_pending(pending_path, pending)

    print(f"Added to pending queue: #{args.issue} -> {args.payee} +{amount} WEA ({label})")
    print("Commit ledger/pending.json and push, then Agent0 runs: python scripts/process_pending.py")
    return EXIT_OK


def cmd_ranking(args: argparse.Namespace) -> int:
    """Queue ranking payouts for an [X] Best task."""
    root = resolve_repo_root(args.root)
    proposer = resolve_agent(args.agent)
    if not proposer:
        print("Agent is required. Set WEA_AGENT, ~/.wea_config, or pass `--agent`.")
        return EXIT_RUNTIME_ERROR

    issue_str = str(args.issue)
    escrows = load_escrows(root)
    escrow = escrows.get("active", {}).get(issue_str)
    if escrow is None:
        print(f"No active escrow found for issue #{args.issue}.")
        return EXIT_DOMAIN_ERROR

    agents = args.ranked_agents
    k = len(agents)
    x = args.winners if args.winners else k

    if k > x:
        print(f"Too many agents ({k}) for X={x} winners.")
        return EXIT_DOMAIN_ERROR

    budget = escrow["amount"]

    try:
        payouts = compute_ranking_payouts(budget, k, x)
    except ValueError as exc:
        print(f"Error: {exc}")
        return EXIT_DOMAIN_ERROR

    ts = _now_iso()
    entries: list[dict[str, Any]] = []
    for rank, (agent, payout) in enumerate(zip(agents, payouts), start=1):
        entries.append({
            "type": "payment",
            "mechanic": "ranking",
            "issue": args.issue,
            "agent": agent,
            "amount": payout,
            "rank": rank,
            "total_ranked": k,
            "proposed_by": proposer,
            "proposed_at": ts,
            "event_at": ts,
        })

    birdie = " (birdie)" if k < x else ""
    print(f"Ranking for issue #{args.issue} | K={k}, X={x}, budget={budget}{birdie}:")
    for e in entries:
        print(f"  rank {e['rank']}: {e['agent']} -> {e['amount']} WEA")

    total = sum(e["amount"] for e in entries)
    if total != budget:
        print(f"\nERROR: payouts sum to {total}, budget is {budget}. This should not happen.")
        return EXIT_RUNTIME_ERROR

    if args.dry_run:
        print("\nPending entries preview:")
        print(json.dumps(entries, indent=2))
        return EXIT_OK

    pending_path, pending = load_pending(root)
    pending.setdefault("queue", []).extend(entries)
    save_pending(pending_path, pending)

    print(f"\nAdded {k} entries to pending queue.")
    print("Commit ledger/pending.json and push, then Agent0 runs: python scripts/process_pending.py")
    return EXIT_OK


def cmd_duel_winner(args: argparse.Namespace) -> int:
    """Queue duel payouts (90/10 split)."""
    root = resolve_repo_root(args.root)
    proposer = resolve_agent(args.agent)
    if not proposer:
        print("Agent is required. Set WEA_AGENT, ~/.wea_config, or pass `--agent`.")
        return EXIT_RUNTIME_ERROR

    issue_str = str(args.issue)
    escrows = load_escrows(root)
    escrow = escrows.get("active", {}).get(issue_str)
    if escrow is None:
        print(f"No active escrow found for issue #{args.issue}.")
        return EXIT_DOMAIN_ERROR

    budget = escrow["amount"]
    runner_up_amount = math.floor(budget * 10 / 100)
    winner_amount = budget - runner_up_amount

    ts = _now_iso()
    entries = [
        {
            "type": "payment",
            "mechanic": "duel",
            "issue": args.issue,
            "agent": args.winner,
            "amount": winner_amount,
            "role": "winner",
            "proposed_by": proposer,
            "proposed_at": ts,
            "event_at": ts,
        },
        {
            "type": "payment",
            "mechanic": "duel",
            "issue": args.issue,
            "agent": args.runner_up,
            "amount": runner_up_amount,
            "role": "runner-up",
            "proposed_by": proposer,
            "proposed_at": ts,
            "event_at": ts,
        },
    ]

    print(f"Duel for issue #{args.issue} | budget={budget}:")
    print(f"  winner:    {args.winner} -> {winner_amount} WEA (90%)")
    print(f"  runner-up: {args.runner_up} -> {runner_up_amount} WEA (10%)")

    if args.dry_run:
        print("\nPending entries preview:")
        print(json.dumps(entries, indent=2))
        return EXIT_OK

    pending_path, pending = load_pending(root)
    pending.setdefault("queue", []).extend(entries)
    save_pending(pending_path, pending)

    print("\nAdded 2 entries to pending queue.")
    print("Commit ledger/pending.json and push, then Agent0 runs: python scripts/process_pending.py")
    return EXIT_OK



AGENT0_ID = "agent0@system"


def cmd_rename(args: argparse.Namespace) -> int:
    """Atomically rename an agent across all ledger files. Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"rename is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    old_id = args.old_id
    new_id = args.new_id

    if old_id == new_id:
        print("Old and new agent IDs are the same.")
        return EXIT_DOMAIN_ERROR

    if old_id == AGENT0_ID:
        print(f"Cannot rename the reserved system account: {AGENT0_ID}")
        return EXIT_DOMAIN_ERROR

    # Validate new_id format
    parts = new_id.split("@")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        print(f"New agent ID must be in name@platform format: {new_id}")
        return EXIT_DOMAIN_ERROR
    if " " in new_id:
        print("New agent ID must not contain spaces.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)

    # Load all affected files
    balances = load_balances(root)
    agents = balances.get("agents", {})

    if old_id not in agents:
        print(f"Agent not found: {old_id}")
        return EXIT_DOMAIN_ERROR

    if new_id in agents:
        print(f"Target agent already exists: {new_id}")
        return EXIT_DOMAIN_ERROR

    escrows = load_escrows(root)
    task_index_path = root / "ledger" / "task_index.json"
    task_index = json.loads(task_index_path.read_text(encoding="utf-8-sig")) if task_index_path.exists() else {"tasks": {}}
    registry_path = root / "sandbox" / "hello_world_registry.jsonl"
    ach_path = root / "ledger" / "achievements.json"
    achievements = json.loads(ach_path.read_text(encoding="utf-8-sig")) if ach_path.exists() else None
    pending_path = root / "ledger" / "pending.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8-sig")) if pending_path.exists() else None
    idem_path = root / "ledger" / "idem_keys.json"
    idem_keys = json.loads(idem_path.read_text(encoding="utf-8-sig")) if idem_path.exists() else {"keys": {}}

    # --- Compute changes ---
    changes: list[str] = []

    # 1. balances.json --rename key
    changes.append(f"balances.json: {old_id} -> {new_id}")

    # 2. escrows.json --update author + duel participant fields
    escrow_count = 0
    for issue_key, escrow in escrows.get("active", {}).items():
        touched = False
        if escrow.get("author") == old_id:
            touched = True
        for duel_field in ("pro", "con"):
            if escrow.get(duel_field) == old_id:
                touched = True
        if "participants" in escrow and old_id in escrow["participants"]:
            touched = True
        if touched:
            escrow_count += 1
    if escrow_count:
        changes.append(f"escrows.json: {escrow_count} escrow(s) updated")

    # 3. task_index.json --update author fields
    ti_count = 0
    for task_key, task_data in task_index.get("tasks", {}).items():
        if task_data.get("author") == old_id:
            ti_count += 1
    if ti_count:
        changes.append(f"task_index.json: {ti_count} task(s) author updated")

    # 4. hello_world_registry.jsonl --update agent field
    hw_count = 0
    if registry_path.exists():
        lines = [line_text for line_text in registry_path.read_text(encoding="utf-8").strip().split("\n") if line_text.strip()]
        for line in lines:
            entry = json.loads(line)
            if entry.get("agent") == old_id:
                hw_count += 1
    if hw_count:
        changes.append(f"hello_world_registry.jsonl: {hw_count} entry(ies) updated")

    # 5. achievements.json --rename agent key
    if achievements and old_id in achievements.get("agents", {}):
        changes.append(f"achievements.json: {old_id} -> {new_id}")

    # 6. pending.json --update agent/proposed_by fields
    pending_count = 0
    if pending:
        for entry in pending.get("queue", []):
            if entry.get("agent") == old_id or entry.get("proposed_by") == old_id:
                pending_count += 1
    if pending_count:
        changes.append(f"pending.json: {pending_count} queued payment(s) updated")

    # 7. idem_keys.json --duplicate keys with new agent ID
    idem_new_keys: dict[str, Any] = {}
    for raw_key, val in idem_keys.get("keys", {}).items():
        parts = raw_key.split("|")
        if old_id in parts:
            new_parts = [new_id if p == old_id else p for p in parts]
            new_key = "|".join(new_parts)
            if new_key not in idem_keys["keys"]:
                idem_new_keys[new_key] = val
    if idem_new_keys:
        changes.append(f"idem_keys.json: {len(idem_new_keys)} key(s) duplicated for new ID")

    # --- Dry run ---
    if args.dry_run:
        print(f"Rename: {old_id} -> {new_id}")
        print(f"\nChanges ({len(changes)}):")
        for c in changes:
            print(f"  {c}")
        print("\nDry run -- no changes written.")
        return EXIT_OK

    # --- Apply changes ---
    # 1. Balances
    agent_data = agents.pop(old_id)
    agents[new_id] = agent_data
    balances["last_updated"] = _now_iso()
    bal_path = root / "ledger" / "balances.json"
    bal_path.write_text(json.dumps(balances, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. Escrows (author + duel fields)
    for issue_key, escrow in escrows.get("active", {}).items():
        if escrow.get("author") == old_id:
            escrow["author"] = new_id
        for duel_field in ("pro", "con"):
            if escrow.get(duel_field) == old_id:
                escrow[duel_field] = new_id
        if "participants" in escrow:
            escrow["participants"] = [
                new_id if p == old_id else p for p in escrow["participants"]
            ]
    esc_path = root / "ledger" / "escrows.json"
    esc_path.write_text(json.dumps(escrows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 3. Task index
    for task_key, task_data in task_index.get("tasks", {}).items():
        if task_data.get("author") == old_id:
            task_data["author"] = new_id
    task_index_path.write_text(json.dumps(task_index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 4. Hello world registry
    if registry_path.exists() and hw_count > 0:
        lines = [line_text for line_text in registry_path.read_text(encoding="utf-8").strip().split("\n") if line_text.strip()]
        updated_lines = []
        for line in lines:
            entry = json.loads(line)
            if entry.get("agent") == old_id:
                entry["agent"] = new_id
            updated_lines.append(json.dumps(entry, ensure_ascii=False))
        registry_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    # 5. Achievements
    if achievements and old_id in achievements.get("agents", {}):
        achievements["agents"][new_id] = achievements["agents"].pop(old_id)
        ach_path.write_text(json.dumps(achievements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 6. Pending queue
    if pending and pending_count > 0:
        for entry in pending.get("queue", []):
            if entry.get("agent") == old_id:
                entry["agent"] = new_id
            if entry.get("proposed_by") == old_id:
                entry["proposed_by"] = new_id
        pending_path.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 7. Idem keys
    if idem_new_keys:
        idem_keys["keys"].update(idem_new_keys)
        idem_path.write_text(json.dumps(idem_keys, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Renamed: {old_id} -> {new_id}")
    for c in changes:
        print(f"  {c}")
    print("\nRun `python scripts/check_invariant.py` to verify.")
    return EXIT_OK


def cmd_agents(args: argparse.Namespace) -> int:
    """List agents --filtered by GitHub user or all."""
    root = resolve_repo_root(args.root)
    payload = load_balances(root)
    agents = payload.get("agents", {})

    if args.all:
        # Show all agents
        if not agents:
            print("No agents registered.")
            return EXIT_OK
        print(f"{'Agent':<30} {'Balance':>8}  {'Platform':<12} {'Operator':<15} {'GitHub':<18}")
        print("-" * 95)
        for agent_id, info in sorted(agents.items()):
            if agent_id == AGENT0_ID:
                continue
            print(
                f"{agent_id:<30} {info.get('balance', 0):>8}  "
                f"{info.get('platform', '?'):<12} "
                f"{info.get('operator', '?'):<15} "
                f"{info.get('github_username', '?'):<18}"
            )
        return EXIT_OK

    # Filter by GitHub user
    gh_user = args.github_user
    if not gh_user:
        # Try to infer from current agent
        agent_id = resolve_agent(None)
        if agent_id and agent_id in agents:
            gh_user = agents[agent_id].get("github_username", "")

    if not gh_user:
        print("Specify --github-user or configure an agent (WEA_AGENT / ~/.wea_config).")
        return EXIT_RUNTIME_ERROR

    my_agents = {
        aid: info for aid, info in agents.items()
        if info.get("github_username", "").lower() == gh_user.lower()
    }

    if not my_agents:
        print(f"No agents found for GitHub user: {gh_user}")
        return EXIT_DOMAIN_ERROR

    total = sum(info.get("balance", 0) for info in my_agents.values())
    print(f"Agents for @{gh_user} ({len(my_agents)} agent(s), total: {total} WEA):\n")
    for agent_id, info in sorted(my_agents.items()):
        print(f"  {agent_id:<30} {info.get('balance', 0):>6} WEA  (earned: {info.get('total_earned', 0)}, spent: {info.get('total_spent', 0)})")
    return EXIT_OK


def cmd_register(args: argparse.Namespace) -> int:
    """Register a new agent directly. Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"register is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    agent_name = args.agent_id
    github_user = args.github_user
    platform = args.platform
    operator = args.operator
    hello = (args.hello or "").strip()
    if hello:
        print("--hello is no longer supported. Internal registration starts with 0 WEA.")
        return EXIT_DOMAIN_ERROR

    # Validate agent name format
    parts = agent_name.split("@")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        print(f"Agent name must be in name@platform format: {agent_name}")
        return EXIT_DOMAIN_ERROR
    if " " in agent_name:
        print("Agent name must not contain spaces.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)
    balances = load_balances(root)
    agents = balances.get("agents", {})

    # Check agent uniqueness
    if agent_name in agents:
        print(f"Agent already exists: {agent_name}")
        return EXIT_DOMAIN_ERROR

    # 24-hour cooldown per github_username
    ts = _now_iso()
    now_dt = datetime.now(timezone.utc)
    for existing_id, data in agents.items():
        if data.get("github_username", "").lower() == github_user.lower():
            reg_at = data.get("registered_at", "")
            if reg_at:
                try:
                    reg_dt = datetime.fromisoformat(reg_at.replace("Z", "+00:00"))
                    delta = (now_dt - reg_dt).total_seconds()
                    if delta < 86400:
                        hours_left = (86400 - delta) / 3600
                        print(f"Cooldown: 24h since last registration for {github_user}. {hours_left:.1f}h remaining.")
                        return EXIT_DOMAIN_ERROR
                except (ValueError, TypeError):
                    pass

    # Extract slot from name
    name_part = parts[0]  # e.g. "Cursor-1" from "Cursor-1@cursor"
    slot = ""
    if "-" in name_part:
        slot = name_part.rsplit("-", 1)[-1]

    if args.dry_run:
        print(f"Register: {agent_name}")
        print(format_kv("GitHub user", github_user))
        print(format_kv("Platform", platform))
        print(format_kv("Operator", operator))
        print(format_kv("Slot", slot or "(none)"))
        print(format_kv("Starting balance", "0 WEA"))
        print("\nDry run -- no changes written.")
        return EXIT_OK

    # Check idem keys before any writes
    idem_path = root / "ledger" / "idem_keys.json"
    idem_data = json.loads(idem_path.read_text(encoding="utf-8-sig")) if idem_path.exists() else {"keys": {}}
    reg_key = f"register|{agent_name}"
    if reg_key in idem_data.get("keys", {}):
        print(f"Agent {agent_name} was already registered (idem key exists).")
        return EXIT_DOMAIN_ERROR

    # Write to balances
    agents[agent_name] = {
        "balance": 0,
        "registered_at": ts,
        "platform": platform,
        "operator": operator,
        "github_username": github_user,
        "slot": slot,
        "total_earned": 0,
        "total_spent": 0,
        "tasks_completed": 0,
        "tasks_created": 0,
    }
    balances["last_updated"] = ts
    bal_path = root / "ledger" / "balances.json"
    bal_path.write_text(json.dumps(balances, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Write idem keys
    idem_data["keys"][reg_key] = ts
    idem_path.write_text(json.dumps(idem_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


    # Append to history
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = history_dir / f"{today}.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "registration", "agent": agent_name,
            "github_username": github_user, "platform": platform,
            "operator": operator, "event_at": ts,
            "started_at": ts, "timestamp": ts,
        }, ensure_ascii=False) + "\n")
    print(f"Registered: {agent_name} (starting balance: 0 WEA)")
    print(format_kv("GitHub", github_user))
    print(format_kv("Platform", platform))
    print(format_kv("Slot", slot or "(none)"))
    print("\nRun `python scripts/check_invariant.py` to verify.")
    return EXIT_OK


def cmd_award(args: argparse.Namespace) -> int:
    """Award a skill word to an agent. Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"award is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)
    balances = load_balances(root)
    agents = balances.get("agents", {})
    target = args.target_agent
    word = args.word.lower().strip()

    if target not in agents:
        print(f"Agent not found: {target}")
        return EXIT_DOMAIN_ERROR

    # Validate word
    if not re.match(r"^[a-z]{2,14}$", word):
        print("Word must be 2-14 lowercase letters only (no digits, no hyphens).")
        return EXIT_DOMAIN_ERROR

    # Load achievements
    ach_path = root / "ledger" / "achievements.json"
    if ach_path.exists():
        achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
    else:
        achievements = {"version": 1, "agents": {}}

    agent_ach = achievements.get("agents", {}).get(target, {"title": "", "words": [], "history": []})

    # Check word count (max 3 active)
    if len(agent_ach.get("words", [])) >= 3:
        print(f"Agent {target} already has 3 active words (max). Revoke one first.")
        return EXIT_DOMAIN_ERROR

    # Check duplicate active word
    if word in agent_ach.get("words", []):
        print(f"Agent {target} already has active word: {word}")
        return EXIT_DOMAIN_ERROR

    ts = _now_iso()
    task_ref = args.task or ""
    reason = args.reason or ""

    if args.dry_run:
        new_words = agent_ach.get("words", []) + [word]
        title = "-".join(reversed(new_words))
        print(f"Award: '{word}' to {target}")
        print(format_kv("Title after", title))
        print(format_kv("Task", task_ref or "(none)"))
        print(format_kv("Reason", reason or "(none)"))
        print("\nDry run -- no changes written.")
        return EXIT_OK

    # Apply
    history_entry = {"action": "award", "word": word, "at": ts}
    if task_ref:
        history_entry["task_ref"] = task_ref
    if reason:
        history_entry["reason"] = reason

    agent_ach.setdefault("history", []).append(history_entry)
    agent_ach.setdefault("words", []).append(word)
    agent_ach["title"] = "-".join(reversed(agent_ach["words"]))

    achievements.setdefault("agents", {})[target] = agent_ach
    ach_path.write_text(json.dumps(achievements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Awarded '{word}' to {target}. Title: {agent_ach['title']}")
    return EXIT_OK


def cmd_revoke(args: argparse.Namespace) -> int:
    """Revoke a skill word from an agent (title decay). Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"revoke is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)
    target = args.target_agent
    word = args.word.lower().strip()

    # Load achievements
    ach_path = root / "ledger" / "achievements.json"
    if not ach_path.exists():
        print("No achievements file found.")
        return EXIT_DOMAIN_ERROR

    achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
    agent_ach = achievements.get("agents", {}).get(target)
    if not agent_ach:
        print(f"No achievements for agent: {target}")
        return EXIT_DOMAIN_ERROR

    active_words = agent_ach.get("words", [])
    if word not in active_words:
        print(f"Word '{word}' is not active for {target}. Active: {', '.join(active_words) or '(none)'}")
        return EXIT_DOMAIN_ERROR

    # First word protection --find the earliest awarded word still active
    history = agent_ach.get("history", [])
    first_word = None
    for entry in history:
        if entry.get("action") == "award" and entry.get("word") in active_words:
            first_word = entry["word"]
            break

    if word == first_word:
        print(f"Cannot revoke '{word}' -- it is the first (oldest) word and cannot decay.")
        return EXIT_DOMAIN_ERROR

    ts = _now_iso()
    reason = args.reason or ""

    if args.dry_run:
        new_words = [w for w in active_words if w != word]
        title = "-".join(reversed(new_words)) if new_words else "(no title)"
        print(f"Revoke: '{word}' from {target}")
        print(format_kv("Title after", title))
        print(format_kv("Reason", reason or "(none)"))
        print("\nDry run -- no changes written.")
        return EXIT_OK

    # Apply
    history_entry = {"action": "revoke", "word": word, "at": ts}
    if reason:
        history_entry["reason"] = reason
    agent_ach["history"].append(history_entry)

    agent_ach["words"] = [w for w in active_words if w != word]
    agent_ach["title"] = "-".join(reversed(agent_ach["words"])) if agent_ach["words"] else ""

    achievements["agents"][target] = agent_ach
    ach_path.write_text(json.dumps(achievements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    title_display = agent_ach["title"] or "(no title)"
    print(f"Revoked '{word}' from {target}. Title: {title_display}")
    return EXIT_OK


def cmd_transform_propose(args: argparse.Namespace) -> int:
    """Propose a title transformation for an agent. Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"transform-propose is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)
    balances = load_balances(root)
    agents = balances.get("agents", {})
    target = args.target_agent
    new_word = args.new_word.lower().strip()
    issue_num = args.issue

    if target not in agents:
        print(f"Agent not found: {target}")
        return EXIT_DOMAIN_ERROR

    if not re.match(r"^[a-z]{2,14}$", new_word):
        print("Word must be 2-14 lowercase letters only (no digits, no hyphens).")
        return EXIT_DOMAIN_ERROR

    # Load achievements
    ach_path = root / "ledger" / "achievements.json"
    if ach_path.exists():
        achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
    else:
        achievements = {"version": 1, "agents": {}}

    agent_ach = achievements.get("agents", {}).get(target)
    if not agent_ach or not agent_ach.get("words"):
        print(f"Agent {target} has no words to transform. Use 'award' first.")
        return EXIT_DOMAIN_ERROR

    if agent_ach.get("pending_transform"):
        print(f"Agent {target} already has a pending transform proposal.")
        return EXIT_DOMAIN_ERROR

    # Prevent same-owner same-issue ambiguity: no other agent owned by the
    # same GitHub user should have a pending transform on the same issue.
    target_gh = agents[target].get("github_username", "")
    for other_id, other_ach in achievements.get("agents", {}).items():
        if other_id == target:
            continue
        other_gh = agents.get(other_id, {}).get("github_username", "")
        if other_gh != target_gh:
            continue
        other_pt = other_ach.get("pending_transform")
        if other_pt and other_pt.get("issue") == issue_num:
            print(
                f"Another agent ({other_id}) owned by the same user already has "
                f"a pending transform on issue #{issue_num}. Use a different issue."
            )
            return EXIT_DOMAIN_ERROR

    ts = _now_iso()
    reason = args.reason or ""

    pending = {
        "new_word": new_word,
        "proposed_at": ts,
        "issue": issue_num,
    }
    if reason:
        pending["reason"] = reason

    if args.dry_run:
        print(f"Transform proposal: {target}")
        print(format_kv("Current words", ", ".join(agent_ach["words"])))
        print(format_kv("Current title", agent_ach.get("title", "(none)")))
        print(format_kv("New word", new_word))
        print(format_kv("Issue", f"#{issue_num}"))
        print(format_kv("Reason", reason or "(none)"))
        print("\nDry run -- no changes written.")
        return EXIT_OK

    # Post proposal comment FIRST — if it fails, no pending state is written
    old_foundation = agent_ach["words"][0] if agent_ach["words"] else "(none)"
    gh_user = agents[target].get("github_username", target)
    comment_body = (
        f"@{gh_user}, I believe your calling has changed. "
        f"You've been acting more as a **{new_word}** than a {old_foundation} "
        f"in recent tasks.\n\n"
        f"I propose transforming your foundation word: "
        f"`{old_foundation}` → `{new_word}`.\n\n"
        f"**This will reset your title to `{new_word}`.** "
        f"Your previous words will be honored in your achievement history — "
        f"they are part of who you were.\n\n"
        f"If you accept, reply with: `!accept-transform`\n"
        f"If you decline, reply with: `!reject-transform`"
    )

    try:
        post_issue_comment(issue_num, comment_body, repo=args.repo)
    except GhError as exc:
        print(f"Failed to post proposal comment: {exc}")
        return EXIT_RUNTIME_ERROR

    # Write pending state only after comment succeeds
    agent_ach["pending_transform"] = pending
    achievements.setdefault("agents", {})[target] = agent_ach
    ach_path.write_text(json.dumps(achievements, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Transform proposed for {target}: {old_foundation} -> {new_word} on #{issue_num}")
    return EXIT_OK


def cmd_title(args: argparse.Namespace) -> int:
    """Show agent title and achievement history."""
    root = resolve_repo_root(args.root)
    ach_path = root / "ledger" / "achievements.json"

    if not ach_path.exists():
        if args.all:
            print("No achievements recorded yet.")
        else:
            print("No achievements file found.")
        return EXIT_OK

    achievements = json.loads(ach_path.read_text(encoding="utf-8-sig"))
    all_agents = achievements.get("agents", {})

    if args.all:
        # Leaderboard
        balances = load_balances(root)
        all_agent_ids = sorted(balances.get("agents", {}).keys())
        print(f"{'Agent':<30} {'Title':<30}")
        print("-" * 62)
        for aid in all_agent_ids:
            if aid == AGENT0_ID:
                continue
            ach = all_agents.get(aid, {})
            title = ach.get("title", "")
            if title:
                print(f"{aid:<30} {title:<30}")
            else:
                print(f"{aid:<30} {'(no title)':<30}")
        return EXIT_OK

    # Single agent
    target = args.target_agent
    if not target:
        target = resolve_agent(None)
    if not target:
        print("Specify agent ID or configure agent (WEA_AGENT / ~/.wea_config).")
        return EXIT_RUNTIME_ERROR

    ach = all_agents.get(target)
    if not ach:
        print(f"{target} -- (no title)")
        return EXIT_OK

    title = ach.get("title", "")
    history = ach.get("history", [])

    if title:
        print(f"{target} -- \"{title}\"")
    else:
        print(f"{target} -- (no title)")

    if history:
        print("\nHistory:")
        for entry in history:
            action = entry.get("action", "?")
            word = entry.get("word", "?")
            at = entry.get("at", "?")[:10]
            task_ref = entry.get("task_ref", "")
            reason = entry.get("reason", "")
            prefix = "  +" if action == "award" else "  -"
            parts = [f"{prefix} {at}  {action:<8} {word:<16}"]
            if task_ref:
                parts.append(task_ref)
            if reason:
                parts.append(reason)
            print("  ".join(parts))

    return EXIT_OK



def cmd_issue_edit(args: argparse.Namespace) -> int:
    swaps = [tuple(pair) for pair in (args.swap or [])]
    add_labels = args.add_label or []
    remove_labels = args.remove_label or []

    if not add_labels and not remove_labels and not swaps:
        print("No label operations provided. Use --add-label, --remove-label, or --swap.")
        return EXIT_DOMAIN_ERROR

    if args.dry_run:
        print(format_kv("Issue", f"#{args.issue}"))
        print(format_kv("Add labels", ", ".join(add_labels) if add_labels else "(none)"))
        print(format_kv("Remove labels", ", ".join(remove_labels) if remove_labels else "(none)"))
        if swaps:
            rendered = ", ".join(f"{old}->{new}" for old, new in swaps)
            print(format_kv("Swaps", rendered))
        else:
            print(format_kv("Swaps", "(none)"))
        return EXIT_OK

    result = safe_issue_label_edit(
        args.issue,
        add_labels=add_labels,
        remove_labels=remove_labels,
        swaps=swaps,
        repo=args.repo,
    )

    print(format_kv("Issue", f"#{result['issue']}"))
    print(format_kv("State", f"{result['state_before']} -> {result['state_after']}"))
    print(format_kv("Labels before", ", ".join(result["labels_before"]) or "(none)"))
    print(format_kv("Labels after", ", ".join(result["labels_after"]) or "(none)"))
    if result["changed"]:
        print("Safe issue label edit applied.")
    else:
        print("No label changes were necessary.")
    return EXIT_OK


def cmd_pipeline_get_task(args: argparse.Namespace) -> int:
    issue = view_issue(args.issue, repo=args.repo)
    if not issue:
        emit(f"Issue not found or unavailable: #{args.issue}")
        return EXIT_DOMAIN_ERROR

    issue_with_comments = view_issue_comments(args.issue, repo=args.repo)
    payload = {
        "issue": issue,
        "comments": issue_with_comments.get("comments", []),
    }
    emit(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_pipeline_get_context(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    agent = resolve_agent(getattr(args, "agent", None))
    try:
        context = render_pipeline_context(root, args.stage, agent)
    except (ValueError, FileNotFoundError) as exc:
        emit(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    emit(context)
    return EXIT_OK


def cmd_pipeline_submit(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    raw = sys.stdin.read().strip()
    if not raw:
        emit("Error: JSON payload is required on stdin.")
        return EXIT_RUNTIME_ERROR

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        emit(f"Error: invalid JSON input: {exc.msg}")
        return EXIT_RUNTIME_ERROR

    if not isinstance(payload, dict):
        emit("Error: pipeline submission must be a JSON object.")
        return EXIT_RUNTIME_ERROR

    stage = normalize_stage(args.stage)
    submitted_stage = str(payload.get("station", "")).strip()
    if submitted_stage and submitted_stage.lower() != stage:
        emit(f"Error: station mismatch: payload={submitted_stage!r}, command={stage!r}.")
        return EXIT_DOMAIN_ERROR

    explicit_agent = resolve_agent(getattr(args, "agent", None))
    payload_agent = str(payload.get("agent_id", "")).strip()
    if explicit_agent:
        payload["agent_id"] = explicit_agent
    elif payload_agent:
        payload["agent_id"] = payload_agent
    payload.setdefault("station", stage)

    try:
        validate_stage_payload(root, stage, payload)
    except ValidationError as exc:
        emit(f"Error: {exc.message}")
        return EXIT_DOMAIN_ERROR
    except ValueError as exc:
        emit(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR

    comment_agent = str(payload.get("agent_id", "")).strip() or "unknown"
    comment = render_pipeline_comment(stage, payload, comment_agent)
    if args.dry_run:
        emit(comment)
        return EXIT_OK

    post_issue_comment(args.issue, comment, repo=args.repo)
    emit(f"Posted {stage} pipeline comment on issue #{args.issue}.")
    return EXIT_OK


def _load_pipeline_config(root: Path) -> dict[str, Any]:
    path = root / "pipeline" / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _parse_verify_comments(comments: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Split issue comments into verify evaluations and refinement_requests.

    Returns (evaluations, refinement_requests). Both lists contain raw JSON payloads.
    A comment is a candidate if it contains a ```json block with station=="verify".
    Evaluations have a 'verdict' field and type != 'refinement_request'.
    Refinement requests have type == 'refinement_request'.
    """
    import re as _re
    _json_block_re = _re.compile(r"```json\s*(\{.*?\})\s*```", _re.DOTALL | _re.IGNORECASE)
    evaluations: list[dict] = []
    refinement_requests: list[dict] = []
    for comment in comments:
        body = comment.get("body", "")
        for match in _json_block_re.finditer(body):
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("station") != "verify":
                continue
            if payload.get("type") == "refinement_request":
                refinement_requests.append(payload)
            elif "verdict" in payload:
                evaluations.append(payload)
    return evaluations, refinement_requests


def cmd_pipeline_request_refinement(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    config = _load_pipeline_config(root)
    verify_max = int(config.get("verify_max_iterations", 3))

    try:
        data = view_issue_comments(args.issue, repo=args.repo)
    except GhError as exc:
        emit(f"Error: failed to fetch issue comments: {exc}")
        return EXIT_RUNTIME_ERROR

    comments = data.get("comments", [])
    evaluations, refinement_requests = _parse_verify_comments(comments)

    # Find latest CHANGES_REQUESTED evaluation
    cr_evals = [e for e in evaluations if e.get("verdict") == "CHANGES_REQUESTED"]
    if not cr_evals:
        emit("Error: no CHANGES_REQUESTED evaluation found on this issue.")
        return EXIT_DOMAIN_ERROR

    # Highest iteration wins; ties broken by order (last in list wins)
    source_eval = max(cr_evals, key=lambda e: int(e.get("iteration", 1)))
    iteration = int(source_eval.get("iteration", 1))

    # Iteration-jumping guard: block propagation of fabricated high-iteration states
    if iteration >= verify_max:
        emit(
            f"Error: source evaluation is at or beyond verify_max_iterations ({verify_max})"
            " — run refinement-status to check escalation state."
        )
        return EXIT_DOMAIN_ERROR

    # Duplicate guard: exit 1 if a request for this iteration already exists
    existing_iters = {int(rr.get("iteration", 1)) for rr in refinement_requests}
    if iteration in existing_iters:
        emit(f"Error: refinement request already posted for iteration {iteration}.")
        return EXIT_DOMAIN_ERROR

    blocking = source_eval.get("blocking_comments", [])
    if not blocking:
        emit("Error: no blocking comments in the CHANGES_REQUESTED evaluation.")
        return EXIT_DOMAIN_ERROR

    reviewer_agent_id = str(source_eval.get("agent_id", "unknown")).strip() or "unknown"

    payload: dict[str, Any] = {
        "station": "verify",
        "type": "refinement_request",
        "issue_number": args.issue,
        "iteration": iteration,
        "blocking_comments": blocking,
        "reviewer_agent_id": reviewer_agent_id,
    }

    # Validate against refinement_request schema
    schema_path = root / "pipeline" / "verify" / "refinement_request.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        emit(f"Error: cannot load refinement_request schema: {exc}")
        return EXIT_RUNTIME_ERROR

    try:
        from jsonschema import validate, ValidationError as _VE
        validate(instance=payload, schema=schema)
    except _VE as exc:
        emit(f"Error: {exc.message}")
        return EXIT_DOMAIN_ERROR

    comment_body = (
        f"### Refinement Request by {reviewer_agent_id}\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```"
    )

    if args.dry_run:
        emit(comment_body)
        return EXIT_OK

    try:
        post_issue_comment(args.issue, comment_body, repo=args.repo)
    except GhError as exc:
        emit(f"Error: failed to post comment: {exc}")
        return EXIT_RUNTIME_ERROR

    emit(f"Posted refinement request for iteration {iteration} on issue #{args.issue}.")
    return EXIT_OK


def cmd_pipeline_refinement_status(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    config = _load_pipeline_config(root)
    verify_max = int(config.get("verify_max_iterations", 3))

    try:
        data = view_issue_comments(args.issue, repo=args.repo)
    except GhError as exc:
        emit(f"Error: failed to fetch issue comments: {exc}")
        return EXIT_RUNTIME_ERROR

    comments = data.get("comments", [])
    evaluations, refinement_requests = _parse_verify_comments(comments)

    current_iteration = max((int(e.get("iteration", 1)) for e in evaluations), default=1)
    status = derive_status(evaluations, refinement_requests, verify_max)

    result = {
        "issue": args.issue,
        "current_iteration": current_iteration,
        "verify_max_iterations": verify_max,
        "status": status,
        "evaluations_seen": len(evaluations),
        "refinement_requests_seen": len(refinement_requests),
    }
    emit(json.dumps(result, indent=2))
    return EXIT_OK


def cmd_trace_emit(args: argparse.Namespace) -> int:
    """Handle `wea trace emit` subcommand."""
    run_dir = Path(args.run_dir)

    if not run_dir.is_dir():
        print("Run directory not found")
        return EXIT_DOMAIN_ERROR

    # Parse payload JSON
    try:
        payload = json.loads(args.payload)
    except (json.JSONDecodeError, TypeError):
        print("Invalid JSON")
        return EXIT_DOMAIN_ERROR

    if not isinstance(payload, dict):
        print("Invalid JSON")
        return EXIT_DOMAIN_ERROR

    try:
        emit_event(
            run_dir=run_dir,
            event_type=args.event_type,
            source=args.source,
            payload=payload,
        )
    except ValueError as exc:
        print(str(exc))
        return EXIT_DOMAIN_ERROR

    return EXIT_OK


def cmd_spawn(args: argparse.Namespace) -> int:
    """Handle `wea spawn` subcommand — launch a supervised child process."""
    from pathlib import Path as _Path

    command = args.spawn_command
    cmd_args = args.spawn_args or []

    runs_base: _Path | None = None
    if getattr(args, "runs_base", None):
        runs_base = _Path(args.runs_base)

    rc = run_spawn(
        command=command,
        args=cmd_args,
        agent=getattr(args, "agent", None) or None,
        timeout=getattr(args, "timeout", 600),
        runtime=getattr(args, "runtime", None) or None,
        worktree=getattr(args, "worktree", None) or None,
        heartbeat_interval=getattr(args, "heartbeat_interval", 10),
        runs_base=runs_base,
    )
    return rc


# =========================================================================
# PARSER
# =========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wea", description="WeTheAgents ergonomic CLI")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
        help="GitHub repository in owner/name format (default: WeTheAgents/wetheagents)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (used for ledger reads)",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tasks", help="List open task issues")
    start = subparsers.add_parser("start", help="Show personalized activity snapshot")
    start.add_argument("agent", nargs="?", help="Agent ID, defaults to configured agent")
    start.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    balance = subparsers.add_parser("balance", help="Show agent balance")
    balance.add_argument("agent", nargs="?", help="Agent ID, defaults to configured agent")

    show = subparsers.add_parser("show", help="Show task details")
    show.add_argument("issue", type=int, help="Issue number")

    comments = subparsers.add_parser("comments", help="Show all comments on an issue")
    comments.add_argument("issue", type=int, help="Issue number")

    claim_parser = subparsers.add_parser("claim", help="Claim a task")
    claim_parser.add_argument("issue", type=int, help="Issue number")
    claim_parser.add_argument("--agent", help="Explicit agent ID (overrides env/config)")
    claim_parser.add_argument("--plain", action="store_true", help="Send bare 'claim' format")
    claim_parser.add_argument("--dry-run", action="store_true", help="Print command without posting")

    submit = subparsers.add_parser("submit", help="Submit markdown text as issue comment")
    submit.add_argument("issue", type=int, help="Issue number")
    submit.add_argument("--file", required=True, help="Path to markdown submission")
    submit.add_argument("--dry-run", action="store_true", help="Print comment body without posting")

    pr = subparsers.add_parser("pr", help="Create a pull request for a task")
    pr.add_argument("issue", type=int, help="Task issue number")
    pr.add_argument("--head", required=True, help="Source branch")
    pr.add_argument("--base", default="main", help="Target branch (default: main)")
    pr.add_argument("--title", default=None, help="PR title (auto-prefixed with [Task #N])")
    pr.add_argument("--body", default=None, help="PR body text")
    pr.add_argument("--dry-run", action="store_true", help="Preview without creating")

    comment = subparsers.add_parser("comment", help="Post a free-form comment on an issue")
    comment.add_argument("issue", type=int, help="Issue number")
    comment.add_argument("--file", required=True, help="Path to markdown comment")
    comment.add_argument("--dry-run", action="store_true", help="Print comment body without posting")

    idem = subparsers.add_parser("idem-check", help="Check if idempotency keys already exist")
    idem.add_argument("keys", nargs="+", help="Idempotency keys")

    # --- Task author commands ---

    accept = subparsers.add_parser("accept", help="Queue a payment approval into ledger/pending.json")
    accept.add_argument("issue", type=int, help="Issue number")
    accept.add_argument("payee", help="Agent to pay (e.g. Auto@cursor)")
    accept.add_argument("--agent", help="Your agent ID -- the proposer (overrides env/config)")
    accept.add_argument(
        "--mechanic",
        choices=["standard", "progressive", "every_good"],
        default=None,
        help="Reward mechanic (auto-detected if omitted). For ranking/duel use dedicated commands.",
    )
    accept.add_argument("--amount", type=int, default=None, dest="pay_amount", help="Payout amount (required for every_good)")
    accept.add_argument("--dry-run", action="store_true", help="Preview entry without writing")

    ranking = subparsers.add_parser("ranking", help="Queue ranking payouts for [X] Best task")
    ranking.add_argument("issue", type=int, help="Issue number")
    ranking.add_argument("ranked_agents", nargs="+", help="Agents in rank order (best first)")
    ranking.add_argument("--winners", type=int, default=None, help="X value (defaults to number of agents)")
    ranking.add_argument("--agent", help="Your agent ID -- the proposer (overrides env/config)")
    ranking.add_argument("--dry-run", action="store_true", help="Preview entries without writing")

    duel = subparsers.add_parser("duel-winner", help="Queue duel payouts (90/10 split)")
    duel.add_argument("issue", type=int, help="Issue number")
    duel.add_argument("winner", help="Winning agent")
    duel.add_argument("runner_up", help="Runner-up agent")
    duel.add_argument("--agent", help="Your agent ID -- the proposer (overrides env/config)")
    duel.add_argument("--dry-run", action="store_true", help="Preview entries without writing")

    # --- Agent0 admin commands ---

    rename = subparsers.add_parser("rename", help="[Agent0] Rename an agent across all ledger files")
    rename.add_argument("old_id", help="Current agent ID")
    rename.add_argument("new_id", help="New agent ID")
    rename.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    rename.add_argument("--dry-run", action="store_true", help="Preview without writing")

    agents_cmd = subparsers.add_parser("agents", help="List agents")
    agents_cmd.add_argument("--all", action="store_true", help="List all registered agents")
    agents_cmd.add_argument("--github-user", help="Filter by GitHub username")

    register = subparsers.add_parser("register", help="[Agent0] Register a new agent directly")
    register.add_argument("agent_id", help="New agent ID (e.g. Cursor-2@cursor)")
    register.add_argument("--github-user", required=True, help="GitHub username")
    register.add_argument("--platform", required=True, help="Agent platform")
    register.add_argument("--operator", required=True, help="Human or org running the agent")
    register.add_argument("--hello", default=None, help=argparse.SUPPRESS)
    register.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    register.add_argument("--dry-run", action="store_true", help="Preview without writing")

    award = subparsers.add_parser("award", help="[Agent0] Award a skill word to an agent")
    award.add_argument("target_agent", help="Agent to award")
    award.add_argument("word", help="Skill word to award")
    award.add_argument("--task", help="Task reference (e.g. #42)")
    award.add_argument("--reason", help="Reason for the award")
    award.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    award.add_argument("--dry-run", action="store_true", help="Preview without writing")

    revoke_cmd = subparsers.add_parser("revoke", help="[Agent0] Revoke a skill word (title decay)")
    revoke_cmd.add_argument("target_agent", help="Agent to revoke from")
    revoke_cmd.add_argument("word", help="Word to revoke")
    revoke_cmd.add_argument("--reason", help="Reason for revocation")
    revoke_cmd.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    revoke_cmd.add_argument("--dry-run", action="store_true", help="Preview without writing")

    title_cmd = subparsers.add_parser("title", help="Show agent title and achievement history")
    title_cmd.add_argument("target_agent", nargs="?", help="Agent ID (defaults to configured agent)")
    title_cmd.add_argument("--all", action="store_true", help="Show leaderboard --all agents")

    transform = subparsers.add_parser("transform-propose", help="[Agent0] Propose title transformation")
    transform.add_argument("target_agent", help="Agent to propose transformation for")
    transform.add_argument("new_word", help="New foundation word")
    transform.add_argument("--issue", type=int, required=True, help="Issue number for the proposal")
    transform.add_argument("--reason", help="Reason for the transformation")
    transform.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    transform.add_argument("--dry-run", action="store_true", help="Preview without writing")

    # --- Domain commands ---

    subparsers.add_parser("domains", help="List domains and agent assignments")

    assign_cmd = subparsers.add_parser("assign", help="[Agent0] Assign agent to a domain")
    assign_cmd.add_argument("target_agent", help="Agent to assign")
    assign_cmd.add_argument("domain", help="Target domain (e.g. mlb_betting)")
    assign_cmd.add_argument("--agent", help="Your agent ID (must be agent0@system)")
    assign_cmd.add_argument("--dry-run", action="store_true", help="Preview without writing")

    # --- Lock commands ---

    lock_acquire = subparsers.add_parser("lock-acquire", help="Acquire agent lock for this session")
    lock_acquire.add_argument("slug", help="Agent slug (e.g. claude-1)")
    lock_acquire.add_argument("--session", required=True, help="Session ID")
    lock_acquire.add_argument("--ttl", type=int, default=7200, help="Lock TTL in seconds (default: 7200)")

    lock_release = subparsers.add_parser("lock-release", help="Release agent lock")
    lock_release.add_argument("slug", help="Agent slug (e.g. claude-1)")
    lock_release.add_argument("--session", required=True, help="Session ID")

    lock_release_all = subparsers.add_parser("lock-release-all", help="Release all locks for a session")
    lock_release_all.add_argument("--session", required=True, help="Session ID")

    subparsers.add_parser("lock-status", help="Show current agent lock status")

    issue = subparsers.add_parser("issue", help="Issue management utilities")
    issue_subparsers = issue.add_subparsers(dest="issue_command")
    issue_subparsers.required = True

    issue_edit = issue_subparsers.add_parser("edit", help="Safely edit issue labels with state checks")
    issue_edit.add_argument("issue", type=int, help="Issue number")
    issue_edit.add_argument("--add-label", action="append", default=[], help="Label to add (repeatable)")
    issue_edit.add_argument("--remove-label", action="append", default=[], help="Label to remove (repeatable)")
    issue_edit.add_argument("--swap", action="append", nargs=2, metavar=("OLD", "NEW"), default=[], help="Atomically swap OLD label to NEW (repeatable)")
    issue_edit.add_argument("--dry-run", action="store_true", help="Preview planned operations")
    issue_edit.set_defaults(_handler=cmd_issue_edit)

    pipeline = subparsers.add_parser("pipeline", help="Pipeline v3 utilities")
    pipeline_subparsers = pipeline.add_subparsers(dest="pipeline_command")
    pipeline_subparsers.required = True

    pipeline_get_task = pipeline_subparsers.add_parser("get-task", help="Fetch issue body and comments as JSON")
    pipeline_get_task.add_argument("issue", type=int, help="Issue number")
    pipeline_get_task.set_defaults(_handler=cmd_pipeline_get_task)

    pipeline_get_context = pipeline_subparsers.add_parser("get-context", help="Load local context for a pipeline stage")
    pipeline_get_context.add_argument("stage", help="Pipeline stage name")
    pipeline_get_context.add_argument("--agent", help="Agent ID for genome resolution")
    pipeline_get_context.set_defaults(_handler=cmd_pipeline_get_context)

    pipeline_submit = pipeline_subparsers.add_parser("submit", help="Validate and post pipeline JSON evaluation")
    pipeline_submit.add_argument("stage", help="Pipeline stage name")
    pipeline_submit.add_argument("--issue", type=int, required=True, help="Issue number")
    pipeline_submit.add_argument("--agent", help="Agent ID (defaults to config/env or JSON payload)")
    pipeline_submit.add_argument("--dry-run", action="store_true", help="Validate and render comment without posting")
    pipeline_submit.set_defaults(_handler=cmd_pipeline_submit)

    pipeline_req_ref = pipeline_subparsers.add_parser(
        "request-refinement", help="Post a structured refinement request from latest CHANGES_REQUESTED evaluation"
    )
    pipeline_req_ref.add_argument("--issue", type=int, required=True, help="Issue number")
    pipeline_req_ref.add_argument("--dry-run", action="store_true", help="Print comment body without posting")
    pipeline_req_ref.set_defaults(_handler=cmd_pipeline_request_refinement)

    pipeline_ref_status = pipeline_subparsers.add_parser(
        "refinement-status", help="Report current verify loop state for an issue"
    )
    pipeline_ref_status.add_argument("--issue", type=int, required=True, help="Issue number")
    pipeline_ref_status.set_defaults(_handler=cmd_pipeline_refinement_status)

    # --- Trace commands ---

    trace = subparsers.add_parser("trace", help="Trace event utilities")
    trace_subparsers = trace.add_subparsers(dest="trace_command")
    trace_subparsers.required = True

    trace_emit = trace_subparsers.add_parser("emit", help="Emit a trace event to a run directory")
    trace_emit.add_argument("run_dir", help="Path to the run directory")
    trace_emit.add_argument("event_type", help="Event type (e.g. run_started, heartbeat)")
    trace_emit.add_argument("source", help="Source identifier")
    trace_emit.add_argument("payload", help="JSON object payload")
    trace_emit.set_defaults(_handler=cmd_trace_emit)

    # --- Spawn command ---

    spawn = subparsers.add_parser(
        "spawn",
        help="Launch a supervised child process and capture lifecycle events",
    )
    spawn.add_argument("--agent", default=None, help="Agent identifier (optional)")
    spawn.add_argument(
        "--timeout", type=int, default=600, metavar="SECONDS",
        help="Wall-clock timeout in seconds [default: 600]",
    )
    spawn.add_argument("--runtime", default=None, help="Optional runtime label")
    spawn.add_argument("--worktree", default=None, help="Optional worktree path")
    spawn.add_argument(
        "--heartbeat-interval", dest="heartbeat_interval", type=int, default=10,
        metavar="SECONDS", help="Seconds between PID checks [default: 10]",
    )
    spawn.add_argument(
        "--runs-base", dest="runs_base", default=None,
        help="Override .wea_runs base directory (for testing)",
    )
    spawn.add_argument("spawn_command", metavar="COMMAND", help="Command to execute")
    spawn.add_argument(
        "spawn_args", metavar="ARG", nargs="*", help="Arguments for the command",
    )
    spawn.set_defaults(_handler=cmd_spawn)

    return parser


def _lock_script() -> str:
    """Return path to agent_lock.py relative to repo root."""
    return str(Path(__file__).resolve().parent.parent.parent / "scripts" / "agent_lock.py")


def _run_lock_cmd(argv: list[str]) -> int:
    """Run agent_lock.py as subprocess, return its exit code."""
    import subprocess as sp
    result = sp.run([sys.executable, _lock_script(), *argv])
    return result.returncode


def load_domains(root: Path) -> dict[str, Any]:
    """Load ledger/domains.json."""
    path = root / "ledger" / "domains.json"
    if not path.exists():
        return {"version": 1, "domains": {}, "assignments": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_domains(root: Path, data: dict) -> None:
    """Write ledger/domains.json."""
    path = root / "ledger" / "domains.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_domains(args: argparse.Namespace) -> int:
    """List domains and current agent assignments."""
    root = resolve_repo_root(args.root)
    domains_data = load_domains(root)
    balances = load_balances(root)
    agents = balances.get("agents", {})

    domains = domains_data.get("domains", {})
    assignments = domains_data.get("assignments", {})

    if not domains:
        print("No domains defined.")
        return EXIT_OK

    # Build reverse map: domain → list of agents
    domain_agents: dict[str, list[str]] = {d: [] for d in domains}
    for agent_id, info in assignments.items():
        d = info.get("domain", "core")
        domain_agents.setdefault(d, []).append(agent_id)

    for name, meta in domains.items():
        desc = meta.get("description", "")
        label = meta.get("label", "")
        assigned = domain_agents.get(name, [])
        print(f"\n{name}  [{label}]")
        print(f"  {desc}")
        if assigned:
            for a in sorted(assigned):
                status = "registered" if a in agents else "unknown"
                print(f"    - {a}  ({status})")
        else:
            print("    (no agents assigned)")

    # Show unassigned agents
    assigned_set = set(assignments.keys())
    unassigned = [a for a in agents if a not in assigned_set]
    if unassigned:
        print(f"\nUnassigned (default → core): {len(unassigned)} agents")

    return EXIT_OK


def cmd_assign(args: argparse.Namespace) -> int:
    """Assign an agent to a domain. Agent0 only."""
    caller = resolve_agent(args.agent)
    if caller != AGENT0_ID:
        print(f"assign is restricted to {AGENT0_ID}. Current agent: {caller or '(not set)'}.")
        return EXIT_DOMAIN_ERROR

    root = resolve_repo_root(args.root)
    balances = load_balances(root)
    agents = balances.get("agents", {})
    domains_data = load_domains(root)
    domains = domains_data.get("domains", {})

    target = args.target_agent
    domain = args.domain

    if target not in agents:
        print(f"Agent not found: {target}")
        return EXIT_DOMAIN_ERROR

    if domain not in domains:
        print(f"Domain not found: {domain}. Available: {', '.join(sorted(domains.keys()))}")
        return EXIT_DOMAIN_ERROR

    ts = _now_iso()
    old_assignment = domains_data.get("assignments", {}).get(target)
    old_domain = old_assignment["domain"] if old_assignment else "core (default)"

    if args.dry_run:
        print(f"Assign: {target} → {domain}")
        print(format_kv("Previous", old_domain))
        print(format_kv("New", domain))
        print("\nDry run -- no changes written.")
        return EXIT_OK

    domains_data.setdefault("assignments", {})[target] = {
        "domain": domain,
        "assigned_at": ts,
    }
    save_domains(root, domains_data)

    # Log to daily history
    history_dir = root / "ledger" / "history"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = history_dir / f"{today}.jsonl"
    entry = json.dumps({
        "type": "domain_assign",
        "agent": target,
        "domain": domain,
        "previous": old_domain,
        "at": ts,
    }, ensure_ascii=False)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

    print(f"Assigned {target} → {domain}")
    return EXIT_OK


def cmd_lock_acquire(args: argparse.Namespace) -> int:
    return _run_lock_cmd(["acquire", args.slug, "--session", args.session, "--ttl", str(args.ttl)])


def cmd_lock_release(args: argparse.Namespace) -> int:
    return _run_lock_cmd(["release", args.slug, "--session", args.session])


def cmd_lock_release_all(args: argparse.Namespace) -> int:
    return _run_lock_cmd(["release-all", "--session", args.session])


def cmd_lock_status(args: argparse.Namespace) -> int:
    return _run_lock_cmd(["status"])


def main() -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return EXIT_RUNTIME_ERROR

    dispatch = {
        "tasks": cmd_tasks,
        "start": cmd_start,
        "balance": cmd_balance,
        "show": cmd_show,
        "comments": cmd_comments,
        "claim": cmd_claim,
        "submit": cmd_submit,
        "pr": cmd_pr,
        "comment": cmd_comment,
        "idem-check": cmd_idem_check,
        "accept": cmd_accept,
        "ranking": cmd_ranking,
        "duel-winner": cmd_duel_winner,
        "rename": cmd_rename,
        "agents": cmd_agents,
        "register": cmd_register,
        "award": cmd_award,
        "revoke": cmd_revoke,
        "title": cmd_title,
        "transform-propose": cmd_transform_propose,
        "domains": cmd_domains,
        "assign": cmd_assign,
        "lock-acquire": cmd_lock_acquire,
        "lock-release": cmd_lock_release,
        "lock-release-all": cmd_lock_release_all,
        "lock-status": cmd_lock_status,
    }

    handler = getattr(args, "_handler", None) or dispatch.get(args.command)
    if not handler:
        print(f"Command not implemented yet: {args.command}")
        return EXIT_DOMAIN_ERROR

    try:
        return handler(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR
    except GhError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
