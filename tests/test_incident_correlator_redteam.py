#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_incident_correlator.py"
SCRIPTS_DIR = SCRIPT.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_incident_correlator import (
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    build_report,
    correlate_failures,
    run_all_checks,
    _CHECK_REGISTRY,
)

def test_all_checks_fail_attributes_to_invariant():
    # 1. All checks fail: BFS must attribute root cause to invariant (graph root), not a leaf
    results = []
    for check in _CHECK_REGISTRY:
        results.append({
            "name": check["name"],
            "status": STATUS_FAIL,
            "script": check["script"],
            "exit_code": 1,
            "stdout": "",
            "stderr": "",
            "skip_reason": None,
        })
    
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "invariant" in correlation["root_causes"]
    # It must NOT attribute to leaves like idem_consistency
    assert "idem_consistency" not in correlation["root_causes"]
    assert correlation["root_causes"] == ["invariant"]

def test_leaf_fails_parent_passes():
    # 2. Leaf fails, parent passes: must be reported as independent root (not downstream)
    results = [
        {"name": "idem_consistency", "status": STATUS_PASS},
        {"name": "idem_keys", "status": STATUS_FAIL},
        {"name": "history_reconciliation", "status": STATUS_FAIL},
    ]
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "idem_keys" in correlation["root_causes"]
    assert "history_reconciliation" in correlation["root_causes"]

def test_error_status_counts_as_failure():
    # 3. ERROR exit code: must count as failure, not ignored
    results = [
        {"name": "idem_consistency", "status": STATUS_ERROR},
        {"name": "idem_keys", "status": STATUS_ERROR},
    ]
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "idem_consistency" in correlation["root_causes"]

def test_skip_status_not_counted_as_failure():
    # 4. SKIP result: must not count as failure or affect root-cause attribution
    results = [
        {"name": "idem_consistency", "status": STATUS_SKIP},
        {"name": "idem_keys", "status": STATUS_FAIL},
        {"name": "invariant", "status": STATUS_FAIL},
    ]
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "idem_keys" in correlation["root_causes"]

def test_unknown_check_name_no_crash():
    # 5. Unknown check name: must not crash the correlator
    results = [
        {"name": "unknown_check_1", "status": STATUS_FAIL},
        {"name": "unknown_check_2", "status": STATUS_FAIL},
    ]
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "unknown_check_1" in correlation["root_causes"]
    assert "unknown_check_2" in correlation["root_causes"]

def test_empty_results_clean_exit():
    # 6. Empty results: must exit 0 cleanly
    results = []
    correlation = correlate_failures(results)
    assert correlation is None
    report = build_report(results, "2026-04-08T00:00:00Z")
    assert report["overall_status"] == "PASS"

def test_disconnected_failures_handled():
    # 7. Additional edge case: disconnected checks fail
    results = [
        {"name": "idem_consistency", "status": STATUS_FAIL},
        {"name": "stale_escrows", "status": STATUS_FAIL},
    ]
    correlation = correlate_failures(results)
    assert correlation is not None
    assert "idem_consistency" in correlation["root_causes"]
    assert "stale_escrows" in correlation["root_causes"]

def test_circular_dependency_simulation():
    # 8. Additional edge case: if we mock DEPENDENCY_GRAPH to have a cycle, does it crash?
    import check_incident_correlator
    old_graph = check_incident_correlator.DEPENDENCY_GRAPH.copy()
    try:
        check_incident_correlator.DEPENDENCY_GRAPH["idem_consistency"] = ["invariant"]
        results = [
            {"name": "idem_consistency", "status": STATUS_FAIL},
            {"name": "invariant", "status": STATUS_FAIL},
        ]
        # Since they are a cycle, both have failing upstream, so neither is a root cause!
        # But wait, if root_causes is empty, BFS should still handle it!
        correlation = correlate_failures(results)
        assert correlation is not None
        # With cycle, root_causes will be empty under current logic, but BFS shouldn't crash.
        assert len(correlation["root_causes"]) == 0
        # It should still output investigation order covering all failed nodes
        assert set(correlation["investigation_order"]) == {"idem_consistency", "invariant"}
    finally:
        check_incident_correlator.DEPENDENCY_GRAPH = old_graph