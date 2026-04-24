"""Boundary-spec tests for scripts/check_escrow_return_coverage.py.

Covers all 7 boundary conditions: same-file mint+return, cross-file mint+return,
minted with no return, return with no mint, duplicate mint events, active escrow
with mint, and empty history directory.

## Gaps

GAP-1  Case 3 narrow — the spec states "Minted with no return → FAIL".
       The implementation only flags issues that have *both* a trajectory_mint
       and an escrow_create event.  A trajectory_mint with no paired escrow_create
       (pre-escrow-era mint) is silently exempted: missing_return stays empty and
       status is PASS even though no escrow_return exists.
       See test_case3b_mint_no_escrow_create_not_flagged.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_escrow_return_coverage import load_history_events, run_check


def _mint(issue: int | str) -> dict:
    return {"type": "trajectory_mint", "issue": issue}


def _escrow_create(issue: int | str) -> dict:
    return {"type": "escrow_create", "issue": issue}


def _return(issue: int | str) -> dict:
    return {"type": "escrow_return", "issue": issue}


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


# ── 1. Minted with return in SAME file ────────────────────────────────────────
# Both trajectory_mint+escrow_create and escrow_return appear in a single .jsonl.
# The loader reads all lines in one pass; order within a file does not matter for
# set membership.
#
# Decision table:
# | initial state | data in 2026-04-24.jsonl                          | expected |
# |---------------|---------------------------------------------------|----------|
# | history empty | trajectory_mint(101), escrow_create(101),         | PASS     |
# |               | escrow_return(101)                                |          |


def test_case1_mint_and_return_same_file(tmp_path: Path) -> None:
    """Both mint+escrow_create and return in a single JSONL file → PASS."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    _write_jsonl(
        history_dir / "2026-04-24.jsonl",
        [
            {"type": "trajectory_mint", "issue": 101},
            {"type": "escrow_create", "issue": 101},
            {"type": "escrow_return", "issue": 101},
        ],
    )

    result = run_check(tmp_path, events=load_history_events(history_dir))

    assert result["status"] == "PASS"
    assert result["minted_total"] == 1
    assert result["with_return"] == ["101"]
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


# ── 2. Minted with return in DIFFERENT files ──────────────────────────────────
# trajectory_mint+escrow_create live in an earlier file; escrow_return is in a
# later file.  load_history_events iterates sorted(glob("*.jsonl")) so both files
# are loaded and merged before coverage analysis.
#
# Decision table:
# | initial state | 2026-04-23.jsonl              | 2026-04-24.jsonl       | expected |
# |---------------|-------------------------------|------------------------|----------|
# | history empty | trajectory_mint(202),         | escrow_return(202)     | PASS     |
# |               | escrow_create(202)            |                        |          |


