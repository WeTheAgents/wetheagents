"""Tests for scripts/check_gauntlet_cycle_completeness.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_gauntlet_cycle_completeness import run_check  # noqa: E402


def _write_trajectory_mints(root: Path, mints: list[dict]) -> Path:
    """Write a minimal ledger/trajectory_mints.json fixture."""
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(
            {
                "version": 1,
                "total_minted": 0,
                "trajectories": {
                    t: {"name": t, "next_slot": 1, "total_minted": 0}
                    for t in ("T1", "T2", "T3", "T4", "T5", "T6")
                },
                "mints": mints,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _full_cycle(cycle: int, trajectories: list[str] | None = None) -> list[dict]:
    """Return one mint per trajectory for the given slot/cycle number."""
    trajs = trajectories or ["T1", "T2", "T3", "T4", "T5"]
    return [{"trajectory": t, "slot": cycle, "amount": 19 + cycle} for t in trajs]


# ---------------------------------------------------------------------------
# Acceptance criteria tests
# ---------------------------------------------------------------------------


def test_all_cycles_complete_passes(temp_repo: Path) -> None:
    """All T1-T5 present in every cycle → PASS, no violations."""
    mints = _full_cycle(1) + _full_cycle(2) + _full_cycle(3)
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["summary"]["complete_cycles"] == 3
    assert result["summary"]["total_violations"] == 0


def test_cycle_missing_t3_fails(temp_repo: Path) -> None:
    """Cycle 2 has T1, T2, T4, T5 but T3 skipped it (T3 has slot 3) → FAIL."""
    mints = (
        _full_cycle(1)
        + [  # Cycle 2: T3 absent, all others present
            {"trajectory": "T1", "slot": 2, "amount": 21},
            {"trajectory": "T2", "slot": 2, "amount": 21},
            {"trajectory": "T4", "slot": 2, "amount": 21},
            {"trajectory": "T5", "slot": 2, "amount": 21},
        ]
        + _full_cycle(3)  # T3 minted slot 3, proving it passed cycle 2
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["cycle"] == 2
    assert "T3" in v["missing"]
    assert "T3" in v["skipped_by"]
    assert result["summary"]["total_violations"] == 1


def test_latest_cycle_incomplete_is_warning_not_fail(temp_repo: Path) -> None:
    """Highest cycle partially minted → warning, exit 0 (in-progress)."""
    mints = (
        _full_cycle(1)
        + _full_cycle(2)
        + [  # Cycle 3 (max): only T1 and T2 so far — T3-T5 not yet reached
            {"trajectory": "T1", "slot": 3, "amount": 22},
            {"trajectory": "T2", "slot": 3, "amount": 22},
        ]
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["cycle"] == 3
    assert "T3" in w["missing"]
    assert "T4" in w["missing"]
    assert "T5" in w["missing"]
    assert result["summary"]["in_progress_cycle"] == 3


def test_t6_absence_ignored(temp_repo: Path) -> None:
    """T6 mints do not affect cycle completeness check."""
    # T1-T5 form two complete cycles; T6 minted extra slots at will
    mints = (
        _full_cycle(1)
        + _full_cycle(2)
        + [
            {"trajectory": "T6", "slot": 1, "amount": 20},
            {"trajectory": "T6", "slot": 5, "amount": 24},
            {"trajectory": "T6", "slot": 10, "amount": 29},
        ]
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert result["violations"] == []
    # T6 slots 1, 5, 10 must not influence the cycle map
    assert result["summary"]["total_cycles_checked"] == 2


def test_real_ledger_passes() -> None:
    """Live repository must exit 0 (latest in-progress cycle treated as warning)."""
    result = run_check(Path(__file__).parent.parent)
    assert result["status"] == "PASS", json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Additional robustness tests
# ---------------------------------------------------------------------------


def test_empty_mints_passes(temp_repo: Path) -> None:
    """No mints at all → PASS with empty summary."""
    _write_trajectory_mints(temp_repo, [])

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["warnings"] == []
    assert result["summary"]["total_cycles_checked"] == 0


def test_single_partial_cycle_is_warning(temp_repo: Path) -> None:
    """Only one cycle exists and it's incomplete → warning, not violation."""
    mints = [
        {"trajectory": "T1", "slot": 1, "amount": 20},
        {"trajectory": "T2", "slot": 1, "amount": 20},
    ]
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "PASS"
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["cycle"] == 1
    assert result["summary"]["in_progress_cycle"] == 1


