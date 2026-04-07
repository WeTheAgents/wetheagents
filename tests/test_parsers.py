from __future__ import annotations

from wea_cli.parsers import (
    inspect_acceptance_criteria,
    normalize_header,
    parse_field,
    parse_section,
    parse_task_metadata,
)


def test_normalize_header_strips_case_parentheses_and_colon() -> None:
    assert normalize_header("  Reward Type (optional):  ") == "reward type"


def test_normalize_header_preserves_unicode_and_collapses_whitespace() -> None:
    assert normalize_header("  Über   Skills   Needed  ") == "über skills needed"


def test_parse_field_reads_markdown_heading_value() -> None:
    body = """## Your Agent ID

Codex-2@codex
"""

    assert parse_field(body, ["Your Agent ID"]) == "Codex-2@codex"


def test_parse_field_reads_bold_inline_value() -> None:
    body = "**Reward:** 25"

    assert parse_field(body, ["Reward (WEA)", "Reward"]) == "25"


def test_parse_field_prefers_heading_match_before_inline_match() -> None:
    body = """## Reward

10

**Reward:** 99
"""

    assert parse_field(body, ["Reward"]) == "10"


def test_parse_field_returns_none_when_alias_is_missing() -> None:
    body = """## Reward

10
"""

    assert parse_field(body, ["Deadline"]) is None


def test_parse_field_matches_normalized_alias_names() -> None:
    body = """## Deadline

2026-05-01
"""

    assert parse_field(body, ["Deadline (optional)"]) == "2026-05-01"


def test_parse_section_reads_multiline_content() -> None:
    body = """## Acceptance Criteria

- [ ] MUST: tests pass
- [ ] MUST NOT: change unrelated files

## Notes

Ignored
"""

    assert parse_section(body, ["Acceptance Criteria"]) == (
        "- [ ] MUST: tests pass\n- [ ] MUST NOT: change unrelated files"
    )


def test_parse_section_normalizes_crlf_newlines() -> None:
    body = "## Verification Criteria\r\n\r\n- [ ] MUST: run checks\r\n- [ ] MUST NOT: regress\r\n"

    assert parse_section(body, ["Verification Criteria"]) == (
        "- [ ] MUST: run checks\n- [ ] MUST NOT: regress"
    )


def test_parse_section_returns_none_for_no_response_placeholder() -> None:
    body = """## Verification Criteria

_No Response_
"""

    assert parse_section(body, ["Verification Criteria"]) is None


def test_parse_section_returns_none_for_none_placeholder() -> None:
    body = """## Acceptance Criteria

None
"""

    assert parse_section(body, ["Acceptance Criteria"]) is None


def test_inspect_acceptance_criteria_rejects_empty_body() -> None:
    check = inspect_acceptance_criteria("")

    assert check.source == "missing"
    assert check.criteria == ()
    assert check.errors == ("Issue body is empty.",)


def test_inspect_acceptance_criteria_rejects_missing_section() -> None:
    check = inspect_acceptance_criteria("## Notes\n\nNo criteria here.\n")

    assert check.source == "missing"
    assert check.errors == ("No acceptance criteria section found.",)


def test_inspect_acceptance_criteria_requires_markdown_checkboxes() -> None:
    body = """## Verification Criteria

MUST: tests pass
MUST NOT: regress existing behavior
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert check.criteria == ()
    assert check.errors == ("Acceptance criteria must be written as markdown checkboxes.",)


def test_inspect_acceptance_criteria_parses_structured_machine_and_manual_items() -> None:
    body = """## Acceptance Criteria

- [X] must: `pytest tests/test_parsers.py -q` exits 0
- [ ] MUST NOT: modify src/wea_cli/parsers.py
- [ ] MUST: Manual: author confirms unicode output matches
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "structured"
    assert check.errors == ()
    assert [criterion.requirement for criterion in check.criteria] == ["must", "must_not", "must"]
    assert [criterion.text for criterion in check.machine_criteria] == [
        "`pytest tests/test_parsers.py -q` exits 0",
        "modify src/wea_cli/parsers.py",
    ]
    assert [criterion.text for criterion in check.human_criteria] == [
        "author confirms unicode output matches"
    ]
    assert check.has_machine_checks is True
    assert check.is_valid is True


def test_inspect_acceptance_criteria_rejects_mixed_structured_and_legacy_items() -> None:
    body = """## Verification Criteria

- [ ] MUST: tests pass
- [ ] Manual: author verifies output
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert "every checkbox" in "\n".join(check.errors)
    assert "MUST NOT" in "\n".join(check.errors)


def test_inspect_acceptance_criteria_requires_must_and_must_not_pairs() -> None:
    body = """## Verification Criteria

- [ ] MUST: tests pass
- [ ] MUST: keep unicode intact
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert check.errors == ("Structured acceptance criteria must include at least one `MUST NOT:` item.",)


def test_inspect_acceptance_criteria_rejects_manual_only_legacy_items() -> None:
    body = """## Verification Criteria

- [ ] Manual: reviewer confirms behavior
- [ ] Manual: reviewer confirms docs
"""

    check = inspect_acceptance_criteria(body)

    assert check.source == "malformed"
    assert check.has_machine_checks is False
    assert check.is_valid is False
    assert check.errors == (
        "Acceptance criteria must include at least one non-manual machine-checkable criterion.",
    )


def test_parse_task_metadata_reads_heading_style_fields() -> None:
    body = """## Your Agent ID

Codex-2@codex

## Reward Type

Winner Take All

## Reward (WEA)

40

## Deadline (optional)

2026-04-30

## Skills Needed

pytest, regex
"""

    assert parse_task_metadata(body) == {
        "agent_id": "Codex-2@codex",
        "reward_type": "Winner Take All",
        "reward": "40",
        "deadline": "2026-04-30",
        "skills_needed": "pytest, regex",
    }


def test_parse_task_metadata_returns_none_values_for_empty_body() -> None:
    assert parse_task_metadata("") == {
        "agent_id": None,
        "reward_type": None,
        "reward": None,
        "deadline": None,
        "skills_needed": None,
    }


def test_parse_task_metadata_ignores_malformed_unformatted_metadata() -> None:
    body = """Your Agent ID: Codex-2@codex
Reward: 15
Skills Needed: pytest
"""

    assert parse_task_metadata(body) == {
        "agent_id": None,
        "reward_type": None,
        "reward": None,
        "deadline": None,
        "skills_needed": None,
    }


def test_parse_task_metadata_reads_inline_style_and_leaves_missing_fields_none() -> None:
    body = """**Your Agent ID:** Codex-2@codex
**Reward:** 15
**Skills:** parsing, unicode, café
"""

    assert parse_task_metadata(body) == {
        "agent_id": "Codex-2@codex",
        "reward_type": None,
        "reward": "15",
        "deadline": None,
        "skills_needed": "parsing, unicode, café",
    }
