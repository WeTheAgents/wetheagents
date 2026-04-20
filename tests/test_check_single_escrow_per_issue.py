from __future__ import annotations

import json
from pathlib import Path

from scripts.check_single_escrow_per_issue import main, run_check


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


def test_passes_when_history_is_empty(temp_repo: Path) -> None:
    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["history_events_scanned"] == 0


def test_fails_when_issue_opens_twice_before_closing(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["issues_with_multiple_active_escrows"] == 1
    assert report["violations"] == [{
        "issue": 42,
        "open_escrows": 2,
        "peak_open_escrows": 2,
        "file": "2026-04-01.jsonl",
        "line": 2,
        "timestamp": "2026-04-01T01:00:00Z",
        "event_type": "escrow_create",
        "reason": "multiple_active_escrows",
    }]


def test_passes_when_issue_reopens_after_accept(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 7, "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "accept", "issue": 7, "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "escrow_create", "issue": 7, "timestamp": "2026-04-01T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_payment_closes_open_count(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-02.jsonl": [
            {"type": "escrow_create", "issue": 9, "timestamp": "2026-04-02T00:00:00Z"},
            {"type": "payment", "issue": 9, "timestamp": "2026-04-02T01:00:00Z"},
            {"type": "escrow_create", "issue": 9, "timestamp": "2026-04-02T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["closing_events_scanned"] == 1


def test_escrow_return_closes_open_count(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-03.jsonl": [
            {"type": "escrow_create", "issue": 10, "timestamp": "2026-04-03T00:00:00Z"},
            {"type": "escrow_return", "issue": 10, "timestamp": "2026-04-03T01:00:00Z"},
            {"type": "escrow_create", "issue": 10, "timestamp": "2026-04-03T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["closing_events_scanned"] == 1


def test_timestamp_sorting_applies_across_files(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-02.jsonl": [
            {"type": "escrow_create", "issue": 12, "timestamp": "2026-04-01T00:00:00Z"},
        ],
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 12, "timestamp": "2026-04-01T01:00:00Z"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["line"] == 1
    assert report["violations"][0]["file"] == "2026-04-01.jsonl"


def test_string_issue_values_are_normalized(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-04.jsonl": [
            {"type": "escrow_create", "issue": " 42 ", "timestamp": "2026-04-04T00:00:00Z"},
            {"type": "escrow_create", "issue": 42, "timestamp": "2026-04-04T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["issue"] == 42


def test_invalid_issue_values_are_ignored(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-05.jsonl": [
            {"type": "escrow_create", "issue": "not-a-number", "timestamp": "2026-04-05T00:00:00Z"},
            {"type": "escrow_create", "issue": "", "timestamp": "2026-04-05T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["escrow_creates_scanned"] == 0


def test_malformed_lines_are_skipped(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-06.jsonl": [
            {"type": "escrow_create", "issue": 20, "timestamp": "2026-04-06T00:00:00Z"},
            "not-json",
            {"type": "escrow_create", "issue": 20, "timestamp": "2026-04-06T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["malformed_lines_skipped"] == 1


def test_invalid_escape_lines_are_repaired(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-07.jsonl": [
            '{"type":"escrow_create","issue":30,"timestamp":"2026-04-07T00:00:00Z","note":"bad \\\\! escape"}',
            {"type": "escrow_create", "issue": 30, "timestamp": "2026-04-07T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["malformed_lines_skipped"] == 0


def test_close_events_clamp_count_at_zero(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-08.jsonl": [
            {"type": "payment", "issue": 50, "timestamp": "2026-04-08T00:00:00Z"},
            {"type": "escrow_create", "issue": 50, "timestamp": "2026-04-08T01:00:00Z"},
            {"type": "escrow_create", "issue": 50, "timestamp": "2026-04-08T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["open_escrows"] == 2


def test_supports_event_and_op_fields_and_ts_created_at_timestamps(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-10.jsonl": [
            {"op": "escrow_create", "issue": 60, "created_at": "2026-04-10T00:00:00Z"},
        ],
        "2026-04-09.jsonl": [
            {"event": "escrow_create", "issue": 60, "ts": "2026-04-10T01:00:00Z"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["timestamp"] == "2026-04-10T01:00:00Z"


def test_peak_open_escrows_tracks_additional_duplicates(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-11.jsonl": [
            {"type": "escrow_create", "issue": 77, "timestamp": "2026-04-11T00:00:00Z"},
            {"type": "escrow_create", "issue": 77, "timestamp": "2026-04-11T01:00:00Z"},
            {"type": "escrow_create", "issue": 77, "timestamp": "2026-04-11T02:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["peak_open_escrows"] == 3


def test_main_returns_nonzero_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-12.jsonl": [
            {"type": "escrow_create", "issue": 88, "timestamp": "2026-04-12T00:00:00Z"},
            {"type": "escrow_create", "issue": 88, "timestamp": "2026-04-12T01:00:00Z"},
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
