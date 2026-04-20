"""Tests for scripts/check_history_file_gaps.py."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from scripts.check_history_file_gaps import _collect_timestamp_dates, main, run_check


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _touch_history(root: Path, *dates: str) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for date_value in dates:
        (history_dir / f"{date_value}.jsonl").write_text("", encoding="utf-8")


@pytest.fixture
def temp_root() -> Path:
    root = Path(".test_runs") / f"history_gap_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    yield root

    shutil.rmtree(root, ignore_errors=True)


def test_collect_timestamp_dates_ignores_free_text_dates() -> None:
    payload = {
        "accepted_at": "2026-04-15T07:04:43Z",
        "evidence": "PR merged on 2026-04-15 with 11/11 tests passing",
        "nested": [
            {"created_at": "2026-04-16T20:15:36Z"},
            {"note": "2026-04-17T00:00:00Z in prose only, not a bare timestamp"},
        ],
    }

    assert _collect_timestamp_dates(payload) == {"2026-04-15", "2026-04-16"}


def test_run_check_no_timestamps_passes(temp_root: Path) -> None:
    root = temp_root
    _write_json(root / "ledger" / "balances.json", {"agents": {"alice@test": {"balance": 5}}})
    _write_json(root / "ledger" / "escrows.json", {"active": {"42": {"amount": 10}}})
    _write_json(root / "ledger" / "trajectory_mints.json", {"mints": [{"trajectory": "T1", "slot": 1}]})
    _write_json(root / "ledger" / "idem_keys.json", {"keys": {"abc": True}})

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == []
    assert report["missing_dates"] == []


def test_run_check_all_dates_have_files_passes(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {"last_updated": "2026-04-15T06:36:31Z"},
    )
    _write_json(
        root / "ledger" / "escrows.json",
        {"active": {"42": {"created_at": "2026-04-16T13:00:00Z"}}},
    )
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {"mints": [{"accepted_at": "2026-04-15T07:47:32Z"}]},
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"escrow_create_42_gauntlet": "2026-04-16T20:24:48Z"},
    )
    _touch_history(root, "2026-04-15", "2026-04-16")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2026-04-15", "2026-04-16"]
    assert report["missing_dates"] == []


def test_run_check_one_date_missing_fails(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {"last_updated": "2026-04-15T06:36:31Z"},
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"escrow_create_42_gauntlet": "2026-04-16T20:24:48Z"},
    )
    _touch_history(root, "2026-04-15")

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["missing_dates"] == ["2026-04-16"]


def test_run_check_absent_metadata_files_passes(temp_root: Path) -> None:
    report = run_check(temp_root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == []
    assert report["missing_dates"] == []


def test_run_check_future_date_passes(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {"mints": [{"accepted_at": "2099-01-01T00:00:00Z"}]},
    )
    _touch_history(root, "2099-01-01")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2099-01-01"]


def test_run_check_deduplicates_shared_dates(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {"last_updated": "2026-04-15T06:36:31Z"},
    )
    _write_json(
        root / "ledger" / "escrows.json",
        {"active": {"42": {"created_at": "2026-04-15T07:04:43Z"}}},
    )
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {"mints": [{"accepted_at": "2026-04-15T07:47:32Z"}]},
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"escrow_create_42_gauntlet": "2026-04-15T20:24:48Z"},
    )
    _touch_history(root, "2026-04-15")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2026-04-15"]


def test_run_check_accepts_fractional_offset_timestamps(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"escrow_return|494|agent0@system": "2026-04-15T06:31:04.418025+00:00"},
    )
    _touch_history(root, "2026-04-15")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2026-04-15"]


def test_run_check_reads_nested_idem_key_timestamps(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "idem_keys.json",
        {
            "keys": {
                "hash-1": {
                    "action": "payment",
                    "timestamp": "2026-04-11T00:29:39Z",
                }
            }
        },
    )
    _touch_history(root, "2026-04-11")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2026-04-11"]


def test_run_check_preserves_recorded_offset_date(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"offset-example": "2026-04-15T00:30:00+02:00"},
    )
    _touch_history(root, "2026-04-15")

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == ["2026-04-15"]


def test_run_check_missing_history_dir_fails_when_dates_exist(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "escrows.json",
        {"active": {"42": {"created_at": "2026-04-18T20:13:23Z"}}},
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["missing_dates"] == ["2026-04-18"]


def test_run_check_ignores_invalid_timestamp_strings(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {
            "last_updated": "2026-04-15",
            "agents": {"alice@test": {"registered_at": "2026-04-15T99:99:99Z"}},
        },
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["dates_checked"] == []


def test_run_check_missing_dates_are_sorted(temp_root: Path) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {"last_updated": "2026-04-17T04:02:46Z"},
    )
    _write_json(
        root / "ledger" / "escrows.json",
        {"active": {"42": {"created_at": "2026-04-15T07:04:43Z"}}},
    )
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {"mints": [{"accepted_at": "2026-04-16T12:14:02Z"}]},
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["missing_dates"] == ["2026-04-15", "2026-04-16", "2026-04-17"]


def test_main_prints_json_and_returns_exit_code(temp_root: Path, capsys) -> None:
    root = temp_root
    _write_json(
        root / "ledger" / "balances.json",
        {"last_updated": "2026-04-15T06:36:31Z"},
    )
    _touch_history(root, "2026-04-15")

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert payload["dates_checked"] == ["2026-04-15"]
