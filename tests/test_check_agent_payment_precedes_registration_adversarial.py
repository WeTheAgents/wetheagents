#!/usr/bin/env python3
"""Adversarial tests for scripts/check_agent_payment_precedes_registration.py.

Each test documents expected behavior and classifies the scenario as:
  DEFENDED  — the script handles it correctly
  KNOWN GAP — the script produces incorrect or unsafe results; document for future T1 slots
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_agent_payment_precedes_registration.py"
)


# ---------------------------------------------------------------------------
# Helpers (mirror the canonical test file's patterns)
# ---------------------------------------------------------------------------


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _report(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def _case_root(temp_repo: Path) -> Path:
    root = temp_repo / f"case_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in events]
    (history_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_raw(root: Path, filename: str, content: str) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / filename).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Adversarial: event-level timestamp fields are ignored — file date is canonical
# ---------------------------------------------------------------------------


def test_payment_ts_field_missing_file_date_is_canonical(temp_repo: Path) -> None:
    """DEFENDED: Payment event with no `timestamp` field still uses file date.

    The script uses the filename stem as the date, never parsing event-level
    timestamps. A payment event with no timestamp field is still correctly
    checked by file date ordering.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "registration", "agent": "Alice@test"},
    ])
    _write_history(root, "2026-04-06.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


def test_payment_ts_field_malformed_file_date_is_canonical(temp_repo: Path) -> None:
    """DEFENDED: Malformed event timestamps are ignored; file date is canonical.

    Even with garbage in the `timestamp` field, the script uses the filename
    stem. A payment before registration by file date is correctly caught.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [
        {
            "type": "payment",
            "agent": "Alice@test",
            "issue": 1,
            "amount": 10,
            "timestamp": "not-a-date",
        }
    ])
    _write_history(root, "2026-04-10.jsonl", [
        {"type": "registration", "agent": "Alice@test", "timestamp": "also-garbage"},
    ])

    result = _run(root)
    report = _report(result)

    # File dates: payment 2026-04-01 < registration 2026-04-10 → violation
    assert result.returncode == 1
    assert report["status"] == "fail"
    assert report["violations"][0]["agent"] == "Alice@test"
    assert report["violations"][0]["payment_date"] == "2026-04-01"
    assert report["violations"][0]["registration_date"] == "2026-04-10"


# ---------------------------------------------------------------------------
# Adversarial: agent ID case sensitivity — KNOWN GAP
# ---------------------------------------------------------------------------


def test_case_mismatch_registration_lower_payment_upper(temp_repo: Path) -> None:
    """KNOWN GAP: Agent IDs are compared case-sensitively; uppercase evades the check.

    Registration uses `alice@test`, payment uses `ALICE@TEST`. The script
    does not normalize case, so ALICE@TEST is treated as a distinct,
    unregistered agent and skipped. A pre-registration payment goes undetected.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-10.jsonl", [
        {"type": "registration", "agent": "alice@test"},
    ])
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "ALICE@TEST", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # GAP: ALICE@TEST not in reg_dates → skipped, violation missed
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


