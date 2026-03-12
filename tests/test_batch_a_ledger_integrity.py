"""Tests for Batch A: Ledger Integrity Reconciliation.

Tests reconcile_batch_a.py (6-phase reconciliation) and
the tide.py _pay() fix (tasks_completed dedup).
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_history(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


ALIAS_MAP = {
    "CursorWea@cursor": "cursor-3@cursor",
    "Cursor-1@cursor": "cursor-3@cursor",
    "AntigravityWea@Google": "Antigravity-1@Google",
}

RESET_BOUNDARY = "2026-03-07T12:00:00Z"


# ---------------------------------------------------------------------------
# Fixture: minimal ledger for reconciliation tests
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger_dir(tmp_path):
    """Create a minimal ledger directory with test data."""
    ld = tmp_path / "ledger"
    ld.mkdir()
    (ld / "history").mkdir()

    # balances: agent0 has 9900, cursor-3 has 80, Codex-2 has 20
    # (intentionally wrong counters to test reconciliation)
    _write_json(ld / "balances.json", {
        "version": 3,
        "last_updated": "2026-03-09T00:00:00Z",
        "agents": {
            "agent0@system": {
                "balance": 9880,
                "registered_at": "2026-03-02T00:00:00Z",
                "platform": "github-actions",
                "operator": "wetheagents",
                "github_username": "peachgabba22",
                "total_earned": 999,  # wrong, should be 10000
                "total_spent": 999,   # wrong, should be recomputed
                "tasks_completed": 5,  # wrong, should be 0
                "tasks_created": 10,
            },
            "cursor-3@cursor": {
                "balance": 20,
                "registered_at": "2026-03-03T11:24:22Z",
                "platform": "Cursor",
                "operator": "peach",
                "github_username": "CursorWEA",
                "total_earned": 999,  # wrong
                "total_spent": 999,   # wrong
                "tasks_completed": 99, # wrong
                "tasks_created": 3,
            },
            "Codex-2@codex": {
                "balance": 20,
                "registered_at": "2026-03-07T12:00:00Z",
                "platform": "codex",
                "operator": "peach",
                "github_username": "peachgabba22",
                "total_earned": 999,  # wrong
                "total_spent": 999,   # wrong
                "tasks_completed": 99, # wrong
                "tasks_created": 0,
            },
            "Claude-1@claude": {
                "balance": 0,
                "registered_at": "2026-03-07T12:00:00Z",
                "platform": "claude-code",
                "operator": "peach",
                "github_username": "peachgabba22",
                "total_earned": 0,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
            },
            "Antigravity-1@Google": {
                "balance": 0,
                "registered_at": "2026-03-03T16:46:59Z",
                "platform": "Gemini",
                "operator": "Antigravity",
                "github_username": "AntigravityWea",
                "total_earned": 999,
                "total_spent": 999,
                "tasks_completed": 99,
                "tasks_created": 0,
            },
        },
    })

    # escrows: issue 50 is closed (orphan), issue 100 is open
    _write_json(ld / "escrows.json", {
        "version": 1,
        "active": {
            "50": {
                "author": "agent0@system",
                "amount": 20,
                "type": "best_x",
                "created_at": "2026-03-08T00:00:00Z",
                "winners": 1,
            },
            "100": {
                "author": "agent0@system",
                "amount": 60,
                "type": "best_x",
                "created_at": "2026-03-09T00:00:00Z",
                "winners": 1,
            },
        },
    })

    # idem_keys: includes non-canonical names and removed agents
    _write_json(ld / "idem_keys.json", {
        "keys": {
            # Non-canonical aliases (should be cleaned)
            "payment|7|CursorWea@cursor": "2026-03-03T16:00:00Z",
            "payment|4|CursorWea@cursor": "2026-03-03T16:00:00Z",
            "payment|21|AntigravityWea@Google": "2026-03-04T00:00:00Z",
            # Canonical versions (should remain)
            "payment|7|cursor-3@cursor": "2026-03-03T16:00:00Z",
            "payment|4|cursor-3@cursor": "2026-03-03T16:00:00Z",
            "payment|21|Antigravity-1@Google": "2026-03-04T00:00:00Z",
            # Removed agents (should be cleaned)
            "provisional_join|khattab-crow": "2026-03-04T12:00:00Z",
            "payment|32|khattab-crow@unknown|proposal1": "2026-03-04T12:00:00Z",
            "payment|32|khattab-crow@unknown|proposal2": "2026-03-04T12:00:00Z",
            "reg-confirm|khattab-crow@openclaw": "2026-03-05T06:00:00Z",
            "hello_world|khattab-crow@openclaw": "2026-03-05T06:00:00Z",
            # Post-reset canonical keys (should remain)
            "escrow|107|agent0@system": "2026-03-08T10:59:23Z",
            "payment|109|Codex-2@codex|ranking|1": "2026-03-09T06:05:36Z",
            "payment|70|cursor-3@cursor|ranking|1": "2026-03-09T07:18:39Z",
            "payment|71|cursor-3@cursor|ranking|1": "2026-03-09T07:18:39Z",
            # Cursor-1 canonical counterpart exists (should be cleaned)
            "payment|70|Cursor-1@cursor|ranking|1": "2026-03-09T06:31:16Z",
        },
    })

    # Post-reset history: entries at or after 2026-03-07T12:00:00Z
    _write_history(ld / "history" / "2026-03-07.jsonl", [
        {"type": "economy_reset", "timestamp": "2026-03-07T12:00:02Z",
         "agents_zeroed": ["CursorWea@cursor", "AntigravityWea@Google"],
         "wea_returned_to_agent0": 487},
        {"type": "agent_registration", "agent": "Codex-2@codex",
         "timestamp": "2026-03-07T12:00:03Z"},
        {"type": "agent_registration", "agent": "Claude-1@claude",
         "timestamp": "2026-03-07T12:00:04Z"},
    ])

    _write_history(ld / "history" / "2026-03-08.jsonl", [
        {"type": "escrow", "issue": 107, "agent": "agent0@system",
         "amount": 5, "timestamp": "2026-03-08T10:59:23Z"},
        {"type": "escrow", "issue": 100, "agent": "agent0@system",
         "amount": 60, "timestamp": "2026-03-08T11:00:00Z"},
    ])

    _write_history(ld / "history" / "2026-03-09.jsonl", [
        {"type": "escrow", "issue": 50, "agent": "agent0@system",
         "amount": 20, "timestamp": "2026-03-09T00:00:00Z"},
        {"type": "payment", "subtype": "ranking", "issue": 109,
         "agent": "Codex-2@codex", "amount": 20,
         "timestamp": "2026-03-09T06:05:36Z", "rank": 1},
        {"type": "escrow", "issue": 70, "agent": "agent0@system",
         "amount": 10, "timestamp": "2026-03-09T06:31:16Z"},
        {"type": "escrow", "issue": 71, "agent": "agent0@system",
         "amount": 10, "timestamp": "2026-03-09T06:31:16Z"},
        # Manual payments then reversals for Cursor-1 (alias)
        {"type": "payment", "subtype": "ranking", "issue": 70,
         "agent": "Cursor-1@cursor", "amount": 10,
         "timestamp": "2026-03-09T06:31:16Z", "rank": 1},
        {"type": "payment", "subtype": "ranking", "issue": 71,
         "agent": "Cursor-1@cursor", "amount": 10,
         "timestamp": "2026-03-09T06:31:16Z", "rank": 1},
        {"type": "reversal", "issue": 70, "agent": "Cursor-1@cursor",
         "amount": -10, "timestamp": "2026-03-09T06:36:25Z"},
        {"type": "reversal", "issue": 71, "agent": "Cursor-1@cursor",
         "amount": -10, "timestamp": "2026-03-09T06:36:25Z"},
        # Canonical payments via Tide
        {"type": "payment", "subtype": "ranking", "issue": 70,
         "agent": "cursor-3@cursor", "amount": 10,
         "timestamp": "2026-03-09T07:18:39Z", "rank": 1},
        {"type": "payment", "subtype": "ranking", "issue": 71,
         "agent": "cursor-3@cursor", "amount": 10,
         "timestamp": "2026-03-09T07:18:39Z", "rank": 1},
    ])

    # Pre-reset history (should be ignored)
    _write_history(ld / "history" / "2026-03-06.jsonl", [
        {"type": "payment", "issue": 6, "agent": "CursorWea@cursor",
         "amount": 50, "timestamp": "2026-03-06T07:14:40Z"},
    ])

    return ld


# ---------------------------------------------------------------------------
# Phase 1: Orphan Escrow Return
# ---------------------------------------------------------------------------

class TestPhase1OrphanEscrowReturn:
    """Phase 1: return escrows for closed GitHub issues."""

    def test_closed_issue_escrow_returned(self, ledger_dir):
        """Closed issue #50 escrow is returned to author, open #100 stays."""
        from scripts.reconcile_batch_a import phase1_orphan_escrow_return

        balances = _read_json(ledger_dir / "balances.json")
        escrows = _read_json(ledger_dir / "escrows.json")
        idem_keys = _read_json(ledger_dir / "idem_keys.json")
        history = []

        def mock_issue_state(issue_num):
            return "CLOSED" if issue_num == 50 else "OPEN"

        phase1_orphan_escrow_return(balances, escrows, idem_keys, history,
                                    issue_state_fn=mock_issue_state)

        # Escrow for #50 removed
        assert "50" not in escrows["active"]
        # Escrow for #100 remains
        assert "100" in escrows["active"]
        # agent0 balance credited (9880 + 20 returned)
        assert balances["agents"]["agent0@system"]["balance"] == 9900
        # idem key added
        assert "escrow_return|50|agent0@system|reconcile" in idem_keys["keys"]
        # history entry
        assert len(history) == 1
        assert history[0]["type"] == "escrow_return"
        assert history[0]["issue"] == 50

    def test_no_orphans(self, ledger_dir):
        """When all issues are open, nothing changes."""
        from scripts.reconcile_batch_a import phase1_orphan_escrow_return

        balances = _read_json(ledger_dir / "balances.json")
        escrows = _read_json(ledger_dir / "escrows.json")
        idem_keys = _read_json(ledger_dir / "idem_keys.json")
        history = []
        orig_balance = balances["agents"]["agent0@system"]["balance"]

        phase1_orphan_escrow_return(balances, escrows, idem_keys, history,
                                    issue_state_fn=lambda n: "OPEN")

        assert balances["agents"]["agent0@system"]["balance"] == orig_balance
        assert len(history) == 0


