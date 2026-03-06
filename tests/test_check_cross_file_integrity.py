from __future__ import annotations

import json
from pathlib import Path

from scripts.check_cross_file_integrity import run_checks


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, *records: dict) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record) for record in records]
    (history_dir / "2026-03-06.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_repo(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "ledger" / "balances.json",
        {
            "agents": {
                "author@test": {"balance": 10},
                "worker@test": {"balance": 5},
            }
        },
    )
    _write_json(
        root / "ledger" / "escrows.json",
        {
            "active": {
                "42": {"author": "author@test", "amount": 3, "type": "standard"},
            }
        },
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {
            "keys": {
                "payment|42|worker@test": "2026-03-06T10:00:00Z",
            }
        },
    )
    _write_history(
        root,
        {
            "type": "payment",
            "issue": 42,
            "agent": "worker@test",
            "amount": 3,
            "timestamp": "2026-03-06T10:00:00Z",
        },
    )
    return root


def test_run_checks_passes_on_clean_data(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)

    checks = run_checks(
        root,
        repo="WeTheAgents/wetheagents",
        issue_fetcher=lambda issue: {"state": "OPEN", "label_names": {"task", "open"}},
    )

    assert all(not failures for _, failures in checks)


def test_missing_escrow_author_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    escrows = json.loads((root / "ledger" / "escrows.json").read_text(encoding="utf-8"))
    escrows["active"]["42"]["author"] = "ghost@test"
    _write_json(root / "ledger" / "escrows.json", escrows)

    checks = dict(
        run_checks(
            root,
            repo="WeTheAgents/wetheagents",
            issue_fetcher=lambda issue: {"state": "OPEN", "label_names": {"task", "open"}},
        )
    )

    assert checks["Every escrow author exists in balances.json"]


def test_orphaned_escrow_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    checks = dict(
        run_checks(
            root,
            repo="WeTheAgents/wetheagents",
            issue_fetcher=lambda issue: {"state": "CLOSED", "label_names": {"task"}},
        )
    )

    assert checks["No orphaned escrows"] == ["escrow #42: issue is closed without `paid` label"]


def test_payment_idem_without_history_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    _write_history(root)

    checks = dict(
        run_checks(
            root,
            repo="WeTheAgents/wetheagents",
            issue_fetcher=lambda issue: {"state": "OPEN", "label_names": {"task", "open"}},
        )
    )

    assert checks["Every payment idem key has a corresponding history entry"]


def test_duplicate_agent_ids_and_negative_balances_fail(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    _write_json(
        root / "ledger" / "balances.json",
        {
            "agents": {
                "worker@test": {"balance": 5},
                "Worker@Test": {"balance": -1},
                "author@test": {"balance": 10},
            }
        },
    )

    checks = dict(
        run_checks(
            root,
            repo="WeTheAgents/wetheagents",
            issue_fetcher=lambda issue: {"state": "OPEN", "label_names": {"task", "open"}},
        )
    )

    assert checks["No duplicate agent entries in balances.json"]
    assert checks["All agent balances are non-negative"]
