from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_chronological_order import main, run_check


def _make_root(root: Path) -> Path:
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_passes_for_ordered_file_and_prior_escrow_create(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_fails_when_timestamp_moves_backwards_within_file(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:10:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any(v["check"] == "within_file_non_decreasing_timestamps" for v in report["violations"])


def test_equal_timestamps_within_file_are_allowed(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"


def test_cross_file_earlier_escrow_create_passes_even_if_filename_is_later(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-02.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
        ],
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"


def test_payment_without_any_matching_escrow_is_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "payment", "issue": 7, "agent": "alice@test", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    cross_check = next(check for check in report["checks"] if check["name"] == "escrow_create_precedes_payment")
    assert report["status"] == "PASS"
    assert cross_check["payments_skipped_without_escrow"] == 1


def test_payment_with_missing_issue_fails_cross_file_check(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any(v.get("reason") == "payment_missing_issue" for v in report["violations"])


def test_payment_before_same_issue_escrow_create_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ],
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-02.jsonl",
        [
            {"type": "escrow_create", "issue": 10, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T02:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any(v.get("reason") == "escrow_after_payment" for v in report["violations"])


def test_created_at_alias_is_used_for_escrow_create(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "created_at": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"


def test_legacy_escrow_counts_as_prior_escrow(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"


def test_legacy_invalid_escape_is_repaired_for_loading(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    path = root / "ledger" / "history" / "2026-04-01.jsonl"
    path.write_text(
        '{"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z", "note": "11 - \\!3"}\n'
        '{"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T00:05:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(root)

    assert report["status"] == "PASS"


def test_irreparable_malformed_json_fails_parseability_check(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    path = root / "ledger" / "history" / "2026-04-01.jsonl"
    path.write_text(
        '{"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"}\n'
        '{"type": "payment", "issue": 42,\n',
        encoding="utf-8",
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any(v["check"] == "history_parseability" for v in report["violations"])


def test_missing_timestamp_field_fails_parseability_check(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any("missing timestamp field" in v["detail"] for v in report["violations"])


def test_non_object_json_line_fails_parseability_check(temp_repo: Path) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
            "[]",
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert any("expected JSON object" in v["detail"] for v in report["violations"])


def test_missing_history_directory_fails(temp_repo: Path) -> None:
    root = temp_repo / "no-history-root"
    root.mkdir()
    report = run_check(root)

    assert report["status"] == "FAIL"
    assert "history directory not found" in report["summary"]


def test_main_returns_nonzero_on_failure(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {"type": "payment", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ],
    )
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-02.jsonl",
        [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T02:00:00Z"},
        ],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
