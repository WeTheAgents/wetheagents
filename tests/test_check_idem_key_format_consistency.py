"""Tests for scripts/check_idem_key_format_consistency.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_idem_key_format_consistency import (
    _event_type,
    check_format_consistency,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_history(tmp_path: Path, events: list[dict]) -> Path:
    """Write events as a single JSONL file under a history/ directory."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    (history_dir / "2099-01-01.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Unit: _event_type field resolution
# ---------------------------------------------------------------------------


def test_event_type_prefers_event_field():
    # 'event' field takes precedence over 'type' (mechanic subtype)
    assert _event_type({"event": "escrow_create", "type": "standard"}) == "escrow_create"


def test_event_type_falls_back_to_op():
    assert _event_type({"op": "escrow_return"}) == "escrow_return"


def test_event_type_falls_back_to_type():
    assert _event_type({"type": "payment"}) == "payment"


def test_event_type_empty_when_no_fields():
    assert _event_type({}) == ""


# ---------------------------------------------------------------------------
# Unit: check_format_consistency — correct prefixes (PASS)
# ---------------------------------------------------------------------------


def _events_pass(events):
    """Assert check returns PASS with no violations."""
    status, violations, warnings, summary = check_format_consistency(events)
    assert status == "PASS"
    assert violations == []
    return warnings


def test_accept_valid_prefix():
    _events_pass([{"type": "accept", "idem_key": "accept|272|Claude-1@claude"}])


def test_escrow_create_underscore_prefix():
    _events_pass([{"type": "escrow_create", "idem_key": "escrow_create|123"}])


def test_escrow_create_underscore_variant():
    _events_pass([{"type": "escrow_create", "idem_key": "escrow_create_496_t1s13_gauntlet"}])


def test_escrow_create_hyphen_prefix():
    _events_pass([{"type": "escrow_create", "idem_key": "escrow-create-gauntlet-cycle20-741"}])


def test_escrow_create_hyphen_short():
    _events_pass([{"type": "escrow_create", "idem_key": "escrow-create-587"}])


def test_escrow_return_hyphen_prefix():
    _events_pass([{"type": "escrow_return", "idem_key": "escrow-return-cycle15-674"}])


def test_escrow_return_underscore_prefix():
    _events_pass([{"type": "escrow_return", "idem_key": "escrow_return|610"}])


def test_escrow_return_underscore_long():
    _events_pass([{"type": "escrow_return", "idem_key": "escrow_return_486_t3s12_gauntlet"}])


def test_trajectory_mint_prefix():
    _events_pass([{"type": "trajectory_mint", "idem_key": "trajectory_mint|T1|23"}])


def test_payment_standard_prefix():
    _events_pass([{"type": "payment", "idem_key": "payment|380|Claude-1@claude"}])


def test_payment_legacy_accept_prefix():
    # Legacy payment events used accept| idem_key prefix.
    _events_pass([{"type": "payment", "idem_key": "accept|5|AntigravityWea@Google|slot1"}])


def test_payment_pay_prefix():
    _events_pass([{"type": "payment", "idem_key": "pay-issue-42"}])


def test_registration_confirmed_any_format():
    # registration_confirmed has no prefix constraint.
    _events_pass([{"type": "registration_confirmed", "idem_key": "anything-goes-here"}])


def test_events_without_idem_key_skipped():
    # Events without idem_key are not checked; no violations or warnings.
    status, violations, warnings, _ = check_format_consistency(
        [{"type": "payment"}, {"type": "accept"}]
    )
    assert status == "PASS"
    assert violations == []
    assert warnings == []


# ---------------------------------------------------------------------------
# Unit: check_format_consistency — wrong prefix (VIOLATION)
# ---------------------------------------------------------------------------


def test_accept_wrong_prefix_is_violation():
    status, violations, warnings, _ = check_format_consistency(
        [{"type": "accept", "idem_key": "payment|99|agent@p"}]
    )
    assert status == "FAIL"
    assert len(violations) == 1
    assert violations[0]["event_type"] == "accept"
    assert violations[0]["idem_key"] == "payment|99|agent@p"


def test_trajectory_mint_accept_prefix_is_violation():
    status, violations, _, _ = check_format_consistency(
        [{"type": "trajectory_mint", "idem_key": "accept|T1|10"}]
    )
    assert status == "FAIL"
    assert len(violations) == 1
    assert violations[0]["event_type"] == "trajectory_mint"


def test_payment_trajectory_prefix_is_violation():
    status, violations, _, _ = check_format_consistency(
        [{"type": "payment", "idem_key": "trajectory_mint|380"}]
    )
    assert status == "FAIL"
    assert len(violations) == 1


def test_escrow_create_wrong_prefix_is_violation():
    status, violations, _, _ = check_format_consistency(
        [{"type": "escrow_create", "idem_key": "escrow-return-cycle1-99"}]
    )
    assert status == "FAIL"
    assert len(violations) == 1
    assert violations[0]["event_type"] == "escrow_create"


