"""Tests for scripts/check_script_test_coverage.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_script_test_coverage import (
    build_script_pattern,
    discover_check_scripts,
    discover_check_test_files,
    discover_test_files,
    run,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_script_test_coverage.py"


@pytest.fixture
def sandbox_root() -> Path:
    root = Path(".test_runs") / f"check_script_test_coverage_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _make_repo(root: Path) -> Path:
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    return root


def _write_script(repo: Path, name: str, content: str | None = None) -> Path:
    path = repo / "scripts" / name
    path.write_text(content or 'print("ok")\n', encoding="utf-8")
    return path


def _write_test(repo: Path, name: str, content: str) -> Path:
    path = repo / "tests" / name
    path.write_text(content, encoding="utf-8")
    return path


def test_discover_helpers_return_sorted_files(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_beta.py")
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "other.py")
    _write_test(repo, "test_zeta.py", "pass\n")
    _write_test(repo, "test_alpha.py", "pass\n")
    _write_test(repo, "test_check_beta.py", "pass\n")

    assert [path.name for path in discover_check_scripts(repo)] == [
        "check_alpha.py",
        "check_beta.py",
    ]
    assert [path.name for path in discover_test_files(repo)] == [
        "test_alpha.py",
        "test_check_beta.py",
        "test_zeta.py",
    ]
    assert [path.name for path in discover_check_test_files(repo)] == [
        "test_check_beta.py",
    ]


def test_build_script_pattern_matches_stem_and_filename() -> None:
    pattern = build_script_pattern("check_alpha")

    assert pattern.search("from scripts.check_alpha import run")
    assert pattern.search('script = "check_alpha.py"')


def test_build_script_pattern_is_boundary_aware() -> None:
    pattern = build_script_pattern("check_alpha")

    assert pattern.search("check_alpha") is not None
    assert pattern.search("check_alpha_extra") is None
    assert pattern.search("precheck_alpha") is None


def test_run_passes_when_all_scripts_are_referenced(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "check_beta.py")
    _write_test(
        repo,
        "test_alpha.py",
        "from scripts.check_alpha import main\n",
    )
    _write_test(
        repo,
        "test_beta.py",
        'SCRIPT = "check_beta.py"\n',
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["uncovered_scripts"] == []
    assert result["dead_test_files"] == []


def test_single_test_can_cover_multiple_scripts(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "check_beta.py")
    _write_test(
        repo,
        "test_combo.py",
        "\n".join(
            [
                "from scripts.check_alpha import run as alpha_run",
                'BETA_SCRIPT = "check_beta.py"',
            ]
        )
        + "\n",
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"


def test_uncovered_script_fails(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "check_beta.py")
    _write_test(repo, "test_only_alpha.py", "import scripts.check_alpha\n")

    result, passed = run(repo)

    assert passed is False
    assert result["status"] == "FAIL"
    assert result["uncovered_scripts"] == ["check_beta.py"]


def test_multiple_uncovered_scripts_are_sorted(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_gamma.py")
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "check_beta.py")
    _write_test(repo, "test_alpha_only.py", "from scripts.check_alpha import run\n")

    result, passed = run(repo)

    assert passed is False
    assert result["uncovered_scripts"] == ["check_beta.py", "check_gamma.py"]


def test_dead_check_test_file_fails(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_test(repo, "test_alpha.py", "from scripts.check_alpha import run\n")
    _write_test(repo, "test_check_ghost.py", 'TARGET = "check_ghost.py"\n')

    result, passed = run(repo)

    assert passed is False
    assert result["status"] == "FAIL"
    assert result["dead_test_files"] == ["test_check_ghost.py"]


def test_non_check_test_file_is_not_marked_dead(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_test(repo, "test_alpha.py", "from scripts.check_alpha import run\n")
    _write_test(repo, "test_misc.py", "assert 1 + 1 == 2\n")

    result, passed = run(repo)

    assert passed is True
    assert result["dead_test_files"] == []


def test_missing_tests_directory_causes_uncovered_scripts(sandbox_root: Path) -> None:
    (sandbox_root / "scripts").mkdir()
    (sandbox_root / "scripts" / "check_alpha.py").write_text('print("ok")\n', encoding="utf-8")

    result, passed = run(sandbox_root)

    assert passed is False
    assert result["uncovered_scripts"] == ["check_alpha.py"]
    assert result["dead_test_files"] == []


def test_no_check_scripts_passes_cleanly(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_test(repo, "test_misc.py", "assert True\n")

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["uncovered_scripts"] == []
    assert result["dead_test_files"] == []
    assert "no scripts/check_*.py" in result["summary"]


def test_prefix_collision_does_not_count_as_coverage(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_script(repo, "check_alpha_extra.py")
    _write_test(repo, "test_extra.py", "from scripts.check_alpha_extra import run\n")

    result, passed = run(repo)

    assert passed is False
    assert result["uncovered_scripts"] == ["check_alpha.py"]


def test_cli_exits_zero_and_emits_json_on_pass(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")
    _write_test(repo, "test_alpha.py", "from scripts.check_alpha import run\n")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["status"] == "PASS"


def test_cli_exits_one_and_emits_json_on_fail(sandbox_root: Path) -> None:
    repo = _make_repo(sandbox_root)
    _write_script(repo, "check_alpha.py")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["uncovered_scripts"] == ["check_alpha.py"]


def test_current_repo_passes() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, passed = run(repo_root)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["uncovered_scripts"] == []
    assert result["dead_test_files"] == []
