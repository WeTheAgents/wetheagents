"""Boundary-spec tests for scripts/check_history_escrow_solvency.py.

Covers exact-balance boundary, same-timestamp ordering, balance-restored-before-second-
escrow, zero-balance escrow attempts, escrow_return balance restoration, and multi-file
chronological replay.

## Gaps

GAP-1 (zero-amount escrow on zero-balance agent): An escrow_create with amount=0 on a
zero-balance agent is not flagged as a violation. The solvency check is
``balance_before < amount``; when amount=0 the condition is False regardless of balance.
Free-task escrows and data-entry errors with amount=0 silently pass the solvency check.

GAP-2 (same-timestamp ordering determines solvency outcome): When two escrow_create
events share an identical timestamp in the same file, replay processes them in ascending
line-number order. The first line debits balance before the second line is evaluated.
If the combined total exceeds the balance, only the later-line event is flagged as a
violation even though both events were submitted at the same instant. Callers issuing
simultaneous escrows for the same agent must pre-verify that the combined total does not
exceed the available balance; there is no atomic batch guarantee.

GAP-3 (duplicate escrow_return for same issue+recipient is silently dropped): The replay
deduplicates escrow_return events on the key (issue, recipient). A second return event
with the same key is silently ignored — the agent's balance is not credited a second
time. If a workflow legitimately issues two separate return credits for the same
issue+agent pair, only the first is applied. Any subsequent escrow_create that depends on
both returns being credited will see a lower-than-expected balance and may be incorrectly
flagged or pass incorrectly in external tooling that assumes full restoration.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_escrow_solvency import run_check


def _hist(root: Path, filename: str, events: list[dict]) -> None:
    """Write events as a .jsonl history file (directory already exists via temp_repo)."""
    (root / "ledger" / "history" / filename).write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


# ── 1. Exact Balance Boundary ──────────────────────────────────────────────────
# The solvency check is: balance_before < amount → violation (strict less-than).
# An escrow_create for exactly the full balance passes (>=, not >).
#
# Decision table (alice funded with 50 WEA):
# | event              | balance_before | amount | balance_after | result |
# |--------------------|----------------|--------|---------------|--------|
# | payment(50)        | 0              | +50    | 50            | credit |
# | escrow_create(50)  | 50             | 50     | 0             | PASS   | ← 50 >= 50
# | escrow_create(1)   | 0              | 1      | —             | FAIL   | ← 0 < 1
#
# After the first escrow debits the full balance, any subsequent positive-amount
# escrow_create fails immediately because balance is 0.


def test_exact_balance_boundary_at_exact_amount_passes(temp_repo: Path) -> None:
    """escrow_create for exactly the full balance passes (>= check, not strictly >)."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 1, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_exact_balance_boundary_second_escrow_after_exhaustion_fails(temp_repo: Path) -> None:
    """After an exact-balance escrow exhausts all funds, any subsequent escrow fails."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 1, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
        {"type": "escrow_create", "issue": 2, "author": "alice@test", "amount": 1,  "timestamp": "2026-01-01T03:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 2
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["issue"] == 2
    assert v["balance_before"] == 0
    assert v["shortfall"] == 1


# ── 2. Same-Timestamp Ordering ─────────────────────────────────────────────────
# Sort key: (event_timestamp, filename, line_number). When two escrow_create events
# share the same timestamp inside the same file, replay processes them in ascending
# line-number order. The first line debits balance before the second line is evaluated.
#
# Decision table (alice has 70 WEA, both escrow_creates share timestamp T):
# | event             | file | line | balance_before | amount | result |
# |-------------------|------|------|----------------|--------|--------|
# | payment(70)       | A    | 1    | —              | +70    | credit |
# | escrow_create(40) | A    | 2    | 70             | 40     | PASS   |
# | escrow_create(35) | A    | 3    | 30             | 35     | FAIL   | ← GAP-2
#
# Combined 40+35=75 > 70, so the second (later-line) event is flagged.
#
# Decision table (alice has 100 WEA, combined 40+40=80 ≤ 100):
# | event             | file | line | balance_before | amount | result |
# |-------------------|------|------|----------------|--------|--------|
# | payment(100)      | A    | 1    | —              | +100   | credit |
# | escrow_create(40) | A    | 2    | 100            | 40     | PASS   |
# | escrow_create(40) | A    | 3    | 60             | 40     | PASS   |


def test_same_timestamp_later_line_fails_when_combined_exceeds_balance(temp_repo: Path) -> None:
    """Same-timestamp escrow_creates processed by line order; combined >balance fails the second.

    GAP-2: the later-line event is rejected even though both were submitted simultaneously.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 70, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 10, "author": "alice@test", "amount": 40, "timestamp": "2026-01-01T02:00:00Z"},
        {"type": "escrow_create", "issue": 11, "author": "alice@test", "amount": 35, "timestamp": "2026-01-01T02:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 2
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["issue"] == 11       # second line fails, not the first
    assert v["balance_before"] == 30
    assert v["shortfall"] == 5


def test_same_timestamp_both_pass_when_combined_within_balance(temp_repo: Path) -> None:
    """Same-timestamp escrow_creates both pass when their combined total stays within balance."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 100, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 10, "author": "alice@test", "amount": 40, "timestamp": "2026-01-01T02:00:00Z"},
        {"type": "escrow_create", "issue": 11, "author": "alice@test", "amount": 40, "timestamp": "2026-01-01T02:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 2
    assert report["violations"] == []


# ── 3. Balance Restored Before Second Escrow ───────────────────────────────────
# Replay credits each payment event before it reaches subsequent escrow_create events.
# When an agent escrows their full balance, receives a new payment, and escrows again,
# both escrow_create events see a solvent balance.
#
# Decision table (alice receives two 50 WEA payments, one per cycle):
# | event              | balance_before | amount | balance_after | result |
# |--------------------|----------------|--------|---------------|--------|
# | payment(50)        | 0              | +50    | 50            | credit |
# | escrow_create(50)  | 50             | 50     | 0             | PASS   |
# | payment(50)        | 0              | +50    | 50            | credit |
# | escrow_create(50)  | 50             | 50     | 0             | PASS   |


def test_balance_restored_by_payment_before_second_escrow_passes(temp_repo: Path) -> None:
    """Two payment-then-escrow cycles both pass when each payment precedes its escrow."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 20, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T03:00:00Z"},
        {"type": "escrow_create", "issue": 21, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T04:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 2
    assert report["violations"] == []


def test_second_escrow_without_intervening_payment_fails(temp_repo: Path) -> None:
    """Second escrow for same amount fails when no payment replenishes the balance first."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 20, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
        # No payment here — balance stays 0
        {"type": "escrow_create", "issue": 21, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T03:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 21
    assert report["violations"][0]["balance_before"] == 0


# ── 4. Zero-Balance Escrow Attempt ─────────────────────────────────────────────
# An agent with 0 WEA cannot fund any positive-amount escrow. The check is
# balance_before < amount; for amount > 0 on a zero-balance agent this is always True.
#
# Decision table (alice has no incoming payment — starts at 0):
# | escrow_amount | balance_before | condition      | result      |
# |---------------|----------------|----------------|-------------|
# | 1             | 0              | 0 < 1 → True   | FAIL        |
# | 50            | 0              | 0 < 50 → True  | FAIL        |
# | 0             | 0              | 0 < 0 → False  | PASS (GAP-1)|
#
# GAP-1: amount=0 bypasses the solvency check. A zero-amount escrow on a zero-balance
# agent passes silently — neither the amount nor the balance is validated for positivity.


def test_zero_balance_escrow_attempt_for_positive_amount_fails(temp_repo: Path) -> None:
    """Agent with 0 WEA cannot create a positive-amount escrow (shortfall = amount)."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_create", "issue": 30, "author": "alice@test", "amount": 1, "timestamp": "2026-01-01T01:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert report["escrows_checked"] == 1
    assert report["violations"][0]["balance_before"] == 0
    assert report["violations"][0]["shortfall"] == 1


def test_zero_balance_escrow_attempt_large_amount_fails(temp_repo: Path) -> None:
    """Zero-balance agent attempting any positive amount is rejected; shortfall equals the amount."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_create", "issue": 31, "author": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["shortfall"] == 50


def test_zero_amount_escrow_on_zero_balance_passes_gap1(temp_repo: Path) -> None:
    """GAP-1: escrow_create with amount=0 on a zero-balance agent is not flagged.

    balance_before < amount evaluates to 0 < 0 = False, so no violation is recorded.
    Zero-amount escrows (free tasks or data-entry errors) pass the solvency check
    silently regardless of the agent's balance.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_create", "issue": 32, "author": "alice@test", "amount": 0, "timestamp": "2026-01-01T01:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS", "GAP-1: amount=0 satisfies balance_before < amount → False"
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


# ── 5. escrow_return Restores Balance ─────────────────────────────────────────
# escrow_return credits the named recipient (or agent0@system if no recipient field).
# Deduplication key is (issue, recipient); a second event with the same key is ignored.
#
# Normal case — return between two escrow_creates:
# | event                          | balance | dedup_set         | result |
# |--------------------------------|---------|-------------------|--------|
# | payment(50)                    | 50      | {}                | credit |
# | escrow_create(50) issue=40     | 0       | {}                | PASS   |
# | escrow_return(50) issue=40     | 50      | {(40, alice)}     | return |
# | escrow_create(50) issue=41     | 0       | {(40, alice)}     | PASS   |
#
# GAP-3 sub-case — second return for same (issue, recipient) is silently ignored:
# | event                          | balance | dedup_set         | result         |
# |--------------------------------|---------|-------------------|----------------|
# | payment(50)                    | 50      | {}                | credit         |
# | escrow_create(50) issue=60     | 0       | {}                | PASS           |
# | escrow_return(50) issue=60 #1  | 50      | {(60, alice)}     | return         |
# | escrow_return(50) issue=60 #2  | 50      | {(60, alice)}     | IGNORED (GAP-3)|
# | escrow_create(100) issue=61    | —       | {(60, alice)}     | FAIL ← 50 < 100|


def test_escrow_return_restores_balance_for_subsequent_escrow(temp_repo: Path) -> None:
    """escrow_return credits balance so a second escrow_create for the same amount passes."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 40, "author": "alice@test",    "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
        {"type": "escrow_return", "issue": 40, "recipient": "alice@test", "amount": 50, "timestamp": "2026-01-01T03:00:00Z"},
        {"type": "escrow_create", "issue": 41, "author": "alice@test",    "amount": 50, "timestamp": "2026-01-01T04:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 2
    assert report["violations"] == []


def test_escrow_return_without_matching_escrow_create_still_credits(temp_repo: Path) -> None:
    """escrow_return credits balance even if no prior escrow_create for that issue is in history."""
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_return", "issue": 50, "recipient": "alice@test", "amount": 30, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 51, "author": "alice@test",    "amount": 30, "timestamp": "2026-01-01T02:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1


def test_duplicate_escrow_return_second_ignored_causes_shortage_gap3(temp_repo: Path) -> None:
    """GAP-3: second escrow_return for same (issue, recipient) is silently dropped.

    Only the first return is credited. A subsequent escrow that relies on both returns
    being applied sees a lower balance than expected and is flagged as a violation.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",       "agent": "alice@test", "amount": 50, "timestamp": "2026-01-01T01:00:00Z"},
        {"type": "escrow_create", "issue": 60, "author": "alice@test",    "amount": 50, "timestamp": "2026-01-01T02:00:00Z"},
        # First return: credited → balance = 50
        {"type": "escrow_return", "issue": 60, "recipient": "alice@test", "amount": 50, "timestamp": "2026-01-01T03:00:00Z"},
        # Second return (same issue, same recipient): IGNORED by dedup → balance stays 50
        {"type": "escrow_return", "issue": 60, "recipient": "alice@test", "amount": 50, "timestamp": "2026-01-01T04:00:00Z"},
        # Agent expects balance=100 from two returns; actual=50 → escrow for 100 fails
        {"type": "escrow_create", "issue": 61, "author": "alice@test",    "amount": 100, "timestamp": "2026-01-01T05:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL", "GAP-3: second return dropped; balance=50, not 100"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["issue"] == 61
    assert v["balance_before"] == 50
    assert v["shortfall"] == 50


# ── 6. Multi-File Cross-Boundary Replay ───────────────────────────────────────
# Events are sorted globally by (event_timestamp, filename, line_number) before replay.
# Balance state carries across file boundaries: a payment in an earlier file funds an
# escrow in a later file, provided the payment's timestamp precedes the escrow's.
#
# Decision table (explicit timestamps, two files):
# | event             | file             | timestamp          | balance | result |
# |-------------------|------------------|--------------------|---------|--------|
# | payment(50)       | 2026-04-01.jsonl | 2026-04-01T10:00Z  | 50      | credit |
# | escrow_create(50) | 2026-04-02.jsonl | 2026-04-02T10:00Z  | 0       | PASS   |
#
# No-timestamp fallback case (file date used as timestamp):
# | event             | file             | file_date_ts       | balance | result |
# |-------------------|------------------|--------------------|---------|--------|
# | payment(50)       | 2026-04-01.jsonl | 2026-04-01T00:00Z  | 50      | credit |
# | escrow_create(50) | 2026-04-02.jsonl | 2026-04-02T00:00Z  | 0       | PASS   |
#
# Timestamp-overrides-filename case (event timestamp takes precedence over filename sort):
# | event             | file             | event_timestamp    | sort_pos | result |
# |-------------------|------------------|--------------------|----------|--------|
# | payment(50)       | 2026-04-02.jsonl | 2026-04-01T09:00Z  | 1st      | credit |
# | escrow_create(50) | 2026-04-01.jsonl | 2026-04-01T10:00Z  | 2nd      | PASS   |
# The payment is in the later-named file but its earlier timestamp causes it to replay
# first. Filename is only a tiebreak when timestamps are equal.


def test_multifile_payment_before_escrow_with_explicit_timestamps(temp_repo: Path) -> None:
    """Payment in an earlier-dated file funds an escrow in a later-dated file."""
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50, "timestamp": "2026-04-01T10:00:00Z"},
    ])
    _hist(temp_repo, "2026-04-02.jsonl", [
        {"type": "escrow_create", "issue": 70, "author": "alice@test", "amount": 50, "timestamp": "2026-04-02T10:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_multifile_no_timestamp_uses_file_date_order(temp_repo: Path) -> None:
    """Events without explicit timestamps fall back to the file-date (filename stem) for ordering."""
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50},
    ])
    _hist(temp_repo, "2026-04-02.jsonl", [
        {"type": "escrow_create", "issue": 71, "author": "alice@test", "amount": 50},
    ])
    report = run_check(temp_repo)
    # file date 2026-04-01 < 2026-04-02 → payment replays first → PASS
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1


