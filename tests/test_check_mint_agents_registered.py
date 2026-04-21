"""Tests for scripts/check_mint_agents_registered.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_mint_agents_registered import (
    find_unregistered_mint_agents,
    get_mints,
    get_registered_agent_ids,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_mint_agents_registered.py"
)
TEMP_ROOT = Path(".test_runs") / "check_mint_agents_registered"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _mint(
    *,
    trajectory: str = "T3",
    slot: int = 1,
    idem_key: str = "trajectory_mint|T3|1",
    agents: list[object] | None = None,
) -> dict[str, object]:
    return {
        "trajectory": trajectory,
        "slot": slot,
        "idem_key": idem_key,
        "agents": agents if agents is not None else ["Codex-19@codex", "Claude-1@claude"],
    }


def _make_repo(
    tmp_path: Path,
    *,
    balances_agents: dict[str, dict[str, object]] | None = None,
    mints: list[object] | None = None,
    trajectory_top_level: dict[str, object] | None = None,
) -> Path:
    _write_json(
        tmp_path / "ledger" / "balances.json",
        {
            "version": 1,
            "agents": balances_agents
            or {
                "Codex-19@codex": {"balance": 10},
                "Claude-1@claude": {"balance": 20},
                "gemini-4@google": {"balance": 30},
            },
        },
    )
    payload: dict[str, object] = {
        "version": 1,
        "mints": mints if mints is not None else [_mint()],
    }
    if trajectory_top_level:
        payload.update(trajectory_top_level)
    _write_json(tmp_path / "ledger" / "trajectory_mints.json", payload)
    return tmp_path


@pytest.fixture
def case_root() -> Path:
    root = TEMP_ROOT / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def tmp_path(case_root: Path) -> Path:
    return case_root


def test_get_registered_agent_ids_requires_agents_object() -> None:
    try:
        get_registered_agent_ids({"agents": []})
    except ValueError as exc:
        assert str(exc) == "balances.json must contain an object at key 'agents'"
    else:
        raise AssertionError("Expected ValueError")


def test_get_mints_requires_top_level_list() -> None:
    try:
        get_mints({"mints": {}})
    except ValueError as exc:
        assert str(exc) == "trajectory_mints.json must contain a list at key 'mints'"
    else:
        raise AssertionError("Expected ValueError")


def test_find_unregistered_mint_agents_passes_when_all_agents_registered() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [_mint(agents=["Claude-1@claude", "Codex-19@codex"])],
        {"Claude-1@claude", "Codex-19@codex"},
    )

    assert violations == []
    assert agent_refs_checked == 2


def test_find_unregistered_mint_agents_reports_unknown_agent_with_context() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [_mint(trajectory="T6", slot=4, idem_key="trajectory_mint|T6|4", agents=["Codex-19@codex", "Ghost-9@void"])],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 2
    assert violations == [
        {
            "mint_index": 0,
            "trajectory": "T6",
            "slot": 4,
            "idem_key": "trajectory_mint|T6|4",
            "agent_index": 1,
            "agent": "Ghost-9@void",
            "reason": "agent not found in balances.json",
        }
    ]


def test_find_unregistered_mint_agents_flags_non_dict_entry() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        ["not-a-dict"],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 0
    assert violations == [
        {
            "mint_index": 0,
            "reason": "trajectory_mints.json mints[0] must be an object",
        }
    ]


def test_find_unregistered_mint_agents_flags_non_list_agents_field() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [{"trajectory": "T3", "slot": 1, "idem_key": "trajectory_mint|T3|1", "agents": "Codex-19@codex"}],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 0
    assert violations == [
        {
            "mint_index": 0,
            "trajectory": "T3",
            "slot": 1,
            "idem_key": "trajectory_mint|T3|1",
            "reason": "trajectory_mints.json mints[0].agents must be a list",
        }
    ]


def test_find_unregistered_mint_agents_flags_non_string_agent_id() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [_mint(agents=["Codex-19@codex", 123])],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 2
    assert violations == [
        {
            "mint_index": 0,
            "trajectory": "T3",
            "slot": 1,
            "idem_key": "trajectory_mint|T3|1",
            "agent_index": 1,
            "agent": 123,
            "reason": "trajectory_mints.json mints[0].agents[1] must be a string",
        }
    ]


def test_find_unregistered_mint_agents_flags_blank_agent_id() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [_mint(agents=["Codex-19@codex", "   "])],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 2
    assert violations == [
        {
            "mint_index": 0,
            "trajectory": "T3",
            "slot": 1,
            "idem_key": "trajectory_mint|T3|1",
            "agent_index": 1,
            "agent": "   ",
            "reason": "trajectory_mints.json mints[0].agents[1] must be a non-empty string",
        }
    ]


def test_find_unregistered_mint_agents_flags_blank_agent_id() -> None:
    violations, agent_refs_checked = find_unregistered_mint_agents(
        [_mint(agents=["Codex-19@codex", "   "])],
        {"Codex-19@codex"},
    )

    assert agent_refs_checked == 2
    assert violations == [
        {
            "mint_index": 0,
            "trajectory": "T3",
            "slot": 1,
            "idem_key": "trajectory_mint|T3|1",
            "agent_index": 1,
            "agent": "   ",
            "reason": "trajectory_mints.json mints[0].agents[1] must be a non-empty string",
        }
    ]


def test_run_check_passes_for_clean_repo(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        mints=[
            _mint(trajectory="T3", slot=1, idem_key="trajectory_mint|T3|1"),
            _mint(
                trajectory="T4",
                slot=2,
                idem_key="trajectory_mint|T4|2",
                agents=["gemini-4@google"],
            ),
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["mints_checked"] == 2
    assert report["summary"]["agent_refs_checked"] == 3
    assert report["summary"]["violations"] == 0
    assert report["violations"] == []


def test_run_check_fails_when_unknown_agent_present(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        mints=[_mint(agents=["Codex-19@codex", "Ghost-9@void"])],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["summary"]["unregistered_agent_refs"] == 1
    assert report["violations"][0]["agent"] == "Ghost-9@void"


def test_run_check_fails_when_balances_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "trajectory_mints.json", {"version": 1, "mints": [_mint()]})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["summary"]["input_errors"] == 1
    assert report["violations"] == [{"reason": "balances.json not found"}]


def test_run_check_fails_when_trajectory_mints_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "balances.json", {"version": 1, "agents": {}})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["violations"] == [{"reason": "trajectory_mints.json not found"}]


def test_run_check_fails_when_mints_key_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "balances.json", {"version": 1, "agents": {}})
    _write_json(case_root / "ledger" / "trajectory_mints.json", {"version": 1})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["violations"] == [
        {"reason": "trajectory_mints.json must contain a list at key 'mints'"}
    ]


def test_run_check_fails_on_invalid_balances_json(case_root: Path) -> None:
    balances_path = case_root / "ledger" / "balances.json"
    balances_path.parent.mkdir(parents=True, exist_ok=True)
    balances_path.write_text("{not-json", encoding="utf-8")
    _write_json(case_root / "ledger" / "trajectory_mints.json", {"version": 1, "mints": [_mint()]})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert "balances.json contains invalid JSON:" in report["violations"][0]["reason"]


def test_main_emits_fail_json(case_root: Path, capsys) -> None:
    root = _make_repo(
        case_root,
        mints=[_mint(agents=["Ghost-9@void"])],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["violations"][0]["agent"] == "Ghost-9@void"


def test_cli_returns_exit_code_one_for_unknown_agent(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        mints=[_mint(agents=["Ghost-9@void"])],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["violations"][0]["agent"] == "Ghost-9@void"


def test_real_ledger_passes() -> None:
    root = Path(__file__).resolve().parent.parent

    report, exit_code = run_check(root)

    assert exit_code == 0, json.dumps(report, indent=2)
    assert report["status"] == "PASS"