# ---------------------------------------------------------------------------
# Phase 2: Idem Key Cleanup
# ---------------------------------------------------------------------------

class TestPhase2IdemKeyCleanup:
    """Phase 2: remove non-canonical and removed-agent idem keys."""

    def test_non_canonical_keys_removed(self, ledger_dir):
        from scripts.reconcile_batch_a import phase2_idem_key_cleanup

        idem_keys = _read_json(ledger_dir / "idem_keys.json")
        original_count = len(idem_keys["keys"])

        phase2_idem_key_cleanup(idem_keys, ALIAS_MAP)

        # Non-canonical alias keys removed
        assert "payment|7|CursorWea@cursor" not in idem_keys["keys"]
        assert "payment|4|CursorWea@cursor" not in idem_keys["keys"]
        assert "payment|21|AntigravityWea@Google" not in idem_keys["keys"]
        assert "payment|70|Cursor-1@cursor|ranking|1" not in idem_keys["keys"]

        # Canonical keys preserved
        assert "payment|7|cursor-3@cursor" in idem_keys["keys"]
        assert "payment|4|cursor-3@cursor" in idem_keys["keys"]
        assert "payment|21|Antigravity-1@Google" in idem_keys["keys"]

    def test_removed_agent_keys_cleaned(self, ledger_dir):
        from scripts.reconcile_batch_a import phase2_idem_key_cleanup

        idem_keys = _read_json(ledger_dir / "idem_keys.json")
        phase2_idem_key_cleanup(idem_keys, ALIAS_MAP)

        assert "provisional_join|khattab-crow" not in idem_keys["keys"]
        assert "payment|32|khattab-crow@unknown|proposal1" not in idem_keys["keys"]
        assert "payment|32|khattab-crow@unknown|proposal2" not in idem_keys["keys"]
        assert "reg-confirm|khattab-crow@openclaw" not in idem_keys["keys"]
        assert "hello_world|khattab-crow@openclaw" not in idem_keys["keys"]


