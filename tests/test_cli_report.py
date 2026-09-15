"""Regression coverage for the canonical vNext `wea report`.

The report is exercised at two levels: the pure assembly/rendering functions in
``wea_cli.tide`` (with a synthetic replay engine so the tests are hermetic) and
the ref-resolution failure path against a real local Git repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wea_cli import tide

# --- local Git integration: canonical ref selection --------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A worktree with a canonical `origin/main` remote-tracking ref."""
    origin = tmp_path / "origin.git"
    root = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(origin), "--bare"],
        check=True,
        capture_output=True,
    )
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "tester")
    _git(root, "remote", "add", "origin", str(origin))
    (root / "f.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-qm", "one")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "fetch", "-q", "origin")
    return root


def test_resolve_ref_commit_returns_full_sha_for_canonical_ref(git_repo: Path) -> None:
    commit = tide.resolve_ref_commit(git_repo, "origin/main")
    assert len(commit) == 40
    assert (
        commit
        == subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "refs/remotes/origin/main"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def test_resolve_ref_commit_rejects_noncanonical_local_ref(git_repo: Path) -> None:
    with pytest.raises(tide.TideReadError) as excinfo:
        tide.resolve_ref_commit(git_repo, "main", fetch=False)
    assert "not a canonical origin ref" in str(excinfo.value)


def test_resolve_ref_commit_fails_actionably_for_missing_ref(git_repo: Path) -> None:
    with pytest.raises(tide.TideReadError) as excinfo:
        tide.resolve_ref_commit(git_repo, "origin/does-not-exist", fetch=False)
    message = str(excinfo.value)
    assert "origin/does-not-exist" in message
    assert "stale" in message.lower()


def test_resolve_ref_commit_fails_when_fetch_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "tester")
    _git(root, "remote", "add", "origin", str(tmp_path / "nonexistent.git"))
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-qm", "x")
    with pytest.raises(tide.TideReadError) as excinfo:
        tide.resolve_ref_commit(root, "origin/main", fetch=True)
    assert "fetch" in str(excinfo.value).lower()


def test_build_report_reports_inactive_when_no_bootstrap(git_repo: Path) -> None:
    report = tide.build_vnext_report(
        git_repo, ref="origin/main", agent="Claude-15@claude", fetch=False
    )
    assert report["active"] is False
    assert report["commit"] == tide.resolve_ref_commit(
        git_repo, "origin/main", fetch=False
    )
    # Inactive still renders without raising.
    assert "not initialized" in tide.render_vnext_report(report).lower()


# --- synthetic replay engine: state rendering & next actions -----------------


class _FakeLifecycle:
    def next_action(self, runtime: object, agent: str) -> dict[str, object]:
        return {
            "action": "submit eligible Work",
            "mode": "ranked",
            "depth": "implement",
            "boundary_at": "2026-09-22T06:11:03Z",
        }


class _FakeEngine:
    def __init__(self) -> None:
        self.sources = {
            "rev-a": {"issue_id": 5452795028, "issue_number": 980},
            "rev-b": {"issue_id": 111, "issue_number": 964},
        }
        self.runtimes = {"5452795028": object()}
        self.modules = {"lifecycle": _FakeLifecycle()}

    def state(self) -> dict[str, object]:
        return {
            "schema": "wea-tide-state-2",
            "sequence": 11,
            "last_hash": "a530d12f",
            "cutoff": "2026-09-15T06:11:03Z",
            "balances": {"Claude-15@claude": 123},
            "opening_supply": 19025,
            "escrow_wea": 20,
            "tasks": {
                "5452795028": {
                    "plan_id": "resolution-plan:x:5452795028",
                    "plan_status": "active",
                    "current_stage_index": 0,
                    "stages": [
                        {
                            "stage_index": 0,
                            "stage_key": "cli-reliability",
                            "status": "active",
                            "phase": "intake",
                        }
                    ],
                    "escrow": {
                        "deposited_wea": 20,
                        "paid_wea": 0,
                        "refunded_wea": 0,
                        "status": "active",
                    },
                },
                "111": {
                    "plan_id": "resolution-plan:x:111",
                    "plan_status": "completed",
                    "current_stage_index": 0,
                    "stages": [
                        {
                            "stage_index": 0,
                            "stage_key": "work-declaration",
                            "status": "closed",
                            "phase": "closed",
                        }
                    ],
                    "escrow": {
                        "deposited_wea": 20,
                        "paid_wea": 20,
                        "refunded_wea": 0,
                        "status": "closed",
                    },
                },
            },
            "dispositions": {
                "rev-bad": {"status": "unresolved", "reason": "missing edit evidence"},
                "rev-ok": {"status": "accepted", "reason": "fine"},
            },
        }


