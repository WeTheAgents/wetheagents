"""Tests for scripts/check_precommit_coverage.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_precommit_coverage import parse_invoked_scripts, run

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_precommit_coverage.py"


@pytest.fixture
def precommit_repo() -> Path:
    root = Path(".test_runs") / f"precommit_coverage_{uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "scripts").mkdir(parents=True)
    (root / ".githooks").mkdir()
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _write_script(scripts_dir: Path, name: str) -> None:
    (scripts_dir / name).write_text('print("ok")\n', encoding="utf-8")


def _write_hook(repo: Path, content: str) -> Path:
    path = repo / ".githooks" / "pre-commit"
    path.write_text(content, encoding="utf-8")
    return path


def _mandatory_hook() -> str:
    return "\n".join(
        [
            'python "$REPO_ROOT/scripts/genome_guard.py" --files $GENOME_FILES || exit 1',
            'python "$REPO_ROOT/scripts/check_invariant.py" --root "$REPO_ROOT" || exit 1',
            'python "$REPO_ROOT/scripts/check_ledger_schema.py" || exit 1',
        ]
    ) + "\n"


def _write_mandatory_scripts(repo: Path) -> None:
    scripts_dir = repo / "scripts"
    for name in ("genome_guard.py", "check_invariant.py", "check_ledger_schema.py"):
        _write_script(scripts_dir, name)


def test_all_mandatory_present_pass(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(repo, _mandatory_hook())

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["missing_mandatory"] == []
    assert result["dead_references"] == []


def test_one_missing_mandatory_fails(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        "\n".join(
            [
                'python "$REPO_ROOT/scripts/genome_guard.py" || exit 1',
                'python "$REPO_ROOT/scripts/check_invariant.py" || exit 1',
            ]
        ) + "\n",
    )

    result, passed = run(repo)

    assert passed is False
    assert result["status"] == "FAIL"
    assert result["missing_mandatory"] == ["check_ledger_schema.py"]


def test_dead_reference_warns_but_passes(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_script(repo / "scripts", "check_doc_sync.py")
    _write_hook(
        repo,
        _mandatory_hook()
        + 'python "$REPO_ROOT/scripts/check_doc_sync.py" || exit 1\n'
        + 'python "$REPO_ROOT/scripts/check_ghost.py" || exit 1\n',
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["dead_references"] == ["check_ghost.py"]
    assert "dead reference" in result["summary"]


def test_empty_hook_fails(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(repo, "")

    result, passed = run(repo)

    assert passed is False
    assert result["status"] == "FAIL"
    assert result["missing_mandatory"] == [
        "check_invariant.py",
        "check_ledger_schema.py",
        "genome_guard.py",
    ]


def test_hook_with_extras_passes(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_script(repo / "scripts", "check_doc_sync.py")
    _write_script(repo / "scripts", "check_ledger_schema.py")
    _write_hook(
        repo,
        _mandatory_hook()
        + 'python "$REPO_ROOT/scripts/check_doc_sync.py" || exit 1\n'
        + 'python "$REPO_ROOT/scripts/check_ledger_schema.py" || exit 1\n',
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["dead_references"] == []


def test_missing_hook_file_fails(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    (repo / ".githooks" / "pre-commit").unlink(missing_ok=True)

    result, passed = run(repo)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "hook file not found" in result["summary"]


def test_comments_do_not_count_as_invocations(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        "\n".join(
            [
                '# python "$REPO_ROOT/scripts/check_ledger_schema.py" || exit 1',
                'python "$REPO_ROOT/scripts/genome_guard.py" || exit 1',
                '# python "$REPO_ROOT/scripts/check_invariant.py" || exit 1',
            ]
        ) + "\n",
    )

    result, passed = run(repo)

    assert passed is False
    assert result["missing_mandatory"] == [
        "check_invariant.py",
        "check_ledger_schema.py",
    ]


def test_duplicate_dead_reference_is_reported_once(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        _mandatory_hook()
        + 'python "$REPO_ROOT/scripts/check_ghost.py" || exit 1\n'
        + 'python "$REPO_ROOT/scripts/check_ghost.py" --again || exit 1\n',
    )

    result, passed = run(repo)

    assert passed is True
    assert result["dead_references"] == ["check_ghost.py"]


def test_non_python_references_are_ignored(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        "\n".join(
            [
                'bash "$REPO_ROOT/scripts/check_ledger_schema.py"',
                'python "$REPO_ROOT/scripts/genome_guard.py"',
                'python "$REPO_ROOT/scripts/check_invariant.py"',
            ]
        ) + "\n",
    )

    result, passed = run(repo)

    assert passed is False
    assert result["missing_mandatory"] == ["check_ledger_schema.py"]


def test_python_substring_command_is_ignored(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        "\n".join(
            [
                'mypython "$REPO_ROOT/scripts/check_ledger_schema.py"',
                'python "$REPO_ROOT/scripts/genome_guard.py"',
                'python "$REPO_ROOT/scripts/check_invariant.py"',
            ]
        ) + "\n",
    )

    result, passed = run(repo)

    assert passed is False
    assert result["missing_mandatory"] == ["check_ledger_schema.py"]


def test_line_continuation_is_parsed(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(
        repo,
        "\n".join(
            [
                'python \\',
                '  "$REPO_ROOT/scripts/genome_guard.py" --files $GENOME_FILES || exit 1',
                'python "$REPO_ROOT/scripts/check_invariant.py" || exit 1',
                'python "$REPO_ROOT/scripts/check_ledger_schema.py" || exit 1',
            ]
        ) + "\n",
    )

    result, passed = run(repo)

    assert passed is True
    assert result["status"] == "PASS"


def test_parse_invoked_scripts_preserves_first_seen_order() -> None:
    hook_text = "\n".join(
        [
            'python "$REPO_ROOT/scripts/check_invariant.py" || exit 1',
            'python "$REPO_ROOT/scripts/genome_guard.py" || exit 1',
            'python "$REPO_ROOT/scripts/check_invariant.py" || exit 1',
        ]
    )

    assert parse_invoked_scripts(hook_text) == [
        "check_invariant.py",
        "genome_guard.py",
    ]


def test_subprocess_exit_zero_and_json_on_pass(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(repo, _mandatory_hook())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["missing_mandatory"] == []


def test_subprocess_exit_one_on_fail(precommit_repo: Path) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(repo, 'python "$REPO_ROOT/scripts/genome_guard.py" || exit 1\n')

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["missing_mandatory"] == [
        "check_invariant.py",
        "check_ledger_schema.py",
    ]


def test_current_repo_hook_passes() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    result, passed = run(repo_root)

    assert passed is True
    assert result["status"] == "PASS"


@pytest.mark.parametrize("payload", [None, "", _mandatory_hook()])
def test_forwarded_hook_requires_the_actual_safety_checks(precommit_repo: Path, payload: str | None) -> None:
    repo = precommit_repo
    _write_mandatory_scripts(repo)
    _write_hook(repo, 'exec bash "$REPO_ROOT/gunnery/hooks/pre-commit" "$@"\n')
    if payload is not None:
        target = repo / "gunnery" / "hooks" / "pre-commit"
        target.parent.mkdir(parents=True)
        target.write_text(payload, encoding="utf-8")
    result, passed = run(repo)
    assert passed is bool(payload)
    assert result["status"] == ("PASS" if payload else "FAIL")
