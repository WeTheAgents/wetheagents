"""Tests for scripts/check_orphan_genome_dirs.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_orphan_genome_dirs import (
    build_report,
    find_missing_genome_dirs,
    find_orphan_genome_dirs,
    main,
    requires_genome_dir,
    run_check,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_orphan_genome_dirs.py"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_repo(tmp_path: Path, *, agents: dict[str, dict] | None = None) -> Path:
    if agents is not None:
        _write_json(
            tmp_path / "ledger" / "balances.json",
            {
                "version": 1,
                "agents": agents,
            },
        )
    (tmp_path / "genomes").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_genome_dir(root: Path, name: str) -> None:
    (root / "genomes" / name).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def case_root() -> Path:
    root = Path(r"C:\Users\peach\AppData\Local\Temp\check-orphan-genome-dirs") / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_requires_genome_dir_only_for_positive_metrics() -> None:
    assert requires_genome_dir({"tasks_completed": 1, "total_earned": 0}) is True
    assert requires_genome_dir({"tasks_completed": 0, "total_earned": 5}) is True
    assert requires_genome_dir({"tasks_completed": 0, "total_earned": 0}) is False
    assert requires_genome_dir({"tasks_completed": False, "total_earned": False}) is False


def test_find_orphan_genome_dirs_returns_sorted_missing_registrations() -> None:
    orphans = find_orphan_genome_dirs(
        {"Codex-2@codex"},
        ["Claude-18@claude", "Codex-2@codex", "ghost@void"],
    )

    assert orphans == ["Claude-18@claude", "ghost@void"]


def test_find_missing_genome_dirs_reports_agents_requiring_genomes() -> None:
    missing = find_missing_genome_dirs(
        {
            "agent0@system": {"tasks_completed": 99, "total_earned": 500},
            "Codex-2@codex": {"tasks_completed": 1, "total_earned": 0},
            "Claude-18@claude": {"tasks_completed": 0, "total_earned": 25},
            "cursor-3@cursor": {"tasks_completed": 0, "total_earned": 0},
        },
        {"Codex-2@codex"},
    )

    assert missing == [
        {
            "agent": "Claude-18@claude",
            "expected_path": "genomes/Claude-18@claude",
            "tasks_completed": 0,
            "total_earned": 25,
        }
    ]


def test_run_check_passes_when_repo_is_consistent(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={
            "agent0@system": {"tasks_completed": 0, "total_earned": 500},
            "Codex-2@codex": {"tasks_completed": 1, "total_earned": 0},
            "Claude-18@claude": {"tasks_completed": 0, "total_earned": 25},
            "cursor-3@cursor": {"tasks_completed": 0, "total_earned": 0},
        },
    )
    _make_genome_dir(root, "base")
    _make_genome_dir(root, "Codex-2@codex")
    _make_genome_dir(root, "Claude-18@claude")
    (root / "genomes" / "README.txt").write_text("ignore me\n", encoding="utf-8")

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["orphan_genome_dirs"] == []
    assert report["missing_genome_dirs"] == []
    assert report["summary"] == {
        "registered_agents": 4,
        "genome_dirs_scanned": 2,
        "agents_requiring_genomes": 2,
        "orphan_genome_dirs": 0,
        "missing_genome_dirs": 0,
        "exempt_agents": ["agent0@system"],
        "skipped_genome_dirs": ["base"],
    }


def test_run_check_fails_for_orphan_genome_dir(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={"Codex-2@codex": {"tasks_completed": 1, "total_earned": 0}},
    )
    _make_genome_dir(root, "Codex-2@codex")
    _make_genome_dir(root, "ghost@void")

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["orphan_genome_dirs"] == [
        {"agent_dir": "ghost@void", "path": "genomes/ghost@void"}
    ]
    assert report["missing_genome_dirs"] == []


def test_run_check_fails_for_missing_required_genome_dir(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={
            "Codex-2@codex": {"tasks_completed": 0, "total_earned": 10},
            "Claude-18@claude": {"tasks_completed": 2, "total_earned": 0},
        },
    )
    _make_genome_dir(root, "Codex-2@codex")

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["orphan_genome_dirs"] == []
    assert report["missing_genome_dirs"] == [
        {
            "agent": "Claude-18@claude",
            "expected_path": "genomes/Claude-18@claude",
            "tasks_completed": 2,
            "total_earned": 0,
        }
    ]


def test_run_check_reports_sorted_failures(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={
            "z@agent": {"tasks_completed": 2, "total_earned": 0},
            "a@agent": {"tasks_completed": 0, "total_earned": 3},
            "m@agent": {"tasks_completed": 0, "total_earned": 0},
        },
    )
    _make_genome_dir(root, "zzz@orphan")
    _make_genome_dir(root, "aaa@orphan")

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert [entry["agent_dir"] for entry in report["orphan_genome_dirs"]] == [
        "aaa@orphan",
        "zzz@orphan",
    ]
    assert [entry["agent"] for entry in report["missing_genome_dirs"]] == [
        "a@agent",
        "z@agent",
    ]


def test_run_check_skips_agent0_missing_genome(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={"agent0@system": {"tasks_completed": 3, "total_earned": 1200}},
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["missing_genome_dirs"] == []


def test_run_check_fails_when_balances_missing(case_root: Path) -> None:
    root = _make_repo(case_root, agents=None)

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["errors"] == [{"reason": "balances.json not found"}]


def test_run_check_fails_on_invalid_balances_json(case_root: Path) -> None:
    ledger = case_root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text("{not-json", encoding="utf-8")
    (case_root / "genomes").mkdir(parents=True, exist_ok=True)

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["errors"][0]["reason"].startswith("balances.json contains invalid JSON:")


def test_build_report_includes_error_without_violations() -> None:
    report = build_report(
        agents={},
        genome_dirs=[],
        orphan_genome_dirs=[],
        missing_genome_dirs=[],
        error="balances.json not found",
    )

    assert report["status"] == "FAIL"
    assert report["orphan_genome_dirs"] == []
    assert report["missing_genome_dirs"] == []
    assert report["errors"] == [{"reason": "balances.json not found"}]


def test_main_emits_pass_json(case_root: Path, capsys) -> None:
    root = _make_repo(
        case_root,
        agents={"Codex-2@codex": {"tasks_completed": 1, "total_earned": 0}},
    )
    _make_genome_dir(root, "Codex-2@codex")

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_cli_returns_exit_code_one_and_json_for_fail(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        agents={"Codex-2@codex": {"tasks_completed": 1, "total_earned": 0}},
    )
    _make_genome_dir(root, "ghost@void")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["orphan_genome_dirs"] == [
        {"agent_dir": "ghost@void", "path": "genomes/ghost@void"}
    ]
