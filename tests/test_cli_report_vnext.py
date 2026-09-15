"""Regression tests for `wea report` vNext canonical rendering (src/wea_cli/tide.py).

The canonical read-only ledger primitives (`git`, `files`, `load`) are patched so
the report logic can be exercised without constructing a full executor-replayed
git fixture. Failure paths must be actionable with no stale fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wea_cli import tide
from wea_cli.tide import ReportError, build_report, render_report


class _FakeEngine:
    def __init__(self) -> None:
        self.sources = {
            "rev-open": {"issue_id": 980, "issue_number": 980},
            "rev-done": {"issue_id": 964, "issue_number": 964},
        }
        self.runtimes = {"980": object(), "964": object()}
        self.funding_batches = {"980": "batch-1", "964": "batch-0"}
        self.bootstrap = {
            "legacy_files": {
                "ledger/balances.json": "h1",
                "ledger/escrows.json": "h2",
            }
        }
        self.modules = {"lifecycle": self}

    def next_action(self, runtime: object, agent: str) -> dict:
        return {
            "actor_id": agent,
            "action": "submit eligible Work",
            "boundary_at": "2026-09-22T06:11:03.822994Z",
        }

    def state(self) -> dict:
        return {
            "sequence": 11,
            "cutoff": "2026-09-15T06:11:03.822994Z",
            "last_hash": "abc123",
            "opening_supply": 19025,
            "escrow_wea": 20,
            "balances": {"Claude-14@claude": 110, "agent0@system": 100},
            "tasks": {
                "980": {
                    "plan_id": "resolution-plan:x",
                    "plan_status": "active",
                    "current_stage_index": 0,
                    "stages": [
                        {
                            "stage_index": 0,
                            "stage_key": "cli-reliability",
                            "status": "active",
                            "phase": "intake",
                            "works": [],
                            "paid_wea": 0,
                            "contract": {"mode": "ranked", "depth": "implement"},
                        }
                    ],
                },
                "964": {
                    "plan_id": "resolution-plan:y",
                    "plan_status": "completed",
                    "current_stage_index": 0,
                    "stages": [
                        {
                            "stage_index": 0,
                            "stage_key": "work-guidance",
                            "status": "closed",
                            "phase": "closed",
                            "works": [1, 2, 3],
                            "paid_wea": 20,
                            "contract": {"mode": "ranked", "depth": "implement"},
                        }
                    ],
                },
            },
        }


def _patch_ok(monkeypatch: pytest.MonkeyPatch, commit: str = "d" * 40) -> None:
    monkeypatch.setattr(tide, "git", lambda root, *a: commit)
    monkeypatch.setattr(tide, "files", lambda root, c, prefix: [tide.BOOTSTRAP])
    monkeypatch.setattr(tide, "load", lambda root, c: (_FakeEngine(), []))


# --- happy path -------------------------------------------------------------


def test_report_resolves_ref_and_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ok(monkeypatch, commit="a" * 40)
    report = build_report(Path("."), "origin/main", "Claude-14@claude")
    assert report["ref"] == "origin/main"
    assert report["commit"] == "a" * 40
    assert report["sequence"] == 11


def test_report_invoking_agent_balance_and_next_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ok(monkeypatch)
    report = build_report(Path("."), "origin/main", "Claude-14@claude")
    assert report["agent_balance"] == 110
    task = next(t for t in report["tasks"] if t["issue"] == 980)
    assert task["lifecycle"] == "open"
    assert task["next_action"]["action"] == "submit eligible Work"


def test_report_classifies_settlement_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ok(monkeypatch)
    report = build_report(Path("."), "origin/main", "Claude-14@claude")
    done = next(t for t in report["tasks"] if t["issue"] == 964)
    assert done["lifecycle"] == "settlement"
    assert done["paid_wea"] == 20


def test_report_separates_legacy_history(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ok(monkeypatch)
    report = build_report(Path("."), "origin/main", None)
    legacy = report["legacy_history"]
    assert legacy["retained"] is True
    assert "ledger/balances.json" in legacy["files"]
    assert "not" in legacy["note"].lower()


def test_render_report_contains_key_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ok(monkeypatch)
    report = build_report(Path("."), "origin/main", "Claude-14@claude")
    text = render_report(report)
    assert "WEA vNEXT REPORT" in text
    assert "#980 [open] cli-reliability" in text
    assert "LEGACY HISTORY" in text
    assert "next: submit eligible Work" in text


# --- failure paths (no stale fallback) -------------------------------------


def test_report_fails_on_unresolvable_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(root, *a):
        raise subprocess.CalledProcessError(128, ["git"], stderr=b"unknown revision")

    monkeypatch.setattr(tide, "git", _raise)
    with pytest.raises(ReportError, match="Fetch origin first"):
        build_report(Path("."), "origin/missing", None)


def test_report_fails_when_tide_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tide, "git", lambda root, *a: "c" * 40)
    monkeypatch.setattr(tide, "files", lambda root, c, prefix: [])
    with pytest.raises(ReportError, match="not active"):
        build_report(Path("."), "origin/main", None)


def test_report_fails_on_replay_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tide, "git", lambda root, *a: "c" * 40)
    monkeypatch.setattr(tide, "files", lambda root, c, prefix: [tide.BOOTSTRAP])

    def _boom(root, c):
        raise ValueError("canonical projection does not match task replay")

    monkeypatch.setattr(tide, "load", _boom)
    with pytest.raises(ReportError, match="Canonical replay failed"):
        build_report(Path("."), "origin/main", None)


# --- lifecycle mapping unit --------------------------------------------------


@pytest.mark.parametrize(
    "plan_status,stage,expected",
    [
        ("active", {"status": "active", "phase": "intake"}, "open"),
        ("active", {"status": "active", "phase": "decision"}, "review"),
        ("active", {"status": "closed", "phase": "closed"}, "settlement"),
        ("completed", {"status": "closed", "phase": "closed"}, "settlement"),
        ("stopped", {"status": "closed", "phase": "closed"}, "settlement"),
        # A paused plan is NOT terminal: keep it distinct from settlement even
        # while its current stage is still an active intake.
        ("paused", {"status": "active", "phase": "intake"}, "paused"),
        ("active", None, "funded"),
    ],
)
def test_stage_lifecycle(plan_status, stage, expected) -> None:
    assert tide._stage_lifecycle(plan_status, stage) == expected


def test_report_rejects_noncanonical_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local/unmerged ref not contained in fetched origin/main is rejected."""

    def _fake_git(root, *args):
        if args[0] == "fetch":
            return ""
        if args[0] == "rev-parse":
            target = args[-1]  # anchor is refs/remotes/origin/main^{commit}
            return ("a" * 40) if target.startswith("refs/remotes/") else ("b" * 40)
        if args[0] == "merge-base":
            # merge-base(pending b..., canonical a...) == canonical a..., != ref b...
            return "a" * 40
        return ""

    monkeypatch.setattr(tide, "git", _fake_git)
    # The requested ref resolves to a local commit not contained in origin/main.
    with pytest.raises(ReportError, match="not canonical"):
        build_report(Path("."), "local-pending", None)


