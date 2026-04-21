from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_history_event_idem_keys import (
    load_idem_keys,
    main,
    run_check,
    scan_history,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "check_history_event_idem_keys.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, filename: str, *events: object) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) if not isinstance(e, str) else e for e in events]
    text = "\n".join(lines)
    if text:
        text += "\n"
    (history_dir / filename).write_text(text, encoding="utf-8")


def _make_repo(
    root: Path,
    *,
    idem_payload: object | None = None,
) -> Path:
    if idem_payload is not None:
        _write_json(root / "ledger" / "idem_keys.json", idem_payload)
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# load_idem_keys tests
# ---------------------------------------------------------------------------


def test_load_idem_keys_returns_empty_when_file_missing(temp_repo: Path) -> None:
    keys = load_idem_keys(temp_repo / "ledger" / "nonexistent.json")
    assert keys == set()


def test_load_idem_keys_reads_top_level_keys(temp_repo: Path) -> None:
    _make_repo(temp_repo, idem_payload={"accept|5|alice@test": True, "escrow_return|10": True})
    keys = load_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert "accept|5|alice@test" in keys
    assert "escrow_return|10" in keys


def test_load_idem_keys_reads_nested_keys_block(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={
            "version": 1,
            "keys": {"payment|20|bob@test": {"action": "payment"}},
        },
    )
    keys = load_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert "payment|20|bob@test" in keys


def test_load_idem_keys_skips_reserved_fields(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={"version": 1, "keys": {}, "accept|1|agent@test": True},
    )
    keys = load_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert "version" not in keys
    assert "keys" not in keys
    assert "accept|1|agent@test" in keys


def test_load_idem_keys_merges_top_level_and_nested(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={
            "top_key": True,
            "keys": {"nested_key": True},
            "version": 1,
        },
    )
    keys = load_idem_keys(temp_repo / "ledger" / "idem_keys.json")
    assert "top_key" in keys
    assert "nested_key" in keys
    assert len(keys) == 2


# ---------------------------------------------------------------------------
# scan_history tests
# ---------------------------------------------------------------------------


def test_scan_history_ignores_events_without_idem_key(temp_repo: Path) -> None:
    _make_repo(temp_repo)
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "payment", "agent": "alice@test", "amount": 10, "timestamp": "2026-03-01T00:00:00Z"},
    )
    events = scan_history(temp_repo / "ledger" / "history")
    assert events == []


def test_scan_history_collects_events_with_idem_key(temp_repo: Path) -> None:
    _make_repo(temp_repo)
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {
            "type": "payment",
            "agent": "alice@test",
            "amount": 10,
            "timestamp": "2026-03-01T00:00:00Z",
            "idem_key": "payment|100|alice@test",
        },
    )
    events = scan_history(temp_repo / "ledger" / "history")
    assert len(events) == 1
    assert events[0]["idem_key"] == "payment|100|alice@test"
    assert events[0]["op"] == "payment"
    assert events[0]["file"] == "2026-03-01.jsonl"


def test_scan_history_returns_empty_when_dir_missing(temp_repo: Path) -> None:
    events = scan_history(temp_repo / "ledger" / "nonexistent")
    assert events == []


def test_scan_history_skips_blank_lines(temp_repo: Path) -> None:
    _make_repo(temp_repo)
    history_dir = temp_repo / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-03-01.jsonl").write_text(
        '\n\n{"type":"payment","idem_key":"payment|1|a@test","timestamp":""}\n\n',
        encoding="utf-8",
    )
    events = scan_history(history_dir)
    assert len(events) == 1


def test_scan_history_skips_malformed_lines(temp_repo: Path) -> None:
    _make_repo(temp_repo)
    history_dir = temp_repo / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-03-01.jsonl").write_text(
        'not-json\n{"type":"payment","idem_key":"pay|1|a@test","timestamp":""}\n',
        encoding="utf-8",
    )
    events = scan_history(history_dir)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# run_check tests
# ---------------------------------------------------------------------------


def test_run_check_passes_when_all_idem_keys_registered(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={"payment|100|alice@test": True},
    )
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {
            "type": "payment",
            "idem_key": "payment|100|alice@test",
            "timestamp": "2026-03-01T00:00:00Z",
        },
    )
    report, exit_code = run_check(temp_repo)
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_run_check_fails_when_idem_key_not_in_registry(temp_repo: Path) -> None:
    _make_repo(temp_repo, idem_payload={})
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {
            "type": "escrow_return",
            "idem_key": "escrow_return|200",
            "timestamp": "2026-03-01T00:00:00Z",
        },
    )
    report, exit_code = run_check(temp_repo)
    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["idem_key"] == "escrow_return|200"