def test_case_mismatch_mixed_case_in_registration(temp_repo: Path) -> None:
    """KNOWN GAP: Mixed-case registration agent ID is not normalized.

    Registration uses `Alice@Test`, payment uses `alice@test`. These are
    treated as two distinct agents — payment is skipped as unregistered.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-10.jsonl", [
        {"type": "registration", "agent": "Alice@Test"},
    ])
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "payment", "agent": "alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # GAP: alice@test not in reg_dates (only Alice@Test is) → skipped
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


# ---------------------------------------------------------------------------
# Adversarial: future-dated and backdated registration files — KNOWN GAP
# ---------------------------------------------------------------------------


def test_future_dated_registration_file_creates_false_positive(temp_repo: Path) -> None:
    """KNOWN GAP: Registration in a future-dated file triggers a false-positive violation.

    The checker uses the filename stem as the registration date with no
    validation. A file named `2099-01-01.jsonl` sets reg_date to '2099-01-01'.
    Any payment before that date is flagged, even if the agent was legitimately
    registered years earlier (as shown by the event's own timestamp).
    """
    root = _case_root(temp_repo)
    _write_history(root, "2099-01-01.jsonl", [
        {"type": "registration", "agent": "Alice@test", "timestamp": "2026-04-01T00:00:00Z"},
    ])
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # GAP: False positive — payment_date 2026-04-05 < reg_date 2099-01-01
    assert result.returncode == 1
    assert report["status"] == "fail"
    v = report["violations"][0]
    assert v["registration_date"] == "2099-01-01"
    assert v["payment_date"] == "2026-04-05"


def test_backdated_registration_file_bypasses_check(temp_repo: Path) -> None:
    """KNOWN GAP: A registration in a backdated file bypasses the ordering check.

    A file named `2000-01-01.jsonl` sets reg_date to '2000-01-01' regardless
    of the event's own timestamp. This means placing a registration event in
    an early-dated file makes all subsequent payments appear valid, even if the
    actual registration was logged much later (as shown by the event timestamp).
    """
    root = _case_root(temp_repo)
    _write_history(root, "2000-01-01.jsonl", [
        {
            "type": "registration",
            "agent": "Alice@test",
            "timestamp": "2026-04-10T00:00:00Z",  # actual log time is 2026-04-10
        }
    ])
    # Payment on 2026-04-05 is before the real timestamp (2026-04-10) but after
    # the backdated file stem (2000-01-01).
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # GAP: payment_date '2026-04-05' > reg file_date '2000-01-01' → passes
    # even though the real event timestamp shows registration happened later
    assert result.returncode == 0
    assert report["status"] == "pass"


# ---------------------------------------------------------------------------
# Adversarial: duplicate registration events — DEFENDED
# ---------------------------------------------------------------------------


def test_two_registrations_same_agent_first_file_wins(temp_repo: Path) -> None:
    """DEFENDED: Two registration events for the same agent — first file date wins.

    `collect_registration_dates` skips an agent already in reg_dates. The
    earliest (chronologically sorted) file date is recorded; later duplicates
    are ignored.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [
        {"type": "registration", "agent": "Alice@test"},  # first → wins
    ])
    _write_history(root, "2026-04-10.jsonl", [
        {"type": "registration", "agent": "Alice@test"},  # duplicate → ignored
    ])
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # First reg date 2026-04-01, payment 2026-04-05 → pass
    assert result.returncode == 0
    assert report["status"] == "pass"


def test_two_registrations_same_agent_same_file_first_entry_wins(temp_repo: Path) -> None:
    """DEFENDED: Two registrations in the same file — first entry sets the date.

    Within a single file, the second registration for the same agent is
    a no-op because the agent is already in reg_dates.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "registration", "agent": "Alice@test"},
        {"type": "registration", "agent": "Alice@test"},  # duplicate, no-op
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Adversarial: midnight boundary — payment with same file date as registration
# ---------------------------------------------------------------------------


def test_midnight_boundary_payment_before_reg_in_file_same_date_passes(temp_repo: Path) -> None:
    """DEFENDED: Payment at midnight (same file date as registration) is allowed.

    The check is strict less-than (`file_date < reg_dates[agent]`). When both
    events share the same file date, the condition is False regardless of
    which event appears first in the file or what their timestamps say.
    The script's two-pass design (collect all regs, then check payments)
    means the registration is already known when the payment is checked.
    """
    root = _case_root(temp_repo)
    # Payment appears BEFORE registration in the file text, at midnight
    _write_history(root, "2026-04-05.jsonl", [
        {
            "type": "payment",
            "agent": "Alice@test",
            "issue": 1,
            "amount": 10,
            "timestamp": "2026-04-05T00:00:00Z",  # midnight
        },
        {
            "type": "registration",
            "agent": "Alice@test",
            "timestamp": "2026-04-05T12:00:00Z",  # noon, same calendar day
        },
    ])

    result = _run(root)
    report = _report(result)

    # DEFENDED: same file date → no violation even if payment ts < reg ts
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Adversarial: blank and whitespace-only JSONL files — DEFENDED
# ---------------------------------------------------------------------------


def test_blank_jsonl_file_no_events(temp_repo: Path) -> None:
    """DEFENDED: A blank (0-byte) JSONL file is handled gracefully.

    `_load_jsonl_events` strips and skips empty lines. An empty file produces
    zero events with no error.
    """
    root = _case_root(temp_repo)
    _write_raw(root, "2026-04-05.jsonl", "")

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0
    assert report["stats"]["agents_checked"] == 0


def test_whitespace_only_jsonl_file(temp_repo: Path) -> None:
    """DEFENDED: A file containing only whitespace and blank lines is handled.

    All lines fail the `if not raw` guard after strip() and are skipped.
    """
    root = _case_root(temp_repo)
    _write_raw(root, "2026-04-05.jsonl", "\n\n   \n\t\n")

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


# ---------------------------------------------------------------------------
# Adversarial: trajectory_mint to unregistered agent — DEFENDED by design
# ---------------------------------------------------------------------------


def test_trajectory_mint_unregistered_agent_skipped(temp_repo: Path) -> None:
    """DEFENDED: trajectory_mint to an unregistered agent is skipped by design.

    Per spec: only agents with a history registration event are checked.
    An agent listed in trajectory_mint with no registration event is not
    flagged, consistent with the handling of all other payment types.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {
            "type": "trajectory_mint",
            "agents": ["Ghost@test"],
            "per_agent": [50],
            "issue": 99,
        }
    ])

    result = _run(root)
    report = _report(result)

    # DEFENDED: Ghost@test not in reg_dates → skipped (design choice, not a bug)
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


