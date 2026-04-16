"""Adversarial tests for scripts/check_escrow_task_reward_match.py.

Probes the checker for false-PASS inputs — cases where the checker returns
PASS despite a real escrow/reward mismatch.

Each test is labeled:
  CONFIRMED GAP  — checker returns PASS when it should FAIL
  EXPECTED FAIL  — checker correctly returns FAIL (verifying correct behavior)
  EXPECTED PASS  — checker correctly returns PASS (documenting design choices)
"""
from __future__ import annotations

from pathlib import Path

from scripts import check_escrow_task_reward_match as checker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(
    active: dict | None = None,
    task_entries: dict | None = None,
    events: list | None = None,
) -> dict:
    escrows = {"version": 1, "active": active or {}}
    tasks = task_entries or {}
    return checker.run_check(
        Path("/fake/root"),
        escrows=escrows,
        tasks=tasks,
        events=events or [],
    )


# ===========================================================================
# CONFIRMED GAP — checker returns PASS when it should FAIL
# ===========================================================================

def test_gap_reward_wea_as_string_causes_false_pass() -> None:
    """CONFIRMED GAP: reward_wea stored as string "35" causes silent skip.

    _get_task_reward checks isinstance(val, int). A string like "35" fails
    that check, so the task is skipped as "no valid reward field".
    Result: PASS even though escrow amount (99) != true reward (35).

    Attack surface: 'task_index has reward_wea as string not int — type
    coercion causes false PASS'.
    """
    result = _run(
        active={"100": {"amount": 99, "type": "pod"}},
        task_entries={"100": {"reward_wea": "35"}},  # string, not int
    )
    # GAP: skipped instead of flagged — real mismatch (99 vs 35) undetected
    assert result["status"] == "PASS"
    assert result["violations"] == []
    skipped_issues = {s["issue"] for s in result["skipped"]}
    assert "100" in skipped_issues, "Task with string reward should appear in skipped"


def test_gap_reward_wea_as_float_causes_false_pass() -> None:
    """CONFIRMED GAP: reward_wea stored as float 34.0 causes silent skip.

    isinstance(34.0, int) is False in CPython (float is not a subtype of int),
    so float rewards fail _get_task_reward and the task is skipped. Checker
    returns PASS despite escrow=99 being wildly wrong for reward=34.
    """
    result = _run(
        active={"200": {"amount": 99, "type": "pod"}},
        task_entries={"200": {"reward_wea": 34.0}},  # float, not int
    )
    # GAP: 99 != 34, but checker skips the task → false PASS
    assert result["status"] == "PASS"
    assert result["violations"] == []
    skipped_issues = {s["issue"] for s in result["skipped"]}
    assert "200" in skipped_issues, "Task with float reward should appear in skipped"


def test_gap_history_issue_as_float_bypasses_lookup() -> None:
    """CONFIRMED GAP: history escrow_create with issue stored as float skips check.

    The checker does str(event["issue"]).strip(), so float 100.0 becomes
    "100.0". tasks.get("100.0") finds nothing (key is "100") → skipped →
    PASS, even though the escrow_create had amount=99 for issue 100 with
    reward_wea=35.

    Attack surface: 'History escrow_create event with amount != task reward —
    missed by active-escrow-only check'.
    """
    events = [{"type": "escrow_create", "issue": 100.0, "amount": 99}]
    result = _run(
        task_entries={"100": {"reward_wea": 35}},
        events=events,
    )
    # GAP: key "100.0" != "100" → task not found → mismatch (99 vs 35) undetected
    assert result["status"] == "PASS"
    assert result["violations"] == []
    skipped_issues = {s["issue"] for s in result["skipped"]}
    assert "100.0" in skipped_issues, "Float issue should be recorded as skipped under '100.0'"


# ===========================================================================
# EXPECTED FAIL — checker correctly detects violations
# ===========================================================================

def test_expected_fail_off_by_one_active_escrow() -> None:
    """EXPECTED FAIL: active escrow amount off-by-one is correctly caught.

    Attack surface: 'Active escrow with amount off-by-one (e.g. 34 vs 35)'.
    Checker correctly flags this as a violation.
    """
    result = _run(
        active={"535": {"amount": 34, "type": "pod"}},
        task_entries={"535": {"reward_wea": 35}},
    )
    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["issue"] == "535"
    assert v["escrow_amount"] == 34
    assert v["expected_reward"] == 35


def test_expected_fail_history_partial_initial_escrow_for_progressive() -> None:
    """EXPECTED FAIL: history escrow_create with partial amount is caught.

    Attack surface: 'Progressive PoD task where escrow covers only one slot'.
    At creation time the FULL reward must be escrowed — even for progressive
    tasks. The history check enforces an exact match regardless of type.
    """
    events = [{"type": "escrow_create", "issue": 308, "amount": 3}]
    result = _run(
        task_entries={"308": {"reward_wea": 10, "reward_type": "progressive"}},
        events=events,
    )
    assert result["status"] == "FAIL"
    v = result["violations"][0]
    assert v["source"] == "history"
    assert v["issue"] == "308"
    assert v["escrow_amount"] == 3
    assert v["expected_reward"] == 10


