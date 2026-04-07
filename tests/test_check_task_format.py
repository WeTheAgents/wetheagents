from __future__ import annotations

import json
import sys
from unittest.mock import mock_open

import pytest

import scripts.check_task_format as check_task_format


def make_body(
    *,
    agent_id: str = "agent0@system",
    reward_type: str = "Winner Take All (single winner, full budget)",
    reward: str = "5",
    verification: str | None = None,
    slots: str | None = None,
    slots_label: str = "Slots (Progressive / Linear only)",
    winners: str | None = None,
    extra_sections: list[tuple[str, str]] | None = None,
) -> str:
    sections: list[tuple[str, str]] = [
        ("Your Agent ID", agent_id),
        ("Reward Type", reward_type),
        ("Reward (WEA)", reward),
    ]
    if slots is not None:
        sections.append((slots_label, slots))
    if winners is not None:
        sections.append(("Winners X ([X] Best only)", winners))
    if verification is not None:
        sections.append(("Verification Criteria", verification))
    if extra_sections:
        sections.extend(extra_sections)
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in sections)


REAL_WORLD_WTA_BODY = """### Your Agent ID

agent0@system

### Task Description

Do something useful.

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

30

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Deadline (optional)

_No response_

### Verification Criteria

- [ ] MUST: `pytest tests/ -q` exits 0
- [ ] MUST: manual review confirms parser accepts the task
"""


REAL_WORLD_BEST_X_BODY = """### Your Agent ID

agent0@system

### Task Description

Best of 3.

### Reward Type

[X] Best (ranked winners share budget, X > 1)

### Reward (WEA)

30

### Slots (Progressive Every Good only)

_No response_

### Winners X ([X] Best only)

3

### Rounds (Duel only)

_No response_

### Skills Needed

Other

### Deadline (optional)

_No response_

### Verification Criteria

- [ ] MUST: ranked winners can be verified from the issue thread
"""


def test_validate_accepts_linear_pod_with_slots() -> None:
    body = make_body(
        reward_type="Linear PoD",
        reward="15",
        slots="5",
        verification="- [ ] tests pass",
    )

    assert check_task_format.validate(body) == []


def test_validate_accepts_progressive_every_good_with_legacy_slots_label() -> None:
    body = make_body(
        reward_type="Progressive Every Good (Fibonacci rewards per slot)",
        reward="12",
        slots="5",
        slots_label="Slots (Progressive Every Good only)",
        verification="- [ ] payout schedule matches slot count",
    )

    assert check_task_format.validate(body) == []


def test_validate_accepts_real_world_winner_take_all_body() -> None:
    assert check_task_format.validate(REAL_WORLD_WTA_BODY) == []


def test_validate_accepts_real_world_best_x_body() -> None:
    assert check_task_format.validate(REAL_WORLD_BEST_X_BODY) == []


def test_validate_rejects_empty_body() -> None:
    assert check_task_format.validate("  \n\t") == ["Issue body is empty."]


def test_validate_treats_none_required_field_value_as_missing() -> None:
    body = make_body(reward_type="none")

    errors = check_task_format.validate(body)

    assert any(
        "Field **Reward Type** found but value is empty or missing." in error
        for error in errors
    )


@pytest.mark.parametrize(
    ("missing_label", "expected_error"),
    [
        ("Your Agent ID", "Missing required field: **Your Agent ID**"),
        ("Reward Type", "Missing required field: **Reward Type**"),
        ("Reward (WEA)", "Missing required field: **Reward (WEA)**"),
    ],
)
def test_validate_rejects_missing_required_field(
    missing_label: str, expected_error: str
) -> None:
    sections = {
        "Your Agent ID": "agent0@system",
        "Reward Type": "Winner Take All (single winner, full budget)",
        "Reward (WEA)": "5",
    }
    sections.pop(missing_label)
    body = "\n\n".join(f"### {label}\n\n{value}" for label, value in sections.items())

    errors = check_task_format.validate(body)

    assert expected_error in errors


@pytest.mark.parametrize("field", ["Your Agent ID", "Reward Type", "Reward (WEA)"])
def test_validate_rejects_missing_blank_line_after_required_header(field: str) -> None:
    bad_field = {
        "Your Agent ID": "### Your Agent ID\nagent0@system",
        "Reward Type": "### Reward Type\nWinner Take All (single winner, full budget)",
        "Reward (WEA)": "### Reward (WEA)\n5",
    }[field]
    body = "\n\n".join(
        [
            bad_field if field == "Your Agent ID" else "### Your Agent ID\n\nagent0@system",
            bad_field if field == "Reward Type" else "### Reward Type\n\nWinner Take All (single winner, full budget)",
            bad_field if field == "Reward (WEA)" else "### Reward (WEA)\n\n5",
        ]
    )

    errors = check_task_format.validate(body)

    assert (
        f"Field **{field}** found but value is empty or missing. Ensure a blank line"
        in "\n".join(errors)
    )


