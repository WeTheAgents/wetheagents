"""Tests for scripts/check_gauntlet_founding_escrow_consistency.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_gauntlet_founding_escrow_consistency import (  # noqa: E402
    LEGACY_CUTOFF,
    main,
    run_check,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_TRAJ_MINTS_TEMPLATE: dict = {
    "version": 1,
    "total_minted": 0,
    "trajectories": {
        t: {"name": t, "next_slot": 1, "total_minted": 0}
        for t in ("T1", "T2", "T3", "T4", "T5", "T6")
    },
    "mints": [],
}


def _write_mints(root: Path, mints: list[dict]) -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    payload = {**_TRAJ_MINTS_TEMPLATE, "mints": mints}
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _write_history(root: Path, events: list[dict]) -> None:
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(ev) for ev in events)
    (history / "2026-01-01.jsonl").write_text(lines + "\n", encoding="utf-8")


def _mint(trajectory: str, slot: int, issue: int) -> dict:
    return {"trajectory": trajectory, "slot": slot, "issue_or_pr": f"#{issue}"}


def _escrow_create(issue: int, slot: int) -> dict:
    return {
        "type": "escrow_create",
        "issue": issue,
        "amount": 19 + slot,
        "author": "agent0@system",
        "idem_key": f"escrow_create_gauntlet|{issue}",
    }


def _escrow_return(issue: int, slot: int) -> dict:
    return {
        "type": "escrow_return",
        "issue": issue,
        "amount": 19 + slot,
        "recipient": "agent0@system",
        "idem_key": f"escrow-return-{issue}",
    }


# Issue numbers safely above LEGACY_CUTOFF to ensure checks always run
_ISSUE_A = LEGACY_CUTOFF + 101  # 701
_ISSUE_B = LEGACY_CUTOFF + 102  # 702
_ISSUE_C = LEGACY_CUTOFF + 103  # 703
_SLOT_A = 30
_SLOT_B = 31
_SLOT_C = 32


# ---------------------------------------------------------------------------
# Acceptance-criteria tests
# ---------------------------------------------------------------------------


def test_all_mints_valid_passes(tmp_path: Path) -> None:
    """All mints have founding escrow + return → PASS, no failures or warnings."""
    mints = [
        _mint("T1", _SLOT_A, _ISSUE_A),
        _mint("T2", _SLOT_B, _ISSUE_B),
    ]
    events = [
        _escrow_create(_ISSUE_A, _SLOT_A),
        _escrow_return(_ISSUE_A, _SLOT_A),
        _escrow_create(_ISSUE_B, _SLOT_B),
        _escrow_return(_ISSUE_B, _SLOT_B),
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert result["warnings"] == []
    assert result["summary"]["checked"] == 2
    assert result["summary"]["failures"] == 0


def test_missing_escrow_create_fails(tmp_path: Path) -> None:
    """Mint present but no escrow_create in history → status FAIL."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, [])  # no escrow events at all

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["type"] == "missing_escrow_create"
    assert result["failures"][0]["issue"] == _ISSUE_A


def test_dangling_escrow_fails(tmp_path: Path) -> None:
    """escrow_create present but no return or consumption → status FAIL."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    events = [_escrow_create(_ISSUE_A, _SLOT_A)]  # no escrow_return
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["type"] == "dangling_escrow"
    assert result["failures"][0]["issue"] == _ISSUE_A


def test_amount_mismatch_warns_not_fails(tmp_path: Path) -> None:
    """Escrow amount doesn't match 19+slot → WARNING only, status PASS."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    wrong_amount = 19 + _SLOT_A + 99
    events = [
        {"type": "escrow_create", "issue": _ISSUE_A, "amount": wrong_amount},
        _escrow_return(_ISSUE_A, _SLOT_A),
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["type"] == "amount_mismatch"
    assert result["warnings"][0]["expected"] == 19 + _SLOT_A
    assert result["warnings"][0]["actual"] == wrong_amount


def test_empty_trajectory_mints_passes(tmp_path: Path) -> None:
    """No mints in trajectory_mints.json → PASS with zero checked."""
    _write_mints(tmp_path, [])
    _write_history(tmp_path, [])

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert result["summary"]["checked"] == 0


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


def test_legacy_mints_skipped(tmp_path: Path) -> None:
    """Mints with issue <= legacy_cutoff are silently skipped."""
    legacy_issue = LEGACY_CUTOFF  # exactly at the cutoff → should be skipped
    mints = [_mint("T1", _SLOT_A, legacy_issue)]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, [])  # no escrow — would be FAIL if checked

    result = run_check(tmp_path)  # default cutoff

    assert result["status"] == "PASS"
    assert result["summary"]["skipped_legacy"] == 1
    assert result["summary"]["checked"] == 0


