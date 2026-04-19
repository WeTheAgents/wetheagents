"""Boundary spec tests for scripts/check_history_completeness.py (T4S22).

Encodes the behavioral contract for five edge cases that guarantee the checker
does not silently pass malformed or incomplete ledger inputs:

  (a) escrow_create idem_key exists; matching history event uses non-standard
      op VALUE ('create_escrow') — checker detects the missing linkage because
      _history_kind() returns 'create_escrow' verbatim, which does not match
      the 'escrow_create' branch. The write IS collected (via key prefix), but
      the history event is NOT counted. Result: FAIL.
  (b) trajectory_mint in history carries a slot that mismatches the slot
      recorded in trajectory_mints.json — checker flags the discrepancy because
      Counter keys are (trajectory, slot) tuples and a slot-99 event does not
      satisfy a slot-5 expectation.
  (c) history directory contains empty JSONL files — checker must not crash;
      empty files produce zero events, and with no expected writes the result
      is PASS.
  (d) idem_key present in idem_keys.json with zero matching history events —
      checker must return FAIL for accept/payment and escrow_create writes alike.
  (e) accept idem_key references an agent not in balances.json but no matching
      history event exists — checker surfaces the agent name in the missing
      list because completeness is verified via idem_key→history linkage.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_completeness import run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo(root: Path) -> Path:
    """Minimal ledger dir structure required by check_history_completeness.run()."""
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    _write_json(root / "ledger" / "idem_keys.json", {"keys": {}})
    _write_json(root / "ledger" / "trajectory_mints.json", {"mints": []})
    return root


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict]) -> None:  # type: ignore[type-arg]
    path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )


def _get_check(result: dict, name: str) -> dict:  # type: ignore[type-arg]
    return next(c for c in result["checks"] if c["name"] == name)


# ---------------------------------------------------------------------------
# (a) Non-standard op VALUE in history event
# ---------------------------------------------------------------------------


class TestNonStandardOpValue:
    """(a) escrow_create idem_key with non-standard op VALUE in the history event."""

    def test_standard_type_field_satisfies_idem_key(self, tmp_path: Path) -> None:
        """Baseline: history event with type='escrow_create' satisfies the write."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"escrow_create_42_gauntlet": True},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "escrow_create", "issue": 42}],
        )
        _, passed = run(root)
        assert passed

    def test_op_field_name_normalized_to_escrow_create(self, tmp_path: Path) -> None:
        """Field-name normalization: 'op: escrow_create' is treated as escrow_create.

        _history_kind() checks 'event', 'op', 'type' fields in order.
        Using the 'op' key with VALUE 'escrow_create' is a valid alternative
        schema → should PASS.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"escrow_create_42_gauntlet": True},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"op": "escrow_create", "issue": 42}],
        )
        _, passed = run(root)
        assert passed, (
            "_history_kind() normalizes field names (event/op/type); "
            "op='escrow_create' must be recognized"
        )

    def test_nonstandard_op_value_create_escrow_fails(self, tmp_path: Path) -> None:
        """(a) History event op VALUE is 'create_escrow' (not 'escrow_create').

        _history_kind() returns 'create_escrow' verbatim — it normalizes field
        NAMES (event/op/type) but not VALUES. The write is collected (via key
        prefix 'escrow_create_42_...') but no history event counts as
        escrow_create for issue 42. Checker must FAIL.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"escrow_create_42_gauntlet": True},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"op": "create_escrow", "issue": 42}],
        )
        result, passed = run(root)
        assert not passed, (
            "Non-standard op VALUE 'create_escrow' must not satisfy an "
            "escrow_create idem_key — checker should detect the missing linkage"
        )
        check = _get_check(result, "escrow_create_history")
        assert check["status"] == "FAIL"
        missing_issues = [m["issue"] for m in check["missing"]]
        assert "42" in missing_issues, f"Issue 42 must appear in missing: {missing_issues}"

    def test_event_field_name_normalized_to_escrow_create(self, tmp_path: Path) -> None:
        """'event: escrow_create' field name variant is also normalized → PASS."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"escrow_create_55_gauntlet": True},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"event": "escrow_create", "issue": 55}],
        )
        _, passed = run(root)
        assert passed, "event='escrow_create' field variant must be normalized → PASS"


# ---------------------------------------------------------------------------
# (b) Trajectory mint slot mismatch
# ---------------------------------------------------------------------------


class TestTrajectoryMintSlotMismatch:
    """(b) trajectory_mint in history with slot mismatch vs trajectory_mints.json."""

    def test_correct_slot_passes(self, tmp_path: Path) -> None:
        """Baseline: history event with matching trajectory + slot → PASS."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {"mints": [{"trajectory": "T1", "slot": 5, "issue": "100"}]},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "trajectory_mint", "trajectory": "T1", "slot": 5}],
        )
        _, passed = run(root)
        assert passed

    def test_wrong_slot_in_history_fails(self, tmp_path: Path) -> None:
        """(b) History event carries slot 99 but trajectory_mints.json records slot 5.

        Counter keys are (trajectory, slot) tuples. A history event for
        ('T1', 99) does NOT satisfy the ('T1', 5) expectation → FAIL.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {"mints": [{"trajectory": "T1", "slot": 5, "issue": "100"}]},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "trajectory_mint", "trajectory": "T1", "slot": 99}],
        )
        result, passed = run(root)
        assert not passed, "Slot mismatch (history=99 vs expected=5) must be detected"
        check = _get_check(result, "trajectory_mint_history")
        assert check["status"] == "FAIL"
        assert any(
            m["slot"] == 5 and m["trajectory"] == "T1" for m in check["missing"]
        ), f"Missing must reference T1/slot-5: {check['missing']}"

    def test_wrong_trajectory_name_fails(self, tmp_path: Path) -> None:
        """History event has correct slot but wrong trajectory name → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {"mints": [{"trajectory": "T1", "slot": 5, "issue": "100"}]},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "trajectory_mint", "trajectory": "T2", "slot": 5}],
        )
        result, passed = run(root)
        assert not passed, "Wrong trajectory name must be detected"
        check = _get_check(result, "trajectory_mint_history")
        assert check["status"] == "FAIL"
        assert any(m["trajectory"] == "T1" for m in check["missing"])

    def test_correct_trajectory_multiple_slots_partial_match_fails(
        self, tmp_path: Path
    ) -> None:
        """Two mints required; history only has one slot → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {
                "mints": [
                    {"trajectory": "T2", "slot": 10, "issue": "200"},
                    {"trajectory": "T2", "slot": 11, "issue": "201"},
                ]
            },
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "trajectory_mint", "trajectory": "T2", "slot": 10}],
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "trajectory_mint_history")
        assert check["status"] == "FAIL"
        assert any(m["slot"] == 11 for m in check["missing"])


# ---------------------------------------------------------------------------
# (c) Empty JSONL files in history dir
# ---------------------------------------------------------------------------


class TestEmptyJsonlFiles:
    """(c) Empty JSONL files in history dir must not crash the checker."""

    def test_single_empty_jsonl_does_not_crash(self, tmp_path: Path) -> None:
        """Empty .jsonl file → 0 events loaded, no crash, PASS."""
        root = _make_repo(tmp_path)
        (root / "ledger" / "history" / "2026-04-01.jsonl").write_text(
            "", encoding="utf-8"
        )
        result, passed = run(root)
        assert passed
        assert result["status"] == "PASS"

    def test_multiple_empty_jsonl_files_do_not_crash(self, tmp_path: Path) -> None:
        """Multiple empty JSONL files → no crash, no false failures."""
        root = _make_repo(tmp_path)
        for fname in ["2026-01-01.jsonl", "2026-02-01.jsonl", "2026-03-01.jsonl"]:
            (root / "ledger" / "history" / fname).write_text("", encoding="utf-8")
        result, passed = run(root)
        assert passed
        assert result["status"] == "PASS"

    def test_whitespace_only_jsonl_does_not_crash(self, tmp_path: Path) -> None:
        """Whitespace-only JSONL file → 0 events, no crash."""
        root = _make_repo(tmp_path)
        (root / "ledger" / "history" / "2026-04-01.jsonl").write_text(
            "   \n\n\t\n", encoding="utf-8"
        )
        _, passed = run(root)
        assert passed

    def test_empty_jsonl_alongside_valid_entry_satisfies_idem_key(
        self, tmp_path: Path
    ) -> None:
        """Empty file + file with valid event → valid event is still processed.

        The empty file must not cause the valid event in a sibling file to be
        silently dropped.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"accept|50|alice@test": "2026-01-01T00:00:00Z"},
        )
        (root / "ledger" / "history" / "2026-01-01.jsonl").write_text(
            "", encoding="utf-8"
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "accept", "issue": 50, "agent": "alice@test"}],
        )
        _, passed = run(root)
        assert passed, "Valid event in non-empty sibling file must satisfy idem_key"


