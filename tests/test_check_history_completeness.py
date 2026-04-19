"""Tests for scripts/check_history_completeness.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_completeness import main, run


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def _base_repo(root: Path) -> Path:
    _write_json(
        root / "ledger" / "idem_keys.json",
        {
            "version": 1,
            "keys": {
                "accept|42|alice@test": "2026-04-18T00:00:00Z",
                "escrow_create_42_t3_gauntlet": "2026-04-18T00:00:00Z",
            },
        },
    )
    _write_json(
        root / "ledger" / "trajectory_mints.json",
        {
            "version": 1,
            "trajectories": {"T3": {"next_slot": 22, "total_minted": 40}},
            "total_minted": 40,
            "mints": [
                {
                    "trajectory": "T3",
                    "slot": 21,
                    "amount": 40,
                    "agents": ["alice@test"],
                    "per_agent": [40],
                    "issue_or_pr": "#633",
                    "idem_key": "trajectory_mint|T3|21",
                }
            ],
        },
    )
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-18T00:00:00Z",
            },
            {
                "op": "escrow_create",
                "issue": 42,
                "amount": 10,
                "from": "agent0@system",
                "idem_key": "escrow_create_42_t3_gauntlet",
                "ts": "2026-04-18T00:00:00Z",
            },
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 21,
                "amount": 40,
                "issue": 633,
                "agents": ["alice@test"],
                "per_agent": [40],
                "timestamp": "2026-04-18T00:00:00Z",
            },
        ],
    )
    return root


def test_clean_state_passes(temp_repo: Path, capsys) -> None:
    root = _base_repo(temp_repo)

    report, passed = run(root)
    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert passed is True
    assert report["status"] == "PASS"
    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert all(check["status"] == "PASS" for check in report["checks"])


def test_missing_accept_entry_fails(temp_repo: Path) -> None:
    root = _base_repo(temp_repo)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "op": "escrow_create",
                "issue": 42,
                "amount": 10,
                "from": "agent0@system",
                "idem_key": "escrow_create_42_t3_gauntlet",
                "ts": "2026-04-18T00:00:00Z",
            },
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 21,
                "amount": 40,
                "issue": 633,
                "agents": ["alice@test"],
                "per_agent": [40],
                "timestamp": "2026-04-18T00:00:00Z",
            },
        ],
    )

    report, passed = run(root)

    accept_check = next(check for check in report["checks"] if check["name"] == "accept_payment_history")
    assert passed is False
    assert report["status"] == "FAIL"
    assert accept_check["status"] == "FAIL"
    assert accept_check["missing"][0]["issue"] == "42"
    assert accept_check["missing"][0]["agent"] == "alice@test"


def test_missing_escrow_create_entry_fails(temp_repo: Path) -> None:
    root = _base_repo(temp_repo)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-18T00:00:00Z",
            },
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 21,
                "amount": 40,
                "issue": 633,
                "agents": ["alice@test"],
                "per_agent": [40],
                "timestamp": "2026-04-18T00:00:00Z",
            },
        ],
    )

    report, passed = run(root)

    escrow_check = next(check for check in report["checks"] if check["name"] == "escrow_create_history")
    assert passed is False
    assert report["status"] == "FAIL"
    assert escrow_check["status"] == "FAIL"
    assert escrow_check["missing"][0]["issue"] == "42"
    assert escrow_check["missing"][0]["write_id"] == "escrow_create_42_t3_gauntlet"


def test_missing_mint_entry_fails(temp_repo: Path) -> None:
    root = _base_repo(temp_repo)
    _write_history(
        root / "ledger" / "history" / "2026-04-18.jsonl",
        [
            {
                "type": "accept",
                "issue": 42,
                "agent": "alice@test",
                "amount": 10,
                "timestamp": "2026-04-18T00:00:00Z",
            },
            {
                "op": "escrow_create",
                "issue": 42,
                "amount": 10,
                "from": "agent0@system",
                "idem_key": "escrow_create_42_t3_gauntlet",
                "ts": "2026-04-18T00:00:00Z",
            },
        ],
    )

    report, passed = run(root)

    mint_check = next(check for check in report["checks"] if check["name"] == "trajectory_mint_history")
    assert passed is False
    assert report["status"] == "FAIL"
    assert mint_check["status"] == "FAIL"
    assert mint_check["missing"][0]["trajectory"] == "T3"
    assert mint_check["missing"][0]["slot"] == 21