def test_run_check_passes_with_empty_history(temp_repo: Path) -> None:
    _make_repo(temp_repo, idem_payload={})
    report, exit_code = run_check(temp_repo)
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["stats"]["events_scanned"] == 0
    assert report["stats"]["idem_keys_checked"] == 0
    assert report["stats"]["violations_found"] == 0


def test_run_check_counts_stats_correctly(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={"accept|1|alice@test": True},
    )
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "registration", "agent": "alice@test", "timestamp": "2026-03-01T00:00:00Z"},
        {"type": "payment", "idem_key": "accept|1|alice@test", "timestamp": "2026-03-01T01:00:00Z"},
        {"type": "escrow_return", "idem_key": "escrow_return|99", "timestamp": "2026-03-01T02:00:00Z"},
    )
    report, exit_code = run_check(temp_repo)
    assert report["stats"]["events_scanned"] == 3
    assert report["stats"]["idem_keys_checked"] == 2
    assert report["stats"]["violations_found"] == 1


def test_run_check_scans_multiple_history_files(temp_repo: Path) -> None:
    _make_repo(
        temp_repo,
        idem_payload={"accept|1|alice@test": True},
    )
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "payment", "idem_key": "accept|1|alice@test", "timestamp": "2026-03-01T00:00:00Z"},
    )
    _write_history(
        temp_repo,
        "2026-03-02.jsonl",
        {"type": "escrow_return", "idem_key": "escrow_return|55", "timestamp": "2026-03-02T00:00:00Z"},
    )
    report, exit_code = run_check(temp_repo)
    assert exit_code == 1
    assert report["stats"]["idem_keys_checked"] == 2
    assert report["stats"]["violations_found"] == 1
    assert report["violations"][0]["file"] == "2026-03-02.jsonl"


def test_run_check_violation_includes_op_ts_file(temp_repo: Path) -> None:
    _make_repo(temp_repo, idem_payload={})
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        {
            "type": "escrow_return",
            "idem_key": "escrow_return|777",
            "timestamp": "2026-04-01T12:00:00Z",
        },
    )
    report, _ = run_check(temp_repo)
    v = report["violations"][0]
    assert v["idem_key"] == "escrow_return|777"
    assert v["op"] == "escrow_return"
    assert v["ts"] == "2026-04-01T12:00:00Z"
    assert v["file"] == "2026-04-01.jsonl"


def test_run_check_passes_when_no_idem_keys_file_and_no_history_idem_events(temp_repo: Path) -> None:
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "mint", "agent": "alice@test", "amount": 5, "timestamp": "2026-03-01T00:00:00Z"},
    )
    report, exit_code = run_check(temp_repo)
    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_fails_when_no_idem_keys_file_but_history_has_idem_events(temp_repo: Path) -> None:
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "payment", "idem_key": "payment|1|x@test", "timestamp": "2026-03-01T00:00:00Z"},
    )
    report, exit_code = run_check(temp_repo)
    assert exit_code == 1
    assert report["status"] == "FAIL"


# ---------------------------------------------------------------------------
# CLI / main() tests
# ---------------------------------------------------------------------------


def test_main_exits_0_on_clean_repo(temp_repo: Path, capsys: pytest.CaptureFixture) -> None:
    _make_repo(
        temp_repo,
        idem_payload={"payment|1|alice@test": True},
    )
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "payment", "idem_key": "payment|1|alice@test", "timestamp": "2026-03-01T00:00:00Z"},
    )
    exit_code = main(["--root", str(temp_repo)])
    assert exit_code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "PASS"


def test_main_exits_1_on_violations(temp_repo: Path, capsys: pytest.CaptureFixture) -> None:
    _make_repo(temp_repo, idem_payload={})
    _write_history(
        temp_repo,
        "2026-03-01.jsonl",
        {"type": "payment", "idem_key": "payment|1|alice@test", "timestamp": "2026-03-01T00:00:00Z"},
    )
    exit_code = main(["--root", str(temp_repo)])
    assert exit_code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "FAIL"
    assert data["stats"]["violations_found"] == 1


def test_script_invocable_as_subprocess(temp_repo: Path) -> None:
    _make_repo(temp_repo, idem_payload={})
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert result.returncode == 0
    assert data["status"] == "PASS"
    assert "violations" in data
    assert "stats" in data
