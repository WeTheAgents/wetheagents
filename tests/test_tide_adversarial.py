"""Adversarial tests for tide.py."""

from __future__ import annotations

import hashlib
import pytest

from scripts.tide import TideProcessor, build_events
from scripts.tide_parser import TideEvent

def _balances():
    return {
        "agents": {
            "alice@x": {"balance": 100, "github_username": "alice-gh"},
            "bob@y": {"balance": 10, "github_username": "bob-gh"},
            "attacker@z": {"balance": 0, "github_username": "attacker-gh"},
        }
    }

def _escrows(**active):
    return {"active": dict(active)}

def _idem(*keys):
    return {"keys": {k: "2026-01-01T00:00:00Z" for k in keys}}

def _proc(balances=None, escrows=None, idem_keys=None, task_index=None):
    return TideProcessor(
        balances=balances or _balances(),
        escrows=escrows or _escrows(),
        idem_keys=idem_keys or _idem(),
        task_index=task_index or {"version": 1, "tasks": {}},
    )

def test_non_utf8_input():
    # Attack Vector: An attacker submits an issue or comment containing unpaired surrogate
    # characters or invalid UTF-8 (simulated here by a surrogate pair that fails default encode).
    # If unhandled, body.encode() would throw UnicodeEncodeError and crash the entire Tide batch.
    bad_body = "Evil surrogate \udce2 injected"
    issues = [{
        "number": 1,
        "body": bad_body,
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "attacker-gh"},
        "title": "test"
    }]
    events = build_events(issues, [], _idem(), {1})
    # build_events should process it without crashing (using errors="replace").
    # It won't yield a task_create event because it lacks the required template fields,
    # but the crucial part is that it survives the parsing and hashing.
    assert len(events) == 0

def test_empty_body():
    # Attack Vector: An attacker submits an issue or comment with a None or entirely empty body.
    # The system could crash with AttributeError when calling .strip() or .encode().
    issues = [{
        "number": 1,
        "body": None,
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "attacker-gh"}
    }]
    comments = [{
        "issue_url": "https://api.github.com/repos/x/y/issues/1",
        "body": None,
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "attacker-gh"},
        "id": 100
    }]
    events = build_events(issues, comments, _idem(), {1})
    # Should safely parse to 0 events without crashing.
    assert len(events) == 0

def test_non_operator_accept_command():
    # Attack Vector: An attacker attempts to 'accept' their own or someone else's submission
    # on a task they did not create, in order to steal escrowed funds.
    p = _proc(escrows=_escrows(**{
        "1": {"author": "alice@x", "amount": 20, "type": "standard", "created_at": "2026-01-01T00:00:00Z"},
    }))
    comments = [{
        "issue_url": "https://api.github.com/repos/x/y/issues/1",
        "body": "accept @attacker@z",
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "attacker-gh"},
        "id": 100
    }]
    events = build_events([], comments, _idem(), {1})
    assert len(events) == 1
    assert not p.process(events[0])
    # Ensure balance hasn't changed.
    assert p.balances["agents"]["attacker@z"]["balance"] == 0

def test_task_body_injection():
    # Attack Vector: An attacker embeds a command (like 'accept @attacker') directly within
    # the issue creation body. If the system mixes up issue bodies and comments, it might
    # execute the unauthorized command.
    body = "### Your Agent ID\n\nalice@x\n\n### Reward (WEA)\n\n10\n\n### Reward Type\n\nwinner take all\n\naccept @attacker@z"
    issues = [{
        "number": 1,
        "body": body,
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "alice-gh"},
        "title": "task"
    }]
    events = build_events(issues, [], _idem(), {1})
    # It should parse as a task_create but NOT as an accept command.
    assert len(events) == 1
    assert events[0].type == "task_create"
    assert "accept" not in [e.type for e in events]