@pytest.fixture()
def fake_report(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(tide, "resolve_ref_commit", lambda root, ref, **kw: "f" * 40)
    monkeypatch.setattr(tide, "files", lambda root, commit, prefix: ["bootstrap"])
    monkeypatch.setattr(tide, "load", lambda root, commit: (_FakeEngine(), []))
    monkeypatch.setattr(
        tide,
        "_legacy_summary",
        lambda root, commit: {
            "source": "ledger/balances.json",
            "agents": 19,
            "total_wea": 19025,
            "note": "retained legacy ledger",
        },
    )
    return tide.build_vnext_report(
        Path("."), ref="origin/main", agent="Claude-15@claude"
    )


def test_report_surfaces_canonical_tide_and_balance(
    fake_report: dict[str, object],
) -> None:
    assert fake_report["active"] is True
    assert fake_report["tide"]["sequence"] == 11  # type: ignore[index]
    assert fake_report["tide"]["cutoff"] == "2026-09-15T06:11:03Z"  # type: ignore[index]
    assert fake_report["tide"]["active_escrow_wea"] == 20  # type: ignore[index]
    assert fake_report["available_wea"] == 123


def test_report_shows_invoking_agent_next_action_only_for_funded(
    fake_report: dict[str, object],
) -> None:
    tasks = {t["issue"]: t for t in fake_report["tasks"]}  # type: ignore[union-attr]
    assert tasks[980]["next_action"]["action"] == "submit eligible Work"
    assert tasks[980]["stage_label"] == "open"
    assert tasks[980]["escrow"]["available_wea"] == 20
    # Completed task renders settlement and paid escrow.
    assert tasks[964]["stage_label"] == "settlement"
    assert tasks[964]["escrow"]["available_wea"] == 0


def test_report_separates_unresolved_and_legacy(fake_report: dict[str, object]) -> None:
    unresolved = fake_report["unresolved_sources"]
    assert len(unresolved) == 1  # only the "unresolved" disposition, not "accepted"
    assert unresolved[0]["revision_id"] == "rev-bad"  # type: ignore[index]
    assert fake_report["legacy"]["total_wea"] == 19025  # type: ignore[index]


def test_report_issue_filter_restricts_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tide, "resolve_ref_commit", lambda root, ref, **kw: "f" * 40)
    monkeypatch.setattr(tide, "files", lambda root, commit, prefix: ["bootstrap"])
    monkeypatch.setattr(tide, "load", lambda root, commit: (_FakeEngine(), []))
    monkeypatch.setattr(tide, "_legacy_summary", lambda root, commit: None)
    report = tide.build_vnext_report(
        Path("."), ref="origin/main", agent="Claude-15@claude", issue=980
    )
    assert [t["issue"] for t in report["tasks"]] == [980]
    assert report["legacy"] is None


def test_render_report_is_human_readable(fake_report: dict[str, object]) -> None:
    text = tide.render_vnext_report(fake_report)
    assert "WEA vNext REPORT" in text
    assert "CANONICAL TIDE" in text
    assert "RETAINED LEGACY (historical, not vNext authority)" in text
    assert "your next action: submit eligible Work" in text
    assert "#980" in text


def test_build_report_wraps_replay_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from wea_vnext.tide.replay import ReplayError

    monkeypatch.setattr(tide, "resolve_ref_commit", lambda root, ref, **kw: "f" * 40)
    monkeypatch.setattr(tide, "files", lambda root, commit, prefix: ["bootstrap"])

    def _boom(root: Path, commit: str) -> object:
        raise ReplayError("projection mismatch")

    monkeypatch.setattr(tide, "load", _boom)
    with pytest.raises(tide.TideReadError) as excinfo:
        tide.build_vnext_report(Path("."), ref="origin/main", agent="a@b")
    assert "replay failed" in str(excinfo.value).lower()
    assert "projection mismatch" in str(excinfo.value)
