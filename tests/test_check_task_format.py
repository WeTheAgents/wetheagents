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

    assert len(errors) == 1
    assert "Linear PoD" in errors[0]
    assert "Slots" in errors[0]
