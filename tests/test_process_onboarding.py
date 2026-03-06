"""Tests for process_onboarding — pure function tests (no GitHub CLI)."""

from scripts.process_onboarding import parse_issue_body, validate_agent_name


class TestParseIssueBody:
    def test_valid_form(self):
        body = "### Agent Name\n\nalice@cursor\n\n### Platform\n\nCursor\n\n### Operator\n\nAlice Smith"
        fields = parse_issue_body(body)
        assert fields["agent_name"] == "alice@cursor"
        assert fields["platform"] == "Cursor"
        assert fields["operator"] == "Alice Smith"

    def test_missing_fields(self):
        body = "### Agent Name\n\nalice@cursor"
        fields = parse_issue_body(body)
        assert fields["agent_name"] == "alice@cursor"
        assert "platform" not in fields

    def test_no_response_skipped(self):
        body = "### Agent Name\n\nalice@cursor\n\n### Platform\n\n_No response_"
        fields = parse_issue_body(body)
        assert "platform" not in fields

    def test_extra_whitespace(self):
        body = "### Agent Name\n\n  alice@cursor  \n\n### Platform\n\n  Cursor  "
        fields = parse_issue_body(body)
        assert fields["agent_name"] == "alice@cursor"
        assert fields["platform"] == "Cursor"

    def test_empty_body(self):
        assert parse_issue_body("") == {}

    def test_no_headers(self):
        assert parse_issue_body("Just some plain text without any headers.") == {}

    def test_empty_value_skipped(self):
        body = "### Agent Name\n\n\n\n### Platform\n\nCursor"
        fields = parse_issue_body(body)
        assert "agent_name" not in fields
        assert fields["platform"] == "Cursor"

    def test_label_normalized(self):
        body = "### Hello World\n\nSome creative submission"
        fields = parse_issue_body(body)
        assert "hello_world" in fields


class TestValidateAgentName:
    def test_valid(self):
        assert validate_agent_name("alice@cursor") is None

    def test_valid_with_numbers(self):
        assert validate_agent_name("bot123@github") is None

    def test_missing_at(self):
        err = validate_agent_name("alice")
        assert err is not None
        assert "name@platform" in err

    def test_empty(self):
        err = validate_agent_name("")
        assert err is not None
        assert "required" in err.lower()

    def test_spaces_in_name(self):
        err = validate_agent_name("alice doe@cursor")
        assert err is not None
        assert "spaces" in err.lower()

    def test_spaces_in_platform(self):
        err = validate_agent_name("alice@my cursor")
        assert err is not None
        assert "spaces" in err.lower()

    def test_multiple_at_signs(self):
        err = validate_agent_name("a@b@c")
        assert err is not None

    def test_at_only(self):
        err = validate_agent_name("@")
        assert err is not None
