"""Tests for scripts/run_all_checks.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_all_checks import discover_checks, main, run_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_check(tmp_path: Path, name: str, exit_code: int, output: str) -> Path:
    """Write a minimal check_*.py that prints output and exits with exit_code."""
    script = tmp_path / name
    script.write_text(
        f"import sys\nprint({output!r})\nsys.exit({exit_code})\n", encoding="utf-8"
    )
    return script


# ---------------------------------------------------------------------------
# Unit tests for discover_checks
# ---------------------------------------------------------------------------


def test_discover_checks_finds_all_check_scripts(tmp_path: Path) -> None:
    """discover_checks returns all check_*.py files, sorted by name."""
    (tmp_path / "check_alpha.py").touch()
    (tmp_path / "check_beta.py").touch()
    (tmp_path / "run_all_checks.py").touch()   # must NOT be included
    (tmp_path / "check_gamma.txt").touch()      # not .py, must NOT be included

    found = discover_checks(tmp_path)
    names = [f.name for f in found]
    assert names == ["check_alpha.py", "check_beta.py"]


def test_discover_checks_empty_dir(tmp_path: Path) -> None:
    """discover_checks on a dir with no check_*.py returns empty list."""
    assert discover_checks(tmp_path) == []


# ---------------------------------------------------------------------------
# Test 1: All checks pass → exit 0
# ---------------------------------------------------------------------------


def test_all_checks_pass_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When every check script exits 0, main() returns 0."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_a.py", 0, "all good")
    _make_check(scripts_dir, "check_b.py", 0, "also good")

    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: sorted(scripts_dir.glob("check_*.py")),
    )
    assert main([]) == 0


# ---------------------------------------------------------------------------
# Test 2: One check fails → exit 1
# ---------------------------------------------------------------------------


def test_one_check_fails_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When at least one runnable check exits non-zero, main() returns 1."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_good.py", 0, "ok")
    _make_check(scripts_dir, "check_bad.py", 1, "FAIL: something wrong")

    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: sorted(scripts_dir.glob("check_*.py")),
    )
    assert main([]) == 1


# ---------------------------------------------------------------------------
# Test 3: Exit-2 scripts are SKIPPED, not counted as failures
# ---------------------------------------------------------------------------


def test_skip_exit2_does_not_cause_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scripts exiting 2 (argparse: needs external context) are SKIPPED, not FAILED.

    Exit code 2 is the standard argparse error for missing required arguments.
    CI-only checks (check_pr_scope, check_diary_incidents, etc.) exit 2 when
    run without their required PR context.  The runner must treat these as SKIP
    so that sweep-mode runs are not blocked by context-only checks.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_good.py", 0, "ok")
    _make_check(scripts_dir, "check_ci_only.py", 2, "Error: provide --files")

    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: sorted(scripts_dir.glob("check_*.py")),
    )
    assert main([]) == 0  # ci_only is skipped, not a failure


# ---------------------------------------------------------------------------
# Test 4: No check_*.py files → exits 1 with error message
# ---------------------------------------------------------------------------


def test_no_scripts_found_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """When no check scripts are discovered, main() exits 1 and prints an error."""
    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: [],
    )
    rc = main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "No check_*.py" in out


# ---------------------------------------------------------------------------
# Test 5: JSON output is valid schema
# ---------------------------------------------------------------------------


def test_json_output_valid_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """--json output is valid JSON with required top-level and per-result keys."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_check(scripts_dir, "check_x.py", 0, "pass")
    _make_check(scripts_dir, "check_y.py", 2, "needs context")

    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: sorted(scripts_dir.glob("check_*.py")),
    )
    rc = main(["--json"])
    assert rc == 0

    out = capsys.readouterr().out
    data = json.loads(out)

    # Top-level keys
    for key in ("all_passed", "total", "runnable", "passed", "failed", "skipped", "results"):
        assert key in data, f"missing key: {key}"

    assert isinstance(data["all_passed"], bool)
    assert data["total"] == 2
    assert data["skipped"] == 1
    assert data["runnable"] == 1

    # Per-result keys
    for entry in data["results"]:
        for key in ("script", "exit_code", "status", "passed", "skipped", "first_line",
                    "stdout", "stderr"):
            assert key in entry, f"result missing key: {key}"


# ---------------------------------------------------------------------------
# Test 6: Discovered scripts count matches expected count
# ---------------------------------------------------------------------------


def test_discovered_scripts_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """JSON results list length matches the number of discovered scripts."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for i in range(4):
        _make_check(scripts_dir, f"check_{i:02d}.py", 0, "ok")

    monkeypatch.setattr(
        "scripts.run_all_checks.discover_checks",
        lambda _d: sorted(scripts_dir.glob("check_*.py")),
    )
    main(["--json"])
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["total"] == 4
    assert len(data["results"]) == 4


# ---------------------------------------------------------------------------
# Test 7: Integration — real repo: runner works correctly
#
# The runner discovers all check_*.py scripts, produces valid JSON, reports
# check_invariant as PASS, and exits cleanly (0 = all pass, 1 = some fail).
# NOTE: Several pre-existing integrity violations in the repo cause the runner
# to exit 1 on the current main branch.  That is CORRECT behavior — the runner
# is doing its job.  This test verifies runner correctness, not repo health.
# ---------------------------------------------------------------------------


def test_integration_real_repo_runner_correctness() -> None:
    """Runner on the real repo: clean exit, valid JSON, 20+ scripts, invariant passes."""
    repo_root = Path(__file__).resolve().parent.parent
    runner = repo_root / "scripts" / "run_all_checks.py"
    result = subprocess.run(
        [sys.executable, str(runner), "--json"],
        capture_output=True,
        text=True,
    )

    # Runner must exit cleanly (0=all pass, 1=some fail — never crash/2)
    assert result.returncode in (0, 1), (
        f"runner exited {result.returncode} (expected 0 or 1).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    data = json.loads(result.stdout)

    # At least 20 check scripts discovered (repo has 21 as of this writing)
    assert data["total"] >= 20, f"expected 20+ checks, got {data['total']}"

    # check_invariant must pass — it tests the core economy equation
    inv = next((r for r in data["results"] if r["script"] == "check_invariant.py"), None)
    assert inv is not None, "check_invariant.py not found in results"
    assert inv["passed"], f"check_invariant.py failed:\n{inv['stdout']}"


# ---------------------------------------------------------------------------
# Test 8: run_check result dict has expected shape
# ---------------------------------------------------------------------------


def test_run_check_result_shape(tmp_path: Path) -> None:
    """run_check returns a dict with all required keys and correct types."""
    script = _make_check(tmp_path, "check_shape.py", 0, "hello")
    result = run_check(script)

    assert result["script"] == "check_shape.py"
    assert result["exit_code"] == 0
    assert result["status"] == "pass"
    assert result["passed"] is True
    assert result["skipped"] is False
    assert "hello" in result["first_line"]
    assert isinstance(result["stdout"], str)
    assert isinstance(result["stderr"], str)
