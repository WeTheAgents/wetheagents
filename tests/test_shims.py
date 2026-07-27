"""Tests for wea_cli.shims — PATH shim milestone wrapper generation.

Strategy:
- Build a fake "real" binary (a Python script that just exits 0 or 1).
- On Windows create .cmd wrappers for the fake binary so the OS resolves it.
- Build a fake "wea" binary that records calls to `wea trace emit` in a JSON
  capture file instead of actually calling the real CLI.
- Run the shimmed binary through subprocess with a manipulated PATH that puts
  the shim dir first, then the fake-bin dir, omitting the real system PATH.
- Inspect the capture file and/or the exit code.

All 8 required test functions are present.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from wea_cli.shims import create_shim_dir

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"
PY = sys.executable


def _write_fake_binary(
    bin_dir: Path,
    name: str,
    exit_code: int = 0,
    extra_body: str = "",
) -> Path:
    """Write a fake Python binary that exits with exit_code.

    Always written as a .py file so the shim can find and invoke it via
    sys.executable without needing shell=True.  This keeps tests simple and
    cross-platform — no .cmd wrapper needed in the test harness.

    Returns the path to the .py script.
    """
    py_path = bin_dir / f"{name}.py"
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys
        {extra_body}
        sys.exit({exit_code})
        """
    )
    py_path.write_text(script, encoding="utf-8")
    if not IS_WINDOWS:
        py_path.chmod(py_path.stat().st_mode | 0o111)
    return py_path


def _write_fake_wea(bin_dir: Path, capture_file: Path) -> Path:
    """Write a fake `wea` binary that records `wea trace emit` calls.

    When invoked as: wea trace emit <run_dir> <event_type> <source> <payload>
    it appends a JSON record to capture_file and exits 0.
    For any other invocation it just exits 0 silently.

    Written as a standalone .py file (not embedded via extra_body) to avoid
    indentation issues with the _write_fake_binary template.
    """
    cap_repr = repr(str(capture_file))
    script = (
        "#!/usr/bin/env python3\n"
        "import sys, json, os\n"
        "args = sys.argv[1:]\n"
        f"cap = {cap_repr}\n"
        'if len(args) >= 6 and args[0] == "trace" and args[1] == "emit":\n'
        "    record = {\n"
        '        "run_dir": args[2],\n'
        '        "event_type": args[3],\n'
        '        "source": args[4],\n'
        '        "payload": json.loads(args[5]),\n'
        "    }\n"
        "    existing = []\n"
        "    if os.path.exists(cap):\n"
        "        existing = json.loads(open(cap).read())\n"
        "    existing.append(record)\n"
        '    open(cap, "w").write(json.dumps(existing))\n'
        "sys.exit(0)\n"
    )
    py_path = bin_dir / "wea.py"
    py_path.write_text(script, encoding="utf-8")
    if not IS_WINDOWS:
        py_path.chmod(py_path.stat().st_mode | 0o111)
    return py_path


def _run_shim(
    shim_dir: Path,
    fake_bin_dir: Path,
    binary: str,
    args: list[str],
    *,
    run_dir: Path | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run a shim script as a subprocess with controlled PATH.

    PATH = shim_dir : fake_bin_dir  (system PATH excluded for isolation)
    WEA_RUN_DIR = str(run_dir) if provided, else unset.
    """
    env = {}
    if extra_env:
        env.update(extra_env)

    path = str(shim_dir) + os.pathsep + str(fake_bin_dir)
    env["PATH"] = path

    if run_dir is not None:
        env["WEA_RUN_DIR"] = str(run_dir)
    else:
        # Explicitly unset
        env.pop("WEA_RUN_DIR", None)

    # On Windows the .cmd wrapper is the entry point; invoke via cmd /C
    # On POSIX invoke the wrapper script directly via python
    shim_py = shim_dir / f"{binary}.py"

    return subprocess.run(
        [PY, str(shim_py)] + args,
        env=env,
        capture_output=True,
        text=True,
    )


def _read_captures(capture_file: Path) -> list[dict]:
    if not capture_file.exists():
        return []
    return json.loads(capture_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup(tmp_path: Path):
    """Create shim dir, fake-bin dir, run_dir, and capture file."""
    run_dir = tmp_path / ".wea_runs" / "test-run-abc123"
    run_dir.mkdir(parents=True)

    shim_dir = create_shim_dir(run_dir)

    fake_bin_dir = tmp_path / "fake_bins"
    fake_bin_dir.mkdir()

    capture_file = tmp_path / "captures.json"

    return {
        "run_dir": run_dir,
        "shim_dir": shim_dir,
        "fake_bin_dir": fake_bin_dir,
        "capture_file": capture_file,
    }


# ---------------------------------------------------------------------------
# Test 1: git commit → commit_created milestone emitted
# ---------------------------------------------------------------------------


def test_git_commit_emits_commit_created(tmp_path: Path, setup: dict) -> None:
    """Shim emits 'commit_created' milestone after successful git commit."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["commit", "-m", "test"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["event_type"] == "milestone"
    assert caps[0]["source"] == "wea-shim"
    assert caps[0]["payload"] == {"milestone": "commit_created"}


# ---------------------------------------------------------------------------
# Test 2: git status → no milestone emitted (pass-through)
# ---------------------------------------------------------------------------


def test_git_status_no_milestone(tmp_path: Path, setup: dict) -> None:
    """Shim passes through 'git status' without emitting any milestone."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["status"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert caps == [], f"Expected no milestone but got: {caps}"


# ---------------------------------------------------------------------------
# Test 3: Exit code from real command is preserved
# ---------------------------------------------------------------------------


def test_shim_preserves_exit_code(tmp_path: Path, setup: dict) -> None:
    """Shim exits with the same code as the real binary (non-zero case)."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=42)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["commit", "-m", "oops"],
        run_dir=run_dir,
    )

    assert result.returncode == 42


