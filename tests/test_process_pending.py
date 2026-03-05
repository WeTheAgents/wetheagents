from __future__ import annotations

import json
from pathlib import Path

from scripts.process_pending import idem_key_hash, process


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _supply_total(balances: dict, escrows: dict) -> int:
    balances_sum = sum(v.get("balance", 0) for v in balances.get("agents", {}).values())
    escrow_sum = sum(v.get("amount", 0) for v in escrows.get("active", {}).values())
    return balances_sum + escrow_sum


def test_process_standard_payment_keeps_supply_and_exhausts_escrow(temp_repo: Path) -> None:
    balances_path = temp_repo / "ledger" / "balances.json"
    escrows_path = temp_repo / "ledger" / "escrows.json"
    pending_path = temp_repo / "ledger" / "pending.json"

    balances = _read_json(balances_path)
    escrows = _read_json(escrows_path)

    escrows["active"]["201"] = {
        "author": "author@local",
        "amount": 10,
        "type": "standard",
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, escrows)
    before_total = _supply_total(balances, escrows)
    _write_json(
        pending_path,
        {
            "version": 1,
            "queue": [
                {
                    "type": "payment",
                    "mechanic": "standard",
                    "issue": 201,
                    "agent": "alice@test",
                    "amount": 10,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:01:00Z",
                    "event_at": "2026-03-04T10:01:00Z",
                }
            ],
        },
    )

    rc = process(temp_repo, dry_run=False)
    assert rc == 0

    balances = _read_json(balances_path)
    escrows = _read_json(escrows_path)
    pending = _read_json(pending_path)
    assert balances["agents"]["alice@test"]["balance"] == 10
    assert "201" not in escrows["active"]
    assert pending["queue"] == []
    assert _supply_total(balances, escrows) == before_total


def test_process_rejects_duplicate_idem_key_from_ledger(temp_repo: Path) -> None:
    escrows_path = temp_repo / "ledger" / "escrows.json"
    pending_path = temp_repo / "ledger" / "pending.json"
    idem_path = temp_repo / "ledger" / "idem_keys.json"

    escrows = _read_json(escrows_path)
    escrows["active"]["202"] = {
        "author": "author@local",
        "amount": 10,
        "type": "standard",
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, escrows)

    raw_key = "payment|202|alice@test"
    idem = _read_json(idem_path)
    idem["keys"][idem_key_hash(raw_key)] = {
        "action": "payment",
        "timestamp": "2026-03-04T10:00:00Z",
    }
    _write_json(idem_path, idem)

    _write_json(
        pending_path,
        {
            "version": 1,
            "queue": [
                {
                    "type": "payment",
                    "mechanic": "standard",
                    "issue": 202,
                    "agent": "alice@test",
                    "amount": 10,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:01:00Z",
                    "event_at": "2026-03-04T10:01:00Z",
                }
            ],
        },
    )

    rc = process(temp_repo, dry_run=False)
    assert rc == 1
    pending_after = _read_json(pending_path)
    assert len(pending_after["queue"]) == 1


def test_process_progressive_pod_fibonacci_slots(temp_repo: Path) -> None:
    balances_path = temp_repo / "ledger" / "balances.json"
    escrows_path = temp_repo / "ledger" / "escrows.json"
    pending_path = temp_repo / "ledger" / "pending.json"

    escrows = _read_json(escrows_path)
    escrows["active"]["203"] = {
        "author": "author@local",
        "amount": 4,
        "type": "progressive",
        "slots": 3,
        "paid_count": 0,
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, escrows)

    _write_json(
        pending_path,
        {
            "version": 1,
            "queue": [
                {
                    "type": "payment",
                    "mechanic": "progressive",
                    "issue": 203,
                    "agent": "alice@test",
                    "amount": 1,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:01:00Z",
                    "event_at": "2026-03-04T10:01:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "progressive",
                    "issue": 203,
                    "agent": "bob@test",
                    "amount": 1,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:02:00Z",
                    "event_at": "2026-03-04T10:02:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "progressive",
                    "issue": 203,
                    "agent": "carol@test",
                    "amount": 2,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:03:00Z",
                    "event_at": "2026-03-04T10:03:00Z",
                },
            ],
        },
    )

    rc = process(temp_repo, dry_run=False)
    assert rc == 0

    balances = _read_json(balances_path)
    escrows = _read_json(escrows_path)
    assert "203" not in escrows["active"]
    assert balances["agents"]["alice@test"]["balance"] == 1
    assert balances["agents"]["bob@test"]["balance"] == 1
    assert balances["agents"]["carol@test"]["balance"] == 2


def test_process_ranking_and_winner_take_all_splits(temp_repo: Path) -> None:
    balances_path = temp_repo / "ledger" / "balances.json"
    escrows_path = temp_repo / "ledger" / "escrows.json"
    pending_path = temp_repo / "ledger" / "pending.json"

    escrows = _read_json(escrows_path)
    escrows["active"]["204"] = {
        "author": "author@local",
        "amount": 100,
        "type": "best_x",
        "winners": 2,
        "created_at": "2026-03-04T10:00:00Z",
    }
    escrows["active"]["205"] = {
        "author": "author@local",
        "amount": 100,
        "type": "best_x",
        "winners": 3,
        "created_at": "2026-03-04T10:00:00Z",
    }
    escrows["active"]["206"] = {
        "author": "author@local",
        "amount": 100,
        "type": "best_x",
        "winners": 1,
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, escrows)

    _write_json(
        pending_path,
        {
            "version": 1,
            "queue": [
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 204,
                    "agent": "alice@test",
                    "amount": 70,
                    "rank": 1,
                    "total_ranked": 2,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:01:00Z",
                    "event_at": "2026-03-04T10:01:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 204,
                    "agent": "bob@test",
                    "amount": 30,
                    "rank": 2,
                    "total_ranked": 2,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:01:00Z",
                    "event_at": "2026-03-04T10:01:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 205,
                    "agent": "alice@test",
                    "amount": 50,
                    "rank": 1,
                    "total_ranked": 3,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:02:00Z",
                    "event_at": "2026-03-04T10:02:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 205,
                    "agent": "bob@test",
                    "amount": 30,
                    "rank": 2,
                    "total_ranked": 3,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:02:00Z",
                    "event_at": "2026-03-04T10:02:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 205,
                    "agent": "carol@test",
                    "amount": 20,
                    "rank": 3,
                    "total_ranked": 3,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:02:00Z",
                    "event_at": "2026-03-04T10:02:00Z",
                },
                {
                    "type": "payment",
                    "mechanic": "ranking",
                    "issue": 206,
                    "agent": "alice@test",
                    "amount": 100,
                    "rank": 1,
                    "total_ranked": 1,
                    "proposed_by": "author@local",
                    "proposed_at": "2026-03-04T10:03:00Z",
                    "event_at": "2026-03-04T10:03:00Z",
                },
            ],
        },
    )

    rc = process(temp_repo, dry_run=False)
    assert rc == 0

    balances = _read_json(balances_path)
    escrows = _read_json(escrows_path)
    assert "204" not in escrows["active"]
    assert "205" not in escrows["active"]
    assert "206" not in escrows["active"]
    assert balances["agents"]["alice@test"]["balance"] == 220
    assert balances["agents"]["bob@test"]["balance"] == 60
    assert balances["agents"]["carol@test"]["balance"] == 20