def test_report_rejects_pending_tide_candidate_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--ref origin/tide/pending` must NOT be validated against itself.

    The canonical head is resolved from origin/main independently, so a
    replayable but unmerged Tide candidate is rejected, not reported as canonical.
    """

    def _fake_git(root, *args):
        if args[0] == "fetch":
            return ""
        if args[0] == "rev-parse":
            target = args[-1]
            # fully-qualified canonical anchor is a...; the pending candidate is b...
            return ("a" * 40) if target.startswith("refs/remotes/") else ("b" * 40)
        if args[0] == "merge-base":
            return "a" * 40  # base is canonical head, not the pending commit
        return ""

    monkeypatch.setattr(tide, "git", _fake_git)
    with pytest.raises(ReportError, match="not canonical"):
        build_report(Path("."), "origin/tide/pending", None)


def test_report_anchor_is_fully_qualified_against_spoof_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local tag/branch named `origin/main` cannot shadow the trusted anchor.

    The requested ref `origin/main` resolves to a spoof candidate, but the anchor
    resolves the fully-qualified refs/remotes/origin/main, so containment fails.
    """
    calls: list[tuple] = []

    def _fake_git(root, *args):
        calls.append(args)
        if args[0] == "fetch":
            return ""
        if args[0] == "rev-parse":
            target = args[-1]
            # fully-qualified anchor -> real canonical; bare name -> spoof candidate
            return ("a" * 40) if target.startswith("refs/remotes/") else ("b" * 40)
        if args[0] == "merge-base":
            return "a" * 40
        return ""

    monkeypatch.setattr(tide, "git", _fake_git)
    with pytest.raises(ReportError, match="not canonical"):
        build_report(Path("."), "origin/main", None)
    # The anchor was resolved via the fully-qualified remote-tracking ref.
    assert any(
        a[0] == "rev-parse" and a[-1].startswith("refs/remotes/origin/main")
        for a in calls
    )
    # The fetch used an explicit destination refspec.
    assert any(
        a[0] == "fetch" and a[-1].endswith("refs/remotes/origin/main") for a in calls
    )
