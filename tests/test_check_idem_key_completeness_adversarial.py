"""
Adversarial tests for scripts/check_idem_key_completeness.py

Each test targets a specific weakness, edge case, or confirms robustness of
the checker. 8 required scenarios + 1 bonus.

Tests confirm both FAIL paths (checker catches the bug) and PASS paths (checker
is silent — documenting real weaknesses or correct coercion behaviour).

Bug findings are documented in-situ and in the PR body.
"""

from __future__ import annotations

from scripts.check_idem_key_completeness import run_completeness_check


# ---------------------------------------------------------------------------
# Test 1 — Key prefix confusion: escrow key where payment key expected
# ---------------------------------------------------------------------------


def test_key_prefix_confusion_escrow_instead_of_payment() -> None:
    """
    A payment event exists but the idem key was registered with the 'escrow'
    prefix instead of 'payment'. The classifier puts 'escrow|123|alice@claude'
    in the escrow bucket — the payment event never finds a match.

    Expected:
      VIOLATION — payment event has no matching payment key.
      WARNING   — orphan escrow key has no matching escrow event.
    """
    events = [
        {
            "type": "payment",
            "issue": 123,
            "agent": "alice@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    # Wrong prefix — should be payment|123|alice@claude
    all_keys = {"escrow|123|alice@claude": "2026-01-01T00:00:00Z"}

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    v = violations[0]
    assert v["event_type"] == "payment"
    assert v["issue"] == "123"
    assert v["actor"] == "alice@claude"

    # Orphan escrow key: no escrow event for issue 123
    assert len(warnings) == 1
    w = warnings[0]
    assert w["idem_key"] == "escrow|123|alice@claude"
    assert w["namespace"] == "escrow"
    assert "123" in w["detail"]


# ---------------------------------------------------------------------------
# Test 2 — Integer vs string issue coercion (both paths)
# ---------------------------------------------------------------------------


def test_int_issue_vs_string_key_coercion_no_violation() -> None:
    """
    Payment event has 'issue': 99 (int). Idem key encodes it as '99' in
    the pipe-delimited string. Checker coerces both to str() before comparing.

    Also validates the hash-key path: hash dict with 'issue': 99 (int) vs
    event 'issue': '99' (string) — both normalise to '99'.

    Expected: no VIOLATION (type coercion handled correctly in both paths).
    """
    # Path A: string-format idem key, integer issue in event
    events_int = [
        {
            "type": "payment",
            "issue": 99,
            "agent": "alice@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    keys_string = {"payment|99|alice@claude": "2026-01-01T00:00:00Z"}

    violations_a, _ = run_completeness_check(keys_string, events_int, aliases={})
    assert violations_a == [], "Int issue in event must match string '99' in key"

    # Path B: hash-dict idem key with integer issue, string issue in event
    events_str = [
        {
            "type": "payment",
            "issue": "99",
            "agent": "alice@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    keys_hash_int = {
        "deadbeef": {
            "action": "payment",
            "issue": 99,  # integer stored in hash dict
            "agent": "alice@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    }

    violations_b, _ = run_completeness_check(keys_hash_int, events_str, aliases={})
    assert violations_b == [], "Int issue in hash dict must match string issue in event"


# ---------------------------------------------------------------------------
# Test 3 — Agent name case mismatch → VIOLATION (no alias applied)
# ---------------------------------------------------------------------------


def test_agent_case_mismatch_causes_violation() -> None:
    """
    Payment event agent 'Alice@claude' does not match idem key agent
    'alice@claude' because the checker performs case-sensitive string
    comparison and no alias covers the capitalisation difference.

    WEAKNESS: Without an alias mapping, a capitalisation divergence between
    the history event and the idem key produces a false VIOLATION.

    Expected: VIOLATION (case mismatch, no alias supplied).
    """
    events = [
        {
            "type": "payment",
            "issue": 10,
            "agent": "Alice@claude",  # capital A
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    # Idem key uses lowercase agent name
    all_keys = {"payment|10|alice@claude": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1, "Case mismatch without alias must generate VIOLATION"
    v = violations[0]
    assert v["event_type"] == "payment"
    assert v["actor"] == "Alice@claude"  # original case preserved in violation


def test_agent_case_mismatch_resolved_by_alias() -> None:
    """
    Same capitalisation divergence as above, but an alias maps 'Alice@claude'
    → 'alice@claude'. Both sides normalise to the canonical name → no violation.

    Expected: no VIOLATION (alias resolves the mismatch).
    """
    aliases = {"Alice@claude": "alice@claude"}
    events = [
        {
            "type": "payment",
            "issue": 10,
            "agent": "Alice@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    all_keys = {"payment|10|alice@claude": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases=aliases)

    assert violations == [], "Alias must normalise case and suppress the violation"


# ---------------------------------------------------------------------------
# Test 4 — Missing agent field → VIOLATION, not false PASS
# ---------------------------------------------------------------------------


def test_missing_agent_field_payment_causes_violation() -> None:
    """
    Payment event has neither 'agent' nor 'author' field. The checker resolves
    actor as '' (empty string). A legitimate key for a different agent exists
    but must NOT suppress the violation — the lookup is (issue, actor).

    Confirms graceful failure: the checker flags the anomaly rather than
    silently passing an unattributed payment.

    Expected: VIOLATION with empty actor.
    """
    events = [
        {
            "type": "payment",
            "issue": 10,
            "timestamp": "2026-01-01T00:00:00Z",
            # deliberately no 'agent' and no 'author' field
        }
    ]
    # A valid key for a different agent — must not suppress the violation
    all_keys = {"payment|10|agent0@system": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1, "Missing agent field must NOT produce a false PASS"
    v = violations[0]
    assert v["event_type"] == "payment"
    assert v["actor"] == ""


# ---------------------------------------------------------------------------
# Test 5 — escrow_create event with wrong key prefix not classified
# ---------------------------------------------------------------------------


def test_escrow_create_prefix_in_idem_key_causes_violation() -> None:
    """
    An 'escrow_create' history event was properly written, but the idem key
    uses the literal prefix 'escrow_create|10|agent0@system' instead of the
    canonical 'escrow|10|...'.

    BUG FINDING: classify_idem_keys only handles 'escrow' as a prefix; the
    'escrow_create' prefix falls through the elif chain unclassified. Therefore:
      - The escrow_create event cannot find a key in classified['escrow'] → VIOLATION.
      - The 'escrow_create|...' key is placed in no bucket → no WARNING emitted
        for it (it is invisible to orphan detection in Direction 2).

    Expected: VIOLATION for the escrow_create event; no WARNING for the
    unclassified key.
    """
    events = [
        {
            "type": "escrow_create",
            "issue": 10,
            "author": "agent0@system",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    # Wrong prefix — should be escrow|10|...
    all_keys = {"escrow_create|10|agent0@system": "2026-01-01T00:00:00Z"}

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    v = violations[0]
    assert v["event_type"] == "escrow"  # checker normalises escrow_create → escrow
    assert v["issue"] == "10"

    # Unclassified key generates no WARNING (invisible to Direction 2)
    assert not any(
        "escrow_create|10" in w.get("idem_key", "") for w in warnings
    ), "Unclassified 'escrow_create|' key must not appear in warnings"


# ---------------------------------------------------------------------------
# Test 6 — Orphan payment key generates WARNING, not VIOLATION
# ---------------------------------------------------------------------------


def test_orphan_payment_key_is_warning_not_violation() -> None:
    """
    An idem key 'payment|99|bob@claude' exists in idem_keys but there is no
    corresponding payment event in history. The key was written but the
    payment event was never recorded.

    Expected: WARNING (not VIOLATION); overall status is PASS.
    Orphan keys are anomalous but not integrity failures.
    """
    all_keys = {"payment|99|bob@claude": "2026-01-01T00:00:00Z"}
    events: list[dict] = []  # no payment event

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    assert violations == [], "Orphan key must not cause VIOLATION"
    assert len(warnings) == 1
    w = warnings[0]
    assert w["idem_key"] == "payment|99|bob@claude"
    assert w["namespace"] == "payment"
    assert "99" in w["detail"]
    assert "bob@claude" in w["detail"]


# ---------------------------------------------------------------------------
# Test 7 — escrow_batch with partial idem keys: silent PASS (bug)
# ---------------------------------------------------------------------------


def test_escrow_batch_partial_idem_keys_silent_pass() -> None:
    """
    An escrow_batch event covers issues [100, 101, 102]. Only 2 of the 3
    expected individual escrow keys are present; issue 102 has no key.

    BUG FINDING: 'escrow_batch' is NOT in TARGET_HISTORY_TYPES. Direction 1
    only iterates TARGET_HISTORY_TYPES, so it never checks whether each
    issue in a batch has a corresponding idem key. The missing key for
    issue 102 is completely invisible.

    Direction 2 also produces no warning: issue 102 has no key at all, so
    there is nothing to classify and nothing to check for orphan status.

    Result: violations=[], warnings=[] — completely silent. A real integrity
    gap: escrow operations performed via escrow_batch can lack idem keys
    without the checker noticing.

    Expected: violations == [] (checker silently passes — this is the bug).
    """
    events = [
        {
            "type": "escrow_batch",
            "author": "agent0@system",
            "issues": [100, 101, 102],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    # Only 2 of 3 expected keys present; issue 102 intentionally missing
    all_keys = {
        "escrow|100|agent0@system": "2026-01-01T00:00:00Z",
        "escrow|101|agent0@system": "2026-01-01T00:00:00Z",
        # escrow|102|... is absent
    }

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    # BUG: missing key for issue 102 goes undetected
    assert violations == [], (
        "escrow_batch issues are not in TARGET_HISTORY_TYPES — "
        "a missing idem key for a batch issue is silently ignored (bug)"
    )
    # No warning for issue 102 either: no key → nothing in Direction 2
    assert not any("102" in w.get("detail", "") for w in warnings)


# ---------------------------------------------------------------------------
# Test 8 — trajectory_mint malformed slot format → VIOLATION + WARNING
# ---------------------------------------------------------------------------


def test_trajectory_mint_malformed_slot_format_causes_violation() -> None:
    """
    A trajectory_mint event has slot=1 (integer). The idem key encodes it as
    'trajectory_mint|T1|slot1' — using 'slot1' as the slot segment instead of
    the canonical '1'.

    The classifier indexes the key under ("T1", "slot1"). The event lookup uses
    ("T1", "1") — no match — so a VIOLATION is raised.

    The malformed key also has no matching history event → WARNING.

    Expected: VIOLATION for the trajectory_mint event; WARNING for the orphan
    malformed key.
    """
    events = [
        {
            "type": "trajectory_mint",
            "trajectory": "T1",
            "slot": 1,
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]
    # Malformed: uses "slot1" instead of "1" as slot segment
    all_keys = {"trajectory_mint|T1|slot1": "2026-01-01T00:00:00Z"}

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    v = violations[0]
    assert v["event_type"] == "trajectory_mint"
    assert v["trajectory"] == "T1"
    assert v["slot"] == "1"  # event's slot, not the malformed key's segment
    assert "trajectory_mint|T1|1" in v["detail"]

    # Malformed key has no matching event → WARNING
    assert len(warnings) == 1
    w = warnings[0]
    assert w["idem_key"] == "trajectory_mint|T1|slot1"
    assert w["namespace"] == "trajectory_mint"
