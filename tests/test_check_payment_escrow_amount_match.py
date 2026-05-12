from __future__ import annotations

import json
from pathlib import Path

from scripts.check_payment_escrow_amount_match import main, run_check


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


def _check(report: dict) -> dict:
    return report["checks"][0]


def test_single_payment_within_escrow_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 7, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _check(report)["violations"] == []
    assert report["summary"]["payment_events_scanned"] == 1


def test_single_payment_exceeding_escrow_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 11, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert _check(report)["violations"] == [{
        "issue": "42",
        "agent": "alice@test",
        "amount": 11,
        "available_before": 10,
        "timestamp": "2026-04-01T01:00:00Z",
        "file": "2026-04-01.jsonl",
        "line": 2,
        "reason": "payment_exceeds_available_escrow",
    }]


def test_multiple_payments_up_to_escrow_pass(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 15, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 10, "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _check(report)["violations"] == []


def test_second_payment_that_overshoots_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": "42", "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 6, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 5, "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(_check(report)["violations"]) == 1
    assert _check(report)["violations"][0]["available_before"] == 4


def test_later_escrow_before_second_payment_replenishes_budget(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 8, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "escrow_create", "issue": 42, "amount": 5, "timestamp": "2026-04-01T02:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 7, "timestamp": "2026-04-01T03:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _check(report)["violations"] == []


def test_ts_timestamp_sorts_op_escrow_before_payment(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"op": "escrow_create", "issue": 42, "amount": 10, "ts": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _check(report)["violations"] == []


def test_duplicate_payment_with_same_balance_after_is_deduped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 40, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 40, "balance_after": 10, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 40, "balance_after": 10, "timestamp": "2026-04-01T01:00:05Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["deduped_duplicate_payments"] == 1


def test_later_escrow_does_not_retroactively_fix_earlier_overpayment(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-02.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 5, "timestamp": "2026-04-01T02:00:00Z"},
        ],
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 12, "timestamp": "2026-04-01T01:00:00Z"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(_check(report)["violations"]) == 1
    assert _check(report)["violations"][0]["amount"] == 12


def test_escrow_return_reduces_available_budget(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "escrow_return", "issue": 42, "amount": 3, "timestamp": "2026-04-01T02:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 3, "timestamp": "2026-04-01T03:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert _check(report)["violations"][0]["available_before"] == 2


def test_negative_reversal_restores_available_budget(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "reversal", "issue": 42, "agent": "alice@test", "amount": -10, "timestamp": "2026-04-01T02:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 10, "timestamp": "2026-04-01T03:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _check(report)["violations"] == []


def test_legacy_batch_only_issue_is_skipped_not_failed(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_batch", "issues": [4, 5, 6], "total": 30, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 5, "agent": "alice@test", "amount": 20, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["skipped_legacy_batch_only_payments"] == 1
    assert _check(report)["warnings"][0]["reason"] == "skipped_legacy_batch_without_per_issue_amount"


def test_payment_before_first_explicit_escrow_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert _check(report)["violations"][0]["available_before"] == 0


def test_malformed_and_non_json_payment_rows_are_skipped_cleanly(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            "not-json",
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": "oops", "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "bob@test", "amount": 5, "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["skipped_malformed_payments"] == 1
    assert len(_check(report)["warnings"]) == 1


def test_main_prints_json_and_returns_nonzero_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow", "issue": 42, "amount": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 11, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["summary"]["violations"] == 1
