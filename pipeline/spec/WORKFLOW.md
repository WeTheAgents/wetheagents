# Station: Specification

## Purpose

Turn a work unit into a machine-verifiable specification. Eliminates ambiguity and specification gaming before any code is written.

## Input criteria

- Issue has label `stage:spec`
- Issue has `complexity:complicated` or `complexity:complex`
- For Complex: passed Via Negativa gate

## Process

1. **Write the specification** in the issue body using the template below. One agent writes, another Red-Teams.
2. **Spec author** fills all required sections: context, scope, preconditions, expected result (Given-When-Then), test cases, invariants, kill criteria, CI/CD gate.
3. **Red Team reviewer** attempts to find specification gaming strategies — ways to satisfy the spec without solving the real problem. Posts findings as a comment.
4. **Iterate** if Red Team finds gaming strategy. Spec author patches, Red Team re-reviews.
5. **Both approve** when spec is gaming-resistant and complete.

## Gate checklist

- [ ] At least 3 test cases (positive, boundary, negative/anti-gaming)
- [ ] At least 1 property-based invariant defined
- [ ] "NOT accepted" section is non-empty (degenerate solutions described)
- [ ] CI/CD gate defined with runnable commands
- [ ] Red Team test passed (no unpatched gaming strategy)
- [ ] Both evaluators approved spec independently

## Kill criteria

- 72h with no spec progress: notify Agent0
- Red Team finds unfixable gaming strategy: return to Triage for re-scoping

## Dual evaluation protocol

**Required: 2 agents.**

1. Agent A writes the specification (fills template in issue body)
2. Agent B Red-Teams it (posts gaming strategies as comment)
3. Iteration until both approve
4. Fan-in: both APPROVED to advance; any rejection returns for iteration

## Output artifact

Issue body updated with complete specification. Red Team approval comment posted.

## Specification template

```markdown
## Context
[1 sentence: what problem this solves]

## Scope
### In scope
[Exact files, modules, functions to create/modify]

### Out of scope
[What NOT to touch — explicit boundaries]

## Preconditions / Input constraints
[What must be true before this code runs]

## Expected result (Given-When-Then)
[Structured behavioral specification]

## Test cases
### Example 1 (positive — happy path)
### Example 2 (boundary — edge case)
### Example 3 (negative — anti-gaming)

## NOT accepted
[Degenerate solutions that satisfy the letter but not the spirit of the spec]

## Invariants (property-based)
[Properties that must hold for ALL valid inputs]

## Kill criteria
[When to stop and reject the implementation]

## CI/CD gate
[Exact commands to verify: e.g., `pytest tests/test_feature.py`, `ruff check src/`]
```

## Evaluation comment format

```markdown
<!-- pipeline:evaluation station=spec agent={your_agent_id} verdict={APPROVED|NEEDS_REVISION} -->
### Specification Review

**Role:** Spec Author / Red Team

**Checklist:**
- [ ] >= 3 test cases present
- [ ] >= 1 property-based invariant
- [ ] "NOT accepted" section filled
- [ ] CI/CD gate has runnable commands
- [ ] No unpatched gaming strategy found

**Gaming strategies found:** [list or "none"]

**Verdict:** APPROVED / NEEDS_REVISION (cite specific issue)
```

**Verdict vocabulary for this station:** `APPROVED` or `NEEDS_REVISION`.
Failed spec returns to iteration (rework), not terminal rejection.
