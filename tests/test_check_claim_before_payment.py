#!/usr/bin/env python3
"""Tests for scripts/check_claim_before_payment.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from uuid import uuid4

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_claim_before_payment.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event) for event in events]
    (history_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def _case_root(temp_repo: Path) -> Path:
    root = temp_repo / f"case_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_pass_when_prior_claim_exists_same_agent_and_issue(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "author": "Codex-2@codex", "timestamp": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["checks"][0]["payments_checked"] == 1


def test_fail_when_payment_has_no_prior_claim_after_enforcement(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 100, "author": "Alice@test", "timestamp": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "FAIL"
    assert report["violations"] == [
        {
            "issue": 486,
            "agent": "Codex-2@codex",
            "payment_ts": "2026-04-10T10:00:00Z",
            "claim_ts": None,
        }
    ]


def test_fail_when_claim_is_for_different_agent(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "author": "Claude-1@claude", "timestamp": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["violations"][0]["agent"] == "Codex-2@codex"
    assert report["violations"][0]["claim_ts"] is None


def test_fail_when_claim_is_after_payment(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 100, "author": "Alice@test", "timestamp": "2026-04-10T08:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
            {"type": "claim", "issue": 486, "author": "Codex-2@codex", "timestamp": "2026-04-10T11:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["violations"][0]["payment_ts"] == "2026-04-10T10:00:00Z"
    assert report["violations"][0]["claim_ts"] is None


def test_sorts_across_multiple_files_by_timestamp(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-11.jsonl",
        [
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )
    _write_history(
        root,
        "2026-04-12.jsonl",
        [
            {"type": "claim", "issue": 486, "author": "Codex-2@codex", "timestamp": "2026-04-10T09:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["payments_checked"] == 1


def test_trajectory_mint_is_exempt(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "trajectory_mint", "issue": 486, "agents": ["Codex-2@codex"], "per_agent": [29], "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["trajectory_mint_exemptions"] == 1
    assert report["checks"][0]["payments_total"] == 0


def test_historical_payments_are_skipped_when_no_claim_events_exist(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-03-03.jsonl",
        [
            {"type": "payment", "issue": 7, "agent": "CursorWea@cursor", "amount": 5, "timestamp": "2026-03-03T16:00:00Z"},
            {"type": "payment", "issue": 17, "agent": "CursorWea@cursor", "amount": 20, "timestamp": "2026-03-03T19:15:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["enforcement_started_at"] is None
    assert report["checks"][0]["payments_skipped_historical"] == 2
    assert "no claim events found" in report["summary"]


def test_claim_event_accepts_agent_field_too(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "agent": "Codex-2@codex", "timestamp": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"


def test_equal_timestamp_claim_is_not_prior(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "author": "Codex-2@codex", "timestamp": "2026-04-10T10:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "timestamp": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "FAIL"
    assert report["violations"][0]["claim_ts"] is None


def test_invalid_jsonl_returns_fail_report(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-04-10.jsonl").write_text("{not-json}\n", encoding="utf-8")

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "FAIL"
    assert report["checks"][0]["status"] == "FAIL"
    assert "FAIL:" in report["summary"]


def test_payment_uses_started_at_when_timestamp_missing(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "author": "Codex-2@codex", "started_at": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "started_at": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["payments_checked"] == 1


def test_payment_uses_ts_when_timestamp_missing(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-10.jsonl",
        [
            {"type": "claim", "issue": 486, "agent": "Codex-2@codex", "ts": "2026-04-10T09:00:00Z"},
            {"type": "payment", "issue": 486, "agent": "Codex-2@codex", "amount": 29, "ts": "2026-04-10T10:00:00Z"},
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["payments_checked"] == 1


def test_legacy_invalid_escape_in_note_is_repaired(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-04-10.jsonl").write_text(
        '{"type":"payment","issue":486,"agent":"Codex-2@codex","amount":29,"timestamp":"2026-04-10T10:00:00Z","note":"11 - \\!3"}\n',
        encoding="utf-8",
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "PASS"
    assert report["checks"][0]["payments_skipped_historical"] == 1
