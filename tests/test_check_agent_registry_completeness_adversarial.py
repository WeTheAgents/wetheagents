"""Adversarial tests for scripts/check_agent_registry_completeness.py.

Seven adversarial scenarios from T2S39 Issue #843.

The implementation:
  - scans ledger/history/*.jsonl for payment/accept/trajectory_mint recipients
  - classifies unregistered recipients as VIOLATION or WARNING
  - VIOLATION  — received > 0 WEA, no rename evidence
  - WARNING    — zero-amount only, OR known former ID, OR idem_key infers rename
  - exit code 1 on any VIOLATION; 0 on PASS or warnings-only
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.check_agent_registry_completeness import run_check


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
    agents: dict,
    idem_keys: dict | None = None,
    history_events: list[dict] | None = None,
) -> Path:
    _write_json(
        root / "ledger" / "balances.json",
        {"version": 1, "agents": agents},
    )
    _write_json(
        root / "ledger" / "idem_keys.json",
        {"version": 1, "keys": idem_keys or {}},
    )
    if history_events is not None:
        _write_jsonl(
            root / "ledger" / "history" / "2026-01-01.jsonl", history_events
        )
    else:
        (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def case_root(tmp_path: Path) -> Path:
    root = tmp_path / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Scenario 1: Rename cascade — 3 historical IDs (A → B → C), only C in balances
# ---------------------------------------------------------------------------
# The implementation collects former IDs from registration_confirmed.previous_id.
# A three-step chain: A→B→C.  B and C each declare a previous_id, so both
# A and B end up in former_ids → WARNING, not VIOLATION.
# ---------------------------------------------------------------------------


class TestRenameCascade:
    def _make_cascade_repo(self, root: Path) -> Path:
        """ID-A → ID-B → ID-C rename chain; only ID-C in balances."""
        return _make_repo(
            root,
            agents={"Claude-C@claude": {"balance": 100}},
            history_events=[
                # Payments to former IDs
                {"type": "payment", "agent": "Claude-A@claude", "amount": 20, "issue": 1},
                {"type": "payment", "agent": "Claude-B@claude", "amount": 30, "issue": 2},
                {"type": "payment", "agent": "Claude-C@claude", "amount": 50, "issue": 3},
                # B declared A as its previous ID
                {
                    "type": "registration_confirmed",
                    "agent": "Claude-B@claude",
                    "previous_id": "Claude-A@claude",
                },
                # C declared B as its previous ID
                {
                    "type": "registration_confirmed",
                    "agent": "Claude-C@claude",
                    "previous_id": "Claude-B@claude",
                },
            ],
        )

    def test_intermediate_ids_are_warnings_not_violations(
        self, case_root: Path
    ) -> None:
        """ID-A and ID-B (former names) must be WARNING, not VIOLATION."""
        report, exit_code = run_check(self._make_cascade_repo(case_root))

        assert exit_code == 0
        assert report["status"] == "PASS"
        assert report["violations"] == []

        warning_agents = {w["agent"] for w in report["warnings"]}
        assert "Claude-A@claude" in warning_agents
        assert "Claude-B@claude" in warning_agents
        # Current name is registered — no entry in warnings either
        assert "Claude-C@claude" not in warning_agents

    def test_cascade_warnings_cite_former_id_reason(self, case_root: Path) -> None:
        """WARNING entries must contain 'former' in their reason string."""
        report, _ = run_check(self._make_cascade_repo(case_root))

        for w in report["warnings"]:
            assert "former" in w["reason"], (
                f"Expected 'former' in reason for {w['agent']!r}, got: {w['reason']!r}"
            )

    def test_cascade_without_registration_confirmed_becomes_violation(
        self, case_root: Path
    ) -> None:
        """Without registration_confirmed events the old IDs have no rename evidence → VIOLATION."""
        root = _make_repo(
            case_root,
            agents={"Claude-C@claude": {"balance": 100}},
            history_events=[
                {"type": "payment", "agent": "Claude-A@claude", "amount": 20, "issue": 1},
                {"type": "payment", "agent": "Claude-B@claude", "amount": 30, "issue": 2},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        violation_agents = {v["agent"] for v in report["violations"]}
        assert "Claude-A@claude" in violation_agents
        assert "Claude-B@claude" in violation_agents


# ---------------------------------------------------------------------------
# Scenario 2: Zero-amount only
# ---------------------------------------------------------------------------
# An unregistered agent that appears only in zero-amount events must be
# classified as WARNING (exit code 0), not VIOLATION.
# ---------------------------------------------------------------------------


class TestZeroAmountOnly:
    def test_zero_amount_accept_is_warning(self, case_root: Path) -> None:
        """Unregistered agent receiving only amount=0 accept events → WARNING."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            history_events=[
                {"type": "accept", "agent": "Ghost-Zero@test", "amount": 0, "issue": 5},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 0
        assert report["status"] == "PASS"
        assert report["violations"] == []
        assert len(report["warnings"]) == 1
        assert report["warnings"][0]["agent"] == "Ghost-Zero@test"
        assert "zero amount" in report["warnings"][0]["reason"]

    def test_mixed_zero_and_nonzero_payments_is_violation(
        self, case_root: Path
    ) -> None:
        """Agent with at least one non-zero event is VIOLATION, not WARNING."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            history_events=[
                {"type": "payment", "agent": "Ghost-Mixed@test", "amount": 0, "issue": 1},
                {"type": "payment", "agent": "Ghost-Mixed@test", "amount": 10, "issue": 2},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        assert any(v["agent"] == "Ghost-Mixed@test" for v in report["violations"])

    def test_multiple_zero_amount_events_still_warning(self, case_root: Path) -> None:
        """Multiple zero-amount events for same unregistered agent → single WARNING."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            history_events=[
                {"type": "payment", "agent": "Ghost-Zero@test", "amount": 0, "issue": 1},
                {"type": "payment", "agent": "Ghost-Zero@test", "amount": 0, "issue": 2},
                {"type": "accept",  "agent": "Ghost-Zero@test", "amount": 0, "issue": 3},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 0
        assert len(report["warnings"]) == 1
        assert report["warnings"][0]["total_received"] == 0


