from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_file_date_consistency import main, run_check


def _history_dir(root: Path) -> Path:
    path = root / "ledger" / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines = [e if isinstance(e, str) else json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Filename / structural checks
# ---------------------------------------------------------------------------


def test_passes_when_history_directory_missing(tmp_path: Path) -> None:
    root = tmp_path / "no-history"
    root.mkdir()
    report = run_check(root)
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"] == {"files_scanned": 0, "events_checked": 0, "violations_found": 0}


def test_passes_for_empty_history_directory(temp_repo: Path) -> None:
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["stats"]["files_scanned"] == 0


def test_invalid_filename_no_date_pattern(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "not-a-date.jsonl").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert any(
        v["violation_type"] == "invalid_filename" and v["file"] == "not-a-date.jsonl"
        for v in report["violations"]
    )


def test_invalid_filename_extra_suffix(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "2026-04-01.jsonl.bak").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["violation_type"] == "invalid_filename"


def test_invalid_calendar_date_in_filename(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "2026-13-01.jsonl").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert any(
        v["violation_type"] == "invalid_date" and "2026-13-01" in v["file"]
        for v in report["violations"]
    )


def test_invalid_calendar_date_day_32(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "2026-01-32.jsonl").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["violation_type"] == "invalid_date"


# ---------------------------------------------------------------------------
# Empty file and valid-events happy paths
# ---------------------------------------------------------------------------


def test_empty_file_passes(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "2026-04-01.jsonl").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 0


def test_all_valid_events_same_date(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T12:00:00Z"},
            {"timestamp": "2026-04-01T23:59:59Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 3
    assert report["stats"]["violations_found"] == 0


# ---------------------------------------------------------------------------
# Date-mismatch violations
# ---------------------------------------------------------------------------


def test_event_2_days_off_is_violation(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-03T10:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violations"][0]
    assert v["violation_type"] == "date_mismatch"
    assert v["file"] == "2026-04-01.jsonl"
    assert v["days_off"] == 2


def test_event_many_days_off_is_violation(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-03-15T10:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["violation_type"] == "date_mismatch"
    assert report["violations"][0]["days_off"] == 17


def test_event_exactly_1_day_ahead_passes(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-02T00:01:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_event_exactly_1_day_behind_passes(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-03-31T23:59:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_timezone_edge_case_from_spec(temp_repo: Path) -> None:
    """2026-04-01T23:59Z and 2026-04-02T00:01Z both in 2026-04-01.jsonl → pass."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T23:59:00Z"},
            {"timestamp": "2026-04-02T00:01:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


# ---------------------------------------------------------------------------
# Chronological-order violations
# ---------------------------------------------------------------------------


def test_reverse_chronological_order_is_violation(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T12:00:00Z"},
            {"timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violations"][0]
    assert v["violation_type"] == "out_of_order"
    assert v["file"] == "2026-04-01.jsonl"
    assert v["ts_prev"] == "2026-04-01T12:00:00Z"
    assert v["ts_curr"] == "2026-04-01T09:00:00Z"


def test_equal_timestamps_are_allowed(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:00Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_order_violation_index_is_correct(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T11:00:00Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["violations"][0]["index"] == 3


# ---------------------------------------------------------------------------
# Both violation types in the same file
# ---------------------------------------------------------------------------


def test_date_mismatch_and_out_of_order_both_reported(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-05T12:00:00Z"},  # date_mismatch (4 days off)
            {"timestamp": "2026-04-05T10:00:00Z"},  # out_of_order
        ],
    )

    report = run_check(temp_repo)

    types = {v["violation_type"] for v in report["violations"]}
    assert "date_mismatch" in types
    assert "out_of_order" in types


# ---------------------------------------------------------------------------
# Stats accumulation across multiple files
# ---------------------------------------------------------------------------


def test_stats_accumulate_across_files(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )
    _write_jsonl(
        hd / "2026-04-02.jsonl",
        [{"timestamp": "2026-04-02T11:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["stats"]["files_scanned"] == 2
    assert report["stats"]["events_checked"] == 3
    assert report["status"] == "PASS"


# ---------------------------------------------------------------------------
# Robustness: malformed / missing timestamp lines
# ---------------------------------------------------------------------------


def test_skips_malformed_json_lines(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    (hd / "2026-04-01.jsonl").write_text(
        '{"timestamp": "2026-04-01T09:00:00Z"}\n'
        '{"timestamp": "broken"\n'
        '{"timestamp": "2026-04-01T10:00:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_skips_entries_without_timestamp(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T09:00:00Z"},
            {"note": "no timestamp here"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2


def test_normalizes_timezone_offsets(temp_repo: Path) -> None:
    hd = _history_dir(temp_repo)
    # +02:00 offset → UTC 08:00, still on 2026-04-01 → OK
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-01T10:00:00+02:00"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------


def test_main_exits_zero_on_clean_repo(temp_repo: Path, capsys) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-01T12:00:00Z"}],
    )

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "PASS"


def test_main_exits_one_on_invalid_filename(temp_repo: Path, capsys) -> None:
    hd = _history_dir(temp_repo)
    (hd / "badname.jsonl").write_text("", encoding="utf-8")

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["status"] == "FAIL"


def test_main_exits_one_on_date_mismatch(temp_repo: Path, capsys) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-10T00:00:00Z"}],
    )

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["violations"][0]["violation_type"] == "date_mismatch"


def test_main_exits_one_on_out_of_order(temp_repo: Path, capsys) -> None:
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T15:00:00Z"},
            {"timestamp": "2026-04-01T08:00:00Z"},
        ],
    )

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["violations"][0]["violation_type"] == "out_of_order"
