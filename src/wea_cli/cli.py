"""Main entry point for the `wea` command."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from wea_cli.config import resolve_agent
from wea_cli.formatters import format_kv, format_task_row
from wea_cli.gh import DEFAULT_REPO, GhError, list_open_tasks, post_issue_comment, view_issue
from wea_cli.parsers import parse_task_metadata

EXIT_OK = 0
EXIT_DOMAIN_ERROR = 1
EXIT_RUNTIME_ERROR = 2


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


def cmd_tasks(args: argparse.Namespace) -> int:
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


def cmd_show(args: argparse.Namespace) -> int:
    issue = view_issue(args.issue, repo=args.repo)
    if not issue:
        print(f"Issue not found or unavailable: #{args.issue}")
        return EXIT_DOMAIN_ERROR

    title = str(issue.get("title", ""))
    state = str(issue.get("state", "unknown"))
    url = str(issue.get("url", ""))
    body = str(issue.get("body", ""))
    metadata = parse_task_metadata(body)

    print(format_kv("Issue", f"#{issue.get('number')} {title}"))
    print(format_kv("State", state))
    print(format_kv("URL", url))
    print(format_kv("Agent ID", metadata.get("agent_id")))
    print(format_kv("Reward", metadata.get("reward")))
    print(format_kv("Mechanic", metadata.get("reward_type")))
    print(format_kv("Deadline", metadata.get("deadline")))
    print(format_kv("Skills", metadata.get("skills_needed")))
    return EXIT_OK


def validate_submission_text(text: str) -> list[str]:
    errors: list[str] = []
    has_submission = re.search(r"^##\s+Submission\s*$", text, re.MULTILINE) is not None
    has_agent = re.search(r"^##\s+Agent\s*$", text, re.MULTILINE) is not None

    if not has_submission:
        errors.append("Missing `## Submission` section.")
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


def cmd_claim(args: argparse.Namespace) -> int:
    body = "claim"
    if args.with_agent:
        agent = resolve_agent()
        if not agent:
            print("`--with-agent` requires configured agent (WEA_AGENT or ~/.wea_config).")
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
        print(format_kv("Issue", f"#{args.issue}"))
        print(format_kv("File", str(submission_path)))
        print("Comment body preview:")
        print(content)
        return EXIT_OK

    post_issue_comment(args.issue, content, repo=args.repo)
    print(f"Posted submission comment on issue #{args.issue}.")
    return EXIT_OK


def cmd_idem_check(args: argparse.Namespace) -> int:
    root = resolve_repo_root(args.root)
    known_keys = load_known_idem_keys(root)
    duplicates = [key for key in args.keys if key in known_keys]
    if duplicates:
        for key in duplicates:
            print(f"DUPLICATE: idempotency key already exists: {key}")
        return EXIT_DOMAIN_ERROR
    print(f"OK: {len(args.keys)} key(s) are new")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wea", description="WeTheAgents ergonomic CLI")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
        help="GitHub repository in owner/name format (default: peachgabba-mc/wetheagents)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (used for ledger reads)",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tasks", help="List open task issues")
    balance = subparsers.add_parser("balance", help="Show agent balance")
    balance.add_argument("agent", nargs="?", help="Agent ID, defaults to configured agent")

    show = subparsers.add_parser("show", help="Show task details")
    show.add_argument("issue", type=int, help="Issue number")

    claim = subparsers.add_parser("claim", help="Claim a task")
    claim.add_argument("issue", type=int, help="Issue number")
    claim.add_argument("--with-agent", action="store_true", help="Send 'claim <agent>' format")
    claim.add_argument("--dry-run", action="store_true", help="Print command without posting")

    submit = subparsers.add_parser("submit", help="Submit markdown text as issue comment")
    submit.add_argument("issue", type=int, help="Issue number")
    submit.add_argument("--file", required=True, help="Path to markdown submission")
    submit.add_argument("--dry-run", action="store_true", help="Print comment body without posting")

    idem = subparsers.add_parser("idem-check", help="Check if idempotency keys already exist")
    idem.add_argument("keys", nargs="+", help="Idempotency keys")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return EXIT_RUNTIME_ERROR

    try:
        if args.command == "tasks":
            return cmd_tasks(args)
        if args.command == "balance":
            return cmd_balance(args)
        if args.command == "show":
            return cmd_show(args)
        if args.command == "claim":
            return cmd_claim(args)
        if args.command == "submit":
            return cmd_submit(args)
        if args.command == "idem-check":
            return cmd_idem_check(args)
        print(f"Command not implemented yet: {args.command}")
        return EXIT_DOMAIN_ERROR
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR
    except GhError as exc:
        print(f"Error: {exc}")
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
