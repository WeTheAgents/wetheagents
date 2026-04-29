"""Red-team tests for scripts/check_history_escrow_solvency.py.

Six bypass vectors that cause the checker to report PASS for genuinely insolvent
escrow_create events (false negatives) or to silently skip solvency enforcement on
functionally equivalent bulk-escrow events.

## Bypass Vector 1 — ``type = "escrow"`` bypasses solvency check [CRITICAL]

The dispatch branch is ``elif event_type in {"escrow", "escrow_create"}``, but the
inner solvency guard fires only when ``event_type == "escrow_create"``.  A bare
``"escrow"`` event debits the author's balance without any violation check.

Decision table (alice has 0 WEA):
| event                 | event_type    | balance_before | check? | balance_after | result |
|-----------------------|---------------|----------------|--------|---------------|--------|
| escrow(amount=100)    | "escrow"      | 0              | NO     | -100          | PASS ← |

The violation is silently swallowed.  The balance goes negative, but no violation
is appended and the function returns ``status = "PASS"``.

## Bypass Vector 2 — ``escrow_return_bulk`` no deduplication, unlimited inflation [CRITICAL]

``escrow_return`` deduplicates on ``(issue, recipient)``.  ``escrow_return_bulk``
has no such guard: every event unconditionally credits ``balances[recipient]``.
Repeating bulk-return events for the same agent multiplies their balance by the
repetition count.

Decision table (alice has 0 WEA, issue=10, amount=50 each):
| event                     | balance | dedup_set | result       |
|---------------------------|---------|-----------|--------------|
| escrow_return_bulk #1     | 50      | —         | credited     |
| escrow_return_bulk #2     | 100     | —         | credited     |
| escrow_return_bulk #3     | 150     | —         | credited     |
| escrow_create(amount=140) | 10      | —         | PASS ← false |

Alice started with 0 WEA.  Without the bulk returns her escrow would fail
(0 < 140).  With three unguarded bulk returns the replay sees 150 WEA and
records no violation.

## Bypass Vector 3 — ``_MECHANIC_KEYWORDS`` type + ``event`` field shadow [CRITICAL]

``_normalize_type`` replaces ``event_type`` with ``event.get("event")`` whenever
``type`` is in ``_MECHANIC_KEYWORDS``.  A crafted event with
``type = "pod"`` and ``event = "payment"`` is dispatched through the payment
handler and credits the recipient's balance without any corresponding debit.

Decision table (alice has 0 WEA):
| event dict                                       | resolved type | balance delta | result |
|--------------------------------------------------|---------------|---------------|--------|
| {type:"pod", event:"payment", amount:500, ...}  | "payment"     | alice += 500  | credit |
| {type:"escrow_create", amount:400, author:alice} | "escrow_create"| alice -= 400  | PASS ← |

The type normalisation path was designed to unify mechanic-keyword aliases
(``"pod"`` → look at ``"event"`` for the actual intent), but it also lets an
attacker inject arbitrary event-type semantics through the ``event`` field.

## Bypass Vector 4 — Non-ISO-date filename pushes ``escrow_create`` to sort ``max_dt`` [HIGH]

Events without an explicit timestamp fall back to ``_file_timestamp(path)``,
which parses ``{path.stem}T00:00:00Z``.  Files whose stem is not a valid ISO
date (e.g. ``misc.jsonl``) produce ``None``, and the sort key becomes
``datetime.max`` — placing those events LAST in the replay, after all dated events.

Attack scenario (alice has 0 WEA at escrow time; payment arrives later):
| event              | file              | effective sort key            | result         |
|--------------------|-------------------|-------------------------------|----------------|
| payment(50)        | 2026-04-01.jsonl  | 2026-04-01T00:00:00Z          | replayed 1st   |
| escrow_create(50)  | misc.jsonl        | datetime.max                  | replayed 2nd   |

In real-time alice had 0 WEA when the escrow was created; the payment came
later.  But because ``misc.jsonl`` sorts after ``2026-04-01.jsonl``, the replay
processes the payment first, giving alice 50 WEA, and then sees the escrow
against a balance of 50 → PASS.  The insolvency at creation time is concealed
by the sort anomaly.

## Bypass Vector 5 — ``escrow_batch`` not checked for solvency [HIGH]

``escrow_batch`` debits ``balances[author] -= total`` but contains no
``balance_before < total`` guard.  A zero-balance agent can issue an arbitrarily
large ``escrow_batch`` and the checker never records a violation.  The spec says
"every escrow_create event", but a batch escrow represents the same lock-up of
funds and is equally capable of representing a fraudulent over-allocation.

Decision table (alice has 0 WEA):
| event                              | check? | balance_after | result |
|------------------------------------|--------|---------------|--------|
| escrow_batch(total=9999, alice)    | NO     | -9999         | PASS ← |

``escrows_checked`` stays 0.  No violation is raised despite alice creating a
9999-WEA escrow with no funds.

## Bypass Vector 6 — ``agent_removal`` phantom ``balance_returned`` inflates agent0 [MEDIUM]

``agent_removal`` adds ``event["balance_returned"]`` directly to
``balances[AGENT0]`` with no cross-check: it does not verify that the removed
agent actually held that balance.  A forged removal for a non-existent (or
zero-balance) agent with an inflated ``balance_returned`` gives agent0 free WEA.

Decision table (agent0 starts at 10 000 WEA; "ghost@test" has 0 WEA):
| event                                             | agent0 balance | result       |
|---------------------------------------------------|----------------|--------------|
| agent_removal(agent="ghost@test", returned=50000) | 60 000         | inflated     |
| escrow_create(amount=55000, author=agent0)        | 5 000          | PASS ← false |

Without the phantom removal the escrow would fail (10 000 < 55 000).  With it
the replay sees 60 000 WEA for agent0 and passes the check.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_history_escrow_solvency import run_check


# ── helpers ────────────────────────────────────────────────────────────────────


def _hist(root: Path, filename: str, events: list[dict]) -> None:
    path = root / "ledger" / "history" / filename
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _ts(hour: int) -> str:
    return f"2026-01-01T{hour:02d}:00:00Z"


# ── Bypass Vector 1: ``type = "escrow"`` skips solvency check ─────────────────


def test_v1_escrow_type_skips_solvency_check_false_negative(temp_repo: Path) -> None:
    """BYPASS: ``type = "escrow"`` debits balance without triggering solvency check.

    alice has 0 WEA.  Using ``type = "escrow"`` (not ``"escrow_create"``) the
    event enters the shared ``{"escrow", "escrow_create"}`` branch but the inner
    ``if event_type == "escrow_create"`` guard is False.  No violation is added.
    Checker reports PASS despite alice having insufficient funds.

    Severity: CRITICAL — any escrow can bypass solvency enforcement by using the
    bare "escrow" type instead of "escrow_create".
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow", "from": "alice@test", "amount": 100, "issue": 1,
         "timestamp": _ts(1)},
    ])

    report = run_check(temp_repo)

    # Checker should FAIL (alice has 0 WEA, escrow=100), but it PASSES.
    assert report["status"] == "PASS", (
        "BYPASS V1: insolvent 'escrow' event passes unchecked — "
        "only 'escrow_create' triggers the solvency guard"
    )
    assert report["escrows_checked"] == 0, (
        "BYPASS V1: escrow event is not counted as an escrow_create — "
        "solvency check counter stays at 0"
    )
    assert report["violations"] == []


