from __future__ import annotations

import json
from pathlib import Path

from scripts.check_task_escrow_sync import run_checks


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_repo(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "ledger" / "task_index.json",
        {
            "tasks": {
                "42": {
                    "title": "Test task",
                    "author": "agent0@system",
                    "reward": 10,
                    "mechanic": "best_x",
                    "status": "open",
                }
            }
        },
    )
    _write_json(
        root / "ledger" / "escrows.json",
        {
            "active": {
                "42": {"author": "agent0@system", "amount": 10, "type": "best_x"}
            }
        },
    )
    return root


def test_open_task_with_matching_escrow_passes(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    checks = run_checks(root)
    assert all(not failures for _, failures in checks)


def test_open_task_without_escrow_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    _write_json(root / "ledger" / "escrows.json", {"active": {}})

    checks = dict(run_checks(root))
    failures = checks["Every open task has an active escrow"]
    assert len(failures) == 1
    assert "task #42" in failures[0]


def test_escrow_without_task_entry_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    escrows = json.loads((root / "ledger" / "escrows.json").read_text(encoding="utf-8"))
    escrows["active"]["99"] = {"author": "agent0@system", "amount": 5, "type": "pod"}
    _write_json(root / "ledger" / "escrows.json", escrows)

    checks = dict(run_checks(root))
    failures = checks["Every active escrow has a task_index entry"]
    assert len(failures) == 1
    assert "escrow #99" in failures[0]


def test_escrow_exceeds_reward_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    escrows = json.loads((root / "ledger" / "escrows.json").read_text(encoding="utf-8"))
    escrows["active"]["42"]["amount"] = 15
    _write_json(root / "ledger" / "escrows.json", escrows)

    checks = dict(run_checks(root))
    failures = checks["No escrow amount exceeds task reward"]
    assert len(failures) == 1
    assert "exceeds" in failures[0]


def test_escrow_less_than_reward_passes(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    escrows = json.loads((root / "ledger" / "escrows.json").read_text(encoding="utf-8"))
    escrows["active"]["42"]["amount"] = 7
    _write_json(root / "ledger" / "escrows.json", escrows)

    checks = run_checks(root)
    assert all(not failures for _, failures in checks)


def test_paid_task_no_escrow_passes(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    tasks = json.loads((root / "ledger" / "task_index.json").read_text(encoding="utf-8"))
    tasks["tasks"]["42"]["status"] = "paid"
    _write_json(root / "ledger" / "task_index.json", tasks)
    _write_json(root / "ledger" / "escrows.json", {"active": {}})

    checks = run_checks(root)
    assert all(not failures for _, failures in checks)


def test_empty_task_index_and_escrows_passes(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    _write_json(root / "ledger" / "task_index.json", {"tasks": {}})
    _write_json(root / "ledger" / "escrows.json", {"active": {}})

    checks = run_checks(root)
    assert all(not failures for _, failures in checks)