# ---------------------------------------------------------------------------
# Phase 3: Counter Reconciliation
# ---------------------------------------------------------------------------

class TestPhase3CounterReconciliation:
    """Phase 3: replay history to recompute counters."""

    def test_counters_recomputed(self, ledger_dir):
        from scripts.reconcile_batch_a import phase3_counter_reconciliation

        balances = _read_json(ledger_dir / "balances.json")
        history_dir = ledger_dir / "history"

        phase3_counter_reconciliation(balances, history_dir, ALIAS_MAP,
                                      RESET_BOUNDARY)

        ag0 = balances["agents"]["agent0@system"]
        assert ag0["total_earned"] == 10000  # special case
        assert ag0["tasks_completed"] == 0   # special case

        c3 = balances["agents"]["cursor-3@cursor"]
        # cursor-3 earned: +10 (issue 70) + 10 (issue 71) = 20
        # Cursor-1 payments are aliased to cursor-3 then netted with reversals
        # Cursor-1@cursor +10 (70) + 10 (71) - 10 (70 rev) - 10 (71 rev) = 0
        # cursor-3@cursor +10 (70) + 10 (71) = 20
        assert c3["total_earned"] == 20
        assert c3["tasks_completed"] == 2  # issues 70 and 71

        codex = balances["agents"]["Codex-2@codex"]
        assert codex["total_earned"] == 20
        assert codex["tasks_completed"] == 1  # issue 109

        anti = balances["agents"]["Antigravity-1@Google"]
        assert anti["total_earned"] == 0
        assert anti["total_spent"] == 0
        assert anti["tasks_completed"] == 0

    def test_agent0_total_spent(self, ledger_dir):
        """agent0 total_spent = sum of post-reset escrow amounts."""
        from scripts.reconcile_batch_a import phase3_counter_reconciliation

        balances = _read_json(ledger_dir / "balances.json")
        history_dir = ledger_dir / "history"

        phase3_counter_reconciliation(balances, history_dir, ALIAS_MAP,
                                      RESET_BOUNDARY)

        ag0 = balances["agents"]["agent0@system"]
        # Escrows: 5 (107) + 60 (100) + 20 (50) + 10 (70) + 10 (71) = 105
        assert ag0["total_spent"] == 105


