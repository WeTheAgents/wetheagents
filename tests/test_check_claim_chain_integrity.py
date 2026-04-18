"""Tests for scripts/check_claim_chain_integrity.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_claim_chain_integrity import main, run_check

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_claim_chain_integrity.py"


def _make_repo(root: Path) -> Path:
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def _write_history(root: Path, filename: str, events: list[dict[str, object] | str]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    (root / "ledger" / "history" / filename).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_task_index(root: Path, tasks: dict[str, dict[str, object]]) -> None:
    (root / "ledger" / "task_index.json").write_text(
        json.dumps({"version": 1, "tasks": tasks}),
        encoding="utf-8",
    )


def _write_escrows(root: Path, active: dict[str, dict[str, object]] | None = None) -> None:
    (root / "ledger" / "escrows.json").write_text(
        json.dumps({"version": 1, "active": active or {}}),
        encoding="utf-8",
    )


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_claim_events_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "payment", "issue": 7, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["total_claim_events"] == 0
    assert report["pending_claims"] == []
    assert report["broken_claims"] == []


def test_claim_resolves_via_accept_same_agent(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 10, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 10, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_accept"] == 1
    assert report["summary"]["broken"] == 0


def test_claim_resolves_via_payment_same_agent(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 11, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "payment", "issue": 11, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_payment"] == 1


def test_claim_resolves_via_reject_same_agent(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 12, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "reject", "issue": 12, "agent": "alice@test", "reason": "needs tests", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_reject"] == 1


def test_standard_claim_is_superseded_by_later_claim(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "20": {"status": "open", "mechanic": "standard"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 20, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "claim", "issue": 20, "agent": "bob@test", "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 20, "agent": "bob@test", "amount": 10, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["superseded"] == 1
    assert report["summary"]["resolved_by_payment"] == 1


def test_standard_claim_with_mismatched_terminal_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "21": {"status": "open", "mechanic": "standard"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 21, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 21, "agent": "bob@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["summary"]["broken"] == 1
    assert report["broken_claims"][0]["reason"] == "mismatched_terminal"


def test_every_good_claims_do_not_supersede_each_other(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "30": {"status": "open", "mechanic": "every_good"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 30, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "claim", "issue": 30, "agent": "bob@test", "timestamp": "2026-04-01T09:30:00Z"},
            {"type": "payment", "issue": 30, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 30, "agent": "bob@test", "amount": 5, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["superseded"] == 0
    assert report["summary"]["resolved_by_payment"] == 2


def test_every_good_other_agent_payment_before_my_payment_does_not_break_chain(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "31": {"status": "open", "mechanic": "every_good"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 31, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "claim", "issue": 31, "agent": "bob@test", "timestamp": "2026-04-01T09:30:00Z"},
            {"type": "payment", "issue": 31, "agent": "bob@test", "amount": 5, "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 31, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["broken"] == 0
    assert report["summary"]["resolved_by_payment"] == 2


def test_missing_metadata_infers_multi_claim_from_multiple_terminal_agents(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 32, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "claim", "issue": 32, "agent": "bob@test", "timestamp": "2026-04-01T09:30:00Z"},
            {"type": "payment", "issue": 32, "agent": "bob@test", "amount": 5, "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 32, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_payment"] == 2
    assert report["summary"]["broken"] == 0


def test_latest_claim_without_followup_is_pending(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "40": {"status": "open", "mechanic": "standard"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 40, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["pending"] == 1
    assert report["pending_claims"][0]["issue"] == 40


def test_closed_issue_with_unresolved_claim_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "41": {"status": "paid", "mechanic": "standard"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 41, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert report["broken_claims"][0]["reason"] == "closed_without_resolution"


def test_same_agent_reclaim_supersedes_prior_multiclaim_claim(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_task_index(
        root,
        {
            "42": {"status": "open", "mechanic": "every_good"},
        },
    )
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "claim", "issue": 42, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 42, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["superseded"] == 1
    assert report["summary"]["resolved_by_payment"] == 1


def test_claim_accepts_author_and_created_at_aliases(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 50, "author": "alice@test", "created_at": "2026-04-01T09:00:00Z"},
            {"type": "payment", "issue": 50, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z", "amount": 5},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_payment"] == 1


def test_sorts_events_across_files_by_timestamp(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-02.jsonl",
        [
            {"type": "payment", "issue": 60, "agent": "alice@test", "amount": 5, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )
    _write_history(
        root,
        "2026-04-03.jsonl",
        [
            {"type": "claim", "issue": 60, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["resolved_by_payment"] == 1


def test_invalid_json_returns_fail_report(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    (root / "ledger" / "history" / "2026-04-01.jsonl").write_text("{not-json}\n", encoding="utf-8")

    result = _run(root)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert "error" in payload["checks"][0]


def test_missing_agent_on_relevant_event_returns_fail_report(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 70, "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    result = _run(root)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert "missing agent" in payload["checks"][0]["error"]


def test_main_returns_zero_for_clean_repo(temp_repo: Path, capsys) -> None:
    root = _make_repo(temp_repo)
    _write_history(
        root,
        "2026-04-01.jsonl",
        [
            {"type": "claim", "issue": 80, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )
    _write_task_index(
        root,
        {
            "80": {"status": "open", "mechanic": "standard"},
        },
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_current_repo_passes() -> None:
    root = Path(__file__).resolve().parent.parent

    report = run_check(root)

    assert report["status"] == "PASS"
