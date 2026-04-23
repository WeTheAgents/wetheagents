from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_escrow_solvency import main, run_check


def _ts(hour: int) -> str:
    return f"2026-01-01T{hour:02d}:00:00Z"


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_solvent_escrow_create_passes(temp_repo: Path) -> None:
    root = temp_repo
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@test", "amount": 50, "timestamp": _ts(1)},
            {"type": "escrow_create", "issue": 42, "author": "alice@test", "amount": 40, "timestamp": _ts(2)},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_insolvent_escrow_create_fails(temp_repo: Path) -> None:
    root = temp_repo
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@test", "amount": 50, "timestamp": _ts(1)},
            {"type": "escrow_create", "issue": 43, "author": "alice@test", "amount": 60, "timestamp": _ts(2)},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 43
    assert report["violations"][0]["balance_before"] == 50
    assert report["violations"][0]["shortfall"] == 10


def test_concurrent_escrows_exceeding_balance_fail(temp_repo: Path) -> None:
    root = temp_repo
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@test", "amount": 70, "timestamp": _ts(1)},
            {"type": "escrow_create", "issue": 50, "author": "alice@test", "amount": 40, "timestamp": _ts(2)},
            {"type": "escrow_create", "issue": 51, "author": "alice@test", "amount": 35, "timestamp": _ts(2)},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 2
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 51
    assert report["violations"][0]["balance_before"] == 30
    assert report["violations"][0]["shortfall"] == 5


def test_zero_balance_escrow_create_fails(temp_repo: Path) -> None:
    root = temp_repo
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow_create", "issue": 99, "from": "alice@test", "amount": 1, "ts": _ts(1)},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["author"] == "alice@test"
    assert report["violations"][0]["balance_before"] == 0
    assert report["violations"][0]["shortfall"] == 1


def test_main_json_flag_outputs_json(temp_repo: Path, capsys) -> None:
    root = temp_repo
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "alice@test", "amount": 10, "timestamp": _ts(1)},
            {"type": "escrow_create", "issue": 77, "author": "alice@test", "amount": 10, "timestamp": _ts(2)},
        ],
    )

    exit_code = main(["--root", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["escrows_checked"] == 1
