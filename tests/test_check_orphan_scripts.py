"""Tests for scripts/check_orphan_scripts.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_orphan_scripts import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    """Create minimal repo layout: scripts/ and .github/workflows/."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    return tmp_path


def _write_script(scripts_dir: Path, name: str, lines: int = 5) -> Path:
    """Write a stub check script with the given line count."""
    path = scripts_dir / name
    path.write_text("\n".join(f"# line {i}" for i in range(lines)), encoding="utf-8")
    return path


def _write_runner(scripts_dir: Path, content: str) -> Path:
    path = scripts_dir / "run_all_checks.py"
    path.write_text(content, encoding="utf-8")
    return path


def _write_workflow(workflows_dir: Path, name: str, content: str) -> Path:
    path = workflows_dir / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. All scripts wired via explicit mention in runner → PASS
# ---------------------------------------------------------------------------

def test_all_scripts_wired_explicit_pass(tmp_path: Path) -> None:
    """Scripts explicitly named in run_all_checks.py are not orphans."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    _write_script(scripts_dir, "check_foo.py")
    _write_script(scripts_dir, "check_bar.py")
    _write_runner(scripts_dir, 'scripts = ["check_foo.py", "check_bar.py"]\n')

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["orphans"] == []


# ---------------------------------------------------------------------------
# 2. One script not wired → WARN with that script listed
# ---------------------------------------------------------------------------

def test_one_orphan_reported_as_warn(tmp_path: Path) -> None:
    """A script absent from runner and workflows is flagged as WARN."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    _write_script(scripts_dir, "check_foo.py", lines=10)
    _write_script(scripts_dir, "check_bar.py", lines=7)
    # runner only mentions bar; foo is the orphan
    _write_runner(scripts_dir, 'scripts = ["check_bar.py"]\n')

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "WARN"
    assert len(result["orphans"]) == 1
    orphan = result["orphans"][0]
    assert orphan["filename"] == "check_foo.py"
    assert orphan["line_count"] == 10


# ---------------------------------------------------------------------------
# 3. Multiple scripts not wired → all reported
# ---------------------------------------------------------------------------

def test_multiple_orphans_all_reported(tmp_path: Path) -> None:
    """All orphan scripts appear in the result."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    for name in ("check_alpha.py", "check_beta.py", "check_gamma.py"):
        _write_script(scripts_dir, name)
    # runner exists but mentions nothing
    _write_runner(scripts_dir, "# empty runner\n")

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "WARN"
    orphan_names = {o["filename"] for o in result["orphans"]}
    assert orphan_names == {"check_alpha.py", "check_beta.py", "check_gamma.py"}


# ---------------------------------------------------------------------------
# 4. Empty scripts directory → PASS
# ---------------------------------------------------------------------------

def test_empty_scripts_dir_passes(tmp_path: Path) -> None:
    """No check_*.py files at all → PASS with no orphans."""
    repo = _make_repo(tmp_path)
    # scripts dir exists but has no check_*.py
    _write_runner(repo / "scripts", "# runner\n")

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["orphans"] == []
    assert "no check_*.py" in result["summary"]


# ---------------------------------------------------------------------------
# 5. run_all_checks.py missing → handle gracefully, check workflows only
# ---------------------------------------------------------------------------

def test_missing_runner_no_crash(tmp_path: Path) -> None:
    """If run_all_checks.py is absent, no crash; workflows are still checked."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    _write_script(scripts_dir, "check_foo.py")
    _write_script(scripts_dir, "check_bar.py")
    # runner NOT written
    # workflow covers bar; foo is orphan
    _write_workflow(
        repo / ".github" / "workflows",
        "ci.yml",
        "run: python scripts/check_bar.py\n",
    )

    result, passed = run(repo)

    assert passed is True  # no crash
    assert result["status"] == "WARN"
    orphan_names = {o["filename"] for o in result["orphans"]}
    assert orphan_names == {"check_foo.py"}


# ---------------------------------------------------------------------------
# 6. Wildcard glob in runner covers all scripts → PASS
# ---------------------------------------------------------------------------

def test_wildcard_covers_all_scripts(tmp_path: Path) -> None:
    """A glob('check_*.py') pattern in runner counts as wiring all scripts."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    _write_script(scripts_dir, "check_new_one.py")
    _write_script(scripts_dir, "check_another.py")
    # runner uses wildcard glob — matches the real run_all_checks.py pattern
    _write_runner(
        scripts_dir,
        'checks = scripts_dir.glob("check_*.py")\n',
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["orphans"] == []


# ---------------------------------------------------------------------------
# 7. Wired via CI workflow, not runner → PASS
# ---------------------------------------------------------------------------

def test_wired_via_workflow_not_runner(tmp_path: Path) -> None:
    """A script only mentioned in a CI workflow is not an orphan."""
    repo = _make_repo(tmp_path)
    scripts_dir = repo / "scripts"
    _write_script(scripts_dir, "check_ci_only.py")
    # runner mentions nothing
    _write_runner(scripts_dir, "# no explicit scripts\n")
    _write_workflow(
        repo / ".github" / "workflows",
        "guard.yml",
        "- run: python scripts/check_ci_only.py\n",
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["orphans"] == []


# ---------------------------------------------------------------------------
# 8. Output structure always has status, orphans, summary
# ---------------------------------------------------------------------------

def test_output_structure(tmp_path: Path) -> None:
    """run() always returns a dict with status, orphans, and summary keys."""
    repo = _make_repo(tmp_path)
    _write_script(repo / "scripts", "check_x.py")
    _write_runner(repo / "scripts", 'scripts_dir.glob("check_*.py")\n')

    result, passed = run(repo)

    assert "status" in result
    assert "orphans" in result
    assert "summary" in result
    assert isinstance(result["orphans"], list)
    assert isinstance(result["summary"], str)
    assert result["status"] in ("PASS", "WARN")
    assert isinstance(passed, bool)