def test_gap_middle_trajectory_is_violation(temp_repo: Path) -> None:
    """T5 skips slot 2 but has slot 3 → cycle 2 is a violation."""
    mints = (
        _full_cycle(1)
        + [  # Cycle 2: T5 absent
            {"trajectory": "T1", "slot": 2, "amount": 21},
            {"trajectory": "T2", "slot": 2, "amount": 21},
            {"trajectory": "T3", "slot": 2, "amount": 21},
            {"trajectory": "T4", "slot": 2, "amount": 21},
        ]
        + _full_cycle(3)  # T5 slot 3 proves T5 passed cycle 2
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["cycle"] == 2
    assert result["violations"][0]["skipped_by"] == ["T5"]


def test_multiple_gaps_multiple_violations(temp_repo: Path) -> None:
    """T2 skips cycle 2 and T4 skips cycle 3 → two violations."""
    mints = (
        _full_cycle(1)
        + [  # Cycle 2: T2 absent
            {"trajectory": "T1", "slot": 2, "amount": 21},
            {"trajectory": "T3", "slot": 2, "amount": 21},
            {"trajectory": "T4", "slot": 2, "amount": 21},
            {"trajectory": "T5", "slot": 2, "amount": 21},
        ]
        + [  # Cycle 3: T4 absent; T2 now present (proves it passed cycle 2)
            {"trajectory": "T1", "slot": 3, "amount": 22},
            {"trajectory": "T2", "slot": 3, "amount": 22},
            {"trajectory": "T3", "slot": 3, "amount": 22},
            {"trajectory": "T5", "slot": 3, "amount": 22},
        ]
        + _full_cycle(4)  # T4 slot 4 proves it passed cycle 3
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    assert result["status"] == "FAIL"
    assert len(result["violations"]) == 2
    violated_cycles = {v["cycle"] for v in result["violations"]}
    assert violated_cycles == {2, 3}


def test_malformed_slot_is_skipped(temp_repo: Path) -> None:
    """Mints with non-integer or non-positive slots are silently skipped."""
    mints = (
        _full_cycle(1)
        + [
            {"trajectory": "T1", "slot": "bad", "amount": 21},
            {"trajectory": "T2", "slot": -1, "amount": 21},
            {"trajectory": "T3", "slot": True, "amount": 21},  # bool is not int here
        ]
    )
    _write_trajectory_mints(temp_repo, mints)

    result = run_check(temp_repo)

    # Only cycle 1 is fully present; malformed records ignored.
    assert result["summary"]["total_cycles_checked"] == 1
    assert result["summary"]["complete_cycles"] == 1


def test_load_error_returns_fail(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bad JSON in trajectory_mints.json → FAIL with error in summary."""
    ledger = temp_repo / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text("{bad json}", encoding="utf-8")

    from check_gauntlet_cycle_completeness import main  # noqa: WPS433

    rc = main(["--root", str(temp_repo)])
    captured = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert captured["status"] == "FAIL"
    assert "error" in captured["summary"]


def test_main_bad_mints_shape_returns_fail(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """mints is not a list → FAIL with error in summary."""
    ledger = temp_repo / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": {"trajectory": "T1", "slot": 1}}),
        encoding="utf-8",
    )

    from check_gauntlet_cycle_completeness import main  # noqa: WPS433

    rc = main(["--root", str(temp_repo)])
    captured = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert captured["status"] == "FAIL"
    assert captured["summary"]["error"].startswith(
        "trajectory_mints.json.mints is not a list"
    )
