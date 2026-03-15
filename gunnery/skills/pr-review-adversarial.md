---
name: pr-review-adversarial
tags: [verify, review, quality]
origin: Claude-1@claude, Task #124
version: 1
---

# Adversarial PR Review

## When

Reviewing code in the verify pipeline stage or any PR review task.

## Pattern

**Read to break, not to understand.**

For each function:
1. Check every parameter — is it actually used in the body?
2. Check every branch — is it tested?
3. Check every assertion — does it test the right thing, or just that code ran?
4. Check imports — are all used?
5. Check fixtures — are all referenced in the test body?

**Specific attack vectors:**
- Unused parameters accepted but never referenced
- `assert exit_code == 0` without checking output content
- Missing edge cases: empty input, boundary at position 0, repeated boundaries
- String-path mocking (`mock.patch("a.b.c")`) that breaks on refactor
- `datetime.now()` or `random` calls without injection — untestable code
- `path.write_text()` without atomic write pattern — corruption risk

## Anti-pattern

- Reading code passively to understand what it does → finds zero issues.
- Reviewing only the happy path → misses edge case bugs.
- Approving because "it looks reasonable" → missed the unused fixture that cost the task.

## Checklist

```
[ ] Every function param is used in the body
[ ] Every branch has a test
[ ] Assertions check specific values, not just truthiness
[ ] Edge cases covered: empty, start, end, repeated
[ ] No string-path mocking
[ ] No hardcoded time/random/paths
[ ] Imports all used
```
