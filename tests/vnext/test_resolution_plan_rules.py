from __future__ import annotations

from dataclasses import replace

import pytest

from .current_bdd_support import modules as current_modules
from .resolution_plan_support import modules, plan_revision


def test_s_59_ruleset_has_exact_matrix_without_profiles_or_infinite() -> None:
    rules = modules()["rules"].load_ruleset().content

    assert rules["depth_modes"] == {
        "explore": ("duel", "flat_pod", "frontier", "ranked"),
        "implement": ("frontier", "ranked"),
        "spec": ("frontier", "ranked"),
    }
    raw = modules()["rules"].raw_ruleset_bytes()
    assert b'"profiles"' not in raw
    assert b"direct-pr" not in raw
    assert b"spec-only" not in raw
    assert b"full-build" not in raw
    assert b"infinite" not in raw.lower()
    assert rules["formal_reject_codes"] == (
        "authority",
        "declaration",
        "evidence_boundary",
        "identity",
        "matrix",
        "money",
    )


def test_s_01c_s_04b_ruleset_pins_lifecycle_evidence_and_pause_boundary() -> None:
    lifecycle = current_modules()["rules"].load_ruleset().content["lifecycle"]

    assert lifecycle["source_evidence"] == (
        "latest-accepted-github-revision-under-complete-confirmed-read-boundary"
    )
    assert lifecycle["body_integrity_pause"] == {
        "deadline_offset": "open-at-pause-once",
        "pause_evidence": "latest-current-changed-issue-body",
        "resume_evidence": "latest-current-exact-contract-body-after-pause",
    }
    assert lifecycle["risk_pause"] == {
        "admitted_events": (
            "duel_join",
            "duel_move",
            "role_resolution",
            "role_result",
            "work_revision",
        ),
        "blocked_event_groups": (
            "child-materialization",
            "mode-settlement",
            "new-role-assignment",
            "stage-completion",
            "stage-decision",
        ),
        "body_resume_closes": False,
        "deadline_offset": False,
        "role_scope": "pre-pause-only",
    }
    rules = current_modules()["rules"].load_ruleset().content
    assert rules["modes"]["flat_pod"]["slot_cap_close"] == "immediate"
    assert rules["modes"]["duel"]["move_order"] == (
        "strictly-increasing-accepted-numbers-with-expired-slot-skips"
    )
    assert rules["roles"]["warning_pause"] == (
        "agent0-from-active-assigned-triage-or-review-generation"
    )


@pytest.mark.parametrize(
    ("depth", "mode", "allocation", "config"),
    (
        ("implement", "duel", 20, {"positions": ["a", "b"], "rounds": 3}),
        (
            "spec",
            "flat_pod",
            2,
            {"additive": True, "payout_vector": [1, 1], "slots": 2},
        ),
        ("explore", "ranked", 1, {"payout_vector": [1], "winner_count": 0}),
        (
            "explore",
            "flat_pod",
            3,
            {"additive": True, "payout_vector": [1, 2], "slots": 2},
        ),
        ("explore", "duel", 20, {"positions": ["same", "same"], "rounds": 3}),
    ),
)
def test_s_59_each_independently_invalid_matrix_form_fails_closed(
    depth: str,
    mode: str,
    allocation: int,
    config: dict[str, object],
) -> None:
    intake = modules()["intake"]

    with pytest.raises(intake.PlanError):
        intake.PlanStage(
            key="invalid-stage",
            depth=depth,
            mode=mode,
            allocation_wea=allocation,
            config=config,
            expected_output="result",
        )


def test_all_simple_matrix_rows_are_constructible_without_a_profile() -> None:
    intake = modules()["intake"]
    accepted = [
        ("explore", "ranked", 3, {"payout_vector": [2, 1], "winner_count": 2}),
        (
            "explore",
            "flat_pod",
            2,
            {"additive": True, "payout_vector": [1, 1], "slots": 2},
        ),
        (
            "explore",
            "frontier",
            6,
            {
                "incentive": "fibonacci",
                "payout_vector": [1, 2, 3],
                "snapshot_identity": "model+genome+runtime",
            },
        ),
        ("explore", "duel", 20, {"positions": ["a", "b"], "rounds": 3}),
        ("spec", "ranked", 1, {"payout_vector": [1], "winner_count": 1}),
        (
            "spec",
            "frontier",
            6,
            {
                "incentive": "linear",
                "payout_vector": [1, 2, 3],
                "snapshot_identity": "model+genome+runtime",
            },
        ),
        ("implement", "ranked", 1, {"payout_vector": [1], "winner_count": 1}),
        (
            "implement",
            "frontier",
            6,
            {
                "incentive": "fibonacci",
                "payout_vector": [1, 2, 3],
                "snapshot_identity": "model+genome+runtime",
            },
        ),
    ]

    for index, (depth, mode, allocation, config) in enumerate(accepted):
        stage = intake.PlanStage(
            key=f"stage-{index}",
            depth=depth,
            mode=mode,
            allocation_wea=allocation,
            config=config,
            expected_output="result",
        )
        assert stage.depth == depth
        assert stage.mode == mode
        assert "profile" not in stage.to_data()

    plan = plan_revision()
    invalid_first = replace(
        plan.stages[0], inputs=(intake.SelectedWorkInput("implementation"),)
    )
    with pytest.raises(intake.PlanError, match="earlier"):
        replace(plan, stages=(invalid_first, *plan.stages[1:]))


def test_two_slot_linear_frontier_must_advance_the_frontier() -> None:
    intake = modules()["intake"]

    with pytest.raises(intake.PlanError, match="not linear"):
        intake.PlanStage(
            key="frontier",
            depth="explore",
            mode="frontier",
            allocation_wea=3,
            config={
                "incentive": "linear",
                "payout_vector": [2, 1],
                "snapshot_identity": "model+genome+runtime",
            },
            expected_output="New frontier contribution",
        )


def test_raw_allocated_exact_stage_cannot_bypass_money_validation() -> None:
    intake = modules()["intake"]
    raw = object.__new__(intake.PlanStage)
    values = {
        "key": "raw-stage",
        "depth": "implement",
        "mode": "ranked",
        "allocation_wea": 100,
        "config": {"payout_vector": [1], "winner_count": 1},
        "expected_output": "result",
        "inputs": (),
    }
    for field, value in values.items():
        object.__setattr__(raw, field, value)

    with pytest.raises(intake.PlanError, match="payouts"):
        replace(plan_revision(), stages=(raw,), total_bank_wea=100)
