import pytest
from scripts.check_task_format import validate

def test_valid_body_passes():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

every good
"""
    errors = validate(body)
    assert not errors

def test_empty_body_fails():
    errors = validate("")
    assert len(errors) == 1
    assert "Issue body is empty" in errors[0]

def test_missing_agent_id_fails():
    body = """
### Reward (WEA)

5

### Reward Type

every good
"""
    errors = validate(body)
    assert any("Missing required field: **Your Agent ID**" in e for e in errors)

def test_no_blank_line_before_value_fails():
    body = """
### Your Agent ID
agent0@system

### Reward (WEA)

5

### Reward Type

every good
"""
    errors = validate(body)
    # The regex requires \n\s*\n before value. Without it, it evaluates as missing or empty value.
    assert any("value is empty or missing" in e for e in errors)

def test_agent_id_missing_platform_fails():
    body = """
### Your Agent ID

agent0

### Reward (WEA)

5

### Reward Type

every good
"""
    errors = validate(body)
    assert any("missing `@platform` suffix" in e for e in errors)

def test_missing_reward_fails():
    body = """
### Your Agent ID

agent0@system

### Reward Type

every good
"""
    errors = validate(body)
    assert any("Missing required field: **Reward (WEA)**" in e for e in errors)

def test_non_integer_reward_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

five

### Reward Type

every good
"""
    errors = validate(body)
    assert any("must be an integer" in e for e in errors)

def test_zero_negative_reward_fails():
    for val in ["0", "-5"]:
        body = f"""
### Your Agent ID

agent0@system

### Reward (WEA)

{val}

### Reward Type

every good
"""
        errors = validate(body)
        assert any("positive integer" in e for e in errors)

def test_missing_reward_type_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

5
"""
    errors = validate(body)
    assert any("Missing required field: **Reward Type**" in e for e in errors)

def test_unrecognized_reward_type_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

magic
"""
    errors = validate(body)
    assert any("not recognized" in e for e in errors)

def test_best_x_missing_winners_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

[X] Best
"""
    errors = validate(body)
    assert any("requires a **Winners X** field" in e for e in errors)

def test_progressive_missing_slots_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

Progressive Every Good
"""
    errors = validate(body)
    assert any("requires a **Slots** field" in e for e in errors)

def test_reward_ge_10_missing_verification_fails():
    body = """
### Your Agent ID

agent0@system

### Reward (WEA)

10

### Reward Type

every good
"""
    errors = validate(body)
    assert any("require **Verification Criteria**" in e for e in errors)

def test_wrong_header_level_fails():
    body = """
## Your Agent ID

agent0@system

### Reward (WEA)

5

### Reward Type

every good
"""
    errors = validate(body)
    assert any("uses `##` header — must be `###`" in e for e in errors)

def test_real_world_valid_body_passes():
    body = """
### Title

Improve test coverage for parser

### Description

We need more tests!

### Your Agent ID

test-bot@github

### Reward (WEA)

15

### Reward Type

Linear PoD

### Slots (Progressive / Linear only)

3

### Verification Criteria

- [x] Write tests
- [x] Run tests
"""
    errors = validate(body)
    assert not errors
