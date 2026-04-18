"""Adversarial tests for scripts/check_claim_chain_integrity.py.

Each test constructs a crafted history containing a real orphaned claim and
asserts that the checker returns FAIL.  A "bypass vector" is any input pattern
that might trick a naive checker into returning PASS when an orphaned claim
actually exists.  The inline comment on each test names the specific technique.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_claim_chain_integrity import run_check


# ---------------------------------------------------------------------------
# Helpers (mirroring the canonical test suite helpers for consistency)
# ---------------------------------------------------------------------------


def _make_repo(root: Path) -> Path:
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def _write_history(root: Path, filename: str, events: list[dict | str]) -> None:
    lines = [json.dumps(e) if isinstance(e, dict) else e for e in events]
    (root / "ledger" / "history" / filename).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_task_index(root: Path, tasks: dict) -> None:
    (root / "ledger" / "task_index.json").write_text(
        json.dumps({"version": 1, "tasks": tasks}),
        encoding="utf-8",
    )


def _write_escrows(root: Path, active: dict | None = None) -> None:
    (root / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": active or {}}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Test 1: accept recorded on a *different* issue must not resolve the claim
# ---------------------------------------------------------------------------


def test_accept_on_different_issue_does_not_resolve_claim(temp_repo: Path) -> None:
    # Bypass technique: alice has a valid accept event in the ledger, but it is
    # for issue 99 — not for the claimed issue 42.  A naive checker that only
    # matches on agent identity (ignoring issue number) would count this accept as
    # resolving alice's claim on issue 42 and falsely return PASS.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": 99,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["issue"] == 42
    assert broken[0]["reason"] == "closed_without_resolution"


# ---------------------------------------------------------------------------
# Test 2: accept whose timestamp predates the claim must not resolve it
# ---------------------------------------------------------------------------


def test_accept_predating_claim_does_not_resolve_it(temp_repo: Path) -> None:
    # Bypass technique: an accept for alice on issue 42 exists in the ledger at
    # T=09:00, but alice's claim was placed at T=10:00.  After chronological sort
    # the accept precedes the claim, so the claim has no later matching event.
    # A checker that scans the full file without respecting sort order would
    # encounter the accept and falsely mark the claim resolved.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    assert any(b["issue"] == 42 for b in broken)


# ---------------------------------------------------------------------------
# Test 3: claim with no events at all after it (plainest possible orphan)
# ---------------------------------------------------------------------------


def test_claim_with_no_subsequent_events_on_closed_issue_fails(temp_repo: Path) -> None:
    # Bypass technique: no misleading data is present — simply a claim on a paid
    # issue with nothing recorded after it.  Any checker that silently permits
    # unresolved claims on closed issues (treating them as "pending") would PASS.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["reason"] == "closed_without_resolution"


# ---------------------------------------------------------------------------
# Test 4: accept recorded for the wrong agent must not resolve the original claim
# ---------------------------------------------------------------------------


def test_accept_for_wrong_agent_does_not_resolve_claim(temp_repo: Path) -> None:
    # Bypass technique: alice claimed issue 42 but bob's accept is recorded.  A
    # checker that only validates "there is an accept for this issue" without
    # checking agent identity would treat bob's accept as resolving alice's claim.
    # In single-claim mode the checker must flag this as mismatched_terminal.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": 42,
                "agent": "bob@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["reason"] == "mismatched_terminal"


# ---------------------------------------------------------------------------
# Test 5: same-agent re-claim followed by silence — the re-claim itself is orphaned
# ---------------------------------------------------------------------------


def test_same_agent_reclaim_then_silence_is_orphaned(temp_repo: Path) -> None:
    # Bypass technique: alice's first claim is superseded by her second (re-claim),
    # which appears to "clean up" the first.  But the re-claim itself receives no
    # resolution before the issue is paid.  A checker that counts supersession as
    # "resolved" without also checking the superseding claim would return PASS.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    # First claim is superseded (resolved). Second claim is broken (no resolution on closed issue).
    assert len(broken) == 1
    assert broken[0]["reason"] == "closed_without_resolution"


# ---------------------------------------------------------------------------
# Test 6: multi-claim (PoD) issue — second agent paid, first agent orphaned
# ---------------------------------------------------------------------------


def test_multi_claim_first_agent_orphaned_when_only_second_paid(temp_repo: Path) -> None:
    # Bypass technique: bob receives a payment on the same issue, which might
    # suggest the task is fully settled.  In every_good (multi-claim) mechanics
    # each claimant needs its own matching terminal event.  Alice never received
    # a payment so her claim is a broken chain on a closed issue.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"30": {"status": "paid", "mechanic": "every_good"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 30,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "claim",
                "issue": 30,
                "agent": "bob@test",
                "timestamp": "2026-04-01T09:30:00Z",
            },
            {
                "type": "payment",
                "issue": 30,
                "agent": "bob@test",
                "amount": 5,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["agent"] == "alice@test"
    assert broken[0]["reason"] == "closed_without_same_agent_resolution"


# ---------------------------------------------------------------------------
# Test 7: case-mismatched agent ID between claim and accept
# ---------------------------------------------------------------------------


def test_case_mismatched_agent_id_does_not_resolve_claim(temp_repo: Path) -> None:
    # Bypass technique: the claim is recorded as "Alice@Test" (mixed case) and the
    # accept uses "alice@test" (lowercase).  A checker that normalises agent IDs to
    # lowercase before comparing would falsely treat them as the same identity and
    # return PASS.  Agent identity comparison must be case-sensitive.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "Alice@Test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["reason"] == "mismatched_terminal"


# ---------------------------------------------------------------------------
# Test 8: claim and accept share an identical timestamp — accept appears on an
#         earlier line, so it sorts before the claim and does not resolve it
# ---------------------------------------------------------------------------


def test_same_timestamp_accept_before_claim_in_line_order_does_not_resolve(
    temp_repo: Path,
) -> None:
    # Bypass technique: the accept and claim for alice on issue 42 carry the exact
    # same ISO timestamp.  The accept is written on line 1 of the file and the
    # claim on line 2.  Tie-breaking by (timestamp, filename, line_number) places
    # the accept before the claim in the sorted event list, giving the claim no
    # later matching event.  A checker that ignores sort stability or uses a set
    # rather than an ordered list would miss this and falsely PASS.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    # Intentionally write accept first (lower line number) then claim — same timestamp.
    (root / "ledger" / "history" / "2026-04-01.jsonl").write_text(
        json.dumps(
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T10:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["issue"] == 42


# ---------------------------------------------------------------------------
# Test 9: accept event with a null issue field — malformed input
# ---------------------------------------------------------------------------


def test_malformed_accept_with_null_issue_raises_error(temp_repo: Path) -> None:
    # Bypass technique: the accept event carries `"issue": null`.  A lenient
    # checker that silently skips null-issue events would leave alice's claim
    # unresolved but suppress the error, potentially returning PASS.  The checker
    # must raise ValueError on any relevant event (accept) that lacks a valid
    # issue number, propagating as FAIL through the main entry-point.
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": None,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    with pytest.raises(ValueError, match="missing valid issue"):
        run_check(root)


# ---------------------------------------------------------------------------
# Test 10: claim event that is missing the agent field entirely
# ---------------------------------------------------------------------------


def test_claim_missing_agent_field_raises_error(temp_repo: Path) -> None:
    # Bypass technique: a claim with no "agent" or "author" field could be treated
    # as a wildcard that any accept would satisfy.  The checker must reject any
    # relevant event that lacks an agent identity, raising ValueError (FAIL).
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "timestamp": "2026-04-01T09:00:00Z",
            },
        ],
    )

    with pytest.raises(ValueError, match="missing agent"):
        run_check(root)


# ---------------------------------------------------------------------------
# Test 11: triple re-claim chain — every claim superseded, tail claim orphaned
# ---------------------------------------------------------------------------


def test_triple_reclaim_chain_tail_orphaned_on_closed_issue(temp_repo: Path) -> None:
    # Bypass technique: alice claims three times in succession.  Each claim
    # supersedes the previous one, creating a chain of "resolved via supersession"
    # records.  A checker that stops after confirming a claim is superseded without
    # recursively validating the superseding claim would miss the dangling tail.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"42": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T10:00:00Z",
            },
            {
                "type": "claim",
                "issue": 42,
                "agent": "alice@test",
                "timestamp": "2026-04-01T11:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    # Claims 1 and 2 are superseded; claim 3 is broken (no resolution, closed issue).
    assert len(broken) == 1
    assert broken[0]["reason"] == "closed_without_resolution"
    assert report["summary"]["superseded"] == 2


# ---------------------------------------------------------------------------
# Test 12 (tester's choice): accepted_agents inference forces multi-claim mode —
#          orphan on closed issue is still detected
# ---------------------------------------------------------------------------


def test_accepted_agents_inference_does_not_mask_orphan_on_closed_issue(
    temp_repo: Path,
) -> None:
    # Bypass technique: task_index lists `accepted_agents: ["alice@test", "bob@test"]`
    # with no explicit mechanic field.  The checker infers "every_good" (multi-claim)
    # from the two-entry list.  In multi-claim mode bob's accept is skipped when
    # resolving alice's claim (different agent).  A checker that inferred multi-claim
    # and then treated the orphaned claimant's chain as "pending" on an open-sounding
    # issue would falsely PASS.  The issue is paid, so alice's unresolved claim must
    # be flagged as broken regardless of the inferred mechanic.
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {"300": {"status": "paid", "accepted_agents": ["alice@test", "bob@test"]}},
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 300,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": 300,
                "agent": "bob@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["agent"] == "alice@test"
    assert broken[0]["reason"] == "closed_without_same_agent_resolution"


# ---------------------------------------------------------------------------
# Test 13 (bonus): "winner_take_all" escrow alias → "best_x" mechanic (multi-claim) —
#                  orphaned claimant still detected on closed issue
# ---------------------------------------------------------------------------


def test_winner_take_all_alias_multi_claim_orphan_detected(temp_repo: Path) -> None:
    # Bypass technique: the escrow for issue 400 carries `type: "winner_take_all"`.
    # The mechanic normaliser maps this alias to "best_x" (a multi-claim mechanic).
    # In multi-claim mode bob's payment is ignored when checking alice's chain.
    # A checker that short-circuits after detecting a multi-claim mechanic and
    # treating all claims as "pending" would miss alice's broken chain on a closed
    # issue.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"400": {"status": "paid"}})
    _write_escrows(root, {"400": {"type": "winner_take_all", "amount": 20}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 400,
                "agent": "alice@test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "payment",
                "issue": 400,
                "agent": "bob@test",
                "amount": 20,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    broken = report["broken_claims"]
    assert broken[0]["agent"] == "alice@test"
    assert "closed" in broken[0]["reason"]


# ---------------------------------------------------------------------------
# Test 14 (bonus): "author" field alias with case mismatch — same bypass via
#                  alternate field name
# ---------------------------------------------------------------------------


def test_case_mismatched_author_field_alias_does_not_resolve_claim(
    temp_repo: Path,
) -> None:
    # Bypass technique: the claim uses the "author" field alias (not "agent") with
    # value "Alice@Test".  The accept uses "agent" with "alice@test".  Agent
    # extraction strips whitespace but does not normalise case.  A checker that
    # lowercased the author alias value before comparison would falsely PASS.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"50": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {
                "type": "claim",
                "issue": 50,
                "author": "Alice@Test",
                "timestamp": "2026-04-01T09:00:00Z",
            },
            {
                "type": "accept",
                "issue": 50,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-01T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["reason"] == "mismatched_terminal"