def test_expected_fail_gauntlet_task_wrong_slot_in_escrow() -> None:
    """EXPECTED FAIL: gauntlet escrow with wrong slot amount is caught.

    Attack surface: 'Gauntlet task with correct 19+slot formula but wrong
    slot number'. Escrow amount (34 = 19+15) is wrong; task_index has the
    correct reward (35 = 19+16). Checker correctly flags the violation.
    """
    result = _run(
        active={"535": {"amount": 34, "type": "pod"}},   # 19+15 wrong slot
        task_entries={"535": {"reward_wea": 35}},          # 19+16 correct
    )
    assert result["status"] == "FAIL"
    v = result["violations"][0]
    assert v["escrow_amount"] == 34
    assert v["expected_reward"] == 35


# ===========================================================================
# EXPECTED PASS — checker behaves as designed (documenting design choices)
# ===========================================================================

def test_expected_pass_progressive_active_escrow_below_reward() -> None:
    """EXPECTED PASS: progressive active escrow with partial remaining budget.

    Attack surface: 'Progressive PoD task where escrow covers only one slot'.
    An active progressive escrow may legitimately be below full reward after
    partial payouts. Checker correctly allows this by design.
    """
    result = _run(
        active={"400": {"amount": 3, "type": "progressive"}},
        task_entries={"400": {"reward_wea": 10}},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_expected_pass_missing_task_in_index_skipped() -> None:
    """EXPECTED PASS: active escrow for task not in task_index is skipped.

    Attack surface: 'Escrow exists but task is not in task_index at all'.
    Current design: skip gracefully (not a violation). This means escrows
    for unregistered tasks cannot be validated — a known design tradeoff.
    """
    result = _run(
        active={"9999": {"amount": 50, "type": "pod"}},
        task_entries={},
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []
    skipped_issues = {s["issue"] for s in result["skipped"]}
    assert "9999" in skipped_issues


def test_expected_pass_progressive_zero_amount_not_flagged() -> None:
    """EXPECTED PASS (potential design gap): zero-amount progressive escrow passes.

    A fully-depleted-but-still-active progressive escrow (all slots paid,
    escrow not yet closed) passes the ceiling check: 0 > task_reward → False.
    The checker has no floor check for progressive types, so depleted-but-open
    escrows are invisible to it. Whether this needs a floor is a design question.
    """
    result = _run(
        active={"401": {"amount": 0, "type": "progressive"}},
        task_entries={"401": {"reward_wea": 10}},
    )
    # Not flagged — checker only enforces ceiling for progressive, not floor
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_expected_pass_history_payment_events_ignored() -> None:
    """EXPECTED PASS: non-escrow_create history events are not checked.

    Attack surface: 'History escrow_create event with amount != task reward'.
    Specifically verifying that payment and escrow_return events with arbitrary
    amounts do NOT trigger violations — only escrow_create is inspected.
    """
    events = [
        {"type": "payment", "issue": 102, "amount": 9999},
        {"type": "escrow_return", "issue": 102, "amount": 9999},
    ]
    result = _run(
        task_entries={"102": {"reward_wea": 25}},
        events=events,
    )
    assert result["status"] == "PASS"
    assert result["violations"] == []


def test_gap_reward_wea_bool_causes_false_pass() -> None:
    """CONFIRMED GAP: reward_wea = True (bool) causes silent skip.

    _get_task_reward explicitly excludes bools via `not isinstance(val, bool)`,
    so True/False are treated as "no valid reward field" and skipped.
    An escrow of 99 for a task with reward_wea=True (truthy but excluded)
    silently passes even though no legitimate reward is on record.
    """
    result = _run(
        active={"300": {"amount": 99, "type": "pod"}},
        task_entries={"300": {"reward_wea": True}},  # bool excluded from reward
    )
    # GAP: bool excluded → task skipped → mismatch (99 vs True≡1) undetected
    assert result["status"] == "PASS"
    assert result["violations"] == []
    skipped_issues = {s["issue"] for s in result["skipped"]}
    assert "300" in skipped_issues


def test_gap_history_missing_issue_field_silently_skipped() -> None:
    """CONFIRMED GAP: history escrow_create with no issue field is silently dropped.

    The checker does `issue = str(event.get("issue", "")).strip()` then
    `if not issue: continue`. A malformed event with no issue key (or empty
    issue) is silently discarded regardless of amount. Any amount mismatch
    in such an event goes entirely undetected and unreported in skipped[].
    """
    events = [{"type": "escrow_create", "amount": 99}]  # no "issue" key
    result = _run(
        task_entries={"200": {"reward_wea": 35}},
        events=events,
    )
    # GAP: event with missing issue is dropped with no trace in skipped[]
    assert result["status"] == "PASS"
    assert result["violations"] == []
    # No skipped entry either — the event vanishes without trace
    assert result["skipped"] == []
