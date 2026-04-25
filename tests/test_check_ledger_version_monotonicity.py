from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_ledger_version_monotonicity as checker  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_ledger_files(
    root: Path,
    *,
    balances_version: Any = 10,
    escrows_version: Any = 10,
    idem_keys_version: Any = 10,
    omit_balances_version: bool = False,
    omit_escrows_version: bool = False,
    omit_idem_keys_version: bool = False,
) -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)

    def _build(version_val: Any, omit: bool) -> dict[str, Any]:
        obj: dict[str, Any] = {"agents": {}}
        if not omit:
            obj["version"] = version_val
        return obj

    (ledger / "balances.json").write_text(
        json.dumps(_build(balances_version, omit_balances_version)), encoding="utf-8"
    )
    (ledger / "escrows.json").write_text(
        json.dumps(_build(escrows_version, omit_escrows_version)), encoding="utf-8"
    )
    (ledger / "idem_keys.json").write_text(
        json.dumps(_build(idem_keys_version, omit_idem_keys_version)), encoding="utf-8"
    )


def _write_history(root: Path, events: list[dict[str, Any]], filename: str = "2026-04-24.jsonl") -> None:
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e) for e in events) + "\n"
    (history / filename).write_text(lines, encoding="utf-8")


def _payment_events(n: int) -> list[dict[str, Any]]:
    return [{"type": "payment", "amount": 5, "agent": "agent0@system"} for _ in range(n)]


def _registration_events(n: int) -> list[dict[str, Any]]:
    return [{"type": "registration", "agent": f"Claude-{i}@claude"} for i in range(n)]


def _escrow_create_events(n: int) -> list[dict[str, Any]]:
    return [{"type": "escrow_create", "author": "agent0@system", "amount": 10} for _ in range(n)]


# ---------------------------------------------------------------------------
# Spec-required tests
# ---------------------------------------------------------------------------

def test_version_present_and_positive_passes(tmp_path: Path) -> None:
    """All three files have version=1 (positive int) with zero history → PASS."""
    _write_ledger_files(tmp_path, balances_version=1, escrows_version=1, idem_keys_version=1)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    _, passed = checker.check(tmp_path)

    assert passed is True


def test_version_missing_fails(tmp_path: Path) -> None:
    """balances.json has no version field → FAIL."""
    _write_ledger_files(tmp_path, omit_balances_version=True)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report, passed = checker.check(tmp_path)

    assert passed is False
    failed_files = [v["file"] for v in report["violations"]]
    assert any("balances" in f for f in failed_files)


def test_version_string_not_int_fails(tmp_path: Path) -> None:
    """version="140" (a string, not an int) → FAIL."""
    _write_ledger_files(tmp_path, balances_version="140")
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report, passed = checker.check(tmp_path)

    assert passed is False
    assert any("balances" in v["file"] for v in report["violations"])
    reasons = " ".join(v["reason"] for v in report["violations"])
    assert "positive integer" in reasons


def test_version_lower_than_write_event_count_fails(tmp_path: Path) -> None:
    """version=1 but there are 50 payment events in history → FAIL (1 < 50)."""
    _write_ledger_files(tmp_path, balances_version=1, escrows_version=100, idem_keys_version=100)
    _write_history(tmp_path, _payment_events(50))

    report, passed = checker.check(tmp_path)

    assert passed is False
    violated = [v for v in report["violations"] if "balances" in v["file"]]
    assert len(violated) == 1
    assert violated[0]["version"] == 1
    assert violated[0]["write_event_count"] == 50
    assert "regression" in violated[0]["reason"]


def test_zero_history_events_passes(tmp_path: Path) -> None:
    """No history events exist → event counts are all 0 → any positive version passes."""
    _write_ledger_files(tmp_path, balances_version=1, escrows_version=1, idem_keys_version=1)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    _, passed = checker.check(tmp_path)

    assert passed is True


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

def test_version_zero_fails(tmp_path: Path) -> None:
    """version=0 is not a positive integer → FAIL."""
    _write_ledger_files(tmp_path, idem_keys_version=0)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report, passed = checker.check(tmp_path)

    assert passed is False
    assert any("idem_keys" in v["file"] for v in report["violations"])


def test_version_null_fails(tmp_path: Path) -> None:
    """version=null in JSON (None in Python) → FAIL."""
    _write_ledger_files(tmp_path, escrows_version=None)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    report, passed = checker.check(tmp_path)

    assert passed is False
    assert any("escrows" in v["file"] for v in report["violations"])


