"""Adversarial tests for check_payment_amount_matches_escrow.

Each test targets a specific bypass scenario, edge case, or implementation
boundary that the basic test suite does not cover. Tests that document known
bypass vectors assert the script's actual (permissive) behaviour so that any
future fix is immediately visible as a test failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_payment_amount_matches_escrow import run_check


def _write_jsonl(path: Path, events: list[dict | str | int]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_root(root: Path, events_by_file: dict[str, list[dict | str | int]]) -> Path:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for filename, events in events_by_file.items():
        _write_jsonl(history_dir / filename, events)
    return root


# ── 1. Split payment bypass ───────────────────────────────────────────────────


def test_split_payment_bypass_each_under_but_total_over(temp_repo: Path) -> None:
    """Two payments each individually ≤ escrow, but their sum exceeds it."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
            {"type": "payment", "issue": 42, "amount": 20, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 15, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["issue"] == "42"
    assert v["escrow_amount"] == 30
    assert v["payment_amount"] == 35  # total, not single
    assert v["delta"] == 5


# ── 2. Case / leading-zero key mismatch ──────────────────────────────────────


def test_case_manipulation_leading_zero_creates_key_mismatch(temp_repo: Path) -> None:
    """Escrow for string '042' vs payment for int 42 normalises differently.

    _normalize_issue('042') == '042'; _normalize_issue(42) == '42'.
    The escrow does not cover the payment — flagged as missing escrow.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": "042", "amount": 30},
            {"type": "payment", "issue": 42, "amount": 25, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    issues_in_violations = {v["issue"] for v in report["violations"]}
    assert "42" in issues_in_violations   # payment flagged as missing escrow
    assert "042" not in issues_in_violations  # escrow-only issue is not flagged


# ── 3. Escrow-return-then-payment bypass vector ───────────────────────────────


def test_escrow_return_then_payment_is_bypass_vector(temp_repo: Path) -> None:
    """escrow_return events are ignored; the returned escrow still authorises payments.

    Bypass: after escrow is returned, a subsequent payment should be flagged but
    the script does not subtract returned escrow amounts — payment passes unchallenged.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
            {"type": "escrow_return", "issue": 42, "amount": 30},
            {"type": "payment", "issue": 42, "amount": 25, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    # Script ignores escrow_return — original escrow still covers the payment
    assert report["status"] == "PASS"
    assert report["violations"] == []


# ── 4. Legacy batch bypass: excessive payment for batch-only issue ────────────


def test_legacy_batch_bypass_excessive_payment_undetected(temp_repo: Path) -> None:
    """Payments for batch-only issues skip amount validation entirely.

    Any amount — even a wildly excessive one — passes because batch-only
    issues carry no per-issue escrow amount to validate against.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_batch", "issues": [42], "total": 10},
            {"type": "payment", "issue": 42, "amount": 9999, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["skipped_batch_only_issues"] == 1


# ── 5. Zero-amount escrow — any positive payment is a violation ───────────────


def test_zero_amount_escrow_any_payment_is_violation(temp_repo: Path) -> None:
    """escrow_create with amount=0 is valid; any positive payment exceeds it."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 0},
            {"type": "payment", "issue": 42, "amount": 1, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["escrow_amount"] == 0
    assert report["violations"][0]["payment_amount"] == 1
    assert report["violations"][0]["delta"] == 1


# ── 6. Negative payment gracefully skipped ───────────────────────────────────


def test_negative_payment_amount_gracefully_skipped(temp_repo: Path) -> None:
    """Negative payment amounts are rejected as malformed — no crash, no false violation."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": -5, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["payment_events_scanned"] == 1
    assert report["stats"]["skipped_malformed_payments"] == 1


# ── 7. Payment missing issue field ───────────────────────────────────────────


def test_payment_missing_issue_field_gracefully_skipped(temp_repo: Path) -> None:
    """Payment event with no 'issue' key is skipped as malformed — no crash."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "amount": 10, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["payment_events_scanned"] == 1
    assert report["stats"]["skipped_malformed_payments"] == 1


# ── 8. Multi-issue: only one violates, others must not be false positives ──────


def test_multi_issue_only_one_violates_no_false_positives(temp_repo: Path) -> None:
    """Three issues — only issue 55 overpays; issues 10 and 99 must be clean."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 10, "amount": 20},
            {"type": "escrow_create", "issue": 55, "amount": 10},
            {"type": "escrow_create", "issue": 99, "amount": 50},
            {"type": "payment", "issue": 10, "amount": 15, "agent": "alice@test"},
            {"type": "payment", "issue": 55, "amount": 12, "agent": "alice@test"},
            {"type": "payment", "issue": 99, "amount": 40, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == "55"


# ── 9. Whitespace agent ID — violation still detected ────────────────────────


def test_whitespace_agent_id_does_not_mask_violation(temp_repo: Path) -> None:
    """Agent with leading/trailing whitespace does not suppress violation detection."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": 42, "amount": 15, "agent": "  alice@test  "},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["delta"] == 5


# ── 10. Two escrow_create events accumulate (not override) ────────────────────


def test_two_escrow_creates_same_issue_accumulate_not_override(temp_repo: Path) -> None:
    """Second escrow_create for the same issue adds to, not replaces, the first."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "escrow_create", "issue": 42, "amount": 15},
            # total escrow = 25; payment = 20 should PASS
            {"type": "payment", "issue": 42, "amount": 20, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["escrow_create_events_scanned"] == 2


def test_two_escrow_creates_accumulated_total_is_enforced(temp_repo: Path) -> None:
    """A payment exceeding the accumulated sum of two escrow_create events is flagged."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "escrow_create", "issue": 42, "amount": 15},
            # total escrow = 25; payment = 26 should FAIL with delta=1
            {"type": "payment", "issue": 42, "amount": 26, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["escrow_amount"] == 25
    assert report["violations"][0]["delta"] == 1


# ── 11. Payment appears before escrow_create in the same file ─────────────────


def test_payment_before_escrow_same_file_same_timestamp_correct(temp_repo: Path) -> None:
    """Event ordering within a file does not affect correctness.

    Payment event (ts=T) precedes escrow_create (ts=T) in the JSONL.
    Violation check runs after all events are accumulated, so order is irrelevant.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 42, "amount": 25, "agent": "alice@test",
             "ts": "2026-04-01T10:00:00Z"},
            {"type": "escrow_create", "issue": 42, "amount": 30,
             "ts": "2026-04-01T10:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


# ── 12. Payment exactly at escrow boundary ────────────────────────────────────


def test_payment_exact_at_escrow_boundary_passes(temp_repo: Path) -> None:
    """Boundary: payment == escrow (30 == 30) is not a violation."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
            {"type": "payment", "issue": 42, "amount": 30, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


# ── 13. Payment 1 WEA over escrow boundary ────────────────────────────────────


def test_payment_one_over_boundary_fails_with_delta_one(temp_repo: Path) -> None:
    """Off-by-one: payment = escrow + 1 is a violation with delta exactly 1."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
            {"type": "payment", "issue": 42, "amount": 31, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["delta"] == 1


# ── 14. Escrow-only, no payment ───────────────────────────────────────────────


def test_escrow_only_no_payment_produces_no_violation(temp_repo: Path) -> None:
    """Escrow created but never paid — no false positive, exits PASS."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["payment_events_scanned"] == 0


# ── 15. Corrupt JSONL line in the middle ─────────────────────────────────────


def test_corrupt_jsonl_in_middle_does_not_crash(temp_repo: Path) -> None:
    """Malformed JSON line sandwiched between valid events must not crash the script."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            "this is not valid json {{{",
            {"type": "payment", "issue": 42, "amount": 10, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["skipped_invalid_json_lines"] == 1


# ── 16. trajectory_mint not counted as payment ───────────────────────────────


def test_trajectory_mint_not_counted_as_payment(temp_repo: Path) -> None:
    """trajectory_mint events are not treated as payments — ignored completely."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "trajectory_mint", "issue": 42, "amount": 50, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 10, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["payment_events_scanned"] == 1


# ── 17. WTA: two full payments from same escrow exceed total ─────────────────


def test_wta_two_full_payments_same_escrow_exceeds_total(temp_repo: Path) -> None:
    """Winner-take-all variant: each of two payments matches escrow, total is 2x.

    max_payment == escrow_amount (not >), so individual-payment check passes.
    Total-paid check catches the combined overpayment.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
            {"type": "payment", "issue": 42, "amount": 30, "agent": "alice@test"},
            {"type": "payment", "issue": 42, "amount": 30, "agent": "bob@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    v = report["violations"][0]
    assert v["escrow_amount"] == 30
    assert v["payment_amount"] == 60  # total_paid, not single
    assert v["delta"] == 30


# ── 18. Payment with null issue field ────────────────────────────────────────


def test_payment_null_issue_field_gracefully_skipped(temp_repo: Path) -> None:
    """Payment with issue=null is skipped as malformed — no crash, no phantom violation."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10},
            {"type": "payment", "issue": None, "amount": 5, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["stats"]["skipped_malformed_payments"] == 1


# ── 19. Boolean escrow amount treated as malformed ───────────────────────────


def test_bool_escrow_amount_treated_as_malformed_not_as_one(temp_repo: Path) -> None:
    """escrow_create with amount=True must be rejected (bool subclasses int in Python).

    _numeric_amount explicitly guards against bool — True is not treated as 1.
    With the escrow skipped, the subsequent payment becomes a missing-escrow violation.
    """
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": True},
            {"type": "payment", "issue": 42, "amount": 1, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["skipped_malformed_escrows"] == 1
    assert report["violations"][0]["escrow_amount"] == 0


# ── 20. Float amounts — exact boundary and one-unit over ─────────────────────


def test_float_escrow_exact_boundary_passes(temp_repo: Path) -> None:
    """Float escrow with payment at exact float value is not a violation."""
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 10.5},
            {"type": "payment", "issue": 42, "amount": 10.5, "agent": "alice@test"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_float_escrow_fractional_overage_fails(tmp_path: Path) -> None:
    """Float payment 0.1 above float escrow is a violation."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    _write_jsonl(history_dir / "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 99, "amount": 10.5},
        {"type": "payment", "issue": 99, "amount": 10.6, "agent": "bob@test"},
    ])

    report = run_check(tmp_path)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["delta"] > 0


# ── 21. Escrow in one file, payment in another ────────────────────────────────


def test_cross_file_escrow_and_payment_aggregated(temp_repo: Path) -> None:
    """Escrow in an earlier JSONL file and payment in a later one are correctly joined."""
    root = _make_root(temp_repo, {
        "2026-03-01.jsonl": [
            {"type": "escrow_create", "issue": 42, "amount": 30},
        ],
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 42, "amount": 35, "agent": "alice@test"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["stats"]["history_files_scanned"] == 2
    assert report["violations"][0]["delta"] == 5


# ── 22. Empty JSONL file alongside a valid file ───────────────────────────────


def test_empty_jsonl_file_does_not_crash(temp_repo: Path) -> None:
    """An empty JSONL file in the history directory must not crash the script."""
    history_dir = temp_repo / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-03-01.jsonl").write_text("", encoding="utf-8")
    _write_jsonl(history_dir / "2026-04-01.jsonl", [
        {"type": "escrow_create", "issue": 42, "amount": 10},
        {"type": "payment", "issue": 42, "amount": 10, "agent": "alice@test"},
    ])

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["history_files_scanned"] == 2
