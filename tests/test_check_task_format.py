from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_task_format import validate  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body(
    agent_id: str = "agent0@system",
    reward: str = "5",
    reward_type: str = "Every Good",
    blank_before_agent: bool = True,
    blank_before_reward: bool = True,
    blank_before_reward_type: bool = True,
    extra: str = "",
) -> str:
    """Build a minimal task body with configurable field formatting."""
    sep_agent = "\n" if blank_before_agent else ""
    sep_reward = "\n" if blank_before_reward else ""
    sep_rtype = "\n" if blank_before_reward_type else ""
    return (
        f"### Your Agent ID\n{sep_agent}{agent_id}\n\n"
        f"### Reward (WEA)\n{sep_reward}{reward}\n\n"
        f"### Reward Type\n{sep_rtype}{reward_type}\n"
        + extra
    )


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


def test_validate_accepts_linear_pod_with_slots() -> None:
    body = """### Your Agent ID

agent0@system

### Reward Type

Linear PoD

### Reward (WEA)

15

### Slots (Progressive / Linear only)

5

### Verification Criteria

- [ ] tests pass
"""

    assert validate(body) == []


def test_validate_rejects_linear_pod_without_slots() -> None:
    body = """### Your Agent ID

agent0@system

### Reward Type

Linear PoD

### Reward (WEA)

15
"""

    errors = validate(body)

    # Should have both: missing Slots + missing verification criteria (15 >= 10 WEA)
    slot_errors = [e for e in errors if "Slots" in e]
    assert len(slot_errors) == 1
    assert "Linear PoD" in slot_errors[0]


def test_verification_criteria_required_above_threshold() -> None:
    """Tasks >= 10 WEA without verification criteria should fail."""
    body = """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

20
"""
    errors = validate(body)
    vc_errors = [e for e in errors if "Verification Criteria" in e]
    assert len(vc_errors) == 1


def test_verification_criteria_not_required_below_threshold() -> None:
    """Tasks < 10 WEA without verification criteria should pass."""
    body = """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

5
"""
    errors = validate(body)
    vc_errors = [e for e in errors if "Verification Criteria" in e]
    assert len(vc_errors) == 0


def test_verification_criteria_present_passes() -> None:
    """Tasks >= 10 WEA with verification criteria should pass."""
    body = """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

20

### Verification Criteria

- [ ] tests pass
- [ ] manual check
"""
    errors = validate(body)
    vc_errors = [e for e in errors if "Verification Criteria" in e]
    assert len(vc_errors) == 0


# ---------------------------------------------------------------------------
# New tests — full code path coverage
# ---------------------------------------------------------------------------


# 1. Valid task body — all required fields, correct format
def test_valid_body_all_required_fields_passes() -> None:
    body = _body()
    assert validate(body) == []


# 2. Empty body fails
def test_empty_body_fails() -> None:
    errors = validate("")
    assert len(errors) == 1
    assert "empty" in errors[0].lower()


# 3. Whitespace-only body also treated as empty
def test_whitespace_only_body_fails() -> None:
    errors = validate("   \n\n  \t  ")
    assert len(errors) == 1
    assert "empty" in errors[0].lower()


# 4. Missing ### Your Agent ID fails
def test_missing_agent_id_fails() -> None:
    body = """### Reward (WEA)

5

### Reward Type

Every Good
"""
    errors = validate(body)
    assert any("Your Agent ID" in e and "Missing" in e for e in errors)


# 5. ### Your Agent ID present but NO blank line before value fails (the regression)
def test_agent_id_no_blank_line_before_value_fails() -> None:
    """Regression from issue #259: header without blank line before value must be caught."""
    body = _body(blank_before_agent=False)
    errors = validate(body)
    agent_errors = [e for e in errors if "Your Agent ID" in e]
    assert len(agent_errors) == 1
    assert "blank line" in agent_errors[0] or "empty or missing" in agent_errors[0]


# 6. Agent ID missing @platform suffix fails
def test_agent_id_missing_at_platform_fails() -> None:
    body = _body(agent_id="myagent")
    errors = validate(body)
    assert any("@platform" in e for e in errors)


# 7. Missing ### Reward (WEA) fails
def test_missing_reward_wea_fails() -> None:
    body = """### Your Agent ID

agent0@system

### Reward Type

Every Good
"""
    errors = validate(body)
    assert any("Reward (WEA)" in e and "Missing" in e for e in errors)


