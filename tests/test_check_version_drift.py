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


def _patch_balances(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: dict[str, object] | None,
    history: list[tuple[str, int]],
    previous: dict[str, object] | None = None,
) -> None:
    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        if path == ROOT / check_version_drift.BALANCES_PATH:
            return current is not None
        return original_exists(path)

    def fake_load_worktree_json(path: Path) -> dict[str, object]:
        rel_path = path.relative_to(ROOT).as_posix()
        assert rel_path == check_version_drift.BALANCES_PATH
        assert current is not None
        return current

    def fake_git_log(_root: str, rel_path: str) -> tuple[tuple[str, int], ...]:
        assert rel_path == check_version_drift.BALANCES_PATH
        return tuple(history)

    def fake_git_show_json(_root: str, commit: str, rel_path: str) -> dict[str, object]:
        assert rel_path == check_version_drift.BALANCES_PATH
        assert previous is not None
        assert commit == history[-2][0]
        return previous

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(check_version_drift, "_load_worktree_json", fake_load_worktree_json)
    monkeypatch.setattr(check_version_drift, "_git_log", fake_git_log)
    monkeypatch.setattr(check_version_drift, "_git_show_json", fake_git_show_json)


def test_clean_monotonic_versions_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 3, "last_updated": _iso(2026, 1, 1, 12), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11)), ("c3", _epoch(2026, 1, 1, 12))],
        previous={"version": 2, "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["status"] == "PASS"
    assert payload["version_drift"] == []
    assert payload["timestamp_drift"] == []


def test_version_reuse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 1, "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["reason"] == "version reused across consecutive snapshots"


def test_version_skip_greater_than_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 3, "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["delta"] == 2
    assert payload["version_drift"][0]["reason"] == "version jump exceeded 1"


def test_backdated_last_updated_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 2, "last_updated": _iso(2026, 1, 1, 9, 59), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["timestamp_drift"][0]["reason"] == (
        "last_updated regressed compared to previous snapshot"
    )


def test_equal_last_updated_does_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same last_updated across snapshots is not a regression.

    Captures the writer-race pattern where a tool computes the snapshot
    first and commits it ~seconds later. The version field still bumps,
    so monotonicity is preserved; the logical clock has just not moved
    yet. This is informational, not a failure.
    """
    _patch_balances(
        monkeypatch,
        current={"version": 2, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["timestamp_drift"] == []


def test_first_commit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10))],
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["status"] == "PASS"
    assert payload["version_drift"] == []
    assert payload["timestamp_drift"] == []


def test_previous_snapshot_without_version_is_treated_as_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 1, "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is True
    assert payload["files_checked"][0]["previous_version"] is None


def test_version_decrease_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 2, "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 3, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["version_drift"][0]["delta"] == -1
    assert payload["version_drift"][0]["reason"] == (
        "version decreased instead of increasing monotonically"
    )


def test_missing_last_updated_after_first_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": 2, "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
    )

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["timestamp_drift"][0]["reason"] == (
        "missing or invalid last_updated after first commit"
    )


def test_current_non_integer_version_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_balances(
        monkeypatch,
        current={"version": "2", "last_updated": _iso(2026, 1, 1, 11), "agents": {}},
        history=[("c1", _epoch(2026, 1, 1, 10)), ("c2", _epoch(2026, 1, 1, 11))],
        previous={"version": 1, "last_updated": _iso(2026, 1, 1, 10), "agents": {}},
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
    monkeypatch.setattr(check_version_drift, "inspect_balances", lambda root: (_ for _ in ()).throw(RuntimeError("git log failed")))

    payload, passed = check_version_drift.run(ROOT)

    assert passed is False
    assert payload["status"] == "FAIL"
    assert payload["error"] == "git log failed"