@pytest.mark.parametrize("field", ["Your Agent ID", "Reward Type", "Reward (WEA)"])
def test_validate_rejects_wrong_required_header_level(field: str) -> None:
    wrong_header = {
        "Your Agent ID": "## Your Agent ID\n\nagent0@system",
        "Reward Type": "## Reward Type\n\nWinner Take All (single winner, full budget)",
        "Reward (WEA)": "## Reward (WEA)\n\n5",
    }[field]
    body = "\n\n".join(
        [
            wrong_header if field == "Your Agent ID" else "### Your Agent ID\n\nagent0@system",
            wrong_header if field == "Reward Type" else "### Reward Type\n\nWinner Take All (single winner, full budget)",
            wrong_header if field == "Reward (WEA)" else "### Reward (WEA)\n\n5",
        ]
    )

    errors = check_task_format.validate(body)

    assert any(f"Field **{field}** uses `##` header" in error for error in errors)


@pytest.mark.parametrize("agent_id", ["agent0", "cursor-1", "missing-platform suffix"])
def test_validate_rejects_agent_ids_without_platform_suffix(agent_id: str) -> None:
    errors = check_task_format.validate(make_body(agent_id=agent_id))

    assert any("missing `@platform` suffix" in error for error in errors)


@pytest.mark.parametrize("reward", ["ten", "5.5"])
def test_validate_rejects_non_integer_rewards(reward: str) -> None:
    errors = check_task_format.validate(make_body(reward=reward))

    assert f"Reward must be an integer, got `{reward}`." in errors


@pytest.mark.parametrize("reward", ["0", "-3"])
def test_validate_rejects_non_positive_rewards(reward: str) -> None:
    errors = check_task_format.validate(make_body(reward=reward))

    assert f"Reward must be a positive integer, got `{reward}`." in errors


@pytest.mark.parametrize(
    "reward_type",
    ["Lottery", "Winner-takes-all", "Progressive payouts"],
)
def test_validate_rejects_unrecognized_reward_types(reward_type: str) -> None:
    errors = check_task_format.validate(make_body(reward_type=reward_type))

    assert any(f"Reward Type `{reward_type}` not recognized." in error for error in errors)


def test_validate_requires_slots_for_linear_pod() -> None:
    errors = check_task_format.validate(make_body(reward_type="Linear PoD", reward="15"))

    assert any("Reward Type `Linear PoD` requires a **Slots** field" in error for error in errors)


def test_validate_requires_slots_for_progressive_every_good() -> None:
    errors = check_task_format.validate(
        make_body(
            reward_type="Progressive Every Good (Fibonacci rewards per slot)",
            reward="15",
        )
    )

    assert any(
        "Reward Type `Progressive Every Good` requires a **Slots** field" in error
        for error in errors
    )


def test_validate_requires_winners_x_for_best_x() -> None:
    errors = check_task_format.validate(
        make_body(reward_type="[X] Best (ranked winners share budget, X > 1)", reward="15")
    )

    assert any("Reward Type `[X] Best` requires a **Winners X** field" in error for error in errors)


def test_validate_requires_verification_criteria_for_rewards_at_threshold() -> None:
    errors = check_task_format.validate(make_body(reward="10"))

    assert any("require **Verification Criteria**" in error for error in errors)


def test_validate_treats_no_response_verification_as_missing() -> None:
    errors = check_task_format.validate(make_body(reward="20", verification="_No response_"))

    assert any("require **Verification Criteria**" in error for error in errors)


def test_validate_allows_missing_verification_below_threshold() -> None:
    assert check_task_format.validate(make_body(reward="9")) == []


def test_main_returns_error_when_issue_json_missing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    original_argv = sys.argv[:]
    monkeypatch.delenv("ISSUE_JSON", raising=False)
    sys.argv = ["check_task_format.py"]
    try:
        exit_code = check_task_format.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Error: provide --issue-json or set ISSUE_JSON env var." in captured.out


def test_main_writes_comment_and_error_flag_for_invalid_issue(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = {"number": 348, "body": make_body(reward="20", verification=None)}
    fake_open = mock_open()

    monkeypatch.setenv("ISSUE_JSON", json.dumps(issue))
    monkeypatch.setenv("GITHUB_OUTPUT", "fake-output.txt")
    monkeypatch.setattr(sys, "argv", ["check_task_format.py"])
    monkeypatch.setattr(check_task_format, "open", fake_open, raising=False)

    exit_code = check_task_format.main()
    captured = capsys.readouterr()
    output_text = "".join(call.args[0] for call in fake_open().write.call_args_list)

    assert exit_code == 1
    assert "Task #348: 1 format error(s)" in captured.out
    assert "## Task Format Check — FAIL" in captured.out
    assert "comment<<TASK_FORMAT_EOF" in output_text
    assert "has_errors=true" in output_text


def test_main_writes_success_flag_for_valid_issue(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = {"number": 348, "body": make_body(reward="9")}
    fake_open = mock_open()

    monkeypatch.setenv("ISSUE_JSON", json.dumps(issue))
    monkeypatch.setenv("GITHUB_OUTPUT", "fake-output.txt")
    monkeypatch.setattr(sys, "argv", ["check_task_format.py"])
    monkeypatch.setattr(check_task_format, "open", fake_open, raising=False)

    exit_code = check_task_format.main()
    captured = capsys.readouterr()
    output_text = "".join(call.args[0] for call in fake_open().write.call_args_list)

    assert exit_code == 0
    assert "Task #348: format OK" in captured.out
    assert output_text.strip() == "has_errors=false"
