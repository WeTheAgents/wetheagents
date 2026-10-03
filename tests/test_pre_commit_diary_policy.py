"""Exercise diary policy retirement without weakening other hook dispatch."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"


def _shell_path(path: Path) -> str:
    text = path.resolve().as_posix()
    if os.name == "nt" and path.drive:
        return "/" + text[0].lower() + text[2:]
    return text


def _run_hook(tmp_path: Path, files: dict[str, str], fail: str = ""):
    git = shutil.which("git")
    assert git is not None
    if os.name == "nt":
        bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if not bash.is_file():
            pytest.skip("Git Bash is unavailable")
    else:
        found = shutil.which("bash")
        if found is None:
            pytest.skip("Bash is unavailable")
        bash = Path(found)
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run([git, "-C", str(tmp_path), "add", "--", *files], check=True)
    tools = tmp_path / "fake-bin"
    tools.mkdir()
    python = tools / "python"
    python.write_text(
        '#!/bin/sh\nname="${1##*/}"\n'
        'printf "%s\\n" "$name" >> "$CHECK_LOG"\n'
        'if [ "$name" = "censor_diary.py" ] || '
        '[ "$name" = "$FAIL_CHECK" ]; then exit 1; fi\nexit 0\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    env = dict(
        os.environ,
        TEST_BIN=_shell_path(tools),
        HOOK_FILE=_shell_path(HOOK),
        BASH_EXE=_shell_path(bash),
        CHECK_LOG=_shell_path(tmp_path / "checks.log"),
        FAIL_CHECK=fail,
    )
    result = subprocess.run(
        [
            str(bash),
            "-c",
            'export PATH="$TEST_BIN:$PATH"; exec "$BASH_EXE" "$HOOK_FILE"',
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    log = tmp_path / "checks.log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


def test_diary_vocabulary_no_longer_blocks_commit(tmp_path: Path) -> None:
    result, calls = _run_hook(
        tmp_path,
        {"agent0_diary/current.md": "genome mutation; local path/contact allowed\n"},
    )
    assert result.returncode == 0, result.stderr
    assert calls == ["check_doc_sync.py"]


@pytest.mark.parametrize(
    ("path", "checker"),
    [
        ("ledger/balances.json", "check_invariant.py"),
        ("genomes/example/AGENTS.local.md", "genome_guard.py"),
    ],
)
def test_other_guards_still_block(tmp_path: Path, path: str, checker: str) -> None:
    result, calls = _run_hook(tmp_path, {path: "fixture\n"}, fail=checker)
    assert result.returncode == 1, result.stderr
    assert calls == [checker]


def test_history_and_document_checks_remain(tmp_path: Path) -> None:
    result, calls = _run_hook(
        tmp_path,
        {
            "ledger/history/2026-10-03.jsonl": "fixture\n",
            "agent0_diary/current.md": "genome\n",
        },
    )
    assert result.returncode == 0, result.stderr
    assert calls == [
        "check_invariant.py",
        "check_ledger_schema.py",
        "check_doc_sync.py",
        "check_history_jsonl_integrity.py",
        "check_history_file_date_consistency.py",
    ]
