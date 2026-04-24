"""Tests for scripts/check_escrow_return_coverage.py."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_escrow_return_coverage import run_check


def _mint(issue: int | str) -> dict:
    return {"type": "trajectory_mint", "issue": issue}


def _escrow_create(issue: int | str) -> dict:
    return {"type": "escrow_create", "issue": issue}


def _return(issue: int | str) -> dict:
    return {"type": "escrow_return", "issue": issue}


def _return_bulk(issues: list[int]) -> dict:
    return {"type": "escrow_return_bulk", "issues": issues}


def test_all_minted_have_returns_pass() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(101), _return(101), _mint("202"), _return("202")],
    )
    assert result["status"] == "PASS"
    assert result["minted_total"] == 2
    assert result["with_return"] == ["101", "202"]
    assert result["missing_return"] == []
    assert result["live_orphans"] == []


def test_missing_return_fails_and_reports_issue() -> None:
    result = run_check(Path("/tmp/repo"), events=[_mint(303), _escrow_create(303)])
    assert result["status"] == "FAIL"
    assert result["minted_total"] == 1
    assert result["with_return"] == []
    assert result["missing_return"] == ["303"]
    assert result["live_orphans"] == []


def test_string_issue_values_are_normalized() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint("003"), _return(3)],
    )
    assert result["status"] == "PASS"
    assert result["with_return"] == ["3"]
    assert result["missing_return"] == []


def test_bulk_return_does_not_cover_single_issue_check() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(404), _escrow_create(404), _return_bulk([404])],
    )
    assert result["status"] == "FAIL"
    assert result["missing_return"] == ["404"]


def test_active_orphan_for_missing_return() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(500), _escrow_create(500)],
        active_escrows={"500": {"amount": 18, "author": "agent@x"}},
    )
    assert result["status"] == "FAIL"
    assert result["missing_return"] == ["500"]
    assert result["live_orphans"] == [
        {"issue": "500", "amount": 18, "author": "agent@x", "state": "active"},
    ]


def test_active_escrow_without_missing_return_not_reported() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(600), _escrow_create(600)],
        active_escrows={"601": {"amount": 5, "author": "agent@x"}},
    )
    assert result["status"] == "FAIL"
    assert result["missing_return"] == ["600"]
    assert result["live_orphans"] == []


def test_invalid_issue_types_are_ignored() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[
            {"type": "trajectory_mint", "issue": None},
            {"type": "trajectory_mint", "issue": "bad"},
            {"type": "trajectory_mint", "issue": True},
            {"type": "escrow_return", "issue": "bad"},
        ],
    )
    assert result["status"] == "PASS"
    assert result["minted_total"] == 0
    assert result["with_return"] == []
    assert result["missing_return"] == []


def test_lists_and_counts_are_sorted_and_deduplicated() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[
            _mint("010"),
            _return("10"),
            _mint(10),
            _mint(2),
            _return(2),
            _mint("002"),
            _return("2"),
            _mint(700),
            _escrow_create(700),
        ],
    )
    assert result["status"] == "FAIL"
    assert result["with_return"] == ["2", "10"]
    assert result["missing_return"] == ["700"]


def test_live_orphan_records_active_fields() -> None:
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(700), _escrow_create(700)],
        active_escrows={"700": {"amount": 99, "author": "agent@x", "state": "active"}},
    )
    assert result["status"] == "FAIL"
    assert len(result["live_orphans"]) == 1
    assert result["live_orphans"][0] == {
        "issue": "700",
        "amount": 99,
        "author": "agent@x",
        "state": "active",
    }


def test_mint_without_escrow_create_is_not_flagged() -> None:
    """Pre-escrow-era mints (no escrow_create event) are exempt from coverage check."""
    result = run_check(
        Path("/tmp/repo"),
        events=[_mint(101)],
    )
    assert result["status"] == "PASS"
    assert result["minted_total"] == 1
    assert result["missing_return"] == []
