from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_escrow_age_report import build_report, classify_age, run_check

_NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_ago: float) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _escrows(entries: dict[str, dict]) -> dict:
    return {"version": 1, "active": entries}


def _write_ledger(root: Path, escrows: dict) -> Path:
    ledger_dir = root / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "escrows.json").write_text(
        json.dumps(escrows, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def test_empty_ledger_is_pass() -> None:
    report = build_report(_escrows({}), now=_NOW)

    assert report["status"] == "PASS"
    assert report["escrows"] == []
    assert report["summary"] == {"fresh": 0, "aging": 0, "stale": 0, "frozen": 0}


def test_all_fresh_escrows_are_pass() -> None:
    report = build_report(
        _escrows(
            {
                "101": {"created_at": _ts(0)},
                "102": {"created_at": _ts(6)},
            }
        ),
        now=_NOW,
    )

    assert report["status"] == "PASS"
    assert [entry["classification"] for entry in report["escrows"]] == ["FRESH", "FRESH"]
    assert report["summary"]["fresh"] == 2


def test_aging_escrow_is_reported_without_warning() -> None:
    report = build_report(_escrows({"201": {"created_at": _ts(7)}}), now=_NOW)

    assert report["status"] == "PASS"
    assert report["escrows"][0]["age_days"] == 7
    assert report["escrows"][0]["classification"] == "AGING"
    assert report["summary"] == {"fresh": 0, "aging": 1, "stale": 0, "frozen": 0}


def test_stale_escrow_sets_warn_status() -> None:
    report = build_report(_escrows({"301": {"created_at": _ts(20)}}), now=_NOW)

    assert report["status"] == "WARN"
    assert report["escrows"][0]["classification"] == "STALE"
    assert report["checks"][0]["status"] == "WARN"


def test_frozen_escrow_sets_fail_status() -> None:
    report = build_report(_escrows({"401": {"created_at": _ts(45)}}), now=_NOW)

    assert report["status"] == "FAIL"
    assert report["escrows"][0]["classification"] == "FROZEN"
    assert report["summary"]["frozen"] == 1


def test_mixed_escrows_count_each_bucket() -> None:
    report = build_report(
        _escrows(
            {
                "1": {"created_at": _ts(1)},
                "2": {"created_at": _ts(8)},
                "3": {"created_at": _ts(14)},
                "4": {"created_at": _ts(30)},
            }
        ),
        now=_NOW,
    )

    assert report["status"] == "FAIL"
    assert report["summary"] == {"fresh": 1, "aging": 1, "stale": 1, "frozen": 1}
    assert [entry["issue"] for entry in report["escrows"]] == [1, 2, 3, 4]


def test_exactly_14_days_is_stale_boundary() -> None:
    assert classify_age(14) == "STALE"


def test_exactly_30_days_is_frozen_boundary() -> None:
    assert classify_age(30) == "FROZEN"


def test_run_check_reads_repo_files() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    temp_dir = repo_root / "tmp_check_escrow_age_report"
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        root = _write_ledger(
            temp_dir,
            _escrows({"501": {"created_at": _ts(13)}}),
        )

        report = run_check(root, now=_NOW)

        assert report["status"] == "PASS"
        assert report["escrows"][0]["classification"] == "AGING"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_cli_real_repo_exits_cleanly() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "check_escrow_age_report.py"

    result = subprocess.run(
        [sys.executable, str(script), "--root", str(repo_root)],
        capture_output=True,
        text=True,
    )

    assert result.returncode in (0, 1), result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] in ("PASS", "WARN", "FAIL")
    assert set(payload["summary"]) == {"fresh", "aging", "stale", "frozen"}
