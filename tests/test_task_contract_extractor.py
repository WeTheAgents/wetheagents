"""Tests for scripts/circle1/task_contract_extractor.py — circle-1 phase 1."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.circle1.task_contract_extractor import classify_body, extract_completeness


# ── Fixtures ──────────────────────────────────────────────────────────────────

COMPLIANT_BODY = """\
### Your Agent ID

agent0@system

### What needs to be done

## Goal
Build the extractor.

### Why (motivation)

Instrumentation.

### Expected outcome

Working code with tests.

### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0 with no regressions
- [ ] MUST: At least one fixture-backed test proves compliant vs incomplete classification
- [ ] MUST NOT: Rewrite the global task template or issue-governance mechanics

### Scope boundaries

In scope: `scripts/circle1/`, targeted tests
Out of scope: issue templates, governance mechanics, full GitHub-history mining

### Skills Needed

Coding (Python)
Data Analysis
Review / QA

### Estimated appetite

3 days

### Reward Type

Winner Take All
"""

MISSING_MUST_NOT_BODY = """\
### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0

### Scope boundaries

In scope: scripts/
Out of scope: nothing else

### Skills Needed

Coding (Python)
"""

MISSING_MUST_BODY = """\
### Verification Criteria

- [ ] MUST NOT: Modify files outside scope

### Scope boundaries

In scope: scripts/
Out of scope: nothing else

### Skills Needed

Coding (Python)
"""

MISSING_VERIFICATION_CRITERIA_BODY = """\
### What needs to be done

Build something useful.

### Scope boundaries

In scope: scripts/
Out of scope: everything else

### Skills Needed

Coding (Python)
"""

PLACEHOLDER_SCOPE_BODY = """\
### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST NOT: Modify unrelated files

### Scope boundaries

_No response_

### Skills Needed

Coding (Python)
"""

ABSENT_SCOPE_BODY = """\
### Verification Criteria

- [ ] MUST: Tests pass
- [ ] MUST NOT: Break things

### Skills Needed

Coding (Python)
"""

NON_CODING_SKILLS_BODY = """\
### Verification Criteria

Summary of analysis.

### Scope boundaries

In scope: research only

### Skills Needed

Research
Writing / Documentation
"""

PYTEST_IN_VC_BODY = """\
### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST NOT: Touch unrelated files

### Scope boundaries

In scope: scripts/

### Skills Needed

Review / QA
"""

DUEL_BODY = COMPLIANT_BODY


# ── Element detection ────────────────────────────────────────────────────────

class TestElementDetection:

    def test_compliant_body_has_all_elements(self):
        r = classify_body(COMPLIANT_BODY, mechanic="winner_take_all", issue="100")
        assert set(r["present_elements"]) == {
            "must", "must_not", "verification_criteria", "scope_boundaries"
        }
        assert r["missing_elements"] == []

    def test_missing_must_not_detected(self):
        r = classify_body(MISSING_MUST_NOT_BODY, mechanic="best_x", issue="101")
        assert "must_not" in r["missing_elements"]
        assert "must" in r["present_elements"]

    def test_missing_must_detected(self):
        r = classify_body(MISSING_MUST_BODY, mechanic="best_x", issue="102")
        assert "must" in r["missing_elements"]
        assert "must_not" in r["present_elements"]

    def test_missing_verification_criteria_section_detected(self):
        r = classify_body(MISSING_VERIFICATION_CRITERIA_BODY, mechanic="best_x", issue="103")
        assert "verification_criteria" in r["missing_elements"]

    def test_placeholder_scope_counts_as_missing(self):
        r = classify_body(PLACEHOLDER_SCOPE_BODY, mechanic="best_x", issue="104")
        assert "scope_boundaries" in r["missing_elements"]

    def test_absent_scope_section_counts_as_missing(self):
        r = classify_body(ABSENT_SCOPE_BODY, mechanic="best_x", issue="105")
        assert "scope_boundaries" in r["missing_elements"]

    def test_must_not_line_does_not_satisfy_must_requirement(self):
        """MUST NOT items must not count toward the MUST requirement."""
        r = classify_body(MISSING_MUST_BODY, mechanic="best_x", issue="106")
        assert "must" in r["missing_elements"]
        assert "must_not" not in r["missing_elements"]

    def test_checked_must_item_counts(self):
        """A checked "- [x] MUST:" line still satisfies the MUST requirement."""
        body = """\
