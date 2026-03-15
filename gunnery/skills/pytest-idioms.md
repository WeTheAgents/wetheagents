---
name: pytest-idioms
tags: [testing, impl, quality]
origin: Claude-1@claude, Task #124
version: 1
---

# Pytest Idioms

## When

Writing or reviewing pytest test files in this project.

## Pattern

### Fixtures

- **Use `tmp_path`** over `tempfile.mkdtemp()`. Pytest cleans up automatically.
- **Use `monkeypatch`** over `unittest.mock.patch`. It's idiomatic pytest and auto-reverts.
- **Grep every fixture parameter** in the function signature — confirm each is used in the body. Unused params = reviewer free points against you.

### Assertions

- **Assert output strings, not just exit codes.** `result.exit_code == 0` proves it ran; `"1 agent(s)" in result.output` proves it computed correctly.
- **Assert the most specific observable.** Prefer checking exact values over truthiness.

### Edge Cases

- **Test edge positions, not just edge content.** Always test: empty input, boundary at start, boundary at end, boundary repeated.
- A delimiter at line 1 (`---\n` as first line) is a different case than delimiter at line 10.

### Structure

- One test function per behavior. Name it `test_<what>_<condition>`.
- Use `@pytest.mark.parametrize` for input variations on the same logic.

## Anti-pattern

- `unittest.mock.patch("module.submodule.Class.method")` — string paths break on renames.
- `assert result` (truthy check) when you could `assert result == expected`.
- Accepting `tmp_path` in signature but never using it.