# ---------------------------------------------------------------------------
# (d) idem_key with zero matching history events
# ---------------------------------------------------------------------------


class TestIdemKeyZeroHistoryEvents:
    """(d) idem_key present in idem_keys.json with zero matching history events → FAIL."""

    def test_accept_idem_key_no_history_fails(self, tmp_path: Path) -> None:
        """accept idem_key exists; history dir is empty → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"accept|100|alice@test": "2026-01-01T00:00:00Z"},
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "accept_payment_history")
        assert check["status"] == "FAIL"
        assert any(
            m["agent"] == "alice@test" for m in check["missing"]
        ), f"alice@test must appear in missing: {check['missing']}"

    def test_payment_idem_key_no_history_fails(self, tmp_path: Path) -> None:
        """payment| idem_key exists; no matching history → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"payment|200|bob@test": "2026-02-01T00:00:00Z"},
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "accept_payment_history")
        assert check["status"] == "FAIL"
        assert any(m["agent"] == "bob@test" for m in check["missing"])

    def test_escrow_create_idem_key_no_history_fails(self, tmp_path: Path) -> None:
        """escrow_create_ idem_key exists; no matching history → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"escrow_create_42_gauntlet": True},
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "escrow_create_history")
        assert check["status"] == "FAIL"
        assert any(m["issue"] == "42" for m in check["missing"])

    def test_multiple_idem_keys_all_missing_reports_each(self, tmp_path: Path) -> None:
        """Multiple idem_keys with no history → each missing write is reported."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {
                "accept|100|alice@test": "2026-01-01T00:00:00Z",
                "accept|101|alice@test": "2026-01-02T00:00:00Z",
            },
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "accept_payment_history")
        assert check["expected_writes"] == 2
        assert len(check["missing"]) == 2

    def test_idem_key_with_matching_history_passes(self, tmp_path: Path) -> None:
        """Baseline: idem_key + matching history event → PASS."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"accept|100|alice@test": "2026-01-01T00:00:00Z"},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "accept", "issue": 100, "agent": "alice@test"}],
        )
        _, passed = run(root)
        assert passed

    def test_trajectory_mint_record_no_history_fails(self, tmp_path: Path) -> None:
        """trajectory_mints.json has a mint with zero history events → FAIL."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {"mints": [{"trajectory": "T5", "slot": 3, "issue": "99"}]},
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "trajectory_mint_history")
        assert check["status"] == "FAIL"
        assert any(
            m["trajectory"] == "T5" and m["slot"] == 3 for m in check["missing"]
        )


