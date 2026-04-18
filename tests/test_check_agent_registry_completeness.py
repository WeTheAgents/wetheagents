"""Tests for scripts/check_agent_registry_completeness.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_agent_registry_completeness import (
    EXEMPT_AGENT,
    build_report,
    find_missing_register_keys,
    get_agent_ids,
    get_nested_idem_keys,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_agent_registry_completeness.py"
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def case_root() -> Path:
    root = Path(".test_runs") / "check_agent_registry_completeness" / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _make_repo(
    tmp_path: Path,
    *,
    agents: dict[str, dict] | None = None,
    idem_keys: dict[str, object] | None = None,
    top_level_idem: dict[str, object] | None = None,
) -> Path:
    root = tmp_path
    _write_json(
        root / "ledger" / "balances.json",
        {
            "version": 1,
            "agents": agents
            or {
                EXEMPT_AGENT: {"balance": 1000},
                "Codex-19@codex": {"balance": 10},
                "Claude-1@claude": {"balance": 20},
            },
        },
    )
    payload: dict[str, object] = {"version": 1, "keys": idem_keys or {}}
    if top_level_idem:
        payload.update(top_level_idem)
    _write_json(root / "ledger" / "idem_keys.json", payload)
    return root


def test_get_agent_ids_returns_sorted_ids() -> None:
    agent_ids = get_agent_ids(
        {"agents": {"b@test": {}, EXEMPT_AGENT: {}, "a@test": {}}}
    )

    assert agent_ids == ["a@test", EXEMPT_AGENT, "b@test"]


def test_get_agent_ids_requires_agents_object() -> None:
    try:
        get_agent_ids({"agents": []})
    except ValueError as exc:
        assert "balances.json must contain an object at key 'agents'" == str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_get_nested_idem_keys_requires_nested_keys_object() -> None:
    try:
        get_nested_idem_keys({"keys": []})
    except ValueError as exc:
        assert "idem_keys.json must contain an object at key 'keys'" == str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_find_missing_register_keys_passes_when_all_non_exempt_agents_registered() -> None:
    missing = find_missing_register_keys(
        [EXEMPT_AGENT, "Codex-19@codex", "Claude-1@claude"],
        {
            "register|Codex-19@codex": "2026-03-27T13:05:23Z",
            "register|Claude-1@claude": "2026-03-07T12:00:04Z",
        },
    )

    assert missing == []


def test_find_missing_register_keys_exempts_agent0() -> None:
    missing = find_missing_register_keys([EXEMPT_AGENT], {})

    assert missing == []


def test_find_missing_register_keys_reports_single_missing_agent() -> None:
    missing = find_missing_register_keys(
        [EXEMPT_AGENT, "Codex-19@codex", "Claude-1@claude"],
        {"register|Codex-19@codex": "2026-03-27T13:05:23Z"},
    )

    assert missing == ["Claude-1@claude"]


def test_find_missing_register_keys_reports_multiple_missing_agents_sorted() -> None:
    missing = find_missing_register_keys(
        [EXEMPT_AGENT, "z@test", "a@test", "m@test"],
        {"register|m@test": "2026-04-01T00:00:00Z"},
    )

    assert missing == ["a@test", "z@test"]


def test_build_report_formats_missing_keys() -> None:
    report = build_report(
        agent_ids=[EXEMPT_AGENT, "Codex-19@codex", "Claude-1@claude"],
        missing_agents=["Claude-1@claude"],
    )

    assert report["status"] == "FAIL"
    assert report["summary"]["agents_checked"] == 2
    assert report["violations"] == [
        {
            "agent": "Claude-1@claude",
            "missing_key": "register|Claude-1@claude",
        }
    ]


def test_run_check_passes_for_clean_repo(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        idem_keys={
            "register|Codex-19@codex": "2026-03-27T13:05:23Z",
            "register|Claude-1@claude": "2026-03-07T12:00:04Z",
        },
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["summary"]["missing_register_keys"] == 0
    assert report["violations"] == []


def test_run_check_fails_when_register_key_missing(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        idem_keys={"register|Codex-19@codex": "2026-03-27T13:05:23Z"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["summary"]["missing_register_keys"] == 1
    assert report["violations"][0]["agent"] == "Claude-1@claude"


def test_run_check_ignores_top_level_register_key(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        idem_keys={"register|Codex-19@codex": "2026-03-27T13:05:23Z"},
        top_level_idem={"register|Claude-1@claude": "2026-03-07T12:00:04Z"},
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"] == [
        {
            "agent": "Claude-1@claude",
            "missing_key": "register|Claude-1@claude",
        }
    ]


def test_run_check_fails_when_balances_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "idem_keys.json", {"version": 1, "keys": {}})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["violations"] == [{"reason": "balances.json not found"}]


def test_run_check_fails_when_idem_keys_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "balances.json", {"version": 1, "agents": {}})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert report["violations"] == [{"reason": "idem_keys.json not found"}]


def test_run_check_fails_on_invalid_balances_json(case_root: Path) -> None:
    balances_path = case_root / "ledger" / "balances.json"
    balances_path.parent.mkdir(parents=True, exist_ok=True)
    balances_path.write_text("{not-json", encoding="utf-8")
    _write_json(case_root / "ledger" / "idem_keys.json", {"version": 1, "keys": {}})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert "balances.json contains invalid JSON:" in report["violations"][0]["reason"]


def test_run_check_fails_when_nested_keys_missing(case_root: Path) -> None:
    _write_json(case_root / "ledger" / "balances.json", {"version": 1, "agents": {}})
    _write_json(case_root / "ledger" / "idem_keys.json", {"version": 1})

    report, exit_code = run_check(case_root)

    assert exit_code == 1
    assert report["violations"] == [
        {"reason": "idem_keys.json must contain an object at key 'keys'"}
    ]


def test_main_emits_pass_json(case_root: Path, capsys) -> None:
    root = _make_repo(
        case_root,
        idem_keys={
            "register|Codex-19@codex": "2026-03-27T13:05:23Z",
            "register|Claude-1@claude": "2026-03-07T12:00:04Z",
        },
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_main_emits_fail_json(case_root: Path, capsys) -> None:
    root = _make_repo(
        case_root,
        idem_keys={"register|Codex-19@codex": "2026-03-27T13:05:23Z"},
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["summary"]["missing_register_keys"] == 1


def test_cli_returns_exit_code_one_for_missing_registration(case_root: Path) -> None:
    root = _make_repo(
        case_root,
        idem_keys={"register|Codex-19@codex": "2026-03-27T13:05:23Z"},
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["violations"][0]["agent"] == "Claude-1@claude"
