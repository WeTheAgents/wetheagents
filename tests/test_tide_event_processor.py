"""Focused tests for TideProcessor event dispatch and edge-case handling."""

from __future__ import annotations

from copy import deepcopy

from scripts.tide import TideProcessor
from scripts.tide_parser import TideEvent


def _agent(balance: int, github_username: str) -> dict:
    return {
        "balance": balance,
        "github_username": github_username,
        "total_earned": balance,
        "total_spent": 0,
        "tasks_completed": 0,
        "tasks_created": 0,
    }


def _balances() -> dict:
    return {
        "agents": {
            "alice@x": _agent(100, "alice-gh"),
            "bob@y": _agent(50, "bob-gh"),
            "carol@z": _agent(30, "carol-gh"),
        }
    }


def _escrows(**active) -> dict:
    return {"active": dict(active)}


def _idem(*keys: str) -> dict:
    return {"keys": {key: "2026-01-01T00:00:00Z" for key in keys}}


def _ev(type: str, issue: int = 1, agent: str | None = None, **kwargs) -> TideEvent:
    return TideEvent(
        type=type,
        issue=issue,
        created_at=kwargs.pop("created_at", "2026-03-05T12:00:00Z"),
        author_github=kwargs.pop("author_github", "alice-gh"),
        source=kwargs.pop("source", "comment"),
        comment_id=kwargs.pop("comment_id", 100),
        agent=agent,
        agents=kwargs.pop("agents", []),
        reason=kwargs.pop("reason", None),
        task_author_agent=kwargs.pop("task_author_agent", None),
        reward=kwargs.pop("reward", None),
        reward_type=kwargs.pop("reward_type", None),
        slots=kwargs.pop("slots", None),
        winners=kwargs.pop("winners", None),
        rounds=kwargs.pop("rounds", None),
        deadline=kwargs.pop("deadline", None),
        min_agents=kwargs.pop("min_agents", None),
        verification_criteria=kwargs.pop("verification_criteria", None),
    )


def _proc(
    *,
    balances: dict | None = None,
    escrows: dict | None = None,
    idem_keys: dict | None = None,
    task_index: dict | None = None,
) -> TideProcessor:
    return TideProcessor(
        balances=balances or _balances(),
        escrows=escrows or _escrows(),
        idem_keys=idem_keys or _idem(),
        task_index=task_index or {"version": 1, "tasks": {}},
    )


def _snapshot(proc: TideProcessor) -> tuple[dict, dict, dict, dict, list, list, int]:
    return (
        deepcopy(proc.balances),
        deepcopy(proc.escrows),
        deepcopy(proc.idem_keys),
        deepcopy(proc.task_index),
        deepcopy(proc.actions),
        deepcopy(proc.history),
        proc.count,
    )


class TestProcessDispatch:
    def test_process_dispatches_claim_and_counts_success(self, monkeypatch):
        proc = _proc()
        event = _ev("claim", agent="bob@y", author_github="bob-gh")
        seen = {}

        def fake_claim(ev: TideEvent) -> bool:
            seen["event"] = ev
            return True

        monkeypatch.setattr(proc, "_claim", fake_claim)

        assert proc.process(event) is True
        assert seen["event"] is event
        assert proc.count == 1

    def test_process_dispatches_accept_without_counting_failure(self, monkeypatch):
        proc = _proc()
        event = _ev("accept", agent="bob@y")
        seen = {}

        def fake_accept(ev: TideEvent) -> bool:
            seen["event"] = ev
            return False

        monkeypatch.setattr(proc, "_accept", fake_accept)

        assert proc.process(event) is False
        assert seen["event"] is event
        assert proc.count == 0

    def test_process_dispatches_reject_and_counts_success(self, monkeypatch):
        proc = _proc()
        event = _ev("reject", agent="bob@y", reason="missing tests")
        seen = {}

        def fake_reject(ev: TideEvent) -> bool:
            seen["event"] = ev
            return True

        monkeypatch.setattr(proc, "_reject", fake_reject)

        assert proc.process(event) is True
        assert seen["event"] is event
        assert proc.count == 1

    def test_process_rejects_manual_escrow_return_events(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )
        before = _snapshot(proc)

        assert proc.process(_ev("escrow_return", issue=1, agent="alice@x")) is False
        assert _snapshot(proc) == before


class TestClaimEventProcessing:
    def test_claim_without_active_escrow_returns_false(self):
        proc = _proc()
        before = _snapshot(proc)

        assert proc.process(_ev("claim", issue=99, agent="bob@y", author_github="bob-gh")) is False
        assert _snapshot(proc) == before

    def test_claim_unknown_agent_returns_false_without_side_effects(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )
        before = _snapshot(proc)

        assert proc.process(_ev("claim", issue=1, agent="unknown@nowhere", author_github="nobody")) is False
        assert _snapshot(proc) == before


class TestAcceptEventProcessing:
    def test_accept_missing_agent_returns_false_without_side_effects(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )
        before = _snapshot(proc)

        assert proc.process(_ev("accept", issue=1, agent=None, author_github="alice-gh")) is False
        assert _snapshot(proc) == before

    def test_accept_blocks_when_reward_exceeds_remaining_escrow(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 3,
                    "type": "every_good",
                    "per_acceptance": 5,
                    "paid_count": 0,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )

        assert proc.process(_ev("accept", issue=1, agent="bob@y", author_github="alice-gh")) is False
        assert proc.count == 0
        assert proc.balances["agents"]["bob@y"]["balance"] == 50
        assert proc.escrows["active"]["1"]["amount"] == 3
        assert proc.history == []
        assert any(action.body == "Insufficient escrow budget." for action in proc.actions)


class TestRejectEventProcessing:
    def test_reject_non_author_returns_false_without_side_effects(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )
        before = _snapshot(proc)

        assert proc.process(
            _ev("reject", issue=1, agent="bob@y", author_github="bob-gh", reason="nope")
        ) is False
        assert _snapshot(proc) == before

    def test_reject_defaults_reason_when_missing(self):
        proc = _proc(
            escrows=_escrows(**{
                "1": {
                    "author": "alice@x",
                    "amount": 20,
                    "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            })
        )

        assert proc.process(_ev("reject", issue=1, agent="bob@y", author_github="alice-gh")) is True
        assert proc.count == 1
        assert proc.history[0]["reason"] == "No reason given"
        assert any("Reason: No reason given." in action.body for action in proc.actions if action.body)