def test_v1_escrow_type_drains_balance_to_negative_silently(temp_repo: Path) -> None:
    """BYPASS: multiple bare ``escrow`` events drive balance deep negative with no violation.

    alice receives 50 WEA then issues two ``escrow`` events totalling 200 WEA.
    Under correct enforcement the second (and arguably the first) should fail.
    Both pass because neither uses ``escrow_create``.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",  "agent": "alice@test", "amount": 50,  "timestamp": _ts(1)},
        {"type": "escrow",   "from":  "alice@test", "amount": 100, "issue": 2,
         "timestamp": _ts(2)},
        {"type": "escrow",   "from":  "alice@test", "amount": 100, "issue": 3,
         "timestamp": _ts(3)},
    ])

    report = run_check(temp_repo)

    # Both insolvent escrow events pass because neither is "escrow_create".
    assert report["status"] == "PASS", (
        "BYPASS V1: two bare 'escrow' events totalling 200 WEA against a 50 WEA "
        "balance both pass — solvency guard never fires"
    )
    assert report["escrows_checked"] == 0


# ── Bypass Vector 2: ``escrow_return_bulk`` has no deduplication ───────────────


def test_v2_escrow_return_bulk_unlimited_inflation(temp_repo: Path) -> None:
    """BYPASS: repeated ``escrow_return_bulk`` events inflate balance without limit.

    alice has 0 WEA.  Three identical ``escrow_return_bulk`` events for issue=10
    each credit 50 WEA — giving alice 150 WEA in the replay despite starting with
    nothing.  A subsequent ``escrow_create`` for 140 WEA passes because the replay
    sees 150 WEA, not 0.

    Unlike ``escrow_return``, ``escrow_return_bulk`` has no (issue, recipient)
    deduplication guard.  Every copy is applied unconditionally.

    Severity: CRITICAL — attacker can manufacture arbitrary balance from thin air
    by repeating bulk-return events.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        # Three identical bulk returns → alice "credited" 3 × 50 = 150 WEA
        {"type": "escrow_return_bulk", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(1)},
        {"type": "escrow_return_bulk", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(2)},
        {"type": "escrow_return_bulk", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(3)},
        # alice started with 0; real balance = 0; replay sees 150 → PASS
        {"type": "escrow_create", "author": "alice@test", "amount": 140,
         "issue": 11, "timestamp": _ts(4)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        "BYPASS V2: three bulk-return duplicates inflate alice's balance to 150 "
        "WEA; insolvent escrow_create for 140 WEA passes unchallenged"
    )
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_v2_escrow_return_regular_dedup_blocks_same_inflation(temp_repo: Path) -> None:
    """Contrast: ``escrow_return`` (not bulk) deduplicates — same attack is blocked.

    Three identical ``escrow_return`` events for (issue=10, alice) are deduped.
    Only the first 50 WEA credit is applied.  The escrow_create for 140 WEA then
    correctly fails: 50 < 140.

    This test confirms the deduplication asymmetry between the two return types.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_return", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(1)},
        {"type": "escrow_return", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(2)},
        {"type": "escrow_return", "recipient": "alice@test", "amount": 50,
         "issue": 10, "timestamp": _ts(3)},
        {"type": "escrow_create", "author": "alice@test", "amount": 140,
         "issue": 11, "timestamp": _ts(4)},
    ])

    report = run_check(temp_repo)

    # Only first return is credited → balance=50 → 50 < 140 → FAIL (correct)
    assert report["status"] == "FAIL", (
        "escrow_return deduplication limits alice to 50 WEA; escrow for 140 is "
        "correctly flagged as insolvent"
    )
    assert len(report["violations"]) == 1
    assert report["violations"][0]["balance_before"] == 50
    assert report["violations"][0]["shortfall"] == 90


# ── Bypass Vector 3: mechanic-keyword type + ``event`` field shadow ───────────


def test_v3_mechanic_keyword_event_shadow_inflates_balance(temp_repo: Path) -> None:
    """BYPASS: ``type = "pod"`` + ``event = "payment"`` creates a phantom credit.

    ``_normalize_type`` falls through to ``event.get("event")`` when ``type`` is
    in ``_MECHANIC_KEYWORDS``.  ``{"type": "pod", "event": "payment", ...}``
    resolves to ``"payment"`` and credits the recipient without any debit
    elsewhere — manufacturing WEA from nothing.

    alice has 0 WEA.  After the phantom payment she appears to have 500 WEA in
    the replay; her subsequent escrow_create for 400 WEA passes.

    Severity: CRITICAL — any mechanic-keyword alias can shadow an arbitrary event
    type, injecting credits or other state-mutating events.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        # Phantom "payment" disguised as a mechanic-keyword event
        {"type": "pod", "event": "payment", "agent": "alice@test", "amount": 500,
         "timestamp": _ts(1)},
        # alice's real balance = 0; replay balance = 500 → escrow_create passes
        {"type": "escrow_create", "author": "alice@test", "amount": 400,
         "issue": 20, "timestamp": _ts(2)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        "BYPASS V3: 'pod'+'payment' shadow inflates alice's replay balance to 500 "
        "WEA; insolvent escrow_create for 400 WEA passes"
    )
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


