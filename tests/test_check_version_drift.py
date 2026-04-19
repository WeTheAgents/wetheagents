"""Tests for scripts/check_version_drift.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.check_version_drift as check_version_drift


ROOT = Path("D:/fake/repo")


def _iso(year: int, month: int, day: int, hour: int, minute: int = 0) -> str:
    dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _epoch(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _patch_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_files: dict[str, dict[str, object]],
    history_by_path: dict[str, list[tuple[str, int]]],
    committed_files: dict[tuple[str, str], dict[str, object]],
) -> None:
    def fake_list_versioned(_root: Path) -> list[str]:
        return sorted(
            rel_path
            for rel_path, data in current_files.items()
            if isinstance(data, dict) and "version" in data
        )

    def fake_load_worktree_json(path: Path) -> dict[str, object]:
        rel_path = path.relative_to(ROOT).as_posix()
        return current_files[rel_path]

    def fake_git_log(_root: str, rel_path: str) -> tuple[tuple[str, int], ...]:
        return tuple(history_by_path.get(rel_path, []))

    def fake_git_show_json(_root: str, commit: str, rel_path: str) -> dict[str, object]:
        return committed_files[(rel_path, commit)]

    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == ROOT / check_version_drift.BALANCES_PATH:
            return check_version_drift.BALANCES_PATH in current_files
        return original_exists(path)

    monkeypatch.setattr(check_version_drift, "list_versioned_ledger_files", fake_list_versioned)
    monkeypatch.setattr(check_version_drift, "_load_worktree_json", fake_load_worktree_json)
    monkeypatch.setattr(check_version_drift, "_git_log", fake_git_log)
    monkeypatch.setattr(check_version_drift, "_git_show_json", fake_git_show_json)
    monkeypatch.setattr(Path, "exists", fake_exists)


def test_clean_monotonic_versions_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 3,
                "last_updated": _iso(2026, 1, 1, 12),
                "agents": {},
            }
        },
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
                ("c3", _epoch(2026, 1, 1, 12)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c2"): {
                "version": 2,
                "last_updated": _iso(2026, 1, 1, 11),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["status"] == "PASS"
    assert payload["version_drift"] == []
    assert payload["timestamp_drift"] == []


def test_version_reuse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 11),
                "agents": {},
            }
        },
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c1"): {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["reason"] == "version reused across consecutive snapshots"


def test_version_skip_greater_than_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 3,
                "last_updated": _iso(2026, 1, 1, 11),
                "agents": {},
            }
        },
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c1"): {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["delta"] == 2
    assert payload["version_drift"][0]["reason"] == "version jump exceeded 1"


def test_backdated_last_updated_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 2,
                "last_updated": _iso(2026, 1, 1, 9, 59),
                "agents": {},
            }
        },
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c1"): {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["timestamp_drift"][0]["reason"] == (
        "last_updated is older than the second-most-recent commit timestamp"
    )


def test_first_commit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
        history_by_path={"ledger/balances.json": [("c1", _epoch(2026, 1, 1, 10))]},
        committed_files={},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["status"] == "PASS"
    assert payload["version_drift"] == []
    assert payload["timestamp_drift"] == []


def test_pre_version_history_is_tolerated_until_versioning_begins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo(
        monkeypatch,
        current_files={"ledger/idem_keys.json": {"version": 1, "keys": []}},
        history_by_path={
            "ledger/idem_keys.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={("ledger/idem_keys.json", "c1"): {"keys": []}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["status"] == "PASS"
    assert payload["files_checked"][0]["previous_version"] is None


def test_version_decrease_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 2,
                "last_updated": _iso(2026, 1, 1, 11),
                "agents": {},
            }
        },
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c1"): {
                "version": 3,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["delta"] == -1
    assert payload["version_drift"][0]["reason"] == (
        "version decreased instead of increasing monotonically"
    )


def test_missing_last_updated_after_first_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={"ledger/balances.json": {"version": 2, "agents": {}}},
        history_by_path={
            "ledger/balances.json": [
                ("c1", _epoch(2026, 1, 1, 10)),
                ("c2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={
            ("ledger/balances.json", "c1"): {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            }
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["timestamp_drift"][0]["reason"] == (
        "missing or invalid last_updated after first commit"
    )


def test_multiple_files_aggregate_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={
            "ledger/balances.json": {
                "version": 2,
                "last_updated": _iso(2026, 1, 1, 11),
                "agents": {},
            },
            "ledger/task_index.json": {"version": 1, "tasks": {}},
        },
        history_by_path={
            "ledger/balances.json": [
                ("b1", _epoch(2026, 1, 1, 10)),
                ("b2", _epoch(2026, 1, 1, 11)),
            ],
            "ledger/task_index.json": [
                ("t1", _epoch(2026, 1, 1, 10)),
                ("t2", _epoch(2026, 1, 1, 11)),
            ],
        },
        committed_files={
            ("ledger/balances.json", "b1"): {
                "version": 1,
                "last_updated": _iso(2026, 1, 1, 10),
                "agents": {},
            },
            ("ledger/task_index.json", "t1"): {"version": 1, "tasks": {}},
        },
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert {row["path"] for row in payload["files_checked"]} == {
        "ledger/balances.json",
        "ledger/task_index.json",
    }
    assert any(issue["file"] == "ledger/task_index.json" for issue in payload["version_drift"])


def test_current_non_integer_version_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(
        monkeypatch,
        current_files={"ledger/task_index.json": {"version": "2", "tasks": {}}},
        history_by_path={
            "ledger/task_index.json": [
                ("t1", _epoch(2026, 1, 1, 10)),
                ("t2", _epoch(2026, 1, 1, 11)),
            ]
        },
        committed_files={("ledger/task_index.json", "t1"): {"version": 1, "tasks": {}}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["reason"] == "current version is missing or non-integer"


def test_main_emits_json_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "status": "PASS",
        "version_drift": [],
        "timestamp_drift": [],
        "files_checked": [],
        "summary": "ok",
    }
    monkeypatch.setattr(check_version_drift, "run", lambda root: (payload, True))

    code = check_version_drift.main(["--root", str(ROOT)])
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out) == payload


def test_run_returns_fail_payload_on_git_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_root: Path) -> list[str]:
        raise RuntimeError("git log failed for ledger/balances.json: boom")

    monkeypatch.setattr(check_version_drift, "list_versioned_ledger_files", boom)

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["status"] == "FAIL"
    assert payload["error"] == "git log failed for ledger/balances.json: boom"
