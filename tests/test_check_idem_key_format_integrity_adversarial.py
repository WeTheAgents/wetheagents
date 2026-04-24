"""Adversarial tests for scripts/check_idem_key_format_integrity.py.

Targeted at bypass vectors in classify_key — cases where a structurally
invalid or semantically suspicious key might be silently accepted.

Genuine bypasses (script classifies malformed key as valid):
  BYPASS-1  Unicode homoglyph in agent segment
  BYPASS-2  Whitespace embedded in agent segment

Correctly-rejected cases (no bypass, verification of spec boundary):
  REJECT-1  Zero issue integer
  REJECT-2  Negative issue via hyphen
  REJECT-3  Extra pipe segment in register key
  REJECT-4  Truncated gauntlet key
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from scripts.check_idem_key_format_integrity import classify_key


# ---------------------------------------------------------------------------
# BYPASS-1 — Unicode homoglyph in agent segment
# ---------------------------------------------------------------------------

def test_unicode_homoglyph_in_agent_accept():
    """
    BYPASS VECTOR: The leading 'а' in аgent@platform is Cyrillic U+0430,
    visually indistinguishable from Latin 'a'. _has_at only checks for '@'
    presence in the string; @ is ASCII and present, so the check passes.
    No ASCII-only validation exists anywhere in the classifier.

    Impact [MEDIUM]: An agent with a homoglyph ID could register a duplicate
    idem_key that the deduplication system treats as distinct from the
    legitimate key, enabling double-spend on the same operation.
    """
    # 'а' below is Cyrillic U+0430, not Latin 'a' (U+0061)
    homoglyph_key = "accept|42|аgent@platform"
    assert homoglyph_key[10] == "а"  # confirm the homoglyph is present (index 10: after "accept|42|")

    kind, detail = classify_key(homoglyph_key)

    # GENUINE BYPASS: the script classifies this as valid — no non-ASCII guard
    assert kind == "valid", (
        "Expected bypass: homoglyph agent should be valid per current impl; "
        "if this fails the bypass has been fixed"
    )
    assert detail == "accept"


def test_unicode_homoglyph_in_agent_gauntlet():
    """
    Same bypass applies to gauntlet keys — the agent segment uses the same
    _has_at check, and the regex (.+) matches any character including Unicode.
    """
    # 'С' below is Cyrillic U+0421 (looks like Latin 'C')
    homoglyph_key = "gauntlet-T2-S34-Сlaude-6@claude"
    kind, detail = classify_key(homoglyph_key)

    # GENUINE BYPASS: regex (.+) matches Cyrillic; @ is present
    assert kind == "valid"
    assert detail == "gauntlet"


# ---------------------------------------------------------------------------
# BYPASS-2 — Whitespace embedded in agent segment
# ---------------------------------------------------------------------------

def test_whitespace_in_agent_segment_gauntlet():
    """
    BYPASS VECTOR: Same whitespace bypass applies to gauntlet keys.
    The regex (.+) in _GAUNTLET_RE captures any non-empty string including
    strings with spaces, and _has_at then checks for '@' presence.
    'claude 6@claude' passes both: regex matches, @ present.
    """
    key_with_space = "gauntlet-T2-S34-claude 6@claude"
    kind, detail = classify_key(key_with_space)

    # GENUINE BYPASS: regex (.+) matches 'claude 6@claude', _has_at returns True
    assert kind == "valid"
    assert detail == "gauntlet"


def test_whitespace_in_agent_segment_accept():
    """
    BYPASS VECTOR: 'agent @platform' contains a space before '@'. _has_at
    returns True because '@' is present anywhere in the string. There is no
    whitespace-stripping or whitespace-rejection guard in classify_key.

    A key with embedded whitespace would never be emitted by normal wea CLI
    operations, but could appear via direct ledger injection or API misuse.
    The idempotency system would treat it as a distinct key from 'agent@platform',
    potentially allowing the same operation to execute twice.

    Impact [MEDIUM]: idempotency bypass — injected whitespace key hashes to
    a different string than the canonical key, defeating deduplication.
    """
    key_with_space = "accept|42|agent @platform"
    kind, detail = classify_key(key_with_space)

    # GENUINE BYPASS: '@' present → _has_at passes; no whitespace check
    assert kind == "valid", (
        "Expected bypass: whitespace in agent should be valid per current impl; "
        "if this fails the bypass has been fixed"
    )
    assert detail == "accept"


def test_whitespace_in_agent_segment_register():
    """
    The register pattern checks _has_at(rest) on the tail after 'register|'.
    Embedded whitespace in the agent name is not rejected.
    """
    key_with_space = "register|claude 6@claude"
    kind, detail = classify_key(key_with_space)

    # GENUINE BYPASS: '@' in 'claude 6@claude' → True, no whitespace guard
    assert kind == "valid"
    assert detail == "register"


# ---------------------------------------------------------------------------
# REJECT-1 — Zero issue integer (boundary check)
# ---------------------------------------------------------------------------

def test_zero_issue_accept():
    """
    Spec: issue must be a positive integer. Zero is not positive.
    _is_positive_int calls int(s) > 0, which correctly returns False for '0'.
    A naive [0-9]+ regex alone would pass '0'; the > 0 guard is essential.
    """
    kind, detail = classify_key("accept|0|agent@platform")

    assert kind == "malformed"
    assert "positive integer" in detail
    assert "'0'" in detail


def test_zero_issue_escrow_create():
    """Same boundary applies to escrow_create."""
    kind, detail = classify_key("escrow_create|0")

    assert kind == "malformed"
    assert "positive integer" in detail


# ---------------------------------------------------------------------------
# REJECT-2 — Negative issue via hyphen
# ---------------------------------------------------------------------------

def test_negative_issue_escrow_create():
    """
    '-1' contains a hyphen. A naive int() cast would produce -1 < 0, but
    _is_positive_int uses re.fullmatch(r"[0-9]+", s) first — hyphens are
    not in [0-9], so fullmatch returns None and the function short-circuits
    to False before the int() comparison is even reached.
    """
    kind, detail = classify_key("escrow_create|-1")

    assert kind == "malformed"
    assert "positive integer" in detail


def test_negative_issue_accept():
    """Same rejection for accept pattern."""
    kind, detail = classify_key("accept|-5|agent@platform")

    assert kind == "malformed"
    assert "positive integer" in detail


# ---------------------------------------------------------------------------
# REJECT-3 — Extra pipe segments in register key
# ---------------------------------------------------------------------------

def test_extra_pipe_in_register():
    """
    The register validator explicitly checks '|' in rest and rejects.
    A naive implementation checking only that rest is non-empty and has '@'
    would classify this as valid, treating 'extra' as part of the agent name.
    """
    kind, detail = classify_key("register|agent@platform|extra")

    assert kind == "malformed"
    assert "extra" in detail.lower() or "|" in detail


def test_multiple_extra_pipes_in_register():
    """More than one extra segment — still caught by the same '|' in rest check."""
    kind, detail = classify_key("register|agent@platform|extra1|extra2")

    assert kind == "malformed"


# ---------------------------------------------------------------------------
# REJECT-4 — Truncated gauntlet key
# ---------------------------------------------------------------------------

def test_truncated_gauntlet_missing_slot_number():
    """
    'gauntlet-T1-S' triggers the gauntlet branch (starts with 'gauntlet-T',
    first char after T is digit '1'). The regex _GAUNTLET_RE requires
    ([0-9]+) after '-S', but the key ends at 'S' — no digits follow.
    The regex match returns None → classified as malformed.
    """
    kind, detail = classify_key("gauntlet-T1-S")

    assert kind == "malformed"
    assert "gauntlet" in detail.lower()


def test_truncated_gauntlet_missing_agent():
    """
    'gauntlet-T2-S34' has trajectory and slot but no '-{agent}' suffix.
    The regex requires (.+) after the last '-', which needs at least one char.
    """
    kind, detail = classify_key("gauntlet-T2-S34")

    assert kind == "malformed"
    assert "gauntlet" in detail.lower()


def test_truncated_gauntlet_agent_missing_at():
    """
    'gauntlet-T1-S1-agentnoat' — regex matches but agent has no '@'.
    _has_at check on the captured agent segment returns False.
    """
    kind, detail = classify_key("gauntlet-T1-S1-agentnoat")

    assert kind == "malformed"
    assert "@" in detail or "agent" in detail.lower()
