"""Tests for scripts/check_agent_registry_completeness.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_agent_registry_completeness import (
    classify_unregistered,
    collect_former_ids,
    collect_payment_recipients,
    idem_key_implies_rename,
    iter_events,
    main,
    run_check,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_agent_registry_completeness.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_repo(
    root: Path,
    *,
    agents: dict | None = None,
    idem_keys: dict | None = None,
    history_events: list[dict] | None = None,
) -> Path:
    _write_json(
        root / "ledger" / "balances.json",
        {
            "version": 1,
            "agents": agents
            if agents is not None
            else {
                "agent0@system": {"balance": 9000},
                "Claude-1@claude": {"balance": 100},
            },
        },
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"version": 1, "keys": idem_keys if idem_keys is not None else {}},
    )
    if history_events is not None:
        _write_jsonl(root / "ledger" / "history" / "2026-01-01.jsonl", history_events)
    else:
        (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# collect_payment_recipients
# ---------------------------------------------------------------------------


def test_collect_payment_recipients_payment_event() -> None:
    events = [
        {"type": "payment", "agent": "Claude-1@claude", "amount": 10, "issue": 5}
    ]
    result = collect_payment_recipients(events)
    assert "Claude-1@claude" in result
    assert result["Claude-1@claude"][0]["amount"] == 10
    assert result["Claude-1@claude"][0]["issue"] == 5


def test_collect_payment_recipients_accept_event() -> None:
    events = [
        {"type": "accept", "agent": "Claude-1@claude", "amount": 20, "issue": 7}
    ]
    result = collect_payment_recipients(events)
    assert result["Claude-1@claude"][0]["type"] == "accept"
    assert result["Claude-1@claude"][0]["amount"] == 20


def test_collect_payment_recipients_trajectory_mint() -> None:
    events = [
        {
            "type": "trajectory_mint",
            "agents": ["Claude-1@claude", "Claude-5@claude"],
            "per_agent": [30, 25],
            "issue": 99,
        }
    ]
    result = collect_payment_recipients(events)
    assert result["Claude-1@claude"][0]["amount"] == 30
    assert result["Claude-5@claude"][0]["amount"] == 25
    assert result["Claude-1@claude"][0]["issue"] == 99


def test_collect_payment_recipients_skips_non_payment_events() -> None:
    events = [
        {"type": "escrow_create", "author": "agent0@system", "amount": 50, "issue": 1},
        {"type": "registration", "agent": "Claude-1@claude"},
    ]
    result = collect_payment_recipients(events)
    assert result == {}


def test_collect_payment_recipients_skips_empty_agent() -> None:
    events = [{"type": "payment", "agent": "", "amount": 5, "issue": 1}]
    result = collect_payment_recipients(events)
    assert result == {}


# ---------------------------------------------------------------------------
# collect_former_ids
# ---------------------------------------------------------------------------


def test_collect_former_ids_registration_confirmed() -> None:
    events = [
        {
            "type": "registration_confirmed",
            "agent": "new-id@platform",
            "previous_id": "old-id@platform",
        }
    ]
    former = collect_former_ids(events)
    assert "old-id@platform" in former
    assert "new-id@platform" not in former


def test_collect_former_ids_economy_reset() -> None:
    events = [
        {
            "type": "economy_reset",
            "agents_zeroed": ["OldAgent@X", "AnotherOld@Y"],
        }
    ]
    former = collect_former_ids(events)
    assert "OldAgent@X" in former
    assert "AnotherOld@Y" in former


def test_collect_former_ids_empty() -> None:
    events = [{"type": "payment", "agent": "Claude-1@claude", "amount": 5}]
    former = collect_former_ids(events)
    assert former == set()


# ---------------------------------------------------------------------------
# idem_key_implies_rename
# ---------------------------------------------------------------------------


def test_idem_key_implies_rename_detects_via_payment_prefix() -> None:
    events = [
        {"type": "payment", "agent": "OldAgent@x", "amount": 10, "issue": 70}
    ]
    idem_keys = {
        "payment|70|NewAgent@x|ranking|1": "2026-01-01T00:00:00Z",
    }
    assert idem_key_implies_rename(
        "OldAgent@x", events, {"NewAgent@x"}, idem_keys
    )


def test_idem_key_implies_rename_detects_via_accept_prefix() -> None:
    events = [
        {"type": "accept", "agent": "OldAgent@x", "amount": 5, "issue": 42}
    ]
    idem_keys = {
        "accept|42|RegisteredAgent@y": "2026-01-01T00:00:00Z",
    }
    assert idem_key_implies_rename(
        "OldAgent@x", events, {"RegisteredAgent@y"}, idem_keys
    )


def test_idem_key_implies_rename_no_match() -> None:
    events = [
        {"type": "payment", "agent": "Ghost@x", "amount": 10, "issue": 100}
    ]
    idem_keys = {
        "payment|100|UnrelatedAgent@y": "2026-01-01T00:00:00Z",
    }
    # UnrelatedAgent@y is not in registered_ids
    assert not idem_key_implies_rename("Ghost@x", events, {"OtherAgent@z"}, idem_keys)


def test_idem_key_implies_rename_no_paid_issues() -> None:
    events: list = []
    assert not idem_key_implies_rename("Ghost@x", events, {"Agent@y"}, {})


# ---------------------------------------------------------------------------
# classify_unregistered
# ---------------------------------------------------------------------------


def test_classify_unregistered_zero_amount_is_warning() -> None:
    agent_events = [{"type": "payment", "amount": 0, "issue": 1}]
    cls, reason = classify_unregistered(
        "Ghost@x", agent_events, set(), [], set(), {}
    )
    assert cls == "warning"
    assert "zero amount" in reason


def test_classify_unregistered_former_id_is_warning() -> None:
    agent_events = [{"type": "payment", "amount": 50, "issue": 1}]
    cls, reason = classify_unregistered(
        "OldId@x", agent_events, {"OldId@x"}, [], set(), {}
    )
    assert cls == "warning"
    assert "former" in reason


def test_classify_unregistered_idem_key_match_is_warning() -> None:
    all_events = [{"type": "payment", "agent": "OldId@x", "amount": 10, "issue": 5}]
    idem_keys = {"payment|5|NewId@x|suffix": "2026-01-01T00:00:00Z"}
    agent_events = [{"type": "payment", "amount": 10, "issue": 5}]
    cls, reason = classify_unregistered(
        "OldId@x", agent_events, set(), all_events, {"NewId@x"}, idem_keys
    )
    assert cls == "warning"
    assert "idem_keys" in reason


def test_classify_unregistered_ghost_payment_is_violation() -> None:
    agent_events = [{"type": "payment", "amount": 50, "issue": 9}]
    all_events = [{"type": "payment", "agent": "Ghost@x", "amount": 50, "issue": 9}]
    cls, reason = classify_unregistered(
        "Ghost@x", agent_events, set(), all_events, {"Claude-1@claude"}, {}
    )
    assert cls == "violation"
    assert "50 WEA" in reason


# ---------------------------------------------------------------------------
# run_check — integration
# ---------------------------------------------------------------------------


def test_run_check_passes_when_all_recipients_registered(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 900}, "Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Claude-1@claude", "amount": 10, "issue": 1}
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["warnings"] == []


def test_run_check_fails_on_ghost_payment(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 900}, "Claude-1@claude": {"balance": 100}},
        history_events=[
            {
                "type": "payment",
                "agent": "Ghost@unknown",
                "amount": 30,
                "issue": 5,
            }
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["agent"] == "Ghost@unknown"
    assert report["violations"][0]["total_received"] == 30


def test_run_check_warns_on_zero_amount_event(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 1000}},
        history_events=[
            {
                "type": "payment",
                "agent": "Ghost@unknown",
                "amount": 0,
                "issue": 3,
            }
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["agent"] == "Ghost@unknown"
    assert "zero amount" in report["warnings"][0]["reason"]


def test_run_check_warns_on_renamed_agent_via_registration_confirmed(
    tmp_path: Path,
) -> None:
    root = _make_repo(
        tmp_path,
        agents={"NewId@platform": {"balance": 50}},
        history_events=[
            {
                "type": "payment",
                "agent": "OldId@platform",
                "amount": 20,
                "issue": 7,
            },
            {
                "type": "registration_confirmed",
                "agent": "NewId@platform",
                "previous_id": "OldId@platform",
            },
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert report["warnings"][0]["agent"] == "OldId@platform"
    assert "former" in report["warnings"][0]["reason"]


def test_run_check_warns_on_economy_reset_agent(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 1000}},
        history_events=[
            {
                "type": "payment",
                "agent": "EarlyAgent@platform",
                "amount": 100,
                "issue": 2,
            },
            {
                "type": "economy_reset",
                "agents_zeroed": ["EarlyAgent@platform"],
            },
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert "former" in report["warnings"][0]["reason"]


def test_run_check_warns_on_inferred_rename_via_idem_keys(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"RegisteredNew@x": {"balance": 50}},
        idem_keys={"payment|42|RegisteredNew@x|ranking|1": "2026-01-01T00:00:00Z"},
        history_events=[
            {
                "type": "payment",
                "agent": "OldName@x",
                "amount": 15,
                "issue": 42,
            }
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert len(report["warnings"]) == 1
    assert "idem_keys" in report["warnings"][0]["reason"]


def test_run_check_trajectory_mint_recipients_checked(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 900}, "Claude-1@claude": {"balance": 100}},
        history_events=[
            {
                "type": "trajectory_mint",
                "agents": ["Claude-1@claude", "GhostMint@x"],
                "per_agent": [30, 25],
                "issue": 50,
            }
        ],
    )

    report, exit_code = run_check(root)

    assert exit_code == 1
    assert report["violations"][0]["agent"] == "GhostMint@x"
    assert report["violations"][0]["total_received"] == 25


def test_run_check_missing_balances_returns_fail(tmp_path: Path) -> None:
    _write_json(tmp_path / "ledger" / "idem_keys.json", {"version": 1, "keys": {}})
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report, exit_code = run_check(tmp_path)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert "balances.json not found" in report["summary"]


def test_run_check_missing_idem_keys_still_checks_history(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "ledger" / "balances.json",
        {"version": 1, "agents": {"Claude-1@claude": {"balance": 100}}},
    )
    _write_jsonl(
        tmp_path / "ledger" / "history" / "2026-01-01.jsonl",
        [{"type": "payment", "agent": "Ghost@x", "amount": 5, "issue": 1}],
    )

    report, exit_code = run_check(tmp_path)

    assert exit_code == 1
    assert report["status"] == "FAIL"
    assert "idem_keys.json not found" in report["summary"]


def test_run_check_empty_history_passes(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"Claude-1@claude": {"balance": 100}},
        history_events=[],
    )

    report, exit_code = run_check(root)

    assert exit_code == 0
    assert report["status"] == "PASS"


def test_run_check_summary_counts_are_correct(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"agent0@system": {"balance": 900}, "Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Claude-1@claude", "amount": 10, "issue": 1},
            {"type": "payment", "agent": "Ghost@x", "amount": 5, "issue": 2},
        ],
    )

    report, _ = run_check(root)

    assert "2 history-payment recipient(s)" in report["summary"]
    assert "1 violation(s)" in report["summary"]


# ---------------------------------------------------------------------------
# main() — CLI interface
# ---------------------------------------------------------------------------


def test_main_emits_pass_json_for_clean_repo(tmp_path: Path, capsys) -> None:
    root = _make_repo(
        tmp_path,
        agents={"Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Claude-1@claude", "amount": 10, "issue": 1}
        ],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"


def test_main_emits_fail_json_for_ghost_payment(tmp_path: Path, capsys) -> None:
    root = _make_repo(
        tmp_path,
        agents={"Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Ghost@x", "amount": 99, "issue": 7}
        ],
    )

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert payload["violations"][0]["agent"] == "Ghost@x"


def test_cli_exit_code_one_for_violation(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Ghost@x", "amount": 40, "issue": 3}
        ],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["violations"][0]["agent"] == "Ghost@x"


def test_cli_exit_code_zero_for_clean_repo(tmp_path: Path) -> None:
    root = _make_repo(
        tmp_path,
        agents={"Claude-1@claude": {"balance": 100}},
        history_events=[
            {"type": "payment", "agent": "Claude-1@claude", "amount": 10, "issue": 1}
        ],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
