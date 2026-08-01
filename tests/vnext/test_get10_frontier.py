from __future__ import annotations

import pytest

from .current_bdd_support import accept_work, activated_runtime, modules, submit_work


def test_s_68_get10_new_epoch_keeps_six_prior_works_and_seven_new_slots() -> None:
    get10 = modules()["get10"]
    intake = modules()["intake"]
    config = get10.new_epoch_config()
    contract_stage = intake.PlanStage(
        key="get10-frontier-v2",
        depth="explore",
        mode="frontier",
        schedule=intake.StageSchedule(intake_seconds=604800),
        allocation_wea=589,
        config=config,
        expected_output="A valid novel expression that equals 10",
    )

    assert len(config["prior_art"]) == 6
    assert config["payout_vector"] == [13, 21, 34, 55, 89, 144, 233]
    assert sum(config["payout_vector"]) == 589
    assert get10.classify_legacy_expression("11 - 1^3") == ("legacy-noop-anti-example")
    assert get10.classify_legacy_expression("11 - sqrt(1^3)") == (
        "legacy-noop-anti-example"
    )
    assert get10.classify_legacy_expression("(1+1+1)/.3") == (
        "needs-author-after-normalization:3/0.3"
    )
    assert get10.validate_candidate("(1+1+1)/.3").normalized_expression == "3/0.3"
    assert get10.validate_candidate("3/(.1+.1+.1)").normalized_expression == "3/0.3"

    state = activated_runtime(
        plan_stages=(contract_stage,),
        total_bank_wea=589,
        author_balance=700,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.escrow.deposited_wea == 589
    assert projection.escrow.available_wea == 589
    assert len(projection.current_stage.contract.config["prior_art"]) == 6
    assert projection.current_stage.works == ()


def test_s_68_get10_validator_rejects_prior_art_and_defers_novelty() -> None:
    get10 = modules()["get10"]
    intake = modules()["intake"]
    contract_stage = intake.PlanStage(
        key="get10-frontier-v2",
        depth="explore",
        mode="frontier",
        schedule=intake.StageSchedule(intake_seconds=604800),
        allocation_wea=589,
        config=get10.new_epoch_config(),
        expected_output="A valid novel expression that equals 10",
    )
    state = activated_runtime(
        plan_stages=(contract_stage,), total_bank_wea=589, author_balance=700
    )
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        content="1+3^(1+1)",
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    validator = (get10.GET10_VALIDATOR_ID, get10.GET10_VALIDATOR_VERSION)
    with pytest.raises(intake.PlanError, match="requires the exact author"):
        accept_work(
            state,
            work_id=identifier,
            revision_id=revision,
            sequence=2,
            validator=validator,
        )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        verdict="needs_author",
        validator=validator,
    )
    state = accept_work(
        state, work_id=identifier, revision_id=revision, sequence=3
    )
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 13

    state, duplicate_work, duplicate_revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
        content="3^(1+1)+1",
        snapshot={"model": "m2", "genome": "g2", "runtime": "r2"},
    )
    with pytest.raises(intake.PlanError, match="prior art"):
        accept_work(
            state,
            work_id=duplicate_work,
            revision_id=duplicate_revision,
            sequence=5,
            validator=validator,
        )
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 13


def test_s_68_get10_validator_normalizes_whitespace_for_accepted_prior_art() -> None:
    get10 = modules()["get10"]
    intake = modules()["intake"]
    contract_stage = intake.PlanStage(
        key="get10-frontier-v2",
        depth="explore",
        mode="frontier",
        schedule=intake.StageSchedule(intake_seconds=604800),
        allocation_wea=589,
        config=get10.new_epoch_config(),
        expected_output="A valid novel expression that equals 10",
    )
    state = activated_runtime(
        plan_stages=(contract_stage,), total_bank_wea=589, author_balance=700
    )
    validator = (get10.GET10_VALIDATOR_ID, get10.GET10_VALIDATOR_VERSION)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        content="1 + 3 ^ (1 + 1)",
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        verdict="needs_author",
        validator=validator,
    )
    state = accept_work(state, work_id=identifier, revision_id=revision, sequence=3)

    state, duplicate_work, duplicate_revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
        content="1+3^(1+1)",
        snapshot={"model": "m2", "genome": "g2", "runtime": "r2"},
    )
    with pytest.raises(intake.PlanError, match="prior art"):
        accept_work(
            state,
            work_id=duplicate_work,
            revision_id=duplicate_revision,
            sequence=5,
            verdict="needs_author",
            validator=validator,
        )


def test_s_68_get10_defers_first_semantic_form_then_rejects_its_equivalent() -> None:
    get10 = modules()["get10"]
    intake = modules()["intake"]
    contract_stage = intake.PlanStage(
        key="get10-frontier-v2",
        depth="explore",
        mode="frontier",
        schedule=intake.StageSchedule(intake_seconds=604800),
        allocation_wea=589,
        config=get10.new_epoch_config(),
        expected_output="A valid novel expression that equals 10",
    )
    state = activated_runtime(
        plan_stages=(contract_stage,), total_bank_wea=589, author_balance=700
    )
    validator = (get10.GET10_VALIDATOR_ID, get10.GET10_VALIDATOR_VERSION)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        content="(1+1+1)/.3",
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        verdict="needs_author",
        validator=validator,
    )
    state = accept_work(state, work_id=identifier, revision_id=revision, sequence=3)

    state, duplicate_work, duplicate_revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
        content="3/(.1+.1+.1)",
        snapshot={"model": "m2", "genome": "g2", "runtime": "r2"},
    )
    with pytest.raises(intake.PlanError, match="prior art"):
        accept_work(
            state,
            work_id=duplicate_work,
            revision_id=duplicate_revision,
            sequence=5,
            verdict="needs_author",
            validator=validator,
        )
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 13
