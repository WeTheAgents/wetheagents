"""Tests for scripts/check_zombie_genomes.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scripts.check_zombie_genomes import run


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_zombie_genomes.py"


@pytest.fixture
def repo_tmp_path() -> Path:
    base_root = Path(r"C:\Users\peach\AppData\Local\Temp\zombie-genomes-fixed")
    base_root.mkdir(parents=True, exist_ok=True)
    base = base_root / f"case-{uuid.uuid4().hex}"
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _make_repo(tmp_path: Path, agents: dict[str, object] | None) -> Path:
    if agents is not None:
        ledger = tmp_path / "ledger"
        ledger.mkdir(parents=True, exist_ok=True)
        balances = {"version": 1, "agents": agents}
        (ledger / "balances.json").write_text(json.dumps(balances), encoding="utf-8")

    (tmp_path / "genomes").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_genome_dir(root: Path, name: str) -> None:
    (root / "genomes" / name).mkdir(parents=True, exist_ok=True)


def _run_cli(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_passes_when_all_genome_dirs_are_registered(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {
        "agent0@system": {},
        "Codex-19@codex": {},
        "Claude-18@claude": {},
    })
    _make_genome_dir(root, "base")
    _make_genome_dir(root, "Codex-19@codex")
    _make_genome_dir(root, "Claude-18@claude")
    (root / "genomes" / "README.txt").write_text("ignore me\n", encoding="utf-8")

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"
    assert result["zombies"] == []
    assert "2 genome dirs checked" in result["summary"]


def test_fails_when_unregistered_genome_dir_exists(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {"Codex-19@codex": {}})
    _make_genome_dir(root, "Codex-19@codex")
    _make_genome_dir(root, "ghost@void")

    result, passed = run(root)

    assert passed is False
    assert result["status"] == "FAIL"
    assert len(result["zombies"]) == 1
    zombie = result["zombies"][0]
    assert zombie["agent_dir"] == "ghost@void"
    assert zombie["path"] == "genomes/ghost@void"


def test_reports_multiple_zombies_in_sorted_order(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {"Codex-19@codex": {}})
    _make_genome_dir(root, "zzz@late")
    _make_genome_dir(root, "aaa@early")

    result, passed = run(root)

    assert passed is False
    assert [z["agent_dir"] for z in result["zombies"]] == ["aaa@early", "zzz@late"]


def test_skips_base_directory(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {"Codex-19@codex": {}})
    _make_genome_dir(root, "base")

    result, passed = run(root)

    assert passed is True
    assert result["zombies"] == []


def test_missing_balances_json_fails_cleanly(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, None)

    result, passed = run(root)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "balances.json not found" in result["summary"]


def test_invalid_balances_json_fails_cleanly(repo_tmp_path: Path) -> None:
    ledger = repo_tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text("{not json", encoding="utf-8")
    (repo_tmp_path / "genomes").mkdir(parents=True, exist_ok=True)

    result, passed = run(repo_tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "not valid JSON" in result["summary"]


def test_non_dict_agents_section_fails_cleanly(repo_tmp_path: Path) -> None:
    ledger = repo_tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text(
        json.dumps({"version": 1, "agents": ["Codex-19@codex"]}),
        encoding="utf-8",
    )
    (repo_tmp_path / "genomes").mkdir(parents=True, exist_ok=True)

    result, passed = run(repo_tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "'agents' is not a dictionary" in result["summary"]


def test_non_dict_balances_top_level_fails_cleanly(repo_tmp_path: Path) -> None:
    ledger = repo_tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text(
        json.dumps(["Codex-19@codex"]),
        encoding="utf-8",
    )
    (repo_tmp_path / "genomes").mkdir(parents=True, exist_ok=True)

    result, passed = run(repo_tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "top-level value is not an object" in result["summary"]


def test_cli_returns_nonzero_and_json_when_zombie_found(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {"Codex-19@codex": {}})
    _make_genome_dir(root, "ghost@void")

    proc = _run_cli(root)

    payload = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["zombies"][0]["agent_dir"] == "ghost@void"


def test_cli_returns_zero_and_json_when_clean(repo_tmp_path: Path) -> None:
    root = _make_repo(repo_tmp_path, {"Codex-19@codex": {}})
    _make_genome_dir(root, "Codex-19@codex")

    proc = _run_cli(root)

    payload = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["zombies"] == []
