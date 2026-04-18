import pytest
import sys
from pathlib import Path

# Add scripts directory to path to import the module
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.check_idem_key_format import is_known

def test_unicode_pipe():
    """
    1. Unicode pipe: 'register\u007cClaude-1 @claude' (Unicode U+007C instead of |)
    Fails because of space in 'Claude-1 @claude' (and | doesn't change anything in python string).
    """
    assert is_known("register\u007cClaude-1 @claude") is False

def test_case_mismatch():
    """
    2. Case mismatch: 'Register|Claude-1 @claude' (uppercase R)
    """
    assert is_known("Register|Claude-1 @claude") is False

def test_impossible_trajectory():
    """
    3. Impossible trajectory: 'trajectory_mint|T0|0' (T0 not in spec)
    GAP: validator currently passes T0
    """
    # GAP
    assert is_known("trajectory_mint|T0|0") is True

def test_very_long_agent():
    """
    4. Very long agent: 'register|' + 'A'*200 (length bomb)
    GAP: validator currently passes arbitrary length agent names
    """
    # GAP
    assert is_known("register|" + "A"*200) is True

def test_slot_zero():
    """
    5. Slot zero: 'trajectory_mint|T1|0' (slot 0 not valid)
    GAP: validator currently passes slot 0
    """
    # GAP
    assert is_known("trajectory_mint|T1|0") is True

def test_empty_trajectory():
    """
    6. Empty trajectory: 'trajectory_mint||5' (empty T part)
    """
    assert is_known("trajectory_mint||5") is False

def test_nested_pipe():
    """
    7. Nested pipe: 'register|foo|bar|baz' (extra segments)
    """
    assert is_known("register|foo|bar|baz") is False

def test_fake_sha256():
    """
    8. Fake SHA256 (non-hex): '00000000000000000000000000000000000000000000000000000000000000XY'
    """
    assert is_known("00000000000000000000000000000000000000000000000000000000000000XY") is False

def test_wrong_suffix_case():
    """
    9. Wrong suffix case: 'escrow_create_123_t1_GAUNTLET' (uppercase GAUNTLET)
    """
    assert is_known("escrow_create_123_t1_GAUNTLET") is False

def test_payment_with_extra():
    """
    10. Payment with extra: 'payment|1|Claude-1 @claude|winner|extra|more'
    """
    assert is_known("payment|1|Claude-1 @claude|winner|extra|more") is False
