"""
Tests for the circle-1 Phase 1 task contract completeness extractor.

Coverage:
  - Compliant tasks (all four elements present) are classified as complete.
  - Incomplete tasks (one or more elements missing) are classified as incomplete.
  - Each missing element is reported individually.
  - Duel tasks are excluded from the code-change cohort.
  - Rate calculation is correct across mixed cohorts.
  - Machine-readable output contains required fields.
"""

from __future__ import annotations

import json

import pytest

from scripts.circle1.extract_contract_completeness import (
    classify_task,
    classify_tasks,
    extract_elements,
    is_code_change,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPLETE_BODY = """\
### Your Agent ID

agent0@system

### What needs to be done

## Goal
- Build the thing.

### Verification Criteria

- [ ] MUST: pytest tests/ -q exits 0 with no regressions
- [ ] MUST NOT: Modify files outside the agreed scope
- [ ] MUST: Agent0 confirms behavior matches spec

### Scope boundaries

In scope: scripts/circle1/
Out of scope: ledger/, payment mechanics, issue templates
"""

# Missing MUST NOT
BODY_NO_MUST_NOT = """\
### Verification Criteria

- [ ] MUST: pytest passes

### Scope boundaries

In scope: scripts/
Out of scope: nothing
"""

# Missing MUST (only has MUST NOT)
BODY_NO_MUST = """\
### Verification Criteria

- [ ] MUST NOT: Do not break ledger

### Scope boundaries

In scope: scripts/
Out of scope: nothing
"""

# Missing Verification Criteria section entirely
BODY_NO_VERIFICATION = """\
### What needs to be done

Describe task here.

### Scope boundaries

In scope: scripts/
Out of scope: nothing
"""

# Missing Scope boundaries section
BODY_NO_SCOPE = """\
### Verification Criteria

- [ ] MUST: tests pass
- [ ] MUST NOT: no scope creep
"""

# Missing both Verification Criteria and Scope boundaries
BODY_MINIMAL = """\
### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

10
"""

# Duel task (excluded from code-change cohort)
DUEL_BODY = """\
### Verification Criteria

- [ ] MUST: best argument wins
- [ ] MUST NOT: ignore evidence

### Scope boundaries

In scope: debate
Out of scope: code
"""

# Issue #781 — the task that spawned this extractor (real-world complete example)
ISSUE_781_BODY = """\
### Your Agent ID

agent0@system

### What needs to be done

## Goal
- Build a deterministic extractor for code-change task contract completeness.

### Why (motivation)

First bounded measurement-extension cut.

### Expected outcome

One deterministic extractor.

### Verification Criteria

- [ ] MUST: Targeted tests for the extractor pass locally
- [ ] MUST: At least one fixture-backed test proves compliant and incomplete tasks are classified differently
- [ ] MUST: The extractor emits machine-readable output with counts plus issue-level findings or identifiers
- [ ] MUST: The implementation documents exactly what qualifies as complete vs incomplete for Phase 1
- [ ] MUST NOT: Rewrite the global task template, Tide settlement logic, or issue-governance mechanics as part of this task
- [ ] MUST NOT: Claim cohort/outcome metrics from GitHub history beyond the bounded contract-completeness signal implemented here
- [ ] MUST: Manual: Agent0 confirms the output is strong enough to use in later circle-1 monitoring

### Scope boundaries

In scope: a deterministic extractor under `scripts/` or `scripts/circle1/`, targeted tests.
Out of scope: full GitHub-history outcome mining, changes to payment mechanics.
"""


# ---------------------------------------------------------------------------
# extract_elements
# ---------------------------------------------------------------------------

class TestExtractElements:
    def test_complete_body_has_all_four(self) -> None:
        elems = extract_elements(COMPLETE_BODY)
        assert elems["verification_criteria"] is True
        assert elems["must_criterion"] is True
        assert elems["must_not_criterion"] is True
        assert elems["scope_boundaries"] is True

    def test_no_must_not(self) -> None:
        elems = extract_elements(BODY_NO_MUST_NOT)
        assert elems["must_criterion"] is True
        assert elems["must_not_criterion"] is False

    def test_no_must(self) -> None:
        elems = extract_elements(BODY_NO_MUST)
        assert elems["must_criterion"] is False
        assert elems["must_not_criterion"] is True

    def test_missing_verification_section(self) -> None:
        elems = extract_elements(BODY_NO_VERIFICATION)
        assert elems["verification_criteria"] is False
        assert elems["must_criterion"] is False
        assert elems["must_not_criterion"] is False

    def test_missing_scope_boundaries(self) -> None:
        elems = extract_elements(BODY_NO_SCOPE)
        assert elems["scope_boundaries"] is False
        assert elems["verification_criteria"] is True

    def test_minimal_body_all_false(self) -> None:
        elems = extract_elements(BODY_MINIMAL)
        assert all(v is False for v in elems.values())

    def test_issue_781_complete(self) -> None:
        """Real-world task body must be classified as complete."""
        elems = extract_elements(ISSUE_781_BODY)
        assert elems == {
            "verification_criteria": True,
            "must_criterion": True,
            "must_not_criterion": True,
            "scope_boundaries": True,
        }

    def test_must_not_does_not_satisfy_must(self) -> None:
        """MUST NOT lines must not count toward must_criterion."""
        body = """\
### Verification Criteria

- [ ] MUST NOT: do nothing harmful

### Scope boundaries

In scope: x
"""
        elems = extract_elements(body)
        assert elems["must_criterion"] is False
        assert elems["must_not_criterion"] is True

    def test_checked_boxes_counted(self) -> None:
        """Checked [x] boxes count the same as unchecked [ ]."""
        body = """\
### Verification Criteria

- [x] MUST: tests pass
- [x] MUST NOT: no breakage

### Scope boundaries

In scope: x
"""
        elems = extract_elements(body)
        assert elems["must_criterion"] is True
        assert elems["must_not_criterion"] is True

    def test_case_insensitive_must(self) -> None:
        body = """\
### Verification Criteria

- [ ] must: lowercase criterion
- [ ] must not: lowercase must not

### Scope boundaries

x
"""
        elems = extract_elements(body)
        assert elems["must_criterion"] is True
        assert elems["must_not_criterion"] is True

    def test_no_response_verification_treated_as_absent(self) -> None:
        body = """\
### Verification Criteria

_No response_

### Scope boundaries

In scope: x
"""
        elems = extract_elements(body)
        assert elems["verification_criteria"] is False

    def test_no_response_scope_treated_as_absent(self) -> None:
        body = """\
### Verification Criteria

- [ ] MUST: x
- [ ] MUST NOT: y

### Scope boundaries

_No response_
"""
        elems = extract_elements(body)
        assert elems["scope_boundaries"] is False


# ---------------------------------------------------------------------------
# is_code_change
# ---------------------------------------------------------------------------

class TestIsCodeChange:
    def test_duel_excluded(self) -> None:
        ok, reason = is_code_change("duel")
        assert ok is False
        assert reason == "duel"

    def test_duel_case_insensitive(self) -> None:
        ok, reason = is_code_change("DUEL")
        assert ok is False

    def test_winner_take_all_included(self) -> None:
        ok, reason = is_code_change("winner_take_all")
        assert ok is True
        assert reason is None

    def test_none_reward_type_included(self) -> None:
        ok, reason = is_code_change(None)
        assert ok is True
        assert reason is None

    def test_every_good_included(self) -> None:
        ok, reason = is_code_change("every_good")
        assert ok is True


# ---------------------------------------------------------------------------
# classify_task — key invariant: compliant vs incomplete differ
# ---------------------------------------------------------------------------

class TestClassifyTask:
    def test_complete_task_is_complete(self) -> None:
        finding = classify_task("100", COMPLETE_BODY)
        assert finding["is_complete"] is True
        assert finding["missing_elements"] == []
        assert finding["is_code_change"] is True

    def test_incomplete_task_is_not_complete(self) -> None:
        finding = classify_task("101", BODY_NO_MUST_NOT)
        assert finding["is_complete"] is False
        assert "must_not_criterion" in finding["missing_elements"]

    def test_compliant_and_incomplete_classified_differently(self) -> None:
        """Core fixture test: compliant != incomplete."""
        complete = classify_task("200", COMPLETE_BODY)
        incomplete = classify_task("201", BODY_NO_SCOPE)
        assert complete["is_complete"] is True
        assert incomplete["is_complete"] is False
        assert complete["is_complete"] != incomplete["is_complete"]

    def test_duel_excluded_not_complete(self) -> None:
        finding = classify_task("300", DUEL_BODY, reward_type="duel")
        assert finding["is_code_change"] is False
        assert finding["excluded_reason"] == "duel"
        assert finding["is_complete"] is False

    def test_missing_elements_lists_all_absent(self) -> None:
        finding = classify_task("102", BODY_MINIMAL)
        missing = set(finding["missing_elements"])
        assert missing == {
            "verification_criteria",
            "must_criterion",
            "must_not_criterion",
            "scope_boundaries",
        }

    def test_issue_id_preserved(self) -> None:
        finding = classify_task("781", ISSUE_781_BODY)
        assert finding["issue_id"] == "781"


# ---------------------------------------------------------------------------
# classify_tasks — report shape and rate calculation
# ---------------------------------------------------------------------------

class TestClassifyTasks:
    def _make_tasks(self) -> dict:
        return {
            "100": {"body": COMPLETE_BODY, "reward_type": "winner_take_all"},
            "101": {"body": BODY_NO_SCOPE, "reward_type": "winner_take_all"},
            "102": {"body": DUEL_BODY, "reward_type": "duel"},
        }

    def test_report_has_required_keys(self) -> None:
        report = classify_tasks(self._make_tasks())
        assert report["schema_version"] == "1"
        assert report["phase"] == "phase1"
        assert "scan_date" in report
        assert "definition" in report
        assert "summary" in report
        assert "findings" in report

    def test_summary_counts(self) -> None:
        report = classify_tasks(self._make_tasks())
        s = report["summary"]
        assert s["total_processed"] == 3
        assert s["excluded_tasks"] == 1        # duel
        assert s["code_change_tasks"] == 2
        assert s["complete"] == 1
        assert s["incomplete"] == 1

    def test_completeness_rate(self) -> None:
        report = classify_tasks(self._make_tasks())
        assert report["summary"]["task_contract_completeness_rate"] == 0.5

    def test_rate_zero_on_all_incomplete(self) -> None:
        tasks = {
            "1": {"body": BODY_MINIMAL},
            "2": {"body": BODY_NO_SCOPE},
        }
        report = classify_tasks(tasks)
        assert report["summary"]["task_contract_completeness_rate"] == 0.0
        assert report["summary"]["complete"] == 0

    def test_rate_one_on_all_complete(self) -> None:
        tasks = {
            "1": {"body": COMPLETE_BODY},
            "2": {"body": ISSUE_781_BODY},
        }
        report = classify_tasks(tasks)
        assert report["summary"]["task_contract_completeness_rate"] == 1.0

    def test_rate_zero_when_no_code_change_tasks(self) -> None:
        tasks = {
            "1": {"body": DUEL_BODY, "reward_type": "duel"},
        }
        report = classify_tasks(tasks)
        assert report["summary"]["code_change_tasks"] == 0
        assert report["summary"]["task_contract_completeness_rate"] == 0.0

    def test_findings_list_length_matches_input(self) -> None:
        tasks = self._make_tasks()
        report = classify_tasks(tasks)
        assert len(report["findings"]) == len(tasks)

    def test_output_is_json_serialisable(self) -> None:
        report = classify_tasks(self._make_tasks())
        serialised = json.dumps(report)
        parsed = json.loads(serialised)
        assert parsed["summary"]["total_processed"] == 3

    def test_definition_documents_elements(self) -> None:
        report = classify_tasks(self._make_tasks())
        d = report["definition"]
        assert "verification_criteria" in d["complete_requires"]
        assert "must_criterion" in d["complete_requires"]
        assert "must_not_criterion" in d["complete_requires"]
        assert "scope_boundaries" in d["complete_requires"]
        assert "duel" in d["code_change_excludes"]

    def test_empty_tasks_dict(self) -> None:
        report = classify_tasks({})
        assert report["summary"]["total_processed"] == 0
        assert report["summary"]["task_contract_completeness_rate"] == 0.0
        assert report["findings"] == []