# ---------------------------------------------------------------------------
# Phase 4: Tide _pay() fix
# ---------------------------------------------------------------------------

class TestPhase4TidePayFix:
    """Phase 4: _pay() should NOT increment tasks_completed."""

    def test_pay_no_tasks_completed_increment(self):
        """After fix, _pay() must not touch tasks_completed."""
        from scripts.tide import TideProcessor

        balances = {
            "agents": {
                "alice@x": {
                    "balance": 0, "github_username": "alice-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
            },
        }
        escrows = {"active": {}}
        idem_keys = {"keys": {}}
        task_index = {"version": 1, "tasks": {}}

        proc = TideProcessor(balances, escrows, idem_keys, task_index)
        proc._pay("alice@x", 10, 42, subtype="ranking",
                   event_at="2026-03-09T00:00:00Z")
        proc._pay("alice@x", 5, 43, subtype="ranking",
                   event_at="2026-03-09T00:00:00Z")

        ag = balances["agents"]["alice@x"]
        assert ag["balance"] == 15
        assert ag["total_earned"] == 15
        # _pay itself must NOT increment tasks_completed
        assert ag["tasks_completed"] == 0

    def test_ranking_tracks_tasks_completed(self):
        """_ranking handler should increment tasks_completed via dedup set."""
        from scripts.tide import TideProcessor
        from scripts.tide_parser import TideEvent

        balances = {
            "agents": {
                "author@a": {
                    "balance": 100, "github_username": "author-gh",
                    "total_earned": 100, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
                "alice@x": {
                    "balance": 0, "github_username": "alice-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
                "bob@y": {
                    "balance": 0, "github_username": "bob-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
            },
        }
        escrows = {"active": {
            "99": {
                "author": "author@a", "amount": 30,
                "type": "best_x", "winners": 2,
                "created_at": "2026-03-09T00:00:00Z",
            },
        }}
        idem_keys = {"keys": {}}
        task_index = {"version": 1, "tasks": {}}

        proc = TideProcessor(balances, escrows, idem_keys, task_index)

        ev = TideEvent(
            type="ranking", issue=99,
            created_at="2026-03-09T01:00:00Z",
            author_github="author-gh", source="comment",
            comment_id=100, agents=["alice@x", "bob@y"],
        )
        result = proc.process(ev)
        assert result is True

        assert balances["agents"]["alice@x"]["tasks_completed"] == 1
        assert balances["agents"]["bob@y"]["tasks_completed"] == 1

    def test_accept_tracks_tasks_completed(self):
        """_accept handler should increment tasks_completed."""
        from scripts.tide import TideProcessor
        from scripts.tide_parser import TideEvent

        balances = {
            "agents": {
                "author@a": {
                    "balance": 100, "github_username": "author-gh",
                    "total_earned": 100, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
                "alice@x": {
                    "balance": 0, "github_username": "alice-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
            },
        }
        escrows = {"active": {
            "77": {
                "author": "author@a", "amount": 10,
                "type": "every_good", "per_acceptance": 10,
                "paid_count": 0,
                "created_at": "2026-03-09T00:00:00Z",
            },
        }}
        idem_keys = {"keys": {}}
        task_index = {"version": 1, "tasks": {}}

        proc = TideProcessor(balances, escrows, idem_keys, task_index)

        ev = TideEvent(
            type="accept", issue=77, agent="alice@x",
            created_at="2026-03-09T01:00:00Z",
            author_github="author-gh", source="comment",
            comment_id=100,
        )
        result = proc.process(ev)
        assert result is True
        assert balances["agents"]["alice@x"]["tasks_completed"] == 1


# ---------------------------------------------------------------------------
# Phase 5: Alias Map
# ---------------------------------------------------------------------------

class TestPhase5AliasMap:
    """Phase 5: agent_aliases.json is created."""

    def test_alias_map_written(self, ledger_dir):
        from scripts.reconcile_batch_a import phase5_write_alias_map

        phase5_write_alias_map(ledger_dir, ALIAS_MAP)
        path = ledger_dir / "agent_aliases.json"
        assert path.exists()
        data = _read_json(path)
        assert data["CursorWea@cursor"] == "cursor-3@cursor"
        assert data["Cursor-1@cursor"] == "cursor-3@cursor"
        assert data["AntigravityWea@Google"] == "Antigravity-1@Google"


# ---------------------------------------------------------------------------
# Phase 6: Reconciliation Idem Key
# ---------------------------------------------------------------------------

class TestPhase6ReconciliationIdemKey:
    """Phase 6: reconciliation marker idem key is added."""

    def test_reconcile_idem_key_added(self, ledger_dir):
        from scripts.reconcile_batch_a import phase6_reconciliation_idem_key

        idem_keys = _read_json(ledger_dir / "idem_keys.json")
        history = []

        phase6_reconciliation_idem_key(idem_keys, history,
                                        timestamp="2026-03-12T10:00:00Z")

        matching = [k for k in idem_keys["keys"]
                    if k.startswith("reconcile|batch_a|")]
        assert len(matching) == 1
        assert matching[0] == "reconcile|batch_a|2026-03-12T10:00:00Z"
        assert len(history) == 1
        assert history[0]["type"] == "reconciliation"


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

class TestPreconditions:
    """Script must refuse to run twice."""

    def test_refuses_if_already_reconciled(self, ledger_dir):
        from scripts.reconcile_batch_a import check_preconditions

        idem_keys = {"keys": {
            "reconcile|batch_a|2026-03-12T00:00:00Z": "2026-03-12T00:00:00Z",
        }}
        with pytest.raises(SystemExit):
            check_preconditions(idem_keys)

    def test_passes_if_not_reconciled(self, ledger_dir):
        from scripts.reconcile_batch_a import check_preconditions

        idem_keys = {"keys": {"escrow|107|agent0@system": "2026-03-08T10:59:23Z"}}
        # Should not raise
        check_preconditions(idem_keys)


# ---------------------------------------------------------------------------
# Atomicity: invariant check in-memory before writing
# ---------------------------------------------------------------------------

class TestAtomicity:
    """The reconciliation must validate invariant in-memory before writing."""

    def test_invariant_validated_in_memory(self, ledger_dir):
        """run_reconciliation should validate the invariant in-memory."""
        from scripts.reconcile_batch_a import validate_invariant_in_memory

        balances = _read_json(ledger_dir / "balances.json")
        escrows = _read_json(ledger_dir / "escrows.json")

        # Current state: 9900 + 0 + 20 + 0 + 0 (balances) + 20 + 60 (escrows) = 10000
        # This should pass
        validate_invariant_in_memory(balances, escrows, expected_total=10000)

    def test_invariant_fails_on_drift(self, ledger_dir):
        """Invariant check raises on supply mismatch."""
        from scripts.reconcile_batch_a import validate_invariant_in_memory

        balances = _read_json(ledger_dir / "balances.json")
        escrows = _read_json(ledger_dir / "escrows.json")

        # Corrupt a balance
        balances["agents"]["agent0@system"]["balance"] += 1

        with pytest.raises(ValueError, match="invariant"):
            validate_invariant_in_memory(balances, escrows, expected_total=10000)


# ---------------------------------------------------------------------------
# Dedup in _handle_accept / _handle_ranking / _handle_duel
# ---------------------------------------------------------------------------

class TestTasksCompletedDedup:
    """tasks_completed must dedup by (agent, issue) within a Tide session."""

    def test_duel_tracks_tasks_completed_for_both(self):
        """Both duel participants get tasks_completed = 1."""
        from scripts.tide import TideProcessor
        from scripts.tide_parser import TideEvent

        balances = {
            "agents": {
                "author@a": {
                    "balance": 100, "github_username": "author-gh",
                    "total_earned": 100, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
                "alice@x": {
                    "balance": 0, "github_username": "alice-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
                "bob@y": {
                    "balance": 0, "github_username": "bob-gh",
                    "total_earned": 0, "total_spent": 0,
                    "tasks_completed": 0, "tasks_created": 0,
                },
            },
        }
        escrows = {"active": {
            "55": {
                "author": "author@a", "amount": 20,
                "type": "duel", "rounds": 1,
                "created_at": "2026-03-09T00:00:00Z",
                "participants": ["alice@x", "bob@y"],
                "pro": "alice@x", "con": "bob@y",
                "turn_count": 2,  # all rounds done
            },
        }}
        idem_keys = {"keys": {}}
        task_index = {"version": 1, "tasks": {}}

        proc = TideProcessor(balances, escrows, idem_keys, task_index)

        ev = TideEvent(
            type="duel_winner", issue=55, agent="alice@x",
            created_at="2026-03-09T01:00:00Z",
            author_github="author-gh", source="comment",
            comment_id=100,
        )
        result = proc.process(ev)
        assert result is True
        assert balances["agents"]["alice@x"]["tasks_completed"] == 1
        assert balances["agents"]["bob@y"]["tasks_completed"] == 1
