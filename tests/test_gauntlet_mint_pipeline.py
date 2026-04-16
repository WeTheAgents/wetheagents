"""End-to-end tests for the gauntlet mint ledger pipeline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "src" / "wea_cli" / "cli.py"
CONSISTENCY_CHECK = REPO_ROOT / "scripts" / "check_trajectory_mint_consistency.py"
SANDBOX_ROOT = REPO_ROOT / "codex19-tmp-397"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sandbox_root() -> Path:
    SANDBOX_ROOT.mkdir(exist_ok=True)
    root = SANDBOX_ROOT / uuid.uuid4().hex
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _make_repo(root: Path) -> Path:
    ledger = root / "ledger"
    ledger.mkdir()
    _write_json(
        ledger / "balances.json",
        {
            "version": 1,
            "last_updated": "2026-04-10T00:00:00Z",
            "agents": {
                "agent0@system": {"balance": 10000, "total_earned": 0},
                "Alpha-1@codex": {"balance": 0, "total_earned": 0},
                "Beta-2@claude": {"balance": 0, "total_earned": 0},
                "Gamma-3@cursor": {"balance": 0, "total_earned": 0},
            },
        },
    )
    _write_json(ledger / "escrows.json", {"version": 1, "active": {}})
    _write_json(ledger / "idem_keys.json", {"keys": {}})
    return root


def _run(args: list[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _mint(
    root: Path,
    *,
    trajectory: str = "T2",
    slot: int = 1,
    agents: list[str] | None = None,
    issue: int = 397,
) -> subprocess.CompletedProcess[str]:
    agents = agents or ["Alpha-1@codex"]
    return _run(
        [
            str(CLI),
            "--root",
            str(root),
            "gauntlet",
            "mint",
            trajectory,
            str(slot),
            *agents,
            "--issue",
            str(issue),
            "--frontier",
            f"{trajectory} slot {slot} mint pipeline covered end to end",
            "--artifact",
            "tests/test_gauntlet_mint_pipeline.py",
            "--evidence",
            (
                "pytest integration fixture validates mint, ledger write, "
                "and consistency check"
            ),
            "--made-redundant",
            "Manual inspection of trajectory_mints.json after gauntlet mint",
            "--redundancy-proof",
            (
                "The test executes the mint command and then runs a ledger "
                "consistency check against the produced fixture."
            ),
            "--agent",
            "agent0@system",
        ]
    )


def _run_consistency(root: Path) -> subprocess.CompletedProcess[str]:
    return _run([str(CONSISTENCY_CHECK), "--root", str(root)])


def _load_mints(root: Path) -> dict:
    return _read_json(root / "ledger" / "trajectory_mints.json")


def _write_mints(root: Path, payload: dict) -> None:
    _write_json(root / "ledger" / "trajectory_mints.json", payload)


def _minted_repo(root: Path) -> Path:
    _make_repo(root)
    result = _mint(root)
    assert result.returncode == 0, result.stdout + result.stderr
    return root


def test_happy_path_updates_mints_and_passes_check(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)

    mints = _load_mints(root)
    assert mints["total_minted"] == 20
    assert mints["trajectories"]["T2"]["next_slot"] == 2
    assert mints["trajectories"]["T2"]["total_minted"] == 20
    assert mints["mints"][0]["idem_key"] == "trajectory_mint|T2|1"

    check = _run_consistency(root)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "PASS" in check.stdout


def test_mint_record_preserves_all_gauntlet_pr_fields(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)

    record = _load_mints(root)["mints"][0]
    for field in (
        "frontier_closed",
        "artifact",
        "evidence",
        "made_redundant",
        "redundancy_proof",
    ):
        assert record[field]


def test_mint_writes_matching_idem_key_and_history_event(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)

    idem = _read_json(root / "ledger" / "idem_keys.json")
    assert "trajectory_mint|T2|1" in idem["keys"]

    history_events = []
    for history_file in sorted((root / "ledger" / "history").glob("*.jsonl")):
        lines = history_file.read_text(encoding="utf-8").splitlines()
        history_events.extend(json.loads(line) for line in lines)

    assert history_events == [
        {
            "type": "trajectory_mint",
            "trajectory": "T2",
            "slot": 1,
            "amount": 20,
            "agents": ["Alpha-1@codex"],
            "per_agent": [20],
            "issue": 397,
            "timestamp": history_events[0]["timestamp"],
        }
    ]


def test_duplicate_slot_mint_is_blocked_without_writes(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)
    mints_path = root / "ledger" / "trajectory_mints.json"
    balances_path = root / "ledger" / "balances.json"
    before_mints = mints_path.read_text(encoding="utf-8")
    before_balances = balances_path.read_text(encoding="utf-8")

    duplicate = _mint(root)

    assert duplicate.returncode == 1
    assert "Slot must be 2" in duplicate.stdout
    assert mints_path.read_text(encoding="utf-8") == before_mints
    assert balances_path.read_text(encoding="utf-8") == before_balances


def test_two_agent_split_assigns_remainder_to_first_agent(sandbox_root: Path) -> None:
    root = _make_repo(sandbox_root)
    assert _mint(root).returncode == 0

    result = _mint(
        root,
        slot=2,
        agents=["Alpha-1@codex", "Beta-2@claude"],
        issue=398,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = _load_mints(root)["mints"][1]
    assert record["amount"] == 21
    assert record["agents"] == ["Alpha-1@codex", "Beta-2@claude"]
    assert record["per_agent"] == [11, 10]
    assert _run_consistency(root).returncode == 0


def test_three_agent_split_is_equal_for_divisible_amount(sandbox_root: Path) -> None:
    root = _make_repo(sandbox_root)
    assert _mint(root).returncode == 0

    result = _mint(
        root,
        slot=2,
        agents=["Alpha-1@codex", "Beta-2@claude", "Gamma-3@cursor"],
        issue=399,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = _load_mints(root)["mints"][1]
    assert record["amount"] == 21
    assert record["per_agent"] == [7, 7, 7]
    assert _run_consistency(root).returncode == 0


def test_consistency_check_catches_total_minted_drift(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)
    mints = _load_mints(root)
    mints["total_minted"] = 21
    _write_mints(root, mints)

    check = _run_consistency(root)

    assert check.returncode == 1
    assert "total_minted mismatch" in check.stdout


def test_consistency_check_catches_amount_disagreement(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)
    mints = _load_mints(root)
    mints["mints"][0]["amount"] = 19  # history says 20, mints says 19
    _write_mints(root, mints)

    check = _run_consistency(root)

    assert check.returncode == 1
    assert "amount mismatch" in check.stdout


def test_consistency_check_catches_orphan_mint_entry(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)
    mints = _load_mints(root)
    # Inject a mint record with no corresponding history event
    mints["mints"].append({
        "trajectory": "T3",
        "slot": 1,
        "amount": 20,
        "agents": ["Alpha-1@codex"],
        "per_agent": [20],
        "idem_key": "trajectory_mint|T3|1",
    })
    _write_mints(root, mints)

    check = _run_consistency(root)

    assert check.returncode == 1
    assert "orphan mints entry" in check.stdout


def test_consistency_check_catches_per_agent_sum_mismatch(sandbox_root: Path) -> None:
    root = _minted_repo(sandbox_root)
    mints = _load_mints(root)
    mints["mints"][0]["per_agent"] = [15]  # sum=15 != amount=20
    _write_mints(root, mints)

    check = _run_consistency(root)

    assert check.returncode == 1
    assert "per_agent sum mismatch" in check.stdout
