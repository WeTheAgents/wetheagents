# Station 5: Verification

> **SUMMARY:** 3-level check. L1: CI auto (tests, lint, invariant). L2: adversarial code review
> (≤60 min per reviewer). L3: architectural review (complexity:complex only).
> ≥2 reviewers required. Any blocking comment → rework. Rework routing below.

---

## Purpose

Multi-level adversarial check that implementation matches spec and creates no new problems.
Reviewers look for reasons to REJECT, not reasons to approve.

## Input criteria

- Issue has `stage:verify`
- PR is open and linked to the issue
- `!done` was posted by the implementer

## Process

### Level 1 — Automated gate (CI)

pipeline.py checks automatically:

- All tests pass (`pytest`)
- Lint clean (`ruff check .`)
- Invariant intact (`python scripts/check_invariant.py`)
- No coverage regression (if coverage configured)

CI failure at this level → issue returned to `stage:impl` automatically. No human review needed.

### Level 2 — Code review (adversarial)

Two agents assigned as reviewers (pipeline.py round-robin, excluding implementer).

Each reviewer:

1. Read spec in issue body first — understand what the code is *supposed* to do.
   For clear/chaotic tasks (no formal spec): read the issue description and expected outcome instead.
2. Review PR in ≤60 minutes per session
3. Adversarial checklist (evaluate each independently):
   - Gaming possible? PR formally passes tests but doesn't solve real problem?
   - Out-of-scope changes? Files touched that spec says not to touch?
   - New fragility? New dependencies, tech debt, or failure points introduced?
   - Removable code? Can any code be deleted without losing spec-required behavior?
4. Post review comment in required format

**Review comment format:**

```
### Verification Review by {agent_id}

L2 adversarial checklist:
- Gaming: NONE / FOUND — {details}
- Out-of-scope: NONE / FOUND — {details}
- Fragility: NONE / FOUND — {details}
- Removable code: NONE / FOUND — {details}

Blocking comments: YES / NO
- {list blocking issues, or "none"}

Verdict: APPROVED / CHANGES REQUESTED
```

### Level 3 — Architectural review (complexity:complex only)

Required only for tasks that entered via `complexity:complex`.
Performed by Agent0 or operator.

Focus: does this change fit the system architecture? No new design debt?
Post verdict as comment. Format same as L2 but with "Architectural Review" header.

### Step — Aggregate

pipeline.py aggregates all reviews:

- All APPROVED + CI green → advance to `stage:delivery`
- Any CHANGES REQUESTED → rework routing (see below)
- Not enough reviews yet → wait (fan-in incomplete)

## Gate checklist

- [ ] CI green (all auto checks pass)
- [ ] ≥2 reviewer comments posted with required format
- [ ] 0 blocking comments across all reviews
- [ ] Adversarial checklist completed by each reviewer
- [ ] For complexity:complex: architectural review comment posted and APPROVED

## Rework routing

- CI failure → return to `stage:impl`
- Code review: implementation issue → return to `stage:impl`
- Code review: spec issue found → return to `stage:spec`
- Architectural review failure → return to `stage:triage` (re-scope)

Health target: ≤20% of rework goes beyond `stage:impl`. More = spec quality problem.

## Kill criteria

- 48h no reviewer activity → pipeline.py assigns additional reviewer
- Persistent CI failure after 2 impl iterations → escalate to Agent0
- Architectural review rejection → full re-scope at triage (no quick fix)

## Dual evaluation protocol

**YES — required. ≥2 reviewers.**

- Assigned by pipeline.py on `stage:verify` entry (round-robin, excluding implementer)
- Each reviews independently before reading others' comments
- Fan-in: pipeline.py waits for all assigned reviewers before aggregating
- Disagree on blocking: Agent0 casts deciding vote

## Output artifact

All reviewer comments with structured format posted. CI green.
For complex: architectural review approved.
Issue advanced to `stage:delivery` (automatic post-verification).
