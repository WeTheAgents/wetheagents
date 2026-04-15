from __future__ import annotations

import json
from pathlib import Path

from scripts.check_no_duplicate_payments import main, run_check


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def _make_root(root: Path, events_by_file: dict[str, list[dict]]) -> Path:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for filename, events in events_by_file.items():
        _write_jsonl(history_dir / filename, events)
    return root


def _violations(report: dict) -> list[dict]:
    return report["checks"][0]["violations"]


def test_single_payment_per_agent_issue_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test", "timestamp": "2026-04-01T00:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _violations(report) == []
    assert report["summary"]["violations"] == 0


def test_two_payments_same_agent_same_issue_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test|1", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test|2", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert _violations(report) == [{
        "agent": "alice@test",
        "issue": "11",
        "count": 2,
        "timestamps": ["2026-04-01T00:00:00Z", "2026-04-01T01:00:00Z"],
    }]


def test_two_payments_different_agents_same_issue_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 11, "agent": "bob@test", "idem_key": "payment|11|bob@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _violations(report) == []
    assert report["summary"]["payment_groups_checked"] == 2


def test_two_payments_same_agent_different_issues_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 12, "agent": "alice@test", "idem_key": "payment|12|alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert _violations(report) == []


def test_trajectory_mints_are_exempt(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "trajectory_mint", "issue": 11, "agent": "alice@test", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "trajectory_mint", "issue": 11, "agent": "alice@test", "timestamp": "2026-04-01T01:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["payment_events_scanned"] == 0
    assert _violations(report) == []


def test_empty_history_passes(temp_repo: Path) -> None:
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["summary"] == {
        "payment_events_scanned": 0,
        "payment_groups_checked": 0,
        "violations": 0,
        "skipped_legacy_payments": 0,
    }


def test_multiple_issues_all_unique_pass(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 12, "agent": "bob@test", "idem_key": "payment|12|bob@test", "timestamp": "2026-04-01T01:00:00Z"},
        ],
        "2026-04-02.jsonl": [
            {"type": "payment", "issue": 13, "agent": "carol@test", "idem_key": "payment|13|carol@test", "timestamp": "2026-04-02T00:00:00Z"},
            {"type": "payment", "issue": 14, "agent": "alice@test", "idem_key": "payment|14|alice@test", "timestamp": "2026-04-02T01:00:00Z"},
        ],
    })

    report = run_check(root)

    assert report["status"] == "PASS"
    assert report["summary"]["payment_groups_checked"] == 4
    assert _violations(report) == []


def test_mixed_duplicate_and_clean_reports_only_duplicate(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test|1", "timestamp": "2026-04-01T00:00:00Z"},
            {"type": "payment", "issue": 11, "agent": "alice@test", "idem_key": "payment|11|alice@test|2", "timestamp": "2026-04-01T01:00:00Z"},
            {"type": "payment", "issue": 12, "agent": "bob@test", "idem_key": "payment|12|bob@test", "timestamp": "2026-04-01T02:00:00Z"},
            {"type": "payment", "issue": 12, "agent": "carol@test", "idem_key": "payment|12|carol@test", "timestamp": "2026-04-01T03:00:00Z"},
            {"type": "payment", "issue": 13, "agent": "alice@test", "idem_key": "payment|13|alice@test", "timestamp": "2026-04-01T04:00:00Z"},
        ]
    })

    report = run_check(root)

    assert report["status"] == "FAIL"
    assert len(_violations(report)) == 1
    assert _violations(report)[0]["agent"] == "alice@test"
    assert _violations(report)[0]["issue"] == "11"


def test_main_prints_json_and_returns_zero_on_realistic_pass_case(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {"type": "payment", "issue": 21, "agent": "alice@test", "idem_key": "payment|21|alice@test", "timestamp": "2026-04-01T00:00:00Z"},
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert "checks" in payload
    assert "summary" in payload
