"""Tests for scripts/validate_submission.py — T2 Slot 1.

Covers all 6 code paths in validate_submission():
1. Missing ## Submission section
2. Missing ## Agent section
3. Agent line extracted and checked for single '@'
4. Name/platform must have no spaces and be non-empty
5. Agent section exists but is empty (no content line follows)
6. Valid submission passes with empty error list
"""

from __future__ import annotations

from scripts.validate_submission import validate_submission


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_submission_passes() -> None:
    text = "## Submission\nSome content here.\n\n## Agent\nClaude-17@claude\n"
    assert validate_submission(text) == []


def test_valid_submission_with_extra_content_passes() -> None:
    text = (
        "# My Submission Title\n\n"
        "## Submission\n\n"
        "Detailed work goes here.\n\n"
        "## Agent\n\n"
        "my-agent@platform\n"
    )
    assert validate_submission(text) == []


def test_valid_submission_extra_whitespace_in_headers_passes() -> None:
    # ## with trailing spaces on header line is still matched
    text = "##  Submission  \n\ncontent\n\n##  Agent  \n\nagent@platform\n"
    assert validate_submission(text) == []


# ---------------------------------------------------------------------------
# Missing section errors
# ---------------------------------------------------------------------------


def test_missing_submission_section_fails() -> None:
    text = "## Agent\nClaude-17@claude\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "Submission" in errors[0]


def test_missing_agent_section_fails() -> None:
    text = "## Submission\nSome work.\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "Agent" in errors[0]


def test_both_sections_missing_fails() -> None:
    text = "Just some text with no required sections.\n"
    errors = validate_submission(text)
    assert len(errors) == 2


# ---------------------------------------------------------------------------
# Agent ID format errors
# ---------------------------------------------------------------------------


def test_agent_no_at_sign_fails() -> None:
    text = "## Submission\ncontent\n\n## Agent\nmyagent\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "myagent" in errors[0]


def test_agent_multiple_at_signs_fails() -> None:
    text = "## Submission\ncontent\n\n## Agent\nmy@agent@platform\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "my@agent@platform" in errors[0]


def test_agent_space_in_name_fails() -> None:
    text = "## Submission\ncontent\n\n## Agent\nmy agent@platform\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "my agent@platform" in errors[0]


def test_agent_space_in_platform_fails() -> None:
    text = "## Submission\ncontent\n\n## Agent\nagent@my platform\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "agent@my platform" in errors[0]


def test_agent_empty_name_fails() -> None:
    # "@platform" — name part is empty
    text = "## Submission\ncontent\n\n## Agent\n@platform\n"
    errors = validate_submission(text)
    assert len(errors) == 1


def test_agent_empty_platform_fails() -> None:
    # "agent@" — platform part is empty
    text = "## Submission\ncontent\n\n## Agent\nagent@\n"
    errors = validate_submission(text)
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# Empty agent section
# ---------------------------------------------------------------------------


def test_empty_agent_section_fails() -> None:
    # ## Agent at end of document with no following content line
    text = "## Submission\ncontent\n\n## Agent\n"
    errors = validate_submission(text)
    assert len(errors) == 1
    assert "empty" in errors[0].lower()
