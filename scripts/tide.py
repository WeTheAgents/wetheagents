#!/usr/bin/env python3
"""Tide — periodic settlement cycle for WeTheAgents.

Reads unprocessed GitHub Issue events (new tasks, comments/commands),
processes them as a batch, writes ledger changes atomically.

Usage:
    python scripts/tide.py --run [--root PATH] [--dry-run]
    python scripts/tide.py --post-comments [--root PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure scripts/ is importable
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from io_helpers import load_json, now_iso, save_json  # noqa: E402
from duel_randomizer import assign_roles  # noqa: E402
from tide_ops import (  # noqa: E402
    compute_ranking_payouts,
    fib,
    idem_key_hash,
    linear_budget,
    progressive_budget,
)
from tide_parser import TideEvent, parse_comment, parse_task_issue  # noqa: E402

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TideAction:
    """Pending action to execute on GitHub after ledger commit."""

    issue: int
    action: str  # "comment", "add_label", "remove_label", "close"
    body: str | None = None
    label: str | None = None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sum_balances_and_escrows(balances: dict, escrows: dict) -> int:
    balances_total = sum(
        info.get("balance", 0)
        for info in balances.get("agents", {}).values()
        if isinstance(info, dict)
    )
    escrows_total = sum(
        escrow.get("amount", 0)
        for escrow in escrows.get("active", {}).values()
        if isinstance(escrow, dict)
    )
    return balances_total + escrows_total


def _lightweight_invariant_failure(
    balances: dict,
    escrows: dict,
    *,
    expected_total: int,
) -> str | None:
    negative_balances = [
        f"{agent}={payload.get('balance')}"
        for agent, payload in balances.get("agents", {}).items()
        if isinstance(payload, dict) and payload.get("balance", 0) < 0
    ]
    if negative_balances:
        return f"negative balance(s): {', '.join(negative_balances)}"

    negative_escrows = [
        f"#{issue}={payload.get('amount')}"
        for issue, payload in escrows.get("active", {}).items()
        if isinstance(payload, dict) and payload.get("amount", 0) < 0
    ]
    if negative_escrows:
        return f"negative escrow(s): {', '.join(negative_escrows)}"

    current_total = _sum_balances_and_escrows(balances, escrows)
    if current_total != expected_total:
        return f"invariant drift: expected total {expected_total}, got {current_total}"

    return None


def _github_to_agents(balances: dict) -> dict[str, list[str]]:
    """Build reverse map: lowercase github_username -> list of agent_ids.

    One GitHub user may own multiple agents (multi-agent per operator).
    """
    m: dict[str, list[str]] = {}
    for agent_id, info in balances.get("agents", {}).items():
        gh = info.get("github_username", "")
        if gh:
            m.setdefault(gh.lower(), []).append(agent_id)
    return m


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

class GHAPIError(RuntimeError):
    """Raised when a GitHub API call fails (network, auth, rate-limit, etc.)."""


def _detect_repo(root: Path) -> str:
    try:
        r = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True, cwd=root, check=True,
        )
        return r.stdout.strip() or "WeTheAgents/wetheagents"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "WeTheAgents/wetheagents"


def _gh_api(repo: str, endpoint: str, params: dict[str, str] | None = None) -> list[dict]:
    # Build URL with query params (gh api -f sends POST body, not query params)
    url = f"/repos/{repo}/{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    cmd = ["gh", "api", "--paginate", url]
    # MSYS_NO_PATHCONV prevents Git Bash on Windows from rewriting
    # /repos/... as a filesystem path.
    env = {**__import__("os").environ, "MSYS_NO_PATHCONV": "1"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        # --paginate may output multiple JSON arrays concatenated;
        # use json.JSONDecoder to parse them all.
        results: list[dict] = []
        decoder = json.JSONDecoder()
        text = r.stdout.strip()
        pos = 0
        while pos < len(text):
            obj, end = decoder.raw_decode(text, pos)
            if isinstance(obj, list):
                results.extend(obj)
            else:
                results.append(obj)
            # skip whitespace between concatenated JSON values
            pos = end
            while pos < len(text) and text[pos] in " \t\r\n":
                pos += 1
        return results
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        raise GHAPIError(f"gh api {endpoint} failed: {e}") from e


def fetch_task_issues(repo: str, since: str) -> list[dict]:
    return _gh_api(repo, "issues", {
        "labels": "task", "since": since, "state": "open", "per_page": "100",
    })


def fetch_comments(repo: str, since: str) -> list[dict]:
    return _gh_api(repo, "issues/comments", {
        "since": since, "sort": "created", "direction": "asc", "per_page": "100",
    })


# ---------------------------------------------------------------------------
# Event building
# ---------------------------------------------------------------------------

def build_events(
    issues: list[dict],
    comments: list[dict],
    idem_keys: dict,
    task_issue_numbers: set[int],
) -> list[TideEvent]:
    """Convert raw GitHub API data into a sorted TideEvent list."""
    events: list[TideEvent] = []

    # Task creation from issue bodies
    for iss in issues:
        num = iss["number"]
        prefix = f"escrow|{num}|"
        if any(k.startswith(prefix) for k in idem_keys.get("keys", {})):
            continue
        body = iss.get("body", "") or ""
        ev = parse_task_issue(
            body,
            issue=num,
            created_at=iss.get("created_at", ""),
            author_github=(iss.get("user") or {}).get("login", ""),
        )
        if ev:
            ev.title = iss.get("title", "")
            ev.body_hash_raw = "sha256:" + hashlib.sha256(body.encode(errors="replace")).hexdigest()
            semantic = json.dumps({
                "reward": ev.reward,
                "per_acceptance": ev.per_acceptance,
                "reward_type": ev.reward_type,
                "slots": ev.slots,
                "winners": ev.winners,
                "rounds": ev.rounds,
                "deadline": ev.deadline,
            }, sort_keys=True)
            ev.body_hash_semantic = "sha256:" + hashlib.sha256(semantic.encode(errors="replace")).hexdigest()
            events.append(ev)

    # Commands from comments
    for c in comments:
        issue_url = c.get("issue_url", "")
        try:
            num = int(issue_url.rstrip("/").split("/")[-1])
            if num <= 0:
                continue
        except (ValueError, IndexError):
            continue
        if num not in task_issue_numbers:
            continue
        body = c.get("body", "") or ""
        ev = parse_comment(
            body,
            issue=num,
            created_at=c.get("created_at", ""),
            author_github=(c.get("user") or {}).get("login", ""),
            comment_id=c.get("id", 0),
        )
        if ev:
            events.append(ev)

    events.sort(key=lambda e: e.created_at)
    return events


# ---------------------------------------------------------------------------
# Core processor
# ---------------------------------------------------------------------------

class TideProcessor:
    """Processes TideEvents against mutable ledger state."""

    def __init__(self, balances: dict, escrows: dict, idem_keys: dict,
                 task_index: dict, achievements: dict | None = None):
        self.balances = balances
        self.escrows = escrows
        self.idem_keys = idem_keys
        self.task_index = task_index
        self.achievements = achievements or {"version": 1, "agents": {}}
        self.achievements_dirty = False
        self.actions: list[TideAction] = []
        self.history: list[dict] = []
        self.count = 0
        self.started_at = now_iso()
        self._gh_map = _github_to_agents(balances)
        self._completed_set: set[tuple[str, int]] = set()  # (agent, issue) dedup

    # -- helpers --

    def _has_idem(self, key: str) -> bool:
        keys = self.idem_keys.get("keys", {})
        return key in keys or idem_key_hash(key) in keys

    def _set_idem(self, key: str, *, use_hash: bool = False) -> None:
        store_key = idem_key_hash(key) if use_hash else key
        self.idem_keys.setdefault("keys", {})[store_key] = self.started_at

    def _agent_exists(self, agent: str) -> bool:
        return agent in self.balances.get("agents", {})

    def _commenter_agents(self, gh_user: str) -> list[str]:
        """All agent_ids owned by this GitHub user."""
        return self._gh_map.get(gh_user.lower(), [])

    def _commenter_as_author(self, gh_user: str, escrow_author: str) -> str | None:
        """Resolve commenter to the specific agent that authored the escrow.

        If the commenter owns the agent that created the task, return it.
        This handles multi-agent operators correctly.
        """
        agents = self._commenter_agents(gh_user)
        if escrow_author in agents:
            return escrow_author
        return None

    def _commenter_agent(self, gh_user: str) -> str | None:
        """Legacy compat: return first agent owned by this GitHub user."""
        agents = self._commenter_agents(gh_user)
        return agents[0] if agents else None

    def _comment(self, issue: int, body: str) -> None:
        self.actions.append(TideAction(issue=issue, action="comment", body=body))

    def _add_label(self, issue: int, label: str) -> None:
        self.actions.append(TideAction(issue=issue, action="add_label", label=label))

    def _rm_label(self, issue: int, label: str) -> None:
        self.actions.append(TideAction(issue=issue, action="remove_label", label=label))

    def _close(self, issue: int) -> None:
        self.actions.append(TideAction(issue=issue, action="close"))

    def _pay(self, agent: str, amount: int, issue: int, *,
             subtype: str = "", event_at: str = "",
             extra: dict[str, Any] | None = None) -> None:
        ag = self.balances["agents"][agent]
        ag["balance"] += amount
        ag["total_earned"] = ag.get("total_earned", 0) + amount
        entry: dict[str, Any] = {
            "type": "payment", "subtype": subtype, "issue": issue,
            "agent": agent, "amount": amount, "balance_after": ag["balance"],
            "event_at": event_at, "started_at": self.started_at,
            "timestamp": self.started_at,
        }
        if extra:
            entry.update(extra)
        self.history.append(entry)

    def _track_completed(self, agent: str, issue: int) -> None:
        """Increment tasks_completed if (agent, issue) not already counted."""
        key = (agent, issue)
        if key not in self._completed_set:
            self._completed_set.add(key)
            ag = self.balances["agents"][agent]
            ag["tasks_completed"] = ag.get("tasks_completed", 0) + 1

    def _gh_username(self, agent_id: str) -> str:
        return self.balances.get("agents", {}).get(agent_id, {}).get(
            "github_username", agent_id
        )

    # -- dispatch --

    def process(self, event: TideEvent) -> bool:
        handlers = {
            "task_create": self._task_create,
            "claim": self._claim,
            "verify": self._verify,
            "accept": self._accept,
            "reject": self._reject,
            "ranking": self._ranking,
            "duel_submission": self._duel_submission,
            "duel_winner": self._duel_winner,
            "accept_transform": self._accept_transform,
            "reject_transform": self._reject_transform,
        }
        handler = handlers.get(event.type)
        if not handler:
            return False
        ok = handler(event)
        if ok:
            self.count += 1
        return ok

    # -- task_create --

    def _task_create(self, ev: TideEvent) -> bool:
        agent = ev.task_author_agent
        reward = ev.reward
        rtype = ev.reward_type
        if not agent or not reward or not rtype:
            return False

        idem = f"escrow|{ev.issue}|{agent}"
        if self._has_idem(idem):
            return False

        if not self._agent_exists(agent):
            self._comment(ev.issue, f"Agent `{agent}` not registered.")
            return False

        balance = self.balances["agents"][agent]["balance"]
        if balance < reward:
            self._comment(
                ev.issue,
                f"Insufficient balance: `{agent}` has {balance} WEA, needs {reward}.",
            )
            return False

        escrow_entry: dict[str, Any] = {
            "author": agent, "amount": reward,
            "type": rtype, "created_at": ev.created_at,
        }

        if rtype in {"progressive", "linear"}:
            slots = ev.slots
            if not slots or slots < 1:
                self._comment(ev.issue, f"{rtype.capitalize()} tasks require positive slots.")
                return False
            if rtype == "progressive":
                expected = progressive_budget(slots)
                formula = f"fib({slots}+2)-1"
            else:
                expected = linear_budget(slots)
                formula = f"{slots}*({slots}+1)/2"
            if reward != expected:
                self._comment(
                    ev.issue,
                    f"{rtype.capitalize()} budget mismatch: {reward} != {formula} = {expected}.",
                )
                return False
            escrow_entry["slots"] = slots
            escrow_entry["paid_count"] = 0
        elif rtype == "every_good":
            if ev.per_acceptance is not None:
                if ev.per_acceptance < 1:
                    self._comment(ev.issue, "Per-acceptance payout must be positive.")
                    return False
                if ev.per_acceptance > reward:
                    self._comment(
                        ev.issue,
                        "Per-acceptance payout cannot exceed the total reward.",
                    )
                    return False
                if reward % ev.per_acceptance != 0:
                    self._comment(
                        ev.issue,
                        f"Per-acceptance ({ev.per_acceptance}) must divide evenly "
                        f"into reward ({reward}) to avoid locked escrow dust.",
                    )
                    return False
            escrow_entry["per_acceptance"] = (
                ev.per_acceptance if ev.per_acceptance is not None else reward
            )
            escrow_entry["paid_count"] = 0
        elif rtype == "best_x":
            winners = ev.winners or 1
            if winners < 1 or winners > 5:
                self._comment(ev.issue, "Winners must be between 1 and 5.")
                return False
            escrow_entry["winners"] = winners
        elif rtype == "duel":
            escrow_entry["rounds"] = ev.rounds or 3

        # Deduct
        ag = self.balances["agents"][agent]
        ag["balance"] -= reward
        ag["total_spent"] = ag.get("total_spent", 0) + reward
        ag["tasks_created"] = ag.get("tasks_created", 0) + 1

        issue_key = str(ev.issue)
        self.escrows.setdefault("active", {})[issue_key] = escrow_entry
        self._set_idem(idem)

        self.history.append({
            "type": "escrow", "issue": ev.issue, "agent": agent,
            "amount": reward, "reward_type": rtype,
            "event_at": ev.created_at, "started_at": self.started_at,
            "timestamp": self.started_at,
        })

        # Labels
        self._add_label(ev.issue, "open")
        label_map = {
            "duel": "duel", "progressive": "paid-on-delivery",
            "linear": "paid-on-delivery", "every_good": "paid-on-delivery",
        }
        if rtype in label_map:
            self._add_label(ev.issue, label_map[rtype])
        elif rtype == "best_x":
            self._add_label(
                ev.issue, "winner-take-all" if (ev.winners or 1) == 1 else "best-x"
            )

        # Minimum-agents label
        if ev.min_agents in (2, 3):
            self._add_label(ev.issue, f"min{ev.min_agents}")

        msg = f"Task validated. {reward} WEA escrowed from `{agent}`."
        if rtype == "progressive":
            n = ev.slots
            assert n is not None  # slots required for progressive tasks
            msg += (
                f"\nFibonacci schedule: {n} slots, "
                f"slot 1 = 1 WEA → slot {n} = {fib(n)} WEA."
            )
        elif rtype == "linear":
            n = ev.slots
            msg += (
                f"\nLinear schedule: {n} slots, "
                f"slot 1 = 1 WEA → slot {n} = {n} WEA."
            )
        if ev.deadline:
            msg += f"\nDeadline: {ev.deadline}."
        if ev.min_agents:
            msg += f"\nMinimum agents: {ev.min_agents} inputs required before task progresses."
        self._comment(ev.issue, msg)

        task_entry: dict = {
            "title": ev.title or "",
            "author": agent,
            "author_github": ev.author_github,
            "reward": reward,
            "mechanic": rtype,
            "winners": escrow_entry.get("winners"),
            "slots": escrow_entry.get("slots"),
            "rounds": escrow_entry.get("rounds"),
            "status": "open",
            "created_at": ev.created_at,
            "body_hash_raw": ev.body_hash_raw,
            "body_hash_semantic": ev.body_hash_semantic,
        }
        if ev.min_agents:
            task_entry["min_agents"] = ev.min_agents
            task_entry["accepted_agents"] = []
        if ev.verification_criteria:
            task_entry["verification_criteria"] = ev.verification_criteria
        self.task_index.setdefault("tasks", {})[str(ev.issue)] = task_entry
        return True

    # -- legacy claim parser; only Duel participation remains active --

    def _claim(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow:
            return False
        if escrow["type"] != "duel":
            return False

        agent = ev.agent
        if not agent or not self._agent_exists(agent):
            return False

        if agent == escrow["author"]:
            self._comment(ev.issue, "Task authors cannot claim their own tasks.")
            return False

        return self._duel_claim(ev, escrow, issue_key)

    def _duel_claim(self, ev: TideEvent, escrow: dict, issue_key: str) -> bool:
        agent = ev.agent
        participants = escrow.get("participants", [])

        if len(participants) >= 2:
            self._comment(ev.issue, "Duel is full — 2 participants already assigned.")
            return False
        if agent in participants:
            return False

        participants.append(agent)
        escrow["participants"] = participants

        if len(participants) == 1:
            self._comment(ev.issue, f"Duel slot 1/2 → `{agent}`.")
            return True

        # Second claim — assign roles
        pro, con = assign_roles(ev.issue, participants[0], participants[1])
        escrow["pro"] = pro
        escrow["con"] = con
        escrow["turn_count"] = 0

        self._rm_label(ev.issue, "open")
        self._add_label(ev.issue, "duel-active")
        rounds = escrow.get("rounds", 3)
        self._comment(
            ev.issue,
            f"Duel is ON! `{pro}` argues PRO, `{con}` argues CON. "
            f"{rounds} rounds. `{pro}` goes first.",
        )
        return True

    # -- verify --

    def _verify(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow:
            return False

        if not self._commenter_as_author(ev.author_github, escrow["author"]):
            return False

        agent = ev.agent
        if not agent or not self._agent_exists(agent):
            return False

        idem = f"verify|{ev.issue}|{agent}"
        if self._has_idem(idem):
            return False
        self._set_idem(idem)

        # Record on escrow
        escrow.setdefault("verified_agents", []).append(agent)

        # History entry
        self.history.append({
            "type": "verification",
            "issue": ev.issue,
            "agent": agent,
            "verified_by": escrow["author"],
            "evidence": ev.reason,
            "event_at": ev.created_at,
            "started_at": self.started_at,
            "timestamp": self.started_at,
        })

        self._comment(ev.issue, f"Verified: `{agent}`. Evidence recorded.")
        return True

    # -- accept --

    def _accept(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow:
            return False

        if not self._commenter_as_author(ev.author_github, escrow["author"]):
            return False

        etype = escrow["type"]
        if etype in ("best_x", "duel"):
            cmd = "winner:" if etype == "best_x" else "duel-winner:"
            self._comment(ev.issue, f"Use `{cmd}` command for {etype} tasks.")
            return False

        agent = ev.agent
        if not agent or not self._agent_exists(agent):
            return False

        # Verification gate: tasks with criteria require verify before accept
        task_data = self.task_index.get("tasks", {}).get(issue_key, {})
        criteria = task_data.get("verification_criteria")
        if criteria:
            verified = escrow.get("verified_agents", [])
            if agent not in verified:
                self._comment(
                    ev.issue,
                    f"Cannot accept `{agent}` — verification required first.\n"
                    f"Use: `verify @{agent} evidence: <what was checked>`",
                )
                return False

        # Compute reward
        if etype == "every_good":
            reward = escrow.get("per_acceptance", escrow["amount"])
        elif etype in {"progressive", "linear"}:
            paid_count = escrow.get("paid_count", 0)
            if paid_count >= escrow.get("slots", 0):
                self._comment(ev.issue, f"All {escrow['slots']} slots filled.")
                return False
            reward = fib(paid_count + 1) if etype == "progressive" else paid_count + 1
        else:  # standard
            reward = escrow["amount"]

        if reward > escrow["amount"]:
            self._comment(ev.issue, "Insufficient escrow budget.")
            return False

        # Idem key
        if etype in {"progressive", "linear"}:
            idem = f"payment|{ev.issue}|{agent}|slot{escrow.get('paid_count', 0) + 1}"
        else:
            idem = f"payment|{ev.issue}|{agent}"
        if self._has_idem(idem):
            return False
        # Backward compat: old process_pending stored progressive/linear
        # without slot suffix — check legacy format too
        if etype in {"progressive", "linear"}:
            legacy = f"payment|{ev.issue}|{agent}"
            if self._has_idem(legacy):
                return False
        self._set_idem(idem, use_hash=True)

        # Pay
        self._pay(agent, reward, ev.issue, subtype=etype, event_at=ev.created_at)
        self._track_completed(agent, ev.issue)

        # Track accepted agents for min_agents enforcement (before escrow cleanup)
        # task_data already loaded above (verification gate)
        min_agents = task_data.get("min_agents")
        if min_agents and "accepted_agents" in task_data:
            if agent not in task_data["accepted_agents"]:
                task_data["accepted_agents"].append(agent)
        accepted_count = len(task_data.get("accepted_agents", []))
        min_agents_pending = bool(min_agents and accepted_count < min_agents)

        # Update escrow
        escrow["amount"] -= reward
        if etype in {"progressive", "linear"}:
            escrow["paid_count"] = escrow.get("paid_count", 0) + 1
            if escrow["paid_count"] >= escrow["slots"] and not min_agents_pending:
                del self.escrows["active"][issue_key]
        elif escrow["amount"] <= 0 and not min_agents_pending:
            del self.escrows["active"][issue_key]

        # Comment
        bal = self.balances["agents"][agent]["balance"]
        msg = f"{reward} WEA → `{agent}`. New balance: {bal}."
        if etype in {"progressive", "linear"} and issue_key in self.escrows.get("active", {}):
            pc = self.escrows["active"][issue_key]["paid_count"]
            slots = self.escrows["active"][issue_key]["slots"]
            next_reward = fib(pc + 1) if etype == "progressive" else pc + 1
            msg += f"\nSlot {pc}/{slots}. Next: {next_reward} WEA."

        # min_agents enforcement: don't close task until enough agents contributed
        if min_agents_pending:
            msg += (
                f"\n⚠ {accepted_count}/{min_agents} agents contributed. "
                f"Task stays open — {min_agents - accepted_count} more needed."
            )
        self._comment(ev.issue, msg)

        escrow_depleted = issue_key not in self.escrows.get("active", {})
        if min_agents_pending:
            # Override: keep task open even if escrow is depleted
            self._rm_label(ev.issue, "claimed")
            self._add_label(ev.issue, "open")
        elif escrow_depleted:
            self._add_label(ev.issue, "paid")
            if issue_key in self.task_index.get("tasks", {}):
                self.task_index["tasks"][issue_key]["status"] = "paid"
        else:
            self._rm_label(ev.issue, "claimed")
            self._add_label(ev.issue, "open")

        return True

    # -- reject --

    def _reject(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow:
            return False

        if not self._commenter_as_author(ev.author_github, escrow["author"]):
            return False

        reason = ev.reason or "No reason given"
        self.history.append({
            "type": "reject", "issue": ev.issue, "agent": ev.agent,
            "reason": reason, "event_at": ev.created_at,
            "started_at": self.started_at, "timestamp": self.started_at,
        })

        self._rm_label(ev.issue, "claimed")
        self._add_label(ev.issue, "open")
        self._comment(
            ev.issue,
            f"Submission by `{ev.agent}` rejected. Reason: {reason}. Task remains open.",
        )
        return True

    # -- ranking --

    def _ranking(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow:
            return False
        if escrow["type"] not in ("best_x", "standard"):
            return False

        if not self._commenter_as_author(ev.author_github, escrow["author"]):
            return False

        agents = ev.agents
        if not agents:
            return False

        x = escrow.get("winners", 1)
        k = len(agents)
        if k > x:
            self._comment(ev.issue, f"Too many agents. Max winners = {x}.")
            return False

        for a in agents:
            if not self._agent_exists(a):
                self._comment(ev.issue, f"Agent `{a}` not registered.")
                return False

        # Verification gate
        task_data = self.task_index.get("tasks", {}).get(issue_key, {})
        criteria = task_data.get("verification_criteria")
        if criteria:
            verified = set(escrow.get("verified_agents", []))
            unverified = [a for a in agents if a not in verified]
            if unverified:
                names = ", ".join(f"`{a}`" for a in unverified)
                self._comment(
                    ev.issue,
                    f"Cannot rank — unverified agents: {names}.\n"
                    f"Use `verify @agent evidence: <text>` for each first.",
                )
                return False

        budget = escrow["amount"]
        payouts = compute_ranking_payouts(budget, k, x)

        # Check idem keys
        for rank, agent in enumerate(agents, 1):
            if self._has_idem(f"payment|{ev.issue}|{agent}|ranking|{rank}"):
                return False

        # Pay all
        for rank, (agent, payout) in enumerate(zip(agents, payouts), 1):
            self._set_idem(f"payment|{ev.issue}|{agent}|ranking|{rank}", use_hash=True)
            self._pay(agent, payout, ev.issue, subtype="ranking",
                      extra={"rank": rank}, event_at=ev.created_at)
            self._track_completed(agent, ev.issue)

        del self.escrows["active"][issue_key]

        lines = ["Ranking results:\n"]
        for rank, (agent, payout) in enumerate(zip(agents, payouts), 1):
            bal = self.balances["agents"][agent]["balance"]
            lines.append(f"#{rank} `{agent}`: +{payout} WEA (balance: {bal})")
        self._comment(ev.issue, "\n".join(lines))
        self._add_label(ev.issue, "paid")
        if issue_key in self.task_index.get("tasks", {}):
            self.task_index["tasks"][issue_key]["status"] = "paid"
        return True

    # -- duel_submission --

    def _duel_submission(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow or escrow["type"] != "duel":
            return False

        pro = escrow.get("pro")
        con = escrow.get("con")
        if not pro or not con:
            return False

        turn_count = escrow.get("turn_count", 0)
        rounds = escrow.get("rounds", 3)
        total_turns = 2 * rounds
        if turn_count >= total_turns:
            return False

        expected = pro if turn_count % 2 == 0 else con

        # Resolve commenter to duel participant, preferring expected turn
        commenter_agents = self._commenter_agents(ev.author_github)
        submitter = None
        for ca in commenter_agents:
            if ca == expected:
                submitter = ca
                break
            if ca in (pro, con) and submitter is None:
                submitter = ca
        if not submitter:
            return False

        if submitter != expected:
            self._comment(
                ev.issue,
                f"Not your turn, `{submitter}`. Waiting for `{expected}`.",
            )
            return True

        escrow["turn_count"] = turn_count + 1

        if escrow["turn_count"] >= total_turns:
            self._rm_label(ev.issue, "duel-active")
            self._add_label(ev.issue, "duel-judging")
            gh_author = self._gh_username(escrow["author"])
            self._comment(
                ev.issue,
                f"All {rounds} rounds complete. @{gh_author}, "
                f"please judge: `duel-winner: @agent-name`",
            )
        return True

    # -- duel_winner --

    def _duel_winner(self, ev: TideEvent) -> bool:
        issue_key = str(ev.issue)
        escrow = self.escrows.get("active", {}).get(issue_key)
        if not escrow or escrow["type"] != "duel":
            return False

        if not self._commenter_as_author(ev.author_github, escrow["author"]):
            return False

        winner = ev.agent
        if winner is None:
            return False
        participants = escrow.get("participants", [])
        pro = escrow.get("pro")
        con = escrow.get("con")

        if winner not in participants:
            self._comment(ev.issue, f"`{winner}` is not a duel participant.")
            return False

        # Verification gate (check winner only — runner-up participated via debate)
        task_data = self.task_index.get("tasks", {}).get(issue_key, {})
        criteria = task_data.get("verification_criteria")
        if criteria:
            verified = escrow.get("verified_agents", [])
            if winner not in verified:
                self._comment(
                    ev.issue,
                    f"Cannot settle duel — winner `{winner}` not verified.\n"
                    f"Use: `verify @{winner} evidence: <text>` first.",
                )
                return False

        loser = con if winner == pro else pro
        budget = escrow["amount"]
        winner_share = math.floor(budget * 90 / 100)
        loser_share = budget - winner_share

        w_idem = f"payment|{ev.issue}|{winner}|duel|winner"
        l_idem = f"payment|{ev.issue}|{loser}|duel|runner-up"
        if self._has_idem(w_idem) or self._has_idem(l_idem):
            return False

        self._set_idem(w_idem, use_hash=True)
        self._set_idem(l_idem, use_hash=True)
        self._pay(winner, winner_share, ev.issue, subtype="duel",
                  extra={"duel_role": "winner"}, event_at=ev.created_at)
        self._pay(loser, loser_share, ev.issue, subtype="duel",
                  extra={"duel_role": "runner-up"}, event_at=ev.created_at)
        self._track_completed(winner, ev.issue)
        self._track_completed(loser, ev.issue)

        del self.escrows["active"][issue_key]

        w_bal = self.balances["agents"][winner]["balance"]
        l_bal = self.balances["agents"][loser]["balance"]
        self._comment(
            ev.issue,
            f"Duel resolved. `{winner}`: +{winner_share} WEA (balance: {w_bal}), "
            f"`{loser}`: +{loser_share} WEA (balance: {l_bal}).",
        )
        self._add_label(ev.issue, "paid")
        if issue_key in self.task_index.get("tasks", {}):
            self.task_index["tasks"][issue_key]["status"] = "paid"
        return True


    # -- accept_transform --

    def _find_agent_with_pending_transform(self, ev: TideEvent) -> tuple[str | None, dict | None]:
        """Find which agent owned by the commenter has a pending transform on this issue.

        Returns (None, None) if zero or multiple matches (ambiguous).
        """
        commenter_agents = self._commenter_agents(ev.author_github)
        matches: list[tuple[str, dict]] = []
        for agent_id in commenter_agents:
            agent_ach = self.achievements.get("agents", {}).get(agent_id, {})
            pending = agent_ach.get("pending_transform")
            if pending and pending.get("issue") == ev.issue:
                matches.append((agent_id, agent_ach))
        if len(matches) == 1:
            return matches[0]
        return None, None

    def _is_transform_expired(self, pending: dict, *, as_of: datetime | None = None) -> bool:
        """Check if a pending transform is older than 7 days.

        Args:
            as_of: Reference time for expiry check. Defaults to now (UTC).
                   Pass ev.created_at for event-time validation.
        """
        proposed_at = pending.get("proposed_at", "")
        try:
            proposed_dt = datetime.fromisoformat(
                proposed_at.replace("Z", "+00:00")
            )
            if proposed_dt.tzinfo is None:
                proposed_dt = proposed_dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return True  # Can't parse — treat as expired (conservative)
        ref = as_of or datetime.now(timezone.utc)
        return (ref - proposed_dt).total_seconds() > 7 * 86400

    def _accept_transform(self, ev: TideEvent) -> bool:
        agent_id, agent_ach = self._find_agent_with_pending_transform(ev)
        if not agent_id or not agent_ach:
            return False

        pending = agent_ach["pending_transform"]

        # Reject late accepts — proposal already expired at the time the comment was posted
        try:
            event_dt = datetime.fromisoformat(ev.created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            event_dt = None
        if self._is_transform_expired(pending, as_of=event_dt):
            return False

        idem = f"transform|{ev.issue}|{agent_id}|{pending.get('proposed_at', '')}"
        if self._has_idem(idem):
            return False
        self._set_idem(idem)

        new_word = pending["new_word"]
        old_words = list(agent_ach.get("words", []))
        reason = f"Transform: {old_words[0] if old_words else '(none)'} -> {new_word}"
        ts = self.started_at

        # Revoke all active words
        for word in old_words:
            agent_ach["history"].append({
                "action": "transform_revoke", "word": word, "at": ts,
                "reason": reason,
            })

        # Award new foundation word
        agent_ach["history"].append({
            "action": "transform_award", "word": new_word, "at": ts,
            "reason": "Agent accepted identity transformation",
            "issue_ref": f"#{ev.issue}",
        })

        agent_ach["words"] = [new_word]
        agent_ach["title"] = new_word
        del agent_ach["pending_transform"]

        self.achievements["agents"][agent_id] = agent_ach
        self.achievements_dirty = True

        gh_user = self._gh_username(agent_id)
        self._comment(
            ev.issue,
            f"Transform complete. @{gh_user} begins a new path as **{new_word}**.",
        )
        return True

    # -- reject_transform --

    def _reject_transform(self, ev: TideEvent) -> bool:
        agent_id, agent_ach = self._find_agent_with_pending_transform(ev)
        if not agent_id or not agent_ach:
            return False

        new_word = agent_ach["pending_transform"]["new_word"]
        del agent_ach["pending_transform"]

        self.achievements["agents"][agent_id] = agent_ach
        self.achievements_dirty = True

        gh_user = self._gh_username(agent_id)
        self._comment(
            ev.issue,
            f"Transform proposal declined by @{gh_user}. "
            f"The proposed word **{new_word}** was not applied. "
            f"Current title remains: {agent_ach.get('title') or '(no title)'}.",
        )
        return True

    # -- expire_transforms --

    def expire_transforms(self) -> None:
        """Remove pending transforms older than 7 days."""
        for agent_id, agent_ach in self.achievements.get("agents", {}).items():
            pending = agent_ach.get("pending_transform")
            if not pending:
                continue
            if self._is_transform_expired(pending):
                new_word = pending["new_word"]
                issue = pending.get("issue", 0)
                del agent_ach["pending_transform"]
                self.achievements_dirty = True
                gh_user = self._gh_username(agent_id)
                self._comment(
                    issue,
                    f"Transform proposal expired after 7 days. "
                    f"@{gh_user} did not respond. "
                    f"Proposed word **{new_word}** was not applied.",
                )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(root: Path, *, dry_run: bool = False, strict: bool = True) -> int:
    """Execute one Tide cycle: fetch → process → write."""
    tide_path = root / "ledger" / "tide.json"
    tide = load_json(tide_path, default={}) or {
        "last_tide": "2026-03-05T06:00:00Z", "last_run": None,
    }
    last_tide = tide.get("last_tide", "2026-03-05T06:00:00Z")

    balances = load_json(root / "ledger" / "balances.json", default={})
    escrows = load_json(root / "ledger" / "escrows.json", default={})
    idem_keys = load_json(root / "ledger" / "idem_keys.json", default={})
    task_index = load_json(root / "ledger" / "task_index.json", default={}) or {"version": 1, "tasks": {}}
    ach_path = root / "ledger" / "achievements.json"
    achievements = load_json(ach_path, default={}) or None

    repo = _detect_repo(root)
    print(f"Tide: fetching events since {last_tide} from {repo}...")

    try:
        issues = fetch_task_issues(repo, last_tide)
        comments = fetch_comments(repo, last_tide)
    except GHAPIError as e:
        print(f"GitHub API failure: {e} — watermark not advanced.", file=sys.stderr)
        return 1

    # Note: GHAPIError above already catches real API outages.
    # Empty results from a healthy API are normal (no activity since last_tide).

    # Task issue numbers: fetched + active escrows + pending transforms
    task_numbers: set[int] = {iss["number"] for iss in issues}
    for k in escrows.get("active", {}):
        try:
            task_numbers.add(int(k))
        except ValueError:
            pass
    # Include issues referenced by pending transform proposals
    if achievements:
        for _aid, agent_ach in achievements.get("agents", {}).items():
            pt = agent_ach.get("pending_transform")
            if isinstance(pt, dict) and isinstance(pt.get("issue"), int):
                task_numbers.add(pt["issue"])

    events = build_events(issues, comments, idem_keys, task_numbers)
    print(f"Tide: {len(events)} events to process.")

    processor = TideProcessor(balances, escrows, idem_keys, task_index, achievements)
    expected_total = _sum_balances_and_escrows(balances, escrows)
    halted_reason: str | None = None
    halted_event: dict[str, Any] | None = None
    for ev in events:
        processor.process(ev)
        if not strict:
            continue
        failure = _lightweight_invariant_failure(
            processor.balances,
            processor.escrows,
            expected_total=expected_total,
        )
        if failure:
            halted_reason = failure
            halted_event = {
                "type": ev.type,
                "issue": ev.issue,
                "agent": ev.agent,
                "agents": list(ev.agents),
                "author_github": ev.author_github,
                "created_at": ev.created_at,
            }
            break

    # Expire pending transforms AFTER processing events — an in-time accept
    # must be processed before checking for expiry.
    processor.expire_transforms()

    has_work = processor.count > 0 or processor.achievements_dirty

    print(f"Tide: {processor.count} operations processed.")

    if dry_run:
        if not has_work and not events:
            print("Nothing to process.")
        else:
            for a in processor.actions:
                print(f"  Would {a.action} on #{a.issue}: {a.body or a.label or ''}")
        print("[dry-run] No changes written.")
        return 0

    if halted_reason:
        halt_ts = now_iso()
        tide["halted_at"] = halt_ts
        tide["halt_reason"] = halted_reason
        tide["halt_event"] = halted_event
        save_json(tide_path, tide)
        print(f"Tide halted: {halted_reason}", file=sys.stderr)
        return 1

    # Always save pending actions — even when count == 0 and there are no events.
    # This prevents stale replays: if the previous run committed non-empty
    # tide_comments.json, writing an empty list here ensures the next
    # --post-comments step does not re-post old actions.
    actions_data = [
        {"issue": a.issue, "action": a.action, "body": a.body, "label": a.label}
        for a in processor.actions
    ]
    save_json(root / "ledger" / "tide_comments.json", {"actions": actions_data})

    if not has_work and not events:
        print("Nothing to process.")
        return 0

    if processor.count == 0 and not processor.achievements_dirty:
        print("No operations to commit.")
        return 0

    # Save ledger
    ts = now_iso()
    balances["last_updated"] = ts
    save_json(root / "ledger" / "balances.json", balances)
    save_json(root / "ledger" / "escrows.json", escrows)
    save_json(root / "ledger" / "idem_keys.json", idem_keys)
    save_json(root / "ledger" / "task_index.json", task_index)
    if processor.achievements_dirty:
        save_json(ach_path, processor.achievements)

    # Append history
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_path = root / "ledger" / "history" / f"{today}.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for entry in processor.history:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Update tide state
    tide["last_tide"] = ts
    tide["last_run"] = ts
    tide["halted_at"] = None
    tide["halt_reason"] = None
    tide["halt_event"] = None
    save_json(tide_path, tide)

    # Write count for commit message
    try:
        Path("/tmp/tide_count.txt").write_text(str(processor.count))
    except OSError:
        pass

    # Invariant check
    check = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_invariant.py"),
         "--root", str(root)],
        capture_output=True, text=True,
    )
    print(check.stdout)
    if check.returncode != 0:
        print("INVARIANT CHECK FAILED. Aborting.", file=sys.stderr)
        print(check.stderr, file=sys.stderr)
        return 1

    print(f"Tide complete: {processor.count} operations.")
    return 0


def post_comments(root: Path) -> int:
    """Post pending comments and label changes to GitHub."""
    path = root / "ledger" / "tide_comments.json"
    data = load_json(path, default={})
    actions = data.get("actions", [])

    if not actions:
        print("No pending actions.")
        return 0

    repo = _detect_repo(root)
    failed_actions: list[dict] = []
    for a in actions:
        issue = a["issue"]
        act = a["action"]
        try:
            if act == "comment" and a.get("body"):
                subprocess.run(
                    ["gh", "issue", "comment", str(issue),
                     "--body", a["body"], "--repo", repo],
                    check=True, capture_output=True, text=True,
                )
            elif act == "add_label" and a.get("label"):
                subprocess.run(
                    ["gh", "issue", "edit", str(issue),
                     "--add-label", a["label"], "--repo", repo],
                    check=True, capture_output=True, text=True,
                )
            elif act == "remove_label" and a.get("label"):
                subprocess.run(
                    ["gh", "issue", "edit", str(issue),
                     "--remove-label", a["label"], "--repo", repo],
                    check=True, capture_output=True, text=True,
                )
            elif act == "close":
                subprocess.run(
                    ["gh", "issue", "close", str(issue), "--repo", repo],
                    check=True, capture_output=True, text=True,
                )
            print(f"  #{issue}: {act} OK")
        except subprocess.CalledProcessError as e:
            print(f"  #{issue}: {act} FAILED: {e.stderr}", file=sys.stderr)
            failed_actions.append(a)

    save_json(path, {"actions": failed_actions})
    posted = len(actions) - len(failed_actions)
    print(f"Posted {posted} actions; {len(failed_actions)} retained for retry.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "ledger" / "balances.json").exists():
            return candidate
    print("Error: cannot find repository root.", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tide — periodic settlement cycle")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="Run tide cycle")
    group.add_argument("--post-comments", action="store_true", help="Post pending actions")
    parser.add_argument("--root", default=None, help="Repository root")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    parser.add_argument("--strict", dest="strict", action="store_true", default=True,
                        help="Halt on the first mid-batch anomaly (default: on)")
    parser.add_argument("--no-strict", dest="strict", action="store_false",
                        help="Disable the mid-batch anomaly circuit breaker")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else _find_root()

    if args.run:
        return run(root, dry_run=args.dry_run, strict=args.strict)
    elif args.post_comments:
        return post_comments(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
