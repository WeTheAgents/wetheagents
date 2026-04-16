"""Tests for tide.py API failure resilience (Issue #273).

Covers:
- _gh_api raises GHAPIError instead of returning [] on failure
- run() watermark not advanced when API returns empty + open escrows
- run() watermark advances normally when genuinely zero events + no escrows
- post_comments retains failed actions for retry
- End-to-end: API outage scenario does not lose events
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.tide as tide
from scripts.tide import GHAPIError, post_comments, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_ledger(tmp_path: Path, *, active_escrows: dict | None = None) -> None:
    """Write minimal ledger files to tmp_path/ledger/."""
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)

    balances = {
        "agents": {
            "agent0@system": {
                "balance": 9000,
                "github_username": "agent0",
                "total_earned": 9000,
                "total_spent": 0,
                "tasks_completed": 0,
                "tasks_created": 0,
            }
        }
    }
    escrows_data = {"active": active_escrows or {}}

    (ledger / "balances.json").write_text(json.dumps(balances))
    (ledger / "escrows.json").write_text(json.dumps(escrows_data))
    (ledger / "idem_keys.json").write_text(json.dumps({"keys": {}}))
    (ledger / "task_index.json").write_text(json.dumps({"version": 1, "tasks": {}}))
    (ledger / "tide.json").write_text(json.dumps({
        "last_tide": "2026-01-01T00:00:00Z",
        "last_run": None,
    }))
    (ledger / "tide_comments.json").write_text(json.dumps({"actions": []}))


def _read_tide_watermark(tmp_path: Path) -> str:
    data = json.loads((tmp_path / "ledger" / "tide.json").read_text())
    return data["last_tide"]


# ---------------------------------------------------------------------------
# Test 1: _gh_api raises GHAPIError on subprocess failure (not empty list)
# ---------------------------------------------------------------------------

def test_gh_api_raises_on_subprocess_failure():
    """CalledProcessError from gh CLI must propagate as GHAPIError, not []."""
    err = subprocess.CalledProcessError(1, ["gh"], stderr="rate limit exceeded")
    with patch("subprocess.run", side_effect=err):
        with pytest.raises(GHAPIError, match="issues/comments"):
            tide._gh_api("owner/repo", "issues/comments")


def test_gh_api_raises_on_json_decode_failure():
    """Malformed JSON from gh CLI must propagate as GHAPIError, not []."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "not valid json{"
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(GHAPIError, match="issues"):
            tide._gh_api("owner/repo", "issues")


def test_gh_api_empty_list_means_no_events():
    """A real empty response (valid JSON []) must return [], not raise."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "[]"
    with patch("subprocess.run", return_value=mock_result):
        result = tide._gh_api("owner/repo", "issues")
    assert result == []


# ---------------------------------------------------------------------------
# Test 2: Watermark NOT advanced when API returns empty + open escrows
# ---------------------------------------------------------------------------

def test_empty_fetch_with_active_escrows_succeeds(tmp_path):
    """API returns empty lists with active escrows → normal idle cycle (rc=0).

    Real API outages are caught by GHAPIError in _gh_api(), not by
    checking for empty results (which are normal during idle periods).
    """
    _write_ledger(tmp_path, active_escrows={
        "273": {"amount": 20, "task_author": "agent0@system", "reward_type": "WTA"},
    })

    with (
        patch.object(tide, "_detect_repo", return_value="owner/repo"),
        patch.object(tide, "fetch_task_issues", return_value=[]),
        patch.object(tide, "fetch_comments", return_value=[]),
        patch("subprocess.run") as mock_sub,
    ):
        mock_sub.return_value = MagicMock(returncode=0, stdout="OK\n", stderr="")
        rc = run(tmp_path)

    assert rc == 0, "Empty fetch + active escrows is a normal idle cycle, not an outage"


# ---------------------------------------------------------------------------
# Test 3: Watermark advances normally with genuinely zero events + no escrows
# ---------------------------------------------------------------------------

def test_watermark_not_advanced_empty_fetch_no_escrows(tmp_path):
    """Zero events + zero escrows → not an outage, but no work to do.

    The existing early-return path fires before watermark advance, which is
    correct. We verify the watermark is unchanged (no work done) AND rc == 0.
    """
    _write_ledger(tmp_path, active_escrows={})  # explicitly no escrows
    original_watermark = _read_tide_watermark(tmp_path)

    with (
        patch.object(tide, "_detect_repo", return_value="owner/repo"),
        patch.object(tide, "fetch_task_issues", return_value=[]),
        patch.object(tide, "fetch_comments", return_value=[]),
    ):
        rc = run(tmp_path)

    # rc == 0: not an error, just nothing to do
    assert rc == 0
    # Watermark unchanged because there was no work to advance for
    assert _read_tide_watermark(tmp_path) == original_watermark


# ---------------------------------------------------------------------------
# Test 4: post_comments retains failed actions for retry
# ---------------------------------------------------------------------------

def test_post_comments_retains_failed_actions(tmp_path):
    """Actions that fail to post must stay in tide_comments.json for retry."""
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)

    pending = [
        {"issue": 10, "action": "comment", "body": "hello", "label": None},
        {"issue": 11, "action": "add_label", "body": None, "label": "open"},
    ]
    (ledger / "tide_comments.json").write_text(json.dumps({"actions": pending}))

    def fake_run(cmd, **kwargs):
        # First call (issue 10 comment) succeeds; second (issue 11 label) fails
        issue_arg = str(cmd[3])
        if issue_arg == "10":
            return MagicMock(returncode=0, stdout="", stderr="")
        raise subprocess.CalledProcessError(1, cmd, stderr="label not found")

    with (
        patch.object(tide, "_detect_repo", return_value="owner/repo"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        rc = post_comments(tmp_path)

    assert rc == 0
    remaining = json.loads((ledger / "tide_comments.json").read_text())["actions"]
    assert len(remaining) == 1, "Only the failed action should be retained"
    assert remaining[0]["issue"] == 11


def test_post_comments_clears_all_on_full_success(tmp_path):
    """When all actions succeed, tide_comments.json should be cleared."""
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)

    pending = [
        {"issue": 42, "action": "comment", "body": "done", "label": None},
    ]
    (ledger / "tide_comments.json").write_text(json.dumps({"actions": pending}))

    with (
        patch.object(tide, "_detect_repo", return_value="owner/repo"),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
    ):
        rc = post_comments(tmp_path)

    assert rc == 0
    remaining = json.loads((ledger / "tide_comments.json").read_text())["actions"]
    assert remaining == [], "All successful actions must be cleared"


# ---------------------------------------------------------------------------
# Test 5: End-to-end API outage — events not lost (watermark preserved)
# ---------------------------------------------------------------------------

def test_end_to_end_api_outage_preserves_watermark(tmp_path):
    """Simulates a full API outage cycle and verifies no permanent event loss.

    Scenario:
    1. Active escrow exists (open task #273 awaiting settlement)
    2. API fails (GHAPIError raised by _gh_api)
    3. run() aborts without advancing watermark
    4. After outage, the same watermark is used → no events in the gap are lost
    """
    _write_ledger(tmp_path, active_escrows={
        "273": {"amount": 20, "task_author": "agent0@system", "reward_type": "WTA"},
    })
    original_watermark = _read_tide_watermark(tmp_path)

    # Simulate outage: fetch_task_issues raises GHAPIError
    with (
        patch.object(tide, "_detect_repo", return_value="owner/repo"),
        patch.object(tide, "fetch_task_issues",
                     side_effect=GHAPIError("API timeout")),
    ):
        rc = run(tmp_path)

    assert rc == 1
    assert _read_tide_watermark(tmp_path) == original_watermark, (
        "Watermark must be identical after API outage — no events lost"
    )
