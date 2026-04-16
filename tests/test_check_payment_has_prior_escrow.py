from __future__ import annotations

import json
from pathlib import Path

from scripts.check_payment_has_prior_escrow import main, run_check


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_root(root: Path) -> Path:
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    return root


def test_passes_when_payment_has_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 42, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["checked"] == 1
    assert report["violations"] == []
    assert report["warnings"] == []


def test_fails_when_keyed_payment_has_no_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["checked"] == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 42
    assert report["violations"][0]["reason"] == "payment_without_prior_escrow"


def test_warns_for_keyless_payment_without_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["reason"] == "keyless_payment_without_prior_escrow"


def test_warns_when_payment_predates_first_escrow_event(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "issue": 7, "agent": "alice@test", "idem_key": "payment|7|alice@test", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["reason"] == "payment_predates_first_escrow_event"


def test_warns_when_payment_predates_first_escrow_for_mechanic(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "mechanic": "standard", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "mechanic": "progressive", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow", "issue": 99, "mechanic": "progressive", "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["reason"] == "payment_predates_first_escrow_for_mechanic"


def test_escrow_batch_counts_as_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow_batch", "issues": [4, 5, 6], "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 5, "agent": "alice@test", "idem_key": "payment|5|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["warnings"] == []


def test_escrow_create_counts_as_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "mechanic": "best_x", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["warnings"] == []


def test_uses_timestamp_sort_across_files(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-02.jsonl",
        [
            {"type": "escrow", "issue": 42, "timestamp": "2026-01-01T00:00:00Z"},
        ],
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["warnings"] == []


def test_later_escrow_does_not_satisfy_prior_requirement(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "escrow", "issue": 42, "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 42


def test_warns_for_missing_payment_timestamp(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["reason"] == "payment_missing_timestamp_no_prior_escrow"


def test_skips_blank_and_invalid_jsonl_lines(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 42, "timestamp": "2026-01-01T00:00:00Z"},
            "",
            "not-json",
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["checked"] == 1


def test_checked_counts_only_payment_events(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 42, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "escrow_return", "issue": 42, "timestamp": "2026-01-01T00:30:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
            {"type": "payment", "issue": 99, "agent": "bob@test", "timestamp": "2026-01-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["checked"] == 2


def test_main_returns_nonzero_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"type": "escrow", "issue": 10, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "idem_key": "payment|42|alice@test", "timestamp": "2026-01-01T01:00:00Z"},
        ],
    )

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
