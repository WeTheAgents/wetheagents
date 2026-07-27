"""Unit tests for src/wea_cli/parsers.py.

Covers all 5 public functions:
- normalize_header
- parse_field
- parse_section
- inspect_acceptance_criteria
- parse_task_metadata
"""

from __future__ import annotations

import pytest

from wea_cli.parsers import (
    inspect_acceptance_criteria,
    normalize_header,
    parse_field,
    parse_section,
    parse_task_metadata,
)


# ---------------------------------------------------------------------------
# normalize_header
# ---------------------------------------------------------------------------


class TestNormalizeHeader:
    def test_basic_lowercasing(self) -> None:
        assert normalize_header("Reward Type") == "reward type"

    def test_strips_trailing_colon(self) -> None:
        assert normalize_header("Reward:") == "reward"

    def test_removes_parenthetical(self) -> None:
        assert normalize_header("Deadline (optional)") == "deadline"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_header("Reward  Type") == "reward type"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert normalize_header("  Reward Type  ") == "reward type"

    def test_empty_string(self) -> None:
        assert normalize_header("") == ""

    def test_unicode_content(self) -> None:
        assert normalize_header("Récompense") == "récompense"

    def test_parenthetical_with_inner_content(self) -> None:
        assert normalize_header("Reward (WEA)") == "reward"


# ---------------------------------------------------------------------------
# parse_field
# ---------------------------------------------------------------------------


class TestParseField:
    def test_heading_style_two_hashes(self) -> None:
        body = "## Reward Type\nPoD\n"
        assert parse_field(body, ["Reward Type"]) == "PoD"

    def test_heading_style_three_hashes(self) -> None:
        body = "### Skills Needed\nPython\n"
        assert parse_field(body, ["Skills Needed"]) == "Python"

    def test_bold_inline_style(self) -> None:
        body = "**Reward Type:** PoD\n"
        assert parse_field(body, ["Reward Type"]) == "PoD"

    def test_not_found_returns_none(self) -> None:
        body = "## Some Other Field\nvalue\n"
        assert parse_field(body, ["Reward Type"]) is None

    def test_empty_body_returns_none(self) -> None:
        assert parse_field("", ["Reward Type"]) is None

    def test_alias_matching_normalized_parenthetical(self) -> None:
        body = "## Deadline (optional)\n2026-05-01\n"
        assert parse_field(body, ["Deadline", "Deadline (optional)"]) == "2026-05-01"

    def test_unicode_field_value(self) -> None:
        body = "## Agent ID\nClaude-1@claude\n"
        assert parse_field(body, ["Agent ID"]) == "Claude-1@claude"

    def test_first_matching_alias_wins(self) -> None:
        body = "## Reward\n50\n\n## Reward Type\nPoD\n"
        assert parse_field(body, ["Reward", "Reward Type"]) == "50"


# ---------------------------------------------------------------------------
# parse_section
# ---------------------------------------------------------------------------


class TestParseSection:
    def test_normal_section_returns_content(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: do something\n\n"
            "## Next Section\nstuff\n"
        )
        result = parse_section(body, ["Acceptance Criteria"])
        assert result is not None
        assert "MUST" in result

    def test_no_response_returns_none(self) -> None:
        body = "## Acceptance Criteria\n\n_No response_\n\n## Other\nstuff\n"
        assert parse_section(body, ["Acceptance Criteria"]) is None

    def test_none_returns_none(self) -> None:
        body = "## Acceptance Criteria\n\nNone\n\n## Other\nstuff\n"
        assert parse_section(body, ["Acceptance Criteria"]) is None

    def test_section_not_found_returns_none(self) -> None:
        body = "## Completely Different Section\n\ncontent\n"
        assert parse_section(body, ["Acceptance Criteria"]) is None

    def test_empty_body_returns_none(self) -> None:
        assert parse_section("", ["Acceptance Criteria"]) is None

    def test_crlf_line_endings_normalized(self) -> None:
        body = (
            "## Acceptance Criteria\r\n\r\n"
            "- [ ] MUST: do something\r\n\r\n"
            "## Other\r\nstuff\r\n"
        )
        result = parse_section(body, ["Acceptance Criteria"])
        assert result is not None
        assert "MUST" in result

    def test_verification_criteria_alias(self) -> None:
        body = "## Verification Criteria\n\n- [ ] MUST: something\n\n## End\n\n"
        result = parse_section(body, ["Acceptance Criteria", "Verification Criteria"])
        assert result is not None


# ---------------------------------------------------------------------------
# inspect_acceptance_criteria
# ---------------------------------------------------------------------------


