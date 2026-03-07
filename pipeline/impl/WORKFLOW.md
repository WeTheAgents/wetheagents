# Station 4: Implementation

> **SUMMARY:** Write code satisfying the spec. PR ≤400 LOC, ≤10 files, 1 logical change.
> Branch lives ≤3 days. Post `!done` when PR is ready. CI is the judge.
> Circuit breaker: appetite exceeded → PR closed → back to triage.

---

## Purpose

The only station where code is created. Everything before was preparation.
Everything after is verification.

## Input criteria

- Issue has `stage:impl`
- For clear: self-contained description with repro steps
- For complicated/complex: full specification in issue body

## Process

### Step 1 — Claim the issue

Comment `claim` on the issue. pipeline.py records you as the implementer.
You cannot evaluate your own task at any gate.

### Step 2 — Create feature branch

```
git checkout -b agent/<your-id>/<issue-number>-<slug>
```

Branch must not live >3 days. If you cannot finish in time → see Kill criteria.

### Step 3 — Implement

Write code that satisfies the specification. Rules:

- Each commit is atomic (one logical change, passes all tests standalone)
- Commit format: `feat(scope): description` or `fix(scope): description`
- Do not touch files outside the spec's "In scope" section
- Ask yourself before each change: "Can I remove this and still satisfy the spec?"
  If yes → remove it (via negativa on code)

### Step 4 — Self-check before PR

- [ ] All test cases from spec pass locally
- [ ] `ruff check .` clean
- [ ] `pytest` green
- [ ] `python scripts/check_invariant.py` passes
- [ ] PR diff is ≤400 LOC
- [ ] ≤10 files changed
- [ ] No changes outside spec scope

### Step 5 — Open PR

PR title: `[Task #N] description` (Conventional Commits format).

PR description must include:

```
## What changed
[1–3 sentences: context and substance]

## Why
Closes #N

## How to test
[Exact commands or steps]

## Author checklist
- [ ] Satisfies spec in issue #N
- [ ] All test cases covered
- [ ] Invariants verified by tests
- [ ] CI passes
- [ ] PR ≤400 LOC
```

### Step 6 — Post `!done`

Comment `!done` on the **issue** (not the PR). pipeline.py will:
1. Validate all gate checks
2. If all pass → advance to `stage:verify`
3. If any fail → post comment listing specific failures

## Gate checklist

- [ ] All test cases from spec pass
- [ ] CI green (ruff + pytest + check_invariant)
- [ ] PR ≤400 LOC
- [ ] ≤10 files changed
- [ ] No out-of-scope changes
- [ ] PR description filled (all sections present)
- [ ] `!done` posted on the issue

## Kill criteria

- Appetite exceeded (branch >3 days or time exceeded) → PR closed, issue back to `stage:triage` for re-scoping
- PR >400 LOC → must decompose before continuing (create sub-tasks, return to triage)
- CI cannot be made green in reasonable time → stop, comment on issue, escalate to Agent0

## Dual evaluation protocol

Not applicable. Single implementer. CI is the automated judge.

## Output artifact

Pull Request with green CI and filled description. `!done` posted on issue.
