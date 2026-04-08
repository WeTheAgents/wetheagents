#!/usr/bin/env python3
"""Tests for scripts/check_incident_correlator.py.

Covers:
  1. correlate_failures — at least 3 correlation rules exercised
  2. build_report structure
  3. run_all_checks integration (against a real minimal ledger)
  4. Exit code behaviour via subprocess
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Imports from the script under test
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_incident_correlator.py"
SCRIPTS_DIR = SCRIPT.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from check_incident_correlator import (  # noqa: E402
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    build_report,
    correlate_failures,
    run_all_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(name: str, status: str) -> dict:
    return {
        "name": name,
        "script": f"scripts/check_{name}.py",
        "status": status,
        "exit_code": 0 if status == STATUS_PASS else 1,
        "stdout": "",
        "stderr": "",
        "skip_reason": None,
    }


def _make_ledger(tmp_path: Path) -> Path:
    """Create a minimal valid ledger for integration tests."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "balances.json").write_text(
        json.dumps({"agents": {"agent0@system": {"balance": 10000}}}),
        encoding="utf-8",
    )
    (ledger / "escrows.json").write_text(
        json.dumps({"active": {}}),
        encoding="utf-8",
    )
    (ledger / "task_index.json").write_text(
        json.dumps({"tasks": {}}),
        encoding="utf-8",
    )
    (ledger / "idem_keys.json").write_text(
        json.dumps({"keys": {}}),
        encoding="utf-8",
    )
    return tmp_path


