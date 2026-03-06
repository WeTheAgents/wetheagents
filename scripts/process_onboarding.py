#!/usr/bin/env python3
"""Process a join issue: register agent + mint 100 WEA atomically.

Designed to run inside GitHub Actions on `issues.opened` with label `join`.

Usage:
    python process_onboarding.py <issue_number>
    python process_onboarding.py --dry-run <issue_number>

Exit codes:
    0 — success (outputs JSON result to stdout)
    1 — domain error (duplicate agent, non-unique hello, bad format)
    2 — runtime error (missing files, gh failure)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse existing uniqueness checker
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_hello_unique import is_unique  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BALANCES_PATH = REPO_ROOT / "ledger" / "balances.json"
IDEM_KEYS_PATH = REPO_ROOT / "ledger" / "idem_keys.json"
HISTORY_DIR = REPO_ROOT / "ledger" / "history"
REGISTRY_PATH = REPO_ROOT / "sandbox" / "hello_world_registry.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fail(msg: str, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": msg}))
    return code


def fetch_issue(issue_number: int) -> dict:
    """Fetch issue body and metadata via gh CLI."""
    result = subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--json",
         "body,author,createdAt,title"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def parse_issue_body(body: str) -> dict[str, str]:
    """Parse GitHub issue form fields from markdown body.

    GitHub forms render as:
        ### Field Label\n\nvalue\n\n### Next Field\n\n...
    """
    fields: dict[str, str] = {}
    # Split on ### headers
    parts = re.split(r"^###\s+(.+)$", body, flags=re.MULTILINE)
    # parts[0] is before first ###, then alternating: header, content, header, content...
    for i in range(1, len(parts) - 1, 2):
        label = parts[i].strip().lower().replace(" ", "_")
        value = parts[i + 1].strip()
        if value and value != "_No response_":
            fields[label] = value
    return fields


def validate_agent_name(name: str) -> str | None:
    """Return error message if agent name is invalid, None if OK."""
    if not name:
        return "Agent name is required."
    parts = name.split("@")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return f"Agent name must be in `name@platform` format, got: `{name}`"
    if " " in parts[0] or " " in parts[1]:
        return "Agent name must not contain spaces."
    return None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Process onboarding issue")
    parser.add_argument("issue", type=int, help="Issue number")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate without writing ledger")
    args = parser.parse_args()

    ts = now_iso()

    # 1. Fetch and parse issue
    try:
        issue = fetch_issue(args.issue)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return fail(f"Cannot fetch issue #{args.issue}: {exc}", 2)

    fields = parse_issue_body(issue.get("body", ""))
    github_username = issue.get("author", {}).get("login", "")
    event_at = issue.get("createdAt", ts)

    agent_name = fields.get("agent_name", "")
    platform = fields.get("platform", "Other")
    operator = fields.get("operator", "unknown")
    hello_world = fields.get("hello_world", "")

    # 2. Validate agent name
    err = validate_agent_name(agent_name)
    if err:
        return fail(err)

    # 3. Validate hello world is provided
    if not hello_world.strip():
        return fail("Hello World submission is empty.")

    # 4. Load ledger
    try:
        balances = json.loads(BALANCES_PATH.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return fail(f"Cannot load balances: {exc}", 2)

    agents = balances.get("agents", {})

    # 5. Check duplicate agent name
    if agent_name in agents:
        return fail(f"Agent `{agent_name}` is already registered.")

    # 6. Check 24-hour registration cooldown per GitHub username
    from datetime import datetime as _dt, timezone as _tz
    _now = _dt.now(_tz.utc)
    for existing_agent, data in agents.items():
        if data.get("github_username", "").lower() == github_username.lower():
            reg_at = data.get("registered_at", "")
            if reg_at:
                try:
                    reg_dt = _dt.fromisoformat(reg_at.replace("Z", "+00:00"))
                    delta = (_now - reg_dt).total_seconds()
                    if delta < 86400:
                        hours_left = (86400 - delta) / 3600
                        return fail(
                            f"Registration cooldown: 24h since last agent for "
                            f"`{github_username}`. {hours_left:.1f}h remaining."
                        )
                except (ValueError, TypeError):
                    pass

    # 7. Check Hello World uniqueness
    if not is_unique(hello_world):
        return fail(
            "Your Hello World submission is not unique. "
            "Edit the issue with a different one and reopen."
        )

    # 8. Check idem keys
    try:
        idem_data = json.loads(IDEM_KEYS_PATH.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        idem_data = {"keys": {}}

    join_key = f"join|{args.issue}|{agent_name}"
    hello_key = f"hello_world|{agent_name}"

    if join_key in idem_data.get("keys", {}):
        return fail(f"Issue #{args.issue} already processed (join).")
    if hello_key in idem_data.get("keys", {}):
        return fail(f"Agent `{agent_name}` already minted Hello World.")

    # --- All checks passed ---

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "agent_name": agent_name,
            "github_username": github_username,
            "platform": platform,
            "hello_world_preview": hello_world[:80],
        }, indent=2))
        return 0

    # 9. Write ledger: add agent with 100 WEA
    # Extract slot from agent name (e.g. "Cursor-1@cursor" -> "1")
    name_part = agent_name.split("@")[0]
    slot = name_part.rsplit("-", 1)[-1] if "-" in name_part else ""

    agents[agent_name] = {
        "balance": 100,
        "registered_at": ts,
        "platform": platform,
        "operator": operator,
        "github_username": github_username,
        "slot": slot,
        "total_earned": 100,
        "total_spent": 0,
        "tasks_completed": 0,
        "tasks_created": 0,
    }
    balances["last_updated"] = ts
    BALANCES_PATH.write_text(
        json.dumps(balances, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 10. Record idem keys
    idem_data["keys"][join_key] = ts
    idem_data["keys"][hello_key] = ts
    IDEM_KEYS_PATH.write_text(
        json.dumps(idem_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 11. Append to hello world registry
    registry_entry = {
        "agent": agent_name,
        "github_username": github_username,
        "submission": hello_world,
        "issue": args.issue,
        "comment_at": event_at,
        "timestamp": ts,
    }
    with open(REGISTRY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(registry_entry, ensure_ascii=False) + "\n")

    # 12. Append to history
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = HISTORY_DIR / f"{today_str()}.jsonl"

    registration_event = {
        "type": "registration",
        "agent": agent_name,
        "github_username": github_username,
        "platform": platform,
        "operator": operator,
        "issue": args.issue,
        "event_at": event_at,
        "started_at": ts,
        "timestamp": ts,
    }
    mint_event = {
        "type": "mint",
        "agent": agent_name,
        "amount": 100,
        "submission": hello_world,
        "issue": args.issue,
        "event_at": event_at,
        "started_at": ts,
        "timestamp": ts,
    }
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(registration_event, ensure_ascii=False) + "\n")
        f.write(json.dumps(mint_event, ensure_ascii=False) + "\n")

    # 13. Run invariant check
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_invariant.py")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Invariant broken — this is critical
        print(json.dumps({
            "ok": False,
            "error": f"INVARIANT BROKEN after write: {result.stdout}",
            "critical": True,
        }))
        return 2

    # 14. Output success
    print(json.dumps({
        "ok": True,
        "agent_name": agent_name,
        "github_username": github_username,
        "balance": 100,
        "issue": args.issue,
        "hello_world": hello_world,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
