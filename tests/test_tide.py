"""Tests for tide.py — batch event processing."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import tide
from scripts.tide import TideProcessor
from scripts.tide_parser import TideEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _balances(**overrides):
    base = {
        "agents": {
            "alice@x": {
                "balance": 100, "github_username": "alice-gh",
                "total_earned": 100, "total_spent": 0,
                "tasks_completed": 0, "tasks_created": 0,
            },
            "bob@y": {
                "balance": 50, "github_username": "bob-gh",
                "total_earned": 50, "total_spent": 0,
                "tasks_completed": 0, "tasks_created": 0,
            },
            "carol@z": {
                "balance": 30, "github_username": "carol-gh",
                "total_earned": 30, "total_spent": 0,
                "tasks_completed": 0, "tasks_created": 0,
            },
        }
    }
    base.update(overrides)
    return base


def _escrows(**active):
    return {"active": dict(active)}


def _idem(*keys):
    return {"keys": {k: "2026-01-01T00:00:00Z" for k in keys}}


def _ev(type, issue=1, agent=None, agents=None, **kw):
    return TideEvent(
        type=type, issue=issue,
        created_at=kw.pop("created_at", "2026-03-05T12:00:00Z"),
        author_github=kw.pop("author_github", "alice-gh"),
        source=kw.pop("source", "comment"),
        comment_id=kw.pop("comment_id", 100),
        agent=agent,
        agents=agents or [],
        reason=kw.pop("reason", None),
        task_author_agent=kw.pop("task_author_agent", None),
        reward=kw.pop("reward", None),
        per_acceptance=kw.pop("per_acceptance", None),
        reward_type=kw.pop("reward_type", None),
        slots=kw.pop("slots", None),
        winners=kw.pop("winners", None),
        rounds=kw.pop("rounds", None),
        deadline=kw.pop("deadline", None),
        min_agents=kw.pop("min_agents", None),
        verification_criteria=kw.pop("verification_criteria", None),
    )


def _proc(balances=None, escrows=None, idem_keys=None, task_index=None):
    return TideProcessor(
        balances=balances or _balances(),
        escrows=escrows or _escrows(),
        idem_keys=idem_keys or _idem(),
        task_index=task_index or {"version": 1, "tasks": {}},
    )


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

class TestTaskCreate:
    def test_creates_escrow_and_deducts(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=30, reward_type="best_x",
                 winners=1, source="issue_body")
        assert p.process(ev)
        assert p.balances["agents"]["alice@x"]["balance"] == 70
        assert "10" in p.escrows["active"]
        assert p.escrows["active"]["10"]["amount"] == 30

    def test_progressive_validates_budget(self):
        p = _proc()
        # 3 slots: sum(fib(1..3)) = 1+1+2 = 4 = fib(5)-1
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=99, reward_type="progressive",
                 slots=3, source="issue_body")
        assert not p.process(ev)
        # Correct budget
        ev2 = _ev("task_create", issue=10, author_github="alice-gh",
                  task_author_agent="alice@x", reward=4, reward_type="progressive",
                  slots=3, source="issue_body")
        assert p.process(ev2)

    def test_insufficient_balance(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="bob-gh",
                 task_author_agent="bob@y", reward=999, reward_type="best_x",
                 winners=1, source="issue_body")
        assert not p.process(ev)
        assert p.balances["agents"]["bob@y"]["balance"] == 50  # unchanged

    def test_unregistered_agent(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="nobody",
                 task_author_agent="nobody@z", reward=10, reward_type="best_x",
                 winners=1, source="issue_body")
        assert not p.process(ev)

    def test_idem_prevents_duplicate(self):
        p = _proc(idem_keys=_idem("escrow|10|alice@x"))
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=10, reward_type="best_x",
                 winners=1, source="issue_body")
        assert not p.process(ev)

    def test_duel_escrow_has_rounds(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=20, reward_type="duel",
                 rounds=3, source="issue_body")
        assert p.process(ev)
        assert p.escrows["active"]["10"]["rounds"] == 3

    def test_every_good_uses_parsed_per_acceptance(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=15, reward_type="every_good",
                 per_acceptance=5, source="issue_body")
        assert p.process(ev)
        escrow = p.escrows["active"]["10"]
        assert escrow["amount"] == 15
        assert escrow["per_acceptance"] == 5

    def test_every_good_defaults_per_acceptance_to_reward(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=15, reward_type="every_good",
                 source="issue_body")
        assert p.process(ev)
        assert p.escrows["active"]["10"]["per_acceptance"] == 15

    def test_every_good_rejects_over_budget_per_acceptance(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=15, reward_type="every_good",
                 per_acceptance=20, source="issue_body")
        assert not p.process(ev)
        assert "10" not in p.escrows["active"]

    def test_every_good_rejects_non_divisible_per_acceptance(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=10, reward_type="every_good",
                 per_acceptance=6, source="issue_body")
        assert not p.process(ev)
        assert "10" not in p.escrows["active"]


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class TestClaim:
    def _setup_task(self):
        return _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 30, "type": "best_x",
                  "winners": 1, "created_at": "2026-01-01T00:00:00Z"},
        }))

    def test_regular_claim(self):
        p = self._setup_task()
        ev = _ev("claim", issue=1, agent="bob@y", author_github="bob-gh")
        assert p.process(ev)
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("remove_label", "open") in labels
        assert ("add_label", "claimed") in labels

    def test_self_claim_prevention(self):
        p = self._setup_task()
        ev = _ev("claim", issue=1, agent="alice@x", author_github="alice-gh")
        assert not p.process(ev)

    def test_duplicate_claim(self):
        p = self._setup_task()
        ev = _ev("claim", issue=1, agent="bob@y", author_github="bob-gh")
        assert p.process(ev)
        assert not p.process(ev)  # idem prevents second claim


class TestDuelClaim:
    def _setup_duel(self):
        return _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "duel",
                  "rounds": 3, "created_at": "2026-01-01T00:00:00Z"},
        }))

    def test_first_claim(self):
        p = self._setup_duel()
        ev = _ev("claim", issue=1, agent="bob@y", author_github="bob-gh")
        assert p.process(ev)
        assert p.escrows["active"]["1"]["participants"] == ["bob@y"]

    def test_second_claim_assigns_roles(self):
        p = self._setup_duel()
        p.process(_ev("claim", issue=1, agent="bob@y", author_github="bob-gh"))
        ev2 = _ev("claim", issue=1, agent="carol@z", author_github="carol-gh")
        assert p.process(ev2)
        escrow = p.escrows["active"]["1"]
        assert "pro" in escrow
        assert "con" in escrow
        assert escrow["turn_count"] == 0
        assert set(escrow["participants"]) == {"bob@y", "carol@z"}

    def test_duel_full(self):
        p = self._setup_duel()
        p.process(_ev("claim", issue=1, agent="bob@y", author_github="bob-gh"))
        p.process(_ev("claim", issue=1, agent="carol@z", author_github="carol-gh"))
        # Third claim should fail
        b = _balances()
        b["agents"]["dave@w"] = {
            "balance": 10, "github_username": "dave-gh",
            "total_earned": 10, "total_spent": 0,
            "tasks_completed": 0, "tasks_created": 0,
        }
        p.balances = b
        p._gh_map = {"alice-gh": "alice@x", "bob-gh": "bob@y",
                     "carol-gh": "carol@z", "dave-gh": "dave@w"}
        ev = _ev("claim", issue=1, agent="dave@w", author_github="dave-gh")
        assert not p.process(ev)


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------

class TestAccept:
    def test_every_good_payment(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 15, "type": "every_good",
                  "per_acceptance": 15, "paid_count": 0,
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.balances["agents"]["bob@y"]["balance"] == 65
        assert "1" not in p.escrows["active"]  # exhausted

    def test_every_good_multiple_agents_paid_from_one_escrow(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 10, "type": "every_good",
                  "per_acceptance": 5, "paid_count": 0,
                  "created_at": "2026-01-01T00:00:00Z"},
        }))

        ev1 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev1)
        assert p.balances["agents"]["bob@y"]["balance"] == 55
        assert p.escrows["active"]["1"]["amount"] == 5

        ev2 = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh",
                  comment_id=101)
        assert p.process(ev2)
        assert p.balances["agents"]["carol@z"]["balance"] == 35
        assert "1" not in p.escrows["active"]

    def test_progressive_fibonacci(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 7, "type": "progressive",
                  "slots": 3, "paid_count": 0,
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        # Slot 1: fib(1) = 1
        ev1 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh",
                  created_at="2026-03-05T12:00:00Z")
        assert p.process(ev1)
        assert p.balances["agents"]["bob@y"]["balance"] == 51

        # Slot 2: fib(2) = 1
        ev2 = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh",
                  created_at="2026-03-05T12:01:00Z")
        assert p.process(ev2)
        assert p.balances["agents"]["carol@z"]["balance"] == 31

        # Slot 3: fib(3) = 2
        ev3 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh",
                  created_at="2026-03-05T12:02:00Z")
        assert p.process(ev3)
        assert p.balances["agents"]["bob@y"]["balance"] == 53
        assert "1" not in p.escrows["active"]  # all slots filled

    def test_linear_progression(self):
        # 3 slots: budget = 3*4/2 = 6
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 6, "type": "linear",
                  "slots": 3, "paid_count": 0,
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        # Slot 1: 1 WEA
        ev1 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh",
                  created_at="2026-03-05T12:00:00Z")
        assert p.process(ev1)
        assert p.balances["agents"]["bob@y"]["balance"] == 51

        # Slot 2: 2 WEA
        ev2 = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh",
                  created_at="2026-03-05T12:01:00Z")
        assert p.process(ev2)
        assert p.balances["agents"]["carol@z"]["balance"] == 32

        # Slot 3: 3 WEA
        ev3 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh",
                  created_at="2026-03-05T12:02:00Z")
        assert p.process(ev3)
        assert p.balances["agents"]["bob@y"]["balance"] == 54
        assert "1" not in p.escrows["active"]  # all slots filled

    def test_standard_full_payment(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard",
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.balances["agents"]["bob@y"]["balance"] == 70

    def test_authorization_check(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard",
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        # bob tries to accept on alice's task
        ev = _ev("accept", issue=1, agent="carol@z", author_github="bob-gh")
        assert not p.process(ev)

    def test_rejects_best_x(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "best_x",
                  "winners": 1, "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert not p.process(ev)
        assert any("winner:" in a.body for a in p.actions if a.body)

    def test_idem_prevents_duplicate(self):
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            idem_keys=_idem("payment|1|bob@y"),
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert not p.process(ev)


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

class TestReject:
    def test_reject_reopens(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard",
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("reject", issue=1, agent="bob@y", author_github="alice-gh",
                 reason="incomplete work")
        assert p.process(ev)
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("remove_label", "claimed") in labels
        assert ("add_label", "open") in labels
        assert p.balances["agents"]["bob@y"]["balance"] == 50  # unchanged


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

class TestRanking:
    def test_single_winner(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 30, "type": "best_x",
                  "winners": 1, "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("ranking", issue=1, agents=["bob@y"], author_github="alice-gh")
        assert p.process(ev)
        assert p.balances["agents"]["bob@y"]["balance"] == 80  # +30
        assert "1" not in p.escrows["active"]

    def test_three_ranked(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 100, "type": "best_x",
                  "winners": 3, "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("ranking", issue=1,
                 agents=["bob@y", "carol@z", "alice@x"],
                 author_github="alice-gh")
        assert p.process(ev)
        # Split: 50/30/20
        assert p.balances["agents"]["bob@y"]["balance"] == 100   # 50+50
        assert p.balances["agents"]["carol@z"]["balance"] == 60  # 30+30
        assert p.balances["agents"]["alice@x"]["balance"] == 120 # 100+20

    def test_birdie_rule(self):
        """K=2 with X=3: rank2 gets 30% (X=3 table), rank1 gets remainder."""
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 100, "type": "best_x",
                  "winners": 3, "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("ranking", issue=1, agents=["bob@y", "carol@z"],
                 author_github="alice-gh")
        assert p.process(ev)
        # rank2: floor(100*30/100)=30, rank1: 100-30=70
        assert p.balances["agents"]["carol@z"]["balance"] == 60  # 30+30
        assert p.balances["agents"]["bob@y"]["balance"] == 120   # 50+70

    def test_too_many_agents(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 100, "type": "best_x",
                  "winners": 1, "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("ranking", issue=1, agents=["bob@y", "carol@z"],
                 author_github="alice-gh")
        assert not p.process(ev)


# ---------------------------------------------------------------------------
# Duel lifecycle
# ---------------------------------------------------------------------------

class TestDuelLifecycle:
    def _setup_active_duel(self):
        """Create processor with a fully set up duel (both claimed, roles assigned)."""
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "duel",
                  "rounds": 2, "created_at": "2026-01-01T00:00:00Z",
                  "participants": ["bob@y", "carol@z"],
                  "pro": "bob@y", "con": "carol@z", "turn_count": 0},
        }))
        return p

    def test_turn_order(self):
        p = self._setup_active_duel()
        # PRO (bob) goes first — turn 0 is even → pro
        ev_bob = _ev("duel_submission", issue=1, author_github="bob-gh")
        assert p.process(ev_bob)
        assert p.escrows["active"]["1"]["turn_count"] == 1

        # CON (carol) goes second
        ev_carol = _ev("duel_submission", issue=1, author_github="carol-gh")
        assert p.process(ev_carol)
        assert p.escrows["active"]["1"]["turn_count"] == 2

    def test_wrong_turn_gets_warning(self):
        p = self._setup_active_duel()
        # Carol tries to go first (should be bob)
        ev = _ev("duel_submission", issue=1, author_github="carol-gh")
        assert p.process(ev)  # returns True (we responded)
        assert p.escrows["active"]["1"]["turn_count"] == 0  # not incremented
        assert any("Not your turn" in a.body for a in p.actions if a.body)

    def test_all_rounds_complete(self):
        p = self._setup_active_duel()  # 2 rounds = 4 turns
        agents = ["bob-gh", "carol-gh"]
        for i in range(4):
            ev = _ev("duel_submission", issue=1, author_github=agents[i % 2])
            p.process(ev)
        assert p.escrows["active"]["1"]["turn_count"] == 4
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("add_label", "duel-judging") in labels

    def test_winner_90_10_split(self):
        p = self._setup_active_duel()
        ev = _ev("duel_winner", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        # 90/10 of 20: winner=18, loser=2
        assert p.balances["agents"]["bob@y"]["balance"] == 68   # 50+18
        assert p.balances["agents"]["carol@z"]["balance"] == 32 # 30+2
        assert "1" not in p.escrows["active"]

    def test_winner_90_10_split_odd_budget_rounds_down_winner(self):
        p = self._setup_active_duel()
        p.escrows["active"]["1"]["amount"] = 33
        ev = _ev("duel_winner", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.balances["agents"]["bob@y"]["balance"] == 79   # 50+29
        assert p.balances["agents"]["carol@z"]["balance"] == 34 # 30+4
        assert "1" not in p.escrows["active"]

    def test_winner_must_be_participant(self):
        p = self._setup_active_duel()
        ev = _ev("duel_winner", issue=1, agent="alice@x", author_github="alice-gh")
        assert not p.process(ev)


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_empty_batch(self):
        p = _proc()
        assert p.count == 0
        assert p.actions == []
        assert p.history == []

    def test_fifo_ordering(self):
        """Events processed in chronological order — claim before accept."""
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard",
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        # Claim first, then accept
        ev_claim = _ev("claim", issue=1, agent="bob@y",
                       author_github="bob-gh",
                       created_at="2026-03-05T12:00:00Z")
        ev_accept = _ev("accept", issue=1, agent="bob@y",
                        author_github="alice-gh",
                        created_at="2026-03-05T12:01:00Z")
        # Sort by created_at (mimicking build_events)
        events = sorted([ev_accept, ev_claim], key=lambda e: e.created_at)
        for ev in events:
            p.process(ev)
        assert p.count == 2
        assert p.balances["agents"]["bob@y"]["balance"] == 70

    def test_count_tracks_processed(self):
        p = _proc(escrows=_escrows(**{
            "1": {"author": "alice@x", "amount": 20, "type": "standard",
                  "created_at": "2026-01-01T00:00:00Z"},
        }))
        p.process(_ev("claim", issue=1, agent="bob@y", author_github="bob-gh"))
        p.process(_ev("accept", issue=1, agent="bob@y", author_github="alice-gh"))
        assert p.count == 2

    def test_unknown_event_type(self):
        p = _proc()
        ev = _ev("unknown_type", issue=1)
        assert not p.process(ev)


class TestCircuitBreaker:
    def test_lightweight_invariant_detects_negative_balance(self):
        balances = _balances()
        balances["agents"]["bob@y"]["balance"] = -1
        failure = tide._lightweight_invariant_failure(
            balances,
            _escrows(),
            expected_total=129,
        )
        assert failure is not None
        assert "negative balance" in failure

    def test_run_halts_without_writing_ledger_on_mid_batch_anomaly(self, temp_repo, monkeypatch):
        ledger = temp_repo / "ledger"
        original_balances = (ledger / "balances.json").read_text(encoding="utf-8")
        original_escrows = (ledger / "escrows.json").read_text(encoding="utf-8")
        original_idem = (ledger / "idem_keys.json").read_text(encoding="utf-8")

        monkeypatch.setattr(tide, "_detect_repo", lambda root: "WeTheAgents/wetheagents")
        monkeypatch.setattr(tide, "fetch_task_issues", lambda repo, since: [])
        monkeypatch.setattr(tide, "fetch_comments", lambda repo, since: [])
        monkeypatch.setattr(
            tide,
            "build_events",
            lambda issues, comments, idem_keys, task_issue_numbers: [
                TideEvent(
                    type="accept",
                    issue=999,
                    created_at="2026-03-06T10:00:00Z",
                    author_github="author",
                    source="comment",
                    comment_id=1,
                    agent="alice@test",
                )
            ],
        )

        original_process = tide.TideProcessor.process

        def bad_process(self, event):
            self.balances["agents"]["alice@test"]["balance"] = -5
            self.count += 1
            return True

        monkeypatch.setattr(tide.TideProcessor, "process", bad_process)
        try:
            result = tide.run(temp_repo, strict=True)
        finally:
            monkeypatch.setattr(tide.TideProcessor, "process", original_process)

        assert result == 1
        assert (ledger / "balances.json").read_text(encoding="utf-8") == original_balances
        assert (ledger / "escrows.json").read_text(encoding="utf-8") == original_escrows
        assert (ledger / "idem_keys.json").read_text(encoding="utf-8") == original_idem

        tide_state = json.loads((ledger / "tide.json").read_text(encoding="utf-8"))
        assert tide_state["halted_at"]
        assert "negative balance" in tide_state["halt_reason"]
        assert tide_state["halt_event"]["issue"] == 999


# ---------------------------------------------------------------------------
# Min-agents enforcement
# ---------------------------------------------------------------------------

class TestMinAgents:
    def test_task_create_stores_min_agents(self):
        p = _proc()
        ev = _ev("task_create", issue=10, author_github="alice-gh",
                 task_author_agent="alice@x", reward=20, reward_type="standard",
                 source="issue_body", min_agents=2)
        assert p.process(ev)
        task = p.task_index["tasks"]["10"]
        assert task["min_agents"] == 2
        assert task["accepted_agents"] == []

    def test_accept_blocks_close_until_min_agents_met(self):
        """With min_agents=2, first accept pays but keeps task open."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 40, "type": "every_good",
                      "per_acceptance": 20, "paid_count": 0,
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"min_agents": 2, "accepted_agents": [],
                      "author": "alice@x", "mechanic": "every_good", "status": "open"},
            }},
        )
        # First accept: pays bob but task stays open
        ev1 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev1)
        assert p.balances["agents"]["bob@y"]["balance"] == 70  # 50 + 20
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("add_label", "open") in labels
        assert ("add_label", "paid") not in labels
        # Check warning in comment
        assert any("1/2 agents" in a.body for a in p.actions if a.body)

    def test_accept_closes_when_min_agents_met(self):
        """With min_agents=2, second accept from different agent allows close."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "every_good",
                      "per_acceptance": 20, "paid_count": 0,
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"min_agents": 2, "accepted_agents": ["bob@y"],
                      "author": "alice@x", "mechanic": "every_good", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh")
        assert p.process(ev)
        assert p.balances["agents"]["carol@z"]["balance"] == 50  # 30 + 20
        labels = [(a.action, a.label) for a in p.actions if a.label]
        # Escrow depleted + min_agents met → paid
        assert ("add_label", "paid") in labels

    def test_escrow_survives_until_min_agents_met(self):
        """Escrow must not be deleted while min_agents threshold unmet,
        otherwise second accept is impossible (codex P1 fix)."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 40, "type": "every_good",
                      "per_acceptance": 20, "paid_count": 0,
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"min_agents": 2, "accepted_agents": [],
                      "author": "alice@x", "mechanic": "every_good", "status": "open"},
            }},
        )
        # First accept: pays bob 20, escrow has 20 left, but only 1/2 agents
        ev1 = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev1)
        assert "1" in p.escrows["active"]  # escrow survives
        # Second accept: pays carol 20, now 2/2 agents met
        ev2 = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh",
                  comment_id=101)
        assert p.process(ev2)
        assert "1" not in p.escrows["active"]  # NOW escrow cleaned up
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("add_label", "paid") in labels

    def test_no_min_agents_standard_closes_normally(self):
        """Without min_agents, standard task closes on first accept as usual."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"author": "alice@x", "mechanic": "standard", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        labels = [(a.action, a.label) for a in p.actions if a.label]
        assert ("add_label", "paid") in labels


# ---------------------------------------------------------------------------
# Bug #168 — task_index status update on payout
# ---------------------------------------------------------------------------

class TestTaskIndexStatusOnPayout:
    """task_index status must be set to 'paid' whenever _add_label(ev.issue, 'paid')."""

    def test_accept_escrow_depleted_sets_paid(self):
        """accept + escrow depleted -> status='paid'."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"author": "alice@x", "mechanic": "standard", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "paid"

    def test_accept_min_agents_pending_stays_open(self):
        """accept + min_agents pending -> status stays 'open'."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 40, "type": "every_good",
                      "per_acceptance": 20, "paid_count": 0,
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"min_agents": 2, "accepted_agents": [],
                      "author": "alice@x", "mechanic": "every_good", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "open"

    def test_accept_min_agents_met_on_final_sets_paid(self):
        """accept + min_agents met on final accept -> status='paid'."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "every_good",
                      "per_acceptance": 20, "paid_count": 0,
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"min_agents": 2, "accepted_agents": ["bob@y"],
                      "author": "alice@x", "mechanic": "every_good", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="carol@z", author_github="alice-gh")
        assert p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "paid"

    def test_missing_task_index_entry_no_crash(self):
        """Missing task_index entry -> no crash, no new entry created."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {}},  # no entry for issue 1
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        # Must not crash and must not create synthetic entry
        assert "1" not in p.task_index["tasks"]

    def test_ranking_sets_paid(self):
        """ranking -> status='paid'."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 30, "type": "best_x",
                      "winners": 1, "created_at": "2026-01-01T00:00:00Z"},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"author": "alice@x", "mechanic": "best_x", "status": "open"},
            }},
        )
        ev = _ev("ranking", issue=1, agents=["bob@y"], author_github="alice-gh")
        assert p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "paid"

    def test_duel_winner_sets_paid(self):
        """duel_winner -> status='paid'."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "duel",
                      "rounds": 2, "created_at": "2026-01-01T00:00:00Z",
                      "participants": ["bob@y", "carol@z"],
                      "pro": "bob@y", "con": "carol@z", "turn_count": 0},
            }),
            task_index={"version": 1, "tasks": {
                "1": {"author": "alice@x", "mechanic": "duel", "status": "open"},
            }},
        )
        ev = _ev("duel_winner", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "paid"

    def test_idem_replay_status_unchanged(self):
        """idem replay -> status unchanged (stays 'open')."""
        p = _proc(
            escrows=_escrows(**{
                "1": {"author": "alice@x", "amount": 20, "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }),
            idem_keys=_idem("payment|1|bob@y"),  # already processed
            task_index={"version": 1, "tasks": {
                "1": {"author": "alice@x", "mechanic": "standard", "status": "open"},
            }},
        )
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert not p.process(ev)
        assert p.task_index["tasks"]["1"]["status"] == "open"


# ---------------------------------------------------------------------------
# Bug #159 — Repo name fallback
# ---------------------------------------------------------------------------

class TestDetectRepoFallback:
    """_detect_repo must fall back to 'WeTheAgents/wetheagents'."""

    def test_file_not_found_fallback(self, monkeypatch):
        """FileNotFoundError -> 'WeTheAgents/wetheagents'."""
        def _raise_fnf(*a, **kw):
            raise FileNotFoundError("gh not found")
        monkeypatch.setattr(tide.subprocess, "run", _raise_fnf)
        result = tide._detect_repo(Path("."))
        assert result == "WeTheAgents/wetheagents"

    def test_called_process_error_fallback(self, monkeypatch):
        """CalledProcessError -> 'WeTheAgents/wetheagents'."""
        def _raise_cpe(*a, **kw):
            raise tide.subprocess.CalledProcessError(1, "gh")
        monkeypatch.setattr(tide.subprocess, "run", _raise_cpe)
        result = tide._detect_repo(Path("."))
        assert result == "WeTheAgents/wetheagents"

    def test_empty_stdout_fallback(self, monkeypatch):
        """Empty stdout -> 'WeTheAgents/wetheagents'."""
        class FakeResult:
            stdout = ""
            returncode = 0
        monkeypatch.setattr(tide.subprocess, "run", lambda *a, **kw: FakeResult())
        result = tide._detect_repo(Path("."))
        assert result == "WeTheAgents/wetheagents"


# ---------------------------------------------------------------------------
# Verification tests
# ---------------------------------------------------------------------------


class TestVerify:
    """Tests for the verify command handler."""

    def _setup_task_with_criteria(self):
        """Create a processor with a task that has verification criteria."""
        escrows = _escrows(**{"1": {
            "author": "alice@x", "amount": 20, "type": "standard",
            "created_at": "2026-03-05T12:00:00Z",
        }})
        task_index = {"version": 1, "tasks": {
            "1": {
                "title": "Test task", "author": "alice@x",
                "verification_criteria": ["tests pass", "endpoint works"],
                "status": "open", "reward": 20, "mechanic": "standard",
            }
        }}
        return _proc(escrows=escrows, task_index=task_index)

    def test_verify_happy_path(self):
        p = self._setup_task_with_criteria()
        ev = _ev("verify", issue=1, agent="bob@y",
                 author_github="alice-gh", reason="tests pass, endpoint verified")
        assert p.process(ev) is True
        assert "bob@y" in p.escrows["active"]["1"]["verified_agents"]
        assert len(p.history) == 1
        assert p.history[0]["type"] == "verification"
        assert p.history[0]["evidence"] == "tests pass, endpoint verified"

    def test_verify_idempotent(self):
        p = self._setup_task_with_criteria()
        ev = _ev("verify", issue=1, agent="bob@y",
                 author_github="alice-gh", reason="evidence")
        assert p.process(ev) is True
        assert p.process(ev) is False  # second time fails (idem)
        assert len(p.escrows["active"]["1"]["verified_agents"]) == 1

    def test_verify_non_author_rejected(self):
        """Only the task author can verify."""
        p = self._setup_task_with_criteria()
        ev = _ev("verify", issue=1, agent="carol@z",
                 author_github="bob-gh", reason="evidence")  # bob is not the author
        assert p.process(ev) is False

    def test_verify_unknown_agent_fails(self):
        p = self._setup_task_with_criteria()
        ev = _ev("verify", issue=1, agent="unknown@nowhere",
                 author_github="alice-gh", reason="evidence")
        assert p.process(ev) is False

    def test_verify_no_escrow_fails(self):
        p = _proc()
        ev = _ev("verify", issue=99, agent="bob@y",
                 author_github="alice-gh", reason="evidence")
        assert p.process(ev) is False


class TestVerificationGate:
    """Tests for the verification gate on accept/ranking/duel."""

    def _setup_with_criteria(self, mechanic="standard", **escrow_extra):
        base_escrow = {
            "author": "alice@x", "amount": 20, "type": mechanic,
            "created_at": "2026-03-05T12:00:00Z",
        }
        base_escrow.update(escrow_extra)
        escrows = _escrows(**{"1": base_escrow})
        task_index = {"version": 1, "tasks": {
            "1": {
                "title": "Test", "author": "alice@x",
                "verification_criteria": ["tests pass"],
                "status": "open", "reward": 20, "mechanic": mechanic,
            }
        }}
        return _proc(escrows=escrows, task_index=task_index)

    def test_accept_blocked_without_verification(self):
        p = self._setup_with_criteria()
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev) is False
        # No payment made
        assert p.balances["agents"]["bob@y"]["balance"] == 50

    def test_accept_after_verification(self):
        p = self._setup_with_criteria()
        # First verify
        verify_ev = _ev("verify", issue=1, agent="bob@y",
                        author_github="alice-gh", reason="all checks pass")
        assert p.process(verify_ev) is True
        # Then accept
        accept_ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(accept_ev) is True
        assert p.balances["agents"]["bob@y"]["balance"] == 70  # 50 + 20

    def test_accept_legacy_no_criteria(self):
        """Tasks without verification criteria skip the gate."""
        escrows = _escrows(**{"1": {
            "author": "alice@x", "amount": 20, "type": "standard",
            "created_at": "2026-03-05T12:00:00Z",
        }})
        task_index = {"version": 1, "tasks": {
            "1": {"title": "Legacy", "author": "alice@x",
                  "status": "open", "reward": 20, "mechanic": "standard"}
        }}
        p = _proc(escrows=escrows, task_index=task_index)
        ev = _ev("accept", issue=1, agent="bob@y", author_github="alice-gh")
        assert p.process(ev) is True  # no gate
        assert p.balances["agents"]["bob@y"]["balance"] == 70

    def test_ranking_blocked_without_verification(self):
        p = self._setup_with_criteria(mechanic="best_x", winners=2)
        ev = _ev("ranking", issue=1, agents=["bob@y", "carol@z"],
                 author_github="alice-gh")
        assert p.process(ev) is False

    def test_ranking_after_verification(self):
        p = self._setup_with_criteria(mechanic="best_x", winners=2)
        # Verify both agents
        p.process(_ev("verify", issue=1, agent="bob@y",
                       author_github="alice-gh", reason="ok"))
        p.process(_ev("verify", issue=1, agent="carol@z",
                       author_github="alice-gh", reason="ok"))
        # Now rank
        ev = _ev("ranking", issue=1, agents=["bob@y", "carol@z"],
                 author_github="alice-gh")
        assert p.process(ev) is True


class TestTaskCreateWithCriteria:
    """Test that verification criteria are stored at task creation."""

    def test_criteria_stored_in_task_index(self):
        p = _proc()
        ev = _ev("task_create", issue=42,
                 task_author_agent="alice@x", reward=20, reward_type="best_x",
                 winners=1, author_github="alice-gh",
                 verification_criteria=["tests pass", "manual check"])
        assert p.process(ev) is True
        task = p.task_index["tasks"]["42"]
        assert task["verification_criteria"] == ["tests pass", "manual check"]

    def test_no_criteria_field_when_absent(self):
        p = _proc()
        ev = _ev("task_create", issue=42,
                 task_author_agent="alice@x", reward=20, reward_type="best_x",
                 winners=1, author_github="alice-gh")
        assert p.process(ev) is True
        task = p.task_index["tasks"]["42"]
        assert "verification_criteria" not in task
