"""Test coverage proving check_task_escrow_sync.py and check_cross_file_integrity.py check different things."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts import check_task_escrow_sync
from scripts import check_cross_file_integrity

def test_coverage_distinction():
    # Mock data to show distinction
    tasks = {
        "tasks": {
            "1": {"status": "open", "reward": 100},
            "2": {"status": "open", "reward": 200},
            "3": {"status": "closed", "reward": 100},
        }
    }
    
    escrows = {
        "active": {
            "2": {"amount": 200, "author": "agent_x"},
            "3": {"amount": 100, "author": "agent_y"}, # Escrow without open task (or rather, active escrow without task index entry or open state depending on check)
            "4": {"amount": 50, "author": "agent_z"}   # Active escrow, no task entry
        }
    }

    balances = {
        "agents": {
            "agent_x": {"balance": 100},
            # missing agent_y and agent_z
        }
    }

    # 1. check_task_escrow_sync tests
    # Open tasks lacking escrow
    open_no_escrow = check_task_escrow_sync.check_open_tasks_have_escrow(tasks, escrows)
    assert len(open_no_escrow) == 1
    assert "task #1" in open_no_escrow[0]

    # Active escrow missing task_index entry
    escrow_no_task = check_task_escrow_sync.check_escrows_have_task(tasks, escrows)
    assert len(escrow_no_task) == 1
    assert "escrow #4" in escrow_no_task[0]

    # Escrow amount exceeds reward
    # Let's adjust mock so one exceeds
    tasks["tasks"]["2"]["reward"] = 150
    amount_exceeds = check_task_escrow_sync.check_escrow_not_exceeds_reward(tasks, escrows)
    assert len(amount_exceeds) == 1
    assert "escrow #2 amount 200 exceeds task reward 150" in amount_exceeds[0]

    # 2. check_cross_file_integrity tests
    # Escrow authors not in balances
    authors_missing = check_cross_file_integrity.check_escrow_authors_exist(balances, escrows)
    assert len(authors_missing) == 2
    assert any("agent_y" in msg for msg in authors_missing)
    assert any("agent_z" in msg for msg in authors_missing)

    # Orphaned escrows (Mocking issue fetcher)
    def mock_issue_fetcher(issue: int):
        if issue == 2:
            return {"state": "OPEN", "label_names": set()}
        if issue == 3:
            return {"state": "CLOSED", "label_names": set()} # CLOSED and missing `paid`
        if issue == 4:
            return {"state": "CLOSED", "label_names": {"paid"}} # Not orphaned
        return {}

    orphaned = check_cross_file_integrity.check_orphaned_escrows(escrows, issue_fetcher=mock_issue_fetcher)
    assert len(orphaned) == 1
    assert "escrow #3" in orphaned[0]

    # Both scripts test completely orthogonal invariants.
    # check_task_escrow_sync focuses on task status vs active escrows, and escrow amount vs task reward.
    # check_cross_file_integrity focuses on escrow author in balances, and escrow being orphaned according to github API.