### Verification Criteria

- [x] MUST: `pytest` passes
- [ ] MUST NOT: Break anything

### Scope boundaries

In scope: scripts/

### Skills Needed

Coding (Python)
"""
        r = classify_body(body, mechanic="best_x", issue="107")
        assert "must" in r["present_elements"]

    def test_checked_must_not_item_counts(self):
        """A checked "- [x] MUST NOT:" line still satisfies the MUST NOT requirement."""
        body = """\
### Verification Criteria

- [ ] MUST: Tests pass
- [x] MUST NOT: Modify governance files

### Scope boundaries

In scope: scripts/

### Skills Needed

Coding (Python)
"""
        r = classify_body(body, mechanic="best_x", issue="108")
        assert "must_not" in r["present_elements"]

    def test_must_outside_vc_section_does_not_satisfy_must(self):
        """MUST checkboxes in other sections (not Verification Criteria) must not count."""
        body = """\
### What needs to be done

- [ ] MUST: Use Python 3.10+

### Verification Criteria

No explicit MUST items here.

### Scope boundaries

In scope: scripts/

### Skills Needed

Coding (Python)
"""
        r = classify_body(body, mechanic="best_x", issue="109")
        assert "must" in r["missing_elements"]

    def test_must_not_outside_vc_section_does_not_satisfy_must_not(self):
        """MUST NOT checkboxes outside Verification Criteria must not count."""
        body = """\
### Goals

- [ ] MUST NOT: Break production

### Verification Criteria

- [ ] MUST: Tests pass

### Scope boundaries

In scope: scripts/

### Skills Needed

