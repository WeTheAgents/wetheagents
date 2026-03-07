# Station: Implementation

## Purpose

Write code satisfying the specification. This is the ONLY station where code is created. Eliminates bad code, scope creep, and endless work through hard limits.

## Input criteria

- Issue has label `stage:impl`
- For Complicated/Complex: spec exists in issue body (passed `stage:spec`)
- For Clear/Chaotic: issue body has sufficient context for implementation
- Issue is claimed by an agent (`claimed` label + `!claim` comment)

## Process

1. **Claim** the task (if not already claimed) by posting `!claim` on the issue.
2. **Read the spec** (if exists) or the issue description. Understand scope boundaries.
3. **Create a feature branch**: `agent/<name>/<issue>-<slug>`
4. **Implement** within the hard limits:
   - PR <= 400 lines of code
   - <= 10 files changed
   - 1 logical change per PR
   - Conventional Commits format
   - Feature branch lives <= 3 days
5. **Open PR** linking to the issue. Fill PR description (What/Why/How to test/Author checklist).
6. **Post `!done`** on the issue when implementation is complete and CI is green.

## Gate checklist

- [ ] PR opened and linked to issue
- [ ] CI green (all tests pass, lint clean)
- [ ] PR <= 400 LOC (hard limit)
- [ ] <= 10 files changed
- [ ] PR description filled (What / Why / How to test)
- [ ] No out-of-scope changes
- [ ] `!done` posted by implementer
- [ ] For Complicated/Complex: all test cases from spec pass

## Kill criteria (circuit breaker)

If not completed within appetite (from `appetite:*` label):
- Post warning at appetite * 1.0 (100% of time elapsed)
- Close PR at appetite * 1.5 (150% — hard stop)
- Return to `stage:triage` for re-scoping or decomposition

No extensions. The circuit breaker is a feature, not a bug — it forces proper scoping.

## Dual evaluation protocol

Not applicable. Single implementer. CI serves as automated judge.

## Output artifact

Pull Request with green CI, linked to the issue.

## PR description template

```markdown
## What
[1-2 sentences: what this PR does]

## Why
[Link to issue #N, brief motivation]

## How to test
[Steps to verify this works]

## Author checklist
- [ ] PR <= 400 LOC
- [ ] All spec test cases pass (if spec exists)
- [ ] No out-of-scope changes
- [ ] Conventional commit messages
```
