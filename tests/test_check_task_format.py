from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_task_format import validate  # noqa: E402


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
