"""Tests for scripts/ledger_health_report.py.

Covers the 6 required cases plus extras:
1. All checks pass → overall PASS
2. One check fails → overall FAIL
3. JSON schema is valid (required top-level and per-check keys)
4. --dry-run prints but does not write ledger/health_report.json
5. duration_ms is non-negative for every check result
6. Integration test on real repo (exits 0 or 1, valid JSON, 20+ checks)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ledger_health_report import build_report, discover_checks, main, run_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(tmp_path: Path, name: str, exit_code: int, output: str = "") -> Path:
    """Write a minimal check_*.py that prints output and exits with exit_code."""
    script = tmp_path / name
    script.write_text(
        f"import sys\nprint({output!r})\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return script


# ---------------------------------------------------------------------------
# Test 1: All checks pass → overall PASS
# ---------------------------------------------------------------------------


def test_all_pass_produces_overall_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When every runnable check exits 0, overall is PASS and return code is 0."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_a.py", 0, "ok a")
    _make_check(scripts_dir, "check_b.py", 0, "ok b")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    report, all_passed = build_report(scripts_dir)
    assert report["overall"] == "PASS"
    assert all_passed is True


# ---------------------------------------------------------------------------
# Test 2: One check fails → overall FAIL
# ---------------------------------------------------------------------------


def test_one_fail_produces_overall_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When at least one runnable check exits non-zero, overall is FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_good.py", 0, "pass")
    _make_check(scripts_dir, "check_bad.py", 1, "FAIL: something broke")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    report, all_passed = build_report(scripts_dir)
    assert report["overall"] == "FAIL"
    assert all_passed is False


# ---------------------------------------------------------------------------
# Test 3: JSON schema validity
# ---------------------------------------------------------------------------


def test_json_schema_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Report dict has required top-level keys and per-check keys."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_x.py", 0, "pass")
    _make_check(scripts_dir, "check_y.py", 2, "needs context")  # SKIP

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    report, _ = build_report(scripts_dir)

    # Top-level keys
    for key in ("generated_at", "overall", "checks"):
        assert key in report, f"missing top-level key: {key}"

    assert report["overall"] in ("PASS", "FAIL")
    assert isinstance(report["checks"], list)

    # Per-check keys
    for entry in report["checks"]:
        for key in ("name", "status", "summary", "duration_ms"):
            assert key in entry, f"check entry missing key: {key}"
        assert entry["status"] in ("PASS", "FAIL", "SKIP")


# ---------------------------------------------------------------------------
# Test 4: --dry-run does not write file
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """--dry-run prints the JSON report but does not write health_report.json."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    _make_check(scripts_dir, "check_ok.py", 0, "pass")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    rc = main(["--dry-run", "--root", str(tmp_path)])

    # File must NOT be written
    out_path = ledger_dir / "health_report.json"
    assert not out_path.exists(), "dry-run must not write health_report.json"

    # JSON is printed to stdout
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "overall" in data

    assert rc == 0


# ---------------------------------------------------------------------------
# Test 5: duration_ms is non-negative
# ---------------------------------------------------------------------------


def test_duration_ms_non_negative(tmp_path: Path) -> None:
    """Every check result has a non-negative duration_ms value."""
    script = _make_check(tmp_path, "check_fast.py", 0, "instant")
    result = run_check(script)

    assert "duration_ms" in result
    assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Test 6: Integration test on real repo
# ---------------------------------------------------------------------------


def test_integration_real_repo() -> None:
    """Runner on the real repo: valid JSON, 20+ checks, proper exit code."""
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "ledger_health_report.py"

    result = subprocess.run(
        [sys.executable, str(script), "--dry-run"],
        capture_output=True,
        text=True,
    )

    # Must exit 0 (all pass) or 1 (some fail) — never crash
    assert result.returncode in (0, 1), (
        f"script exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    data = json.loads(result.stdout)
    assert data["overall"] in ("PASS", "FAIL")
    assert len(data["checks"]) >= 20, f"expected 20+ checks, got {len(data['checks'])}"

    # check_invariant must be present and PASS
    inv = next((c for c in data["checks"] if c["name"] == "check_invariant.py"), None)
    assert inv is not None, "check_invariant.py not found in checks"
    assert inv["status"] == "PASS", f"check_invariant.py failed: {inv['summary']}"


# ---------------------------------------------------------------------------
# Test 7: Exit-2 scripts are SKIP, not FAIL
# ---------------------------------------------------------------------------


def test_skip_exit2_does_not_cause_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scripts exiting 2 get SKIP status and do not push overall to FAIL."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_pass.py", 0, "ok")
    _make_check(scripts_dir, "check_ci.py", 2, "Error: provide --files")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    report, all_passed = build_report(scripts_dir)
    assert report["overall"] == "PASS"
    assert all_passed is True

    skip_entry = next(c for c in report["checks"] if c["name"] == "check_ci.py")
    assert skip_entry["status"] == "SKIP"


# ---------------------------------------------------------------------------
# Test 8: File is written when not dry-run
# ---------------------------------------------------------------------------


def test_file_written_when_not_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() writes health_report.json when --dry-run is not passed."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    _make_check(scripts_dir, "check_z.py", 0, "pass")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    main(["--root", str(tmp_path)])

    out_path = ledger_dir / "health_report.json"
    assert out_path.exists(), "health_report.json must be written"

    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["overall"] in ("PASS", "FAIL")
    assert isinstance(data["checks"], list)


# ---------------------------------------------------------------------------
# Test 9: generated_at is a valid ISO-8601 timestamp with timezone
# ---------------------------------------------------------------------------


def test_generated_at_is_valid_iso8601(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """generated_at must be a parseable ISO-8601 datetime string."""
    from datetime import datetime

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_ts.py", 0, "ok")

    monkeypatch.setattr(
        "scripts.ledger_health_report.discover_checks",
        lambda _: sorted(scripts_dir.glob("check_*.py")),
    )

    report, _ = build_report(scripts_dir)
    ts = report["generated_at"]
    # datetime.fromisoformat handles '+00:00' suffix but not 'Z' on Python < 3.11
    ts_normalized = ts.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(ts_normalized)
    assert parsed.tzinfo is not None, "generated_at must include timezone info"
