"""Tests for scripts/check_history_event_type_schema.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_history_event_type_schema import build_report, _check_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "ledger" / "history").mkdir(parents=True)
    return tmp_path


def _write_jsonl(history_dir: Path, filename: str, entries: list[dict]) -> None:
    (history_dir / filename).write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def _write_raw(history_dir: Path, filename: str, content: str) -> None:
    (history_dir / filename).write_text(content, encoding="utf-8")


def _run(tmp_path: Path) -> dict:
    return build_report(tmp_path)


def _violations(report: dict) -> list[dict]:
    return report["violations"]


def _pass(report: dict) -> bool:
    return report["status"] == "pass"


# ---------------------------------------------------------------------------
# 1. Valid payment passes
# ---------------------------------------------------------------------------

def test_valid_payment_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "Claude-1@claude", "amount": 10,
         "issue": 42, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert _pass(report)
    assert _violations(report) == []


# ---------------------------------------------------------------------------
# 2. Valid escrow_create passes
# ---------------------------------------------------------------------------

def test_valid_escrow_create_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_create", "author": "agent0@system", "amount": 20,
         "issue": 5, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 3. Valid escrow_return (amount=0) passes
# ---------------------------------------------------------------------------

def test_valid_escrow_return_zero_amount_passes(tmp_path: Path) -> None:
    """Amount=0 is valid for escrow_return (reconciliation events)."""
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_return", "agent": "agent0@system", "amount": 0,
         "issue": 22, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 4. Valid trajectory_mint passes
# ---------------------------------------------------------------------------

def test_valid_trajectory_mint_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "trajectory_mint", "trajectory": "T1", "slot": 5,
         "amount": 24, "agents": ["Claude-1@claude"], "issue": 300,
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 5. Valid registration passes
# ---------------------------------------------------------------------------

def test_valid_registration_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "registration", "agent": "Claude-1@claude",
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 6. Missing required field — payment missing amount
# ---------------------------------------------------------------------------

def test_payment_missing_amount_fails(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "Claude-1@claude", "issue": 1,
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    v = _violations(report)
    assert len(v) == 1
    assert "amount" in v[0]["missing_fields"]


# ---------------------------------------------------------------------------
# 7. Missing required field — escrow_create missing creator
# ---------------------------------------------------------------------------

def test_escrow_create_missing_from_fails(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_create", "amount": 10, "issue": 3,
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "from" in _violations(report)[0]["missing_fields"]


# ---------------------------------------------------------------------------
# 8. Bad field type — amount is string instead of int
# ---------------------------------------------------------------------------

def test_payment_amount_string_is_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": "ten",
         "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    v = _violations(report)
    assert "amount" in v[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 9. Missing ts (no timestamp alias at all)
# ---------------------------------------------------------------------------

def test_missing_ts_fails(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": 5, "issue": 1},
    ])
    report = _run(root)
    assert not _pass(report)
    v = _violations(report)
    assert "ts" in v[0]["missing_fields"]


# ---------------------------------------------------------------------------
# 10. Missing type field
# ---------------------------------------------------------------------------

def test_missing_type_field_fails(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"agent": "A@x", "amount": 5, "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "type" in _violations(report)[0]["missing_fields"]


# ---------------------------------------------------------------------------
# 11. Unknown type — warning only (status pass)
# ---------------------------------------------------------------------------

def test_unknown_type_is_pass(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "future_event", "data": "x", "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert _pass(report)
    assert report["stats"]["unknown_types"] == 1
    assert _violations(report) == []


# ---------------------------------------------------------------------------
# 12. Empty history dir — pass
# ---------------------------------------------------------------------------

def test_empty_history_passes(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    report = _run(root)
    assert _pass(report)
    assert report["stats"]["events_checked"] == 0


# ---------------------------------------------------------------------------
# 13. Corrupt JSONL line — skipped, not counted in events_checked
# ---------------------------------------------------------------------------

def test_corrupt_jsonl_line_skipped(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    history_dir = root / "ledger" / "history"
    _write_raw(history_dir, "2026-01-01.jsonl",
               'NOT_JSON\n'
               '{"type": "payment", "agent": "A@x", "amount": 1, "issue": 1, "timestamp": "2026-01-01T00:00:00Z"}\n')
    report = _run(root)
    assert _pass(report)
    assert report["stats"]["events_checked"] == 1  # corrupt line not counted


# ---------------------------------------------------------------------------
# 14. trajectory_mint with invalid trajectory value fails
# ---------------------------------------------------------------------------

def test_trajectory_mint_invalid_trajectory_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "trajectory_mint", "trajectory": "T9", "slot": 1,
         "amount": 20, "agents": ["A@x"], "issue": 100,
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "trajectory" in _violations(report)[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 15. trajectory_mint with slot=0 is bad field
# ---------------------------------------------------------------------------

def test_trajectory_mint_zero_slot_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "trajectory_mint", "trajectory": "T2", "slot": 0,
         "amount": 20, "agents": ["A@x"], "issue": 100,
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "slot" in _violations(report)[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 16. Field aliases — "from" accepted for escrow_create creator
# ---------------------------------------------------------------------------

def test_escrow_create_from_alias_accepted(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_create", "from": "agent0@system", "amount": 15,
         "issue": 7, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 17. Field aliases — "recipient" accepted for escrow_return recipient
# ---------------------------------------------------------------------------

def test_escrow_return_recipient_alias_accepted(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_return", "recipient": "agent0@system", "amount": 10,
         "issue": 8, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 18. Field aliases — "created_at" accepted as timestamp
# ---------------------------------------------------------------------------

def test_created_at_alias_accepted(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "accept", "agent": "A@x", "amount": 5,
         "issue": 2, "created_at": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 19. "event" alias for "type" field is accepted
# ---------------------------------------------------------------------------

def test_event_alias_for_type_accepted(tmp_path: Path) -> None:
    """Legacy events using 'event' instead of 'type' pass validation."""
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"event": "escrow_return", "agent": "agent0@system", "amount": 5,
         "issue": 9, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 20. payment amount > 0 enforced — amount=0 payment fails
# ---------------------------------------------------------------------------

def test_payment_zero_amount_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": 0,
         "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "amount" in _violations(report)[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 21. registration — agent_id alias accepted
# ---------------------------------------------------------------------------

def test_registration_agent_id_alias_accepted(tmp_path: Path) -> None:
    """registration event using agent_id instead of agent passes."""
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "registration", "agent_id": "Claude-5@claude",
         "timestamp": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))


# ---------------------------------------------------------------------------
# 22. output structure — stats keys present
# ---------------------------------------------------------------------------

def test_output_has_required_stats_keys(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": 1,
         "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert "status" in report
    assert "violations" in report
    assert "stats" in report
    stats = report["stats"]
    assert "events_checked" in stats
    assert "violations_found" in stats
    assert "unknown_types" in stats


# ---------------------------------------------------------------------------
# 23. idem_key present but empty string is bad field
# ---------------------------------------------------------------------------

def test_idem_key_empty_string_is_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": 5, "issue": 1,
         "idem_key": "   ", "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "idem_key" in _violations(report)[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 24. escrow_return negative amount is bad field
# ---------------------------------------------------------------------------

def test_escrow_return_negative_amount_bad_field(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"type": "escrow_return", "agent": "agent0@system", "amount": -5,
         "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    report = _run(root)
    assert not _pass(report)
    assert "amount" in _violations(report)[0]["bad_fields"]


# ---------------------------------------------------------------------------
# 25. "op" alias for "type" field is accepted
# ---------------------------------------------------------------------------

def test_op_alias_for_type_accepted(tmp_path: Path) -> None:
    """Legacy events using 'op' instead of 'type' pass validation."""
    root = _make_repo(tmp_path)
    _write_jsonl(root / "ledger" / "history", "2026-01-01.jsonl", [
        {"op": "escrow_create", "from": "agent0@system", "amount": 10,
         "issue": 5, "ts": "2026-01-01T00:00:00Z"},
    ])
    assert _pass(_run(root))
