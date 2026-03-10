"""Tests for pipeline.py — comment parsing and transition validation."""

from pathlib import Path

from scripts.pipeline import (
    check_transition,
    parse_negativa_comment,
    parse_spec_comment,
    parse_verify_comment,
    validate_comment,
    _load_config,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _config():
    return _load_config(_REPO_ROOT)


class TestParseNegativa:
    def test_valid_proceed(self):
        body = """### Via Negativa Evaluation by Cursor-1@cursor

1. Not duplicate: PASS — checked
2. Architecture compatible: PASS — ok
3. Positive ROI: PASS — yes
4. No fragility: PASS — none
5. Gaming-resistant: PASS — spec has NOT-accepted
6. Requires code: PASS — config insufficient

Verdict: PROCEED (item #1 — all pass)"""
        result = parse_negativa_comment(body, _config())
        assert result is not None
        assert result["verdict"] == "PROCEED"

    def test_valid_kill(self):
        body = """### Via Negativa Evaluation by X@y

1. Not duplicate: PASS — ok
2. Architecture compatible: FAIL — conflicts
3. Positive ROI: PASS — ok
4. No fragility: PASS — ok
5. Gaming-resistant: PASS — ok
6. Requires code: PASS — ok

Verdict: KILL (item #2 — architecture conflict)"""
        result = parse_negativa_comment(body, _config())
        assert result is not None
        assert result["verdict"] == "KILL"

    def test_invalid_no_prefix(self):
        assert parse_negativa_comment("PROCEED trust me", _config()) is None

    def test_invalid_wrong_line_count(self):
        body = """### Via Negativa Evaluation by X

1. Not duplicate: PASS — ok
Verdict: PROCEED (item #1 — ok)"""
        assert parse_negativa_comment(body, _config()) is None


class TestParseSpec:
    def test_valid_approved(self):
        body = """### Spec Review by RedTeam@cursor

Red Team result: NO GAMING FOUND
- none

Approval: APPROVED"""
        result = parse_spec_comment(body, _config())
        assert result is not None
        assert result["approval"] == "APPROVED"
        assert result["red_team"] == "NO GAMING FOUND"

    def test_valid_rejected(self):
        body = """### Spec Review by X

Red Team result: GAMING FOUND
- degenerate solution X

Approval: REJECTED"""
        result = parse_spec_comment(body, _config())
        assert result is not None
        assert result["approval"] == "REJECTED"


class TestParseVerify:
    def test_valid_approved(self):
        body = """### Verification Review by Y

L2 adversarial checklist:
- Gaming: NONE — checked
- Out-of-scope: NONE — ok
- Fragility: NONE — ok
- Removable code: NONE — ok

Blocking comments: NO
- none

Verdict: APPROVED"""
        result = parse_verify_comment(body, _config())
        assert result is not None
        assert result["verdict"] == "APPROVED"


class TestValidateComment:
    def test_negativa_valid(self):
        body = """### Via Negativa Evaluation by X

1. Not duplicate: PASS — ok
2. Architecture compatible: PASS — ok
3. Positive ROI: PASS — ok
4. No fragility: PASS — ok
5. Gaming-resistant: PASS — ok
6. Requires code: PASS — ok

Verdict: PROCEED (item #1 — ok)"""
        ok, _ = validate_comment("negativa", body, _config())
        assert ok

    def test_negativa_invalid(self):
        ok, msg = validate_comment("negativa", "garbage", _config())
        assert not ok
        assert "PARSE_SPEC" in msg


class TestCheckTransition:
    def test_impl_to_verify_allowed(self):
        ok, _ = check_transition("stage:impl", "stage:verify", _config())
        assert ok

    def test_impl_to_delivery_rejected(self):
        ok, msg = check_transition("stage:impl", "stage:delivery", _config())
        assert not ok
        assert "stage:delivery" in msg

    def test_verify_to_delivery_allowed(self):
        ok, _ = check_transition("stage:verify", "stage:delivery", _config())
        assert ok
