import pytest
from scripts.check_idem_key_format import run_check

def test_redteam_unicode_normalization():
    # 1. Unicode normalization: pipe replaced with Unicode \u007C
    # \u007C is the exact same character as |, so the parser sees it as |
    # Expected PASS (GAP - if someone injects \u007C in JSON, it bypasses filtering if filtering looks for literal '|')
    res = run_check({"keys": {"register\u007Cclaude-1@claude": {}}})
    assert res["passed"] is True, "GAP: \u007C is interpreted exactly as | and passes"

def test_redteam_case_sensitivity():
    # 2. Case sensitivity: 'Register' vs 'register'
    # Expected FAIL for Register
    res_fail = run_check({"keys": {"Register|Claude-1@claude": {}}})
    assert res_fail["passed"] is False
    
    # Expected PASS for register
    res_pass = run_check({"keys": {"register|Claude-1@claude": {}}})
    assert res_pass["passed"] is True

def test_redteam_semantically_impossible_trajectory():
    # 3. Syntactically valid but semantically impossible: T0 doesn't exist
    # Expected PASS (GAP)
    res = run_check({"keys": {"trajectory_mint|T0|0": {}}})
    assert res["passed"] is True, "GAP: T0 is accepted even though semantically impossible"

def test_redteam_very_long_agent_name():
    # 4. Very long agent name
    # Expected PASS (GAP)
    res = run_check({"keys": {"register|" + "A" * 1000: {}}})
    assert res["passed"] is True, "GAP: No length limit on agent name"

def test_redteam_slot_value_overflow():
    # 5. Slot value overflow
    # Expected PASS (GAP)
    res = run_check({"keys": {"trajectory_mint|T1|999999": {}}})
    assert res["passed"] is True, "GAP: No limit on slot number size"

def test_redteam_empty_trajectory():
    # 6. Empty trajectory
    # Expected FAIL
    res = run_check({"keys": {"trajectory_mint||5": {}}})
    assert res["passed"] is False

def test_redteam_nested_pipe():
    # 7. Nested pipe
    # Expected FAIL
    res = run_check({"keys": {"register|foo|bar|baz": {}}})
    assert res["passed"] is False

def test_redteam_sha256_not_hex():
    # 8. SHA256-length but not hex
    # Expected FAIL
    res = run_check({"keys": {"0" * 62 + "XY": {}}})
    assert res["passed"] is False

def test_redteam_escrow_create_wrong_suffix():
    # 9. escrow_create with wrong suffix (uppercase)
    # Expected FAIL
    res = run_check({"keys": {"escrow_create_123_t1_GAUNTLET": {}}})
    assert res["passed"] is False

def test_redteam_payment_extra_segment():
    # 10. Payment with extra segment
    # Expected FAIL
    res = run_check({"keys": {"payment|1|Claude-1@claude|winner|extra|more": {}}})
    assert res["passed"] is False

def test_redteam_space_in_agent_name():
    # Testing the exact prompt typo 'Claude-1 @claude'
    # Expected FAIL because AGENT regex does not allow spaces
    res = run_check({"keys": {"register|Claude-1 @claude": {}}})
    assert res["passed"] is False