def test_escrow_return_wrong_prefix_is_violation():
    status, violations, _, _ = check_format_consistency(
        [{"type": "escrow_return", "idem_key": "accept|99|agent@p"}]
    )
    assert status == "FAIL"
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# Unit: check_format_consistency — unknown event type (WARNING)
# ---------------------------------------------------------------------------


def test_unknown_event_type_emits_warning():
    status, violations, warnings, _ = check_format_consistency(
        [{"type": "escrow", "idem_key": "escrow|397"}]
    )
    assert status == "PASS"
    assert violations == []
    assert len(warnings) == 1
    assert warnings[0]["event_type"] == "escrow"
    assert "no prefix schema" in warnings[0]["note"]


def test_no_type_field_emits_warning():
    status, violations, warnings, _ = check_format_consistency(
        [{"idem_key": "something|123"}]
    )
    assert status == "PASS"
    assert violations == []
    assert len(warnings) == 1
    assert warnings[0]["event_type"] == ""


# ---------------------------------------------------------------------------
# Unit: check_format_consistency — mixed scenario
# ---------------------------------------------------------------------------


def test_mixed_correct_violation_unknown():
    events = [
        # PASS
        {"type": "accept", "idem_key": "accept|1|agent@p"},
        # VIOLATION: trajectory_mint with wrong prefix
        {"type": "trajectory_mint", "idem_key": "accept|T2|5"},
        # WARNING: unknown type
        {"type": "escrow", "idem_key": "escrow|260|agent0@system"},
        # No idem_key — skipped
        {"type": "payment"},
    ]
    status, violations, warnings, summary = check_format_consistency(events)
    assert status == "FAIL"
    assert len(violations) == 1
    assert violations[0]["event_type"] == "trajectory_mint"
    assert len(warnings) == 1
    assert warnings[0]["event_type"] == "escrow"
    assert "3 event(s)" in summary
    assert "1 VIOLATION" in summary
    assert "1 WARNING" in summary


# ---------------------------------------------------------------------------
# Unit: 'event' and 'op' field resolution in check
# ---------------------------------------------------------------------------


def test_event_field_used_for_type_resolution():
    # 'event' overrides 'type=standard'
    events = [{"event": "escrow_create", "type": "standard", "idem_key": "escrow-create-587"}]
    status, violations, _, _ = check_format_consistency(events)
    assert status == "PASS"
    assert violations == []


def test_op_field_used_for_escrow_return():
    events = [{"op": "escrow_return", "idem_key": "escrow_return|610"}]
    status, violations, _, _ = check_format_consistency(events)
    assert status == "PASS"
    assert violations == []


def test_op_field_used_for_escrow_create():
    events = [{"op": "escrow_create", "idem_key": "escrow_create_618_t1_gauntlet"}]
    status, violations, _, _ = check_format_consistency(events)
    assert status == "PASS"
    assert violations == []


# ---------------------------------------------------------------------------
# Integration: run() on a temp repo
# ---------------------------------------------------------------------------


def test_run_empty_history_passes(tmp_path):
    (tmp_path / "ledger" / "history").mkdir(parents=True)
    result, passed = run(tmp_path)
    assert passed
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_run_missing_history_dir_fails(tmp_path):
    result, passed = run(tmp_path)
    assert not passed
    assert result["status"] == "FAIL"
    assert "not found" in result["summary"]


def test_run_all_valid_events_passes(tmp_path):
    events = [
        {"type": "accept", "idem_key": "accept|10|agent@p"},
        {"type": "escrow_create", "idem_key": "escrow_create|10"},
        {"type": "escrow_return", "idem_key": "escrow-return-cycle1-10"},
        {"type": "trajectory_mint", "idem_key": "trajectory_mint|T1|5"},
        {"type": "payment", "idem_key": "payment|10|agent@p"},
        {"type": "registration_confirmed", "idem_key": "reg-123"},
    ]
    root = _write_history(tmp_path, events)
    result, passed = run(root)
    assert passed
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_run_violation_causes_fail(tmp_path):
    events = [
        {"type": "trajectory_mint", "idem_key": "accept|T1|10"},
    ]
    root = _write_history(tmp_path, events)
    result, passed = run(root)
    assert not passed
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1


def test_run_unknown_type_warns_but_passes(tmp_path):
    events = [
        {"type": "escrow", "idem_key": "escrow|397"},
    ]
    root = _write_history(tmp_path, events)
    result, passed = run(root)
    assert passed
    assert result["status"] == "PASS"
    assert len(result["warnings"]) == 1


# ---------------------------------------------------------------------------
# Integration: CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_exits_0_on_valid_repo(tmp_path):
    events = [{"type": "accept", "idem_key": "accept|1|a@p"}]
    root = _write_history(tmp_path, events)
    result = subprocess.run(
        [sys.executable, "scripts/check_idem_key_format_consistency.py", "--root", str(root)],
        capture_output=True,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["status"] == "PASS"


def test_cli_exits_1_on_violation(tmp_path):
    events = [{"type": "trajectory_mint", "idem_key": "accept|T1|10"}]
    root = _write_history(tmp_path, events)
    result = subprocess.run(
        [sys.executable, "scripts/check_idem_key_format_consistency.py", "--root", str(root)],
        capture_output=True,
    )
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["status"] == "FAIL"
