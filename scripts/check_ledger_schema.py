#!/usr/bin/env python3
"""
Ledger JSON Schema Validator.

Validates all ledger/*.json files against expected structure.
Exits 1 on any violation with remediation instructions.
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(BASE_DIR, "ledger")

ERRORS: list[str] = []


def err(file: str, msg: str, fix: str) -> None:
    ERRORS.append(f"  FAIL [{file}]: {msg}\n        Fix: {fix}")


def validate_balances(data: dict) -> None:
    f = "balances.json"
    if "version" not in data:
        err(f, "missing 'version' key", "add \"version\": <int> at top level")
    if "agents" not in data:
        err(f, "missing 'agents' key", "add \"agents\": {} at top level")
        return

    for agent_id, agent in data["agents"].items():
        if "@" not in agent_id:
            err(f, f"agent id '{agent_id}' missing '@'", "format: <name>@<platform>")

        required = ["balance", "registered_at", "platform", "github_username"]
        for key in required:
            if key not in agent:
                err(f, f"agent '{agent_id}' missing '{key}'", f"add \"{key}\" to agent entry")

        if "balance" in agent and not isinstance(agent["balance"], int):
            err(f, f"agent '{agent_id}' balance is not int", "balance must be an integer")

        if "balance" in agent and agent["balance"] < 0:
            err(f, f"agent '{agent_id}' has negative balance: {agent['balance']}",
                "investigate ledger history — balances must be >= 0")


def validate_escrows(data: dict) -> None:
    f = "escrows.json"
    if "version" not in data:
        err(f, "missing 'version' key", "add \"version\": <int> at top level")
    if "active" not in data:
        err(f, "missing 'active' key", "add \"active\": {} at top level")
        return

    valid_types = {"standard", "progressive", "best_x", "every_good", "duel"}

    for issue, esc in data["active"].items():
        if "author" not in esc:
            err(f, f"escrow #{issue} missing 'author'", "add author agent-id")
        if "amount" not in esc:
            err(f, f"escrow #{issue} missing 'amount'", "add amount (int >= 0)")
        elif not isinstance(esc["amount"], int):
            err(f, f"escrow #{issue} amount is not int", "amount must be an integer")
        elif esc["amount"] < 0:
            err(f, f"escrow #{issue} has negative amount: {esc['amount']}",
                "investigate — escrow amounts must be >= 0")

        if "type" not in esc:
            err(f, f"escrow #{issue} missing 'type'", f"add type, one of: {valid_types}")
        elif esc["type"] not in valid_types:
            err(f, f"escrow #{issue} unknown type '{esc['type']}'",
                f"must be one of: {', '.join(sorted(valid_types))}")


def validate_idem_keys(data: dict) -> None:
    f = "idem_keys.json"
    if "keys" not in data:
        err(f, "missing 'keys' key", "add \"keys\": {} at top level")


def validate_pending(data: dict) -> None:
    f = "pending.json"
    if "queue" not in data:
        err(f, "missing 'queue' key", "add \"queue\": [] at top level")
    elif not isinstance(data["queue"], list):
        err(f, "'queue' is not a list", "queue must be a JSON array")


def validate_task_index(data: dict) -> None:
    f = "task_index.json"
    if "tasks" not in data:
        err(f, "missing 'tasks' key", "add \"tasks\": {} at top level")


VALIDATORS = {
    "balances.json": validate_balances,
    "escrows.json": validate_escrows,
    "idem_keys.json": validate_idem_keys,
    "pending.json": validate_pending,
    "task_index.json": validate_task_index,
}


def main() -> None:
    print("--- Ledger Schema Validation ---")

    for filename, validator in VALIDATORS.items():
        path = os.path.join(LEDGER_DIR, filename)
        if not os.path.exists(path):
            err(filename, "file not found", f"create {filename} with correct structure")
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            err(filename, f"invalid JSON: {e}", "fix JSON syntax")
            continue

        validator(data)

    if ERRORS:
        print(f"\n{len(ERRORS)} schema violation(s) found:\n")
        for e in ERRORS:
            print(e)
        print("\nStatus: FAIL")
        sys.exit(1)
    else:
        print("All ledger files pass schema validation.")
        print("\nStatus: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
