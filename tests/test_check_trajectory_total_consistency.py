"""Tests for scripts/check_trajectory_total_consistency.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_trajectory_total_consistency import (  # noqa: E402
    build_summary,
    find_mismatches,
    run_check,
    sum_mint_amounts_by_trajectory,
)


def make_trajectory_mints(root: Path, payload: dict) -> Path:
    """Write a minimal trajectory_mints.json ledger fixture."""
    ledger_dir = root / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "trajectory_mints.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def clean_payload() -> dict:
    """Return a minimal internally consistent trajectory_mints payload."""
    return {
        "version": 1,
        "total_minted": 61,
        "trajectories": {
            "T1": {"name": "One", "next_slot": 3, "total_minted": 41},
            "T2": {"name": "Two", "next_slot": 2, "total_minted": 20},
        },
        "mints": [
            {"trajectory": "T1", "slot": 1, "amount": 20},
            {"trajectory": "T1", "slot": 2, "amount": 21},
            {"trajectory": "T2", "slot": 1, "amount": 20},
        ],
    }


def test_clean_payload_passes(temp_repo: Path) -> None:
    root = make_trajectory_mints(temp_repo, clean_payload())
    payload = run_check(root)
    assert payload["status"] == "PASS"
    assert payload["mismatches"] == []
    assert payload["summary"]["trajectory_count"] == 2
    assert payload["summary"]["mint_count"] == 3
    assert payload["summary"]["mismatch_count"] == 0


def test_detects_trajectory_total_mismatch(temp_repo: Path) -> None:
    payload = clean_payload()
    payload["trajectories"]["T1"]["total_minted"] = 999
    root = make_trajectory_mints(temp_repo, payload)

    result = run_check(root)

    assert result["status"] == "FAIL"
    assert {
        "type": "trajectory_total_mismatch",
        "trajectory": "T1",
        "declared_total_minted": 999,
        "computed_total_minted": 41,
    } in result["mismatches"]


def test_detects_top_level_total_mismatch(temp_repo: Path) -> None:
    payload = clean_payload()
    payload["total_minted"] = 999
    root = make_trajectory_mints(temp_repo, payload)

    result = run_check(root)

    assert result["status"] == "FAIL"
    assert {
        "type": "top_level_total_mismatch",
        "declared_total_minted": 999,
        "summed_trajectory_total_minted": 61,
    } in result["mismatches"]


def test_detects_unknown_trajectory_in_mints(temp_repo: Path) -> None:
    payload = clean_payload()
    payload["mints"].append({"trajectory": "T9", "slot": 1, "amount": 50})
    root = make_trajectory_mints(temp_repo, payload)

    result = run_check(root)

    assert result["status"] == "FAIL"
    assert {
        "type": "unknown_trajectory_in_mints",
        "trajectory": "T9",
        "computed_total_minted": 50,
    } in result["mismatches"]


def test_sum_mint_amounts_groups_by_trajectory() -> None:
    totals = sum_mint_amounts_by_trajectory(
        [
            {"trajectory": "T1", "amount": 20},
            {"trajectory": "T1", "amount": 21},
            {"trajectory": "T2", "amount": 5},
        ]
    )
    assert totals == {"T1": 41, "T2": 5}


def test_build_summary_reports_declared_and_computed_totals() -> None:
    summary = build_summary(clean_payload())
    assert summary == {
        "trajectory_count": 2,
        "mint_count": 3,
        "top_level_total_minted": 61,
        "summed_trajectory_total_minted": 61,
        "summed_mint_amounts": 61,
    }


def test_find_mismatches_can_report_multiple_problems() -> None:
    payload = clean_payload()
    payload["trajectories"]["T2"]["total_minted"] = 25
    payload["total_minted"] = 60
    mismatches = find_mismatches(payload)
    mismatch_types = {item["type"] for item in mismatches}
    assert mismatch_types == {"trajectory_total_mismatch", "top_level_total_mismatch"}


def test_real_ledger_passes() -> None:
    root = Path(__file__).parent.parent
    payload = run_check(root)
    assert payload["status"] == "PASS", json.dumps(payload, indent=2)


def test_main_returns_json_fail_on_invalid_file(
    temp_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger_dir = temp_repo / "ledger"
    (ledger_dir / "trajectory_mints.json").write_text("{bad json}", encoding="utf-8")

    from check_trajectory_total_consistency import main  # noqa: WPS433

    rc = main(["--root", str(temp_repo)])
    out = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert out["status"] == "FAIL"
    assert out["mismatches"][0]["type"] == "load_error"
