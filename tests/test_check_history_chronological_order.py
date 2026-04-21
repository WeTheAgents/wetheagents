from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_chronological_order import main, run_check


def _history_dir(root: Path) -> Path:
    path = root / "ledger" / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        lines.append(event if isinstance(event, str) else json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_passes_when_history_directory_is_missing(temp_repo: Path) -> None:
    root = temp_repo / "no-history"
    root.mkdir()

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"] == {
        "files_scanned": 0,
        "events_checked": 0,
        "violations_found": 0,
    }


def test_passes_when_history_directory_is_empty(temp_repo: Path) -> None:
    history_dir = temp_repo / "ledger" / "history"
    for existing in history_dir.glob("*.jsonl"):
        existing.unlink()

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["files_scanned"] == 0


def test_passes_for_single_ordered_file(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"ts": "2026-04-01T09:00:00Z"},
            {"ts": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["files_scanned"] == 1
    assert report["stats"]["events_checked"] == 2


def test_equal_adjacent_timestamps_are_allowed(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_detects_single_out_of_order_pair(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00Z"},
            {"timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"] == [
        {
            "file": "2026-04-01.jsonl",
            "index": 2,
            "ts_prev": "2026-04-01T10:00:00Z",
            "ts_curr": "2026-04-01T09:00:00Z",
        }
    ]
    assert report["stats"]["violations_found"] == 1


def test_reports_multiple_pairs_in_one_file(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00Z"},
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T08:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"] == [
        {
            "file": "2026-04-01.jsonl",
            "index": 2,
            "ts_prev": "2026-04-01T10:00:00Z",
            "ts_curr": "2026-04-01T09:00:00Z",
        },
        {
            "file": "2026-04-01.jsonl",
            "index": 3,
            "ts_prev": "2026-04-01T09:00:00Z",
            "ts_curr": "2026-04-01T08:00:00Z",
        },
    ]


def test_accumulates_stats_across_multiple_files(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )
    _write_jsonl(
        history_dir / "2026-04-02.jsonl",
        [
            {"timestamp": "2026-04-02T11:00:00Z"},
            {"timestamp": "2026-04-02T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["stats"] == {
        "files_scanned": 2,
        "events_checked": 4,
        "violations_found": 1,
    }


def test_blank_lines_do_not_affect_checked_index(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    (history_dir / "2026-04-01.jsonl").write_text(
        '\n{"timestamp": "2026-04-01T10:00:00Z"}\n'
        '\n{"timestamp": "2026-04-01T09:00:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(temp_repo)

    assert report["violations"][0]["index"] == 2


def test_uses_ts_field_when_present(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"op": "escrow_create", "ts": "2026-04-01T10:00:00Z"},
            {"op": "payment", "ts": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["ts_prev"] == "2026-04-01T10:00:00Z"


def test_uses_created_at_when_timestamp_missing(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"created_at": "2026-04-01T10:00:00Z"},
            {"created_at": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["index"] == 2


def test_prefers_started_at_over_event_at(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"started_at": "2026-04-01T10:00:00Z", "event_at": "2026-04-01T08:00:00Z"},
            {"started_at": "2026-04-01T09:00:00Z", "event_at": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"] == [
        {
            "file": "2026-04-01.jsonl",
            "index": 2,
            "ts_prev": "2026-04-01T10:00:00Z",
            "ts_curr": "2026-04-01T09:00:00Z",
        }
    ]


def test_falls_back_to_event_at_when_needed(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"event_at": "2026-04-01T10:00:00Z"},
            {"event_at": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["index"] == 2


def test_falls_back_to_at_when_needed(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"at": "2026-04-01T10:00:00Z"},
            {"at": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["ts_curr"] == "2026-04-01T09:00:00Z"


def test_normalizes_offsets_before_comparison(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00+02:00"},
            {"timestamp": "2026-04-01T08:30:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_treats_naive_datetimes_as_utc(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00"},
            {"timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["ts_prev"] == "2026-04-01T10:00:00Z"


def test_repairs_legacy_invalid_escape_sequences(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    (history_dir / "2026-04-01.jsonl").write_text(
        '{"timestamp": "2026-04-01T09:00:00Z", "note": "11 - \\!3"}\n'
        '{"timestamp": "2026-04-01T10:00:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_skips_irreparable_malformed_json_lines(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    (history_dir / "2026-04-01.jsonl").write_text(
        '{"timestamp": "2026-04-01T09:00:00Z"}\n'
        '{"timestamp": "broken"\n'
        '{"timestamp": "2026-04-01T10:00:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_skips_non_object_json_lines(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            "[]",
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_skips_entries_without_parseable_timestamp(temp_repo: Path) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "not-a-timestamp"},
            {"note": "missing timestamp"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_main_returns_zero_and_prints_json_on_success(
    temp_repo: Path,
    capsys,
) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    exit_code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["stats"]["violations_found"] == 0


def test_main_returns_nonzero_and_prints_json_on_failure(
    temp_repo: Path,
    capsys,
) -> None:
    history_dir = _history_dir(temp_repo)
    _write_jsonl(
        history_dir / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00Z"},
            {"timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    exit_code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["violations"][0]["file"] == "2026-04-01.jsonl"