def _run_script(root: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--root", str(root)]
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ===========================================================================
# Correlation rule tests (unit — pure logic, no subprocess)
# ===========================================================================


class TestCorrelationRules:
    """Each test exercises a specific dependency chain rule."""

    # Rule 1: stale_escrows → task_escrow_sync
    def test_stale_escrows_is_root_cause_of_task_escrow_sync(self):
        """When stale_escrows and task_escrow_sync both fail, stale_escrows is the root cause."""
        results = [
            _result("stale_escrows", STATUS_FAIL),
            _result("task_escrow_sync", STATUS_FAIL),
            _result("invariant", STATUS_PASS),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert "stale_escrows" in corr["root_causes"]
        assert "task_escrow_sync" not in corr["root_causes"]
        # stale_escrows should come before task_escrow_sync in investigation order
        order = corr["investigation_order"]
        assert order.index("stale_escrows") < order.index("task_escrow_sync")

    # Rule 2: task_escrow_sync → invariant
    def test_task_escrow_sync_is_root_cause_of_invariant(self):
        """When task_escrow_sync and invariant both fail, task_escrow_sync is the root cause."""
        results = [
            _result("task_escrow_sync", STATUS_FAIL),
            _result("invariant", STATUS_FAIL),
            _result("stale_escrows", STATUS_PASS),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert "task_escrow_sync" in corr["root_causes"]
        assert "invariant" not in corr["root_causes"]
        order = corr["investigation_order"]
        assert order.index("task_escrow_sync") < order.index("invariant")

    # Rule 3: idem_consistency → idem_keys → invariant (transitive chain)
    def test_idem_consistency_is_root_cause_in_full_chain(self):
        """Full idem chain: idem_consistency is root, idem_keys middle, invariant leaf."""
        results = [
            _result("idem_consistency", STATUS_FAIL),
            _result("idem_keys", STATUS_FAIL),
            _result("invariant", STATUS_FAIL),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert corr["root_causes"] == ["idem_consistency"]
        order = corr["investigation_order"]
        assert order[0] == "idem_consistency"
        assert order.index("idem_consistency") < order.index("idem_keys")
        assert order.index("idem_keys") < order.index("invariant")

    # Rule 4: history_reconciliation → invariant
    def test_history_reconciliation_is_root_cause_of_invariant(self):
        """When history_reconciliation and invariant both fail, history_reconciliation is the root cause."""
        results = [
            _result("history_reconciliation", STATUS_FAIL),
            _result("invariant", STATUS_FAIL),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert "history_reconciliation" in corr["root_causes"]
        assert "invariant" not in corr["root_causes"]
        order = corr["investigation_order"]
        assert order.index("history_reconciliation") < order.index("invariant")

    # Rule 5: multiple independent root causes (disconnected failures)
    def test_two_independent_root_causes(self):
        """stale_escrows and history_reconciliation both fail independently — both are root causes."""
        results = [
            _result("stale_escrows", STATUS_FAIL),
            _result("history_reconciliation", STATUS_FAIL),
            _result("invariant", STATUS_PASS),
            _result("task_escrow_sync", STATUS_PASS),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert set(corr["root_causes"]) == {"stale_escrows", "history_reconciliation"}

    # Rule 6: full cascade — stale_escrows → task_escrow_sync → invariant
    def test_full_cascade_three_checks(self):
        """Full cascade: stale_escrows is the single root cause for all three failures."""
        results = [
            _result("stale_escrows", STATUS_FAIL),
            _result("task_escrow_sync", STATUS_FAIL),
            _result("invariant", STATUS_FAIL),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert corr["root_causes"] == ["stale_escrows"]
        order = corr["investigation_order"]
        assert order[0] == "stale_escrows"
        assert order.index("stale_escrows") < order.index("task_escrow_sync")
        assert order.index("task_escrow_sync") < order.index("invariant")


# ===========================================================================
# correlate_failures edge cases
# ===========================================================================


class TestCorrelateFailuresEdgeCases:
    def test_single_failure_returns_none(self):
        """Fewer than 2 failures → no correlation."""
        results = [_result("invariant", STATUS_FAIL), _result("stale_escrows", STATUS_PASS)]
        assert correlate_failures(results) is None

    def test_no_failures_returns_none(self):
        """Zero failures → no correlation."""
        results = [_result("invariant", STATUS_PASS), _result("stale_escrows", STATUS_PASS)]
        assert correlate_failures(results) is None

    def test_error_status_counts_as_failure(self):
        """STATUS_ERROR contributes to failure count for correlation."""
        results = [
            _result("stale_escrows", STATUS_ERROR),
            _result("invariant", STATUS_FAIL),
        ]
        corr = correlate_failures(results)
        assert corr is not None

    def test_skip_status_does_not_count_as_failure(self):
        """STATUS_SKIP checks are ignored in correlation."""
        results = [
            _result("idem_consistency", STATUS_SKIP),
            _result("invariant", STATUS_FAIL),
        ]
        # Only 1 non-SKIP failure → no correlation
        assert correlate_failures(results) is None

    def test_unknown_check_has_no_parents(self):
        """A check not in DEPENDENCY_GRAPH is always a root cause."""
        results = [
            {"name": "brand_new_check", "status": STATUS_FAIL, "script": None,
             "exit_code": 1, "stdout": "", "stderr": "", "skip_reason": None},
            _result("invariant", STATUS_FAIL),
        ]
        corr = correlate_failures(results)
        assert corr is not None
        assert "brand_new_check" in corr["root_causes"]


# ===========================================================================
# build_report structure tests
# ===========================================================================


class TestBuildReport:
    def test_pass_report_structure(self):
        results = [_result("invariant", STATUS_PASS), _result("stale_escrows", STATUS_PASS)]
        report = build_report(results, "2026-04-08T00:00:00Z")
        assert report["version"] == 1
        assert report["overall_status"] == "PASS"
        assert report["failed_count"] == 0
        assert report["failed_checks"] == []
        assert report["correlation"] is None
        assert report["generated_at"] == "2026-04-08T00:00:00Z"

    def test_incident_report_has_correlation(self):
        results = [
            _result("stale_escrows", STATUS_FAIL),
            _result("task_escrow_sync", STATUS_FAIL),
        ]
        report = build_report(results, "2026-04-08T00:00:00Z")
        assert report["overall_status"] == "INCIDENT"
        assert report["failed_count"] == 2
        assert report["correlation"] is not None
        corr = report["correlation"]
        assert "root_causes" in corr
        assert "investigation_order" in corr
        assert "rules_applied" in corr

    def test_single_failure_no_correlation(self):
        results = [_result("invariant", STATUS_FAIL), _result("stale_escrows", STATUS_PASS)]
        report = build_report(results, "2026-04-08T00:00:00Z")
        assert report["overall_status"] == "INCIDENT"
        assert report["correlation"] is None


# ===========================================================================
# Integration tests: run_all_checks against a real minimal ledger
# ===========================================================================


class TestRunAllChecks:
    def test_all_checks_return_results(self, tmp_path):
        """run_all_checks returns one result per registry entry."""
        from check_incident_correlator import _CHECK_REGISTRY
        root = _make_ledger(tmp_path)
        results = run_all_checks(root)
        assert len(results) == len(_CHECK_REGISTRY)

    def test_every_result_has_required_keys(self, tmp_path):
        root = _make_ledger(tmp_path)
        results = run_all_checks(root)
        required = {"name", "script", "status", "exit_code", "stdout", "stderr"}
        for r in results:
            assert required.issubset(r.keys()), f"Missing keys in result for {r.get('name')}"

    def test_missing_script_gets_skip_status(self, tmp_path):
        """Checks with script=None are SKIP, not FAIL."""
        root = _make_ledger(tmp_path)
        results = run_all_checks(root)
        skipped = [r for r in results if r["script"] is None]
        assert all(r["status"] == STATUS_SKIP for r in skipped)

    def test_valid_ledger_runnable_checks_pass(self, tmp_path):
        """Checks that can run on a clean ledger should all pass."""
        root = _make_ledger(tmp_path)
        results = run_all_checks(root)
        runnable = [r for r in results if r["status"] != STATUS_SKIP]
        assert all(r["status"] == STATUS_PASS for r in runnable), (
            [(r["name"], r["status"], r["stdout"][:200]) for r in runnable if r["status"] != STATUS_PASS]
        )

    def test_status_values_are_valid(self, tmp_path):
        root = _make_ledger(tmp_path)
        results = run_all_checks(root)
        valid = {STATUS_PASS, STATUS_FAIL, STATUS_SKIP, STATUS_ERROR}
        for r in results:
            assert r["status"] in valid, f"{r['name']} has unexpected status {r['status']!r}"


# ===========================================================================
# Subprocess / exit code tests
# ===========================================================================


class TestSubprocessBehaviour:
    def test_exit_0_on_all_pass(self, tmp_path):
        """Script exits 0 when all runnable checks pass."""
        root = _make_ledger(tmp_path)
        proc = _run_script(root)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_json_report_in_stdout(self, tmp_path):
        """Script emits valid JSON as the first block of stdout."""
        root = _make_ledger(tmp_path)
        proc = _run_script(root)
        # JSON is printed first; find the end of the first JSON object.
        first_json = proc.stdout.split("\n\n")[0]
        report = json.loads(first_json)
        assert "version" in report
        assert "overall_status" in report
        assert "check_results" in report

    def test_json_only_flag_suppresses_human_output(self, tmp_path):
        """--json-only produces pure JSON with no human summary section."""
        root = _make_ledger(tmp_path)
        proc = _run_script(root, extra=["--json-only"])
        # Should parse cleanly as a single JSON object.
        report = json.loads(proc.stdout)
        assert report["overall_status"] in ("PASS", "INCIDENT")
        # No "Incident Correlator" header line in output.
        assert "Incident Correlator" not in proc.stdout

    def test_exit_1_on_broken_invariant(self, tmp_path):
        """Deliberately break the invariant — script should exit 1."""
        root = _make_ledger(tmp_path)
        # Give agent0 a wrong balance to break sum(balances) + escrows != 10000.
        (root / "ledger" / "balances.json").write_text(
            json.dumps({"agents": {"agent0@system": {"balance": 9999}}}),
            encoding="utf-8",
        )
        proc = _run_script(root)
        assert proc.returncode == 1

    def test_report_contains_all_check_names(self, tmp_path):
        """Every registry check name appears in check_results."""
        from check_incident_correlator import _CHECK_REGISTRY
        root = _make_ledger(tmp_path)
        proc = _run_script(root)
        first_json = proc.stdout.split("\n\n")[0]
        report = json.loads(first_json)
        result_names = {r["name"] for r in report["check_results"]}
        registry_names = {c["name"] for c in _CHECK_REGISTRY}
        assert registry_names == result_names
