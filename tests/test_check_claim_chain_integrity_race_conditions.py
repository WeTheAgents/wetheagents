"""Race condition adversarial tests for scripts/check_claim_chain_integrity.py.

T2S24 — Gauntlet Trajectory 2, Slot 24.

Three multi-agent race-condition scenarios that should be flagged as violations:

  R1. Two agents claim the same single-winner issue with overlapping (sub-second)
      timestamps.  Only the later claimant is the active winner; if the earlier
      claimant gets paid instead the chain is broken.

  R2. An agent submits a claim *after* the issue was already resolved and closed.
      The late claim has no resolution events and must be flagged.

  R3. A payment appears in history *before* the corresponding claim (and before
      the escrow was created).  Because the payment predates the claim it cannot
      serve as the claim's resolution; the claim is left dangling on a closed issue.

For every test: the assertion is ``report["status"] == "FAIL"``.
If the checker returns PASS the assertion fails, meaning the checker missed the
violation.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_claim_chain_integrity import run_check


# ---------------------------------------------------------------------------
# Helpers (mirroring the canonical test suite)
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
# R1: Overlapping claim timestamps — wrong agent paid after supersession
# ---------------------------------------------------------------------------


def test_race_condition_overlapping_claims_wrong_agent_paid(temp_repo: Path) -> None:
    # Race condition scenario: two agents each see the issue as open and submit
    # claims within one second of each other.  alice claims at T=09:00:00Z;
    # bob claims at T=09:00:01Z (one second later — overlapping in a real
    # distributed system).
    #
    # Temporal sort: alice_claim < bob_claim < alice_payment
    #   - alice's chain: next event is bob's claim → superseded (alice loses)
    #   - bob's chain: next event is alice_payment → alice != bob → BROKEN
    #
    # Bypass technique: a naive checker that resolves claims greedily from the
    # beginning of the event list might credit alice's payment to her original
    # claim (ignoring that bob superseded her).  It would mark alice as
    # "resolved" and bob as "pending", returning PASS.  The correct checker
    # must apply temporal supersession: once bob's claim supersedes alice's,
    # the only valid payment is to bob.  Alice receiving payment while bob is
    # the active claimant is a mismatched_terminal violation.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"200": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-19.jsonl",
        [
            # alice is first by 1 second — race condition overlap
            {
                "type": "claim",
                "issue": 200,
                "agent": "alice@test",
                "timestamp": "2026-04-19T09:00:00Z",
            },
            # bob claims 1 second later, superseding alice
            {
                "type": "claim",
                "issue": 200,
                "agent": "bob@test",
                "timestamp": "2026-04-19T09:00:01Z",
            },
            # alice gets paid — but bob is the active claimant after the race
            {
                "type": "payment",
                "issue": 200,
                "agent": "alice@test",
                "amount": 40,
                "timestamp": "2026-04-19T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    # Checker must detect that bob's claim (the superseding, active claim) was
    # never resolved.  alice's payment lands after bob's claim, making it a
    # mismatched_terminal for bob.
    assert report["status"] == "FAIL", (
        "checker missed the race condition: alice's superseded claim was paid "
        "while bob's active claim was never resolved"
    )
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["agent"] == "bob@test"
    assert broken[0]["reason"] == "mismatched_terminal"
    # alice's claim is superseded (not broken)
    assert report["summary"]["superseded"] == 1


# ---------------------------------------------------------------------------
# R2: Claim submitted after issue already resolved — late PR scenario
# ---------------------------------------------------------------------------


def test_claim_submitted_after_issue_already_closed_is_broken(temp_repo: Path) -> None:
    # Scenario: bob legitimately claimed, worked, and had his submission
    # accepted before the issue was marked paid.  alice submits a claim AFTER
    # the issue has already been resolved — equivalent to opening a PR after
    # the issue is closed.
    #
    # Timeline (sorted):
    #   T=08:00Z  bob claims
    #   T=09:00Z  bob accepted  → bob's chain cleanly resolved
    #   T=10:00Z  alice claims  ← AFTER issue was accepted/closed
    #
    # Bypass technique: a checker that processes claims in file-write order
    # (not timestamp order) and stops at the first resolved chain would never
    # reach alice's late claim.  The correct checker must sort all events by
    # timestamp and evaluate every claim, including those filed after the last
    # terminal event.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"201": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-19.jsonl",
        [
            # bob's legitimate chain — fully resolved before alice claims
            {
                "type": "claim",
                "issue": 201,
                "agent": "bob@test",
                "timestamp": "2026-04-19T08:00:00Z",
            },
            {
                "type": "accept",
                "issue": 201,
                "agent": "bob@test",
                "amount": 40,
                "timestamp": "2026-04-19T09:00:00Z",
            },
            # alice files a claim AFTER the issue was already accepted
            {
                "type": "claim",
                "issue": 201,
                "agent": "alice@test",
                "timestamp": "2026-04-19T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    # bob's chain resolves cleanly.  alice's late claim on a paid issue must
    # be flagged as closed_without_resolution.
    assert report["status"] == "FAIL", (
        "checker missed the late claim: alice filed after the issue was already "
        "accepted and paid, but the checker did not flag it"
    )
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["agent"] == "alice@test"
    assert broken[0]["reason"] == "closed_without_resolution"
    # bob's chain should be cleanly resolved
    assert report["summary"]["resolved_by_accept"] == 1


# ---------------------------------------------------------------------------
# R3: Payment recorded before claim and before escrow_create — temporal violation
# ---------------------------------------------------------------------------


def test_payment_before_escrow_create_and_claim_is_temporal_violation(
    temp_repo: Path,
) -> None:
    # Temporal violation scenario: alice's payment appears in history at T=08:00Z,
    # but the escrow for the issue was not created until T=09:00Z and alice's
    # claim was not filed until T=10:00Z.  In a correct ledger, payment can
    # only follow a valid claim; a payment that precedes its own claim is a
    # sign of backdating, replaying, or out-of-order processing.
    #
    # How the checker detects this:
    #   Events sorted by timestamp (claim-relevant only):
    #     T=08:00Z  payment (alice)   ← precedes the claim
    #     T=10:00Z  claim (alice)     ← filed AFTER the payment
    #   For alice's claim at T=10:00Z: later_events = [] (no events after T10).
    #   Issue is paid → broken (closed_without_resolution).
    #
    # The escrow_create at T=09:00Z is non-relevant and invisible to the checker.
    # The violation is caught because the payment is before the claim in sorted
    # order, leaving the claim with no resolution events.
    #
    # Bypass technique: a checker that scans the entire issue event list (not
    # just events *after* the claim) to find a matching payment would see
    # alice's payment at T=08:00Z and falsely mark the claim resolved.  The
    # correct checker must only look at events that are chronologically later
    # than the claim.
    root = _make_repo(temp_repo)
    _write_task_index(root, {"202": {"status": "paid", "mechanic": "standard"}})
    _write_history(
        root,
        "2026-04-19.jsonl",
        [
            # payment recorded FIRST — temporal violation (precedes both escrow and claim)
            {
                "type": "payment",
                "issue": 202,
                "agent": "alice@test",
                "amount": 40,
                "timestamp": "2026-04-19T08:00:00Z",
            },
            # escrow_create is ignored by the checker but documents the real-world order
            {
                "type": "escrow_create",
                "issue": 202,
                "agent": "agent0@system",
                "amount": 40,
                "timestamp": "2026-04-19T09:00:00Z",
            },
            # alice's claim filed AFTER the payment was already recorded
            {
                "type": "claim",
                "issue": 202,
                "agent": "alice@test",
                "timestamp": "2026-04-19T10:00:00Z",
            },
        ],
    )

    report = run_check(root)

    # The payment at T=08:00Z precedes alice's claim at T=10:00Z in the sorted
    # timeline, so it cannot serve as a resolution for the claim.  alice's claim
    # has no later events on a paid issue → broken.
    assert report["status"] == "FAIL", (
        "checker missed the temporal violation: payment was recorded before the "
        "claim was filed, so the claim has no valid resolution"
    )
    broken = report["broken_claims"]
    assert len(broken) == 1
    assert broken[0]["agent"] == "alice@test"
    assert broken[0]["issue"] == 202
    assert broken[0]["reason"] == "closed_without_resolution"
