"""Tests for scripts/check_idem_key_completeness.py"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_idem_key_completeness import (
    classify_idem_keys,
    build_history_index,
    load_idem_keys,
    run_completeness_check,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_idem_keys(tmp_path: Path, keys: dict) -> Path:
    """Write an idem_keys.json under tmp_path/ledger/ and return its path."""
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    p = ledger / "idem_keys.json"
    p.write_text(json.dumps(keys), encoding="utf-8")
    return p


def write_history(tmp_path: Path, events: list[dict]) -> Path:
    """Write a single history/events.jsonl file and return the history dir."""
    history = tmp_path / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    f = history / "2026-01-01.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    return history


# ---------------------------------------------------------------------------
# load_idem_keys
# ---------------------------------------------------------------------------


def test_load_idem_keys_reads_nested_keys(tmp_path: Path) -> None:
    """Keys inside data['keys'] are loaded."""
    raw = {
        "version": 2,
        "keys": {
            "escrow|10|agent0@system": "2026-01-01T00:00:00Z",
            "trajectory_mint|T1|1": "2026-01-01T00:00:00Z",
        },
    }
    p = write_idem_keys(tmp_path, raw)
    result = load_idem_keys(p)

    assert "escrow|10|agent0@system" in result
    assert "trajectory_mint|T1|1" in result


def test_load_idem_keys_includes_top_level_financial_keys(tmp_path: Path) -> None:
    """Top-level financial keys (not inside data['keys']) are also loaded."""
    raw = {
        "version": 2,
        "keys": {"escrow|10|agent0@system": "2026-01-01T00:00:00Z"},
        # top-level key — old ledger code stored some keys here
        "payment|99|Claude-1@claude": "2026-01-01T00:00:00Z",
        "escrow|42": "2026-01-01T00:00:00Z",
    }
    p = write_idem_keys(tmp_path, raw)
    result = load_idem_keys(p)

    assert "payment|99|Claude-1@claude" in result
    assert "escrow|42" in result


def test_load_idem_keys_missing_file_returns_empty(tmp_path: Path) -> None:
    """Missing file returns empty dict without error."""
    p = tmp_path / "ledger" / "idem_keys.json"
    result = load_idem_keys(p)
    assert result == {}


# ---------------------------------------------------------------------------
# classify_idem_keys
# ---------------------------------------------------------------------------


def test_classify_idem_keys_trajectory_mint(tmp_path: Path) -> None:
    """trajectory_mint|T1|3 is classified under trajectory_mint lookup."""
    keys = {
        "trajectory_mint|T1|3": "2026-01-01T00:00:00Z",
        "trajectory_mint|T6|12": "2026-01-01T00:00:00Z",
    }
    classified = classify_idem_keys(keys, aliases={})

    tm = classified["trajectory_mint"]
    assert ("T1", "3") in tm
    assert ("T6", "12") in tm


def test_classify_idem_keys_escrow_two_and_three_part(tmp_path: Path) -> None:
    """Both escrow|N and escrow|N|agent are classified under 'escrow'."""
    keys = {
        "escrow|7": "2026-01-01T00:00:00Z",               # 2-part
        "escrow|9|agent0@system": "2026-01-01T00:00:00Z", # 3-part
    }
    classified = classify_idem_keys(keys, aliases={})

    escrow = classified["escrow"]
    assert "7" in escrow
    assert "9" in escrow


def test_classify_idem_keys_payment_hash(tmp_path: Path) -> None:
    """SHA256 hash keys with action=payment land in payment_hash."""
    keys = {
        "abc123": {
            "action": "payment",
            "issue": "200",
            "agent": "Claude-9@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    }
    classified = classify_idem_keys(keys, aliases={})

    ph = classified["payment_hash"]
    assert ("200", "Claude-9@claude") in ph
    assert ph[("200", "Claude-9@claude")] == ["abc123"]


# ---------------------------------------------------------------------------
# Violations: trajectory_mint
# ---------------------------------------------------------------------------


def test_trajectory_mint_violation_when_key_missing(tmp_path: Path) -> None:
    """trajectory_mint event without idem key → VIOLATION."""
    events = [
        {"type": "trajectory_mint", "trajectory": "T2", "slot": 5, "timestamp": "2026-01-01T00:00:00Z"}
    ]
    # No trajectory_mint keys present
    all_keys: dict = {}

    violations, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    v = violations[0]
    assert v["event_type"] == "trajectory_mint"
    assert v["trajectory"] == "T2"
    assert v["slot"] == "5"
    assert "trajectory_mint|T2|5" in v["detail"]


def test_trajectory_mint_no_violation_when_key_present(tmp_path: Path) -> None:
    """trajectory_mint event with matching idem key → no VIOLATION."""
    events = [
        {"type": "trajectory_mint", "trajectory": "T1", "slot": 3, "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys = {"trajectory_mint|T1|3": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


# ---------------------------------------------------------------------------
# Violations: payment
# ---------------------------------------------------------------------------


def test_payment_violation_when_no_idem_key(tmp_path: Path) -> None:
    """payment event with no matching idem key → VIOLATION."""
    events = [
        {"type": "payment", "issue": 55, "agent": "Claude-1@claude", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys: dict = {}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    v = violations[0]
    assert v["event_type"] == "payment"
    assert v["issue"] == "55"
    assert v["actor"] == "Claude-1@claude"


def test_payment_no_violation_covered_by_hash_key(tmp_path: Path) -> None:
    """payment event covered by a hash-based idem key → no VIOLATION."""
    events = [
        {"type": "payment", "issue": 200, "agent": "Claude-9@claude", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys = {
        "deadbeef": {
            "action": "payment",
            "issue": "200",
            "agent": "Claude-9@claude",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    }

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


def test_payment_no_violation_covered_by_string_key(tmp_path: Path) -> None:
    """payment event covered by a string idem key → no VIOLATION."""
    events = [
        {"type": "payment", "issue": 109, "agent": "Codex-2@codex", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys = {
        "payment|109|Codex-2@codex|ranking|1": "2026-03-09T06:05:36Z",
    }

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


# ---------------------------------------------------------------------------
# Violations: escrow
# ---------------------------------------------------------------------------


def test_escrow_violation_when_key_missing(tmp_path: Path) -> None:
    """escrow event with no idem key → VIOLATION."""
    events = [
        {"type": "escrow", "issue": 77, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys: dict = {}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    assert violations[0]["event_type"] == "escrow"
    assert violations[0]["issue"] == "77"


def test_escrow_covered_by_two_part_key(tmp_path: Path) -> None:
    """escrow event matched by escrow|N (2-part key) → no VIOLATION."""
    events = [
        {"type": "escrow", "issue": 42, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys = {"escrow|42": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


# ---------------------------------------------------------------------------
# Violations: escrow_return
# ---------------------------------------------------------------------------


def test_escrow_return_violation_when_key_missing(tmp_path: Path) -> None:
    """escrow_return event with no idem key → VIOLATION."""
    events = [
        {"type": "escrow_return", "issue": 107, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys: dict = {}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert len(violations) == 1
    assert violations[0]["event_type"] == "escrow_return"
    assert "escrow_return|107" in violations[0]["detail"]


def test_escrow_return_no_violation_three_part_key(tmp_path: Path) -> None:
    """escrow_return event covered by escrow_return|N|agent (3-part key)."""
    events = [
        {"type": "escrow_return", "issue": 7, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    all_keys = {"escrow_return|7|agent0@system": "2026-03-04T09:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


# ---------------------------------------------------------------------------
# Warnings: orphan idem keys
# ---------------------------------------------------------------------------


def test_orphan_escrow_key_generates_warning(tmp_path: Path) -> None:
    """An escrow idem key with no matching history event → WARNING."""
    all_keys = {"escrow|999|agent0@system": "2026-01-01T00:00:00Z"}
    events: list[dict] = []  # no escrow events

    _, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(warnings) == 1
    w = warnings[0]
    assert w["idem_key"] == "escrow|999|agent0@system"
    assert w["namespace"] == "escrow"
    assert "999" in w["detail"]


def test_orphan_trajectory_mint_key_generates_warning(tmp_path: Path) -> None:
    """trajectory_mint idem key with no matching history event → WARNING."""
    all_keys = {"trajectory_mint|T3|99": "2026-01-01T00:00:00Z"}
    events: list[dict] = []

    _, warnings = run_completeness_check(all_keys, events, aliases={})

    assert len(warnings) == 1
    assert warnings[0]["namespace"] == "trajectory_mint"
    assert "T3" in warnings[0]["detail"]


# ---------------------------------------------------------------------------
# escrow_batch expansion
# ---------------------------------------------------------------------------


def test_escrow_key_covered_by_escrow_batch(tmp_path: Path) -> None:
    """escrow idem key is covered by an escrow_batch event → no WARNING."""
    all_keys = {
        "escrow|4|agent0@system": "2026-03-03T16:00:00Z",
        "escrow|5|agent0@system": "2026-03-03T16:00:00Z",
    }
    # escrow_batch expands to individual issues
    events = [
        {
            "type": "escrow_batch",
            "author": "agent0@system",
            "issues": [4, 5, 6, 7],
            "timestamp": "2026-03-03T16:00:00Z",
        }
    ]

    _, warnings = run_completeness_check(all_keys, events, aliases={})

    # issues 4 and 5 are in the batch — no warnings for those
    assert not any("issue=4" in w["detail"] or "issue=5" in w["detail"] for w in warnings)


# ---------------------------------------------------------------------------
# Agent aliases
# ---------------------------------------------------------------------------


def test_payment_matched_via_agent_alias(tmp_path: Path) -> None:
    """Payment to an aliased agent is matched when alias resolves the name."""
    # Old name "OldCursor@cursor" is aliased to "cursor-3@cursor"
    aliases = {"OldCursor@cursor": "cursor-3@cursor"}
    events = [
        {"type": "payment", "issue": 70, "agent": "OldCursor@cursor", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    # idem key uses the canonical name
    all_keys = {
        "deadbeef": {
            "action": "payment",
            "issue": "70",
            "agent": "cursor-3@cursor",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    }

    violations, _ = run_completeness_check(all_keys, events, aliases)

    assert violations == []


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


def test_main_passes_on_clean_repo(tmp_path: Path) -> None:
    """main() exits 0 and outputs PASS JSON when all events are covered."""
    # Build minimal clean repo
    events = [
        {"type": "escrow", "issue": 10, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"},
        {"type": "payment", "issue": 10, "agent": "Claude-1@claude", "timestamp": "2026-01-01T00:01:00Z"},
        {"type": "trajectory_mint", "trajectory": "T1", "slot": 1, "timestamp": "2026-01-01T00:02:00Z"},
        {"type": "escrow_return", "issue": 10, "author": "agent0@system", "timestamp": "2026-01-01T00:03:00Z"},
    ]
    write_history(tmp_path, events)
    write_idem_keys(tmp_path, {
        "version": 2,
        "keys": {
            "escrow|10|agent0@system": "2026-01-01T00:00:00Z",
            "deadbeef": {"action": "payment", "issue": "10", "agent": "Claude-1@claude", "timestamp": "2026-01-01T00:01:00Z"},
            "trajectory_mint|T1|1": "2026-01-01T00:02:00Z",
            "escrow_return|10|agent0@system": "2026-01-01T00:03:00Z",
        },
    })

    exit_code = main(["--root", str(tmp_path)])

    assert exit_code == 0


def test_escrow_create_treated_as_escrow(tmp_path: Path) -> None:
    """escrow_create history event is treated identically to escrow."""
    events = [
        {"type": "escrow_create", "issue": 88, "author": "agent0@system", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    # Key uses 'escrow' prefix — must still match escrow_create events
    all_keys = {"escrow|88|agent0@system": "2026-01-01T00:00:00Z"}

    violations, _ = run_completeness_check(all_keys, events, aliases={})

    assert violations == []


def test_escrow_return_bulk_covers_idem_keys(tmp_path: Path) -> None:
    """escrow_return_bulk event suppresses WARNING for each covered issue."""
    all_keys = {
        "escrow_return|55|agent0@system": "2026-01-01T00:00:00Z",
        "escrow_return|56|agent0@system": "2026-01-01T00:00:00Z",
    }
    events = [
        {
            "type": "escrow_return_bulk",
            "author": "agent0@system",
            "issues": [55, 56],
            "timestamp": "2026-01-01T00:00:00Z",
        }
    ]

    _, warnings = run_completeness_check(all_keys, events, aliases={})

    # Both issues covered by the bulk return — no warnings
    assert not any("issue=55" in w["detail"] or "issue=56" in w["detail"] for w in warnings)


def test_main_fails_on_violation(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """main() exits 1 and JSON shows FAIL when a payment has no idem key."""
    events = [
        {"type": "payment", "issue": 55, "agent": "Claude-1@claude", "timestamp": "2026-01-01T00:00:00Z"}
    ]
    write_history(tmp_path, events)
    write_idem_keys(tmp_path, {"version": 2, "keys": {}})

    exit_code = main(["--root", str(tmp_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "FAIL"
    assert report["summary"]["violations"] == 1
    v = report["violations"][0]
    assert v["event_type"] == "payment"
    assert v["issue"] == "55"
