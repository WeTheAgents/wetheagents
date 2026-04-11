"""
Red-team tests for run_all_checks.py
Task: [Gauntlet T6S8] Adversarial tests for run_all_checks.py
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from scripts import run_all_checks


@pytest.fixture
def run_checks(tmp_path, monkeypatch):
    """Fixture to isolate run_all_checks.py execution to a temporary directory."""
    monkeypatch.setattr(
        run_all_checks, "discover_checks", lambda _: sorted(tmp_path.glob("check_*.py"))
    )

    def _run(args=None):
        if args is None:
            args = []
        return run_all_checks.main(args)

    return _run, tmp_path


def create_check(tmp_path: Path, name: str, content: str) -> Path:
    script = tmp_path / name
    script.write_text(content, encoding="utf-8")
    return script


# --- GAPS & BLIND SPOTS (Tests that prove the runner is vulnerable) ---

def test_exit_0_prints_fail(run_checks, capsys):
    """
    Attack vector: A check script exits 0 but prints 'FAIL' to stdout.
    The runner blindly trusts the exit code and passes, ignoring output.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_1.py", "print('FAIL: something is broken')\nimport sys\nsys.exit(0)")
    
    exit_code = runner()
    assert exit_code == 0, "Runner silently passed despite the failure output"


def test_json_status_fail_exit_0(run_checks, capsys):
    """
    Attack vector: A check outputs valid JSON claiming {"status": "fail"} but exits 0.
    The runner ignores the structured output payload and passes based on exit code.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_json_fail.py", "import json, sys\nprint(json.dumps({'status': 'fail'}))\nsys.exit(0)")
    
    exit_code = runner(["--json"])
    assert exit_code == 0, "Runner silently passed despite JSON fail status"
    
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["all_passed"] is True, "Runner should have passed because of exit 0"


def test_all_skipped_vacuous_pass(run_checks, capsys):
    """
    Attack vector: All scripts exit with 2 (SKIP).
    The runner incorrectly evaluates all([]) as True and passes, 
    resulting in a vacuous pass even when zero checks were actually run.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_skip1.py", "import sys\nsys.exit(2)")
    create_check(tmp, "check_skip2.py", "import sys\nsys.exit(2)")
    
    exit_code = runner()
    assert exit_code == 0, "Runner gave a vacuous PASS when everything was skipped"


def test_check_is_directory_fails(run_checks, capsys):
    """
    Attack vector: A directory is named check_dir.py.
    Expected: Python fails to execute it (exit 1). The runner catches this and fails.
    """
    runner, tmp = run_checks
    (tmp / "check_dir.py").mkdir()
    
    exit_code = runner()
    assert exit_code == 1, "Runner must fail when trying to run a directory"


def test_unreadable_file_fails(run_checks, capsys):
    """
    Attack vector: A check script has permissions that prevent Python from reading it.
    Expected: Python exits with non-zero. The runner catches this and fails.
    """
    runner, tmp = run_checks
    script = create_check(tmp, "check_unreadable.py", "import sys\nsys.exit(1)")
    
    # Remove read permissions
    script.chmod(0o000)
    
    try:
        exit_code = runner()
        assert exit_code == 1, "Runner must fail on unreadable script"
    finally:
        # Restore permissions so cleanup doesn't fail on Windows
        script.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_stderr_ignored_on_exit_0(run_checks, capsys):
    """
    Attack vector: Script writes error details to stderr but exits 0.
    Runner considers it a PASS and ignores stderr.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_stderr.py", "import sys\nprint('ERROR: critical', file=sys.stderr)\nsys.exit(0)")
    
    exit_code = runner()
    assert exit_code == 0, "Runner silently passed despite stderr output"


def test_typo_in_script_name_ignored(run_checks, capsys):
    """
    Attack vector: A check script is named 'chekc_foo.py' instead of 'check_foo.py'.
    The runner's glob pattern misses it. It fails silently by not executing the script.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_valid.py", "import sys\nsys.exit(0)")
    create_check(tmp, "chekc_typo.py", "import sys\nsys.exit(1)") # Fails, but is ignored
    
    exit_code = runner()
    assert exit_code == 0, "Runner silently ignored misnamed script"


# --- EXPECTED BEHAVIORS (Tests that prove the runner is robust against certain attacks) ---

def test_uncaught_exception_caught_by_runner(run_checks, capsys):
    """
    Attack vector: A check script raises an uncaught exception (Python stacktrace, exit 1).
    Expected: The runner correctly catches the non-zero exit code and fails.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_exception.py", "raise ValueError('boom')")
    
    exit_code = runner()
    assert exit_code == 1, "Runner must fail on uncaught Python exceptions"
    
    result = capsys.readouterr()
    assert "ValueError: boom" in result.err or "ValueError: boom" in result.out


def test_no_checks_found_fails(run_checks, capsys):
    """
    Attack vector: No check_*.py scripts exist (glob finds nothing).
    Expected: The runner explicitly exits 1 to prevent vacuous passing without checks.
    """
    runner, tmp = run_checks
    exit_code = runner()
    assert exit_code == 1, "Runner must fail when no scripts are discovered"


def test_json_output_with_crashing_script(run_checks, capsys):
    """
    Attack vector: --json flag is used but one check crashes mid-run.
    Expected: Partial JSON is safely written and is completely valid, correctly reporting fail.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_ok.py", "import sys\nsys.exit(0)")
    create_check(tmp, "check_crash.py", "raise RuntimeError('crash mid-run')")
    
    exit_code = runner(["--json"])
    assert exit_code == 1
    
    out = capsys.readouterr().out
    # Parse should not throw, meaning JSON is valid
    data = json.loads(out)
    assert data["all_passed"] is False
    assert data["failed"] == 1
    assert data["passed"] == 1


def test_timeout_caught_by_runner(run_checks, capsys, monkeypatch):
    """
    Attack vector: A check script hangs in an infinite loop.
    Expected: The runner enforces _CHECK_TIMEOUT, kills the process, and fails.
    """
    runner, tmp = run_checks
    create_check(tmp, "check_hang.py", "import time\ntime.sleep(10)")
    
    monkeypatch.setattr(run_all_checks, "_CHECK_TIMEOUT", 0.1)
    
    exit_code = runner()
    assert exit_code == 1, "Runner must fail on script timeout"
    
    out = capsys.readouterr().out
    assert "timed out after" in out