# ---------------------------------------------------------------------------
# Scenario 3: trajectory_mint recipient not in balances
# ---------------------------------------------------------------------------
# A trajectory_mint event that names an unregistered agent must trigger VIOLATION.
# ---------------------------------------------------------------------------


class TestTrajectoryMintUnregistered:
    def test_unregistered_mint_recipient_is_violation(self, case_root: Path) -> None:
        """trajectory_mint to unregistered agent → VIOLATION."""
        root = _make_repo(
            case_root,
            agents={
                "agent0@system": {"balance": 1000},
                "Claude-1@claude": {"balance": 100},
            },
            history_events=[
                {
                    "type": "trajectory_mint",
                    "agents": ["Claude-1@claude", "Ghost-Minted@x"],
                    "per_agent": [55, 58],
                    "issue": 843,
                }
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        violations = {v["agent"] for v in report["violations"]}
        assert "Ghost-Minted@x" in violations
        # Registered co-recipient is never flagged
        assert "Claude-1@claude" not in violations

    def test_mint_amount_in_violation_entry(self, case_root: Path) -> None:
        """VIOLATION entry records the minted amount correctly."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            history_events=[
                {
                    "type": "trajectory_mint",
                    "agents": ["Ghost-Minted@x"],
                    "per_agent": [58],
                    "issue": 843,
                }
            ],
        )

        report, _ = run_check(root)

        assert report["violations"][0]["total_received"] == 58

    def test_zero_amount_mint_to_unregistered_is_warning(
        self, case_root: Path
    ) -> None:
        """trajectory_mint with amount=0 per_agent → WARNING, not VIOLATION."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            history_events=[
                {
                    "type": "trajectory_mint",
                    "agents": ["Ghost-Minted@x"],
                    "per_agent": [0],
                    "issue": 843,
                }
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 0
        assert report["warnings"][0]["agent"] == "Ghost-Minted@x"


# ---------------------------------------------------------------------------
# Scenario 4: Large history bypass — 200 events, ghost buried deep
# ---------------------------------------------------------------------------
# The checker must scan ALL history events; no bypass via volume.
# ---------------------------------------------------------------------------


class TestLargeHistoryBypass:
    def test_ghost_among_200_events_is_caught(self, case_root: Path) -> None:
        """A single ghost payment among 200 events is always surfaced as VIOLATION."""
        agents: dict = {"agent0@system": {"balance": 9000}}
        idem: dict = {}
        events: list[dict] = []

        for i in range(1, 200):
            aid = f"Claude-{i}@claude"
            agents[aid] = {"balance": i}
            events.append({"type": "payment", "agent": aid, "amount": i, "issue": i})

        ghost = "GhostBuried@deep"
        # Insert ghost payment at position 100 (buried in the middle)
        events.insert(100, {"type": "payment", "agent": ghost, "amount": 99, "issue": 999})

        root = _make_repo(case_root, agents=agents, idem_keys=idem, history_events=events)
        report, exit_code = run_check(root)

        assert exit_code == 1
        assert any(v["agent"] == ghost for v in report["violations"])

    def test_summary_counts_correct_with_large_history(self, case_root: Path) -> None:
        """Summary reflects the correct violation count even in large history."""
        agents: dict = {"agent0@system": {"balance": 9000}}
        events: list[dict] = []

        for i in range(1, 150):
            aid = f"Claude-{i}@claude"
            agents[aid] = {"balance": i}
            events.append({"type": "payment", "agent": aid, "amount": i, "issue": i})

        events.append(
            {"type": "payment", "agent": "GhostOne@x", "amount": 50, "issue": 9001}
        )
        events.append(
            {"type": "payment", "agent": "GhostTwo@x", "amount": 30, "issue": 9002}
        )

        root = _make_repo(case_root, agents=agents, history_events=events)
        report, exit_code = run_check(root)

        assert exit_code == 1
        assert "2 violation(s)" in report["summary"]


# ---------------------------------------------------------------------------
# Scenario 5: False positive rename — idem_key prefix sharing
# ---------------------------------------------------------------------------
# idem_key_implies_rename checks whether a registered agent has an idem_key
# for the SAME ISSUE as the unregistered agent's payments.
# Two unregistered agents on DIFFERENT issues must not be conflated.
# Two unregistered agents on the SAME issue with a matching idem_key are
# both classified as WARNING — this is the false-positive risk.
# ---------------------------------------------------------------------------


class TestFalsePositiveRename:
    def test_different_issues_no_conflation(self, case_root: Path) -> None:
        """Agents on different issues are not conflated — each evaluated independently."""
        root = _make_repo(
            case_root,
            agents={"Registered-X@x": {"balance": 100}},
            # Only issue #10 has an idem_key; issue #20 does not
            idem_keys={"payment|10|Registered-X@x": "2026-04-01T00:00:00Z"},
            history_events=[
                # ghost-A paid on issue #10 → idem_key match → WARNING
                {"type": "payment", "agent": "Ghost-A@test", "amount": 20, "issue": 10},
                # ghost-B paid on issue #20 → no idem_key match → VIOLATION
                {"type": "payment", "agent": "Ghost-B@test", "amount": 25, "issue": 20},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1  # ghost-B is a VIOLATION
        violation_agents = {v["agent"] for v in report["violations"]}
        warning_agents = {w["agent"] for w in report["warnings"]}
        assert "Ghost-B@test" in violation_agents
        assert "Ghost-A@test" in warning_agents
        # Critically: ghost-A must NOT appear in violations
        assert "Ghost-A@test" not in violation_agents

    def test_same_issue_both_classed_as_warning_exposes_limitation(
        self, case_root: Path
    ) -> None:
        """Two unregistered agents on the same issue both get WARNING when idem_key matches.

        This is the false-positive risk: if ghost-B is a real ghost (not a rename)
        but happened to be paid on the same issue as the renamed ghost-A, the checker
        cannot distinguish them and classifies both as WARNING.
        """
        root = _make_repo(
            case_root,
            agents={"Registered-X@x": {"balance": 100}},
            idem_keys={"payment|50|Registered-X@x": "2026-04-01T00:00:00Z"},
            history_events=[
                # ghost-A: a real rename of Registered-X on issue #50
                {"type": "payment", "agent": "Ghost-A@test", "amount": 20, "issue": 50},
                # ghost-B: unrelated ghost, also paid on issue #50
                {"type": "payment", "agent": "Ghost-B@test", "amount": 20, "issue": 50},
            ],
        )

        report, exit_code = run_check(root)

        # Both are WARNING — this is the false-positive scenario
        assert exit_code == 0
        warning_agents = {w["agent"] for w in report["warnings"]}
        assert "Ghost-A@test" in warning_agents
        assert "Ghost-B@test" in warning_agents  # false positive

    def test_idem_key_for_unregistered_agent_in_parts2_is_not_a_match(
        self, case_root: Path
    ) -> None:
        """If parts[2] of the idem_key is itself unregistered, no rename is inferred."""
        root = _make_repo(
            case_root,
            agents={"agent0@system": {"balance": 1000}},
            # The key's parts[2] is 'Ghost-B@test' which is not in registered_ids
            idem_keys={"payment|10|Ghost-B@test": "2026-04-01T00:00:00Z"},
            history_events=[
                {"type": "payment", "agent": "Ghost-A@test", "amount": 30, "issue": 10},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        assert report["violations"][0]["agent"] == "Ghost-A@test"


# ---------------------------------------------------------------------------
# Scenario 6: Case sensitivity
# ---------------------------------------------------------------------------
# Python set membership is case-sensitive.
# 'Agent-1@claude' and 'agent-1@claude' are distinct registered IDs.
# ---------------------------------------------------------------------------


class TestCaseSensitivity:
    def test_lowercase_agent_not_found_when_only_uppercase_registered(
        self, case_root: Path
    ) -> None:
        """History payment to agent-1@claude (lowercase) when only Agent-1@claude
        (uppercase) is registered → VIOLATION; case mismatch is not a rename."""
        root = _make_repo(
            case_root,
            agents={"Agent-1@claude": {"balance": 100}},
            history_events=[
                {"type": "payment", "agent": "agent-1@claude", "amount": 30, "issue": 1},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        assert report["violations"][0]["agent"] == "agent-1@claude"

    def test_both_case_variants_registered_no_violation(
        self, case_root: Path
    ) -> None:
        """When both case variants are in balances their payments pass."""
        root = _make_repo(
            case_root,
            agents={
                "Agent-1@claude": {"balance": 100},
                "agent-1@claude": {"balance": 50},
            },
            history_events=[
                {"type": "payment", "agent": "Agent-1@claude", "amount": 30, "issue": 1},
                {"type": "payment", "agent": "agent-1@claude", "amount": 20, "issue": 2},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 0
        assert report["status"] == "PASS"
        assert report["violations"] == []

    def test_one_case_variant_unregistered_is_violation(
        self, case_root: Path
    ) -> None:
        """One variant registered, other variant received payment → VIOLATION."""
        root = _make_repo(
            case_root,
            agents={"Agent-1@claude": {"balance": 100}},
            history_events=[
                # Uppercase is registered and paid — passes
                {"type": "payment", "agent": "Agent-1@claude", "amount": 30, "issue": 1},
                # Lowercase is NOT registered — VIOLATION
                {"type": "payment", "agent": "agent-1@claude", "amount": 20, "issue": 2},
            ],
        )

        report, exit_code = run_check(root)

        assert exit_code == 1
        violations = {v["agent"] for v in report["violations"]}
        assert "agent-1@claude" in violations
        assert "Agent-1@claude" not in violations


# ---------------------------------------------------------------------------
# Scenario 7: Mixed VIOLATION + WARNING in same history
# ---------------------------------------------------------------------------
# 1 ghost payment (VIOLATION) + 2 renamed former IDs (WARNING).
# Exit code must be 1 (any violation); all 3 reported under correct keys.
# ---------------------------------------------------------------------------


class TestMixedViolationAndWarning:
    def _make_mixed_repo(self, root: Path) -> Path:
        return _make_repo(
            root,
            agents={"agent0@system": {"balance": 9000}, "Claude-New@x": {"balance": 50}},
            history_events=[
                # VIOLATION: real ghost, non-zero amount, no rename evidence
                {"type": "payment", "agent": "Ghost-Real@x", "amount": 50, "issue": 10},
                # WARNING 1: known former ID via registration_confirmed
                {"type": "payment", "agent": "Claude-Old-A@x", "amount": 20, "issue": 2},
                {
                    "type": "registration_confirmed",
                    "agent": "Claude-New@x",
                    "previous_id": "Claude-Old-A@x",
                },
                # WARNING 2: listed in economy_reset.agents_zeroed
                {"type": "payment", "agent": "Bootstrap-Early@x", "amount": 15, "issue": 1},
                {
                    "type": "economy_reset",
                    "agents_zeroed": ["Bootstrap-Early@x"],
                },
            ],
        )

    def test_exit_code_one_on_mixed_results(self, case_root: Path) -> None:
        """Any violation → exit code 1 regardless of warnings present."""
        _, exit_code = run_check(self._make_mixed_repo(case_root))
        assert exit_code == 1

    def test_violation_count_is_one(self, case_root: Path) -> None:
        """Exactly 1 VIOLATION reported in mixed scenario."""
        report, _ = run_check(self._make_mixed_repo(case_root))
        assert len(report["violations"]) == 1
        assert report["violations"][0]["agent"] == "Ghost-Real@x"

    def test_warning_count_is_two(self, case_root: Path) -> None:
        """Exactly 2 WARNINGs reported alongside the VIOLATION."""
        report, _ = run_check(self._make_mixed_repo(case_root))
        assert len(report["warnings"]) == 2

    def test_all_three_entries_reported_correctly(self, case_root: Path) -> None:
        """VIOLATION and both WARNINGs contain correct agent IDs."""
        report, _ = run_check(self._make_mixed_repo(case_root))

        violation_agents = {v["agent"] for v in report["violations"]}
        warning_agents = {w["agent"] for w in report["warnings"]}

        assert "Ghost-Real@x" in violation_agents
        assert "Claude-Old-A@x" in warning_agents
        assert "Bootstrap-Early@x" in warning_agents

    def test_summary_string_reflects_correct_counts(self, case_root: Path) -> None:
        """Summary string must report '1 violation(s), 2 warning(s)'."""
        report, _ = run_check(self._make_mixed_repo(case_root))
        assert "1 violation(s)" in report["summary"]
        assert "2 warning(s)" in report["summary"]