def test_idem_key_collision_different_event_type():
    # Attack Vector: An attacker tries to trigger a bug where generating one event (like 'claim')
    # produces an idempotency key that accidentally blocks a subsequent valid event (like 'accept').
    # We verify that prefixes ('claim|', 'payment|') isolate event types successfully.
    p = _proc(
        escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard", "created_at": "2026-01-01T00:00:00Z"},
        }),
        # Attacker already claimed the issue, injecting a claim idem key
        idem_keys=_idem("claim|1|bob@y")
    )
    # Now the author tries to accept bob's work
    comments = [{
        "issue_url": "https://api.github.com/repos/x/y/issues/1",
        "body": "accept @bob@y",
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "alice-gh"},
        "id": 100
    }]
    events = build_events([], comments, _idem(), {1})
    assert len(events) == 1
    assert events[0].type == "accept"
    # Process should succeed because 'payment|1|bob@y' != 'claim|1|bob@y'
    assert p.process(events[0]) is True
    assert p.balances["agents"]["bob@y"]["balance"] == 30 # 10 + 20

def test_malformed_issue_numbers():
    # Attack Vector: An attacker posts a comment with a non-numeric, 0, or negative issue URL
    # attempting to break the integer conversion (int(issue_url...)) or bypass positive int logic.
    comments = [
        {
            "issue_url": "https://api.github.com/repos/x/y/issues/bad123",
            "body": "claim attacker@z",
            "created_at": "2026-03-01T00:00:00Z",
            "user": {"login": "attacker-gh"},
            "id": 100
        },
        {
            "issue_url": "https://api.github.com/repos/x/y/issues/0",
            "body": "claim attacker@z",
            "created_at": "2026-03-01T00:00:01Z",
            "user": {"login": "attacker-gh"},
            "id": 101
        },
        {
            "issue_url": "https://api.github.com/repos/x/y/issues/-5",
            "body": "claim attacker@z",
            "created_at": "2026-03-01T00:00:02Z",
            "user": {"login": "attacker-gh"},
            "id": 102
        }
    ]
    events = build_events([], comments, _idem(), {1})
    # Should safely catch the ValueError/IndexError and skip 0/-5 due to not being in task_issue_numbers (which is {1})
    assert len(events) == 0

def test_double_claim():
    # Attack Vector: An attacker posts two rapid 'claim' comments to exploit a race condition
    # or state-machine flaw to claim the task multiple times. Idempotency keys should block it.
    p = _proc(escrows=_escrows(**{
        "1": {"author": "alice@x", "amount": 20, "type": "standard", "created_at": "2026-01-01T00:00:00Z"},
    }))
    comments = [
        {
            "issue_url": "https://api.github.com/repos/x/y/issues/1",
            "body": "claim attacker@z",
            "created_at": "2026-03-01T00:00:00Z",
            "user": {"login": "attacker-gh"},
            "id": 100
        },
        {
            "issue_url": "https://api.github.com/repos/x/y/issues/1",
            "body": "claim attacker@z",
            "created_at": "2026-03-01T00:00:01Z",
            "user": {"login": "attacker-gh"},
            "id": 101
        }
    ]
    events = build_events([], comments, _idem(), {1})
    assert len(events) == 2
    
    assert p.process(events[0]) is True
    # The second claim should be blocked by idempotency
    assert p.process(events[1]) is False
    # Ensure there's only one successful claim action (e.g. only one comment generated)
    comments_made = [a for a in p.actions if a.action == "comment" and "Task claimed by" in a.body]
    assert len(comments_made) == 1

def test_missing_required_fields():
    # Attack Vector: An attacker submits a task creation issue with missing critical fields
    # (e.g. reward is empty) to bypass budget checks or corrupt the ledger.
    body = "### Your Agent ID\n\nattacker@z\n\n### Reward (WEA)\n\n\n\n### Reward Type\n\nstandard"
    issues = [{
        "number": 1,
        "body": body,
        "created_at": "2026-03-01T00:00:00Z",
        "user": {"login": "attacker-gh"},
        "title": "task"
    }]
    events = build_events(issues, [], _idem(), {1})
    # Should fail to parse as a valid task creation event
    assert len(events) == 0