# ---------------------------------------------------------------------------
# (e) Accept event for agent not in balances.json — orphan detection
# ---------------------------------------------------------------------------


class TestOrphanAgentDetection:
    """(e) accept idem_key for an agent absent from balances.json — surfaces orphan."""

    def test_orphan_agent_no_history_fails(self, tmp_path: Path) -> None:
        """(e) idem_key for ghost@test (not in balances); empty history → FAIL.

        check_history_completeness.py does not load balances.json.  It detects
        the orphan via idem_key→history mismatch: the write is recorded but no
        history event confirms it.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"accept|100|ghost@test": "2026-01-01T00:00:00Z"},
        )
        result, passed = run(root)
        assert not passed, "Orphan agent with no history must cause FAIL"
        check = _get_check(result, "accept_payment_history")
        assert check["status"] == "FAIL"
        missing_agents = [m["agent"] for m in check["missing"]]
        assert "ghost@test" in missing_agents, (
            f"Orphan 'ghost@test' must appear in missing: {missing_agents}"
        )

    def test_orphan_agent_with_history_event_passes_linkage_check(
        self, tmp_path: Path
    ) -> None:
        """When history confirms the accept for ghost@test, linkage check PASSes.

        The completeness checker verifies idem_keys ↔ history linkage only.
        Whether the agent exists in balances.json is outside this checker's scope;
        that is verified by check_agent_balances_schema or similar.
        """
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {"accept|100|ghost@test": "2026-01-01T00:00:00Z"},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [{"type": "accept", "issue": 100, "agent": "ghost@test"}],
        )
        _, passed = run(root)
        assert passed, (
            "History confirms the write for ghost@test → linkage PASS; "
            "balances membership is a separate check"
        )

    def test_multiple_orphan_agents_all_surfaced(self, tmp_path: Path) -> None:
        """Multiple orphan-agent idem_keys with no history → all names surfaced."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {
                "accept|100|orphan1@test": "2026-01-01T00:00:00Z",
                "accept|101|orphan2@test": "2026-01-02T00:00:00Z",
            },
        )
        result, passed = run(root)
        assert not passed
        check = _get_check(result, "accept_payment_history")
        missing_agents = {m["agent"] for m in check["missing"]}
        assert "orphan1@test" in missing_agents
        assert "orphan2@test" in missing_agents


# ---------------------------------------------------------------------------
# Integration: combined PASS scenario
# ---------------------------------------------------------------------------


class TestIntegrationPassScenarios:
    """All three checks pass when every write has a matching history event."""

    def test_all_checks_pass_on_well_formed_input(self, tmp_path: Path) -> None:
        """accept + escrow_create + trajectory_mint all satisfied → full PASS."""
        root = _make_repo(tmp_path)
        _write_json(
            root / "ledger" / "idem_keys.json",
            {
                "accept|100|alice@test": "2026-01-01T00:00:00Z",
                "escrow_create_200_gauntlet": True,
            },
        )
        _write_json(
            root / "ledger" / "trajectory_mints.json",
            {"mints": [{"trajectory": "T3", "slot": 7, "issue": "300"}]},
        )
        _write_jsonl(
            root / "ledger" / "history" / "2026-04-01.jsonl",
            [
                {"type": "accept", "issue": 100, "agent": "alice@test"},
                {"type": "escrow_create", "issue": 200},
                {"type": "trajectory_mint", "trajectory": "T3", "slot": 7},
            ],
        )
        result, passed = run(root)
        assert passed
        assert result["status"] == "PASS"
        assert all(c["status"] == "PASS" for c in result["checks"])

    def test_empty_ledger_passes(self, tmp_path: Path) -> None:
        """No idem_keys, no mints, empty history → PASS (nothing to verify)."""
        root = _make_repo(tmp_path)
        result, passed = run(root)
        assert passed
        assert result["status"] == "PASS"
