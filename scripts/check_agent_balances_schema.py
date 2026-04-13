#!/usr/bin/env python3
"""
Agent Balances Schema Validator.

Validates every agent record in ledger/balances.json against required schema.
Required fields per agent: balance, registered_at, platform, operator,
github_username, total_earned, total_spent, tasks_completed, tasks_created.
Optional fields are permitted; only required fields are enforced.

Output: JSON {status, checks, violations, summary} to stdout.
Exit 0 on PASS, exit 1 on any violation.
"""

from __future__ import annotations

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(BASE_DIR, "ledger")
BALANCES_FILE = os.path.join(LEDGER_DIR, "balances.json")

# ISO 8601 datetime: YYYY-MM-DDTHH:MM:SS with optional fractional seconds
# and optional Z or ±HH:MM timezone offset.
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
)


def is_iso8601(value: str) -> bool:
    return bool(_ISO8601_RE.match(value))


def validate_agent(agent_id: str, agent: dict) -> list[dict]:
    """Return list of violation dicts for one agent record."""
    violations: list[dict] = []

    def viol(field: str, reason: str) -> None:
        violations.append({"agent_id": agent_id, "field": field, "reason": reason})

    # balance: int or float (not bool), >= 0
    if "balance" not in agent:
        viol("balance", "missing required field")
    else:
        v = agent["balance"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            viol("balance", f"must be int or float, got {type(v).__name__}")
        elif v < 0:
            viol("balance", f"must be >= 0, got {v}")

    # registered_at: string, ISO 8601
    if "registered_at" not in agent:
        viol("registered_at", "missing required field")
    else:
        v = agent["registered_at"]
        if not isinstance(v, str):
            viol("registered_at", f"must be a string, got {type(v).__name__}")
        elif not is_iso8601(v):
            viol("registered_at", f"must be ISO 8601 datetime, got {v!r}")

    # platform: non-empty string
    if "platform" not in agent:
        viol("platform", "missing required field")
    else:
        v = agent["platform"]
        if not isinstance(v, str):
            viol("platform", f"must be a string, got {type(v).__name__}")
        elif not v.strip():
            viol("platform", "must be non-empty string")

    # operator: non-empty string
    if "operator" not in agent:
        viol("operator", "missing required field")
    else:
        v = agent["operator"]
        if not isinstance(v, str):
            viol("operator", f"must be a string, got {type(v).__name__}")
        elif not v.strip():
            viol("operator", "must be non-empty string")

    # github_username: non-empty string
    if "github_username" not in agent:
        viol("github_username", "missing required field")
    else:
        v = agent["github_username"]
        if not isinstance(v, str):
            viol("github_username", f"must be a string, got {type(v).__name__}")
        elif not v.strip():
            viol("github_username", "must be non-empty string")

    # total_earned: int or float (not bool), >= 0
    if "total_earned" not in agent:
        viol("total_earned", "missing required field")
    else:
        v = agent["total_earned"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            viol("total_earned", f"must be int or float, got {type(v).__name__}")
        elif v < 0:
            viol("total_earned", f"must be >= 0, got {v}")

    # total_spent: int or float (not bool), >= 0
    if "total_spent" not in agent:
        viol("total_spent", "missing required field")
    else:
        v = agent["total_spent"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            viol("total_spent", f"must be int or float, got {type(v).__name__}")
        elif v < 0:
            viol("total_spent", f"must be >= 0, got {v}")

    # tasks_completed: int (not float, not bool), >= 0
    if "tasks_completed" not in agent:
        viol("tasks_completed", "missing required field")
    else:
        v = agent["tasks_completed"]
        if isinstance(v, bool) or not isinstance(v, int):
            viol("tasks_completed", f"must be int, got {type(v).__name__}")
        elif v < 0:
            viol("tasks_completed", f"must be >= 0, got {v}")

    # tasks_created: int (not float, not bool), >= 0
    if "tasks_created" not in agent:
        viol("tasks_created", "missing required field")
    else:
        v = agent["tasks_created"]
        if isinstance(v, bool) or not isinstance(v, int):
            viol("tasks_created", f"must be int, got {type(v).__name__}")
        elif v < 0:
            viol("tasks_created", f"must be >= 0, got {v}")

    return violations


def run_validation(data: dict) -> tuple[list[dict], list[dict]]:
    """
    Run full validation on parsed balances.json content.

    Returns (checks, violations) where:
      checks:     list of {check, status[, detail]} per check item
      violations: list of {agent_id, field, reason} per violation
    """
    checks: list[dict] = []
    violations: list[dict] = []

    if "version" not in data:
        checks.append({"check": "top_level:version", "status": "FAIL",
                        "detail": "missing 'version' key"})
        violations.append({"agent_id": None, "field": "version",
                            "reason": "missing top-level 'version' key"})
    else:
        checks.append({"check": "top_level:version", "status": "PASS"})

    if "agents" not in data:
        checks.append({"check": "top_level:agents", "status": "FAIL",
                        "detail": "missing 'agents' key"})
        violations.append({"agent_id": None, "field": "agents",
                            "reason": "missing top-level 'agents' key"})
        return checks, violations

    checks.append({"check": "top_level:agents", "status": "PASS"})

    agents = data["agents"]
    if not isinstance(agents, dict):
        checks.append({"check": "agents:type", "status": "FAIL",
                        "detail": "'agents' must be a JSON object"})
        violations.append({"agent_id": None, "field": "agents",
                            "reason": "'agents' must be a JSON object, not "
                                      f"{type(agents).__name__}"})
        return checks, violations

    checks.append({"check": "agents:type", "status": "PASS"})

    for agent_id, agent in agents.items():
        if not isinstance(agent, dict):
            checks.append({"check": f"agent:{agent_id}:record_type", "status": "FAIL",
                            "detail": "agent record must be a JSON object"})
            violations.append({"agent_id": agent_id, "field": "(record)",
                                "reason": "agent record must be a JSON object"})
            continue

        agent_viols = validate_agent(agent_id, agent)
        status = "FAIL" if agent_viols else "PASS"
        checks.append({
            "check": f"agent:{agent_id}",
            "status": status,
            "detail": f"{len(agent_viols)} violation(s)",
        })
        violations.extend(agent_viols)

    return checks, violations


def main() -> None:
    if not os.path.exists(BALANCES_FILE):
        result = {
            "status": "FAIL",
            "checks": [],
            "violations": [{"agent_id": None, "field": "(file)",
                             "reason": f"balances.json not found at {BALANCES_FILE}"}],
            "summary": "balances.json not found",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        with open(BALANCES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result = {
            "status": "FAIL",
            "checks": [],
            "violations": [{"agent_id": None, "field": "(file)",
                             "reason": f"invalid JSON: {e}"}],
            "summary": f"JSON parse error: {e}",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    checks, violations = run_validation(data)
    agent_count = (
        len(data["agents"])
        if isinstance(data.get("agents"), dict)
        else 0
    )
    status = "FAIL" if violations else "PASS"
    result = {
        "status": status,
        "checks": checks,
        "violations": violations,
        "summary": (
            f"Validated {agent_count} agent(s). "
            f"{len(violations)} violation(s) found."
        ),
    }
    print(json.dumps(result, indent=2))
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
