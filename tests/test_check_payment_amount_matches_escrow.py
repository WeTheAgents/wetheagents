from __future__ import annotations

import json
from pathlib import Path

from scripts.check_payment_amount_matches_escrow import main, run_check


def _write_jsonl(path: Path, events: list[dict | str | int]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_root(root: Path, events_by_file: dict[str, list[dict | str | int]]) -> Path:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for filename, events in events_by_file.items():
        _write_jsonl(history_dir / filename, events)
    return root


def test_empty_history_passes(temp_repo: Path) -> None:
    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["history_files_scanned"] == 0


def test_single_payment_exactly_matches_escrow_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 10, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_split_payments_within_escrow_pass(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 4, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 6, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_multiple_explicit_escrows_are_summed(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 5},
            {"type": "escrow", "issue": 42, "amount": 7},
            {"type": "payment", "issue": 42, "amount": 12, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["escrow_create_events_scanned"] == 1
    assert report["stats"]["legacy_escrow_events_scanned"] == 1


def test_missing_escrow_reports_total_paid(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 42, "amount": 3, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 2, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 0,
        "payment_amount": 5,
        "delta": 5,
    }]


def test_batch_only_issue_is_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_batch", "issues": [42], "total": 10},
            {"type": "payment", "issue": 42, "amount": 10, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["skipped_batch_only_issues"] == 1


def test_batch_issue_with_explicit_escrow_uses_explicit_amount(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_batch", "issues": [42], "total": 10},
            {"type": "escrow_create", "issue": 42, "amount": 5},
            {"type": "payment", "issue": 42, "amount": 6, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 5,
        "payment_amount": 6,
        "delta": 1,
    }]


def test_single_payment_larger_than_escrow_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 12, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 10,
        "payment_amount": 12,
        "delta": 2,
    }]


def test_split_payments_exceed_escrow_fails_with_total_paid(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 6, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 5, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 10,
        "payment_amount": 11,
        "delta": 1,
    }]


def test_individual_violation_takes_precedence_over_split_summary(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 3, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 12, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 10,
        "payment_amount": 12,
        "delta": 2,
    }]


def test_issue_ids_are_normalized_across_str_and_int(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": "42", "amount": 8},
            {"type": "payment", "issue": 42, "amount": 8, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"


def test_op_based_escrow_create_counts(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"op": "escrow_create", "issue": 42, "amount": 7, "from": "agent0@system"},
            {"type": "payment", "issue": 42, "amount": 7, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["escrow_create_events_scanned"] == 1


def test_malformed_payment_is_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": "oops", "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 4, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["payment_events_scanned"] == 2
    assert report["stats"]["skipped_malformed_payments"] == 1


def test_malformed_escrow_is_skipped_and_can_cause_missing_violation(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": "oops"},
            {"type": "payment", "issue": 42, "amount": 4, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["skipped_malformed_escrows"] == 1
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 0,
        "payment_amount": 4,
        "delta": 4,
    }]


def test_invalid_json_and_non_object_rows_are_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 5},
            "not-json",
            7,
            {"type": "payment", "issue": 42, "amount": 5, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["skipped_invalid_json_lines"] == 1
    assert report["stats"]["skipped_non_object_events"] == 1


def test_zero_and_negative_payments_are_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 0, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": -1, "agent": "bob@test"},
            {"type": "payment", "issue": 42, "amount": 10, "agent": "carol@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["skipped_malformed_payments"] == 2


def test_negative_escrow_is_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": -5},
            {"type": "payment", "issue": 42, "amount": 2, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["skipped_malformed_escrows"] == 1
    assert report["violations"] == [{
        "issue": "42",
        "escrow_amount": 0,
        "payment_amount": 2,
        "delta": 2,
    }]


def test_multiple_issue_violations_are_sorted_by_issue(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 12, "amount": 4, "agent": "alice@test"},
            {"type": "payment", "issue": 5, "amount": 2, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert [item["issue"] for item in report["violations"]] == ["5", "12"]


def test_main_prints_json_and_returns_zero_on_pass(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 10, "agent": "alice@test"},
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_main_prints_json_and_returns_one_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 42, "amount": 2, "agent": "alice@test"},
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["stats"]["violations"] == 1
