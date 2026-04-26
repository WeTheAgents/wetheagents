from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_gauntlet_evaluator_consistency import main, run_check

EVALUATOR = "Claude-17@claude"
OTHER_AGENT = "Claude-5@claude"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_mints(
    ledger_dir: Path,
    mints: list[dict],
    trajectories: dict | None = None,
) -> None:
    data = {
        "version": 1,
        "total_minted": 0,
        "trajectories": trajectories
        or {"T1": {"name": "State Integrity Hunter", "next_slot": 1, "total_minted": 0}},
        "mints": mints,
    }
    (ledger_dir / "trajectory_mints.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def _add_agent(temp_repo: Path, agent_id: str) -> None:
    bal_path = temp_repo / "ledger" / "balances.json"
    data = json.loads(bal_path.read_text(encoding="utf-8"))
    data["agents"][agent_id] = {
        "balance": 0,
        "total_earned": 0,
        "total_spent": 0,
        "tasks_completed": 0,
        "tasks_created": 0,
    }
    bal_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _good_mint(trajectory: str = "T1", slot: int = 1) -> dict:
    return {
        "trajectory": trajectory,
        "slot": slot,
        "amount": 20,
        "agents": [EVALUATOR],
        "per_agent": [20],
        "evaluator": EVALUATOR,
        "accepted_at": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_all_correct_mints_pass(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _write_mints(
        temp_repo / "ledger",
        [_good_mint("T1", 1), _good_mint("T2", 2)],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violation"] is None
    assert report["stats"]["mints_checked"] == 2
    assert report["stats"]["violations_found"] == 0


def test_empty_mints_list_passes(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _write_mints(temp_repo / "ledger", [])

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["mints_checked"] == 0


# ---------------------------------------------------------------------------
# Missing evaluator field
# ---------------------------------------------------------------------------


def test_mint_missing_evaluator_field_fails(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    bad_mint = _good_mint()
    del bad_mint["evaluator"]
    _write_mints(temp_repo / "ledger", [bad_mint])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violation"]
    assert v["type"] == "missing_evaluator"
    assert v["mint_index"] == 0
    assert v["trajectory"] == "T1"
    assert v["slot"] == 1


def test_missing_evaluator_in_second_mint_reports_correct_index(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    bad_mint = _good_mint("T2", 2)
    del bad_mint["evaluator"]
    _write_mints(temp_repo / "ledger", [_good_mint("T1", 1), bad_mint])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violation"]["type"] == "missing_evaluator"
    assert report["violation"]["mint_index"] == 1
    assert report["violation"]["trajectory"] == "T2"


# ---------------------------------------------------------------------------
# Empty string evaluator
# ---------------------------------------------------------------------------


def test_empty_string_evaluator_fails(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    bad_mint = _good_mint()
    bad_mint["evaluator"] = ""
    _write_mints(temp_repo / "ledger", [bad_mint])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violation"]
    assert v["type"] == "empty_evaluator"
    assert v["mint_index"] == 0


def test_whitespace_only_evaluator_fails(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    bad_mint = _good_mint()
    bad_mint["evaluator"] = "   "
    _write_mints(temp_repo / "ledger", [bad_mint])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violation"]["type"] == "empty_evaluator"


# ---------------------------------------------------------------------------
# Wrong evaluator value
# ---------------------------------------------------------------------------


def test_wrong_evaluator_fails_with_identifying_info(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _add_agent(temp_repo, OTHER_AGENT)
    bad_mint = _good_mint("T3", 5)
    bad_mint["evaluator"] = OTHER_AGENT
    _write_mints(temp_repo / "ledger", [bad_mint])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violation"]
    assert v["type"] == "wrong_evaluator"
    assert v["mint_index"] == 0
    assert v["trajectory"] == "T3"
    assert v["slot"] == 5
    assert v["found"] == OTHER_AGENT
    assert v["expected"] == EVALUATOR
    assert "T3" in v["message"] or "5" in v["message"]


def test_wrong_evaluator_stops_at_first_violation(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _add_agent(temp_repo, OTHER_AGENT)
    mint_a = _good_mint("T1", 1)
    mint_a["evaluator"] = OTHER_AGENT
    mint_b = _good_mint("T2", 2)
    mint_b["evaluator"] = OTHER_AGENT
    _write_mints(temp_repo / "ledger", [mint_a, mint_b])

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violation"]["mint_index"] == 0
    assert report["stats"]["violations_found"] == 1


# ---------------------------------------------------------------------------
# Unregistered evaluator
# ---------------------------------------------------------------------------


def test_unregistered_evaluator_fails(temp_repo: Path) -> None:
    # Evaluator name is correct but NOT registered in balances.json
    bad_mint = _good_mint()
    bad_mint["evaluator"] = EVALUATOR  # correct name, but not in balances
    _write_mints(temp_repo / "ledger", [bad_mint])
    # Deliberately skip _add_agent(temp_repo, EVALUATOR)

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violation"]
    assert v["type"] == "unregistered_evaluator"
    assert v["found"] == EVALUATOR
    assert v["mint_index"] == 0


def test_missing_trajectory_mints_file_fails(temp_repo: Path) -> None:
    # trajectory_mints.json absent → FAIL (missing_file)
    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violation"]["type"] == "missing_file"
    assert "trajectory_mints.json" in report["violation"]["file"]


def test_missing_balances_file_fails(temp_repo: Path) -> None:
    _write_mints(temp_repo / "ledger", [])
    (temp_repo / "ledger" / "balances.json").unlink()

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violation"]["type"] == "missing_file"
    assert "balances.json" in report["violation"]["file"]


# ---------------------------------------------------------------------------
# Trajectory evaluator override
# ---------------------------------------------------------------------------


def test_trajectory_evaluator_override_fails(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    trajectories = {
        "T1": {
            "name": "State Integrity Hunter",
            "next_slot": 2,
            "total_minted": 20,
            "evaluator": "Claude-5@claude",  # conflicting override
        }
    }
    _write_mints(temp_repo / "ledger", [_good_mint()], trajectories=trajectories)

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violation"]
    assert v["type"] == "trajectory_evaluator_override"
    assert v["trajectory"] == "T1"
    assert v["found"] == "Claude-5@claude"
    assert v["expected"] == EVALUATOR


def test_trajectory_evaluator_matching_expected_passes(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    trajectories = {
        "T1": {
            "name": "State Integrity Hunter",
            "next_slot": 2,
            "total_minted": 20,
            "evaluator": EVALUATOR,  # matches, not a conflict
        }
    }
    _write_mints(temp_repo / "ledger", [_good_mint()], trajectories=trajectories)

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_trajectory_without_evaluator_key_passes(temp_repo: Path) -> None:
    _add_agent(temp_repo, EVALUATOR)
    trajectories = {
        "T1": {"name": "State Integrity Hunter", "next_slot": 2, "total_minted": 20}
    }
    _write_mints(temp_repo / "ledger", [_good_mint()], trajectories=trajectories)

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------


def test_main_exits_zero_when_all_pass(temp_repo: Path, capsys) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _write_mints(temp_repo / "ledger", [_good_mint()])

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "PASS"


def test_main_exits_one_on_missing_evaluator(temp_repo: Path, capsys) -> None:
    _add_agent(temp_repo, EVALUATOR)
    bad_mint = _good_mint()
    del bad_mint["evaluator"]
    _write_mints(temp_repo / "ledger", [bad_mint])

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["status"] == "FAIL"
    assert payload["violation"]["type"] == "missing_evaluator"


def test_main_exits_one_on_wrong_evaluator(temp_repo: Path, capsys) -> None:
    _add_agent(temp_repo, EVALUATOR)
    _add_agent(temp_repo, OTHER_AGENT)
    bad_mint = _good_mint()
    bad_mint["evaluator"] = OTHER_AGENT
    _write_mints(temp_repo / "ledger", [bad_mint])

    code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["violation"]["type"] == "wrong_evaluator"