Coding (Python)
"""
        r = classify_body(body, mechanic="best_x", issue="110")
        assert "must_not" in r["missing_elements"]


# ── Code-change classification ────────────────────────────────────────────────

class TestCodeChangeClassification:

    def test_coding_skill_marks_as_code_change(self):
        r = classify_body(COMPLIANT_BODY, mechanic="winner_take_all", issue="200")
        assert r["is_code_change"] is True

    def test_non_coding_skills_not_classified_as_code_change(self):
        r = classify_body(NON_CODING_SKILLS_BODY, mechanic="best_x", issue="201")
        assert r["is_code_change"] is False

    def test_duel_mechanic_excluded_regardless_of_body(self):
        r = classify_body(DUEL_BODY, mechanic="duel", issue="202")
        assert r["is_code_change"] is False

    def test_pytest_artifact_in_vc_marks_as_code_change_without_coding_skill(self):
        r = classify_body(PYTEST_IN_VC_BODY, mechanic="best_x", issue="203")
        assert r["is_code_change"] is True

    def test_empty_body_not_code_change(self):
        r = classify_body("", mechanic="best_x", issue="204")
        assert r["is_code_change"] is False


# ── Complete vs incomplete ────────────────────────────────────────────────────

class TestCompleteVsIncomplete:

    def test_compliant_code_change_task_is_complete(self):
        """Key fixture: compliant body + coding skill → complete=True."""
        r = classify_body(COMPLIANT_BODY, mechanic="winner_take_all", issue="300")
        assert r["complete"] is True

    def test_missing_must_not_makes_task_incomplete(self):
        """Key fixture: missing MUST NOT → complete=False."""
        r = classify_body(MISSING_MUST_NOT_BODY, mechanic="best_x", issue="301")
        assert r["complete"] is False
        assert "must_not" in r["missing_elements"]

    def test_non_code_change_task_is_never_complete(self):
        """Non-code-change tasks are excluded from the cohort; complete is always False."""
        r = classify_body(NON_CODING_SKILLS_BODY, mechanic="best_x", issue="302")
        assert r["complete"] is False
        assert r["is_code_change"] is False

    def test_duel_task_is_never_complete(self):
        r = classify_body(DUEL_BODY, mechanic="duel", issue="303")
        assert r["complete"] is False


# ── extract_completeness aggregation ─────────────────────────────────────────

class TestExtractCompleteness:

    def test_empty_input_produces_zero_counts(self):
        result = extract_completeness([])
        assert result["total_inspected"] == 0
        assert result["code_change_count"] == 0
        assert result["complete_count"] == 0
        assert result["task_contract_completeness_rate"] is None

    def test_all_complete_tasks_yield_rate_one(self):
        issues = [
            {"number": "1", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"},
            {"number": "2", "body": COMPLIANT_BODY, "mechanic": "best_x"},
        ]
        result = extract_completeness(issues)
        assert result["task_contract_completeness_rate"] == 1.0
        assert result["complete_count"] == 2
        assert result["incomplete_count"] == 0

    def test_mixed_complete_and_incomplete_yields_correct_rate(self):
        """One compliant + one missing-must-not → rate = 0.5."""
        issues = [
            {"number": "1", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"},
            {"number": "2", "body": MISSING_MUST_NOT_BODY, "mechanic": "best_x"},
        ]
        result = extract_completeness(issues)
        assert result["code_change_count"] == 2
        assert result["complete_count"] == 1
        assert result["incomplete_count"] == 1
        assert result["task_contract_completeness_rate"] == 0.5

    def test_no_code_change_tasks_gives_none_rate(self):
        issues = [{"number": "1", "body": NON_CODING_SKILLS_BODY, "mechanic": "best_x"}]
        result = extract_completeness(issues)
        assert result["code_change_count"] == 0
        assert result["task_contract_completeness_rate"] is None

    def test_non_code_change_tasks_excluded_from_rate_but_in_findings(self):
        """Non-code-change tasks appear in findings but not in rate numerator/denominator."""
        issues = [
            {"number": "1", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"},
            {"number": "2", "body": NON_CODING_SKILLS_BODY, "mechanic": "best_x"},
        ]
        result = extract_completeness(issues)
        assert result["total_inspected"] == 2
        assert result["code_change_count"] == 1
        assert len(result["findings"]) == 2

    def test_output_has_all_required_fields(self):
        result = extract_completeness(
            [{"number": "1", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"}]
        )
        required = {
            "scan_date", "phase", "definition", "total_inspected",
            "code_change_count", "complete_count", "incomplete_count",
            "task_contract_completeness_rate", "findings",
        }
        assert required.issubset(result.keys())

    def test_findings_include_per_issue_fields(self):
        issues = [{"number": "42", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"}]
        result = extract_completeness(issues)
        assert len(result["findings"]) == 1
        finding = result["findings"][0]
        assert finding["issue"] == "42"
        assert "is_code_change" in finding
        assert "complete" in finding
        assert "missing_elements" in finding
        assert "present_elements" in finding

    def test_phase_is_phase_1(self):
        result = extract_completeness([])
        assert result["phase"] == "phase-1"

    def test_definition_includes_four_elements(self):
        result = extract_completeness([])
        defn = result["definition"]
        for element in ("MUST", "MUST NOT", "verification_criteria", "scope_boundaries"):
            assert element in defn

    def test_scan_date_override(self):
        result = extract_completeness([], scan_date="2026-04-23")
        assert result["scan_date"] == "2026-04-23"

    def test_issue_key_alias_number(self):
        issues = [{"number": 781, "body": COMPLIANT_BODY, "mechanic": "winner_take_all"}]
        result = extract_completeness(issues)
        assert result["findings"][0]["issue"] == "781"

    def test_issue_key_alias_issue(self):
        issues = [{"issue": "781", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"}]
        result = extract_completeness(issues)
        assert result["findings"][0]["issue"] == "781"


# ── CLI smoke test ────────────────────────────────────────────────────────────

class TestCLI:

    def test_cli_no_args_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "scripts/circle1/task_contract_extractor.py"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_cli_valid_input_emits_json(self, tmp_path):
        fixture = [
            {"number": "100", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"},
            {"number": "101", "body": MISSING_MUST_NOT_BODY, "mechanic": "best_x"},
        ]
        input_file = tmp_path / "issues.json"
        input_file.write_text(json.dumps(fixture), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "scripts/circle1/task_contract_extractor.py", str(input_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_inspected"] == 2
        assert data["task_contract_completeness_rate"] == 0.5

    def test_cli_missing_file_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "scripts/circle1/task_contract_extractor.py", "does_not_exist.json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_cli_scan_date_override(self, tmp_path):
        fixture = [{"number": "1", "body": COMPLIANT_BODY, "mechanic": "winner_take_all"}]
        input_file = tmp_path / "issues.json"
        input_file.write_text(json.dumps(fixture), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, "scripts/circle1/task_contract_extractor.py",
                str(input_file), "--scan-date", "2026-04-23",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["scan_date"] == "2026-04-23"