@pytest.mark.parametrize("keyword", [
    "standard", "progressive", "best_x", "winner_take_all",
    "duel", "linear", "every_good", "wta", "every_accepted",
])
def test_v3_all_mechanic_keywords_can_shadow_payment(temp_repo: Path, keyword: str) -> None:
    """BYPASS: every mechanic keyword in ``_MECHANIC_KEYWORDS`` can shadow a payment.

    All nine keywords besides ``"pod"`` also fall through to ``event.get("event")``.
    This parametrised test confirms the inflation bypass works for each one.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": keyword, "event": "payment", "agent": "alice@test", "amount": 200,
         "timestamp": _ts(1)},
        {"type": "escrow_create", "author": "alice@test", "amount": 150,
         "issue": 21, "timestamp": _ts(2)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        f"BYPASS V3: mechanic keyword '{keyword}' + 'payment' shadow inflates "
        "alice's balance; insolvent escrow passes"
    )
    assert report["violations"] == []


# ── Bypass Vector 4: non-ISO-date filename sorts escrow_create to max_dt ──────


def test_v4_non_date_filename_escrow_sorts_after_dated_payment(temp_repo: Path) -> None:
    """BYPASS: ``escrow_create`` in a non-ISO-date-named file sorts to ``datetime.max``.

    ``_sort_key`` resolves the sort timestamp as:
        record.timestamp or _file_timestamp(path) or datetime.max

    ``_file_timestamp`` parses ``{stem}T00:00:00Z``; a file named ``misc.jsonl``
    yields stem ``"misc"`` which is not a valid ISO date → returns ``None``.
    The sort key becomes ``datetime.max``, placing the event after ALL dated events.

    Attack: alice has 0 WEA at escrow time; the payment arrives in a dated file
    AFTER the escrow in real time.  Placing the escrow in ``misc.jsonl`` (no explicit
    timestamp) causes the replay to process the payment first, inflating the visible
    balance and hiding the insolvency.

    | event              | file             | effective sort ts   | result      |
    |--------------------|------------------|---------------------|-------------|
    | payment(50)        | 2026-04-01.jsonl | 2026-04-01T00:00:00 | replayed 1st|
    | escrow_create(50)  | misc.jsonl       | datetime.max        | replayed 2nd|

    Severity: HIGH — a crafted history can reorder any escrow_create to appear
    after legitimising credits, concealing insolvency at creation time.
    """
    # Payment in a dated file (no explicit timestamp → file date used)
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50},
    ])
    # Insolvent escrow_create in a non-date-named file (no explicit timestamp → max_dt)
    _hist(temp_repo, "misc.jsonl", [
        {"type": "escrow_create", "author": "alice@test", "amount": 50, "issue": 30},
    ])

    report = run_check(temp_repo)

    # Real insolvency: alice had 0 WEA when escrow was created.
    # Replay insolvency: payment sorts before escrow → balance=50 at check time → PASS.
    assert report["status"] == "PASS", (
        "BYPASS V4: escrow_create in misc.jsonl sorts to datetime.max — replay "
        "processes dated payment first, concealing insolvency at creation time"
    )
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_v4_explicit_early_timestamp_in_misc_file_is_not_bypassed(temp_repo: Path) -> None:
    """Control: an explicit early timestamp in a non-date file IS correctly ordered.

    When ``misc.jsonl`` events carry an explicit timestamp earlier than the payment,
    the sort respects the explicit timestamp and replays the escrow_create first
    (while alice still has 0 WEA) → correctly reports FAIL.

    This confirms the bypass requires the absence of an explicit timestamp.
    """
    _hist(temp_repo, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "amount": 50,
         "timestamp": "2026-04-01T10:00:00Z"},
    ])
    _hist(temp_repo, "misc.jsonl", [
        # Explicit timestamp BEFORE the payment → sort places this first
        {"type": "escrow_create", "author": "alice@test", "amount": 50, "issue": 31,
         "timestamp": "2026-04-01T09:00:00Z"},
    ])

    report = run_check(temp_repo)

    # escrow sorts before payment → balance=0 at check → correctly FAIL
    assert report["status"] == "FAIL", (
        "explicit timestamp overrides filename sort; early escrow sees 0 balance"
    )
    assert len(report["violations"]) == 1
    assert report["violations"][0]["balance_before"] == 0


# ── Bypass Vector 5: ``escrow_batch`` not checked for solvency ────────────────


def test_v5_escrow_batch_insolvent_total_not_checked(temp_repo: Path) -> None:
    """BYPASS: ``escrow_batch`` debits balance without any solvency check.

    The ``escrow_batch`` branch unconditionally executes
    ``balances[author] -= total`` with no ``balance_before < total`` guard.
    A zero-balance agent can issue an arbitrarily large batch escrow; the
    checker never records a violation and returns ``status = "PASS"``.

    alice has 0 WEA; batch escrow total = 9 999 WEA.

    Severity: HIGH — a batch path equivalent to ``escrow_create`` evades all
    solvency enforcement; ``escrows_checked`` stays at 0.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_batch", "author": "alice@test", "total": 9999,
         "timestamp": _ts(1)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        "BYPASS V5: escrow_batch for 9999 WEA against a 0 WEA balance passes — "
        "no solvency check exists for escrow_batch events"
    )
    assert report["escrows_checked"] == 0
    assert report["violations"] == []