def test_case2_mint_and_return_different_files(tmp_path: Path) -> None:
    """Mint+escrow_create in one file, return in a later file → PASS."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)
    _write_jsonl(
        history_dir / "2026-04-23.jsonl",
        [
            {"type": "trajectory_mint", "issue": 202},
            {"type": "escrow_create", "issue": 202},
        ],
    )
    _write_jsonl(
        history_dir / "2026-04-24.jsonl",
        [{"type": "escrow_return", "issue": 202}],
    )

    result = run_check(tmp_path, events=load_history_events(history_dir))

    assert result["status"] == "PASS"
    assert result["minted_total"] == 1
    assert result["with_return"] == ["202"]
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


# ── 3. Minted with no return ──────────────────────────────────────────────────
# trajectory_mint + escrow_create present; no escrow_return for that issue.
# The coverage check requires a return for every escrowed mint.
#
# Decision table:
# | events                                | expected | missing_return | summary              |
# |---------------------------------------|----------|----------------|----------------------|
# | trajectory_mint(303), escrow_create(303) | FAIL  | ["303"]        | missing_return=1 ... |
#
# GAP-1 sub-case:
# | events                | expected | missing_return | note                      |
# |-----------------------|----------|----------------|---------------------------|
# | trajectory_mint(303)  | PASS     | []             | no escrow_create → exempt |


def test_case3_minted_no_return_fails(tmp_path: Path) -> None:
    """Mint+escrow_create with no escrow_return → FAIL; exact error fields checked."""
    result = run_check(
        tmp_path,
        events=[_mint(303), _escrow_create(303)],
    )

    assert result["status"] == "FAIL"
    assert result["minted_total"] == 1
    assert result["missing_return"] == ["303"]
    assert result["with_return"] == []
    assert result["live_orphans"] == []
    assert result["summary"] == "minted_total=1 with_return=0 missing_return=1 live_orphans=0"


def test_case3b_mint_no_escrow_create_not_flagged(tmp_path: Path) -> None:
    """GAP-1: trajectory_mint alone (no escrow_create) with no return → PASS.

    The spec says 'Minted with no return → FAIL', but the implementation exempts
    pre-escrow-era mints.  Only mints that also have a paired escrow_create event
    are subject to the return requirement.
    """
    result = run_check(
        tmp_path,
        events=[_mint(303)],
    )

    # Actual behavior: PASS (not flagged — pre-escrow-era exemption)
    assert result["status"] == "PASS"
    assert result["minted_total"] == 1
    assert result["missing_return"] == []


# ── 4. Return with no mint ────────────────────────────────────────────────────
# An escrow_return for issue 999 exists in history but no trajectory_mint references
# issue 999.  The implementation computes with_return = minted & returned, so an
# orphan return that has no matching mint contributes nothing to counts or status.
#
# Decision table:
# | events                  | minted_total | with_return | missing_return | expected |
# |-------------------------|--------------|-------------|----------------|----------|
# | escrow_return(999) only | 0            | []          | []             | PASS     |


def test_case4_return_without_mint_is_ignored(tmp_path: Path) -> None:
    """escrow_return for issue 999 with no trajectory_mint → PASS, minted_total=0."""
    result = run_check(
        tmp_path,
        events=[_return(999)],
    )

    assert result["status"] == "PASS"
    assert result["minted_total"] == 0
    assert result["with_return"] == []
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


# ── 5. Duplicate mint events ──────────────────────────────────────────────────
# The same issue appears in two separate trajectory_mint events.  The implementation
# uses a set, so duplicates collapse to one entry; minted_total reflects unique issues.
#
# Decision table (with return):
# | events                                          | minted_total | expected |
# |-------------------------------------------------|--------------|----------|
# | mint(505), escrow_create(505), mint(505)(dup),  | 1            | PASS     |
# | return(505)                                     |              |          |
#
# Decision table (without return):
# | events                                   | minted_total | missing_return | expected |
# |------------------------------------------|--------------|----------------|----------|
# | mint(505), escrow_create(505), mint(505) | 1            | ["505"]        | FAIL     |


def test_case5_duplicate_mint_events_deduplicated_with_return(tmp_path: Path) -> None:
    """Two trajectory_mint events for the same issue → minted_total=1, PASS when return present."""
    result = run_check(
        tmp_path,
        events=[
            _mint(505),
            _escrow_create(505),
            _mint(505),  # duplicate — collapsed by set
            _return(505),
        ],
    )

    assert result["status"] == "PASS"
    assert result["minted_total"] == 1
    assert result["with_return"] == ["505"]
    assert result["missing_return"] == []


def test_case5b_duplicate_mint_no_return_fails(tmp_path: Path) -> None:
    """Two trajectory_mint for same issue, no return → minted_total=1, FAIL."""
    result = run_check(
        tmp_path,
        events=[_mint(505), _escrow_create(505), _mint(505)],
    )

    assert result["status"] == "FAIL"
    assert result["minted_total"] == 1
    assert result["missing_return"] == ["505"]


# ── 6. Active escrow AND mint ─────────────────────────────────────────────────
# Issue appears in active escrows.json AND has a trajectory_mint+escrow_create in
# history but no escrow_return.  The implementation reports it in live_orphans.
#
# Decision table (no return, active escrow present):
# | events                        | active_escrows       | live_orphans          | expected |
# |-------------------------------|----------------------|-----------------------|----------|
# | mint(606), escrow_create(606) | {606: {amount:51}}   | [{issue:606, amt:51}] | FAIL     |
#
# Variant (return present — should NOT appear in live_orphans):
# | events                               | active_escrows       | live_orphans | expected |
# |--------------------------------------|----------------------|--------------|----------|
# | mint(606), escrow_create(606),       | {606: {amount:51}}   | []           | PASS     |
# | return(606)                          |                      |              |          |


def test_case6_active_escrow_and_mint_reported_as_orphan(tmp_path: Path) -> None:
    """Minted issue in active_escrows with no return → FAIL and live_orphan recorded."""
    result = run_check(
        tmp_path,
        events=[_mint(606), _escrow_create(606)],
        active_escrows={"606": {"amount": 51, "author": "agent0@system"}},
    )

    assert result["status"] == "FAIL"
    assert result["missing_return"] == ["606"]
    assert len(result["live_orphans"]) == 1
    assert result["live_orphans"][0] == {
        "issue": "606",
        "amount": 51,
        "author": "agent0@system",
        "state": "active",
    }


def test_case6b_active_escrow_with_return_not_in_live_orphans(tmp_path: Path) -> None:
    """Minted issue with return and active escrow → PASS, not in live_orphans."""
    result = run_check(
        tmp_path,
        events=[_mint(606), _escrow_create(606), _return(606)],
        active_escrows={"606": {"amount": 51, "author": "agent0@system"}},
    )

    assert result["status"] == "PASS"
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


# ── 7. Empty history directory ─────────────────────────────────────────────────
# ledger/history/ exists but contains no *.jsonl files.  load_history_events
# iterates sorted(glob("*.jsonl")) which yields nothing; events list is [].
# run_check receives an empty event set → all counts zero → status PASS (exit 0).
#
# Decision table:
# | history dir state | jsonl files | minted_total | missing_return | expected |
# |-------------------|-------------|--------------|----------------|----------|
# | exists, empty     | 0           | 0            | []             | PASS     |


def test_case7_empty_history_directory(tmp_path: Path) -> None:
    """Empty ledger/history/ dir with no JSONL files → PASS, all counts zero."""
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True)

    result = run_check(tmp_path, events=load_history_events(history_dir))

    assert result["status"] == "PASS"
    assert result["minted_total"] == 0
    assert result["with_return"] == []
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


def test_case7b_nonexistent_history_dir(tmp_path: Path) -> None:
    """If ledger/history/ does not exist at all, load_history_events returns [] → PASS."""
    history_dir = tmp_path / "ledger" / "history"
    # Intentionally not created

    result = run_check(tmp_path, events=load_history_events(history_dir))

    assert result["status"] == "PASS"
    assert result["minted_total"] == 0
    assert result["missing_return"] == []
