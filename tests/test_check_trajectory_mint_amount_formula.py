"""Tests for scripts/check_trajectory_mint_amount_formula.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_trajectory_mint_amount_formula import run_check  # noqa: E402


def _write_trajectory_mints(
    root: Path, mints: list[dict], *, total_minted: int = 0
) -> Path:
    """Write a minimal `ledger/trajectory_mints.json` fixture."""
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(
            {
                "version": 1,
                "total_minted": total_minted,
                "trajectories": {
                    "T1": {"name": "State Integrity", "next_slot": 1, "total_minted": 0}
                },
                "mints": mints,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _write_history(root: Path, events: list[dict]) -> Path:
    """Write a minimal `ledger/history` fixture."""
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    with (history / "2026-01-01.jsonl").open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return root


def _make_mint(slot: int, amount: int, trajectory: str = "T1") -> dict:
    return {"trajectory": trajectory, "slot": slot, "amount": amount}


def _make_history_mint(
    slot: int,
    amount: int,
    trajectory: str = "T1",
    *,
    issue: int | None = None,
) -> dict:
    event: dict = {
        "type": "trajectory_mint",
        "trajectory": trajectory,
        "slot": slot,
        "amount": amount,
        "agents": ["agent@example"],
        "per_agent": [amount],
        "timestamp": "2026-01-01T00:00:00Z",
    }
    if issue is not None:
        event["issue"] = issue
    return event


def test_clean_formula_passes(temp_repo: Path) -> None:
    _write_trajectory_mints(
        temp_repo,
        [_make_mint(1, 20), _make_mint(2, 21)],
        total_minted=41,
    )
    _write_history(
        temp_repo,
        [_make_history_mint(1, 20), _make_history_mint(2, 21, issue=200)],
    )

    result = run_check(temp_repo)
    assert result["status"] == "PASS"
    assert result["mint_violations"] == []
    assert result["history_violations"] == []
    assert result["summary"]["total_violations"] == 0


def test_mint_amount_violation(temp_repo: Path) -> None:
    _write_trajectory_mints(temp_repo, [_make_mint(2, 99)], total_minted=99)
    _write_history(temp_repo, [_make_history_mint(2, 21)])

    result = run_check(temp_repo)
    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 1
    violation = result["mint_violations"][0]
    assert violation["trajectory"] == "T1"
    assert violation["slot"] == 2
    assert violation["amount"] == 99
    assert violation["expected_amount"] == 21


def test_history_amount_violation(temp_repo: Path) -> None:
    _write_trajectory_mints(temp_repo, [_make_mint(1, 20)], total_minted=20)
    _write_history(temp_repo, [_make_history_mint(1, 40)])

    result = run_check(temp_repo)
    assert result["status"] == "FAIL"
    assert len(result["history_violations"]) == 1
    violation = result["history_violations"][0]
    assert violation["trajectory"] == "T1"
    assert violation["slot"] == 1
    assert violation["amount"] == 40
    assert violation["expected_amount"] == 20


def test_invalid_mint_record_is_flagged(temp_repo: Path) -> None:
    _write_trajectory_mints(
        temp_repo,
        [
            {"trajectory": "T1", "slot": 1, "amount": 20},
            {"trajectory": "T1", "slot": "bad", "amount": 20},
            {"trajectory": "T1", "slot": 3, "amount": "wrong"},
        ],
    )
    _write_history(temp_repo, [])

    result = run_check(temp_repo)
    assert result["status"] == "FAIL"
    assert len(result["mint_violations"]) == 2
    assert {v["detail"] for v in result["mint_violations"]} == {
        "slot is not an integer: 'bad'",
        "amount is not an integer: 'wrong'",
    }


def test_non_trajectory_events_are_ignored(temp_repo: Path) -> None:
    _write_trajectory_mints(temp_repo, [_make_mint(1, 20)], total_minted=20)
    _write_history(
        temp_repo,
        [
            _make_history_mint(1, 20),
            {"type": "payment", "trajectory": "T1", "slot": 2, "amount": 21},
        ],
    )

    result = run_check(temp_repo)
    assert result["status"] == "PASS"
    assert result["history_violations"] == []


def test_main_load_error_returns_fail(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (temp_repo / "ledger" / "trajectory_mints.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (temp_repo / "ledger" / "trajectory_mints.json").write_text(
        "{bad json}", encoding="utf-8"
    )
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    from check_trajectory_mint_amount_formula import main  # noqa: WPS433

    rc = main(["--root", str(temp_repo)])
    captured = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert captured["status"] == "FAIL"


def test_main_bad_mints_shape_returns_fail(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (temp_repo / "ledger" / "trajectory_mints.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (temp_repo / "ledger" / "trajectory_mints.json").write_text(
        json.dumps({"mints": {"slot": 1, "amount": 20}}, indent=2),
        encoding="utf-8",
    )
    (temp_repo / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    from check_trajectory_mint_amount_formula import main  # noqa: WPS433

    rc = main(["--root", str(temp_repo)])
    captured = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert captured["status"] == "FAIL"
    assert captured["summary"]["error"].startswith("trajectory_mints.json.mints is not a list")


def test_real_ledger_passes() -> None:
    result = run_check(Path(__file__).parent.parent)
    assert result["status"] == "PASS", json.dumps(result, indent=2)
