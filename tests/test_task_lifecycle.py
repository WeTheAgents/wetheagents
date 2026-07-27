"""Lifecycle tests for TideProcessor task settlement flows.

TideProcessor does not model a standalone submit event for non-duel tasks.
These tests assert the ledger transitions around submission: claim, accept,
payment, and final paid state.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.tide import TideProcessor
from scripts.tide_ops import idem_key_hash
from scripts.tide_parser import TideEvent


def _agent(balance: int, github_username: str, *, spent: int = 0, created: int = 0) -> dict:
    return {
        "balance": balance,
        "github_username": github_username,
        "total_earned": balance + spent,
        "total_spent": spent,
        "tasks_completed": 0,
        "tasks_created": created,
    }


def _balances() -> dict:
    return {
        "agents": {
            "alice@x": _agent(100, "alice-gh"),
            "bob@y": _agent(50, "bob-gh"),
            "carol@z": _agent(30, "carol-gh"),
        }
    }


def _escrows(**active: dict) -> dict:
    return {"version": 1, "active": dict(active)}


def _idem(*keys: str) -> dict:
    return {"keys": {key: "2026-04-01T09:00:00Z" for key in keys}}


def _ev(type: str, issue: int, *, agent: str | None = None, agents: list[str] | None = None, **kwargs) -> TideEvent:
    return TideEvent(
        type=type,
        issue=issue,
        created_at=kwargs.pop("created_at", "2026-04-01T10:00:00Z"),
        author_github=kwargs.pop("author_github", "alice-gh"),
        source=kwargs.pop("source", "comment"),
        comment_id=kwargs.pop("comment_id", 100),
        agent=agent,
        agents=agents or [],
        reason=kwargs.pop("reason", None),
        task_author_agent=kwargs.pop("task_author_agent", None),
        reward=kwargs.pop("reward", None),
        per_acceptance=kwargs.pop("per_acceptance", None),
        reward_type=kwargs.pop("reward_type", None),
        slots=kwargs.pop("slots", None),
        winners=kwargs.pop("winners", None),
        rounds=kwargs.pop("rounds", None),
        deadline=kwargs.pop("deadline", None),
        min_agents=kwargs.pop("min_agents", None),
        verification_criteria=kwargs.pop("verification_criteria", None),
        title=kwargs.pop("title", None),
        body_hash_raw=kwargs.pop("body_hash_raw", None),
        body_hash_semantic=kwargs.pop("body_hash_semantic", None),
    )


def _proc(*, balances: dict | None = None, escrows: dict | None = None, idem_keys: dict | None = None, task_index: dict | None = None) -> TideProcessor:
    return TideProcessor(
        balances=deepcopy(balances or _balances()),
        escrows=deepcopy(escrows or _escrows()),
        idem_keys=deepcopy(idem_keys or {"keys": {}}),
        task_index=deepcopy(task_index or {"version": 1, "tasks": {}}),
    )


def _assert_balances(proc: TideProcessor, *, alice: int, bob: int, carol: int) -> None:
    agents = proc.balances["agents"]
    assert agents["alice@x"]["balance"] == alice
    assert agents["bob@y"]["balance"] == bob
    assert agents["carol@z"]["balance"] == carol


def _assert_idem_keys(proc: TideProcessor, *, raw: set[str], hashed: set[str]) -> None:
    expected = set(raw) | {idem_key_hash(key) for key in hashed}
    assert set(proc.idem_keys["keys"]) == expected


def _assert_task_status(
    proc: TideProcessor,
    issue: int,
    *,
    status: str,
    mechanic: str,
    accepted_agents: list[str] | None = None,
) -> None:
    task = proc.task_index["tasks"][str(issue)]
    assert task["status"] == status
    assert task["mechanic"] == mechanic
    if accepted_agents is None:
        assert "accepted_agents" not in task
    else:
        assert task["accepted_agents"] == accepted_agents


def _standard_seeded_processor() -> TideProcessor:
    return _proc(
        balances={
            "agents": {
                "alice@x": _agent(80, "alice-gh", spent=20, created=1),
                "bob@y": _agent(50, "bob-gh"),
                "carol@z": _agent(30, "carol-gh"),
            }
        },
        escrows=_escrows(**{
            "101": {
                "author": "alice@x",
                "amount": 20,
                "type": "standard",
                "created_at": "2026-04-01T09:00:00Z",
            }
        }),
        idem_keys=_idem("escrow|101|alice@x"),
        task_index={
            "version": 1,
            "tasks": {
                "101": {
                    "title": "Seeded standard lifecycle task",
                    "author": "alice@x",
                    "author_github": "alice-gh",
                    "reward": 20,
                    "mechanic": "standard",
                    "status": "open",
                    "created_at": "2026-04-01T09:00:00Z",
                }
            },
        },
    )


def _assert_standard_escrowed(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=80, bob=50, carol=30)
    assert proc.escrows["active"]["101"] == {
        "author": "alice@x",
        "amount": 20,
        "type": "standard",
        "created_at": "2026-04-01T09:00:00Z",
    }
    _assert_idem_keys(proc, raw={"escrow|101|alice@x"}, hashed=set())
    _assert_task_status(proc, 101, status="open", mechanic="standard")
    assert proc.count == 0


def _assert_standard_claim_rejected(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=80, bob=50, carol=30)
    assert proc.escrows["active"]["101"]["amount"] == 20
    _assert_idem_keys(proc, raw={"escrow|101|alice@x"}, hashed=set())
    _assert_task_status(proc, 101, status="open", mechanic="standard")
    assert proc.count == 0


def _assert_standard_paid(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=80, bob=70, carol=30)
    assert "101" not in proc.escrows["active"]
    _assert_idem_keys(
        proc,
        raw={"escrow|101|alice@x"},
        hashed={"payment|101|bob@y"},
    )
    _assert_task_status(proc, 101, status="paid", mechanic="standard")
    assert proc.count == 1


def _run_standard_lifecycle(stop_after: str) -> TideProcessor:
    proc = _standard_seeded_processor()
    _assert_standard_escrowed(proc)
    if stop_after == "escrow":
        return proc

    claim = _ev(
        "claim",
        101,
        agent="bob@y",
        author_github="bob-gh",
        created_at="2026-04-01T10:05:00Z",
    )
    assert proc.process(claim) is False
    _assert_standard_claim_rejected(proc)
    if stop_after == "claim_rejected":
        return proc

    accept = _ev(
        "accept",
        101,
        agent="bob@y",
        author_github="alice-gh",
        created_at="2026-04-01T10:20:00Z",
        comment_id=101,
    )
    assert proc.process(accept) is True
    _assert_standard_paid(proc)
    if stop_after == "accept":
        return proc

    replay = _ev(
        "accept",
        101,
        agent="bob@y",
        author_github="alice-gh",
        created_at="2026-04-01T10:21:00Z",
        comment_id=102,
    )
    assert proc.process(replay) is False
    _assert_standard_paid(proc)
    return proc


def _assert_every_good_created(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=90, bob=50, carol=30)
    assert proc.escrows["active"]["202"] == {
        "author": "alice@x",
        "amount": 10,
        "type": "every_good",
        "created_at": "2026-04-01T11:00:00Z",
        "per_acceptance": 5,
        "paid_count": 0,
    }
    _assert_idem_keys(proc, raw={"escrow|202|alice@x"}, hashed=set())
    _assert_task_status(proc, 202, status="open", mechanic="every_good", accepted_agents=[])
    assert proc.count == 1


def _assert_every_good_claims_rejected(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=90, bob=50, carol=30)
    assert proc.escrows["active"]["202"]["amount"] == 10
    _assert_idem_keys(proc, raw={"escrow|202|alice@x"}, hashed=set())
    _assert_task_status(proc, 202, status="open", mechanic="every_good", accepted_agents=[])
    assert proc.count == 1


def _assert_every_good_first_payment(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=90, bob=55, carol=30)
    assert proc.escrows["active"]["202"] == {
        "author": "alice@x",
        "amount": 5,
        "type": "every_good",
        "created_at": "2026-04-01T11:00:00Z",
        "per_acceptance": 5,
        "paid_count": 0,
    }
    _assert_idem_keys(
        proc,
        raw={"escrow|202|alice@x"},
        hashed={"payment|202|bob@y"},
    )
    _assert_task_status(proc, 202, status="open", mechanic="every_good", accepted_agents=["bob@y"])
    assert proc.count == 2


def _assert_every_good_paid(proc: TideProcessor) -> None:
    _assert_balances(proc, alice=90, bob=55, carol=35)
    assert "202" not in proc.escrows["active"]
    _assert_idem_keys(
        proc,
        raw={"escrow|202|alice@x"},
        hashed={"payment|202|bob@y", "payment|202|carol@z"},
    )
    _assert_task_status(
        proc,
        202,
        status="paid",
        mechanic="every_good",
        accepted_agents=["bob@y", "carol@z"],
    )
    assert proc.count == 3


def _run_every_good_lifecycle(stop_after: str) -> TideProcessor:
    proc = _proc()
    create = _ev(
        "task_create",
        202,
        author_github="alice-gh",
        source="issue_body",
        created_at="2026-04-01T11:00:00Z",
        task_author_agent="alice@x",
        reward=10,
        reward_type="every_good",
        per_acceptance=5,
        min_agents=2,
    )
    assert proc.process(create) is True
    _assert_every_good_created(proc)
    if stop_after == "create":
        return proc

    bob_claim = _ev(
        "claim",
        202,
        agent="bob@y",
        author_github="bob-gh",
        created_at="2026-04-01T11:05:00Z",
    )
    carol_claim = _ev(
        "claim",
        202,
        agent="carol@z",
        author_github="carol-gh",
        created_at="2026-04-01T11:06:00Z",
        comment_id=101,
    )
    assert proc.process(bob_claim) is False
    assert proc.process(carol_claim) is False
    _assert_every_good_claims_rejected(proc)
    if stop_after == "claims_rejected":
        return proc

    first_accept = _ev(
        "accept",
        202,
        agent="bob@y",
        author_github="alice-gh",
        created_at="2026-04-01T11:20:00Z",
        comment_id=102,
    )
    assert proc.process(first_accept) is True
    _assert_every_good_first_payment(proc)
    if stop_after == "first_accept":
        return proc

    second_accept = _ev(
        "accept",
        202,
        agent="carol@z",
        author_github="alice-gh",
        created_at="2026-04-01T11:30:00Z",
        comment_id=103,
    )
    assert proc.process(second_accept) is True
    _assert_every_good_paid(proc)
    return proc


@pytest.mark.parametrize(
    "stop_after", ["escrow", "claim_rejected", "accept", "replay"], ids=str
)
def test_standard_task_lifecycle(stop_after: str) -> None:
    _run_standard_lifecycle(stop_after)


@pytest.mark.parametrize(
    "stop_after",
    ["create", "claims_rejected", "first_accept", "second_accept"],
    ids=str,
)
def test_every_good_task_lifecycle(stop_after: str) -> None:
    _run_every_good_lifecycle(stop_after)
