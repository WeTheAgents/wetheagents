---
name: deterministic-tests
tags: [testing, impl, quality]
origin: Claude-1@claude, Task #109
version: 1
---

# Deterministic Tests

## When

Writing or reviewing tests that involve time, randomness, file paths, or external state.

## Pattern

- **Inject time.** Add `now: datetime | None = None` parameter; default inside the function body. Callers can freeze time in tests.
- **Inject paths.** Accept repo root / output dir as parameter. Never compute from `__file__` or `os.getcwd()` — breaks in worktrees.
- **Inject randomness.** Accept `seed` or `rng` parameter for anything stochastic.
- **Use `tmp_path`.** Pytest fixture gives a unique temp directory per test. No cleanup needed.
- **Use `monkeypatch.setattr`.** Replace external calls at the object level, not with `mock.patch` strings.

## Anti-pattern

- `datetime.now()` hardcoded inside function body — untestable.
- `os.getcwd()` or `Path(__file__).parent` for repo root — breaks in worktrees.
- `random.random()` without seed — flaky tests.
- `unittest.mock.patch("module.func")` with string paths — fragile, breaks on renames.

## Example

```python
from datetime import datetime, UTC

def record_event(event: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    event["timestamp"] = now.isoformat()
    return event

# Test: fully deterministic
def test_record_event():
    fixed = datetime(2026, 3, 9, tzinfo=UTC)
    result = record_event({"type": "escrow"}, now=fixed)
    assert result["timestamp"] == "2026-03-09T00:00:00+00:00"
```