def test_version_exactly_equals_event_count_passes(tmp_path: Path) -> None:
    """version == event_count satisfies version >= event_count → PASS.

    registration counts for both balances (payment+accept+registration) and
    idem_keys (registration+gauntlet_mint), so balances event_count = 5+2 = 7.
    """
    _write_ledger_files(tmp_path, balances_version=7, escrows_version=3, idem_keys_version=2)
    # 5 payment + 2 registration → balances event_count=7; version=7 → pass
    # 3 escrow_create → escrows event_count=3; version=3 → pass
    # 2 registration → idem_keys event_count=2; version=2 → pass
    _write_history(tmp_path, _payment_events(5) + _escrow_create_events(3) + _registration_events(2))

    _, passed = checker.check(tmp_path)

    assert passed is True


def test_version_above_event_count_passes(tmp_path: Path) -> None:
    """version much higher than event_count is fine (multiple writes per event)."""
    _write_ledger_files(tmp_path, balances_version=200, escrows_version=200, idem_keys_version=200)
    _write_history(tmp_path, _payment_events(10) + _escrow_create_events(5) + _registration_events(3))

    _, passed = checker.check(tmp_path)

    assert passed is True


def test_all_three_files_checked_independently(tmp_path: Path) -> None:
    """Only escrows.json regresses; balances and idem_keys are fine."""
    _write_ledger_files(tmp_path, balances_version=100, escrows_version=1, idem_keys_version=100)
    # 20 escrow_create events but escrows.version=1 → FAIL for escrows only
    _write_history(tmp_path, _escrow_create_events(20))

    report, passed = checker.check(tmp_path)

    assert passed is False
    violated_files = [v["file"] for v in report["violations"]]
    assert any("escrows" in f for f in violated_files)
    # balances and idem_keys must NOT appear in violations
    assert not any("balances" in f for f in violated_files)
    assert not any("idem_keys" in f for f in violated_files)


def test_missing_history_dir_treated_as_zero_events(tmp_path: Path) -> None:
    """No ledger/history directory → all event counts are 0 → version=1 passes."""
    _write_ledger_files(tmp_path, balances_version=1, escrows_version=1, idem_keys_version=1)
    # deliberately do NOT create ledger/history

    _, passed = checker.check(tmp_path)

    assert passed is True


def test_report_contains_event_count_per_file(tmp_path: Path) -> None:
    """Report files list shows the write_event_count for each file."""
    _write_ledger_files(tmp_path, balances_version=10, escrows_version=10, idem_keys_version=10)
    _write_history(tmp_path, _payment_events(3) + _escrow_create_events(7))

    report, passed = checker.check(tmp_path)

    assert passed is True
    counts_by_file = {entry["file"]: entry["write_event_count"] for entry in report["files"]}
    assert counts_by_file["ledger/balances.json"] == 3   # 3 payment events
    assert counts_by_file["ledger/escrows.json"] == 7    # 7 escrow_create events
    assert counts_by_file["ledger/idem_keys.json"] == 0  # no registration/gauntlet_mint


def test_corrupt_history_lines_skipped(tmp_path: Path) -> None:
    """Invalid JSON lines in history do not crash the check."""
    _write_ledger_files(tmp_path, balances_version=5, escrows_version=5, idem_keys_version=5)
    history = tmp_path / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / "2026-04-24.jsonl").write_text(
        "not valid json\n"
        + json.dumps({"type": "payment", "amount": 5}) + "\n"
        + "{broken\n",
        encoding="utf-8",
    )

    _, passed = checker.check(tmp_path)

    assert passed is True  # 1 payment event, balances version=5 >= 1


def test_main_exit_zero_on_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() returns 0 when all checks pass."""
    _write_ledger_files(tmp_path, balances_version=5, escrows_version=5, idem_keys_version=5)
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        sys, "argv", ["check_ledger_version_monotonicity.py", "--root", str(tmp_path)]
    )

    import io
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    exit_code = checker.main()

    assert exit_code == 0
    output = json.loads(captured.getvalue())
    assert output["status"] == "PASS"


def test_main_exit_one_on_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() returns 1 when a version regression is detected."""
    _write_ledger_files(tmp_path, balances_version=1, escrows_version=50, idem_keys_version=50)
    _write_history(tmp_path, _payment_events(30))  # 30 > 1

    monkeypatch.setattr(
        sys, "argv", ["check_ledger_version_monotonicity.py", "--root", str(tmp_path)]
    )

    import io
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    exit_code = checker.main()

    assert exit_code == 1
    output = json.loads(captured.getvalue())
    assert output["status"] == "FAIL"
    assert len(output["violations"]) >= 1
