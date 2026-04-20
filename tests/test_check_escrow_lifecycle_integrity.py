from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_escrow_lifecycle_integrity import main, run_check  # noqa: E402


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_root(root: Path, events_by_file: dict[str, list[dict | str]]) -> Path:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for filename, events in events_by_file.items():
        _write_jsonl(history_dir / filename, events)
    return root


def _issues(report: dict) -> list[dict]:
    return report["issues"]


def test_accept_closes_escrow_create_pass(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "accept", "issue": 42, "amount": 30, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["passes"] == 1
    assert report["summary"]["failures"] == 0
    assert _issues(report) == [{
        "issue": 42,
        "status": "PASS",
        "reason": None,
        "create_kind": "escrow_create",
        "close_kind": "accept",
        "create_amount": 30,
        "close_amount": 30,
        "create_file": "2026-04-01.jsonl",
        "create_line": 1,
        "close_file": "2026-04-01.jsonl",
        "close_line": 2,
    }]


def test_payment_is_valid_equivalent_close_pass(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 77, "amount": 12, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 77, "amount": 12, "agent": "alice@test", "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["passes"] == 1
    assert report["summary"]["close_events_scanned"] == 1
    assert _issues(report)[0]["close_kind"] == "payment"


def test_mixed_event_and_op_fields_are_normalized(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-02.jsonl": [
            {"op": "escrow_create", "issue": 90, "amount": 8, "ts": "2026-04-01T00:00:00Z"},
        ],
        "2026-04-01.jsonl": [
            {"event": "escrow_return", "issue": 90, "amount": 8, "timestamp": "2026-04-01T01:00:00Z"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["passes"] == 1
    assert _issues(report)[0]["create_kind"] == "escrow_create"
    assert _issues(report)[0]["close_kind"] == "escrow_return"


def test_missing_close_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 101, "amount": 20, "timestamp": "2026-04-01T00:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["passes"] == 0
    assert report["summary"]["failures"] == 1
    assert _issues(report)[0]["reason"] == "no_close_event"


def test_amount_mismatch_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 102, "amount": 20, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "accept", "issue": 102, "amount": 19, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["failures"] == 1
    assert _issues(report)[0]["reason"] == "amount_mismatch"
    assert _issues(report)[0]["create_amount"] == 20
    assert _issues(report)[0]["close_amount"] == 19


def test_close_without_prior_create_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "accept", "issue": 103, "amount": 11, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["failures"] == 1
    assert _issues(report)[0]["reason"] == "close_without_prior_create"
    assert _issues(report)[0]["create_kind"] is None


def test_unrelated_payment_without_tracked_create_is_ignored(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 200, "amount": 9, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["passes"] == 0
    assert report["summary"]["failures"] == 0
    assert _issues(report) == []


def test_multiple_closes_for_single_create_fail_on_extra_close(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 104, "amount": 15, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "accept", "issue": 104, "amount": 15, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 104, "amount": 15, "agent": "alice@test", "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["passes"] == 1
    assert report["summary"]["failures"] == 1
    assert _issues(report)[0]["status"] == "PASS"
    assert _issues(report)[1]["reason"] == "close_without_prior_create"
    assert _issues(report)[1]["close_kind"] == "payment"


def test_legacy_escrow_can_absorb_later_payment_after_tracked_close(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 260, "amount": 15, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "accept", "issue": 260, "amount": 15, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "escrow", "issue": 260, "amount": 15, "timestamp": "2026-04-01T02:00:00Z"},
            {"type": "payment", "issue": 260, "amount": 15, "agent": "alice@test", "timestamp": "2026-04-01T03:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["passes"] == 1
    assert report["summary"]["failures"] == 0
    assert len(_issues(report)) == 1
    assert _issues(report)[0]["close_kind"] == "accept"


def test_invalid_escrow_create_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 106, "timestamp": "2026-04-01T00:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["failures"] == 1
    assert _issues(report)[0]["reason"] == "invalid_escrow_create"


def test_main_json_output_and_exit_code_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 105, "amount": 22, "timestamp": "2026-04-01T00:00:00Z"},
        ]
    })

    exit_code = main(["--root", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["summary"]["failures"] == 1
    assert payload["issues"][0]["reason"] == "no_close_event"