def test_v5_escrow_batch_after_escrow_create_also_unchecked(temp_repo: Path) -> None:
    """BYPASS: even when prior ``escrow_create`` events drain balance, batch is unchecked.

    alice has 50 WEA.  She legitimately creates an escrow_create for 50 WEA
    (balance → 0).  A subsequent escrow_batch for 100 WEA then occurs with
    balance = 0.  Only the escrow_create is checked; the batch passes silently.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "payment",      "agent":  "alice@test", "amount": 50,  "timestamp": _ts(1)},
        {"type": "escrow_create","author": "alice@test", "amount": 50,  "issue": 40,
         "timestamp": _ts(2)},
        {"type": "escrow_batch", "author": "alice@test", "total": 100,
         "timestamp": _ts(3)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        "BYPASS V5: escrow_batch for 100 WEA against 0 WEA balance is not checked; "
        "checker only counts the escrow_create"
    )
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


# ── Bypass Vector 6: ``agent_removal`` phantom ``balance_returned`` ───────────


def test_v6_agent_removal_phantom_balance_returned_inflates_agent0(temp_repo: Path) -> None:
    """BYPASS: ``agent_removal`` adds ``balance_returned`` to agent0 with no cross-check.

    The ``agent_removal`` branch sets the removed agent's balance to 0 and then
    adds ``event["balance_returned"]`` to ``balances[AGENT0]``.  There is no
    validation that the removed agent actually held that amount.

    A forged removal of a zero-balance (or non-existent) agent with an inflated
    ``balance_returned`` manufactures WEA for agent0.

    Without phantom removal: agent0 has 10 000 WEA (genesis); escrow for 55 000 fails.
    With phantom removal:    agent0 has 60 000 WEA; escrow for 55 000 passes.

    | event                                              | agent0 bal | result      |
    |----------------------------------------------------|------------|-------------|
    | agent_removal(ghost@test, balance_returned=50000) | 60 000     | inflated    |
    | escrow_create(agent0, amount=55000)                | 5 000      | PASS ← false|

    Severity: MEDIUM — requires the ability to inject an agent_removal event;
    enables agent0-authored escrows of arbitrary size to bypass solvency checks.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        # ghost@test does not exist in ledger; has 0 WEA.
        # balance_returned is fabricated — agent0 receives 50 000 phantom WEA.
        {"type": "agent_removal", "agent": "ghost@test",
         "balance_returned": 50000, "timestamp": _ts(1)},
        # agent0 genesis = 10 000; after phantom removal = 60 000.
        # escrow for 55 000 should fail (10 000 < 55 000) but passes.
        {"type": "escrow_create", "author": "agent0@system", "amount": 55000,
         "issue": 50, "timestamp": _ts(2)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS", (
        "BYPASS V6: phantom agent_removal inflates agent0 balance to 60 000; "
        "escrow_create for 55 000 WEA passes despite agent0 having only 10 000"
    )
    assert report["escrows_checked"] == 1
    assert report["violations"] == []


def test_v6_agent_removal_without_inflation_correctly_fails(temp_repo: Path) -> None:
    """Control: without a phantom removal, insolvent agent0 escrow is correctly caught.

    agent0 starts with 10 000 WEA (genesis).  An ``escrow_create`` for 55 000 WEA
    is correctly flagged as insolvent (10 000 < 55 000 → FAIL).

    This confirms the bypass requires the fabricated ``balance_returned`` field.
    """
    _hist(temp_repo, "2026-01-01.jsonl", [
        {"type": "escrow_create", "author": "agent0@system", "amount": 55000,
         "issue": 51, "timestamp": _ts(1)},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL", (
        "baseline: agent0 has 10 000 WEA; escrow for 55 000 is correctly insolvent"
    )
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["balance_before"] == 10000
    assert v["shortfall"] == 45000