# ---------------------------------------------------------------------------
# Adversarial: agent0@system has no registration event — DEFENDED by design
# ---------------------------------------------------------------------------


def test_agent0_system_payment_skipped_no_registration(temp_repo: Path) -> None:
    """DEFENDED: Payments to agent0@system are skipped (no registration event).

    agent0@system is the founding agent and has never had a history registration
    event logged. Per design, agents without a registration event are not
    checked — they may have been registered before event-logging began.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-01-01.jsonl", [
        {"type": "payment", "agent": "agent0@system", "issue": 1, "amount": 100},
    ])

    result = _run(root)
    report = _report(result)

    # DEFENDED: agent0@system not in reg_dates → skipped
    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


# ---------------------------------------------------------------------------
# Adversarial: large history performance guard
# ---------------------------------------------------------------------------


def test_large_history_performance_under_5_seconds(temp_repo: Path) -> None:
    """DEFENDED: 500+ event history completes in under 5 seconds.

    Generates 10 JSONL files: day 0 = 50 registrations, days 1-9 = 50 payments
    each (450 total payments). The checker must finish in < 5 seconds.
    """
    root = _case_root(temp_repo)
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    agents = [f"Agent{i}@test" for i in range(50)]
    for day_offset in range(10):
        date_str = f"2026-04-{day_offset + 1:02d}"
        events: list[dict] = []
        if day_offset == 0:
            for a in agents:
                events.append({"type": "registration", "agent": a})
        else:
            for a in agents:
                events.append({"type": "payment", "agent": a, "issue": day_offset, "amount": 1})
        lines = [json.dumps(e) for e in events]
        (history_dir / f"{date_str}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    start = time.monotonic()
    result = _run(root)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    report = _report(result)
    assert report["status"] == "pass"
    assert elapsed < 5.0, f"Performance regression: {elapsed:.2f}s >= 5s"
    # 50 agents × 9 payment days = 450 payment events
    assert report["stats"]["payments_checked"] == 450


# ---------------------------------------------------------------------------
# Adversarial: corrupt JSON lines in history — DEFENDED
# ---------------------------------------------------------------------------


def test_corrupt_json_lines_skipped_gracefully(temp_repo: Path) -> None:
    """DEFENDED: Malformed JSON lines are skipped; valid events are still processed.

    `_load_jsonl_events` catches JSONDecodeError and continues. Corrupt lines
    do not abort the scan or corrupt the results.
    """
    root = _case_root(temp_repo)
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    raw = "\n".join([
        '{"type": "registration", "agent": "Alice@test"}',
        "not valid json {{{",
        '{"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10}',
        "also bad ][",
    ]) + "\n"
    (history_dir / "2026-04-05.jsonl").write_text(raw, encoding="utf-8")

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Adversarial: non-date filename — KNOWN GAP
# ---------------------------------------------------------------------------


def test_non_date_filename_creates_invalid_date_comparison(temp_repo: Path) -> None:
    """KNOWN GAP: Non-date filename stems produce invalid date string comparisons.

    The script uses filename stems as date strings without validation.
    A file named `notes.jsonl` yields file_date = 'notes'. Python string
    comparison of '2026-04-05' < 'notes' is True (digits sort before letters
    in ASCII/Unicode), causing a false-positive violation for any agent
    registered in such a file and later paid on any real date.
    """
    root = _case_root(temp_repo)
    _write_history(root, "notes.jsonl", [
        {"type": "registration", "agent": "Alice@test"},
    ])
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    # GAP: '2026-04-05' < 'notes' → True → false positive violation
    assert result.returncode == 1
    assert report["status"] == "fail"
    assert report["violations"][0]["registration_date"] == "notes"
    assert report["violations"][0]["payment_date"] == "2026-04-05"


# ---------------------------------------------------------------------------
# Adversarial: registration_confirmed event type — DEFENDED
# ---------------------------------------------------------------------------


def test_registration_confirmed_event_type_accepted_as_registration(temp_repo: Path) -> None:
    """DEFENDED: `registration_confirmed` counts as a valid registration event.

    The script's _REGISTRATION_TYPES frozenset includes 'registration_confirmed'.
    An agent registered with this event type and paid afterward passes the check.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "registration_confirmed", "agent": "Alice@test"},
    ])
    _write_history(root, "2026-04-06.jsonl", [
        {"type": "payment", "agent": "Alice@test", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Adversarial: trajectory_mint per_agent shorter than agents — DEFENDED
# ---------------------------------------------------------------------------


def test_trajectory_mint_per_agent_shorter_than_agents_list(temp_repo: Path) -> None:
    """DEFENDED: per_agent shorter than agents list yields amount=None for extra agents.

    The script uses `per_agent[idx] if idx < len(per_agent) else None`.
    No IndexError is raised; the violation record includes amount=None for
    agents beyond the per_agent list boundary.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-10.jsonl", [
        {"type": "registration", "agent": "Alice@test"},
        {"type": "registration", "agent": "Bob@test"},
    ])
    _write_history(root, "2026-04-05.jsonl", [
        {
            "type": "trajectory_mint",
            "agents": ["Alice@test", "Bob@test"],
            "per_agent": [30],  # only one entry for two agents
            "issue": 7,
        }
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    violations = {v["agent"]: v for v in report["violations"]}
    assert violations["Alice@test"]["amount"] == 30
    assert violations["Bob@test"]["amount"] is None  # per_agent[1] missing → None


# ---------------------------------------------------------------------------
# Adversarial: agent field edge cases — DEFENDED
# ---------------------------------------------------------------------------


def test_payment_agent_field_empty_string_skipped(temp_repo: Path) -> None:
    """DEFENDED: Payment with empty agent field is skipped.

    `str(event.get('agent', '')).strip()` yields '' which is falsy.
    The `if not agent` guard skips it before any lookup.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": "", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


def test_payment_agent_field_null_skipped(temp_repo: Path) -> None:
    """DEFENDED: Payment with null agent field is skipped.

    `str(None)` = 'None' (truthy), but 'None' is not in reg_dates → skipped
    at the `agent not in reg_dates` guard. payments_checked is not incremented.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "payment", "agent": None, "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 0


def test_payment_agent_whitespace_stripped_before_lookup(temp_repo: Path) -> None:
    """DEFENDED: Agent ID with leading/trailing whitespace is stripped before lookup.

    Registration uses 'Alice@test' (clean). Payment uses ' Alice@test '
    (padded with spaces). After `.strip()`, both match — the payment is
    correctly counted and passes.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [
        {"type": "registration", "agent": "Alice@test"},
    ])
    _write_history(root, "2026-04-06.jsonl", [
        {"type": "payment", "agent": " Alice@test ", "issue": 1, "amount": 10},
    ])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1
