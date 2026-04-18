"""Tests for scripts/check_history_event_completeness.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_event_completeness import main, run


def _make_repo(root: Path) -> Path:
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


def _write_jsonl(path: Path, entries: list[dict[str, object] | str]) -> None:
    lines: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            lines.append(entry)
        else:
            lines.append(json.dumps(entry))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_valid_payment_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "payment",
                "issue": 42,
                "agent": "Codex-19@codex",
                "amount": 15,
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"
    assert report["checks"] == []


def test_escrow_author_alias_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "escrow",
                "issue": 42,
                "author": "agent0@system",
                "amount": 15,
                "created_at": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"


def test_escrow_return_recipient_alias_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "escrow_return",
                "issue": 42,
                "recipient": "agent0@system",
                "amount": 15,
                "created_at": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"


def test_missing_required_field_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "payment",
                "issue": 42,
                "agent": "Codex-19@codex",
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is False
    assert report["status"] == "FAIL"
    fail = report["checks"][0]
    assert fail["check"] == "required_fields"
    assert "amount" in fail["missing_fields"]


def test_blank_string_counts_as_missing(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "verification",
                "issue": 42,
                "agent": "Codex-19@codex",
                "verified_by": "agent0@system",
                "evidence": "   ",
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is False
    assert "evidence" in report["checks"][0]["missing_fields"]


def test_empty_list_counts_as_missing(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "economy_reset",
                "description": "reset",
                "agents_zeroed": [],
                "wea_returned_to_agent0": 10,
                "mint_burned": 5,
                "new_supply": 10000,
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is False
    assert "agents_zeroed" in report["checks"][0]["missing_fields"]


def test_unknown_type_warns_without_failing(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [{"type": "future_event", "timestamp": "2026-04-01T00:00:00Z"}],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"
    assert report["checks"][0]["status"] == "WARN"
    assert report["checks"][0]["check"] == "unknown_type"


def test_missing_type_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [{"issue": 42, "agent": "Codex-19@codex", "amount": 1, "timestamp": "2026-04-01T00:00:00Z"}],
    )

    report, passed = run(root)

    assert passed is False
    assert report["checks"][0]["check"] == "missing_type"


def test_non_string_type_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [{"type": ["payment"], "issue": 42, "agent": "Codex-19@codex", "amount": 1, "timestamp": "2026-04-01T00:00:00Z"}],
    )

    report, passed = run(root)

    assert passed is False
    assert report["checks"][0]["check"] == "missing_type"


def test_register_at_timestamp_alias_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "register",
                "agent": "Claude-13@claude",
                "platform": "claude-code",
                "operator": "peach",
                "github_username": "wetheagents",
                "slot": "13",
                "at": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"


def test_trajectory_mint_single_agent_legacy_variant_passes(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 12,
                "amount": 31,
                "issue": 505,
                "agent": "Codex-19@codex",
                "created_at": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"


def test_trajectory_mint_agents_without_per_agent_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 12,
                "amount": 31,
                "issue": 505,
                "agents": ["Codex-19@codex"],
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    report, passed = run(root)

    assert passed is False
    assert "per_agent" in report["checks"][0]["missing_fields"]


def test_invalid_escape_is_repaired(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    path = root / "ledger" / "history" / "2026-04-01.jsonl"
    path.write_text(
        '{"type":"payment","issue":42,"agent":"Codex-19@codex","amount":15,"note":"11 - \\!3","timestamp":"2026-04-01T00:00:00Z"}\n',
        encoding="utf-8",
    )

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"


def test_irreparable_parse_error_warns(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    path = root / "ledger" / "history" / "2026-04-01.jsonl"
    path.write_text('{"type":"payment","issue":42,\n', encoding="utf-8")

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"
    assert report["checks"][0]["check"] == "parse_error"
    assert report["checks"][0]["status"] == "WARN"


def test_non_object_json_line_fails(temp_repo: Path) -> None:
    root = _make_repo(temp_repo)
    path = root / "ledger" / "history" / "2026-04-01.jsonl"
    path.write_text('[]\n', encoding="utf-8")

    report, passed = run(root)

    assert passed is False
    assert report["status"] == "FAIL"
    assert report["checks"][0]["check"] == "not_a_dict"


def test_missing_history_directory_fails(temp_repo: Path) -> None:
    root = temp_repo / "no-history"
    root.mkdir()
    report, passed = run(root)

    assert passed is False
    assert report["status"] == "FAIL"
    assert "history directory not found" in report["summary"]


def test_main_returns_zero_for_clean_repo(temp_repo: Path, capsys) -> None:
    root = _make_repo(temp_repo)
    _write_jsonl(
        root / "ledger" / "history" / "2026-04-01.jsonl",
        [
            {
                "type": "payment",
                "issue": 42,
                "agent": "Codex-19@codex",
                "amount": 15,
                "timestamp": "2026-04-01T00:00:00Z",
            }
        ],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_current_repo_passes() -> None:
    root = Path(__file__).resolve().parent.parent

    report, passed = run(root)

    assert passed is True
    assert report["status"] == "PASS"
