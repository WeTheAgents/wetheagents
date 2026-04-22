"""
Red-team tests for scripts/check_genome_meta_version_consistency.py.

CRITICAL FINDINGS (Bypass vectors that return PASS):
1. Empty snapshot block for fitness_before/fitness_after:
   _valid_snapshot_block returns True for {}, allowing mutations with empty fitness data.
2. Negative fitness integers in snapshot blocks:
   _valid_snapshot_block uses _is_int which does not check for non-negative values (unlike top-level fitness).
3. Empty sections_changed list:
   _valid_string_list returns True for [], allowing mutations with no sections_changed.
4. Empty changes list in release_session mutation:
   _valid_string_list returns True for [], allowing release sessions with no changes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from scripts.check_genome_meta_version_consistency import run_check


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def case_root() -> Path:
    root = Path(".test_runs") / "check_genome_meta_version_consistency_redteam" / uuid4().hex
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _make_repo(case_root: Path) -> Path:
    (case_root / "genomes").mkdir(parents=True, exist_ok=True)
    return case_root


def _write_genome(
    root: Path,
    agent_id: str,
    mutations: list[Any],
) -> None:
    path = root / "genomes" / agent_id / "genome_meta.json"
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "generation": 1,
        "parent": None,
        "created_at": "2026-04-18T10:00:00Z",
        "last_snapshot": "2026-04-18T10:00:00Z",
        "role": "tester",
        "fitness": {
            "tasks_completed": 0,
            "tasks_created": 0,
            "total_earned": 0,
            "total_minted": 0,
            "gauntlet_slots": 0,
            "total_income": 0,
            "initiative_ratio": 0,
            "acceptance_rate": 0,
            "rework_rate": 0,
            "avg_time_in_stage_hours": 0,
            "zero_code_ratio": 0,
            "review_quality": 0,
            "composite_score": 0
        },
        "lineage": [],
        "mutations": mutations
    }
    _write_json(path, payload)


def test_redteam_empty_snapshot_block_bypass(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts {} for fitness_before/after."""
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Claude-1@claude",
        [{
            "trigger_issue": 101,
            "commit": "abc1234",
            "date": "2026-04-18T10:00:00Z",
            "author": "tester",
            "sections_changed": ["Memory"],
            "lines_added": 10,
            "lines_removed": 5,
            "summary": "test",
            "fitness_before": {},  # Empty block bypass
            "fitness_after": {}
        }],
    )

    report, exit_code = run_check(root)
    
    # Assert the bypass works (script returns 0/PASS instead of catching the error)
    assert exit_code == 0
    assert report["status"] == "PASS"


def test_redteam_negative_snapshot_block_bypass(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts negative values in fitness snapshots."""
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Claude-1@claude",
        [{
            "trigger_issue": 101,
            "commit": "abc1234",
            "date": "2026-04-18T10:00:00Z",
            "author": "tester",
            "sections_changed": ["Memory"],
            "lines_added": 10,
            "lines_removed": 5,
            "summary": "test",
            "fitness_before": {"tasks_completed": -5},  # Negative value bypass
            "fitness_after": {"tasks_completed": 0}
        }],
    )

    report, exit_code = run_check(root)
    
    assert exit_code == 0
    assert report["status"] == "PASS"


def test_redteam_empty_sections_changed_bypass(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts [] for sections_changed."""
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Claude-1@claude",
        [{
            "trigger_issue": 101,
            "commit": "abc1234",
            "date": "2026-04-18T10:00:00Z",
            "author": "tester",
            "sections_changed": [],  # Empty list bypass
            "lines_added": 10,
            "lines_removed": 5,
            "summary": "test",
            "fitness_before": {"tasks_completed": 0},
            "fitness_after": {"tasks_completed": 0}
        }],
    )

    report, exit_code = run_check(root)
    
    assert exit_code == 0
    assert report["status"] == "PASS"


def test_redteam_empty_changes_in_release_session_bypass(case_root: Path) -> None:
    """CRITICAL FINDING: Bypass succeeds. Checker accepts [] for changes in release session mutation."""
    root = _make_repo(case_root)
    _write_genome(
        root,
        "Claude-1@claude",
        [{
            "release_session": "SGR-123",
            "date": "2026-04-18T10:00:00Z",
            "changes": []  # Empty list bypass
        }],
    )

    report, exit_code = run_check(root)
    
    assert exit_code == 0
    assert report["status"] == "PASS"