class TestInspectAcceptanceCriteria:
    def test_empty_body(self) -> None:
        result = inspect_acceptance_criteria("")
        assert result.source == "missing"
        assert result.errors
        assert "empty" in result.errors[0].lower()
        assert not result.is_valid

    def test_whitespace_only_body(self) -> None:
        result = inspect_acceptance_criteria("   \n\n  ")
        assert result.source == "missing"
        assert not result.is_valid

    def test_no_criteria_section(self) -> None:
        body = "## Some Section\n\ncontent here\n"
        result = inspect_acceptance_criteria(body)
        assert result.source == "missing"
        assert not result.is_valid

    def test_no_checkboxes_in_section(self) -> None:
        body = "## Acceptance Criteria\n\nno checkboxes here\n\n## End\n\n"
        result = inspect_acceptance_criteria(body)
        assert result.source == "malformed"
        assert not result.is_valid

    def test_unstructured_legacy_criteria_are_rejected(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] Tests pass\n"
            "- [x] Code runs\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert result.source == "malformed"
        assert not result.is_valid
        assert any("MUST:" in error and "MUST NOT:" in error for error in result.errors)

    def test_valid_structured_criteria(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: tests pass\n"
            "- [ ] MUST NOT: modify parsers.py\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert result.source == "structured"
        assert result.is_valid
        assert len(result.criteria) == 2

    def test_structured_missing_must_item(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST NOT: break things\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert not result.is_valid
        assert any("MUST:" in e for e in result.errors)

    def test_structured_missing_must_not_item(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: do the thing\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert not result.is_valid
        assert any("MUST NOT:" in e for e in result.errors)

    def test_mixed_structured_and_legacy_is_invalid(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: do the thing\n"
            "- [ ] unstructured item\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert not result.is_valid
        assert any("prefix every checkbox" in e for e in result.errors)

    def test_all_manual_criteria_is_invalid(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: manual: reviewer checks this\n"
            "- [ ] MUST NOT: manual: reviewer checks that\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert not result.is_valid
        assert any("non-manual" in e for e in result.errors)

    def test_manual_prefix_is_detected(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: manual: human check\n"
            "- [ ] MUST NOT: machine check\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        manual = [c for c in result.criteria if c.is_manual]
        machine = [c for c in result.criteria if not c.is_manual]
        assert len(manual) == 1
        assert len(machine) == 1
        assert manual[0].text == "human check"

    def test_machine_and_human_criteria_properties(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [ ] MUST: machine check\n"
            "- [ ] MUST NOT: manual: human check\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert result.has_machine_checks
        assert len(result.machine_criteria) == 1
        assert len(result.human_criteria) == 1

    def test_unstructured_uppercase_checkbox_is_rejected(self) -> None:
        body = (
            "## Acceptance Criteria\n\n"
            "- [X] Tests pass\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert result.source == "malformed"
        assert not result.is_valid

    def test_unstructured_verification_criteria_are_rejected(self) -> None:
        body = (
            "## Verification Criteria\n\n"
            "- [ ] Tests pass\n\n"
            "## Other\n\nstuff\n"
        )
        result = inspect_acceptance_criteria(body)
        assert result.source == "malformed"
        assert not result.is_valid


# ---------------------------------------------------------------------------
# parse_task_metadata
# ---------------------------------------------------------------------------


class TestParseTaskMetadata:
    def test_full_metadata_heading_style(self) -> None:
        body = (
            "## Your Agent ID\nClaude-1@claude\n\n"
            "## Reward Type\nPoD\n\n"
            "## Reward (WEA)\n50\n\n"
            "## Deadline\n2026-05-01\n\n"
            "## Skills Needed\nPython\n"
        )
        meta = parse_task_metadata(body)
        assert meta["agent_id"] == "Claude-1@claude"
        assert meta["reward_type"] == "PoD"
        assert meta["reward"] == "50"
        assert meta["deadline"] == "2026-05-01"
        assert meta["skills_needed"] == "Python"

    def test_empty_body_all_none(self) -> None:
        meta = parse_task_metadata("")
        assert meta["agent_id"] is None
        assert meta["reward_type"] is None
        assert meta["reward"] is None
        assert meta["deadline"] is None
        assert meta["skills_needed"] is None

    def test_partial_metadata_missing_fields_are_none(self) -> None:
        body = "## Reward Type\nWinner Take All\n\n## Reward\n100\n"
        meta = parse_task_metadata(body)
        assert meta["reward_type"] == "Winner Take All"
        assert meta["reward"] == "100"
        assert meta["agent_id"] is None
        assert meta["deadline"] is None

    def test_reward_alias_without_wea_suffix(self) -> None:
        body = "## Reward\n75\n"
        meta = parse_task_metadata(body)
        assert meta["reward"] == "75"

    def test_deadline_optional_alias(self) -> None:
        body = "## Deadline (optional)\n2026-06-01\n"
        meta = parse_task_metadata(body)
        assert meta["deadline"] == "2026-06-01"

    def test_skills_short_alias(self) -> None:
        body = "## Skills\nRust, Python\n"
        meta = parse_task_metadata(body)
        assert meta["skills_needed"] == "Rust, Python"

    def test_returns_exactly_five_keys(self) -> None:
        meta = parse_task_metadata("")
        assert set(meta.keys()) == {"agent_id", "reward_type", "reward", "deadline", "skills_needed"}

    def test_bold_inline_style_metadata(self) -> None:
        body = "**Reward Type:** PoD\n**Reward:** 30\n"
        meta = parse_task_metadata(body)
        assert meta["reward_type"] == "PoD"
        assert meta["reward"] == "30"