def test_escrow_consumed_via_payment_counts(tmp_path: Path) -> None:
    """An escrow consumed by a payment event (not escrow_return) is not dangling."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    events = [
        _escrow_create(_ISSUE_A, _SLOT_A),
        {"type": "payment", "issue": _ISSUE_A, "amount": 19 + _SLOT_A, "agent": "x@y"},
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["failures"] == []


def test_old_event_format_event_field(tmp_path: Path) -> None:
    """History records that use 'event' instead of 'type' are parsed correctly."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    events = [
        # Old format: event key + type key meaning escrow kind (not event kind)
        {"event": "escrow_create", "issue": _ISSUE_A, "amount": 19 + _SLOT_A, "type": "standard"},
        {"event": "escrow_return", "issue": _ISSUE_A, "amount": 19 + _SLOT_A},
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"


def test_op_field_escrow_return_counts(tmp_path: Path) -> None:
    """History records that use 'op' field for escrow_return are recognised."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    events = [
        _escrow_create(_ISSUE_A, _SLOT_A),
        {"op": "escrow_return", "issue": _ISSUE_A, "amount": 19 + _SLOT_A},
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"


def test_multiple_failures_all_reported(tmp_path: Path) -> None:
    """Multiple mints with issues → all failures reported in results."""
    mints = [
        _mint("T1", _SLOT_A, _ISSUE_A),  # no escrow
        _mint("T2", _SLOT_B, _ISSUE_B),  # dangling escrow
        _mint("T3", _SLOT_C, _ISSUE_C),  # valid
    ]
    events = [
        _escrow_create(_ISSUE_B, _SLOT_B),  # no return → dangling
        _escrow_create(_ISSUE_C, _SLOT_C),
        _escrow_return(_ISSUE_C, _SLOT_C),
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 2
    failure_types = {f["type"] for f in result["failures"]}
    assert "missing_escrow_create" in failure_types
    assert "dangling_escrow" in failure_types


def test_main_exits_zero_on_pass(tmp_path: Path) -> None:
    """main() returns 0 when all checks pass."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    events = [_escrow_create(_ISSUE_A, _SLOT_A), _escrow_return(_ISSUE_A, _SLOT_A)]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    code = main(["--root", str(tmp_path), "--legacy-cutoff", "0"])
    assert code == 0


def test_main_exits_one_on_fail(tmp_path: Path) -> None:
    """main() returns 1 when a failure is found."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, [])  # no escrow

    code = main(["--root", str(tmp_path), "--legacy-cutoff", "0"])
    assert code == 1


def test_invalid_jsonl_lines_skipped(tmp_path: Path) -> None:
    """Malformed JSONL lines in history don't crash the script."""
    mints = [_mint("T1", _SLOT_A, _ISSUE_A)]
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    # Mix of valid and invalid lines
    lines = [
        "NOT VALID JSON",
        json.dumps(_escrow_create(_ISSUE_A, _SLOT_A)),
        "{broken}",
        json.dumps(_escrow_return(_ISSUE_A, _SLOT_A)),
    ]
    (history_dir / "2026-01-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_mints(tmp_path, mints)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
