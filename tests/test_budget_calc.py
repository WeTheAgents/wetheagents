from __future__ import annotations

import argparse
import json

import pytest

from scripts.check_task_format import validate_detailed
from wea_cli import cli


def _calc_args(
    reward_type: str,
    *,
    budget: int | None = None,
    per_acceptance: int | None = None,
    acceptances: int | None = None,
    slots: int | None = None,
    winners: int | None = None,
    ranked: int | None = None,
    json_output: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        reward_type=reward_type,
        budget=budget,
        per_acceptance=per_acceptance,
        acceptances=acceptances,
        slots=slots,
        winners=winners,
        ranked=ranked,
        json=json_output,
    )


def _make_body(
    *,
    reward_type: str,
    reward: str,
    per_acceptance: str | None = None,
    slots: str | None = None,
    winners: str | None = None,
    rounds: str | None = None,
) -> str:
    sections: list[tuple[str, str]] = [
        ("Your Agent ID", "agent0@system"),
        ("Reward Type", reward_type),
        ("Reward (WEA)", reward),
        ("Per Acceptance (Every Good only)", per_acceptance or "_No response_"),
        ("Slots (Progressive / Linear only)", slots or "_No response_"),
        ("Winners X ([X] Best only)", winners or "_No response_"),
        ("Rounds (Duel only)", rounds or "_No response_"),
        ("Verification Criteria", "- [ ] MUST: machine check\n- [ ] MUST NOT: regressions"),
    ]
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in sections)


def test_parser_supports_task_calc_budget_subcommand() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["task", "calc-budget", "progressive", "--slots", "5", "--json"])

    assert args.command == "task"
    assert args.task_command == "calc-budget"
    assert args.reward_type == "progressive"
    assert args.slots == 5
    assert args.json is True
    assert args._handler is cli.cmd_task_calc_budget


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            _calc_args("every_good", per_acceptance=5, acceptances=3),
            {"reward_type": "every_good", "budget": 15, "payouts": [5, 5, 5]},
        ),
        (
            _calc_args("progressive", slots=5),
            {"reward_type": "progressive", "budget": 12, "payouts": [1, 1, 2, 3, 5]},
        ),
        (
            _calc_args("linear", slots=5),
            {"reward_type": "linear", "budget": 15, "payouts": [1, 2, 3, 4, 5]},
        ),
        (
            _calc_args("winner_take_all", budget=30),
            {"reward_type": "winner_take_all", "budget": 30, "payouts": [30]},
        ),
        (
            _calc_args("best_x", budget=100, winners=3, ranked=2),
            {"reward_type": "best_x", "budget": 100, "payouts": [70, 30]},
        ),
        (
            _calc_args("duel", budget=33),
            {"reward_type": "duel", "budget": 33, "winner": 29, "runner_up": 4},
        ),
    ],
)
def test_task_calc_budget_covers_all_reward_types(
    args: argparse.Namespace,
    expected: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_task_calc_budget(args)

    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    for key, value in expected.items():
        assert payload[key] == value


def test_task_calc_budget_rejects_ranked_above_winners(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.cmd_task_calc_budget(
        _calc_args("best_x", budget=100, winners=3, ranked=4, json_output=False)
    )

    assert rc == cli.EXIT_DOMAIN_ERROR
    assert "--ranked cannot exceed --winners." in capsys.readouterr().out


def test_task_lint_catches_progressive_budget_mismatch() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="Progressive Every Good (Fibonacci rewards per slot)",
            reward="15",
            slots="5",
        )
    )

    assert any(
        "does not match Progressive Every Good budget for 5 slot(s); expected `12`." in issue.message
        for issue in errors
    )


def test_task_lint_catches_linear_budget_mismatch() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="Linear PoD",
            reward="12",
            slots="5",
        )
    )

    assert any(
        "does not match Linear PoD budget for 5 slot(s); expected `15`." in issue.message
        for issue in errors
    )


def test_task_lint_catches_every_good_budget_dead_end() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="Every Good (each accepted submission gets paid)",
            reward="10",
            per_acceptance="6",
        )
    )

    assert any(
        "Reward `10` is not divisible by Per Acceptance `6`." in issue.message
        for issue in errors
    )


def test_task_lint_rejects_wta_with_winners_field() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="Winner Take All (single winner, full budget)",
            reward="9",
            winners="3",
        )
    )

    assert any(
        "Winner Take All must leave **Winners X** blank." in issue.message for issue in errors
    )


def test_task_lint_rejects_best_x_single_winner_gaming() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="[X] Best (ranked winners share budget, X > 1)",
            reward="9",
            winners="1",
        )
    )

    assert any(
        "Winners X must be in range `2..5` for `[X] Best`." in issue.message
        for issue in errors
    )


def test_task_lint_rejects_irrelevant_slots_field() -> None:
    errors = validate_detailed(
        _make_body(
            reward_type="Winner Take All (single winner, full budget)",
            reward="9",
            slots="5",
        )
    )

    assert any(
        "only applies to `Progressive Every Good` or `Linear PoD` tasks." in issue.message
        for issue in errors
    )
