#!/usr/bin/env python3
"""Tests for scripts/check_stale_escrows.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_stale_escrows.py"


def _make_ledger(
    tmp_path: Path,
    escrows: dict,
    idem_keys: dict | None = None,
) -> Path:
    """Create a minimal ledger directory in tmp_path and return the root."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    (ledger_dir / "escrows.json").write_text(
        json.dumps({"version": 6, "active": escrows}),
        encoding="utf-8",
    )
    keys_data = idem_keys if idem_keys is not None else {}
    (ledger_dir / "idem_keys.json").write_text(
        json.dumps({"keys": keys_data}),
        encoding="utf-8",
    )
    return tmp_path


def _run(root: Path, now: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--root", str(root), "--now", now]
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _parse_json_report(stdout: str) -> dict:
    """Extract the first valid JSON block from combined script output."""
    return json.loads(stdout[: stdout.index("\n\n")])


# ---------------------------------------------------------------------------
# Tier classification tests
# ---------------------------------------------------------------------------


def test_fresh_escrow_is_ok(tmp_path: Path) -> None:
    """Escrow created 1 day ago on a clean ledger — exit 0, tier OK."""
    root = _make_ledger(tmp_path, {"1": {"amount": 10, "created_at": "2026-04-01T00:00:00Z"}})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0
    report = _parse_json_report(result.stdout)
    assert report["summary"]["ok_count"] == 1
    assert report["summary"]["frozen_count"] == 0
    assert report["escrows"][0]["tier"] == "OK"


def test_seven_day_escrow_is_warning(tmp_path: Path) -> None:
    """Escrow exactly 7 days old with no activity — tier WARNING."""
    root = _make_ledger(tmp_path, {"42": {"amount": 20, "created_at": "2026-03-26T00:00:00Z"}})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0  # WARNING does not trigger exit 1
    report = _parse_json_report(result.stdout)
    assert report["summary"]["warning_count"] == 1
    assert report["escrows"][0]["tier"] == "WARNING"
    assert "WARNING" in result.stdout


def test_fourteen_day_escrow_no_claim_is_stale(tmp_path: Path) -> None:
    """Escrow exactly 14 days old with no claims — tier STALE."""
    root = _make_ledger(tmp_path, {"99": {"amount": 15, "created_at": "2026-03-19T00:00:00Z"}})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0  # STALE does not trigger exit 1
    report = _parse_json_report(result.stdout)
    assert report["summary"]["stale_count"] == 1
    assert report["escrows"][0]["tier"] == "STALE"
    assert "STALE" in result.stdout


def test_twenty_one_day_escrow_is_frozen_exits_1(tmp_path: Path) -> None:
    """Escrow exactly 21 days old — tier FROZEN, exit code 1."""
    root = _make_ledger(tmp_path, {"7": {"amount": 30, "created_at": "2026-03-12T00:00:00Z"}})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 1
    report = _parse_json_report(result.stdout)
    assert report["summary"]["frozen_count"] == 1
    assert report["escrows"][0]["tier"] == "FROZEN"
    assert "FROZEN" in result.stdout


def test_frozen_escrow_has_claim_still_frozen(tmp_path: Path) -> None:
    """Age >= 21 days overrides claim status — FROZEN regardless."""
    root = _make_ledger(
        tmp_path,
        {"55": {"amount": 10, "created_at": "2026-03-01T00:00:00Z"}},
        idem_keys={"claim|55|some-agent@claude": "2026-03-10T00:00:00Z"},
    )
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 1
    report = _parse_json_report(result.stdout)
    assert report["escrows"][0]["tier"] == "FROZEN"
    assert report["escrows"][0]["has_claim"] is True


def test_fourteen_day_escrow_with_claim_is_ok(tmp_path: Path) -> None:
    """Escrow 14 days old but with an active claim — NOT stale."""
    root = _make_ledger(
        tmp_path,
        {"33": {"amount": 25, "created_at": "2026-03-19T00:00:00Z"}},
        idem_keys={"claim|33|agent-x@claude": "2026-03-20T00:00:00Z"},
    )
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0
    report = _parse_json_report(result.stdout)
    assert report["escrows"][0]["tier"] == "OK"
    assert report["escrows"][0]["has_claim"] is True


def test_seven_day_escrow_with_submission_is_ok(tmp_path: Path) -> None:
    """Escrow 7 days old with an acceptance (submission) — NOT warning."""
    root = _make_ledger(
        tmp_path,
        {"88": {"amount": 15, "created_at": "2026-03-26T00:00:00Z"}},
        idem_keys={"accept|88|agent-y@claude|slot1": "2026-03-27T00:00:00Z"},
    )
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0
    report = _parse_json_report(result.stdout)
    assert report["escrows"][0]["tier"] == "OK"
    assert report["escrows"][0]["has_submission"] is True


def test_missing_created_at_handled_gracefully(tmp_path: Path) -> None:
    """Escrow without created_at — tier UNKNOWN, does not crash, exit 0."""
    root = _make_ledger(tmp_path, {"5": {"amount": 10}})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0
    report = _parse_json_report(result.stdout)
    assert report["summary"]["unknown_count"] == 1
    assert report["escrows"][0]["tier"] == "UNKNOWN"
    assert report["escrows"][0]["age_days"] is None


def test_multiple_escrows_mixed_tiers(tmp_path: Path) -> None:
    """Multiple escrows across tiers — counts are correct, exit 1 due to FROZEN."""
    root = _make_ledger(
        tmp_path,
        {
            "1": {"amount": 10, "created_at": "2026-04-01T00:00:00Z"},   # OK: 1 day
            "2": {"amount": 10, "created_at": "2026-03-26T00:00:00Z"},   # WARNING: 7 days
            "3": {"amount": 10, "created_at": "2026-03-19T00:00:00Z"},   # STALE: 14 days
            "4": {"amount": 10, "created_at": "2026-03-12T00:00:00Z"},   # FROZEN: 21 days
        },
    )
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 1
    report = _parse_json_report(result.stdout)
    assert report["summary"]["ok_count"] == 1
    assert report["summary"]["warning_count"] == 1
    assert report["summary"]["stale_count"] == 1
    assert report["summary"]["frozen_count"] == 1


def test_empty_ledger_exits_0(tmp_path: Path) -> None:
    """Empty active escrows — exit 0, total_active = 0."""
    root = _make_ledger(tmp_path, {})
    result = _run(root, "2026-04-02T00:00:00Z")
    assert result.returncode == 0
    report = _parse_json_report(result.stdout)
    assert report["summary"]["total_active"] == 0
    assert report["summary"]["frozen_count"] == 0


def test_json_report_structure(tmp_path: Path) -> None:
    """Report JSON has required top-level keys and summary fields."""
    root = _make_ledger(tmp_path, {"10": {"amount": 5, "created_at": "2026-04-01T12:00:00Z"}})
    result = _run(root, "2026-04-02T00:00:00Z")
    report = _parse_json_report(result.stdout)
    assert "version" in report
    assert "generated_at" in report
    assert "summary" in report
    assert "escrows" in report
    summary = report["summary"]
    for field in ("total_active", "frozen_count", "stale_count", "warning_count", "ok_count"):
        assert field in summary, f"missing summary field: {field}"
