"""Tests for cross-path idempotency key alignment between tide.py and process_pending.py.

Verifies that a payment processed through one path (tide or process_pending)
is correctly detected as a duplicate by the other path. This prevents double
payments when the same operation is processed through both settlement engines.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.process_pending import build_idem_key, process
from scripts.tide import TideProcessor
from scripts.tide_ops import idem_key_hash
from scripts.tide_parser import TideEvent

# ---------------------------------------------------------------------------
# Helpers (matching test_tide.py patterns)
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
        }
    }
    base.update(overrides)
    return base


def _escrows(**active):
    return {"active": dict(active)}


def _idem(*keys):
    return {"keys": {k: "2026-01-01T00:00:00Z" for k in keys}}


def _ev(type, issue=1, agent=None, **kw):
    return TideEvent(
        type=type, issue=issue,
        created_at=kw.pop("created_at", "2026-03-05T12:00:00Z"),
        author_github=kw.pop("author_github", "alice-gh"),
        source=kw.pop("source", "comment"),
        comment_id=kw.pop("comment_id", 100),
        agent=agent,
        agents=kw.pop("agents", []),
        reason=kw.pop("reason", None),
        task_author_agent=kw.pop("task_author_agent", None),
        reward=kw.pop("reward", None),
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
        achievements={},
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: Cross-path detection
# ---------------------------------------------------------------------------


class TestCrossPathIdemDetection:
    """Payment via tide.py must be detected by process_pending.py and vice versa."""

    def test_tide_payment_blocks_process_pending(self, temp_repo: Path) -> None:
        """After tide pays bob@y for issue #202, process_pending rejects the same."""
        # 1. Run tide accept for standard payment
        p = _proc(escrows=_escrows(**{
            "202": {"author": "alice@x", "amount": 20, "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("accept", issue=202, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)

        # 2. Tide wrote a hashed idem key — extract it
        tide_idem_keys = p.idem_keys

        # 3. Set up process_pending with the same idem_keys
        _write_json(temp_repo / "ledger" / "idem_keys.json", tide_idem_keys)

        # Create escrow (fresh, as if tide didn't deplete it — simulates race)
        escrows = _read_json(temp_repo / "ledger" / "escrows.json")
        escrows["active"]["202"] = {
            "author": "author@local",
            "amount": 20,
            "type": "standard",
            "created_at": "2026-03-04T10:00:00Z",
        }
        _write_json(temp_repo / "ledger" / "escrows.json", escrows)

        # Queue same payment via process_pending
        _write_json(
            temp_repo / "ledger" / "pending.json",
            {
                "version": 1,
                "queue": [
                    {
                        "type": "payment",
                        "mechanic": "standard",
                        "issue": 202,
                        "agent": "bob@test",  # different agent in balances
                        "amount": 20,
                        "proposed_by": "author@local",
                        "proposed_at": "2026-03-04T10:01:00Z",
                        "event_at": "2026-03-04T10:01:00Z",
                    },
                ],
            },
        )

        # This should succeed (different agent), confirming idem keys don't
        # collide across agents
        rc = process(temp_repo, dry_run=False)
        assert rc == 0

    def test_tide_payment_exact_duplicate_blocked(self, temp_repo: Path) -> None:
        """Exact same payment (same issue, same agent) blocked across paths."""
        # 1. Run tide accept
        p = _proc(escrows=_escrows(**{
            "202": {"author": "alice@x", "amount": 20, "type": "standard",
                    "created_at": "2026-01-01T00:00:00Z"},
        }))
        ev = _ev("accept", issue=202, agent="bob@y", author_github="alice-gh")
        assert p.process(ev)

        # 2. Put tide's idem keys into the ledger for process_pending
        _write_json(temp_repo / "ledger" / "idem_keys.json", p.idem_keys)

        # Set up balances with bob@y
        balances = _read_json(temp_repo / "ledger" / "balances.json")
        balances["agents"]["bob@y"] = {
            "balance": 0, "total_earned": 0, "total_spent": 0,
            "tasks_completed": 0, "tasks_created": 0,
        }
        _write_json(temp_repo / "ledger" / "balances.json", balances)

        escrows = _read_json(temp_repo / "ledger" / "escrows.json")
        escrows["active"]["202"] = {
            "author": "author@local",
            "amount": 20,
            "type": "standard",
            "created_at": "2026-03-04T10:00:00Z",
        }
        _write_json(temp_repo / "ledger" / "escrows.json", escrows)

        # Queue same payment: same issue, same agent
        _write_json(
            temp_repo / "ledger" / "pending.json",
            {
                "version": 1,
                "queue": [
                    {
                        "type": "payment",
                        "mechanic": "standard",
                        "issue": 202,
                        "agent": "bob@y",
                        "amount": 20,
                        "proposed_by": "author@local",
                        "proposed_at": "2026-03-04T10:01:00Z",
                        "event_at": "2026-03-04T10:01:00Z",
                    },
                ],
            },
        )

        # Should fail — idem key collision
        rc = process(temp_repo, dry_run=False)
        assert rc == 1  # validation error

    def test_process_pending_payment_blocks_tide(self) -> None:
        """After process_pending pays, tide must detect the duplicate."""
        raw_key = "payment|202|bob@y"
        hashed = idem_key_hash(raw_key)

        # Simulate process_pending having stored the hashed key
        p = _proc(
            idem_keys=_idem(hashed),
            escrows=_escrows(**{
                "202": {"author": "alice@x", "amount": 20, "type": "standard",
                        "created_at": "2026-01-01T00:00:00Z"},
            }),
        )

        # Tide tries to accept — should be blocked by idem
        ev = _ev("accept", issue=202, agent="bob@y", author_github="alice-gh")
        assert not p.process(ev)  # blocked by idem key

    def test_progressive_slot_keys_match_across_paths(self) -> None:
        """Progressive slot keys must match between tide and process_pending."""
        # tide.py format: payment|{issue}|{agent}|slot{paid_count+1}
        # process_pending format: build_idem_key with _slot field
        tide_key = "payment|203|bob@y|slot1"
        pp_key = build_idem_key("progressive", "203", "bob@y", {"_slot": 1})
        assert tide_key == pp_key

        tide_key_2 = "payment|203|carol@z|slot2"
        pp_key_2 = build_idem_key("progressive", "203", "carol@z", {"_slot": 2})
        assert tide_key_2 == pp_key_2

    def test_linear_slot_keys_match_across_paths(self) -> None:
        """Linear slot keys must match between tide and process_pending."""
        tide_key = "payment|300|alice@x|slot1"
        pp_key = build_idem_key("linear", "300", "alice@x", {"_slot": 1})
        assert tide_key == pp_key

    def test_ranking_keys_match_across_paths(self) -> None:
        """Ranking idem keys must use the same format in both paths."""
        tide_key = "payment|204|bob@y|ranking|1"
        pp_key = build_idem_key("ranking", "204", "bob@y", {"rank": 1})
        assert tide_key == pp_key

    def test_duel_keys_match_across_paths(self) -> None:
        """Duel idem keys must use the same format in both paths."""
        tide_key = "payment|205|bob@y|duel|winner"
        pp_key = build_idem_key("duel", "205", "bob@y", {"role": "winner"})
        assert tide_key == pp_key


class TestBackwardCompat:
    """Existing raw-string keys from old tide.py must still be detected."""

    def test_tide_detects_legacy_raw_key(self) -> None:
        """_has_idem finds a raw-string key stored before the hash migration."""
        raw_key = "payment|100|agent@x"
        # Legacy: raw key stored directly
        p = _proc(idem_keys=_idem(raw_key))
        assert p._has_idem(raw_key)

    def test_tide_detects_hashed_key(self) -> None:
        """_has_idem finds a hashed key (new format)."""
        raw_key = "payment|100|agent@x"
        hashed = idem_key_hash(raw_key)
        p = _proc(idem_keys=_idem(hashed))
        assert p._has_idem(raw_key)

    def test_set_idem_default_stores_raw(self) -> None:
        """_set_idem without use_hash stores raw key (for claim/escrow/verify)."""
        raw_key = "claim|100|agent@x"
        p = _proc()
        p._set_idem(raw_key)
        assert raw_key in p.idem_keys["keys"]

    def test_set_idem_hash_stores_hashed(self) -> None:
        """_set_idem with use_hash=True stores hashed key (for payments)."""
        raw_key = "payment|100|agent@x"
        p = _proc()
        p._set_idem(raw_key, use_hash=True)
        hashed = idem_key_hash(raw_key)
        assert hashed in p.idem_keys["keys"]
        assert raw_key not in p.idem_keys["keys"]
