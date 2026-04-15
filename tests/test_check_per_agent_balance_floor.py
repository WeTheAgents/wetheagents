from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_per_agent_balance_floor import main, replay, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _make_root(root: Path, events_by_file: dict[str, list[dict]]) -> Path:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    for filename, events in events_by_file.items():
        _write_jsonl(history_dir / filename, events)
    return root


def _violations(result: dict) -> list[dict]:
    return result["violations"]


def _violating_agents(result: dict) -> set[str]:
    return {v["agent"] for v in result["violations"]}


# ---------------------------------------------------------------------------
# Test 1: Single payment to agent → PASS
# ---------------------------------------------------------------------------

def test_single_payment_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []
    assert "checks" in result
    assert "summary" in result


# ---------------------------------------------------------------------------
# Test 2: Escrow by agent with sufficient balance → PASS
# ---------------------------------------------------------------------------

def test_escrow_with_sufficient_balance_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 200,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 150,
                "timestamp": "2026-04-01T01:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 3: Escrow by agent with zero balance → FAIL
# ---------------------------------------------------------------------------

def test_escrow_with_zero_balance_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 50,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "FAIL"
    assert passed is False
    assert len(_violations(result)) == 1
    v = _violations(result)[0]
    assert v["agent"] == "alice@test"
    assert v["event_type"] == "escrow"
    assert v["balance_at_event"] == -50


# ---------------------------------------------------------------------------
# Test 4: Payment then escrow within budget → PASS
# ---------------------------------------------------------------------------

def test_payment_then_escrow_within_budget_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-04-01T01:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 5: Payment then overspend via escrow → FAIL
# ---------------------------------------------------------------------------

def test_payment_then_overspend_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 150,
                "timestamp": "2026-04-01T01:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "FAIL"
    assert passed is False
    assert len(_violations(result)) == 1
    v = _violations(result)[0]
    assert v["agent"] == "alice@test"
    assert v["balance_at_event"] == -50


# ---------------------------------------------------------------------------
# Test 6: agent0 genesis balance allows escrow from initial 10000 → PASS
# ---------------------------------------------------------------------------

def test_agent0_genesis_escrow_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "escrow",
                "agent": "agent0@system",
                "amount": 500,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 7: Multiple agents, only one goes negative → FAIL, report only violator
# ---------------------------------------------------------------------------

def test_multiple_agents_only_violator_reported(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "payment",
                "agent": "bob@test",
                "amount": 100,
                "timestamp": "2026-04-01T01:00:00Z",
            },
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 200,
                "timestamp": "2026-04-01T02:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "FAIL"
    assert passed is False
    assert _violating_agents(result) == {"alice@test"}
    assert "bob@test" not in _violating_agents(result)


# ---------------------------------------------------------------------------
# Test 8: Empty history → PASS
# ---------------------------------------------------------------------------

def test_empty_history_passes(temp_repo: Path) -> None:
    # temp_repo fixture already creates an empty history dir
    result, passed = run(temp_repo)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []
    assert "Replayed 0 balance events" in result["summary"]


# ---------------------------------------------------------------------------
# Test 9: trajectory_mint credit raises balance → PASS
# ---------------------------------------------------------------------------

def test_trajectory_mint_credit_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "trajectory_mint",
                "agent": "alice@test",
                "amount": 30,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 10: escrow_return restores balance (list trajectory_mint format) → PASS
# ---------------------------------------------------------------------------

def test_trajectory_mint_list_format_and_escrow_return_passes(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "trajectory_mint",
                "agents": ["alice@test", "bob@test"],
                "per_agent": [20, 10],
                "amount": 30,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 20,
                "issue": 42,
                "timestamp": "2026-04-01T01:00:00Z",
            },
            {
                "type": "escrow_return",
                "agent": "alice@test",
                "amount": 20,
                "issue": 42,
                "timestamp": "2026-04-01T02:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 11: hello_world_mint credit → PASS; escrow_create debit → FAIL if over
# ---------------------------------------------------------------------------

def test_hello_world_mint_then_escrow_create_overspend_fails(temp_repo: Path) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "hello_world_mint",
                "agent": "carol@test",
                "amount": 10,
                "timestamp": "2026-04-01T00:00:00Z",
            },
            {
                "type": "escrow_create",
                "agent": "carol@test",
                "amount": 15,
                "timestamp": "2026-04-01T01:00:00Z",
            },
        ]
    })

    result, passed = run(root)

    assert result["status"] == "FAIL"
    assert passed is False
    v = _violations(result)[0]
    assert v["agent"] == "carol@test"
    assert v["balance_at_event"] == -5


# ---------------------------------------------------------------------------
# Test 12: economy_reset clears pre-reset violations and resets to 10000 → PASS
# ---------------------------------------------------------------------------

def test_economy_reset_clears_violations(temp_repo: Path) -> None:
    # alice escrows before having WEA (pre-reset violation), then reset happens,
    # then clean history — final result should PASS because reset cleared violations.
    root = _make_root(temp_repo, {
        "2026-03-01.jsonl": [
            {
                "type": "escrow",
                "agent": "alice@test",
                "amount": 50,
                "timestamp": "2026-03-01T00:00:00Z",
            },
        ],
        "2026-03-02.jsonl": [
            {
                "type": "economy_reset",
                "new_supply": 10000,
                "timestamp": "2026-03-02T00:00:00Z",
            },
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 100,
                "timestamp": "2026-03-02T01:00:00Z",
            },
        ],
    })

    result, passed = run(root)

    assert result["status"] == "PASS"
    assert passed is True
    assert _violations(result) == []


# ---------------------------------------------------------------------------
# Test 13: main() prints JSON and returns 0 on PASS
# ---------------------------------------------------------------------------

def test_main_returns_zero_and_prints_json(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "payment",
                "agent": "alice@test",
                "amount": 50,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert "checks" in payload
    assert "violations" in payload
    assert "summary" in payload


# ---------------------------------------------------------------------------
# Test 14: main() returns 1 on FAIL
# ---------------------------------------------------------------------------

def test_main_returns_one_on_fail(temp_repo: Path, capsys) -> None:
    root = _make_root(temp_repo, {
        "2026-04-01.jsonl": [
            {
                "type": "escrow",
                "agent": "bob@test",
                "amount": 99,
                "timestamp": "2026-04-01T00:00:00Z",
            },
        ]
    })

    exit_code = main(["--root", str(root)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["agent"] == "bob@test"


# ---------------------------------------------------------------------------
# Test 15: replay() with empty events list → PASS
# ---------------------------------------------------------------------------

def test_replay_empty_events() -> None:
    result = replay([])

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert "checks" in result
    assert "summary" in result
