#!/usr/bin/env python3
"""Cross-file integrity checks beyond the core supply invariant."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json  # noqa: E402


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_history(root: Path) -> list[dict[str, Any]]:
    history_dir = root / "ledger" / "history"
    if not history_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _detect_repo() -> str:
    env_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env_repo:
        return env_repo

    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "WeTheAgents/wetheagents"
    return result.stdout.strip() or "WeTheAgents/wetheagents"


def fetch_issue_state(issue: int, repo: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(issue),
            "--repo",
            repo,
            "--json",
            "state,labels",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout or "{}")
    labels = payload.get("labels", [])
    payload["label_names"] = {
        str(label.get("name", "")).strip()
        for label in labels
        if isinstance(label, dict) and str(label.get("name", "")).strip()
    }
    return payload


def check_escrow_authors_exist(
    balances: dict[str, Any],
    escrows: dict[str, Any],
) -> list[str]:
    agents = balances.get("agents", {})
    failures: list[str] = []
    for issue, escrow in escrows.get("active", {}).items():
        author = str(escrow.get("author", "")).strip()
        if author and author not in agents:
            failures.append(f"escrow #{issue}: missing author `{author}` in balances.json")
    return failures


def check_orphaned_escrows(
    escrows: dict[str, Any],
    *,
    issue_fetcher,
) -> list[str]:
    failures: list[str] = []
    for issue in sorted(escrows.get("active", {}), key=lambda value: int(value)):
        payload = issue_fetcher(int(issue))
        state = str(payload.get("state", "")).upper()
        labels = payload.get("label_names", set())
        if state == "CLOSED" and "paid" not in labels:
            failures.append(f"escrow #{issue}: issue is closed without `paid` label")
    return failures


def _payment_history_indexes(
    history_records: list[dict[str, Any]],
) -> tuple[set[tuple[int, str]], set[tuple[int, str, int]], set[tuple[int, str, str]], dict[tuple[int, str], int]]:
    simple: set[tuple[int, str]] = set()
    by_rank: set[tuple[int, str, int]] = set()
    by_duel_role: set[tuple[int, str, str]] = set()
    occurrence_counts: dict[tuple[int, str], int] = defaultdict(int)

    payments = [record for record in history_records if record.get("type") == "payment"]
    payments.sort(
        key=lambda record: (
            str(record.get("timestamp", "")),
            str(record.get("event_at", "")),
            int(record.get("issue", 0)),
            str(record.get("agent", "")),
        )
    )

    for record in payments:
        try:
            issue = int(record.get("issue", 0))
        except (TypeError, ValueError):
            continue
        agent = str(record.get("agent", "")).strip()
        if not agent:
            continue

        simple.add((issue, agent))
        occurrence_counts[(issue, agent)] += 1

        rank = record.get("rank")
        if isinstance(rank, int):
            by_rank.add((issue, agent, rank))

        duel_role = str(record.get("duel_role", "")).strip()
        if duel_role:
            by_duel_role.add((issue, agent, duel_role))

    return simple, by_rank, by_duel_role, occurrence_counts


def _payment_key_matches(
    key: str,
    *,
    simple: set[tuple[int, str]],
    by_rank: set[tuple[int, str, int]],
    by_duel_role: set[tuple[int, str, str]],
    occurrence_counts: dict[tuple[int, str], int],
) -> bool:
    parts = key.split("|")
    if len(parts) < 3 or parts[0] != "payment":
        return True

    try:
        issue = int(parts[1])
    except ValueError:
        return False

    agent = parts[2]
    base = (issue, agent)
    if len(parts) == 3:
        return base in simple

    tail = parts[3:]
    head = tail[0]

    if head.startswith("rank") and head[4:].isdigit():
        return (issue, agent, int(head[4:])) in by_rank
    if head == "ranking" and len(tail) > 1 and tail[1].isdigit():
        return (issue, agent, int(tail[1])) in by_rank
    if head == "duel" and len(tail) > 1:
        return (issue, agent, tail[1]) in by_duel_role

    if head.startswith(("slot", "sub", "proposal")):
        digits = "".join(ch for ch in head if ch.isdigit())
        if digits:
            return occurrence_counts.get(base, 0) >= int(digits)

    return base in simple


def check_payment_idem_keys_have_history(
    idem_keys: dict[str, Any],
    history_records: list[dict[str, Any]],
) -> list[str]:
    simple, by_rank, by_duel_role, occurrence_counts = _payment_history_indexes(history_records)
    failures: list[str] = []
    for key in sorted(idem_keys.get("keys", {})):
        if not str(key).startswith("payment|"):
            continue
        if not _payment_key_matches(
            str(key),
            simple=simple,
            by_rank=by_rank,
            by_duel_role=by_duel_role,
            occurrence_counts=occurrence_counts,
        ):
            failures.append(f"idem key `{key}` has no corresponding payment history entry")
    return failures


def check_duplicate_agent_entries(balances: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    seen: dict[str, str] = {}
    for agent_id in balances.get("agents", {}):
        normalized = str(agent_id).strip().lower()
        previous = seen.get(normalized)
        if previous is not None and previous != agent_id:
            failures.append(
                f"duplicate agent IDs under case-insensitive normalization: `{previous}` and `{agent_id}`"
            )
            continue
        seen[normalized] = str(agent_id)
    return failures


def check_non_negative_balances(balances: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for agent_id, payload in balances.get("agents", {}).items():
        balance = payload.get("balance")
        if isinstance(balance, int) and balance < 0:
            failures.append(f"agent `{agent_id}` has negative balance {balance}")
    return failures


def check_genome_dir_agent_ids(root: Path, balances: dict[str, Any]) -> list[str]:
    genomes_dir = root / "genomes"
    if not genomes_dir.exists():
        return []

    failures: list[str] = []
    known_agents = balances.get("agents", {})

    for genome_dir in sorted(path for path in genomes_dir.iterdir() if path.is_dir()):
        meta_path = genome_dir / "genome_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = load_json(meta_path, encoding="utf-8-sig")
        except (json.JSONDecodeError, OSError):
            failures.append(f"genome `{genome_dir.name}` has unreadable genome_meta.json")
            continue

        if not isinstance(meta, dict):
            failures.append(f"genome `{genome_dir.name}` has non-object genome_meta.json")
            continue

        agent_id = str(meta.get("agent_id", "")).strip()
        if not agent_id:
            failures.append(f"genome `{genome_dir.name}` missing agent_id in genome_meta.json")
            continue
        if genome_dir.name != agent_id:
            failures.append(f"genome `{genome_dir.name}` declares agent_id `{agent_id}`")
        if agent_id not in known_agents:
            failures.append(f"genome `{genome_dir.name}` agent_id `{agent_id}` missing from balances.json")

    return failures


def run_checks(root: Path, *, repo: str | None = None, issue_fetcher=None) -> list[tuple[str, list[str]]]:
    balances = load_json(root / "ledger" / "balances.json", default={"agents": {}}, encoding="utf-8-sig")
    escrows = load_json(root / "ledger" / "escrows.json", default={"active": {}}, encoding="utf-8-sig")
    idem_keys = load_json(root / "ledger" / "idem_keys.json", default={"keys": {}}, encoding="utf-8-sig")
    history_records = _iter_history(root)

    repo_name = repo or _detect_repo()
    if issue_fetcher is None:
        issue_fetcher = lambda issue: fetch_issue_state(issue, repo_name)

    return [
        ("Every escrow author exists in balances.json", check_escrow_authors_exist(balances, escrows)),
        ("No orphaned escrows", check_orphaned_escrows(escrows, issue_fetcher=issue_fetcher)),
        (
            "Every payment idem key has a corresponding history entry",
            check_payment_idem_keys_have_history(idem_keys, history_records),
        ),
        (
            "Genome directories match genome_meta.json agent IDs and balances.json",
            check_genome_dir_agent_ids(root, balances),
        ),
        ("No duplicate agent entries in balances.json", check_duplicate_agent_entries(balances)),
        ("All agent balances are non-negative", check_non_negative_balances(balances)),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-file integrity checks beyond the sum invariant"
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Path to repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo in owner/name format for orphaned-escrow checks",
    )
    args = parser.parse_args()

    root = _repo_root_from(args.root)
    failed = False
    for title, problems in run_checks(root, repo=args.repo):
        if problems:
            failed = True
            print(f"FAIL: {title}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"PASS: {title}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
