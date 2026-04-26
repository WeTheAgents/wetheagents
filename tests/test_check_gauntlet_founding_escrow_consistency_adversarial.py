"""Adversarial tests for scripts/check_gauntlet_founding_escrow_consistency.py.

Seven attack categories probing the script's detection capabilities:
1. Missing founding escrow — neighbor issues have escrows, target doesn't
2. Dangling escrow — escrow_return targets a different issue number
3. Double escrow, single return — implementation limitation (only last create tracked)
4. Wrong escrow amount — warns but does not fail
5. Empty history directory — no crash, 0 violations when no mints above cutoff
6. Forge attack — idem_key references correct issue, 'issue' field is mismatched
7. Bulk mixed states — 10 mints, 8 valid, 1 missing, 1 dangling → exactly 2 violations
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_gauntlet_founding_escrow_consistency import (  # noqa: E402
    LEGACY_CUTOFF,
    run_check,
)

# Issue numbers well above LEGACY_CUTOFF (600) so all are checked by default
_BASE = LEGACY_CUTOFF + 300  # 900


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_mints(root: Path, mints: list[dict]) -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "total_minted": 0,
        "trajectories": {
            t: {"name": t, "next_slot": 1, "total_minted": 0}
            for t in ("T1", "T2", "T3", "T4", "T5", "T6")
        },
        "mints": mints,
    }
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )


def _write_history(root: Path, events: list[dict]) -> None:
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(ev) for ev in events)
    (history / "2026-01-01.jsonl").write_text(lines + "\n", encoding="utf-8")


def _mint(trajectory: str, slot: int, issue: int) -> dict:
    return {"trajectory": trajectory, "slot": slot, "issue_or_pr": f"#{issue}"}


def _escrow_create(issue: int, slot: int) -> dict:
    return {
        "type": "escrow_create",
        "issue": issue,
        "amount": 19 + slot,
        "idem_key": f"escrow_create_gauntlet|{issue}",
    }


def _escrow_return(issue: int, slot: int) -> dict:
    return {
        "type": "escrow_return",
        "issue": issue,
        "amount": 19 + slot,
        "idem_key": f"escrow-return-{issue}",
    }


# ---------------------------------------------------------------------------
# Category 1: Missing founding escrow
# ---------------------------------------------------------------------------


def test_adv_missing_founding_escrow_neighbor_exists(tmp_path: Path) -> None:
    """Escrow creates exist for neighboring issues but NOT for the target — FAIL.

    Attack: rely on issue #900 and #902 having valid escrows to slip #901 past
    a naive range check. Script must key exactly on the mint's own issue number.
    """
    issue = _BASE + 1  # 901
    slot = 38
    mints = [_mint("T1", slot, issue)]
    events = [
        _escrow_create(issue - 1, slot),  # #900
        _escrow_return(issue - 1, slot),
        _escrow_create(issue + 1, slot),  # #902
        _escrow_return(issue + 1, slot),
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["type"] == "missing_escrow_create"
    assert result["failures"][0]["issue"] == issue


# ---------------------------------------------------------------------------
# Category 2: Dangling escrow
# ---------------------------------------------------------------------------


def test_adv_dangling_escrow_return_targets_wrong_issue(tmp_path: Path) -> None:
    """escrow_return uses a different issue number — target issue remains dangling.

    Attack: attacker returns an escrow under issue #903 to obscure that #902's
    escrow was never closed. Script must not allow cross-issue return credit.
    """
    issue = _BASE + 2  # 902
    other = _BASE + 3  # 903
    slot = 38
    mints = [_mint("T1", slot, issue)]
    events = [
        _escrow_create(issue, slot),  # create for #902
        _escrow_return(other, slot),  # return for #903 — wrong issue
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["type"] == "dangling_escrow"
    assert result["failures"][0]["issue"] == issue


# ---------------------------------------------------------------------------
# Category 3: Double escrow, single return
# ---------------------------------------------------------------------------


def test_adv_double_escrow_single_return_passes(tmp_path: Path) -> None:
    """Two escrow_create for the same issue + one escrow_return → PASS.

    Implementation stores escrow_creates as dict[issue → amount], so the second
    create overwrites the first. With one return present, the boolean
    `issue in escrow_returns` is True and no dangling violation is raised.

    This documents a known precision limit: double-create is not detected.
    """
    issue = _BASE + 4  # 904
    slot = 38
    mints = [_mint("T1", slot, issue)]
    events = [
        _escrow_create(issue, slot),  # first create — overwritten by next
        _escrow_create(issue, slot),  # second create — this one is kept
        _escrow_return(issue, slot),  # single return — satisfies boolean check
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["summary"]["failures"] == 0


# ---------------------------------------------------------------------------
# Category 4: Wrong escrow amount
# ---------------------------------------------------------------------------


def test_adv_wrong_escrow_amount_warns_not_fails(tmp_path: Path) -> None:
    """Escrow amount ≠ 19 + slot → WARNING only, status remains PASS.

    Attack: founding escrow funded at 50 WEA for a slot-40 task (expected 59).
    The lifecycle is complete (create + return), so no FAIL — only a WARNING
    flagging the discrepancy.
    """
    issue = _BASE + 5  # 905
    slot = 40  # expected: 19 + 40 = 59
    mints = [_mint("T2", slot, issue)]
    events = [
        {"type": "escrow_create", "issue": issue, "amount": 50},  # 50 ≠ 59
        _escrow_return(issue, slot),
    ]
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert len(result["warnings"]) == 1
    w = result["warnings"][0]
    assert w["type"] == "amount_mismatch"
    assert w["expected"] == 19 + slot
    assert w["actual"] == 50
    assert w["issue"] == issue


# ---------------------------------------------------------------------------
# Category 5: Empty history directory
# ---------------------------------------------------------------------------


def test_adv_empty_history_dir_graceful(tmp_path: Path) -> None:
    """History directory exists but holds no .jsonl files — no crash, 0 violations.

    Attack: attacker removes all history files hoping to confuse or crash the
    script. With no mints to check, the script must handle the empty glob
    gracefully and exit PASS.
    """
    (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    _write_mints(tmp_path, [])  # no mints → nothing to check

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "PASS"
    assert result["summary"]["checked"] == 0
    assert result["summary"]["failures"] == 0


# ---------------------------------------------------------------------------
# Category 6: Forge attack
# ---------------------------------------------------------------------------


def test_adv_forge_attack_idem_key_correct_issue_mismatched(tmp_path: Path) -> None:
    """Forge: idem_key names the target issue, but 'issue' field is one off.

    Attack: attacker injects an escrow_create with idem_key='escrow_create_gauntlet|907'
    (correct format for the target) but sets issue=908. The script indexes events
    by the 'issue' integer field — not by idem_key — so the forged record lands
    under #908 and #907 is correctly flagged as missing.
    """
    issue = _BASE + 7  # 907
    slot = 41  # expected amount = 60
    mints = [_mint("T2", slot, issue)]
    forge_event = {
        "type": "escrow_create",
        "issue": issue + 1,  # 908 — attacker off-by-one in the issue field
        "idem_key": f"escrow_create_gauntlet|{issue}",  # idem_key says 907
        "amount": 19 + slot,
    }
    _write_mints(tmp_path, mints)
    _write_history(tmp_path, [forge_event])

    result = run_check(tmp_path, legacy_cutoff=0)

    # Forged create indexed under #908; #907 has no escrow_create → FAIL
    assert result["status"] == "FAIL"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["type"] == "missing_escrow_create"
    assert result["failures"][0]["issue"] == issue


# ---------------------------------------------------------------------------
# Category 7: Bulk mint with mixed states
# ---------------------------------------------------------------------------


def test_adv_bulk_mixed_states_exactly_two_violations(tmp_path: Path) -> None:
    """10 mints: 8 valid, 1 missing escrow, 1 dangling → exactly 2 violations.

    Verifies that bulk processing does not cause cross-contamination (a valid
    issue's escrow does not accidentally satisfy a missing one) and that the
    failure count is exact.
    """
    base = _BASE + 10  # start at 910
    slot = 38

    mints: list[dict] = []
    events: list[dict] = []

    # Issues 910–917: valid (escrow_create + escrow_return)
    for i in range(8):
        iss = base + i
        mints.append(_mint("T1", slot, iss))
        events.append(_escrow_create(iss, slot))
        events.append(_escrow_return(iss, slot))

    # Issue 918: no escrow_create at all → missing_escrow_create
    missing_issue = base + 8  # 918
    mints.append(_mint("T2", slot, missing_issue))

    # Issue 919: escrow_create but no return/consumption → dangling_escrow
    dangling_issue = base + 9  # 919
    mints.append(_mint("T3", slot, dangling_issue))
    events.append(_escrow_create(dangling_issue, slot))

    _write_mints(tmp_path, mints)
    _write_history(tmp_path, events)

    result = run_check(tmp_path, legacy_cutoff=0)

    assert result["status"] == "FAIL"
    assert result["summary"]["checked"] == 10
    assert result["summary"]["failures"] == 2
    assert result["summary"]["warnings"] == 0

    failure_types = {f["type"] for f in result["failures"]}
    failure_issues = {f["issue"] for f in result["failures"]}
    assert failure_types == {"missing_escrow_create", "dangling_escrow"}
    assert missing_issue in failure_issues
    assert dangling_issue in failure_issues
