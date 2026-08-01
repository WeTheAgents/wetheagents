from __future__ import annotations

from .current_bdd_support import activated_runtime, modules


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