# 8. Non-integer reward fails
def test_reward_non_integer_fails() -> None:
    body = _body(reward="ten")
    errors = validate(body)
    assert any("integer" in e.lower() for e in errors)


# 9. Zero reward fails
def test_reward_zero_fails() -> None:
    body = _body(reward="0")
    errors = validate(body)
    assert any("positive integer" in e.lower() for e in errors)


# 10. Negative reward fails
def test_reward_negative_fails() -> None:
    body = _body(reward="-5")
    errors = validate(body)
    assert any("positive integer" in e.lower() for e in errors)


# 11. Missing ### Reward Type fails
def test_missing_reward_type_fails() -> None:
    body = """### Your Agent ID

agent0@system

### Reward (WEA)

5
"""
    errors = validate(body)
    assert any("Reward Type" in e and "Missing" in e for e in errors)


# 12. Unrecognized reward type fails
def test_unrecognized_reward_type_fails() -> None:
    body = _body(reward_type="Random Payout")
    errors = validate(body)
    assert any("not recognized" in e for e in errors)


# 13. [X] Best without Winners X field fails
def test_best_x_without_winners_fails() -> None:
    body = """### Your Agent ID

agent0@system

### Reward (WEA)

8

### Reward Type

[X] Best (ranked winners share budget, X > 1)
"""
    errors = validate(body)
    winner_errors = [e for e in errors if "Winners" in e]
    assert len(winner_errors) == 1
    assert "[X] Best" in winner_errors[0]


# 14. [X] Best with Winners X field passes (no winner error)
def test_best_x_with_winners_passes() -> None:
    body = """### Your Agent ID

agent0@system

### Reward (WEA)

8

### Reward Type

[X] Best (ranked winners share budget, X > 1)

### Winners X ([X] Best only)

3
"""
    errors = validate(body)
    winner_errors = [e for e in errors if "Winners" in e]
    assert len(winner_errors) == 0


# 15. Progressive Every Good without Slots fails
def test_progressive_every_good_without_slots_fails() -> None:
    body = """### Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

Progressive Every Good
"""
    errors = validate(body)
    slot_errors = [e for e in errors if "Slots" in e]
    assert len(slot_errors) == 1
    assert "Progressive Every Good" in slot_errors[0]


# 16. ## Field (wrong header level) fails with specific message
def test_wrong_header_level_agent_id_fails() -> None:
    """## instead of ### produces specific error mentioning `##` and `###`."""
    body = """## Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

Every Good
"""
    errors = validate(body)
    level_errors = [e for e in errors if "Your Agent ID" in e and "##" in e]
    assert len(level_errors) == 1
    assert "###" in level_errors[0]


# 17. ## on Reward (WEA) also caught
def test_wrong_header_level_reward_wea_fails() -> None:
    body = """### Your Agent ID

agent0@system

## Reward (WEA)

5

### Reward Type

Every Good
"""
    errors = validate(body)
    level_errors = [e for e in errors if "Reward (WEA)" in e and "##" in e]
    assert len(level_errors) == 1


# 18. Real-world valid body produced by GitHub Forms (task.yml) passes
def test_real_world_valid_body_passes() -> None:
    """Exact format GitHub Forms generates — every field with blank-line separator."""
    body = """### Your Agent ID

claude-5@claude

### What needs to be done

Add comprehensive tests for the format checker.

### Why (motivation)

No regression coverage exists.

### Expected outcome

All code paths covered.

### Verification Criteria

- [ ] MUST: `pytest tests/test_check_task_format.py -q` exits 0
- [ ] MUST NOT: Modify files outside tests/

### Scope boundaries

tests/ directory only

### Estimated appetite

2 hours

### Reward Type

Every Good (each accepted submission gets paid)

### Reward (WEA)

15

### Slots (Progressive / Linear only)

_No response_

### Winners X ([X] Best only)

_No response_

### Rounds (Duel only)

_No response_

### Skills Needed

Coding (Python)

### Minimum Agents (optional)

_No response_

### Deadline (optional)

_No response_
"""
    assert validate(body) == []


# 19. _No response_ value treated as missing (GitHub Forms default for skipped fields)
def test_no_response_value_treated_as_missing() -> None:
    """GitHub Forms fills skipped fields with '_No response_' — validate() must treat as absent."""
    body = """### Your Agent ID

_No response_

### Reward (WEA)

5

### Reward Type

Every Good
"""
    errors = validate(body)
    # Agent ID is effectively missing — should raise a "found but value is empty" error
    agent_errors = [e for e in errors if "Your Agent ID" in e]
    assert len(agent_errors) == 1
