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

        if "balance" in agent and isinstance(agent["balance"], int) and agent["balance"] < 0:
            err(f, f"agent '{agent_id}' has negative balance: {agent['balance']}",
                "investigate ledger history — balances must be >= 0")


def validate_escrows(data: dict) -> None:
    f = "escrows.json"
    if "version" not in data:
        err(f, "missing 'version' key", "add \"version\": <int> at top level")
    if "active" not in data:
        err(f, "missing 'active' key", "add \"active\": {} at top level")
        return

    valid_types = {"standard", "progressive", "linear", "best_x", "every_good", "duel"}

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

        # Optional: verified_agents must be a list of strings if present
        va = esc.get("verified_agents")
        if va is not None:
            if not isinstance(va, list):
                err(f, f"escrow #{issue} 'verified_agents' must be a list",
                    "verified_agents should be a JSON array of agent-id strings")
            elif not all(isinstance(a, str) for a in va):
                err(f, f"escrow #{issue} 'verified_agents' contains non-string entries",
                    "all entries must be agent-id strings")


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
        return

    for issue, task in data.get("tasks", {}).items():
        if not isinstance(task, dict):
            continue
        # Optional: verification_criteria must be a list of strings if present
        vc = task.get("verification_criteria")
        if vc is not None:
            if not isinstance(vc, list):
                err(f, f"task #{issue} 'verification_criteria' must be a list",
                    "verification_criteria should be a JSON array of strings")
            elif not all(isinstance(c, str) for c in vc):
                err(f, f"task #{issue} 'verification_criteria' contains non-string entries",
                    "all criteria must be strings")


def validate_achievements(data: dict) -> None:
    f = "achievements.json"
    if "version" not in data:
        err(f, "missing 'version' key", "add \"version\": 1 at top level")
    if "agents" not in data:
        err(f, "missing 'agents' key", "add \"agents\": {} at top level")
        return
    if not isinstance(data["agents"], dict):
        err(f, "'agents' must be a dict", "agents should be an object, not a list")
        return

    for agent_id, ach in data["agents"].items():
        if not isinstance(ach, dict):
            err(f, f"agent '{agent_id}' value must be a dict", "each agent entry should be an object")
            continue
        if "@" not in agent_id:
            err(f, f"agent id '{agent_id}' missing '@'", "format: <name>@<platform>")

        if "title" not in ach:
            err(f, f"agent '{agent_id}' missing 'title'", "add \"title\": \"\" to agent entry")
        if "words" not in ach:
            err(f, f"agent '{agent_id}' missing 'words'", "add \"words\": [] to agent entry")
        elif not isinstance(ach["words"], list):
            err(f, f"agent '{agent_id}' words is not a list", "words must be a JSON array of strings")
        if "history" not in ach:
            err(f, f"agent '{agent_id}' missing 'history'", "add \"history\": [] to agent entry")
        elif not isinstance(ach["history"], list):
            err(f, f"agent '{agent_id}' history is not a list", "history must be a JSON array")
        else:
            for i, entry in enumerate(ach["history"]):
                if not isinstance(entry, dict):
                    err(f, f"agent '{agent_id}' history[{i}] must be a dict", "each history entry should be an object")
                    continue
                if "action" not in entry:
                    err(f, f"agent '{agent_id}' history[{i}] missing 'action'",
                        "add \"action\": \"award\" or \"revoke\"")
                elif entry["action"] not in ("award", "revoke", "transform_award", "transform_revoke"):
                    err(f, f"agent '{agent_id}' history[{i}] unknown action '{entry['action']}'",
                        "action must be 'award', 'revoke', 'transform_award', or 'transform_revoke'")
                if "word" not in entry:
                    err(f, f"agent '{agent_id}' history[{i}] missing 'word'", "add word string")
                if "at" not in entry:
                    err(f, f"agent '{agent_id}' history[{i}] missing 'at'", "add ISO timestamp")

        # Consistency check: computed words/title should match stored
        if isinstance(ach.get("history"), list) and isinstance(ach.get("words"), list):
            computed_words = []
            for entry in ach["history"]:
                if not isinstance(entry, dict):
                    continue
                action = entry.get("action")
                word = entry.get("word", "")
                if not isinstance(word, str):
                    continue
                if action in ("award", "transform_award") and word not in computed_words:
                    computed_words.append(word)
                elif action in ("revoke", "transform_revoke") and word in computed_words:
                    computed_words.remove(word)
            if computed_words != ach["words"]:
                err(f, f"agent '{agent_id}' words mismatch: stored {ach['words']} vs computed {computed_words}",
                    "recompute words from history")
            expected_title = "-".join(str(w) for w in reversed(computed_words)) if computed_words else ""
            if ach.get("title", "") != expected_title:
                err(f, f"agent '{agent_id}' title mismatch: stored '{ach.get('title')}' vs computed '{expected_title}'",
                    "recompute title from words")

        # Validate optional pending_transform
        pt = ach.get("pending_transform")
        if pt is not None:
            if not isinstance(pt, dict):
                err(f, f"agent '{agent_id}' pending_transform must be a dict",
                    "pending_transform should be an object or absent")
            else:
                if "new_word" not in pt or not isinstance(pt.get("new_word"), str):
                    err(f, f"agent '{agent_id}' pending_transform missing/invalid 'new_word'",
                        "add new_word string")
                if "proposed_at" not in pt or not isinstance(pt.get("proposed_at"), str):
                    err(f, f"agent '{agent_id}' pending_transform missing/invalid 'proposed_at'",
                        "add proposed_at ISO timestamp")
                if "issue" not in pt or not isinstance(pt.get("issue"), int):
                    err(f, f"agent '{agent_id}' pending_transform missing/invalid 'issue'",
                        "add issue number (int)")


VALIDATORS = {
    "balances.json": validate_balances,
    "escrows.json": validate_escrows,
    "idem_keys.json": validate_idem_keys,
    "pending.json": validate_pending,
    "task_index.json": validate_task_index,
}

# Optional validators -- only run if file exists
OPTIONAL_VALIDATORS = {
    "achievements.json": validate_achievements,
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

    # Optional files -- validate only if present
    for filename, validator in OPTIONAL_VALIDATORS.items():
        path = os.path.join(LEDGER_DIR, filename)
        if not os.path.exists(path):
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