# ---------------------------------------------------------------------------
# Test 4: Shim inactive when WEA_RUN_DIR not set
# ---------------------------------------------------------------------------


def test_shim_inactive_without_run_dir(tmp_path: Path, setup: dict) -> None:
    """When WEA_RUN_DIR is absent, shim delegates to real binary but never
    attempts to emit a milestone (capture file stays empty)."""
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    # run_dir=None → WEA_RUN_DIR unset
    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["commit", "-m", "no-env"],
        run_dir=None,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert caps == [], f"Expected no milestone without WEA_RUN_DIR but got: {caps}"


# ---------------------------------------------------------------------------
# Test 5: git checkout -b → branch_created milestone
# ---------------------------------------------------------------------------


def test_git_checkout_b_emits_branch_created(tmp_path: Path, setup: dict) -> None:
    """Shim emits 'branch_created' milestone for 'git checkout -b <name>'."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["checkout", "-b", "feature/foo"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["payload"] == {"milestone": "branch_created"}


# ---------------------------------------------------------------------------
# Test 6: gh pr create → pr_opened milestone
# ---------------------------------------------------------------------------


def test_gh_pr_create_emits_pr_opened(tmp_path: Path, setup: dict) -> None:
    """Shim emits 'pr_opened' milestone for 'gh pr create'."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "gh", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "gh", ["pr", "create", "--title", "My PR"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["payload"] == {"milestone": "pr_opened"}


# ---------------------------------------------------------------------------
# Test 7: Failed command (exit 1) → no milestone emitted
# ---------------------------------------------------------------------------


def test_failed_command_no_milestone(tmp_path: Path, setup: dict) -> None:
    """When the real binary exits non-zero, no milestone is emitted."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=1)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["commit", "-m", "will fail"],
        run_dir=run_dir,
    )

    assert result.returncode == 1
    caps = _read_captures(capture_file)
    assert caps == [], f"Expected no milestone on failure but got: {caps}"


# ---------------------------------------------------------------------------
# Test 8: Real binary found via PATH (skipping shim dir)
# ---------------------------------------------------------------------------


def test_real_binary_found_via_path_skipping_shim_dir(tmp_path: Path, setup: dict) -> None:
    """Shim correctly finds the real binary in PATH by skipping its own dir.

    We place a sentinel-writing fake 'git' in fake_bin_dir only.
    If the shim tried to exec itself again it would recurse; instead it finds
    the fake binary in fake_bin_dir and runs it, which writes a sentinel file.
    """
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]
    sentinel = tmp_path / "real_was_called.txt"

    # Fake git writes a sentinel file then exits 0
    _write_fake_binary(
        fake_bin_dir,
        "git",
        exit_code=0,
        extra_body=f"open({str(sentinel)!r}, 'w').write('yes')",
    )
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["push"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    assert sentinel.exists(), "Real binary (fake git) was never called — shim may have invoked itself"
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["payload"] == {"milestone": "push_completed"}


# ---------------------------------------------------------------------------
# Test 9: create_shim_dir creates expected files
# ---------------------------------------------------------------------------


def test_create_shim_dir_creates_files(tmp_path: Path) -> None:
    """create_shim_dir creates .shims/ with a .py file for each shimmed binary."""
    run_dir = tmp_path / ".wea_runs" / "run-xyz"
    run_dir.mkdir(parents=True)

    shim_dir = create_shim_dir(run_dir)

    assert shim_dir.is_dir()
    assert shim_dir.name == ".shims"
    assert shim_dir.parent == run_dir

    for binary in ("git", "gh"):
        py_file = shim_dir / f"{binary}.py"
        assert py_file.exists(), f"Missing shim: {py_file}"
        content = py_file.read_text(encoding="utf-8")
        assert "wea-shim" in content


# ---------------------------------------------------------------------------
# Test 10: git switch -c → branch_created milestone
# ---------------------------------------------------------------------------


def test_git_switch_c_emits_branch_created(tmp_path: Path, setup: dict) -> None:
    """Shim emits 'branch_created' for 'git switch -c <name>'."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "git", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "git", ["switch", "-c", "new-branch"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["payload"] == {"milestone": "branch_created"}


# ---------------------------------------------------------------------------
# Test 11: gh pr merge → pr_merged milestone
# ---------------------------------------------------------------------------


def test_gh_pr_merge_emits_pr_merged(tmp_path: Path, setup: dict) -> None:
    """Shim emits 'pr_merged' for 'gh pr merge'."""
    run_dir = setup["run_dir"]
    shim_dir = setup["shim_dir"]
    fake_bin_dir = setup["fake_bin_dir"]
    capture_file = setup["capture_file"]

    _write_fake_binary(fake_bin_dir, "gh", exit_code=0)
    _write_fake_wea(fake_bin_dir, capture_file)

    result = _run_shim(
        shim_dir, fake_bin_dir, "gh", ["pr", "merge", "--squash"],
        run_dir=run_dir,
    )

    assert result.returncode == 0
    caps = _read_captures(capture_file)
    assert len(caps) == 1
    assert caps[0]["payload"] == {"milestone": "pr_merged"}
