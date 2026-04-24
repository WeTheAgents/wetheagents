"""Tests for scripts/check_escrow_ledger_history_consistency.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_escrow_ledger_history_consistency import run_check


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _write_escrows(root: Path, active: dict[str, dict]) -> None:
    _write_json(root / "ledger" / "escrows.json", {"version": 1, "active": active})


def test_valid_escrow_with_create_event_passes(temp_repo: Path) -> None:
    _write_escrows(temp_repo, {"101": {"amount": 12}})
    _write_history(
        temp_repo / "ledger" / "history" / "2026-01-01.jsonl",
        [{"op": "escrow_create", "issue": 101, "amount": 12}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["total_active_escrows"] == 1
    assert report["phantom_count"] == 0
    assert report["zombie_count"] == 0
    assert report["phantom_issues"] == []
    assert report["zombie_issues"] == []


def test_phantom_escrow_fails_when_create_event_missing(temp_repo: Path) -> None:
    _write_escrows(temp_repo, {"202": {"amount": 12}})

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["phantom_count"] == 1
    assert report["zombie_count"] == 0
    assert report["phantom_issues"] == ["202"]
    assert report["zombie_issues"] == []


def test_zombie_escrow_fails_with_close_event(temp_repo: Path) -> None:
    _write_escrows(temp_repo, {"303": {"amount": 12}})
    _write_history(
        temp_repo / "ledger" / "history" / "2026-01-01.jsonl",
        [
            {"op": "escrow_create", "issue": 303, "amount": 12},
            {"type": "payment", "issue": 303, "amount": 12},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["phantom_count"] == 0
    assert report["zombie_count"] == 1
    assert report["zombie_issues"] == ["303"]


def test_zombie_when_create_and_close_split_across_history_files(temp_repo: Path) -> None:
    _write_escrows(temp_repo, {"404": {"amount": 12}})
    _write_history(
        temp_repo / "ledger" / "history" / "2026-01-01.jsonl",
        [{"type": "escrow_create", "issue": 404, "amount": 12}],
    )
    _write_history(
        temp_repo / "ledger" / "history" / "2026-01-02.jsonl",
        [{"type": "accept", "issue": 404, "amount": 12}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["phantom_count"] == 0
    assert report["zombie_count"] == 1
    assert report["zombie_issues"] == ["404"]


def test_active_escrow_with_create_only_passes(temp_repo: Path) -> None:
    _write_escrows(temp_repo, {"505": {"amount": 12}})
    _write_history(
        temp_repo / "ledger" / "history" / "2026-01-01.jsonl",
        [{"op": "escrow_create", "issue": "505", "amount": 12}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["total_active_escrows"] == 1
    assert report["phantom_count"] == 0
    assert report["zombie_count"] == 0