def test_multifile_event_timestamp_overrides_filename_order(temp_repo: Path) -> None:
    """Event timestamp takes precedence over filename; a later-named file can replay first."""
    # Payment is in the "later" file but its event timestamp is earlier
    _hist(temp_repo, "2026-04-02.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50, "timestamp": "2026-04-01T09:00:00Z"},
    ])
    # escrow_create is in the "earlier" file but its event timestamp is later
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 72, "author": "alice@test", "amount": 50, "timestamp": "2026-04-01T10:00:00Z"},
    ])
    # Sort keys: (2026-04-01T09:00Z, "2026-04-02.jsonl", 1) < (2026-04-01T10:00Z, "2026-04-01.jsonl", 1)
    # Payment replays first despite being in the later-named file → balance=50 → PASS
    report = run_check(temp_repo)
    assert report["status"] == "PASS"
    assert report["escrows_checked"] == 1


def test_multifile_insufficient_payment_across_files_fails(temp_repo: Path) -> None:
    """Escrow in a later file fails when the agent's total payments are insufficient."""
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 30, "timestamp": "2026-04-01T10:00:00Z"},
    ])
    _hist(temp_repo, "2026-04-02.jsonl", [
        {"type": "escrow_create", "issue": 73, "author": "alice@test", "amount": 50, "timestamp": "2026-04-02T10:00:00Z"},
    ])
    report = run_check(temp_repo)
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["balance_before"] == 30
    assert v["shortfall"] == 20
