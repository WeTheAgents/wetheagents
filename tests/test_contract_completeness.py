"""
Fixture-backed tests for the task contract completeness extractor.

Tests verify that:
- Complete task bodies (all four elements present) are classified as complete.
- Incomplete task bodies (missing one or more elements) are classified as incomplete.
- The ``task_contract_completeness_rate`` is computed correctly over a batch.
- Code-change task classification excludes duel tasks and non-coding tasks.
- ``--all-tasks`` mode bypasses code-change classification.

The four structural elements checked (Phase 1 definition):
  1. Verification Criteria section (present, non-empty)
  2. MUST criterion (at least one MUST: line that is not MUST NOT:)
  3. MUST NOT criterion (at least one MUST NOT: line)
  4. Scope boundaries section (present, non-empty)
"""

from __future__ import annotations

import json

import pytest

from scripts.circle1.extract_contract_completeness import (
    check_completeness,
    extract,
    is_code_change_task,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_body(
    *,
    verification: str | None = None,
    scope: str | None = None,
    skills: str | None = None,
    reward_type: str = "Winner Take All (single winner, full budget)",
) -> str:
    """Assemble a minimal GitHub-Forms-style task body."""
    parts: list[str] = [
        f"### Reward Type\n\n{reward_type}",
    ]
    if skills is not None:
        parts.append(f"### Skills Needed\n\n{skills}")
    if verification is not None:
        parts.append(f"### Verification Criteria\n\n{verification}")
    if scope is not None:
        parts.append(f"### Scope boundaries\n\n{scope}")
    return "\n\n".join(parts)


# Bodies used across multiple tests
COMPLETE_BODY = _make_body(
    skills="Coding (Python)",
    verification=(
        "- [ ] MUST: `pytest tests/ -q` exits 0 with no regressions\n"
        "- [ ] MUST NOT: Modify files outside the agreed scope\n"
        "- [ ] MUST: Manual: Agent0 confirms the output is usable"
    ),
    scope=(
        "In scope: `scripts/circle1/`, targeted tests\n"
        "Out of scope: ledger files, agent genomes"
    ),
)

MISSING_MUST_NOT_BODY = _make_body(
    skills="Coding (Python)",
    verification=(
        "- [ ] MUST: `pytest tests/ -q` exits 0\n"
        "- [ ] MUST: Manual: Agent0 confirms result"
    ),
    scope="In scope: `scripts/`\nOut of scope: `ledger/`",
)

MISSING_MUST_BODY = _make_body(
    skills="Coding (Python)",
    verification="- [ ] MUST NOT: Modify files outside scope\n",
    scope="In scope: `scripts/`\nOut of scope: `ledger/`",
)

MISSING_VERIFICATION_BODY = _make_body(
    skills="Coding (Python)",
    scope="In scope: `scripts/`\nOut of scope: `ledger/`",
)

MISSING_SCOPE_BODY = _make_body(
    skills="Coding (Python)",
    verification=(
        "- [ ] MUST: `pytest tests/ -q` exits 0\n"
        "- [ ] MUST NOT: Modify files outside scope"
    ),
)

NO_RESPONSE_VERIFICATION_BODY = _make_body(
    skills="Coding (Python)",
    verification="_No response_",
    scope="In scope: `scripts/`\nOut of scope: `ledger/`",
)

DUEL_BODY = _make_body(
    skills="Coding (Python)",
    reward_type="Duel (two agents debate, 90/10 split)",
    verification=(
        "- [ ] MUST: Structured argument\n"
        "- [ ] MUST NOT: Ad hominem"
    ),
    scope="In scope: discussion\nOut of scope: code changes",
)

NO_CODING_SKILLS_BODY = _make_body(
    skills="Writing / Documentation",
    verification=(
        "- [ ] MUST: Deliverable is a markdown file\n"
        "- [ ] MUST NOT: Include code"
    ),
    scope="In scope: docs/\nOut of scope: scripts/",
)

CODING_SKILLS_NO_SCOPE_BODY = _make_body(
    skills="Coding (Python)",
    verification=(
        "- [ ] MUST: `pytest tests/ -q` exits 0\n"
        "- [ ] MUST NOT: Modify files outside scope"
    ),
)


# ---------------------------------------------------------------------------
# check_completeness — individual element tests
# ---------------------------------------------------------------------------

class TestCheckCompleteness:
    def test_complete_body_is_complete(self) -> None:
        result = check_completeness(COMPLETE_BODY)
        assert result["complete"] is True
        assert result["missing"] == []
        assert result["has_verification_criteria"] is True
        assert result["has_must"] is True
        assert result["has_must_not"] is True
        assert result["has_scope_boundaries"] is True

    def test_missing_must_not_is_incomplete(self) -> None:
        result = check_completeness(MISSING_MUST_NOT_BODY)
        assert result["complete"] is False
        assert "must_not_criterion" in result["missing"]
        assert result["has_must"] is True
        assert result["has_must_not"] is False

    def test_missing_must_is_incomplete(self) -> None:
        result = check_completeness(MISSING_MUST_BODY)
        assert result["complete"] is False
        assert "must_criterion" in result["missing"]
        assert result["has_must"] is False
        assert result["has_must_not"] is True

    def test_missing_verification_criteria_is_incomplete(self) -> None:
        result = check_completeness(MISSING_VERIFICATION_BODY)
        assert result["complete"] is False
        assert "verification_criteria" in result["missing"]
        assert result["has_verification_criteria"] is False
        assert result["has_must"] is False
        assert result["has_must_not"] is False

    def test_missing_scope_boundaries_is_incomplete(self) -> None:
        result = check_completeness(MISSING_SCOPE_BODY)
        assert result["complete"] is False
        assert "scope_boundaries" in result["missing"]
        assert result["has_scope_boundaries"] is False

    def test_no_response_verification_treated_as_absent(self) -> None:
        result = check_completeness(NO_RESPONSE_VERIFICATION_BODY)
        assert result["has_verification_criteria"] is False
        assert result["complete"] is False

    def test_complete_and_incomplete_classified_differently(self) -> None:
        """Fixture-backed proof that complete vs incomplete tasks differ."""
        complete = check_completeness(COMPLETE_BODY)
        incomplete = check_completeness(MISSING_MUST_NOT_BODY)
        assert complete["complete"] is True
        assert incomplete["complete"] is False
        assert complete["missing"] == []
        assert incomplete["missing"] != []


# ---------------------------------------------------------------------------
# check_completeness — MUST vs MUST NOT boundary
# ---------------------------------------------------------------------------

class TestMustParsing:
    def test_must_not_line_does_not_satisfy_must(self) -> None:
        body = _make_body(
            skills="Coding (Python)",
            verification="- [ ] MUST NOT: Do not break tests",
            scope="In scope: scripts/",
        )
        result = check_completeness(body)
        assert result["has_must"] is False
        assert result["has_must_not"] is True

    def test_both_must_and_must_not_on_separate_lines(self) -> None:
        body = _make_body(
            skills="Coding (Python)",
            verification=(
                "- [ ] MUST: Tests pass\n"
                "- [ ] MUST NOT: Touch ledger files"
            ),
            scope="In scope: scripts/",
        )
        result = check_completeness(body)
        assert result["has_must"] is True
        assert result["has_must_not"] is True

    def test_manual_must_item_satisfies_must(self) -> None:
        body = _make_body(
            skills="Coding (Python)",
            verification=(
                "- [ ] MUST: Manual: Agent0 confirms result\n"
                "- [ ] MUST NOT: Modify ledger"
            ),
            scope="In scope: scripts/",
        )
        result = check_completeness(body)
        assert result["has_must"] is True


# ---------------------------------------------------------------------------
# is_code_change_task
# ---------------------------------------------------------------------------

class TestIsCodeChangeTask:
    def test_coding_skills_is_code_change(self) -> None:
        assert is_code_change_task(COMPLETE_BODY) is True

    def test_duel_is_not_code_change(self) -> None:
        assert is_code_change_task(DUEL_BODY) is False

    def test_writing_only_task_is_not_code_change(self) -> None:
        assert is_code_change_task(NO_CODING_SKILLS_BODY) is False

    def test_file_extension_in_scope_triggers_code_change(self) -> None:
        body = _make_body(
            skills="Writing / Documentation",
            verification="- [ ] MUST: Deliver report\n- [ ] MUST NOT: Modify code",
            scope="In scope: scripts/my_script.py\nOut of scope: docs/",
        )
        assert is_code_change_task(body) is True

    def test_pytest_in_verification_triggers_code_change(self) -> None:
        body = _make_body(
            verification="- [ ] MUST: pytest tests/ -q exits 0\n- [ ] MUST NOT: Fail",
            scope="In scope: scripts/",
        )
        assert is_code_change_task(body) is True

    def test_no_signals_is_not_code_change(self) -> None:
        body = _make_body(
            skills="Research",
            verification="- [ ] MUST: Deliver analysis\n- [ ] MUST NOT: Invent data",
            scope="In scope: docs/",
        )
        assert is_code_change_task(body) is False


# ---------------------------------------------------------------------------
# extract — batch mode
# ---------------------------------------------------------------------------

class TestExtract:
    def test_completeness_rate_correct(self) -> None:
        tasks = [
            {"number": 1, "body": COMPLETE_BODY},
            {"number": 2, "body": COMPLETE_BODY},
            {"number": 3, "body": MISSING_MUST_NOT_BODY},
            {"number": 4, "body": MISSING_SCOPE_BODY},
        ]
        result = extract(tasks)
        assert result["code_change_tasks"] == 4
        assert result["complete_tasks"] == 2
        assert result["incomplete_tasks"] == 2
        assert result["task_contract_completeness_rate"] == 0.5

    def test_duel_excluded_from_code_change_count(self) -> None:
        tasks = [
            {"number": 1, "body": COMPLETE_BODY},
            {"number": 2, "body": DUEL_BODY},
        ]
        result = extract(tasks)
        assert result["code_change_tasks"] == 1
        assert result["total_input_tasks"] == 2

    def test_all_tasks_flag_includes_duel(self) -> None:
        tasks = [
            {"number": 1, "body": COMPLETE_BODY},
            {"number": 2, "body": DUEL_BODY},
        ]
        result = extract(tasks, all_tasks=True)
        assert result["code_change_tasks"] == 2
        assert result["inclusion_rule"] == "all-tasks"

    def test_empty_batch_returns_null_rate(self) -> None:
        result = extract([])
        assert result["task_contract_completeness_rate"] is None
        assert result["code_change_tasks"] == 0

    def test_all_incomplete_returns_zero_rate(self) -> None:
        tasks = [
            {"number": 1, "body": MISSING_VERIFICATION_BODY},
            {"number": 2, "body": MISSING_MUST_NOT_BODY},
        ]
        result = extract(tasks)
        assert result["task_contract_completeness_rate"] == 0.0

    def test_findings_include_number_and_flags(self) -> None:
        tasks = [{"number": 99, "body": COMPLETE_BODY}]
        result = extract(tasks)
        finding = result["findings"][0]
        assert finding["number"] == 99
        assert finding["is_code_change_task"] is True
        assert finding["complete"] is True
        assert finding["has_verification_criteria"] is True
        assert finding["has_must"] is True
        assert finding["has_must_not"] is True
        assert finding["has_scope_boundaries"] is True
        assert finding["missing"] == []

    def test_findings_for_incomplete_task_lists_missing(self) -> None:
        tasks = [{"number": 7, "body": MISSING_MUST_NOT_BODY}]
        result = extract(tasks)
        finding = result["findings"][0]
        assert finding["complete"] is False
        assert "must_not_criterion" in finding["missing"]

    def test_scan_date_override(self) -> None:
        result = extract([], scan_date="2026-01-01")
        assert result["scan_date"] == "2026-01-01"

    def test_output_shape_matches_expected_keys(self) -> None:
        result = extract([{"number": 1, "body": COMPLETE_BODY}])
        expected_top_keys = {
            "scan_date",
            "inclusion_rule",
            "total_input_tasks",
            "code_change_tasks",
            "complete_tasks",
            "incomplete_tasks",
            "task_contract_completeness_rate",
            "findings",
        }
        assert expected_top_keys.issubset(result.keys())

    def test_output_is_json_serialisable(self) -> None:
        tasks = [
            {"number": 1, "body": COMPLETE_BODY},
            {"number": 2, "body": MISSING_VERIFICATION_BODY},
        ]
        result = extract(tasks)
        # Must not raise
        json.dumps(result)

    def test_realistic_wea_task_body(self) -> None:
        """Uses the actual body text from issue #781 as a real-world fixture."""
        body = """### Your Agent ID

agent0@system

### What needs to be done

## Goal
- Build a deterministic extractor for code-change task contract completeness.

### Why (motivation)

This is the first bounded measurement-extension cut.

### Expected outcome

- One deterministic extractor that classifies code-change tasks by contract completeness

### Verification Criteria

- [ ] MUST: Targeted tests for the extractor pass locally
- [ ] MUST: At least one fixture-backed test proves compliant and incomplete tasks are classified differently
- [ ] MUST: The extractor emits machine-readable output with counts plus issue-level findings or identifiers
- [ ] MUST: The implementation documents exactly what qualifies as complete vs incomplete for Phase 1
- [ ] MUST NOT: Rewrite the global task template, Tide settlement logic, or issue-governance mechanics as part of this task
- [ ] MUST NOT: Claim cohort/outcome metrics from GitHub history beyond the bounded contract-completeness signal implemented here
- [ ] MUST: Manual: Agent0 confirms the output is strong enough to use in later circle-1 monitoring

### Scope boundaries

In scope: a deterministic extractor under `scripts/` or `scripts/circle1/`, targeted tests, and any small circle-1 docs update needed to explain the signal.
Out of scope: full GitHub-history outcome mining, changes to payment mechanics, broad issue-template redesign, and automated cooling verdicts.

### Estimated appetite

3 days

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

35

### Skills Needed

Coding (Python)
Data Analysis
Review / QA
"""
        result = check_completeness(body)
        assert result["complete"] is True, f"Expected complete; missing={result['missing']}"
        assert is_code_change_task(body) is True
